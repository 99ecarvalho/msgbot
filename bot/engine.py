"""Workflow execution engine — processes messages through configurable step pipelines."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Protocol

import structlog

from bot import db
from bot.config import settings
from bot.services import transcriber, tts, llm
from bot.utils import save_audio, convert_wav_to_ogg_opus

log = structlog.get_logger("engine")


# ---- Sent-message dedup cache (prevents echo loops) ----

_sent_cache: OrderedDict[str, float] = OrderedDict()  # key → timestamp
_SENT_CACHE_TTL = 30  # seconds — ignore echoes within this window
_SENT_CACHE_MAX = 500


def _content_key(platform: str, phone: str, text: str) -> str:
    """Build a dedup key from platform + phone + content hash."""
    h = hashlib.sha256(text.encode()).hexdigest()[:16]
    return f"{platform}:{phone}:{h}"


def _record_sent(platform: str, phone: str, text: str) -> None:
    """Record that we just sent this content so we can detect echoes."""
    key = _content_key(platform, phone, text)
    _sent_cache[key] = time.time()
    # Prune old/excess entries
    now = time.time()
    while _sent_cache and (len(_sent_cache) > _SENT_CACHE_MAX or
            next(iter(_sent_cache.values())) < now - _SENT_CACHE_TTL):
        _sent_cache.popitem(last=False)


def _is_echo(platform: str, phone: str, text: str) -> bool:
    """Check if this content was recently sent by us (likely an echo)."""
    if not text:
        return False
    key = _content_key(platform, phone, text)
    ts = _sent_cache.get(key)
    if ts and time.time() - ts < _SENT_CACHE_TTL:
        return True
    return False


# ---- Sender abstraction ----

class MessageSender(Protocol):
    async def send_text(self, text: str) -> None: ...
    async def send_audio(self, audio_bytes: bytes) -> None: ...


class WhatsAppSender:
    def __init__(self, phone: str):
        self.phone = phone

    async def send_text(self, text: str) -> None:
        from bot.services import evolution
        await evolution.send_text(self.phone, text)

    async def send_audio(self, audio_bytes: bytes) -> None:
        from bot.services import evolution
        await evolution.send_audio(self.phone, audio_bytes)


class TelegramSender:
    def __init__(self, message):
        self._msg = message

    async def send_text(self, text: str) -> None:
        await self._msg.reply_text(text)

    async def send_audio(self, audio_bytes: bytes) -> None:
        import io
        await self._msg.reply_voice(io.BytesIO(audio_bytes))


# ---- Execution context ----

@dataclass
class WorkflowContext:
    """Carries state through the workflow pipeline."""
    chat: dict
    platform: str
    phone: str
    push_name: str
    sender_phone: str
    sender: MessageSender
    audio_bytes: bytes | None = None
    audio_path: str = ""
    original_text: str = ""
    msg_type: str = "text"           # 'voice' or 'text'
    is_forwarded: bool = False
    is_ptt: bool = False
    device: str = ""                 # android | ios | web | unknown
    # Pipeline state — mutated by steps
    transcription: str = ""
    current_text: str = ""
    llm_responses: list[str] = field(default_factory=list)
    message_id: int | None = None    # set by 'save' step
    run_id: str = ""                 # unique per workflow execution
    workflow_name: str = ""


def _get_response_mode(chat: dict) -> str:
    return chat.get("response_mode") or settings.response_mode


def _get_system_prompt(chat: dict) -> str:
    return chat.get("system_prompt") or settings.default_system_prompt


# ---- Condition evaluator ----

def _check_condition(condition: str, ctx: WorkflowContext) -> bool:
    """Return True if the step should execute given the condition."""
    if not condition:
        return True
    if condition == "has_audio":
        return ctx.audio_bytes is not None and len(ctx.audio_bytes) > 0
    if condition == "mode_voice":
        return _get_response_mode(ctx.chat) == "voice"
    if condition == "mode_auto_voice":
        mode = _get_response_mode(ctx.chat)
        return mode == "voice" or (mode == "auto" and ctx.is_ptt)
    if condition == "has_text":
        return bool(ctx.current_text)
    return True  # unknown condition → run


# ---- Step handlers ----

async def _step_transcribe(ctx: WorkflowContext, config: dict) -> tuple[str, str]:
    """Transcribe audio to text. Returns (input_summary, output_summary)."""
    if not ctx.audio_bytes:
        return "(no audio)", "(skipped — no audio)"

    language = config.get("language")
    result = await transcriber.transcribe(ctx.audio_bytes, filename="audio.ogg", language=language)
    text = result.get("text", "")
    ctx.transcription = text
    ctx.current_text = text

    lang_detected = result.get("language", "")
    duration = result.get("audio_duration_sec", 0)

    return (
        f"audio {len(ctx.audio_bytes)} bytes",
        f"{len(text)} chars, lang={lang_detected}, dur={duration:.1f}s",
    )


async def _step_llm(ctx: WorkflowContext, config: dict) -> tuple[str, str]:
    """Process current_text through LLM. Empty prompt = use chat/global default."""
    prompt = config.get("prompt", "")
    if not prompt:
        prompt = _get_system_prompt(ctx.chat)

    input_text = ctx.current_text
    if not input_text:
        return "(no text)", "(skipped — no input text)"

    # Use forwarded handler if message is forwarded
    if ctx.is_forwarded:
        response = await llm.process_forwarded_audio(input_text, prompt)
    else:
        response = await llm.process_voice_message(input_text, prompt)

    ctx.current_text = response
    ctx.llm_responses.append(response)

    return (
        f"{len(input_text)} chars",
        f"{len(response)} chars",
    )


async def _step_reply_text(ctx: WorkflowContext, config: dict) -> tuple[str, str]:
    """Send current_text as a text reply."""
    text = ctx.current_text
    if not text:
        return "(no text)", "(skipped — empty)"

    template = config.get("template", "")
    if template:
        text = template.replace("{text}", text)
        text = text.replace("{transcription}", ctx.transcription)

    await ctx.sender.send_text(text)
    _record_sent(ctx.platform, ctx.phone, text)
    return f"{len(ctx.current_text)} chars", f"sent {len(text)} chars"


async def _step_reply_audio(ctx: WorkflowContext, config: dict) -> tuple[str, str]:
    """TTS current_text and send as audio reply."""
    text = ctx.current_text
    if not text:
        return "(no text)", "(skipped — empty)"

    wav_bytes = await tts.synthesize(text)
    ogg_bytes = await convert_wav_to_ogg_opus(wav_bytes)
    out_path = await save_audio(ctx.phone, "out", ogg_bytes, "ogg")

    await ctx.sender.send_audio(ogg_bytes)

    # Store for the save step
    ctx.audio_path = out_path
    return f"{len(text)} chars", f"audio {len(ogg_bytes)} bytes"


async def _step_save(ctx: WorkflowContext, config: dict) -> tuple[str, str]:
    """Save message to database with accumulated context."""
    msg_id = await db.save_message(
        ctx.chat["id"],
        direction="in",
        msg_type=ctx.msg_type,
        content_text=ctx.original_text,
        audio_path=ctx.audio_path if ctx.msg_type == "voice" else "",
        transcription=ctx.transcription,
        llm_response="\n---\n".join(ctx.llm_responses) if ctx.llm_responses else "",
        sender_name=ctx.push_name,
        sender_phone=ctx.sender_phone,
        device=ctx.device,
    )
    ctx.message_id = msg_id

    # Also save outgoing if we have LLM responses
    if ctx.llm_responses:
        await db.save_message(
            ctx.chat["id"],
            direction="out",
            msg_type="voice" if ctx.audio_path else "text",
            content_text=ctx.current_text,
            audio_path=ctx.audio_path,
        )

    return "saving context", f"message_id={msg_id}"


_STEP_HANDLERS = {
    "transcribe": _step_transcribe,
    "llm": _step_llm,
    "reply_text": _step_reply_text,
    "reply_audio": _step_reply_audio,
    "save": _step_save,
}


# ---- Main execution ----

async def execute_workflow(ctx: WorkflowContext, workflow: dict, steps: list[dict]) -> None:
    """Execute a single workflow's steps in order."""
    ctx.run_id = str(uuid.uuid4())[:12]
    ctx.workflow_name = workflow["name"]
    wf_id = workflow["id"]

    await db.save_log(
        "info",
        f"▶ Starting workflow '{workflow['name']}' ({len(steps)} steps) for {ctx.push_name or ctx.phone}",
        source="workflow",
    )

    for step in steps:
        if not step.get("enabled", True):
            continue

        step_type = step["step_type"]
        step_id = step["id"]
        step_order = step["step_order"]
        label = step.get("label", step_type)

        config = {}
        try:
            config = json.loads(step.get("config_json", "{}") or "{}")
        except json.JSONDecodeError:
            config = {}

        # Check condition
        condition = step.get("condition", "")
        if condition and not _check_condition(condition, ctx):
            await db.save_workflow_log(
                ctx.run_id, ctx.message_id, wf_id,
                step_id, step_order, step_type,
                input_summary="", output_summary=f"condition '{condition}' not met",
                status="skipped",
            )
            await db.save_log(
                "debug",
                f"  ⏭ Step {step_order} '{label}' skipped (condition: {condition})",
                source="workflow",
            )
            continue

        # Execute step
        handler = _STEP_HANDLERS.get(step_type)
        if not handler:
            await db.save_workflow_log(
                ctx.run_id, ctx.message_id, wf_id,
                step_id, step_order, step_type,
                status="error", error_text=f"Unknown step type: {step_type}",
            )
            log.warning("unknown_step_type", step_type=step_type)
            continue

        start = time.time()
        try:
            input_summary, output_summary = await handler(ctx, config)
            elapsed = int((time.time() - start) * 1000)

            await db.save_workflow_log(
                ctx.run_id, ctx.message_id, wf_id,
                step_id, step_order, step_type,
                input_summary=input_summary, output_summary=output_summary,
                status="ok", elapsed_ms=elapsed,
            )
            await db.save_log(
                "info",
                f"  ✓ Step {step_order} '{label}' OK ({elapsed}ms) — {output_summary}",
                source="workflow",
            )
        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            error_msg = str(e)[:500]

            await db.save_workflow_log(
                ctx.run_id, ctx.message_id, wf_id,
                step_id, step_order, step_type,
                input_summary="", output_summary="",
                status="error", error_text=error_msg, elapsed_ms=elapsed,
            )
            await db.save_log(
                "error",
                f"  ✗ Step {step_order} '{label}' FAILED ({elapsed}ms): {error_msg}",
                source="workflow",
            )
            log.error("step_failed", step=label, error=error_msg, workflow=workflow["name"])
            # Don't break — continue to next step (some steps may be independent)
            # But if transcribe or LLM failed, downstream steps will have empty text
            continue

    await db.save_log(
        "info",
        f"✔ Workflow '{workflow['name']}' completed for {ctx.push_name or ctx.phone}",
        source="workflow",
    )


async def process_message(
    chat: dict,
    platform: str,
    phone: str,
    push_name: str,
    sender_phone: str,
    sender: MessageSender,
    whitelist_entry: dict,
    audio_bytes: bytes | None = None,
    audio_path: str = "",
    text: str = "",
    msg_type: str = "text",
    is_forwarded: bool = False,
    is_ptt: bool = False,
    device: str = "",
) -> None:
    """Top-level: find workflows for the whitelist entry, execute them."""
    # ---- Echo / loop guard ----
    # If the incoming text matches something we recently sent, skip it
    if text and _is_echo(platform, phone, text):
        log.info("echo_detected", phone=phone, text=text[:60])
        await db.save_log(
            "debug",
            f"⏩ Echo detected for {push_name or phone} — skipping (text matches recent reply)",
            source="workflow",
        )
        return

    wl_id = whitelist_entry.get("id", 0)

    # Log whitelist match
    await db.save_log(
        "info",
        f"✅ Whitelist match for {push_name or phone} — entry #{wl_id} "
        f"({whitelist_entry.get('filter_type', '?')}={whitelist_entry.get('value', '?')})",
        source=platform,
    )

    # Get workflows linked to this whitelist entry
    workflows = []
    if wl_id > 0:
        workflows = await db.get_workflows_for_whitelist(wl_id)

    # If no workflows linked, use default (first enabled workflow)
    if not workflows:
        all_wf = await db.get_all_workflows()
        enabled = [w for w in all_wf if w.get("enabled")]
        if enabled:
            workflows = [enabled[0]]  # Use first enabled as default

    if not workflows:
        await db.save_log(
            "warning",
            f"No workflows available for {push_name or phone} — message will only be saved",
            source=platform,
        )
        # Still save the message even without workflows
        await db.save_message(
            chat["id"], "in", msg_type,
            content_text=text, audio_path=audio_path,
            sender_name=push_name, sender_phone=sender_phone,
            device=device,
        )
        return

    for workflow in workflows:
        steps = await db.get_workflow_steps(workflow["id"])
        if not steps:
            await db.save_log("warning", f"Workflow '{workflow['name']}' has no steps — skipping", source="workflow")
            continue

        ctx = WorkflowContext(
            chat=chat,
            platform=platform,
            phone=phone,
            push_name=push_name,
            sender_phone=sender_phone,
            sender=sender,
            audio_bytes=audio_bytes,
            audio_path=audio_path,
            original_text=text,
            msg_type=msg_type,
            is_forwarded=is_forwarded,
            is_ptt=is_ptt,
            device=device,
            current_text=text,
        )

        try:
            await execute_workflow(ctx, workflow, steps)
        except Exception as e:
            log.error("workflow_execution_failed", workflow=workflow["name"], error=str(e))
            await db.save_log(
                "error",
                f"Workflow '{workflow['name']}' failed: {e}",
                source="workflow",
            )

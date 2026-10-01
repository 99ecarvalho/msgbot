# Security Policy

Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>

MsgBot handles private messages, voice recordings, and the credentials of a
linked WhatsApp account, so please read this page before you deploy it, and
follow it if you find a vulnerability.

- [Supported versions](#supported-versions)
- [Reporting a vulnerability](#reporting-a-vulnerability)
- [Deploying safely](#deploying-safely)
- [Known limitations](#known-limitations)

## Supported versions

MsgBot has no releases yet. Security fixes are made on the `main` branch
only; please update to the latest commit before reporting.

## Reporting a vulnerability

**Please don't open a public issue for a security problem.** Report it
privately instead:

- through GitHub's [private vulnerability reporting](https://github.com/99ecarvalho/msgbot/security/advisories/new),
  or
- by email to Eduardo Correia <ecorreia@apliant.com.br>, with `[msgbot security]`
  in the subject.

Include:

- what an attacker can do, and what access they need (network access to the
  web UI, the ability to message the bot, etc.);
- the steps or a proof of concept to reproduce it;
- the commit hash you tested;
- any suggestion for a fix.

Don't include real phone numbers, messages, or keys; use test data.

You can expect an acknowledgement within 7 days. Once the problem is
confirmed, a fix is prepared on `main`, and you will be credited in the
advisory unless you prefer otherwise. Please give a reasonable time to fix
the problem before disclosing it publicly.

The patched Evolution API, the transcriber, and the TTS service come from
other projects. Report a problem in them to their maintainers, unless it is
caused by how MsgBot configures or patches them.

## Deploying safely

MsgBot is meant to be run by one person or a small trusted team, on a
private network. If you expose it to the internet:

1. **Never expose the web UI without authentication.** Put a reverse proxy
   with TLS and a login (for example Caddy or nginx with basic auth, or an
   identity-aware proxy) in front of port `8088`, and only let
   `/webhook/telegram` through without it. [QUICKSTART.md](QUICKSTART.md)
   has an example.
2. **Don't publish the other ports.** Evolution API (`8085`), the transcriber
   (`8001`), and TTS (`8002`) don't need to be reachable from outside. Bind
   them to `127.0.0.1` in `docker-compose.yml`, or block them with your cloud
   provider's firewall. Docker's published ports bypass `ufw`.
3. **Use strong secrets.** Generate `EVOLUTION_API_KEY` with
   `openssl rand -hex 32`. Keep `.env` out of git (it is ignored) and
   readable only by you (`chmod 600 .env`).
4. **Change the PostgreSQL password** in `docker-compose.yml` if the database
   could ever be reachable from another host.
5. **Whitelist carefully.** Each whitelisted chat can make the bot call your
   LLM, transcriber, and TTS, which costs money and compute.
6. **Protect the data.** The `bot_data` volume holds every message, audio
   file, transcription, and LLM exchange; `evolution_data` and
   `postgres_data` hold the WhatsApp session. Anyone with access to them can
   read your conversations or take over the linked WhatsApp session. Back
   them up and dispose of them as you would the phone itself.
7. **Mind the people you talk to.** Messages from everyone who writes to the
   linked account are stored, and whitelisted messages are sent to Azure for
   processing. Make sure that is acceptable under the privacy laws that apply
   to you and to them.

## Known limitations

These are known gaps in the current version. Contributions that close them
are welcome.

| Area | Limitation | Mitigation |
| ---- | ---------- | ---------- |
| Web UI | No authentication or CSRF protection. Anyone who reaches it can read messages, send messages from your account, change prompts, and unlink WhatsApp | Keep it private, or behind an authenticating proxy |
| WhatsApp webhook | `/webhook/whatsapp` does not verify that requests come from Evolution API, so anyone who reaches it can inject fake messages | Don't expose the bot's port; only Evolution API needs to reach it, over the Docker network |
| Telegram webhook | The webhook is registered without a `secret_token`, so requests to `/webhook/telegram` are not verified | Treat the webhook URL as public; rely on the whitelist to limit what a forged update can trigger |
| LLM | Message content is sent to the LLM as-is and the reply goes back to the chat, so a sender can try prompt injection against your system prompt | Don't put secrets in system prompts; the LLM has no tools or access to other data |
| Storage | The SQLite database and audio files are not encrypted at rest | Use disk encryption on the host |

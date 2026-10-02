# Contributing to MsgBot

Thanks for your interest in MsgBot! Bug reports, documentation fixes, and
code are all welcome. This guide explains how to get a change merged with as
little back-and-forth as possible.

- [Ways to contribute](#ways-to-contribute)
- [Reporting bugs](#reporting-bugs)
- [Development setup](#development-setup)
- [Making a change](#making-a-change)
- [Coding style](#coding-style)
- [Commit messages](#commit-messages)
- [Pull requests](#pull-requests)
- [Licensing of contributions](#licensing-of-contributions)

## Ways to contribute

- **Report a bug** or unexpected behavior. See [Reporting bugs](#reporting-bugs).
- **Improve the documentation.** If something was unclear or wrong, a fix is
  welcome: [README.md](README.md), [QUICKSTART.md](QUICKSTART.md), and the
  Evolution API notes in [doc/evolution/](doc/evolution/README.md).
- **Add workflow steps or conditions.** New step types belong in
  `bot/engine.py`; see [Making a change](#making-a-change).
- **Support more providers.** Other LLM, transcription, or TTS backends are
  welcome, as long as the existing ones keep working.
- **Test on your setup.** Reports about other GPUs, hosts, Evolution API
  versions, or WhatsApp account types help a lot.

Security problems are the exception: please **don't** open a public issue,
and follow [SECURITY.md](SECURITY.md) instead.

The transcriber and TTS services live in their own repositories,
[ai-transcriber](https://github.com/99ecarvalho/ai-transcriber) and [ai-tts](https://github.com/99ecarvalho/ai-tts), included here as git submodules in `external/`. Bugs and
changes in those services belong in their repositories; this one only
records which version of each it uses.

## Reporting bugs

Search the [existing issues](https://github.com/99ecarvalho/msgbot/issues)
first. If your bug is new, [open an issue](https://github.com/99ecarvalho/msgbot/issues/new)
and include:

- the commit hash you used;
- the platform (WhatsApp or Telegram), and for WhatsApp whether it happened in
  a direct message or a group;
- the workflow and its steps, if the problem is in a workflow;
- what you expected to happen and what happened instead;
- the relevant lines from `docker compose logs bot` (and `evolution-api`,
  `transcriber`, or `tts` if they are involved).

**Remove personal data before posting**: phone numbers, WhatsApp IDs
(`...@s.whatsapp.net`, `...@lid`, `...@g.us`), contact names, message text,
API keys, and tokens. Replace them with obviously fake values such as
`5511900000001`.

A minimal way to reproduce the problem is the most valuable thing you can
provide.

## Development setup

MsgBot is a Python 3.11 [FastAPI](https://fastapi.tiangolo.com/) application
with server-rendered [Jinja2](https://jinja.palletsprojects.com/) pages and
[htmx](https://htmx.org/). Follow [QUICKSTART.md](QUICKSTART.md) to get the
whole stack running in Docker first.

To run the bot from your checkout, keep the other services in Docker:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

docker compose up -d evolution-api transcriber tts
EVOLUTION_API_URL=http://localhost:8085 \
TRANSCRIBER_URL=http://localhost:8001 \
TTS_URL=http://localhost:8002 \
DATA_DIR=./data \
python -m bot.main                        # http://localhost:8000
```

You also need `ffmpeg` on your `PATH` for audio conversion. For WhatsApp
webhooks to reach a bot running outside Docker, set `BOT_URL` to an address
the `evolution-api` container can reach, such as
`http://host.docker.internal:8000` (on Linux, add
`extra_hosts: ["host.docker.internal:host-gateway"]` to the `evolution-api`
service).

The code is organized as follows:

| Path | Purpose |
| ---- | ------- |
| `bot/main.py` | FastAPI app, webhook endpoints, startup (database, Evolution API instance, Telegram webhook) |
| `bot/config.py` | Settings from environment variables |
| `bot/db.py` | SQLite schema, migrations, queries, and the example workflows |
| `bot/engine.py` | Workflow engine: step handlers, conditions, execution, and run logs |
| `bot/handlers/` | Turn Telegram updates and Evolution API webhooks into workflow runs |
| `bot/services/` | HTTP clients for Evolution API, the LLM, the transcriber, and TTS |
| `bot/web/` | Web UI routes and WebSocket endpoints |
| `bot/templates/`, `bot/static/` | Pages, styles, and scripts |
| `docker/evolution/` | Evolution API image and the LID patches applied to it |
| `external/` | Git submodules, don't edit them here: the transcriber and TTS services, and the Baileys and Evolution API forks with the source of the LID patches (see [doc/evolution/](doc/evolution/README.md#lid-patches)) |

### Testing your change

The automated tests are in `tests/` (pytest); more are welcome, especially
for the workflow engine. Before opening a pull request:

1. Install the development requirements
   (`pip install -r requirements-dev.txt`) and run `python -m pytest`.
   Add a test for a bug fix or new behavior where you can.
2. Rebuild and start the stack (`docker compose build bot && docker compose
   up -d bot`) and check `docker compose logs bot` for errors.
3. Exercise what you changed from a real chat: a text message and a voice
   note, in a direct message and, if relevant, in a group. Check the
   **Logs**, **LLM Logs**, and the workflow's run history.
4. Open every web UI page you touched and check the browser's developer
   console for errors.
5. If you changed the database schema, start once with an existing database
   and once with an empty `DATA_DIR`, and check that both work.

Describe what you tested in the pull request.

## Making a change

1. For anything larger than a small fix, **open an issue first** to discuss
   the approach. This avoids wasted work on changes that don't fit the
   project.
2. Fork the repository and create a branch from `main`:
   `git checkout -b fix/group-replies`.
3. Keep each pull request focused on one topic. Unrelated clean-ups belong in
   a separate pull request.
4. Update the documentation in the same pull request when you change
   behavior: the README, QUICKSTART, and `.env.example` for new settings.

Some common changes:

- **A new setting**: add it to `Settings` in `bot/config.py`, to
  `.env.example`, and to the configuration table in the README.
- **A new workflow step**: write an `async def _step_<name>(ctx, config)`
  that returns `(input_summary, output_summary)`, register it in
  `_STEP_HANDLERS` in `bot/engine.py`, make it selectable in
  `bot/templates/workflow_detail.html`, and document it in the README.
- **A schema change**: databases created by earlier versions must keep
  working. Add the column or table in `bot/db.py` with a migration that runs
  on startup, like the existing `ALTER TABLE` migrations.

## Coding style

Follow the style of the surrounding code:

- Python 3.11, 4-space indentation, double quotes, type hints on function
  signatures, and `from __future__ import annotations` at the top of each
  module.
- `snake_case` for functions and variables, `PascalCase` for classes, and
  `UPPER_CASE` for constants.
- Use `async` I/O throughout: `httpx.AsyncClient` for HTTP and `aiosqlite`
  for the database. Don't block the event loop.
- Log with `structlog` (`log = structlog.get_logger("<module>")`) using an
  event name and keyword fields, e.g. `log.info("tts_complete", text_len=...)`.
  Never log API keys or tokens.
- Use `?` placeholders for every value in SQL. Column and table names in
  dynamic queries must come from code, never from a request.
- Read configuration from `settings`, not from `os.environ`.
- Keep pages server-rendered with Jinja2 and htmx; add JavaScript only when
  htmx can't do the job. Jinja escapes values by default: don't use `| safe`
  on data that comes from users or chats, and in JavaScript insert such data
  with `textContent`, not `innerHTML`.
- Comment the *why* of anything non-obvious, as in
  `docker/evolution/apply-patches.js`.

New source files start with this header (adapt the comment syntax to the
file type; templates use a Jinja `{# ... #}` comment):

```python
# Copyright (c) 2026 Your Name <you@example.com>
#
# This file is part of MsgBot. It is free software, licensed under the GNU
# Lesser General Public License v3.0 or later. See COPYING.LESSER and
# COPYING for details.
#
# SPDX-License-Identifier: LGPL-3.0-or-later
```

When you make a substantial change to an existing file, you may add your own
copyright line below the existing one.

## Commit messages

The project uses [Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>(<optional scope>): <short summary in the imperative>

<optional body explaining what changed and why>
```

Common types are `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `build`,
and `chore`. For example:

```text
fix(whatsapp): reply to @lid contacts with the full JID

Bare LID numbers were sent as phone numbers, so Evolution API rejected
every reply to a contact that had migrated to LID.
```

Keep the summary line under about 72 characters. Make each commit leave the
application working.

## Pull requests

Before you open a pull request, check that:

- [ ] `python -m pytest` passes and the bot starts without errors;
- [ ] you tested the change from a real chat, as described above;
- [ ] there are no new errors in the browser console;
- [ ] documentation and `.env.example` reflect any change in behavior;
- [ ] no secrets, phone numbers, or other personal data are in the code,
      the docs, or the commits;
- [ ] new files carry the copyright and SPDX header;
- [ ] commits follow the commit message convention.

A maintainer will review the pull request. You may be asked for changes, so
please don't take that as a rejection. It is how the code stays maintainable.

## Licensing of contributions

MsgBot is licensed under the GNU Lesser General Public License v3.0 or later
(see [COPYING.LESSER](COPYING.LESSER) and [COPYING](COPYING)). By submitting a
contribution, you agree that it is licensed under the same terms, and you
confirm that you have the right to submit it.

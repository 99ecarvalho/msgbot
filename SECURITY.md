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

Evolution API comes from another project; report a problem in it to its
maintainers, unless it is caused by how MsgBot configures or patches it. The
transcriber ([ai-transcriber](https://github.com/99ecarvalho/ai-transcriber)) and TTS service ([ai-tts](https://github.com/99ecarvalho/ai-tts)) have their own repositories and
security policies; report problems in them there.

## Deploying safely

MsgBot is meant to be run by one person or a small trusted team, on a
private network. If you expose it to the internet:

1. **Use TLS and a strong web UI password.** The bot serves plain HTTP, so
   put a reverse proxy with TLS (for example Caddy or nginx) in front of port
   `8088`; [QUICKSTART.md](QUICKSTART.md) has an example. Set a long, random
   `WEB_PASSWORD`: `./run.sh` generates one if it is missing.
2. **Don't publish the other ports.** Evolution API (`8085`), the transcriber
   (`8001`), and TTS (`8002`) don't need to be reachable from outside. Bind
   them to `127.0.0.1` in `docker-compose.yml`, or block them with your cloud
   provider's firewall. Docker's published ports bypass `ufw`.
3. **Use strong secrets.** Generate `EVOLUTION_API_KEY` with
   `openssl rand -hex 32`. The webhook secrets are derived from it and from
   `TELEGRAM_BOT_TOKEN`, so changing either changes them too. Keep `.env` out of git (it is ignored) and
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

## How the bot protects itself

- **Web UI login:** every page, htmx endpoint, audio file, and WebSocket
  needs a session, created by logging in with `WEB_USERNAME` and
  `WEB_PASSWORD`. The session cookie is signed, `HttpOnly`, and
  `SameSite=Strict`, lasts 7 days, and stops working when the password
  changes. Failed logins are logged and slowed down. Without
  `WEB_PASSWORD`, the bot generates a random password at startup and logs it.
- **Cross-site requests:** requests that change something, and WebSocket
  connections, are rejected when the browser says they come from another
  site (`Sec-Fetch-Site` or `Origin`).
- **Webhooks:** Telegram's webhook is registered with a `secret_token`, and
  Evolution API is configured to send an `X-MsgBot-Webhook-Token` header.
  Webhook requests without the right secret get `403`.

## Known limitations

These are known gaps in the current version. Contributions that close them
are welcome.

| Area | Limitation | Mitigation |
| ---- | ---------- | ---------- |
| Web UI | One shared login, with no user accounts, roles, or lockout after repeated failures | Use a strong `WEB_PASSWORD`; add an identity-aware proxy if several people need access |
| Transport | The bot serves plain HTTP | Put a reverse proxy with TLS in front of it |
| Evolution API | Its port (`8085`) is published on the host and protected only by `EVOLUTION_API_KEY` | Bind it to `127.0.0.1` or firewall it |
| LLM | Message content is sent to the LLM as-is and the reply goes back to the chat, so a sender can try prompt injection against your system prompt | Don't put secrets in system prompts; the LLM has no tools or access to other data |
| Storage | The SQLite database and audio files are not encrypted at rest | Use disk encryption on the host |

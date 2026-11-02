<img src="docs/banner.svg" alt="opencode-deepseek-web" width="100%">

Run a **free DeepSeek web account** as an OpenAI-compatible backend, then point
[opencode](https://opencode.ai) at it.

The DeepSeek web chat costs nothing. The metered platform API costs money. This
project bridges the first one into the shape the second one has, keeps the whole
thing on loopback, and paces every upstream request so an autonomous coding
agent does not fire a turn every 200 ms and get the account flagged.

Two files do the work:

| file | job |
|---|---|
| `relay/extract.py` | reads the login token out of a dedicated Firefox profile |
| `relay/relay2.py` | serves `POST /v1/chat/completions` on `127.0.0.1:20232` |

---

## Contents

- [How it works](#how-it-works)
- [The tag contract](#the-tag-contract)
- [Requirements](#requirements)
- [Install](#install)
  - [Step 1 — dedicated Firefox profile](#step-1--dedicated-firefox-profile)
  - [Step 2 — extract the session](#step-2--extract-the-session)
  - [Step 3 — run the relay](#step-3--run-the-relay)
  - [Step 4 — wire up opencode](#step-4--wire-up-opencode)
- [Models](#models)
- [Environment variables](#environment-variables)
- [Limits](#limits)
- [Troubleshooting](#troubleshooting)
- [Credits](#credits)
- [License](#license)

---

## How it works

<img src="docs/how-it-works.svg" alt="Request flow from opencode through the relay to chat.deepseek.com and back" width="100%">

opencode speaks OpenAI. The relay translates:

- **in** — the harness's `system` prompt and JSON tool schemas become a plain
  text tag contract (below), plus a short reminder every turn so long sessions
  do not drift into prose.
- **upstream** — the prompt is sent to `chat.deepseek.com` with the browser's own
  TLS/HTTP2 fingerprint, a solved proof-of-work header, and the chat session id
  from the previous turn, so the account sees one continuous conversation.
- **out** — the reply is parsed back into assistant text or `tool_calls`, and
  streamed to the harness as SSE deltas word by word.

Everything binds to loopback. No port forwarding, no public listener.

---

## The tag contract

<img src="docs/tag-contract.svg" alt="Text tag protocol between harness and model" width="100%">

DeepSeek's web endpoint has no tool-calling API, so tools are described in text
and read back out of text. Three reply dialects are tolerated, because the web
client is not consistent about which one it produces:

```
<bash>{"command": "ls -la"}</bash>          plain tags
<DSML｜｜tool▁calls｜｜> …                    DeepSeek markup
< calls> …                                  reasoning model, bare
```

Unterminated tags are auto-closed before parsing, stray separators and broken
closers are swept, and fenced code blocks are left alone — so a model that
forgot to close a tag still yields a usable `{"cmd": "ls -la"}` instead of a
turn of garbage.

---

## Requirements

- Windows, macOS, or Linux
- Python 3.10+
- **Firefox** (real, installed — the extractor drives it)
- [geckodriver](https://github.com/mozilla/geckodriver/releases) on `PATH`
- A free [chat.deepseek.com](https://chat.deepseek.com) account, logged in once

---

## Install

```bash
git clone https://github.com/Nbill27/opencode-deepseek-web.git
cd opencode-deepseek-web
pip install -r requirements.txt
```

`requirements.txt` pulls `deepseek-pow` (proof-of-work), `wasmtime` (its
runtime), `curl_cffi` (browser TLS fingerprint), and `selenium` (token
extraction).

### Step 1 — dedicated Firefox profile

The relay needs a login token. It reads it from a Firefox profile **you created
for this**, never your daily one.

1. Close every Firefox window.
2. Create a fresh profile and start it:

   ```bash
   firefox -profile ./ff-profile -no-remote
   ```

   Windows (default install path):

   ```powershell
   & "C:\Program Files\Mozilla Firefox\firefox.exe" -profile .\ff-profile -no-remote
   ```

3. In that window, go to <https://chat.deepseek.com> and sign in.
4. Send one message so the session actually exists.
5. **Close that Firefox completely.** The token lives in memory until it is
   flushed to disk, and the extractor will read a stale one if the window is
   still open.

If your Firefox lives somewhere unusual, or geckodriver is not on `PATH`, tell
the extractor:

```bash
export FIREFOX_BIN="/path/to/firefox"
export GECKODRIVER_PATH="/path/to/geckodriver"
export CHATBRAIN_FF_PROFILE="./ff-profile"
```

### Step 2 — extract the session

```bash
python relay/extract.py
```

Writes `relay/.websession.json` (already in `.gitignore` — it is a live login,
treat it like a password). Re-run this whenever the account gets logged out.

### Step 3 — run the relay

```bash
python relay/relay2.py
```

It answers on `http://127.0.0.1:20232`. Check it:

```bash
curl http://127.0.0.1:20232/v1/models
```

```json
{"object": "list", "data": [
  {"id": "deepseek-chat",     "object": "model"},
  {"id": "deepseek-reasoner", "object": "model"}
]}
```

A real completion:

```bash
curl http://127.0.0.1:20232/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-chat","stream":true,
       "messages":[{"role":"user","content":"say hi"}]}'
```

On Windows, `start.ps1` does steps 2–3 and opens opencode for you:

```powershell
./start.ps1
```

### Step 4 — wire up opencode

`~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "deepseek-web": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "DeepSeek (web)",
      "options": {
        "baseURL": "http://127.0.0.1:20232/v1",
        "apiKey": "unused-but-required"
      },
      "models": {
        "deepseek-chat": { "name": "DeepSeek Chat" },
        "deepseek-reasoner": { "name": "DeepSeek Reasoner" }
      }
    }
  },
  "model": "deepseek-web/deepseek-chat"
}
```

Then `opencode` and `/model` to switch.

---

## Models

| id | upstream | notes |
|---|---|---|
| `deepseek-chat` | V3 chat | fast, the default; no visible reasoning |
| `deepseek-reasoner` | R1 | slower, thinking pass, emits the bare `< calls>` dialect |

Both stream. `usage` in the response is **estimated** (token counts are
approximated locally, not reported upstream) — good enough for cost display,
not for billing.

---

## Environment variables

All optional. Defaults are sane.

| variable | default | meaning |
|---|---|---|
| `CHATBRAIN_PORT` | `20232` | listen port |
| `CHATBRAIN_SESSION_FILE` | `relay/.websession.json` | where the token lives |
| `CHATBRAIN_LOG_FILE` | `relay/relay2.log` | operational log |
| `CHATBRAIN_REPLIES_LOG` | `relay/relay2-replies.log` | raw conversations — **delete before sharing** |
| `CHATBRAIN_MIN_GAP` | `2.5` | seconds between upstream calls (log-normally jittered) |
| `CHATBRAIN_JITTER` | `1.5` | log-normal spread of that gap |
| `CHATBRAIN_PAUSE_EVERY` | `15` | calls before a long idle pause |
| `CHATBRAIN_FAIL_COOLDOWN` | `30` | seconds to back off after an upstream error |
| `CHATBRAIN_IMPERSONATE` | `firefox147` | `curl_cffi` TLS target |
| `CHATBRAIN_UA` | derived | override the User-Agent (escape hatch) |
| `CHATBRAIN_FF_PROFILE` | `./ff-profile` | extractor only |
| `FIREFOX_BIN`, `GECKODRIVER_PATH` | auto | extractor only |

Do not set `CHATBRAIN_MIN_GAP` to `0` and then leave an agent running. That is
exactly the pattern the pacing exists to prevent.

---

## Limits

- **This is a consumer chat account, not an API.** Terms of service are on you.
  Do not publish the endpoint, share the box, or resell it.
- No image, file, or attachment input.
- No exact token counts — `usage` is estimated.
- Long conversations eventually hit the upstream context limit; the relay does
  not summarise for you.
- One account is one session chain. Two agents at once means interleaved context.
- Web upstream changes without notice. When replies come back as raw tags or
  empty text, check `relay/relay2.log` before assuming the relay broke.

---

## Troubleshooting

| symptom | cause |
|---|---|
| `no session file` at startup | run `python relay/extract.py` |
| extractor finds no token | Firefox still open, or wrong profile, or not logged in |
| every request 401 / "expired" | token died — re-extract; the relay warns once in the log |
| replies empty or full of raw tags | upstream format changed; look at `relay2-replies.log` |
| `Connection refused` on 20232 | relay not running, or `CHATBRAIN_PORT` differs from `baseURL` |
| requests hang ~30 s | upstream rate limiting; raise `CHATBRAIN_MIN_GAP` |
| opencode shows no tools | model answered in prose; retry, and check the tag reminder in the log |

---

## Credits

Lineage: [`dsh-better-bridge`](https://github.com/betterdeepseek/dsh-better-bridge)
by Samir Jamal — this relay is a fork of that codebase, hardened with a browser
TLS transport, session chaining, log-normal pacing, and a more forgiving reply
parser.

## License

MIT — see [LICENSE](LICENSE).

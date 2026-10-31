# opencode-deepseek-web

Run a **free DeepSeek web account** as an OpenAI-compatible backend, then point
[opencode](https://opencode.ai) at it.

The DeepSeek web chat costs nothing. The metered platform API costs money. This
project bridges the first one into the shape the second one has, keeps the whole
thing on loopback, and paces every upstream request so an autonomous coding
agent does not fire a turn every 200 ms and get the account flagged.

Two files do the work. Everything else is wiring and paperwork.

---

## Contents

- [What this is](#what-this-is)
- [How it works](#how-it-works)
- [Why the pacing exists](#why-the-pacing-exists)
- [Requirements](#requirements)
- [Install](#install)
- [Step 1 — dedicated Firefox profile](#step-1--dedicated-firefox-profile)
- [Step 2 — extract the session](#step-2--extract-the-session)
- [Step 3 — run the relay](#step-3--run-the-relay)
- [Step 4 — wire up opencode](#step-4--wire-up-opencode)
- [Environment variables](#environment-variables)
- [Internals](#internals)
- [Limits](#limits)
- [Troubleshooting](#troubleshooting)
- [Credits](#credits)
- [License](#license)

---

## What this is

A local HTTP server that speaks the OpenAI chat API:

| endpoint | behaviour |
|---|---|
| `GET /v1/models` | returns a single model, `deepseek-chat` |
| `POST /v1/chat/completions` | translates the request, calls `chat.deepseek.com` with your own web token, translates the reply back |

Model name: `deepseek-chat`. Provider label: `chatbrain`. Bearer token: ignored —
any non-empty string works.

Because the surface is the OpenAI API, the client does not have to be opencode.
Anything that accepts `baseURL` + `apiKey` works: opencode, an OpenAI SDK, `curl`,
another harness. opencode is simply the one that is pre-wired.

### What it is not

- Not a DeepSeek product, not affiliated with them.
- Not a wrapper around the paid platform API. There is no API key, no billing,
  no quota — just a browser session.
- Not streaming in any real sense. See [Limits](#limits).
- Not a replacement for a metered API on heavy work. See [Internals](#internals)
  for why tool-call parsing over a chat model is the fragile part.

---

## How it works

```
┌─────────────┐   OpenAI API    ┌───────────────┐   HTTPS + PoW   ┌────────────────────┐
│  opencode   │ ──────────────► │  relay2.py    │ ──────────────► │ chat.deepseek.com  │
│  (client)   │ ◄────────────── │ :20232        │ ◄────────────── │ (your web session) │
└─────────────┘   tool_calls    └───────────────┘   SSE + history └────────────────────┘
                                        ▲
                                        │ token + cookies
                                 ┌──────┴──────┐
                                 │ extract.py  │ ── reads Firefox profile
                                 └─────────────┘    localStorage["userToken"]
```

Three hops, and only the middle one is code we own.

| file | job |
|---|---|
| `relay/extract.py` | opens a dedicated Firefox profile via geckodriver, reads `userToken` from localStorage plus cookies, writes `relay/.websession.json` |
| `relay/relay2.py` | the OpenAI facade. Renders the harness's system prompt + tool catalog as a text contract, sends it to the DeepSeek chat endpoint, parses the tagged reply back into `tool_calls` |
| `start.ps1` | starts the relay if the port is dead, waits for `/v1/models`, hands off to the opencode TUI |
| `requirements.txt` | `deepseek-pow`, `wasmtime`, `selenium` |
| `.gitignore` | keeps the session token and logs out of git |

---

## Why the pacing exists

A human on the website sends maybe one message every ten seconds. A coding agent
in a tool loop fires five in two, then idles for a minute, then fires five more.
The **account** pays for that difference. Bursty traffic from one account is the
signal that gets it flagged.

So every outbound call to `chat.deepseek.com` passes through one gate:

```python
def _throttle(extra=0.0):
    with _throttle_lock:
        gap = MIN_GAP + random.uniform(0, JITTER) + extra
        wait = _last_call[0] + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()
```

`_throttle()` is the first line of `api()`, so nothing reaches DeepSeek without
passing it — not the proof-of-work challenge, not the completion, not the history
readback.

Two properties matter:

1. **The lock is held across the sleep.** Concurrent chains cannot bunch up
   behind the gate and then all release at once. Serialised, always.
2. **A failure costs more than a success.** A non-200 from completion applies
   `FAIL_COOLDOWN` on top, so a broken token produces one attempt and a long
   pause instead of a retry storm.

Net rate: roughly **2.5–4.0 s** between upstream calls with the defaults. The
relay therefore processes completion requests strictly one at a time — a second
`POST` waits on `LOCK` and then waits on the throttle.

Tune up on a fresh or already-chatty account. Setting the gap to `0` is for
debugging and nothing else.

---

## Requirements

- Windows, macOS, or Linux.
- Python 3.10+.
- Firefox, installed normally, profiled separately.
- [geckodriver](https://github.com/mozilla/geckodriver/releases) on `PATH` or
  pointed at with `GECKODRIVER_PATH`.
- A DeepSeek account you can log into in a browser.
- optional: [opencode](https://opencode.ai) as the client.

---

## Install

```powershell
pip install -r requirements.txt
```

Contents: `deepseek-pow>=0.0.1` (proof-of-work solver), `wasmtime` (it runs a
WASM module), `selenium>=4` (profile read).

---

## Step 1 — dedicated Firefox profile

Do **not** point this at the profile you browse with daily. The extractor opens
the profile headlessly and the relay holds its token; keeping it isolated means a
revoked token costs you one throwaway profile, not your daily history.

Create and log in by hand, in a normal Firefox window:

1. Open the Firefox profile manager (`firefox -P`, or
   `about:profiles` in the address bar).
2. Create a new profile, e.g. `deepseek-relay`.
3. Launch that profile, go to `https://chat.deepseek.com`, log in normally.
4. Send one message so the session is definitely live.
5. Close Firefox **completely** before running the extractor.

---

## Step 2 — extract the session

```powershell
$env:CHATBRAIN_FF_PROFILE = "C:\Users\<you>\deepseek-relay-profile"
$env:GECKODRIVER_PATH     = "C:\tools\geckodriver\geckodriver.exe"
python relay\extract.py
```

On success it prints `TOKEN_LEN: <n>` and writes `relay/.websession.json` — a
JSON object holding `token` and `cookies`, which is exactly what `relay2.py`
loads at startup.

`TOKEN_LEN: 0` means the profile is not logged in, or Firefox was still holding
the profile lock. Close Firefox, delete `parent.lock` inside the profile
directory, run it again.

> **`relay/.websession.json` is a live account credential.** It is gitignored.
> Never commit it, never paste it into an issue, never copy it into a screenshot.
> If it leaks, log out of that account everywhere — the token dies with the
> session.

---

## Step 3 — run the relay

```powershell
python relay\relay2.py
```

Expected:

```
relay2 up on 20232
```

Verify from another shell:

```powershell
curl.exe http://127.0.0.1:20232/v1/models
# {"object":"list","data":[{"id":"deepseek-chat",...}]}
```

A first real completion:

```powershell
curl.exe -s http://127.0.0.1:20232/v1/chat/completions `
  -H "Content-Type: application/json" `
  -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"Reply with exactly one word: PONG"}]}'
```

If it answers, the account, the PoW solver, and the throttle are all working.
`relay/relay2.log` records each stage (`pow challenge: algo=... diff=...`,
`chat session created: ...`, `throttle: sleep 2.96s`, `ask done: answer chars=…`).

---

## Step 4 — wire up opencode

Add a provider in `~/.config/opencode/opencode.json` (on Windows:
`C:\Users\<you>\.config\opencode\opencode.json`):

```json
{
  "provider": {
    "chatbrain": {
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "http://127.0.0.1:20232/v1",
        "apiKey": "dummy"
      },
      "models": {
        "deepseek-chat": {
          "name": "DeepSeek Chat (web)",
          "modalities": { "input": ["text"], "output": ["text"] }
        }
      }
    }
  }
}
```

The relay ignores the bearer token, so `apiKey` is a placeholder — but the field
must be non-empty, or the client refuses to start.

Select it:

- interactive TUI: `/model`, then pick `DeepSeek Chat (web)`
- one-shot: `opencode run --model chatbrain/deepseek-chat "…"`

`--model` is a `run` flag, not a TUI flag; inside the TUI it is `/model`.

Or just run the wrapper, which starts the relay first and then opens opencode:

```powershell
.\start.ps1
```

---

## Environment variables

Read at startup by `relay2.py`:

| variable | default | meaning |
|---|---|---|
| `CHATBRAIN_PORT` | `20232` | listen port; keep it loopback |
| `CHATBRAIN_SESSION_FILE` | `relay/.websession.json` | token + cookies file |
| `CHATBRAIN_LOG_FILE` | `relay/relay2.log` | per-call diagnostics |
| `CHATBRAIN_REPLIES_LOG` | `relay/relay2-replies.log` | first 4 KB of every raw reply |
| `CHATBRAIN_MIN_GAP` | `2.5` | floor seconds between upstream calls |
| `CHATBRAIN_JITTER` | `1.5` | random extra, `0..JITTER` |
| `CHATBRAIN_FAIL_COOLDOWN` | `30` | extra hold after a non-200 from completion |

Read at run time by `extract.py`:

| variable | default | meaning |
|---|---|---|
| `CHATBRAIN_FF_PROFILE` | `relay/ff-profile` | Firefox profile directory to read |
| `FIREFOX_BIN` | `/usr/bin/firefox` | Firefox binary; set this on Windows |
| `GECKODRIVER_PATH` | `geckodriver` | driver binary or name on `PATH` |
| `CHATBRAIN_SESSION_FILE` | `relay/.websession.json` | output path |

Back off harder on a healthy account too if you run agentic loops all day:

```powershell
$env:CHATBRAIN_MIN_GAP = "4"; $env:CHATBRAIN_JITTER = "2"
```

---

## Internals

The interesting part is not the HTTP facade — it is the impedance mismatch
between an OpenAI-style agent harness and a chat website that has never heard of
tool calls.

### 1. Prompt rendering

An agent sends `messages[]` plus a `tools[]` catalog. DeepSeek's chat endpoint
takes a single string. So the relay builds one:

- a fixed `PREAMBLE` explaining that the model is a "brain" behind a harness,
  that it has tools, and how to emit a call (`<tool_call>{"name":…, "arguments":{…}}</tool_call>`)
- the tool catalog, name + truncated description + truncated JSON schema
- each message rendered with a role prefix: `[System instructions]`, `User:`,
  `Assistant:`, `Assistant called tool X: …`, `Tool result (name): …`

Tool results are capped at 4000 characters per message, schemas at 1500, so a
wide MCP toolset does not blow the prompt up.

The rendered history is only sent once. Subsequent turns send just the delta
(see the chain logic below), because a web chat session already retains its own
context server-side.

### 2. The PoW header

DeepSeek gates completion behind a proof-of-work challenge. The relay:

1. `POST /api/v0/chat/create_pow_challenge` with `target_path=/api/v0/chat/completion`
2. solves it with `deepseek-pow`'s `DeepSeekHashV1` registry entry (WASM via `wasmtime`)
3. builds the answer payload **by hand** — the library's own
   `to_answer_payload()` omits `target_path`, and the web client requires it
4. sends the whole thing base64-encoded in the `x-ds-pow-response` header

That challenge fetch is a second upstream call, which is why the effective gap
between user-visible turns is roughly double `MIN_GAP`.

### 3. Chat session chain

Each chain is an `ApiBrain` holding `session_id` + `parent_message_id`.

- `POST /api/v0/chat_session/create` mints a session on the first turn.
- Each completion advances `parent_message_id` to the reply's message id.
- The authoritative answer text is **not** taken from the completion response.
  The relay reads it back with
  `GET /api/v0/chat/history_messages?chat_session_id=…` and concatenates the
  `RESPONSE` fragments of the last `ASSISTANT` message. The SSE stream is
  consumed and discarded.

Chains are keyed by `chain_key(messages, tools)`:

```
tools present          -> "tools"                       (the agent's real chain)
otherwise              -> "aux:" + md5(first 2 msgs)[:8] (title calls, side jobs)
```

That split exists because opencode fires auxiliary requests (session titles,
summarisation) on the same endpoint. Without isolation, an aux request would
reset the agent's conversation. The map is capped at 6 chains with oldest-first
eviction.

A chain also resets when the client's message count goes **backwards**, or when
the last-seen message fingerprint changes — i.e. the harness is no longer
continuing the same conversation, so continuing the DeepSeek session would be
wrong.

### 4. Reply parsing

The model does not reliably produce `<tool_call>` JSON. It produces three
dialects, sometimes fused in one reply, so `parse_reply()` handles all of them:

| dialect | shape | handling |
|---|---|---|
| tag contract | `<tool_call>{…}</tool_call>` | **balanced-brace scan**, not regex — nested argument objects survive; the closing tag is treated as optional because the model routinely closes a JSON block with DSML tags |
| DeepSeek DSML | `<｜tool｜invoke name="x">` + `<｜tool｜parameter name="y">` | regex per invoke/parameter, `string="true"` honoured, everything else `json.loads` with a string fallback |
| flattened | `{"name":"x","command":"…"}` with args at top level | remaining top-level keys are promoted to arguments |

`normalize_dsml()` repairs delimiters damaged in transit — fullwidth pipes
sometimes come back as `U+FFFD` runs — before any of that runs. Leftover tag
debris is stripped from visible text at the end.

If any tool call survives parsing, `trim_code_blocks()` caps fenced blocks in the
accompanying prose at 10 lines, because the chat brain's habit is to paste the
entire script it just ran into the visible message.

### 5. Concurrency

`do_POST` holds one global `LOCK` for the whole upstream round trip. Combined
with the throttle this means: **one completion in flight, ever.** Correctness
over throughput — and rate safety, which is the point of the project.

---

## Limits

| limit | cause |
|---|---|
| no real streaming | `stream` is read and then ignored; the response arrives as a single buffered SSE chunk pair, then `[DONE]`. The upstream answer is only final after a history readback, so there is nothing to stream incrementally. |
| `usage` is all zeros | a web session has no token accounting. Do not budget on it. |
| text only | no image or file input is forwarded. |
| one request at a time | global lock. Two agent sessions serialise behind each other. |
| tool-call parsing is the weak spot | the model is a chat model being asked to be a function-calling model. Short loops behave; long agentic loops drift, lose tags, or answer in prose mid-loop. Compare `relay2-replies.log` with what the harness recorded when it goes wrong. |
| single account | one session token, one identity. Volume is the ban risk, not the client choice. |
| loopback only | binds `127.0.0.1`. Do not expose the port, do not put it behind a tunnel, do not share it. |

For heavy coding work, a metered API-backed provider is simply more reliable.
This project exists for the free tier and for light work.

---

## Troubleshooting

**`401` / `brain_failed` / repeated `ask failed`**
The web token expired or was invalidated. Close Firefox, delete `parent.lock`
inside the profile, re-run `python relay\extract.py`, restart the relay.

**`connection refused` on `127.0.0.1:20232`**
Relay is not running, or `CHATBRAIN_PORT` was changed on one side only.

**`TOKEN_LEN: 0`**
Profile is not logged in, or Firefox still holds it. Log in by hand first, close
every Firefox window, retry.

**Tool calls stop landing mid-session**
Expected failure mode. Look at `relay2-replies.log`: if the raw reply contains
prose instead of tags, the model dropped the contract for that turn. Starting a
fresh session (`/new` in opencode) re-renders the preamble and usually fixes it.

**`NativeCommandError` on stderr in PowerShell**
Cosmetic. `opencode.exe` writes progress to stderr.

**Everything is slow**
It is supposed to be. Two upstream calls per turn, each behind a 2.5–4 s gate.
Fifteen seconds for a turn is normal. Lower the gap at your own risk.

**Account flagged or limited**
Stop. Raise `CHATBRAIN_MIN_GAP` and `CHATBRAIN_JITTER`, drop the request volume,
and let it settle. Retrying faster is the thing that makes it worse.

---

## Credits

The relay and the session extractor are derived from **dsh-better-bridge** by
Samir Jamal, used under the MIT license. This project keeps that license and its
copyright notice, and changes the integration target:

- the harness is opencode, not dsh
- the relay gained request pacing (`_throttle`, jitter, failure cooldown)
- the README, launcher, and packaging are new work

If you want the upstream lineage, that repository is the place to look.

## License

MIT — see [LICENSE](LICENSE). Copyright is retained for both this project's
contributors and the upstream author, as MIT requires.

## Disclaimer

Unofficial and unaffiliated with DeepSeek or with opencode. It drives a browser
session you created and own. Whether that is permitted by the service's terms is
between you and them, and an account can be limited or closed for automated
traffic. Use it on your own account, keep the volume low, and do not redistribute
session tokens.

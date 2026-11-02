# AGENTS.md

Commands and invariants for anyone (human or agent) working in this repo.

This project is a **relay**: it turns a free `chat.deepseek.com` web account into
an OpenAI-compatible endpoint on loopback, so `opencode` can use it as a model
provider. Two files do the work — `relay/extract.py` (one-time session grab) and
`relay/relay2.py` (the server). Everything else is wiring.

---

## 1. Layout

```
relay/extract.py     one-time: read the Firefox cookie store -> relay/.websession.json
relay/relay2.py      the relay: OpenAI-shaped HTTP on 127.0.0.1:20232
relay/.websession.json   live credential (gitignored, never commit)
relay/relay2.log         per-call diagnostics (gitignored)
relay/relay2-replies.log first 4 KB of every raw reply (gitignored)
start.ps1            starts the relay hidden, waits on 20232, execs opencode
requirements.txt     deepseek-pow, wasmtime, curl_cffi, selenium
```

---

## 2. First run — in this order

Order matters. The relay cannot start before the session file exists, and the
session file cannot exist before a logged-in Firefox profile does.

```powershell
# 0. dependencies
pip install -r requirements.txt

# 1. build the session (Firefox must be fully closed first)
$env:CHATBRAIN_FF_PROFILE = "<profile Root Directory copied from about:profiles>"
python relay\extract.py

# 2. start the relay (leave it running)
python relay\relay2.py

# 3. use it
opencode run --model chatbrain/deepseek-chat "Reply with exactly one word: OK"
```

Or skip steps 2–3 and use the wrapper, which does both:

```powershell
.\start.ps1
```

---

## 3. Verification — run these, do not assume

```powershell
# session file exists and parses
python -c "import json;d=json.load(open(r'relay\.websession.json'));print('token_len',len(d['token']),'cookies',len(d['cookies']))"

# relay is up and lists the model
curl.exe http://127.0.0.1:20232/v1/models

# a real completion round-trips
curl.exe -s http://127.0.0.1:20232/v1/chat/completions -H "Content-Type: application/json" -d '{\"model\":\"deepseek-chat\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly one word: PONG\"}]}'
```

Expected evidence, in the same currency the README uses:

| claim | evidence required |
|---|---|
| session extracted | `TOKEN_LEN: <n>` printed, `n > 0` |
| relay running | `relay2 up on 20232` on stdout |
| models served | `GET /v1/models` returns `{"object":"list","data":[{"id":"deepseek-chat",...}]}` |
| completion works | `POST /v1/chat/completions` returns non-empty `content` |
| end to end | `opencode run --model chatbrain/deepseek-chat "…"` prints a reply |

Without that evidence, report the failure with the raw message. Do not describe
a run you did not observe.

`relay/relay2.log` is where a failed stage is named — `pow challenge`,
`chat session created`, `throttle: sleep …`, `ask done: answer chars=…`. Read it
before guessing.

---

## 4. Environment variables

`relay/extract.py`:

| variable | default | meaning |
|---|---|---|
| `CHATBRAIN_FF_PROFILE` | `relay/ff-profile` | Firefox **Root Directory** to read |
| `CHATBRAIN_SESSION_FILE` | `relay/.websession.json` | where to write the token |
| `GECKODRIVER_PATH` | auto-probed | geckodriver binary |
| `FIREFOX_BINARY` | auto-probed | firefox executable |

`relay/relay2.py`:

| variable | default | meaning |
|---|---|---|
| `CHATBRAIN_PORT` | `20232` | listen port; keep it loopback |
| `CHATBRAIN_SESSION_FILE` | `relay/.websession.json` | token + cookies |
| `CHATBRAIN_LOG_FILE` | `relay/relay2.log` | diagnostics |
| `CHATBRAIN_REPLIES_LOG` | `relay/relay2-replies.log` | raw reply capture |
| `CHATBRAIN_MIN_GAP` | `2.5` | floor seconds between upstream calls |
| `CHATBRAIN_JITTER` | `1.5` | spread of the log-normal gap draw |
| `CHATBRAIN_PAUSE_EVERY` | `15` | one 20–90 s pause every N calls (`0` disables) |
| `CHATBRAIN_FAIL_COOLDOWN` | `30` | extra hold after a failed completion |
| `CHATBRAIN_IMPERSONATE` | `firefox147` | `curl_cffi` TLS/JA3 profile |
| `CHATBRAIN_UA` | unset | pin a `User-Agent`; default is whatever the profile sends |

---

## 5. Invariants — do not break these

1. **Loopback only.** The relay binds `127.0.0.1`. Never expose it.
2. **The pacing exists for a reason.** `MIN_GAP` + `JITTER` + the request lock
   keep an autonomous agent from firing a turn every 200 ms and getting the
   account flagged. Setting `MIN_GAP=0` is debugging only.
3. **One completion at a time.** A second `POST` waits on the lock. Do not "fix"
   this with threads.
4. **`relay/.websession.json` is a live credential.** Gitignored. Never commit
   it, never paste it into an issue, never screenshot it. If it leaks, log that
   account out everywhere — the token dies with the session.
5. **`relay2-replies.log` contains raw conversations.** Gitignored. Do not attach
   it to anything public.
6. **`stream` is accepted and ignored**; `usage` is always zero. Clients that
   strictly require token accounting need a different backend.
7. **Do not delete user data** — session files, logs, profiles — without explicit
   permission.

---

## 6. Failure → cause

| message | cause | action |
|---|---|---|
| `Session file not found: …` | step 1 never ran | `python relay\extract.py` |
| `Missing dependency 'deepseek_pow'` | deps not installed | `pip install -r requirements.txt` |
| `TOKEN_LEN: 0` | profile not logged in, or Firefox still held the lock | close Firefox, delete `parent.lock` in the profile, rerun |
| `Firefox profile not found` | wrong `CHATBRAIN_FF_PROFILE` | re-copy Root Directory from `about:profiles` |
| `geckodriver not found` | not on `PATH` | set `GECKODRIVER_PATH` |
| `relay not answering on 20232` | relay died at startup | read `relay/relay2.log` |
| `upstream transport failed (…)` | `curl_cffi` could not complete the handshake — bad `CHATBRAIN_IMPERSONATE` value, or the network drops the connection | check `python -c "from curl_cffi.requests import BrowserType; print(list(BrowserType))"` for a valid profile, then `pip install -U curl_cffi` |
| `NativeCommandError` after `pip install` | PowerShell renders pip's stderr notice as an error | cosmetic; confirm with `pip show deepseek-pow wasmtime curl_cffi selenium` |

---

## 7. Editing rules

- Fix `relay2.py` and `extract.py` directly. Do not create parallel variants.
- New failure paths get a `SystemExit` with a message naming the fix, not a bare
  traceback.
- Preserve auto-detection in `extract.py`; a hardcoded local path is a regression.
- If a change alters setup steps, update **both** `README.md` and this file.
- Do not write up transient install bugs here — this file carries commands and
  invariants, not a changelog.

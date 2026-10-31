"""Extract the DeepSeek web session (userToken + cookies) from a dedicated
Firefox profile into the relay's session file.

One-time setup: launch Firefox with a dedicated profile (CHATBRAIN_FF_PROFILE),
log in to https://chat.deepseek.com manually, close Firefox, then run this
script. It re-opens that profile headlessly via Selenium/geckodriver, reads
localStorage["userToken"], and writes {token, cookies} as JSON with mode 600.

Sanitized for publication: all paths are configurable via environment
variables (see .env.example). The output file contains a live account token —
keep it chmod 600 and NEVER commit it."""
import os, time, json
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

HERE = os.path.dirname(os.path.abspath(__file__))

def _find_firefox():
    for p in ("/usr/bin/firefox", "/usr/bin/firefox-esr",
              r"C:\Program Files\Mozilla Firefox\firefox.exe",
              r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe"):
        if os.path.isfile(p):
            return p
    return None

def _find_geckodriver():
    from shutil import which
    p = which("geckodriver")
    if p:
        return p
    for p in (r"C:\tools\geckodriver\geckodriver.exe",
              os.path.join(HERE, "geckodriver.exe"), os.path.join(HERE, "geckodriver")):
        if os.path.isfile(p):
            return p
    return None

FIREFOX_BIN = os.environ.get("FIREFOX_BIN") or _find_firefox()
GECKODRIVER = os.environ.get("GECKODRIVER_PATH") or _find_geckodriver()
FF_PROFILE = os.environ.get("CHATBRAIN_FF_PROFILE", os.path.join(HERE, "ff-profile"))
SESSION_FILE = os.environ.get("CHATBRAIN_SESSION_FILE", os.path.join(HERE, ".websession.json"))

if not FIREFOX_BIN:
    raise SystemExit("Firefox not found. Install Firefox, or set FIREFOX_BIN to firefox.exe")
if not GECKODRIVER:
    raise SystemExit("geckodriver not found on PATH. Download it, put geckodriver.exe next to "
                     "this script or in C:\\tools\\geckodriver, or set GECKODRIVER_PATH")
if not os.path.isdir(FF_PROFILE):
    raise SystemExit(f"Firefox profile not found: {FF_PROFILE}\n"
                     "Open Firefox, go to about:profiles, copy the Root Directory of the profile "
                     "you logged into chat.deepseek.com with, and set CHATBRAIN_FF_PROFILE to it.")

opts = Options()
opts.binary_location = FIREFOX_BIN
opts.add_argument("-profile")
opts.add_argument(FF_PROFILE)
opts.add_argument("-no-remote")
opts.page_load_strategy = "eager"
d = webdriver.Firefox(service=Service(GECKODRIVER), options=opts)
d.set_page_load_timeout(60)
try:
    d.get("https://chat.deepseek.com")
    time.sleep(5)
    keys = d.execute_script("return Object.keys(localStorage)")
    print("LS_KEYS:", keys, flush=True)
    tok = d.execute_script("return localStorage.getItem(\"userToken\")")
    token_val = None
    if tok:
        try:
            j = json.loads(tok)
            token_val = j.get("value") if isinstance(j, dict) else tok
        except Exception:
            token_val = tok
    cookies = d.get_cookies()
    out = {"token": token_val, "cookies": [{"name": c["name"], "value": c["value"], "domain": c.get("domain", "")} for c in cookies]}
    with open(SESSION_FILE, "w") as f:
        json.dump(out, f)
    os.chmod(SESSION_FILE, 0o600)
    print("TOKEN_LEN:", len(token_val) if token_val else 0, flush=True)
    print("COOKIES:", sorted(set(c["name"] for c in out["cookies"])), flush=True)
finally:
    d.quit()
print("EXTRACT_DONE", flush=True)

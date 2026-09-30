"""Run existing P04 CDP assertions against isolated CPU browser/server ports."""
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = "http://127.0.0.1:19104"
CDP = "http://127.0.0.1:19105"

with tempfile.TemporaryDirectory(prefix="p04-refit-chrome-") as profile:
    server = subprocess.Popen(["python3", "-m", "metric_review.server", "--port", "19104"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    browser = subprocess.Popen(["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu", "--remote-debugging-port=19105", f"--user-data-dir={profile}", "--window-size=1440,900", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(SERVER, timeout=.2).close()
                urllib.request.urlopen(CDP + "/json/version", timeout=.2).close()
                break
            except Exception:
                time.sleep(.1)
        else:
            raise RuntimeError("isolated server or CDP unavailable")
        subprocess.run(["python3", "scripts/browser_check.py", "--app", SERVER, "--cdp", CDP, "--output", "artifacts/browser/refit-check"], cwd=ROOT, check=True)
    finally:
        browser.terminate()
        server.terminate()
        browser.wait(timeout=10)
        server.wait(timeout=10)

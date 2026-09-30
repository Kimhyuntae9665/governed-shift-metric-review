"""P04 visual refit browser evidence. Synthetic CPU paths only; zero model calls."""
import hashlib
import json
import os
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BROWSER_CACHE = ROOT / "artifacts" / "browser" / "refit-playwright"
FFMPEG_LINK = BROWSER_CACHE / "ffmpeg-1011" / "ffmpeg-linux"
FFMPEG_LINK.parent.mkdir(parents=True, exist_ok=True)
if not FFMPEG_LINK.exists():
    FFMPEG_LINK.symlink_to("/usr/bin/ffmpeg")
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSER_CACHE)
from playwright.sync_api import sync_playwright

OUT = ROOT / "docs" / "demo" / "current"
OUT.mkdir(parents=True, exist_ok=True)
PORT = 19104
URL = f"http://127.0.0.1:{PORT}"
EARLY = "2026-10-01T23:30:00+09:00"
LATE = "2026-10-02T00:30:00+09:00"
checks = []
images = []


def wait_port():
    for _ in range(80):
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=.2):
                return
        except OSError:
            time.sleep(.1)
    raise RuntimeError("P04 loopback test server unavailable")


def check(ok, label):
    assert ok, label
    checks.append(label)


def wait(page, expression, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.evaluate(expression):
            return
        time.sleep(.08)
    raise RuntimeError("UI wait expired: " + expression)


def capture(page, name, caption, locator=None):
    target = page.locator(locator) if locator else page
    path = OUT / name
    target.screenshot(path=str(path), full_page=locator is None, animations="disabled") if locator is None else target.screenshot(path=str(path), animations="disabled")
    images.append({"file": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "caption": caption, "actual_browser": True})
    time.sleep(.35)


def calculate(page, dataset="baseline", cutoff=LATE, scope="combined", metric="oee"):
    page.locator("#dataset").select_option(dataset)
    page.locator("#cutoff").select_option(cutoff)
    page.locator("#scope").select_option(scope)
    page.locator("#metric").select_option(metric)
    page.locator("#calculate").click()
    wait(page, "!state.busy && !!currentReceipt()")


server = subprocess.Popen(
    ["python3", "-m", "metric_review.server", "--port", str(PORT)],
    cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    start_new_session=True,
)
try:
    wait_port()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True, args=["--no-sandbox", "--disable-gpu"])
        desktop = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1, accept_downloads=True, reduced_motion="reduce", record_video_dir=str(OUT), record_video_size={"width": 1440, "height": 900})
        page = desktop.new_page()
        page.goto(URL, wait_until="networkidle")
        wait(page, "!!state.token && state.datasets.length > 0")
        check(page.locator("h1").inner_text() == "교대 지표 근거 검토", "large Korean task title")
        check(page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "desktop no horizontal overflow")
        check(page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(241, 244, 246)", "reference canvas token")
        check(page.evaluate("Math.abs(document.querySelector('.records-panel').getBoundingClientRect().width-document.querySelector('.results-panel').getBoundingClientRect().width)<3"), "source and result equal panels")
        calculate(page)
        check(page.evaluate("currentReceipt().result.combined.metrics.oee.exact") == "147/160", "baseline combined exact OEE")
        check("8.125" in page.locator("#average-gap").inner_text(), "counterexample gap shown")
        capture(page, "01-combined-result.png", "승인 지표·합산 분자와 분모·원본 행")

        page.locator("[data-record-tab='accepted']").click()
        capture(page, "02-accepted-sources.png", "채택 행과 원본 열람", ".workspace")
        page.locator("[data-evidence-index]").first.click()
        page.locator("#evidence-dialog").wait_for(state="visible")
        check(page.locator("#original-row").inner_text().strip() != "", "admitted source original row visible")
        capture(page, "03-source-detail.png", "원본 행·정확한 표시값·출처 해시", "#evidence-dialog")
        page.locator("#close-evidence").click()
        wait(page, "document.querySelector('[data-evidence-index]')===document.activeElement")
        check(True, "source dialog returns keyboard focus")

        calculate(page, "correction_review", EARLY)
        check(page.evaluate("currentReceipt().result.combined.metrics.oee.exact") == "11/12", "before correction exact OEE")
        capture(page, "04-before-correction.png", "23:30 기록 기준·정정 전 11/12", ".workspace")
        calculate(page, "correction_review", LATE)
        check(page.evaluate("currentReceipt().result.combined.metrics.oee.exact") == "147/160", "after correction exact OEE")
        capture(page, "05-after-correction.png", "00:30 기록 기준·정정 후 147/160", ".workspace")
        page.locator("[data-record-tab='superseded']").click()
        capture(page, "06-superseded-row.png", "이전 개정 제외와 정정 이력", ".records-panel")

        calculate(page, "conflicting_revision")
        check(page.evaluate("currentReceipt().result.combined.metrics.oee.exact === null"), "conflict blocks combined OEE")
        page.locator("[data-record-tab='quarantine']").click()
        capture(page, "07-conflict-quarantine.png", "동일 개정 충돌·격리·정의되지 않음", ".workspace")
        calculate(page, "missing_good")
        check(page.evaluate("currentReceipt().result.combined.metrics.oee.exact === null"), "missing good is unknown, not zero")
        capture(page, "08-missing-good.png", "양품 누락·가동률과 미정의 OEE", ".workspace")

        page.locator("#profile").select_option("reviewer")
        wait(page, "state.principal?.role==='reviewer' && !state.busy")
        calculate(page)
        page.locator("#review-ack").check()
        page.locator("#review-submit").click()
        wait(page, "!state.busy && !!currentReceipt()?.review")
        capture(page, "09-review-history.png", "산술 영수증 검토 기록·이력", ".review-grid")

        mobile = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True, has_touch=True, reduced_motion="reduce")
        small = mobile.new_page()
        small.goto(URL, wait_until="networkidle")
        wait(small, "!!state.token && state.datasets.length > 0")
        calculate(small)
        check(small.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), "390px page reflows without horizontal overflow")
        check(small.evaluate("document.querySelector('h1').getBoundingClientRect().right <= innerWidth"), "390px title does not clip")
        capture(small, "10-mobile-390.png", "390px 화면·선택과 결과")
        mobile.close()
        video = page.video
        desktop.close()
        raw_video = Path(video.path())
        subprocess.run(["ffmpeg", "-y", "-i", str(raw_video), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(OUT / "workflow.mp4")], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        raw_video.unlink(missing_ok=True)
        browser.close()
finally:
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()

(OUT / "checks.json").write_text(json.dumps({"checks": checks, "images": images, "model_requests": 0, "port": PORT, "synthetic": True, "video": {"file": "workflow.mp4", "sha256": hashlib.sha256((OUT / "workflow.mp4").read_bytes()).hexdigest(), "source": "Playwright actual Chrome recording, codec-only ffmpeg conversion; no overlays or compositing"}}, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"checks": len(checks), "images": len(images), "model_requests": 0, "video_bytes": (OUT / "workflow.mp4").stat().st_size}, ensure_ascii=False))

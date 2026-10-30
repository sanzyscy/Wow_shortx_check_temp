#!/usr/bin/env python3
"""Original MediaFire direct URL inspector.

Only inspects the known public Sonic TV APK landing page in an isolated Chrome.
It NEVER clicks Download and NEVER downloads APK bytes. Does not use bypassers.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from urllib.parse import unquote, urlsplit

SHARE_URL = "https://www.mediafire.com/file/5aonm7dpeiejfcz/Sonic+TV_1.0.1.apk/file"
FILE_ID = "5aonm7dpeiejfcz"
DIRECT_HOST = re.compile(r"download[0-9]*\.mediafire\.com", re.I)


def safe_mediafire_share(url: str) -> bool:
    try:
        p = urlsplit(url)
        return (p.scheme == "https" and p.hostname in
                {"mediafire.com", "www.mediafire.com"} and
                p.username is None and p.password is None and
                p.path.startswith(f"/file/{FILE_ID}/") and
                p.path.endswith("/file"))
    except ValueError:
        return False


def direct_apk_url(url: str) -> bool:
    """Narrow candidate check: HTTPS MediaFire download host and APK path."""
    try:
        p = urlsplit(url)
        return bool(p.scheme == "https" and p.hostname and
                    DIRECT_HOST.fullmatch(p.hostname) and
                    p.username is None and p.password is None and
                    unquote(p.path).lower().endswith(".apk"))
    except ValueError:
        return False


def sanitize(url: str) -> str:
    try:
        p = urlsplit(url)
        return f"{p.scheme}://{p.hostname}{p.path}"[:250]
    except ValueError:
        return "invalid"


def choose_candidate(candidates: list[dict]) -> str | None:
    """Accept download links from MediaFire's download button ONLY."""
    for item in candidates:
        ident = item.get("id", "")
        href = item.get("href", "")
        css = item.get("class", "")
        parent = item.get("parent_id", "")
        official_button = (ident == "downloadButton" or
                           (parent == "download_link" and
                            "input" in css.split() and
                            "popsok" in css.split()))
        if official_button and direct_apk_url(href):
            return href
    return None


def inspect(url: str, seconds: int) -> dict:
    from playwright.sync_api import sync_playwright

    report = {
        "source": url,
        "status": "not_found",
        "direct_download_url": None,
        "reason": "",
        "downloaded_bytes": 0,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "note": "Temporary link only; do not treat as APK safety verification.",
    }
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            channel="chrome", headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(accept_downloads=False)
        page = context.new_page()
        page.set_default_timeout(5000)

        def gate(route):
            req_url = route.request.url
            try:
                host = urlsplit(req_url).hostname or ""
            except ValueError:
                route.abort()
                return
            if direct_apk_url(req_url):
                # Prevent all actual APK download network requests.
                report["direct_download_url"] = req_url
                report["status"] = "candidate"
                report["reason"] = "Download URL intercepted without fetching APK"
                route.abort()
                return
            if not (host == "mediafire.com" or host.endswith(".mediafire.com")):
                route.abort()
                return
            if re.search(r"\.apk(?:[?#]|$)", req_url, re.I):
                route.abort()
                return
            route.continue_()

        page.route("**/*", gate)
        page.on("download", lambda download: download.cancel())
        page.on("popup", lambda popup: popup.close())

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            deadline = time.monotonic() + min(max(seconds, 5), 40)
            while time.monotonic() < deadline and not report["direct_download_url"]:
                candidates = page.evaluate("""() =>
                  Array.from(document.querySelectorAll(
                    'a#downloadButton, #download_link a.input.popsok'
                  )).map(a => ({
                    id: a.id || '',
                    href: a.href || '',
                    class: String(a.className || ''),
                    parent_id: a.closest('#download_link') ? 'download_link' : ''
                  }))
                """)
                direct = choose_candidate(candidates)
                if direct:
                    report["status"] = "candidate"
                    report["direct_download_url"] = direct
                    report["reason"] = "MediaFire download-button href; not fetched"
                    break
                page.wait_for_timeout(1200)
            if not report["direct_download_url"]:
                report["reason"] = ("No supported MediaFire download button found. "
                                    "Page may require additional checks or be unavailable.")
            report["landing_host"] = urlsplit(page.url).hostname
            report["page_title"] = page.title()[:180]
        finally:
            context.close()
            browser.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Read MediaFire direct URL only")
    parser.add_argument("--url", default=SHARE_URL)
    parser.add_argument("--seconds", type=int, default=25)
    parser.add_argument("--out", default="mediafire_result")
    args = parser.parse_args()
    if not safe_mediafire_share(args.url):
        parser.error("Only the known Sonic TV MediaFire file page is supported")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        result = inspect(args.url, args.seconds)
    except Exception as exc:
        result = {
            "source": args.url, "status": "error",
            "direct_download_url": None,
            "reason": f"{type(exc).__name__}: {exc}",
            "downloaded_bytes": 0,
        }
    (out / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# MediaFire — пряма адреса Sonic TV",
        "",
        f"- **Статус:** {result['status']}",
        f"- **Сторінка:** {result['source']}",
        f"- **Прямий URL:** {result['direct_download_url'] or 'Не знайдено'}",
        f"- **Діагностика:** {result['reason']}",
        "- **Файл APK не завантажувався.**",
        "",
        "**Увага:** пряма адреса MediaFire може швидко перестати діяти. "
        "Знайдений URL не підтверджує, що файл безпечний.",
    ]
    (out / "RESULT_UA.md").write_text("\n".join(lines), encoding="utf-8")
    print("STATUS:", result["status"], flush=True)
    print("REASON:", result["reason"], flush=True)
    print("DIRECT LINK:", result["direct_download_url"] or "NONE", flush=True)
    return 0 if result["status"] != "error" else 2


if __name__ == "__main__":
    raise SystemExit(main())

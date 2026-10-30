#!/usr/bin/env python3
"""Original ShortxLinks browser-chain investigator. No third-party bypasser.

Uses Microsoft's Playwright for an isolated Chromium/Chrome session.
Never enters credentials, solves CAPTCHA or accepts downloads.
"""
from __future__ import annotations

import argparse
import base64
import binascii
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlparse

SOURCE = "https://shortxlinks.in/8ciL1"
INTERMEDIARIES = {
    "shortxlinks.in", "shortxlinks.com", "mtc1.rbprompt.in",
    "mtc1.thedayspring.in", "mtc1.ibapam.in",
    "mtc1.youtubewalababa.com",
}


def decode_safelink_redirect(url: str) -> dict:
    """Decode metadata only. Do not execute any data from a redirect."""
    try:
        raw = parse_qs(urlparse(url).query).get("safelink_redirect", [""])[0]
        if not raw or len(raw) > 16000:
            return {}
        data = base64.b64decode(raw + "=" * (-len(raw) % 4), validate=True)
        parsed = json.loads(data.decode("utf-8"))
        if not isinstance(parsed, dict):
            return {}
        return {k: v for k, v in parsed.items()
                if k in ("safelink", "second_safelink_url")
                and isinstance(v, str) and len(v) < 4000}
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
        return {}


def safe_url(raw: str) -> bool:
    try:
        p = urlparse(raw)
        return (p.scheme in ("http", "https") and bool(p.hostname)
                and not p.username and not p.password)
    except ValueError:
        return False


def key_of(url: str) -> str:
    """Ignore token changes when looking for a loop."""
    try:
        p = urlparse(url)
        return (p.hostname or "").lower() + p.path.rstrip("/")
    except ValueError:
        return "invalid"


def short_url(url: str) -> str:
    """Suppress query strings and tokens from CI logs."""
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.hostname}{p.path}"[:230]
    except ValueError:
        return "invalid"


def is_intermediary(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
        return host in INTERMEDIARIES or host.startswith("mtc1.")
    except ValueError:
        return False


def get_controls(page):
    return page.evaluate("""() => Array.from(
      document.querySelectorAll('a, button, input[type=submit]')
    ).slice(0, 350).map((e) => {
      const r = e.getBoundingClientRect();
      const c = window.getComputedStyle(e);
      return {
        tag: e.tagName.toLowerCase(),
        id: e.id || '',
        cls: String(e.className || '').slice(0,120),
        text: String(e.innerText || e.value || e.getAttribute('alt') || '').trim().slice(0,100),
        href: e.href || '',
        onclick: String(e.getAttribute('onclick') || '').slice(0,750),
        visible: r.width > 2 && r.height > 2 &&
                 c.visibility !== 'hidden' && c.display !== 'none'
      };
    })""")


def choose_control(controls):
    """Choose only recognisable safe-link controls; ignore generic ad bait."""
    chosen = []
    for i, a in enumerate(controls):
        if not a.get("visible"):
            continue
        aid = a.get("id", "").lower()
        cls = a.get("cls", "").lower()
        href = a.get("href", "")
        txt = a.get("text", "").lower()
        onclick = a.get("onclick", "").lower()
        score = -1
        if aid == "wpsafelinkhuman" or "wpsafehuman()" in onclick:
            score = 100
        elif "safelink_redirect=" in href or "safelink_redirect=" in onclick:
            score = 95
        elif aid in ("get-link", "getlink", "btn-main", "skip-link"):
            score = 75
        elif ("wpsafe" in aid or "wpsafe" in cls) and re.search(
                r"get link|download|generate|continue", txt):
            score = 70
        elif txt in ("get link", "generate link", "click to verify",
                     "click here to verify"):
            score = 35
        elif "download link" in txt and ("wpsafe" in cls or "wpsafe" in aid):
            score = 70
        if score < 0:
            continue
        if score >= 70 and href and safe_url(href) and not is_intermediary(href):
            return {"index": i, "external_candidate": href, "score": score}
        chosen.append({"index": i, "score": score, "name": txt or aid or "control"})
    if not chosen:
        return None
    return sorted(chosen, key=lambda x: x["score"], reverse=True)[0]


def run(source: str, outdir: Path, budget: int, max_clicks: int) -> dict:
    from playwright.sync_api import sync_playwright

    outdir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    trace = []
    visits = Counter()
    report = {
        "source": source, "status": "unresolved", "destination": None,
        "candidate_unverified": None, "reason": "", "actions": trace,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "safety": "No credentials, CAPTCHA solving or accepted downloads."
    }

    def log(kind: str, url: str, detail: str = ""):
        line = {"kind": kind, "url": short_url(url), "detail": detail[:180],
                "seconds": round(time.monotonic() - started, 1)}
        if len(trace) < 100:
            trace.append(line)
        print(f"[{line['seconds']:5.1f}s] {kind}: {line['url']} {line['detail']}",
              flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            channel="chrome", headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(
            accept_downloads=False,
            viewport={"width": 1280, "height": 800},
            locale="en-US")
        page = context.new_page()
        page.set_default_timeout(7000)

        # Capture the URL of an unexpected main-frame navigation BEFORE
        # loading the unknown target. Do not follow it.
        def restrict_navigation(route):
            request = route.request
            try:
                external = (request.is_navigation_request() and
                            request.frame == page.main_frame and
                            safe_url(request.url) and
                            not is_intermediary(request.url))
            except Exception:
                external = False
            if external:
                if not report["candidate_unverified"]:
                    report["candidate_unverified"] = request.url
                    report["status"] = "candidate_unverified"
                    report["reason"] = "Navigation to an unknown external URL was blocked"
                log("EXTERNAL_BLOCKED", request.url)
                route.abort()
            else:
                route.continue_()

        page.route("**/*", restrict_navigation)
        page.on("download", lambda download:
                (log("DOWNLOAD_BLOCKED", download.url), download.cancel()))
        page.on("popup", lambda popup:
                (log("POPUP_CLOSED", popup.url), popup.close()))
        page.on("framenavigated", lambda frame:
                log("NAV", frame.url)
                if frame == page.main_frame and safe_url(frame.url) else None)
        try:
            page.goto(source, wait_until="domcontentloaded", timeout=28000)
            last_action_signature = ""
            action_count = 0
            idle_since = time.monotonic()
            while time.monotonic() - started < budget:
                page.wait_for_timeout(1700)
                if report["status"] == "candidate_unverified":
                    break
                current = page.url
                if not safe_url(current):
                    report["reason"] = "Page has no HTTP(S) URL"
                    break
                k = key_of(current)
                visits[k] += 1
                if visits[k] > 45:
                    report["reason"] = "Repeated same path; stopped"
                    break
                if not is_intermediary(current):
                    report["candidate_unverified"] = current
                    report["status"] = "candidate_unverified"
                    report["reason"] = "Unknown host encountered"
                    break
                captcha_active = page.evaluate("""() =>
                    window.RECAPTCHA_SAFELINK === 'recaptcha' ||
                    window.HCAPTCHA_SAFELINK === 'hcaptcha'
                """)
                if captcha_active:
                    report["reason"] = "Active CAPTCHA; not bypassed"
                    break
                controls = get_controls(page)
                choice = choose_control(controls)
                if choice and "external_candidate" in choice:
                    report["candidate_unverified"] = choice["external_candidate"]
                    report["status"] = "candidate_unverified"
                    report["reason"] = "External candidate found; not opened"
                    break
                if choice and action_count < max_clicks:
                    signature = f"{k}:{choice['index']}:{choice['name']}"
                    if (signature != last_action_signature or
                            time.monotonic() - idle_since > 29):
                        last_action_signature = signature
                        idle_since = time.monotonic()
                        action_count += 1
                        try:
                            log("CLICK", current, choice["name"])
                            page.locator("a, button, input[type=submit]").nth(
                                choice["index"]).click(timeout=5000)
                            page.wait_for_timeout(2200)
                            continue
                        except Exception as exc:
                            log("CLICK_NOT_COMPLETED", current,
                                type(exc).__name__)
                if action_count >= max_clicks:
                    report["reason"] = "Reached click limit"
                    break
                if time.monotonic() - idle_since > 38:
                    report["reason"] = "No supported control progressed for 38 seconds"
                    break
            else:
                report["reason"] = "Time budget reached"
            report["final_seen"] = short_url(page.url)
            report["clicks"] = action_count
            try:
                page.screenshot(path=str(outdir / "last_page.png"),
                                timeout=4000)
            except Exception:
                pass
        finally:
            context.close()
            browser.close()
    return report


def save_report(report: dict, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    dest = (report.get("destination") or
            report.get("candidate_unverified") or "Немає")
    lines = [
        "# ShortxLinks: результат перевірки", "",
        f"- **Статус:** {report['status']}",
        f"- **Початкова адреса:** \`{report['source']}\`",
        f"- **Кандидат на кінцеву адресу:** \`{dest}\`",
        f"- **Пояснення:** {report.get('reason', '—')}", "",
        "Кандидат не означає перевірений або безпечний кінцевий URL.",
        "Скрипт не завантажує кінцевий файл і не долає CAPTCHA.", ""
    ]
    (outdir / "RESULT_UA.md").write_text(
        "\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Original browser URL investigator")
    parser.add_argument("--url", default=SOURCE)
    parser.add_argument("--out", default="result")
    parser.add_argument("--seconds", type=int, default=225)
    parser.add_argument("--max-clicks", type=int, default=10)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        import unittest
        suite = unittest.defaultTestLoader.discover("tests")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 2
    if (not safe_url(args.url) or
            urlparse(args.url).scheme != "https" or
            urlparse(args.url).hostname != "shortxlinks.in"):
        parser.error("Only HTTPS links on shortxlinks.in are supported")
    outdir = Path(args.out)
    try:
        report = run(args.url, outdir,
                     budget=max(30, min(args.seconds, 300)),
                     max_clicks=max(1, min(args.max_clicks, 15)))
    except Exception as exc:
        report = {
            "source": args.url, "status": "error", "destination": None,
            "candidate_unverified": None,
            "reason": f"{type(exc).__name__}: {exc}",
            "actions": []
        }
        print("ERROR", report["reason"])
    save_report(report, outdir)
    print("STATUS:", report["status"], "RESULT DIR:", outdir)
    return 0 if report["status"] != "error" else 2


if __name__ == "__main__":
    raise SystemExit(main())

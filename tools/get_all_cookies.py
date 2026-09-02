"""
Fetch cookies for three accounts in sequence, logging in one by one and saving to individual JSON files.
Usage: python tools/get_all_cookies.py

Cookie filenames are generated dynamically based on the current environment (e.g. cookie_release.json),
ensuring different environments never overwrite each other's cookie files.

Robustness notes:
- Each account is isolated: one failure does NOT abort the remaining accounts.
- browser/context/page are always closed via try/finally, so a timeout on one
  account cannot leak a browser process that interferes with the next account.
- page.goto uses wait_until="domcontentloaded" + retry, because the login page's
  default "load" wait can hang on slow 3rd-party resources, and the release env
  may rate-limit rapid sequential logins from the same IP (causing goto to time out).
"""
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv(Path(__file__).parent.parent / ".env")

PROJECT_ROOT = Path(__file__).parent.parent
COOKIE_DIR = PROJECT_ROOT / "test_case" / "UI" / "Test_Katana"

# Read from BASE_URL environment variable, default to release environment
ENV_BASE = os.environ.get("BASE_URL", "https://release.pear.us")

# Reverse-map domain to environment name for cookie file naming
_ENV_MAP = {
    "https://staging.pear.us": "staging",
    "https://release.pear.us": "release",
    "https://pear.us": "prod",
}
CURRENT_ENV = _ENV_MAP.get(ENV_BASE, "release")

ACCOUNTS = [
    {
        "name": "main (+999)",
        "email": "yuxiao.zhu.ext+999@1m.app",
        "password": "Happy123",
        "cookie_file": f"cookie_{CURRENT_ENV}.json",
    },
    {
        "name": "co-seller (+998)",
        "email": "yuxiao.zhu.ext+998@1m.app",
        "password": "Happy123",
        "cookie_file": f"cookie_{CURRENT_ENV}_co_seller.json",
    },
    {
        "name": "partner co-seller (+997)",
        "email": "yuxiao.zhu.ext+997@1m.app",
        "password": "Happy123",
        "cookie_file": f"cookie_{CURRENT_ENV}_partner_coseller.json",
    },
]

SUBMIT_RETRIES = 3
GOTO_RETRIES = 3
GOTO_TIMEOUT = 20000
BETWEEN_ACCOUNTS_DELAY = 3  # seconds; avoid hammering the login endpoint (rate-limit mitigation)


def _safe_close(obj, label):
    try:
        if obj is not None:
            obj.close()
    except Exception as e:
        print(f"  (warn) failed to close {label}: {e}")


def login_and_save(playwright, account: dict):
    name = account["name"]
    print(f"\n[{name}] Starting login...")
    browser = None
    context = None
    page = None
    try:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Retry navigation: default goto waits for "load", which hangs if any
        # 3rd-party resource stalls; the release env may also rate-limit rapid
        # sequential logins. Use domcontentloaded + retries to absorb both.
        last_err = None
        for attempt in range(1, GOTO_RETRIES + 1):
            try:
                page.goto(f"{ENV_BASE}/login", timeout=GOTO_TIMEOUT, wait_until="domcontentloaded")
                page.wait_for_selector(
                    "input[type='email'], input[name='email'], input[placeholder*='email' i]",
                    timeout=10000,
                )
                break
            except Exception as e:
                last_err = e
                print(f"  [{name}] goto attempt {attempt}/{GOTO_RETRIES} failed: {e}")
                page.wait_for_timeout(2000)
        else:
            page.screenshot(path=f"login_error_{name}.png")
            raise RuntimeError(
                f"[{name}] failed to load login page after {GOTO_RETRIES} attempts: {last_err}"
            )

        page.wait_for_timeout(2000)

        # NOTE (2026-08-31): the email input on the release login page is
        # <input type="text" name="email" placeholder="Email"> -- it is NOT
        # type="email", so any selector relying on input[type='email'] silently
        # matches nothing and the form never validates. Always target by name.
        page.locator("input[name='email']").first.fill(account["email"], timeout=15000)
        page.locator("input[type='password']").first.fill(account["password"], timeout=15000)

        # The form validates on blur (react-hook-form mode:'onBlur'). Without a
        # blur the submit handler sees a stale isValid=false and the click is a
        # silent no-op (zero network requests). Tab off the password field first.
        page.keyboard.press("Tab")
        page.wait_for_timeout(800)

        values = page.evaluate(
            "() => Array.from(document.querySelectorAll('input'))"
            ".map(i => i.name + '=' + (i.type === 'password' ? '***' : i.value))"
        )
        print(f"  [{name}] field values before submit: {values}")

        # Retry the submit: the first click occasionally lands before React has
        # committed the validated state, so re-blur and click again.
        last_url = page.url
        for attempt in range(1, SUBMIT_RETRIES + 1):
            clicked = page.evaluate(
                """() => {
                const b = Array.from(document.querySelectorAll('button')).find(
                    x => (x.innerText||'').trim() === 'Log in');
                if (!b) return false;
                b.setAttribute('data-login-submit','1');
                return true;
            }"""
            )
            if not clicked:
                raise RuntimeError(f"[{name}] 'Log in' button not found")
            page.locator("[data-login-submit='1']").click(timeout=10000)
            try:
                page.wait_for_url(lambda url: "/login" not in url, timeout=25000)
                break
            except Exception:
                print(f"  [{name}] submit attempt {attempt}/{SUBMIT_RETRIES} "
                      f"stayed on {page.url}")
                if attempt == SUBMIT_RETRIES:
                    page.screenshot(path=f"login_error_{name}.png")
                    raise RuntimeError(
                        f"[{name}] still on login page after {SUBMIT_RETRIES} "
                        f"submit attempts (fields: {values})"
                    )
                # re-blur to re-trigger validation, then try again
                page.keyboard.press("Tab")
                page.wait_for_timeout(1500)

        cookie_path = COOKIE_DIR / account["cookie_file"]
        context.storage_state(path=str(cookie_path))
        print(f"[{name}] Cookie saved -> {cookie_path}")
    finally:
        # Always clean up, regardless of success/failure, so a failed account
        # cannot leak a browser that interferes with the next account.
        _safe_close(page, "page")
        _safe_close(context, "context")
        _safe_close(browser, "browser")


def main():
    print("=== Starting bulk cookie collection ===")
    results = []
    with sync_playwright() as pw:
        for i, account in enumerate(ACCOUNTS):
            try:
                login_and_save(pw, account)
                results.append((account["name"], "OK"))
            except Exception as e:
                print(f"!!! [{account['name']}] FAILED: {e}")
                results.append((account["name"], f"FAILED: {e}"))
            # Delay between accounts to avoid hammering the login endpoint
            # (rate-limiting on the release env can cause subsequent gotos to hang).
            if i < len(ACCOUNTS) - 1:
                print(f"  (waiting {BETWEEN_ACCOUNTS_DELAY}s before next account...)")
                time.sleep(BETWEEN_ACCOUNTS_DELAY)

    print("\n=== Cookie collection summary ===")
    for name, status in results:
        print(f"  {name}: {status}")

    failed = [n for n, s in results if s != "OK"]
    if failed:
        print(f"\nWARNING: {len(failed)} account(s) failed: {failed}")
        sys.exit(1)
    print("\n=== All accounts completed ===")


if __name__ == "__main__":
    main()

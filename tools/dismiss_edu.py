"""
Dismiss EDU popups for three accounts on various pages.
Relies on existing cookie files, logs in via storage_state — no password needed.
Usage: python tools/dismiss_edu.py

Cookie filenames and URLs are resolved dynamically from the BASE_URL environment variable.
"""
import os
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
ACCOUNT_ENV = _ENV_MAP.get(ENV_BASE, "release")

ACCOUNTS = [
    {
        "name": "main (+999)",
        "cookie_file": f"cookie_{ACCOUNT_ENV}.json",
        "home_url": f"{ENV_BASE}/autotestshop",
    },
    {
        "name": "co-seller (+998)",
        "cookie_file": f"cookie_{ACCOUNT_ENV}_co_seller.json",
        "home_url": f"{ENV_BASE}/autotest-coseller",
    },
    {
        "name": "partner co-seller (+997)",
        "cookie_file": f"cookie_{ACCOUNT_ENV}_partner_coseller.json",
        "home_url": f"{ENV_BASE}/partnercoseller997",
    },
]


def dismiss_edu_popups(page: "Page", retries: int = 5) -> None:
    """Click away all EDU popup buttons that may appear on the page (Next / Save / Got it / Done / Try it now)."""
    for _ in range(retries):
        clicked = False
        for text in ("Next", "Save", "Got it", "Done"):
            try:
                page.locator("button").filter(has_text=text).click(timeout=800)
                clicked = True
            except Exception:
                pass
        if not clicked:
            break
    try:
        page.get_by_role("button", name="Try it now").click(timeout=800)
    except Exception:
        pass

    # Dismiss the "Your shop is ready" onboarding modal (new-account feature)
    try:
        page.get_by_role("button", name="I'll do it later").click(timeout=800)
    except Exception:
        pass
    try:
        page.get_by_role("button", name="No, take me to my shop").click(timeout=800)
    except Exception:
        pass


def handle_create_post_edu(page: "Page", base_url: str) -> None:
    """Trigger Post EDU by navigating directly to create page and adding a product.
    Works universally across all accounts regardless of existing Post cards.
    After dismissing EDU, closes the draft without saving.
    """
    # Close any blocking modal first ("Your shop is ready" etc.)
    try:
        page.get_by_role("button", name="Close").click(timeout=800)
        page.wait_for_timeout(200)
    except Exception:
        pass

    # Navigate directly to create post page via URL
    try:
        page.goto(f"{base_url}/post/create", timeout=30000)
        page.wait_for_timeout(800)
        dismiss_edu_popups(page)
    except Exception:
        pass

    # Dismiss "Creating a post for one of your events?" dialog — always choose No
    # (accounts with events would get redirected to event post flow if Yes is chosen)
    try:
        page.get_by_role("button", name="No").click(timeout=800)
        page.wait_for_timeout(200)
    except Exception:
        pass

    # Step through the post creation wizard EDU steps
    for btn_name in ("Next", "Next", "Start Creating"):
        try:
            page.get_by_role("button", name=btn_name).click(timeout=1500)
            page.wait_for_timeout(200)
            dismiss_edu_popups(page)
        except Exception:
            pass

    # allow Promoters Resell
    try:
        page.get_by_role("checkbox", name="allowPromotersResell").click(timeout=1000)
        page.wait_for_timeout(200)
        dismiss_edu_popups(page)
    except Exception:
        pass

    
    # Click enhance CTA to trigger product-selection EDU
    try:
        page.get_by_test_id("enhance-button-cta").click(timeout=1000)
        page.wait_for_timeout(200)
        dismiss_edu_popups(page)
    except Exception:
        pass

    #Click enhance CTA to trigger product-selection EDU
    try:
        page.get_by_test_id("ExpandMoreIcon").click(timeout=2000)
        page.wait_for_timeout(200)
        dismiss_edu_popups(page)
    except Exception:
        pass

    # Select a product image to trigger product EDU
    try:
        #page.get_by_role("img", name="Image of Product").first.click(timeout=1500)
        page.get_by_test_id("SquareLineIcon").first.click(timeout=1000)
        page.wait_for_timeout(200)
        dismiss_edu_popups(page)
    except Exception:
        pass

    # Confirm adding the product
    try:
        page.get_by_role("button", name="Add 1/20 product(s)").click(timeout=1000)
        page.wait_for_timeout(200)
        dismiss_edu_popups(page)
    except Exception:
        pass

    # Dismiss "You've added products" EDU popup — check "Do not show me this again" first, then close
    try:
        # Check the "Do not show me this again" checkbox
        page.get_by_role("checkbox", name="Do not show me this again").check(timeout=1500)
        page.wait_for_timeout(200)
    except Exception:
        pass
    try:
        # Click the X button to close the EDU popup
        page.locator("[data-testid='CloseIcon']").first.click(timeout=800)
        page.wait_for_timeout(200)
    except Exception:
        pass

    # Close the post editor without saving (go back to storefront)
    try:
        page.get_by_role("button", name="Close").click(timeout=800)
        page.wait_for_timeout(200)
    except Exception:
        pass
    try:
        page.get_by_role("button", name="Discard").click(timeout=800)
        page.wait_for_timeout(200)
    except Exception:
        pass


def handle_selling_customize(page: "Page") -> None:
    """Selling tab → Customize products page EDU handling flow."""
    try:
        page.get_by_role("tab", name="Selling", exact=True).click(timeout=1500)
        page.wait_for_timeout(300)
        dismiss_edu_popups(page)
    except Exception:
        pass

    # The button label on the Selling page is just "Customize" (not "Customize products"),
    # so we use a regex match — old code's exact match silently failed and downstream
    # "Done" clicks never ran, leaving "Choose a resale model" EDU un-dismissed.
    # try:
    #     import re
    #     page.get_by_role("button", name=re.compile(r"^Customize$", re.I)).first.click(timeout=1500)
    #     page.wait_for_timeout(300)
    #     dismiss_edu_popups(page)
    # except Exception:
    #     pass

    # After clicking Customize, the "Choose a resale model" EDU popover can appear
    # before the user hits "Start Customizing". Dismiss it eagerly here so it doesn't
    # cover the actual Start Customizing button.
    try:
        page.get_by_role("button", name="Start Customizing").click(timeout=1500)
        page.wait_for_timeout(300)
        dismiss_edu_popups(page)
    except Exception:
        pass

    try:
        page.get_by_role("checkbox").check(timeout=800)
    except Exception:
        pass

    # "Choose a resale model" EDU: popover over the editor area; the Done button lives
    # inside a Popover. Click it up to 4× in case the user model choices advance the popup.
    for _ in range(4):
        try:
            page.locator("button").filter(has_text="Done").first.click(timeout=800)
            page.wait_for_timeout(200)
            dismiss_edu_popups(page)
        except Exception:
            break

    try:
        page.get_by_role("button", name="Save").click(timeout=1500)
    except Exception:
        pass

    try:
        page.get_by_role("button", name="Close").click(timeout=800)
    except Exception:
        pass


def handle_customers(page: "Page") -> None:
    """Customers → Followers page EDU handling."""
    try:
        page.goto(f"{ENV_BASE}/customers", timeout=60000)
        page.wait_for_timeout(2000)
        dismiss_edu_popups(page)
    except Exception:
        pass

    try:
        page.get_by_role("tab", name="Followers").click(timeout=5000)
        page.wait_for_timeout(1000)
        dismiss_edu_popups(page)
    except Exception:
        pass

    try:
        page.get_by_role("button", name="Close").click(timeout=3000)
    except Exception:
        pass


def dismiss_for_account(playwright, account: dict):
    name = account["name"]
    cookie_path = COOKIE_DIR / account["cookie_file"]
    home_url = account["home_url"]

    if not cookie_path.exists():
        print(f"[{name}] Cookie file not found, skipping: {cookie_path}")
        return

    print(f"\n[{name}] Loading cookie, starting EDU dismissal...")

    browser = playwright.chromium.launch(headless=False)
    # Load authenticated state via storage_state (not add_init_script)
    context = browser.new_context(storage_state=str(cookie_path))
    page = context.new_page()

    # ── ① Shop home page EDU ──
    page.goto(home_url, timeout=60000)
    page.wait_for_timeout(1500)
    dismiss_edu_popups(page)
    page.wait_for_timeout(500)
    dismiss_edu_popups(page)

    # ── ② Create a Post to trigger Post-related EDU (universal across all accounts) ──
    handle_create_post_edu(page, ENV_BASE)

    # ── ③ Selling tab → Customize products ──
    handle_selling_customize(page)

    # ── ④ Customers → Followers ──
    handle_customers(page)

    # ── ⑤ Return to storefront to finish up ──
    page.goto(home_url, timeout=60000)
    page.wait_for_timeout(1500)
    dismiss_edu_popups(page)
    page.wait_for_timeout(500)
    dismiss_edu_popups(page)

    # ── Save cookie after EDU processing ──
    context.storage_state(path=str(cookie_path))
    print(f"[{name}] EDU dismissal complete, cookie updated -> {cookie_path}")

    page.close()
    context.close()
    browser.close()


def main():
    print("=== Starting EDU popup dismissal ===")
    with sync_playwright() as pw:
        for account in ACCOUNTS:
            dismiss_for_account(pw, account)
    print("\n=== All accounts processed ===")


if __name__ == "__main__":
    main()

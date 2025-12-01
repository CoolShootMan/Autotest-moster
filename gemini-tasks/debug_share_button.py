"""
Debug script to inspect the Share button
"""
from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        iphone_12 = p.devices['iPhone 12 Pro']
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            **iphone_12,
            storage_state=r"..\test_case\UI\Test_Katana\cookie_release.json"
        )
        page = context.new_page()
        
        try:
            print("=== Debugging: Share Button ===\n")
            
            page.goto("https://release.pear.us/yu-xiao", timeout=60000)
            page.wait_for_timeout(5000)
            
            print("\n=== Inspecting 'Share' buttons ===")
            
            # Method 1: get_by_role
            print("\nMethod 1: page.get_by_role('button', name='Share')")
            buttons_role = page.get_by_role("button", name="Share").all()
            print(f"Found {len(buttons_role)} buttons with role='button' and name='Share'")
            for i, btn in enumerate(buttons_role):
                print(f"  Button {i}: visible={btn.is_visible()}")

            # Method 2: text match
            print("\nMethod 2: page.get_by_text('Share')")
            buttons_text = page.get_by_text("Share").all()
            print(f"Found {len(buttons_text)} elements with text='Share'")
            for i, btn in enumerate(buttons_text):
                print(f"  Element {i}: tag={btn.evaluate('el => el.tagName')}, visible={btn.is_visible()}")

            # Method 3: button tag with text
            print("\nMethod 3: page.locator('button:has-text(\"Share\")')")
            buttons_tag = page.locator('button:has-text("Share")').all()
            print(f"Found {len(buttons_tag)} <button> with text='Share'")
            for i, btn in enumerate(buttons_tag):
                print(f"  Button {i}: visible={btn.is_visible()}")

            page.screenshot(path="debug_share_button.png")
            print("\nScreenshot saved to debug_share_button.png")
            
            print("\nPress Enter to close browser...")
            input()
            
        except Exception as e:
            print(f"\nError: {e}")
            page.screenshot(path="debug_error.png")
        finally:
            context.close()
            browser.close()

if __name__ == "__main__":
    run()

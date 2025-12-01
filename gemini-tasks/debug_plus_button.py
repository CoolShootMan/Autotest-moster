"""
Debug script to find the correct + button for creating a new post
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
            print("=== Debugging: Finding + button ===\n")
            
            page.goto("https://release.pear.us/yu-xiao", timeout=60000)
            page.wait_for_timeout(5000)
            
            print("\n1. Looking for all buttons on the page...")
            all_buttons = page.locator('button').all()
            print(f"   Found {len(all_buttons)} buttons total")
            
            print("\n2. Looking for buttons with '+' or 'Add' text...")
            for i, btn in enumerate(all_buttons):
                try:
                    text = btn.inner_text()
                    if '+' in text or 'Add' in text or 'add' in text or text.strip() == '':
                        is_visible = btn.is_visible()
                        print(f"   Button {i}: text='{text}', visible={is_visible}")
                        if is_visible:
                            # Get button attributes
                            aria_label = btn.get_attribute('aria-label')
                            role = btn.get_attribute('role')
                            name = btn.get_attribute('name')
                            print(f"      aria-label='{aria_label}', role='{role}', name='{name}'")
                except:
                    pass
            
            print("\n3. Looking for button with name='0'...")
            try:
                btn_zero = page.get_by_role("button", name="0", exact=True).all()
                print(f"   Found {len(btn_zero)} buttons with name='0' (exact)")
                for i, btn in enumerate(btn_zero):
                    text = btn.inner_text()
                    is_visible = btn.is_visible()
                    print(f"   Button {i}: text='{text}', visible={is_visible}")
            except Exception as e:
                print(f"   Error: {e}")
            
            print("\n4. Looking for floating action button (FAB)...")
            try:
                fab_buttons = page.locator('button[class*="Fab"]').all()
                print(f"   Found {len(fab_buttons)} FAB buttons")
                for i, btn in enumerate(fab_buttons):
                    text = btn.inner_text()
                    is_visible = btn.is_visible()
                    aria_label = btn.get_attribute('aria-label')
                    print(f"   FAB {i}: text='{text}', visible={is_visible}, aria-label='{aria_label}'")
            except Exception as e:
                print(f"   Error: {e}")
            
            page.screenshot(path="debug_plus_button.png")
            print("\nScreenshot saved to debug_plus_button.png")
            
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

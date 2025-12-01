"""
Debug script to simulate the complete T1747 flow and find the correct + button
"""
from playwright.sync_api import sync_playwright
import time

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
            print("=== Debugging: Complete T1747 Flow ===\n")
            
            page.goto("https://release.pear.us/yu-xiao", timeout=60000)
            page.wait_for_timeout(5000)
            
            print("\n1. Clicking + button (name='0')...")
            try:
                btn_zero = page.get_by_role("button", name="0", exact=True)
                btn_zero.click()
                page.wait_for_timeout(2000)
                page.screenshot(path="debug_after_plus_click.png")
                print("   Clicked + button. Screenshot saved to debug_after_plus_click.png")
            except Exception as e:
                print(f"   Error clicking + button: {e}")
                return

            print("\n2. Clicking 'Create a Post' link...")
            try:
                create_link = page.get_by_role("link", name="Create a Post").first
                if create_link.is_visible():
                    print("   'Create a Post' link is visible. Clicking...")
                    create_link.click()
                    page.wait_for_timeout(5000) # Wait for navigation
                    
                    current_url = page.url
                    print(f"   Current URL: {current_url}")
                    page.screenshot(path="debug_after_create_click.png")
                    print("   Screenshot saved to debug_after_create_click.png")
                    
                    if "/post/create" in current_url:
                        print("   ✓ SUCCESS: Navigated to CREATE post page")
                    elif "/post/" in current_url and "/edit" in current_url:
                        print("   ✗ FAILURE: Navigated to EDIT post page")
                    else:
                        print(f"   ? Unknown page state: {current_url}")
                else:
                    print("   'Create a Post' link is NOT visible!")
                    page.screenshot(path="debug_menu_not_visible.png")
            except Exception as e:
                print(f"   Error clicking 'Create a Post': {e}")
            
            print("\nPress Enter to close browser...")
            input()
            
        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()
            page.screenshot(path="debug_error.png")
        finally:
            context.close()
            browser.close()

if __name__ == "__main__":
    run()

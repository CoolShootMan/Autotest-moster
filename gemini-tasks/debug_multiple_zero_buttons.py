"""
Debug script to check for multiple buttons with name='0' and find the correct one
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
            print("=== Checking for multiple buttons with name='0' ===\n")
            
            page.goto("https://release.pear.us/yu-xiao", timeout=60000)
            page.wait_for_timeout(5000)
            
            print("1. Finding all buttons with name='0' (exact)...")
            buttons_zero = page.get_by_role("button", name="0", exact=True).all()
            print(f"   Found {len(buttons_zero)} buttons with name='0'\n")
            
            for i, btn in enumerate(buttons_zero):
                try:
                    text = btn.inner_text()
                    is_visible = btn.is_visible()
                    bbox = btn.bounding_box()
                    
                    print(f"   Button {i}:")
                    print(f"      text: '{text}'")
                    print(f"      visible: {is_visible}")
                    if bbox:
                        print(f"      position: x={bbox['x']}, y={bbox['y']}")
                        print(f"      size: width={bbox['width']}, height={bbox['height']}")
                    
                    # Get parent element info
                    parent = btn.locator('xpath=..')
                    parent_class = parent.get_attribute('class')
                    print(f"      parent class: {parent_class}")
                    
                    # Check if it's at the bottom (likely the + button)
                    if bbox and bbox['y'] > 600:
                        print(f"      >>> This is likely the + button at the bottom!")
                    
                    print()
                except Exception as e:
                    print(f"      Error inspecting button {i}: {e}\n")
            
            print("\n2. Looking for the bottom navigation bar...")
            # Try to find the bottom nav/toolbar
            bottom_elements = [
                'nav[class*="bottom"]',
                '[class*="BottomNav"]',
                '[class*="bottom-nav"]',
                'footer',
                '[role="navigation"]'
            ]
            
            for selector in bottom_elements:
                try:
                    elements = page.locator(selector).all()
                    if elements:
                        print(f"   Found {len(elements)} elements matching '{selector}'")
                        for elem in elements:
                            if elem.is_visible():
                                bbox = elem.bounding_box()
                                if bbox and bbox['y'] > 500:
                                    print(f"      Found bottom element at y={bbox['y']}")
                                    # Look for button inside this element
                                    inner_buttons = elem.locator('button').all()
                                    print(f"      Contains {len(inner_buttons)} buttons")
                except:
                    pass
            
            page.screenshot(path="debug_multiple_buttons.png")
            print("\nScreenshot saved to debug_multiple_buttons.png")
            
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

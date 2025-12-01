from playwright.sync_api import sync_playwright
import re

def run():
    with sync_playwright() as p:
        # Use iPhone 12 Pro emulation to match test environment
        iphone_12 = p.devices['iPhone 12 Pro']
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            **iphone_12,
            storage_state=r"test_case\UI\Test_Katana\cookie_release.json"
        )
        page = context.new_page()
        
        try:
            print("=== Finding PRODUCT CARD Locator ===\n")
            
            print("Step 1: Navigating to shop page...")
            page.goto("https://release.pear.us/yu-xiao", timeout=60000)
            page.wait_for_timeout(5000)
            
            print("\nStep 2: Clicking SVG icon...")
            page.locator(".MuiSvgIcon-root.MuiSvgIcon-fontSizeMedium.shop-text-color").first.click()
            page.wait_for_timeout(2000)
            
            print("\nStep 3: Clicking 'Products'...")
            page.locator("#simple-popover").get_by_text("Products", exact=True).click()
            page.wait_for_timeout(2000)
            
            print("\nStep 4: Looking for PRODUCT cards (not POST cards)...")
            
            # Scroll down to see products
            page.evaluate("window.scrollBy(0, 300)")
            page.wait_for_timeout(1000)
            
            # Test different selectors for product cards
            print("\n   Testing selector: div[data-index]")
            cards1 = page.locator('div[data-index]').all()
            print(f"   Found {len(cards1)} cards with data-index")
            if len(cards1) > 0:
                for i in range(min(5, len(cards1))):
                    try:
                        bbox = cards1[i].bounding_box()
                        data_index = cards1[i].get_attribute('data-index')
                        print(f"   Card {i}: data-index={data_index}, y={bbox['y'] if bbox else 'N/A'}, height={bbox['height'] if bbox else 'N/A'}")
                    except Exception as e:
                        print(f"   Card {i}: Error - {e}")
            
            print("\n   Testing selector: .MuiBox-root[data-index]")
            cards2 = page.locator('.MuiBox-root[data-index]').all()
            print(f"   Found {len(cards2)} cards with MuiBox-root[data-index]")
            if len(cards2) > 0:
                heights = []
                for i in range(min(10, len(cards2))):
                    try:
                        bbox = cards2[i].bounding_box()
                        if bbox:
                            heights.append(bbox['height'])
                            print(f"   Card {i}: y={bbox['y']}, height={bbox['height']}")
                    except Exception as e:
                        print(f"   Card {i}: Error - {e}")
                
                if len(heights) > 1:
                    unique_heights = set(heights)
                    print(f"\n   Unique heights: {unique_heights}")
                    print(f"   Number of unique heights: {len(unique_heights)}")
                    if len(unique_heights) > 1:
                        print(f"   ✅ SUCCESS: Products have different heights!")
                        print(f"   Height range: {min(heights)}px - {max(heights)}px")
            
            page.screenshot(path="debug_product_cards_correct.png")
            print("\n   Screenshot saved to debug_product_cards_correct.png")
            
            print("\n=== Waiting for user to inspect ===")
            print("Press Enter to close browser...")
            input()
            
        except Exception as e:
            print(f"FAILURE: Error during debugging: {e}")
            import traceback
            traceback.print_exc()
        finally:
            context.close()
            browser.close()

if __name__ == "__main__":
    run()

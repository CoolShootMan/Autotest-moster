from playwright.sync_api import sync_playwright
from loguru import logger

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(
        storage_state="test_case/UI/Test_Katana/cookie_release.json",
        **p.devices['iPhone 12 Pro']
    )
    page = context.new_page()
    
    logger.info("1. Opening shop page...")
    page.goto("https://release.pear.us/yu-xiao", wait_until="networkidle")
    page.wait_for_timeout(3000)
    
    logger.info("2. Clicking shop icon...")
    page.locator(".MuiSvgIcon-root.MuiSvgIcon-fontSizeMedium.shop-text-color").first.click()
    page.wait_for_timeout(1000)
    
    logger.info("3. Clicking Products in popover...")
    page.locator("#simple-popover").get_by_text("Products", exact=True).click()
    page.wait_for_timeout(3000)
    
    logger.info("4. Checking different selectors...")
    
    # Test MuiStack-root
    mui_stack = page.locator('.MuiStack-root').all()
    logger.info(f"   .MuiStack-root: Found {len(mui_stack)} elements")
    
    # Test MuiBox-root with data-index
    mui_box_index = page.locator('.MuiBox-root[data-index]').all()
    logger.info(f"   .MuiBox-root[data-index]: Found {len(mui_box_index)} elements")
    
    # Test product links
    product_links = page.locator('a[href*="/p/product/"]').all()
    logger.info(f"   a[href*=\"/p/product/\"]: Found {len(product_links)} elements")
    
    # Test combination
    stack_with_link = page.locator('.MuiStack-root:has(a[href*="/p/product/"])').all()
    logger.info(f"   .MuiStack-root:has(a[href*=\"/p/product/\"]): Found {len(stack_with_link)} elements")
    
    # Dump HTML to inspect
    logger.info("5. Dumping HTML for inspection...")
    with open("gemini-tasks/product_cards_dom.html", "w", encoding="utf-8") as f:
        f.write(page.content())
    
    logger.info("6. Taking screenshot...")
    page.screenshot(path="gemini-tasks/product_cards_screenshot.png")
    
    logger.info("Done! Check product_cards_dom.html and product_cards_screenshot.png")
    
    browser.close()

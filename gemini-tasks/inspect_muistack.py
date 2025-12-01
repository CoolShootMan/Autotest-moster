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
    
    logger.info("4. Getting all MuiStack-root elements...")
    all_stacks = page.locator('.MuiStack-root').all()
    logger.info(f"   Total MuiStack-root elements: {len(all_stacks)}")
    
    # Get first 5 visible ones and check their properties
    visible_count = 0
    for i, stack in enumerate(all_stacks):
        if visible_count >= 5:
            break
        if stack.is_visible():
            bbox = stack.bounding_box()
            if bbox and bbox.get("height", 0) > 0:
                visible_count += 1
                logger.info(f"\n   Visible MuiStack-root #{visible_count}:")
                logger.info(f"      Index: {i}")
                logger.info(f"      Height: {bbox['height']}px")
                logger.info(f"      Width: {bbox['width']}px")
                logger.info(f"      Y position: {bbox['y']}")
                
                # Check if it has product link inside
                has_product_link = stack.locator('a[href*="/p/product/"]').count() > 0
                logger.info(f"      Has product link: {has_product_link}")
                
                # Get class names
                class_attr = stack.get_attribute("class")
                logger.info(f"      Classes: {class_attr}")
    
    logger.info("\n5. Taking screenshot...")
    page.screenshot(path="gemini-tasks/muistack_debug.png")
    
    logger.info("Done!")
    input("Press Enter to close browser...")
    browser.close()

import logging
from playwright.sync_api import sync_playwright

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    iphone_12 = p.devices['iPhone 12 Pro']
    context = browser.new_context(
        storage_state="test_case/UI/Test_Katana/cookie_release.json",
        **iphone_12
    )
    page = context.new_page()
    
    logger.info("1. Navigating to shop page...")
    page.goto("https://release.pear.us/yu-xiao", wait_until="networkidle")
    page.wait_for_timeout(3000)
    
    logger.info("2. Finding all role='tab' elements...")
    tabs = page.get_by_role("tab").all()
    logger.info(f"   Found {len(tabs)} tabs")
    for i, tab in enumerate(tabs):
        try:
            text = tab.inner_text()
            visible = tab.is_visible()
            logger.info(f"   [{i}] '{text}' - Visible: {visible}")
        except:
            logger.info(f"   [{i}] (Cannot read)")
    
    # Capture console messages
    page.on("console", lambda msg: logger.info(f"Console: {msg.text}"))

    # Intercept network responses
    def handle_response(response):
        if "promoter/product" in response.url and response.status == 200:
            try:
                json_body = response.json()
                logger.info(f"API Response for {response.url}: {json_body}")
            except:
                pass

    page.on("response", handle_response)

    logger.info("3. Navigating directly to #Products...")
    page.goto("https://release.pear.us/yu-xiao#Products", wait_until="networkidle")
    
    # Wait for the tab to become selected/active
    page.wait_for_timeout(3000)
    
    products_tab = page.get_by_role("tab", name="Products", exact=True)
    if products_tab.count() > 0:
        is_selected = products_tab.get_attribute("aria-selected")
        logger.info(f"Products tab aria-selected: {is_selected}")
        
        # Try clicking it again forcefully just in case
        logger.info("Force clicking Products tab...")
        products_tab.click(force=True)
        page.wait_for_timeout(1000)

        logger.info(f"Current URL before wait: {page.url}")
        logger.info("Waiting for product cards to load (30s timeout)...")
        
        # Try scrolling down to trigger lazy load
        for _ in range(5):
            page.mouse.wheel(0, 1000)
            page.wait_for_timeout(1000)
            
        try:
            # Wait explicitly for at least one product card to appear
            page.wait_for_selector('a[href*="/p/product/"]', timeout=10000)
            logger.info("Product cards selector found!")
        except Exception as e:
            logger.error(f"Timeout waiting for product cards: {e}")
            logger.info(f"Current URL after timeout: {page.url}")

        # Give a little extra time for layout to stabilize
        page.wait_for_timeout(2000)

        # Check for product cards using the new locator
        cards = page.locator('a[href*="/p/product/"]').all()
        logger.info(f"Found {len(cards)} product cards with locator 'a[href*=\"/p/product/\"]'")
        
        if len(cards) > 0:
            logger.info("   ✅ Success! Product cards loaded")
        else:
            logger.info("   ❌ Product cards NOT loaded")
            
            # Debug: List all links to see what's there
            logger.info("   Debugging: Listing all links on the page...")
            all_links = page.locator("a").all()
            for i, link in enumerate(all_links):
                try:
                    href = link.get_attribute("href")
                    text = link.inner_text()
                    if href and len(text) > 0:
                        logger.info(f"   Link [{i}]: Text='{text[:20]}...', Href='{href}'")
                except:
                    pass
            
            # Debug: Print page text content to see if "No posts yet" is the only thing
            body_text = page.locator("body").inner_text()
            logger.info(f"   Body text sample: {body_text[:500]}")

    else:
        logger.info("4. No Products tab, trying popover flow...")
        shop_icon = page.locator(".MuiSvgIcon-root.shop-text-color").first
        if shop_icon.count() > 0:
            logger.info("   Clicking shop icon...")
            shop_icon.click()
            page.wait_for_timeout(2000)
            
            page.locator("#simple-popover").get_by_text("Products", exact=True).click()
            page.wait_for_timeout(3000)
            
            cards = page.locator('a[href*="/p/product/"]')
            logger.info(f"   Found {cards.count()} product cards")
    
    # Save screenshot
    page.screenshot(path="debug_products_wait.png")
    logger.info("Saved screenshot to debug_products_wait.png")
    
    context.close()
    browser.close()

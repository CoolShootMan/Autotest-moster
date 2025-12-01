from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    
    # Load with cookies
    iphone_12 = p.devices['iPhone 12 Pro']
    context = browser.new_context(
        storage_state="../test_case/UI/Test_Katana/cookie_release.json",
        **iphone_12
    )
    page = context.new_page()
    
    print("1. 导航到 storefront settings...")
    page.goto("https://release.pear.us/storefront-modules#Storefront", wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(2000)
    
    print("2. 勾选 Top aligned...")
    page.get_by_label("Top aligned").check(timeout=60000)
    page.wait_for_timeout(1000)
    
    print("3. 点击 Publish...")
    page.get_by_role("button", name="Publish").click()
    page.wait_for_timeout(3000)
    
    print("4. 等待跳转到 shop 页面...")
    try:
        page.wait_for_url("https://release.pear.us/yu-xiao", timeout=10000)
        print("  - 成功跳转")
    except:
        print("  - 跳转超时,手动导航")
        page.goto("https://release.pear.us/yu-xiao", wait_until="networkidle")
    
    page.wait_for_timeout(3000)
    
    print("5. 查找 shop icon...")
    shop_icon = page.locator(".MuiSvgIcon-root.MuiSvgIcon-fontSizeMedium.shop-text-color").first
    print(f"  - 找到 {shop_icon.count()} 个 shop icon")
    print(f"  - 是否可见: {shop_icon.is_visible()}")
    
    if shop_icon.is_visible():
        print("6. 点击 shop icon...")
        shop_icon.click()
        page.wait_for_timeout(2000)
        
        print("7. 检查 popover...")
        popover = page.locator("#simple-popover")
        print(f"  - Popover 可见: {popover.is_visible()}")
        if popover.is_visible():
            print(f"  - Popover 文本: {popover.inner_text()}")
        
        print("8. 点击 Products...")
        products_link = page.locator("#simple-popover").get_by_text("Products", exact=True)
        print(f"  - 找到 {products_link.count()} 个 Products 链接")
        if products_link.count() > 0:
            products_link.click()
            page.wait_for_timeout(3000)
            
            print("9. 检查产品卡片...")
            product_cards = page.locator('.MuiBox-root[data-index]')
            print(f"  - 找到 {product_cards.count()} 个产品卡片")
            
            if product_cards.count() == 0:
                print("  - ⚠️ 没有找到产品卡片!")
                print("  - 当前 URL:", page.url)
                print("  - 截图保存中...")
                page.screenshot(path="debug_t3370_no_cards.png", full_page=True)
            else:
                print(f"  - ✅ 找到 {product_cards.count()} 个产品卡片")
    
    print("\n按 Enter 继续...")
    input()
    
    context.close()
    browser.close()

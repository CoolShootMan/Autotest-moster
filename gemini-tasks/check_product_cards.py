from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    
    iphone_12 = p.devices['iPhone 12 Pro']
    context = browser.new_context(
        storage_state="test_case/UI/Test_Katana/cookie_release.json",
        **iphone_12
    )
    page = context.new_page()
    
    # 直接去 shop 页
    print("导航到 shop 页面...")
    page.goto("https://release.pear.us/yu-xiao", wait_until="networkidle")
    page.wait_for_timeout(3000)
    
    # 点击 shop icon
    print("点击 shop icon...")
    shop_icon = page.locator(".MuiSvgIcon-root.MuiSvgIcon-fontSizeMedium.shop-text-color").first
    if shop_icon.is_visible():
        shop_icon.click()
        page.wait_for_timeout(2000)
        
        # 点击 Products
        print("点击 Products...")
        page.locator("#simple-popover").get_by_text("Products", exact=True).click()
        page.wait_for_timeout(5000)
        
        print("\n检查产品卡定位器:")
        print(f"1. .MuiBox-root[data-index]: {page.locator('.MuiBox-root[data-index]').count()}")
        print(f"2. [data-index]: {page.locator('[data-index]').count()}")
        print(f"3. .MuiBox-root: {page.locator('.MuiBox-root').count()}")
        
        # 如果找到任何带 data-index 的元素,打印其属性
        data_index_els = page.locator('[data-index]').all()
        if len(data_index_els) > 0:
            print(f"\n找到 {len(data_index_els)} 个 [data-index] 元素:")
            for i, el in enumerate(data_index_els[:3]):
                info = page.evaluate('''el => ({
                    tagName: el.tagName,
                    className: el.className,
                    dataIndex: el.getAttribute('data-index'),
                    visible: el.offsetParent !== null
                })''', el.element_handle())
                print(f"  [{i}] {info}")
        else:
            print("\n未找到 [data-index] 元素,保存DOM...")
            with open("shop_products_dom.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            print("已保存 shop_products_dom.html")
        
        page.screenshot(path="shop_products.png", full_page=True)
        print("\n已保存截图: shop_products.png")
    
    print("\n按 Enter 继续...")
    input()
    
    context.close()
    browser.close()

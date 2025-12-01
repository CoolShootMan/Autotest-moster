from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    
    # Load with cookies
    iphone_12 = p.devices['iPhone 12 Pro']
    context = browser.new_context(
        storage_state="test_case/UI/Test_Katana/cookie_release.json",
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
    page.wait_for_timeout(5000)  # Longer wait
    
    print("4. 检查当前 URL...")
    print(f"  - Current URL: {page.url}")
    
    print("5. 查找 shop icon...")
    shop_icon = page.locator(".MuiSvgIcon-root.MuiSvgIcon-fontSizeMedium.shop-text-color")
    print(f"  - 找到 {shop_icon.count()} 个 shop icon")
    if shop_icon.count() > 0:
        print(f"  - 第一个 shop icon 可见: {shop_icon.first.is_visible()}")
        
        print("\n6. 点击 shop icon...")
        shop_icon.first.click()
        page.wait_for_timeout(2000)
        
        print("7. 检查 popover...")
        popover = page.locator("#simple-popover")
        print(f"  - Popover 可见: {popover.is_visible()}")
        if popover.is_visible():
            print(f"  - Popover 内容:\n{popover.inner_text()}")
        
        print("\n8. 点击 Products...")
        products_link = page.locator("#simple-popover").get_by_text("Products", exact=True)
        print(f"  - 找到 {products_link.count()} 个 Products 链接")
        
        if products_link.count() > 0:
            products_link.click()
            print("  - 已点击 Products")
            
            print("\n9. 等待页面加载...")
            page.wait_for_timeout(5000)
            
            print(f"  - 当前 URL: {page.url}")
            
            print("\n10. 检查产品卡片 (各种定位器)...")
            
            # 尝试原始定位器
            cards1 = page.locator('.MuiBox-root[data-index]')
            print(f"  - .MuiBox-root[data-index]: {cards1.count()} 个")
            
            # 尝试只用 data-index
            cards2 = page.locator('[data-index]')
            print(f"  - [data-index]: {cards2.count()} 个")
            
            # 尝试产品容器
            cards3 = page.locator('.product-card, [class*="product"], [class*="Product"]')
            print(f"  - .product-card 等: {cards3.count()} 个")
            
            # 打印页面上所有带 data- 属性的元素
            print("\n11. 查找所有 data-* 属性...")
            data_elements = page.locator('[data-index], [data-id], [data-testid]').all()
            print(f"  - 找到 {len(data_elements)} 个带 data 属性的元素")
            for i, elem in enumerate(data_elements[:5]):  # 只显示前5个
                try:
                    attrs = page.evaluate('''el => {
                        const attrs = {};
                        for (let attr of el.attributes) {
                            if (attr.name.startsWith('data-')) {
                                attrs[attr.name] = attr.value;
                            }
                        }
                        attrs['class'] = el.className;
                        return attrs;
                    }''', elem.element_handle())
                    print(f"  [{i}] {attrs}")
                except:
                    pass
            
            print("\n12. 保存截图和 HTML...")
            page.screenshot(path="debug_t3370_after_products.png", full_page=True)
            with open("debug_t3370_dom.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            print("  - 已保存 debug_t3370_after_products.png")
            print("  - 已保存 debug_t3370_dom.html")
    
    print("\n按 Enter 继续...")
    input()
    
    context.close()
    browser.close()

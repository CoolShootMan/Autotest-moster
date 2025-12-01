import re
from playwright.sync_api import sync_playwright

def debug_contact_form():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        
        # 创建访客上下文
        iphone_12 = p.devices['iPhone 12 Pro']
        context = browser.new_context(**iphone_12)
        page = context.new_page()
        
        print("1. 打开页面...")
        page.goto("https://release.pear.us/yu-xiao")
        page.wait_for_timeout(3000)
        
        print("2. 关闭 follow 弹窗...")
        try:
            close_btn = page.locator('button[aria-label="Close"]')
            if close_btn.is_visible():
                close_btn.click()
                print("   - 弹窗已关闭")
                page.wait_for_timeout(1000)
        except Exception as e:
            print(f"   - 关闭弹窗失败: {e}")

        print("2.5. 滚动到底部...")
        page.keyboard.press("End")
        page.wait_for_timeout(3000)
        
        print("3. 点击联系表单区域...")
        try:
            # 打印页面上的所有可见文本，帮助定位
            print("   - 正在查找页面上的文本...")
            visible_texts = page.locator("body").inner_text()
            print(f"   - 页面文本预览:\n{visible_texts[:500]}...")
            
            # 尝试查找包含 "Fill" 或 "Send" 的元素
            candidates = page.locator("div, p, span").filter(has_text="Fill").all()
            print(f"   - 包含 'Fill' 的元素: {len(candidates)}")
            for i, elem in enumerate(candidates):
                if elem.is_visible():
                    print(f"     [{i}] '{elem.inner_text()}'")
                    
            # 尝试查找包含 "Auto" 的元素
            candidates = page.locator("div, p, span, h1, h2, h3, h4, h5, h6").filter(has_text="Auto").all()
            print(f"   - 包含 'Auto' 的元素: {len(candidates)}")
            for i, elem in enumerate(candidates):
                if elem.is_visible():
                    print(f"     [{i}] '{elem.inner_text()}'")

            # 之前的定位器
            contact_div = page.locator("div").filter(has_text=re.compile(r"^Fill in the informationSend the message to our email address\.$")).first
            if contact_div.count() > 0:
                contact_div.click()
                print("   - 已点击 (使用旧定位器)")
                page.wait_for_timeout(2000)
            else:
                print("   - 旧定位器未找到元素")
        except Exception as e:
            print(f"   - 点击失败: {e}")
        
        print("4. 查找 Note 字段...")
        try:
            note_field = page.locator('input[name="Note"]')
            print(f"   - 找到 {note_field.count()} 个 Note 字段")
            if note_field.count() > 0:
                print(f"   - 是否可见: {note_field.is_visible()}")
                if note_field.is_visible():
                    note_field.fill("test auto send")
                    print("   - 已填充")
        except Exception as e:
            print(f"   - 错误: {e}")
        
        print("5. 查找 Message 字段...")
        try:
            msg_field = page.locator('textarea[name="Meseege"]')
            print(f"   - 找到 {msg_field.count()} 个 Message 字段")
            if msg_field.count() > 0:
                print(f"   - 是否可见: {msg_field.is_visible()}")
        except Exception as e:
            print(f"   - 错误: {e}")
        
        print("\n6. 截图...")
        print("\n6. 截图...")
        page.screenshot(path="debug_contact_form.png", full_page=True)
        print("   - 截图已保存: debug_contact_form.png")

        print("\n7. 保存 HTML...")
        with open("debug_contact_form.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        print("   - HTML 已保存: debug_contact_form.html")
        
        print("\n按 Enter 继续...")
        input()
        
        context.close()
        browser.close()

if __name__ == "__main__":
    debug_contact_form()

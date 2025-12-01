import asyncio
from playwright.sync_api import sync_playwright
import time

def debug_follow_popup():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        
        # 创建访客上下文(不使用 cookie)
        iphone_12 = p.devices['iPhone 12 Pro']
        context = browser.new_context(**iphone_12)
        page = context.new_page()
        
        print("正在打开页面...")
        page.goto("https://release.pear.us/yu-xiao")
        page.wait_for_timeout(3000)
        
        print("\n检查弹窗状态...")
        
        # 尝试用户提供的 XPath
        xpath1 = "/html/body/div[2]/div[3]/div/section/div[1]/button"
        print(f"\n1. 检查 XPath: {xpath1}")
        try:
            elem1 = page.locator(xpath1)
            print(f"   - 元素数量: {elem1.count()}")
            if elem1.count() > 0:
                print(f"   - 是否可见: {elem1.is_visible()}")
                print(f"   - 文本内容: {elem1.inner_text() if elem1.is_visible() else 'N/A'}")
        except Exception as e:
            print(f"   - 错误: {e}")
        
        # 尝试查找所有可能的关闭按钮
        print("\n2. 查找所有可能的关闭按钮...")
        close_buttons = [
            'button[aria-label="Close"]',
            'button:has-text("×")',
            'button:has-text("Close")',
            '[role="dialog"] button',
            'button.close',
            'button[class*="close"]'
        ]
        
        for selector in close_buttons:
            try:
                elem = page.locator(selector)
                count = elem.count()
                if count > 0:
                    print(f"   - {selector}: 找到 {count} 个")
                    for i in range(min(count, 3)):
                        try:
                            is_visible = elem.nth(i).is_visible()
                            if is_visible:
                                text = elem.nth(i).inner_text()
                                print(f"     第 {i} 个可见, 文本: '{text}'")
                        except:
                            pass
            except Exception as e:
                pass
        
        # 检查是否有 dialog 或 modal
        print("\n3. 检查 dialog/modal...")
        dialogs = page.locator('[role="dialog"], .modal, [class*="modal"], [class*="popup"]')
        print(f"   - 找到 {dialogs.count()} 个 dialog/modal")
        
        # 截图
        print("\n4. 保存截图...")
        page.screenshot(path="debug_follow_popup.png")
        print("   - 截图已保存: debug_follow_popup.png")
        
        # 保存 HTML
        print("\n5. 保存 HTML...")
        with open("debug_follow_popup.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        print("   - HTML 已保存: debug_follow_popup.html")
        
        print("\n按 Enter 继续...")
        input()
        
        context.close()
        browser.close()

if __name__ == "__main__":
    debug_follow_popup()

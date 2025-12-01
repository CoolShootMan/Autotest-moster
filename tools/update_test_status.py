import os
import re
from playwright.sync_api import sync_playwright
from datetime import datetime

def parse_log_for_test_statuses():
    """
    Parses the latest log file for test status entries.
    Returns a dictionary mapping test case ID to status.
    """
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "log")
    
    # Get the latest log file
    log_files = [f for f in os.listdir(log_dir) if f.endswith(".log")]
    if not log_files:
        print("No log files found.")
        return {}
    
    # Sort files by date (assuming YYYY_MM_DD.log format)
    log_files.sort(key=lambda x: datetime.strptime(x.split(".")[0], "%Y_%m_%d"))
    latest_log_file = os.path.join(log_dir, log_files[-1])

    test_results = {}
    with open(latest_log_file, 'r', encoding='utf-8') as f:
        for line in f:
            match = re.search(r"TEST_STATUS: (T\d+) - (passed|failed|skipped)", line)
            if match:
                test_case_id = match.group(1)
                status = match.group(2)
                test_results[test_case_id] = status
    return test_results

def update_ones_test_status(test_results):

    """

    Logs into ones.cn and updates the test case statuses.

    """

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=False)

        context = browser.new_context(viewport={'width': 1920, 'height': 1080}) # Set a larger viewport

        page = context.new_page()

        page.goto("https://ones.cn/identity/login")

        page.get_by_role("textbox", name="* 邮箱").fill("yuxiao.zhu.ext@1m.app")

        page.get_by_role("textbox", name="* 密码").fill("zyx@1032970941")

        page.get_by_role("button", name="登录").click()

        page.get_by_role("link", name="测试管理").click()



        # Navigate to the test plan using fuzzy matching for "smoke testing"

        test_plan_name_regex = re.compile(r"smoke testing", re.IGNORECASE)

        

        # It's better to wait for the element to appear

        page.get_by_text(test_plan_name_regex).first.wait_for(state="visible")

        page.get_by_text(test_plan_name_regex).first.click()

        page.wait_for_load_state("domcontentloaded")



        # Add filtering steps

        page.get_by_text("筛选").click()

        page.locator(".ones-select-selection-overflow").click()

        page.wait_for_timeout(1000) # Give the input field time to appear

        page.locator("#rc_select_6").fill("yuxiao")

        page.get_by_text("YuXiao", exact=True).click()

        page.locator("div").filter(has_text=re.compile(r"^筛选$")).first.click()

        page.wait_for_load_state("domcontentloaded") # Wait for the page to re-load after filtering





        for test_case_id, status in test_results.items():

            print(f"Updating {test_case_id} to {status}")

            try:
                # Scroll down using keyboard to ensure all elements are loaded (lazy loading)
                # This is often more effective for virtual lists than window.scrollTo
                page.keyboard.press("End")
                page.wait_for_timeout(1000)
                page.keyboard.press("End")
                page.wait_for_timeout(1000)
                page.keyboard.press("End") # Do it twice just in case
                page.wait_for_timeout(1000)
                

                # Try to find the row more specifically
                # Assuming it's a table row or a specific item container
                # We can try to find the text element and then go up to the row
                target_text = page.get_by_text(test_case_id, exact=True)
                if target_text.count() > 1:
                    print(f"Warning: Multiple elements found for {test_case_id}")
                    target_text = target_text.first
                
                # Better strategy: Find the row by text, then find checkbox in that row
                # We'll assume the row is a 'tr' or has a specific class, but since we don't know,
                # let's try to find the checkbox relative to the ID text.
                # Often the checkbox is in a preceding sibling or parent's preceding sibling.
                
                # Let's try to find the text, then get the row.
                # Assuming standard ONS layout (Table)
                # Row usually has role="row"
                row = page.get_by_role("row").filter(has_text=test_case_id)
                
                if row.count() == 0:
                    # Fallback to generic div if role="row" doesn't work (e.g. custom div table)
                    row = page.locator("div[class*='table-row']").filter(has_text=test_case_id)
                    
                if row.count() == 0:
                     # Fallback to the original broad locator but take the last one (usually the most specific container?) 
                     # or the first one (top container?). 
                     # Actually, "div:has-text" matches parents too. The most specific one is the last one usually? No, the text node parent.
                     # But we need the ROW (which contains both text and checkbox).
                     # So we want a div that has text AND has a checkbox.
                     row = page.locator("div").filter(has_text=test_case_id).filter(has=page.locator("input[type='checkbox']")).last
                
                if row.count() > 1:
                     print(f"Warning: {row.count()} rows found for {test_case_id}, using first")
                     row = row.first
                
                if row.count() == 0:
                    print(f"Error: Could not find row for {test_case_id}")
                    continue

                checkbox_locator = row.locator("input[type='checkbox']")
                
                # Check if the checkbox is already checked, if not, check it
                if not checkbox_locator.is_checked():
                    checkbox_locator.check()
                
                # Map status to the website's status
                status_map = {
                    "passed": "通过",
                    "failed": "失败",
                    "skipped": "阻塞" 
                }
                website_status = status_map.get(status)

                if website_status:
                    page.get_by_role("button", name="更改执行结果").click()
                    # Use a more specific locator for the status dropdown item within the modal
                    page.locator(".ones-modal-wrap").get_by_text(website_status, exact=True).click()
                    page.get_by_role("button", name="确定").click()
                    page.get_by_role("button", name="确定").wait_for(state="hidden") # Wait for the modal to disappear
                
                if checkbox_locator.is_checked():
                    checkbox_locator.uncheck()

            except Exception as e:
                print(f"Could not update status for {test_case_id}: {e}")



        context.close()

        browser.close()


if __name__ == "__main__":
    results = parse_log_for_test_statuses()
    print("Parsed test results from log:", results)
    if results:
        update_ones_test_status(results)
    else:
        print("No test results found to update.")

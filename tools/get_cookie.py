import time

from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://release.pear.us/login", timeout=90000)
    page.get_by_text("Login with password").click()
    page.get_by_text("Use Email").click()
    #page.get_by_role("textbox", name="Phone number").fill("4086257869")
    #page.get_by_role("textbox", name="Input your password").fill("Xuan123456")
    page.get_by_role("textbox", name="Email").fill("yuxiao.zhu.ext+3@1m.app")
    page.get_by_role("textbox", name="Input your password").fill("Happy123")
    page.get_by_role("button", name="Log in").click()
    # Wait for the URL to change, indicating a successful login and navigation.
    page.wait_for_url(lambda url: "/login" not in url, timeout=60000)

    # Now that login is complete, save the storage state.
    cookies = context.storage_state(path="C:\\Users\\tester\\autotest-monster\\test_case\\UI\\Test_Katana\\cookie_release.json")
    print(cookies)
    page.close()

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)

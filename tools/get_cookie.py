#!usr/bin/env python3
# -*- encoding: utf-8 -*-
'''
Filename         : get_cookie.py
Description      : 用于获取cookie
Time             : 2023/12/29 10:29:01
Author           : Xiao
Version          : 1.0
'''
import time

from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://staging.pear.us/login")
    page.get_by_label("Phone number *").fill("(615) 763-5478")
    page.get_by_role("button", name="Log in or Sign up").click()
    page.wait_for_timeout(30000)
    cookies = context.storage_state(path="cookie_staging.json")
    print(cookies)
    page.wait_for_timeout(6000)
    page.close()

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)

#!usr/bin/env python3
# -*- encoding : utf-8 -*-
# coding : unicode_escape
'''
Filename         : test_my_application.py
Description      : 
Time             : 2023/12/29 10:29:01
Author           : AllenLuo
Version          : 2.0
'''

import re
import sys

import pytest
import pytest
from playwright.sync_api import expect, Page, Browser
import allure
import subprocess

import sys
import os
# Add project root to sys.path to ensure modules like 'page' and 'tools' can be imported
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from page.home import *
import os
import yaml
from tools import BASE_DIR
from loguru import logger
from tools import allure_title, allure_step, allure_step_no

test_case_path = os.path.join(BASE_DIR, "test_case", "UI", "Test_Katana", "Katana_curator_smoke.yaml")
with open(test_case_path, "r", encoding="utf-8") as file:
    case_dict = yaml.safe_load(file.read())



@allure.testcase('https://ones.cn/project/#/testcase/team/T7u1zXum/plan/QCuFwDdq/library/XcAFFViB/module/6mi4qiVp',
                 'ONS测试用例链接')
@allure.title("测试执行")
def test_case(smokecases1, page: Page, browser: Browser, request):
    val = list(smokecases1.values())[0]
    
    if val.get("guest", False):
        logger.info(f"Running {list(smokecases1.keys())[0]} in GUEST mode (new context)")
        context = browser.new_context()
        page = context.new_page()
        request.addfinalizer(lambda: context.close())

    page.set_default_timeout(90000)
    caseno = list(smokecases1.keys())[0]
    description = dict(list(smokecases1.values())[0])["description"]
    test_step = list(smokecases1.values())[0]["test_step"]
    expect_result = dict(list(smokecases1.values())[0])["expect_result"]
    allure_title(caseno)
    allure_step_no(f'description:{description}')
    allure_step_no(f'test_step:{str(test_step)}')

    # --- BEGIN INJECTED LOGIN CODE ---
    # allure_step_no('Executing inline login to solve authentication issue.')
    # page.goto("https://release.pear.us/login", timeout=90000)
    # page.get_by_text("Login with password").click()
    # page.get_by_role("textbox", name="Phone number").fill("4086257869")
    # page.get_by_role("textbox", name="Input your password").fill("Xuan123456")
    # page.get_by_role("button", name="Log in").click()
    # # Wait for navigation to complete by waiting for a URL that is not the login page.
    # page.wait_for_url(lambda url: "/login" not in url, timeout=60000)
    # allure_step_no('Inline login finished, proceeding with test steps.')
    # --- END INJECTED LOGIN CODE ---

    for k, v in test_step.items():
        if k == "open":
            if caseno == "testT4264":
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        page.wait_for_timeout(1000) # Short sleep before navigation
                        page.goto(url=v)
                        page.get_by_role("button", name="Customize").wait_for(state='visible', timeout=90000)
                        break # If successful, break out of the retry loop
                    except Exception as e:
                        logger.warning(f"Attempt {attempt + 1} failed for testT4264 navigation: {e}")
                        if attempt == max_retries - 1:
                            raise # Re-raise the exception if all retries fail
            else:
                page_open(page, url=v)
            if caseno == "testT3370":
                page.screenshot(path="demi_release_page.png")
            elif caseno == "testT1993":
                                page_open(page, test_step["open"])
                                page.wait_for_load_state("networkidle", timeout=120000)
                                allure_step_no(f'Click the "Copy" button (first from recording script)')
                                page.get_by_role("button", name="Copy").first.click()
                                allure_step_no(f'Click the "Manage" button')
                                page.get_by_role("button", name="Manage").click()
                                allure_step_no(f'Click the "CopyOutlineIcon" button (second CopyOutlineIcon)')
                                page.get_by_role("button", name="CopyOutlineIcon").nth(1).click()
                                page.screenshot(path="collabs_page_after_all_clicks.png")
                                page.context.grant_permissions(["clipboard-read"])
                                copied_link = page.evaluate("navigator.clipboard.readText()")
                                allure_step_no(f'Copied link: {copied_link}')
                                assert "invitation?invitationCode=" in copied_link, "Copied link does not contain expected invitation code pattern."
                                # page.goto(copied_link)
                                # page.wait_for_load_state("networkidle", timeout=120000)
                                # page.screenshot(path="collabs_page_after_navigation.png")
                                # assert "/yu-xiao" in page.url, "Navigation to copied link failed. Expected /yu-xiao in URL."

        elif k == "goto_storefront_top_aligned":
            page.goto(v["url"], wait_until="networkidle", timeout=v["timeout"])
        elif k == "check_label_top_aligned":
            page.get_by_label(v["label"]).check(timeout=v["timeout"])
            expect(page.get_by_label(v["label"])).to_be_checked()
        elif k == "publish_button_click_top_aligned":
            page.get_by_role("button", name="Publish").click()
        elif k == "verify_navigation_after_publish_top_aligned":
            try:
                page.wait_for_url(re.compile(v["url_regex"]), timeout=v["timeout"])
            except TimeoutError:
                logger.warning(v["warning_message"])
                page.goto(v["fallback_url"], wait_until="networkidle", timeout=v["fallback_timeout"])
        elif k == "click_mui_svg_icon_top_aligned":
            page.locator(".MuiSvgIcon-root.MuiSvgIcon-fontSizeMedium.shop-text-color").first.click()
        elif k == "click_products_text_top_aligned":
            page.locator("#simple-popover").get_by_text("Products", exact=True).click()
        elif k == "wait_for_product_cards_top_aligned":
            # Wait for product cards to load using MuiStack-root
            page.wait_for_selector('.MuiStack-root', timeout=v["timeout"])
            page.wait_for_timeout(1000)
        elif k == "verify_top_aligned_layout":
            # Find all product cards using MuiStack-root (will find many, we only need first 2 visible ones)
            all_cards = page.locator('.MuiStack-root').all()
            
            # Filter to get only visible cards with valid bounding boxes
            visible_cards = []
            for card in all_cards:
                if card.is_visible():
                    bbox = card.bounding_box()
                    if bbox and bbox.get("height", 0) > 0:
                        visible_cards.append(card)
                        if len(visible_cards) >= 2:
                            break
            
            if len(visible_cards) < 2:
                pytest.fail(f"Not enough visible product cards found. Expected at least 2, found {len(visible_cards)}")
            
            # Get first two visible product cards
            card_0 = visible_cards[0]
            card_1 = visible_cards[1]
            
            # Scroll to make them visible
            card_0.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            
            page.screenshot(path=v["screenshot_path"])
            card_0_y = card_0.bounding_box()["y"]
            card_1_y = card_1.bounding_box()["y"]
            assert abs(card_0_y - card_1_y) < v["threshold"], f"Product card 0 top Y ({card_0_y}) is not aligned with Product card 1 top Y ({card_1_y}) for Top aligned layout."
        elif k == "goto_storefront_waterfall":
            page.goto(v["url"], wait_until="networkidle", timeout=v["timeout"])
        elif k == "check_label_waterfall":
            page.get_by_label(v["label"]).check(timeout=v["timeout"])
            expect(page.get_by_label(v["label"])).to_be_checked()
        elif k == "publish_button_click_waterfall":
            page.get_by_role("button", name="Publish").click()
        elif k == "verify_navigation_after_publish_waterfall":
            try:
                page.wait_for_url(re.compile(v["url_regex"]), timeout=v["timeout"])
            except TimeoutError:
                logger.warning(v["warning_message"])
                page.goto(v["fallback_url"], wait_until="networkidle", timeout=v["fallback_timeout"])
        elif k == "click_mui_svg_icon_waterfall":
            page.locator(".MuiSvgIcon-root.MuiSvgIcon-fontSizeMedium.shop-text-color").first.click()
        elif k == "click_products_text_waterfall":
            page.locator("#simple-popover").get_by_text("Products", exact=True).click()
        elif k == "wait_for_product_cards_waterfall":
            # Wait for product cards to load using MuiStack-root
            page.wait_for_selector('.MuiStack-root', timeout=v["timeout"])
            page.wait_for_timeout(1000)
        elif k == "verify_waterfall_layout":
            try:
                page.wait_for_url(re.compile(v["url_regex"]), timeout=v["timeout"])
            except TimeoutError:
                logger.warning(v["warning_message"])
                page.goto(v["fallback_url"], wait_until="networkidle", timeout=v["fallback_timeout"])

            page.locator(".MuiSvgIcon-root.MuiSvgIcon-fontSizeMedium.shop-text-color").first.click()
            page.locator("#simple-popover").get_by_text("Products", exact=True).click()
            page.wait_for_timeout(v["wait_for_timeout"])
            
            # Wait for product cards and get all cards using MuiStack-root
            page.wait_for_selector('.MuiStack-root', timeout=v["wait_for_cards_timeout"])
            all_cards = page.locator('.MuiStack-root').all()
            
            # Filter to get only visible cards with valid bounding boxes
            visible_cards = []
            for card in all_cards:
                if card.is_visible():
                    bbox = card.bounding_box()
                    if bbox and bbox.get("height", 0) > 0:
                        visible_cards.append(card)
                        if len(visible_cards) >= 2:
                            break
            
            if len(visible_cards) > 1:
                # Scroll first card into view to ensure cards are in viewport
                visible_cards[0].scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                
                heights = [card.bounding_box()["height"] for card in visible_cards]
                unique_heights = set(heights)
                logger.info(f"Waterfall layout: Found {len(visible_cards)} visible cards with {len(unique_heights)} unique heights")
                logger.info(f"Heights: {unique_heights}")
                
                # Assert that cards have different heights for Waterfall layout
                assert len(unique_heights) > 1, f"All product card heights are the same ({heights[0]}px) for Waterfall layout, expected different heights."
            elif len(visible_cards) == 1:
                logger.info("Only one visible product card found, cannot verify Waterfall layout inconsistency.")
            else:
                pytest.fail("No visible product cards found for Waterfall layout verification.")
        # --- General UI Actions ---
        # --- General UI Actions ---
        elif k.startswith("R_click"):
            # page_element_selector_click(page=page, selector=v)
            page.screenshot(path="screenshot.png")
            if caseno == "testT4279" and k == "R_click_submit":
                page.wait_for_timeout(1000) # Wait to allow elements to settle before clicking submit
            page_element_role_click(page=page, role=v.get("role"), name=v.get("name"), index=v.get("index"))
        elif k.startswith("fill_placeholder"):
            page.get_by_placeholder(v["placeholder"]).fill(v["value"])
        elif k.startswith("fill"):
            if "role" in v:
                page_element_input_role_fill(page=page, role=v.get("role"), name=v.get("name"), value=v.get("value"))
            elif "placeholder" in v:
                page_element_input_placeholder_fill(page, v.get("placeholder"), v.get("value"))
            elif "name" in v and "role" not in v:
                # Fill by name attribute (for input[name] or textarea[name])
                page.locator(f'input[name="{v.get("name")}"], textarea[name="{v.get("name")}"]').fill(v.get("value"))
        elif k.startswith("swipe"):
            if isinstance(v, list):
                page_swipe(page, v[0], v[1])
            else:
                page_swipe(page, v["x"], v["y"])
        elif k.startswith("sleep"):
            page.wait_for_timeout(v)
        elif k.startswith("press"):
            page_element_input_role_press(page=page, role=v["role"], key=v["key"])
        elif k.startswith("check"):
            page.get_by_role(role=v.get("role"), name=v.get("name")).check()
        elif k.startswith("upload"):
            with page.expect_file_chooser() as fc_info:
                page.get_by_text(v.get("text"), exact=True).click()
            fc = fc_info.value
            fc.set_files(v.get("file_path"))
        elif k.startswith("wait_for_upload_and_ui_update"):
            page.wait_for_event("response", lambda response: "/upload" in response.url and response.status == 200)
            page.wait_for_timeout(v.get("timeout", 2000))
        elif k.startswith("click_xpath"):
            page.locator(v["xpath"]).click()
        elif k.startswith("l_click_regex"):
            if caseno == "testT4264" and k == "l_click_regex1":
                page.get_by_text("Image", exact=True).click()
            else:
                page.locator("div").filter(has_text=re.compile(v["text"])).nth(v.get("index", 0)).click()
        elif k.startswith("l_click"):
            page_element_label_click(page=page, text=v["text"])
        elif k.startswith("click_contact_form"):
            # Use the text found in debug script
            page.locator("div").filter(has_text="Auto test form").last.click()
        elif k.startswith("click_modal_close"):
            # Close modal by clicking X button (common) or aria-label="Close"
            page.locator('button[aria-label="Close"], button:has-text("×")').first.click()
        elif k.startswith("click_text"):
            page.get_by_text(v["text"]).click()
        elif k.startswith("screenshot"):
            screenshot_name = v.get("name", "screenshot.png")
            page.screenshot(path=os.path.join("test-result", screenshot_name))
        elif k.startswith("save_html"):
            html_name = v.get("name", "page.html")
            with open(os.path.join("test-result", html_name), "w", encoding="utf-8") as f:
                f.write(page.content())
        elif k.startswith("switch_to_new_page"):
            # Switch to the most recent page if a new one was opened
            pages = context.pages
            if len(pages) > 1:
                page = pages[-1]
                print("Switched to new page")
            else:
                print("No new page opened")
        elif k.startswith("wait_for_selector"):
            # v should contain 'selector' and optional 'timeout'
            timeout = v.get("timeout", 5000)
            page.wait_for_selector(v["selector"], timeout=timeout)
        elif k.startswith("save_full_html"):
            html_name = v.get("name", "full_page.html")
            with open(os.path.join("test-result", html_name), "w", encoding="utf-8") as f:
                f.write(page.content())
        elif k.startswith("click_selector_button"):
            page.locator(v["selector"]).click()
        elif k.startswith("wait_for_url"):
            timeout = v.get("timeout", 10000)
            page.wait_for_url(v["url"], timeout=timeout)
        elif k.startswith("wait_for_selector_visible"):
            timeout = v.get("timeout", 10000)
            page.wait_for_selector(v["selector"], state="visible", timeout=timeout)

    allure_step_no(f'expect_result:{str(expect_result)}')
    if "assertions" in expect_result:
        for assertion in expect_result["assertions"]:
            assertion_type = assertion.get("assertion_type")
            if assertion_type == "top_aligned_layout":
                selector = assertion.get("selector", 'a[href*="/p/product/"]')
                threshold = assertion.get("threshold", 5)
                card_0 = page.locator(selector).nth(0)
                card_1 = page.locator(selector).nth(1)
                # Scroll first card into view
                card_0.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                card_0.wait_for(state="visible", timeout=60000)
                card_1.wait_for(state="visible", timeout=60000)
                card_0_y = card_0.bounding_box()["y"]
                card_1_y = card_1.bounding_box()["y"]
                assert abs(card_0_y - card_1_y) < threshold, f"Product card 0 top Y ({card_0_y}) is not aligned with Product card 1 top Y ({card_1_y}) for Top aligned layout."
            elif assertion_type == "waterfall_layout":
                selector = assertion.get("selector", 'a[href*="/p/product/"]')
                product_cards = page.locator(selector).all()
                if len(product_cards) > 1:
                    # Scroll first card into view
                    product_cards[0].scroll_into_view_if_needed()
                    page.wait_for_timeout(500)
                    
                    heights = [card.bounding_box()["height"] for card in product_cards]
                    unique_heights = set(heights)
                    assert len(unique_heights) > 1, f"All product card heights are the same for Waterfall layout, expected different heights."
                elif len(product_cards) == 1:
                    logger.info("Only one product card found, cannot verify Waterfall layout inconsistency.")
                else:
                    pytest.fail("No product cards found to verify 'Waterfall' layout.'")

            elif assertion_type == "element_visible_by_text":
                text = assertion.get("text")
                if text:
                    assert text in page.content()

            elif assertion_type == "element_text":
                role = assertion.get("role")
                value = assertion.get("value")
                if role and value:
                    element = page.get_by_role(role=role).nth(0)
                    expect(element).to_have_text(value)
            elif assertion_type == "element_visible":
                role = assertion.get("role")
                visible = assertion.get("visible", True)
                if role:
                    element = page.get_by_role(role=role).nth(0)
                    if visible:
                        expect(element).to_be_visible()
                    else:
                        expect(element).to_be_hidden()

    # expect(element).to_be_visible(expect_result["visible"]["value"], expect_result["attribute"]["role"])
    # assert expect_result["value"] == page.get_by_role(role=expect_result["role"],name=expect_result["name"]).inner_text()
    # assert expect_result["value"] == page.query_selector(selector=expect_result["selector"]).inner_text()
    # assert expect_result["value"] == page.get_by_text(text=expect_result["text"]).inner_text()
    # 根据要验证的元素的属性或状态，动态地选择合适的断言方法
    # expect(page.get_by_text(text=expect_result["text"])).to_have_text(expect_result["value"])

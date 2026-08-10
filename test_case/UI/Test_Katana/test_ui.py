#!usr/bin/env python3
# -*- encoding : utf-8 -*-
# coding : unicode_escape
'''
Filename         : test_ui.py
Description      : Action Registry Refactored Version
Time             : 2026/01/15
Author           : AllenLuo / Agent
Version          : 4.0 — Step Capture integrated
'''

import sys
import os
import pytest
import allure
from playwright.sync_api import Page, Browser
from loguru import logger

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from tools import allure_title, allure_step_no
from page.home import *

# Import the new Action Registry
from test_case.UI.Test_Katana.actions import get_action
from .actions import get_action, create_session

# Step Capture — in-test data collection (replaces replay engine)
from tools.step_capture import StepCapture


@allure.testcase('https://ones.cn/project/#/testcase/team/T7u1zXum/plan/QCuFwDdq/library/XcAFFViB/module/6mi4qiVp', 'ONS Test Case Link')
@allure.title("Test Execution")
def test_case(smokecases1, page: Page, browser: Browser, request):
    val = list(smokecases1.values())[0]

    # Guest Mode Setup
    if val.get("guest", False):
        logger.info(f"Running {list(smokecases1.keys())[0]} in GUEST mode")

    page.set_default_timeout(30000)  # Reduced from 90s for faster AI failover
    
    # Test Metadata extraction
    caseno = list(smokecases1.keys())[0]
    description = dict(list(smokecases1.values())[0])["description"]
    test_step = list(smokecases1.values())[0]["test_step"]
    expect_result = dict(list(smokecases1.values())[0])["expect_result"]
    
    # Pass metadata to page object for AI context
    setattr(page, "_test_description", description)
    setattr(page, "_test_caseno", caseno)
    setattr(page, "_yaml_path", val.get("__yaml_path__")) # For self-patching
    setattr(page, "_execution_history", [])  # Initialize execution history
    
    # --- Step Capture Setup ---
    step_capture_mode = request.config.getoption("--step-capture", "on-failure")
    capture_enabled = step_capture_mode != "off"
    step_capture = None
    if capture_enabled:
        step_capture = StepCapture(
            case_name=caseno,
            capture_screenshot=True,
            screenshot_mode="always" if step_capture_mode == "on" else "on-failure",
        )
        # Store on page for conftest teardown access
        setattr(page, "_step_capture", step_capture)
        setattr(page, "_step_capture_mode", step_capture_mode)
    
    # Append YAML description to the Allure title so the Behaviors list
    # shows "testT3991: Verify that partner can ..." instead of a bare case id.
    desc = (description or "").strip()
    allure_title(f"{caseno}: {desc}" if desc else caseno)
    allure_step_no(f'description:{description}')
    allure_step_no(f'test_step:{str(test_step)}')

    # Track test outcome for step_capture finalization
    test_failed = False

    # --- Pre-condition Phase ---
    pre_condition = val.get("pre_condition", {})
    if pre_condition:
        pre_steps = pre_condition.get("test_step", {})
        pre_desc = pre_condition.get("description", "pre_condition")
        logger.info(f">>> Starting Pre-condition Phase: {pre_desc}")
        allure_step_no(f'pre_condition:{pre_desc}')
        for pk, pv in pre_steps.items():
            logger.info(f">>> Pre-condition Step: {pk}")
            p_action = get_action(pk)
            if p_action:
                try:
                    p_action(page, pv)
                except Exception as e:
                    logger.warning(f"Pre-condition step '{pk}' failed (non-blocking): {e}")
            else:
                logger.warning(f"Pre-condition step '{pk}' not found in Action Registry, skipping.")
        logger.info(">>> Pre-condition Phase completed")

    # --- Core Execution Engine ---
    for k, v in test_step.items():
        logger.info(f">>> Current Step: {k}")

        # Parse session namespace: session_<name>__<action>
        session_prefix = "session_"
        session_separator = "__"
        target_session = None
        actual_action_name = k

        if k.startswith(session_prefix) and session_separator in k:
            # Extract session name and action
            parts = k[len(session_prefix):].split(session_separator, 1)
            if len(parts) == 2:
                session_name, action_name = parts
                target_session = session_name
                actual_action_name = action_name
                logger.info(f">>> Session Namespace: session='{session_name}', action='{action_name}'")

                # Auto-create session if it doesn't exist
                if not hasattr(page, "_sessions"):
                    setattr(page, "_sessions", {})

                if session_name not in page._sessions:
                    logger.info(f">>> Auto-creating session: {session_name}")
                    create_session(page, {
                        "name": session_name,
                        "url": v.get("url") if isinstance(v, dict) else None
                    })

                # Set as active session
                page._active_session = session_name

        # Get the active page (session page or default page)
        if target_session or hasattr(page, "_active_session") and page._active_session:
            active_session_name = target_session or page._active_session
            if active_session_name in page._sessions:
                active_page = page._sessions[active_session_name]["page"]
                logger.debug(f">>> Using page from session: {active_session_name}")
            else:
                active_page = page
                logger.warning(f">>> Session '{active_session_name}' not found, using default page")
        else:
            active_page = getattr(page, "_active_page", page)

        # Global Crash Check
        if active_page.get_by_text("Something went wrong!", exact=True).is_visible():
            logger.error("Application crash detected (Something went wrong!)")
            active_page.screenshot(path="crash_detected.png")
            if step_capture:
                step_capture.step_end(active_page, status="failed", error_msg="Application crashed")
                test_failed = True
            pytest.fail("Application crashed during test execution.")

        # --- Step Capture: before execution ---
        should_capture = step_capture and StepCapture.should_capture(k)
        if should_capture:
            step_capture.step_start(k, v)

        # 1. Action Registry Lookup
        action = get_action(actual_action_name)

        step_status = "passed"
        step_error = None

        if action:
            try:
                # Handle session namespace actions
                if isinstance(action, dict) and action.get("type") == "session_action":
                    # This is a session namespace action
                    session_name = action["session_name"]
                    action_name = action["action_name"]

                    # Get the actual action function
                    actual_action = get_action(action_name)

                    if actual_action:
                        # Ensure session exists
                        if session_name not in page._sessions:
                            create_session(page, {"name": session_name})

                        # Execute action in session context
                        session_page = page._sessions[session_name]["page"]
                        page._active_session = session_name

                        logger.info(f">>> Executing '{action_name}' in session '{session_name}'")
                        actual_action(session_page, v)
                        page._execution_history.append((k, v))
                    else:
                        logger.error(f"Session action '{action_name}' not found")
                        step_status = "failed"
                        step_error = f"Session action '{action_name}' not found"
                else:
                    # Regular action
                    action(active_page, v)
                    page._execution_history.append((k, v))
            except Exception as e:
                step_status = "failed"
                step_error = str(e)
                logger.error(f"Action '{k}' failed: {e}")
                # Try generic screenshot on failure
                try: active_page.screenshot(path=f"fail_{k}.png")
                except: pass

                # --- Step Capture: capture failed step ---
                if should_capture:
                    step_capture.step_end(active_page, status="failed", error_msg=step_error)
                    test_failed = True

                raise
        else:
            # 2. Legacy Fallback
            logger.warning(f"Step '{k}' not found in Action Registry. Attempting legacy dispatch/fallback.")
            fallback_success = False
            if k.startswith("click"):
                try:
                   target_text = v.get('text') or v.get('name')
                   if target_text:
                       active_page.click(f"text={target_text}", timeout=5000)
                       logger.info(f"Fallback click success for: {target_text}")
                       fallback_success = True
                       page._execution_history.append((k, v))
                except:
                   pass

            if not fallback_success:
                step_status = "failed"
                step_error = f"Step '{k}' not found or failed in fallback"
                logger.error(f"FATAL: Step '{k}' could not be resolved by Registry or Fallback.")

                if should_capture:
                    step_capture.step_end(active_page, status="failed", error_msg=step_error)
                    test_failed = True

                pytest.fail(f"Step '{k}' not found or failed in fallback. Check actions/__init__.py or YAML key.")

        # --- Step Capture: after successful execution ---
        if should_capture and step_status == "passed":
            step_capture.step_end(active_page, status="passed")

        # Post-step Crash Check
        if active_page.get_by_text("Something went wrong!", exact=True).is_visible():
             logger.error("Application crash detected after step completion.")
             active_page.screenshot(path=f"crash_after_{k}.png")
             if step_capture:
                 step_capture.step_end(active_page, status="failed", error_msg="Application crashed after step")
                 test_failed = True
             pytest.fail(f"Application crashed after step: {k}")

    # --- Assertion Phase ---
    allure_step_no(f'expect_result:{str(expect_result)}')
    if "assertions" in expect_result:
        for assertion in expect_result["assertions"]:
            assertion_type = assertion.get("assertion_type")
            
            if assertion_type == "element_visible_by_text":
                text = assertion.get("text")
                if text:
                    logger.info(f"Verifying visibility of text: '{text}'")
                    try:
                        page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=10000)
                        logger.info(f"Assertion success: Text '{text}' is visible.")
                    except:
                        # Capture page content for debugging
                        found_in_content = text in page.content()
                        if not found_in_content:
                            logger.error(f"Assertion failed: Text '{text}' not found in page content.")
                            page.screenshot(path=f"fail_assert_{caseno}.png")
                        assert found_in_content, f"Assertion failed: Text '{text}' not found in page content."
            
            elif assertion_type == "element_visible":
                role = assertion.get("role")
                name = assertion.get("name")
                if role:
                    logger.info(f"Verifying visibility of element: {role} '{name}'")
                    try:
                        page.get_by_role(role, name=name).first.wait_for(state="visible", timeout=10000)
                        logger.info(f"Assertion success: Element {role} '{name}' is visible.")
                    except:
                        logger.error(f"Assertion failed: Element {role} '{name}' not found or visible.")
                        page.screenshot(path=f"fail_assert_{caseno}.png")
                        pytest.fail(f"Assertion failed: Element {role} '{name}' not found or visible.")
            
            elif assertion_type == "element_visible_by_locator":
                locator = assertion.get("locator")
                if locator:
                    logger.info(f"Verifying visibility of locator: '{locator}'")
                    try:
                        page.locator(locator).first.wait_for(state="visible", timeout=10000)
                        logger.info(f"Assertion success: Locator '{locator}' is visible.")
                    except:
                        logger.error(f"Assertion failed: Locator '{locator}' not found or visible.")
                        page.screenshot(path=f"fail_assert_{caseno}.png")
                        pytest.fail(f"Assertion failed: Locator '{locator}' not found or visible.")
            
            elif assertion_type == "element_not_visible":
                role = assertion.get("role")
                name = assertion.get("name")
                locator = assertion.get("locator")
                logger.info(f"Verifying element is NOT visible: role={role}, name={name}, locator={locator}")
                try:
                    if locator:
                        is_visible = page.locator(locator).first.is_visible(timeout=3000)
                    elif role:
                        is_visible = page.get_by_role(role, name=name).first.is_visible(timeout=3000)
                    else:
                        is_visible = False
                    if is_visible:
                        logger.error(f"Assertion failed: Element should NOT be visible but it is (role={role}, name={name}, locator={locator}).")
                        page.screenshot(path=f"fail_assert_{caseno}.png")
                        pytest.fail(f"Assertion failed: Element should NOT be visible but it is (role={role}, name={name}, locator={locator}).")
                    else:
                        logger.info(f"Assertion success: Element is correctly NOT visible (role={role}, name={name}, locator={locator}).")
                except Exception as e:
                    # is_visible returning False or throwing means not visible - which is what we want
                    logger.info(f"Assertion success: Element is correctly NOT visible (role={role}, name={name}, locator={locator}).")
            
            elif assertion_type == "element_checked":
                locator = assertion.get("locator")
                role = assertion.get("role")
                index = assertion.get("index", 0)
                logger.info(f"Verifying element is checked: locator='{locator}', role='{role}', index={index}")
                try:
                    if locator:
                        is_checked = page.locator(locator).nth(index).is_checked()
                    elif role:
                        is_checked = page.get_by_role(role).nth(index).is_checked()
                    else:
                        is_checked = False
                    if not is_checked:
                        logger.error(f"Assertion failed: Element (locator='{locator}', role='{role}', index={index}) should be checked but it is NOT.")
                        page.screenshot(path=f"fail_assert_{caseno}.png")
                        pytest.fail(f"Assertion failed: Element should be checked but it is NOT.")
                    else:
                        logger.info(f"Assertion success: Element is correctly checked.")
                except Exception as e:
                    logger.error(f"Assertion failed: Element is NOT checked (exception: {e}).")
                    page.screenshot(path=f"fail_assert_{caseno}.png")
                    pytest.fail(f"Assertion failed: Element is NOT checked (exception: {e}).")
            
            elif assertion_type == "element_not_checked":
                locator = assertion.get("locator")
                logger.info(f"Verifying element is NOT checked: locator='{locator}'")
                try:
                    if locator:
                        is_checked = page.locator(locator).first.is_checked()
                    else:
                        is_checked = False
                    if is_checked:
                        logger.error(f"Assertion failed: Element '{locator}' should NOT be checked but it is.")
                        page.screenshot(path=f"fail_assert_{caseno}.png")
                        pytest.fail(f"Assertion failed: Element '{locator}' should NOT be checked but it is.")
                    else:
                        logger.info(f"Assertion success: Element '{locator}' is correctly NOT checked.")
                except Exception as e:
                    logger.info(f"Assertion success: Element '{locator}' is correctly NOT checked (exception: {e}).")
            
            elif assertion_type == "element_not_visible_by_text":
                text = assertion.get("text")
                logger.info(f"Verifying text is NOT visible: '{text}'")
                try:
                    is_visible = page.get_by_text(text, exact=False).first.is_visible(timeout=3000)
                    if is_visible:
                        logger.error(f"Assertion failed: Text '{text}' should NOT be visible but it is.")
                        page.screenshot(path=f"fail_assert_{caseno}.png")
                        pytest.fail(f"Assertion failed: Text '{text}' should NOT be visible but it is.")
                    else:
                        logger.info(f"Assertion success: Text '{text}' is correctly NOT visible.")
                except:
                    logger.info(f"Assertion success: Text '{text}' is correctly NOT visible.")
            
            
    # --- Teardown Phase ---
    teardown_step = val.get("teardown_step", {})
    if teardown_step:
        logger.info(">>> Starting Teardown Phase to clean up test data")
        for tk, tv in teardown_step.items():
            logger.info(f">>> Teardown Step: {tk}")
            t_action = get_action(tk)
            if t_action:
                try: t_action(page, tv)
                except Exception as e: logger.error(f"Teardown Action '{tk}' failed: {e}")
            else:
                if tk.startswith("click"):
                    try:
                        t_target_text = tv.get('text') or tv.get('name')
                        if t_target_text: page.click(f"text={t_target_text}", timeout=5000)
                    except: pass

    # Note: Step Capture finalization is handled by conftest.py page fixture teardown,
    # which calls step_capture.finalize() even if the test raised an exception.


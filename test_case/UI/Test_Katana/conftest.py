#!usr/bin/env python3
# -*- encoding: utf-8 -*-
'''
Filename         : conftest.py
Description      :
Time             : 2023/12/14 14:24:12
Author           : AllenLuo
Version          : 2.0
'''
import os
import json
os.environ["AI_DISABLED"] = "True"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
while not os.path.exists(os.path.join(BASE_DIR, "test_case")) and BASE_DIR != os.path.dirname(BASE_DIR):
    BASE_DIR = os.path.dirname(BASE_DIR)

import shutil
from loguru import logger
import warnings
from typing import Any, Callable, Dict, Generator, List, Optional
import allure
import yaml
import pytest
from dotenv import load_dotenv
from playwright.sync_api import (
    Browser,
    BrowserContext,
    BrowserType,
    Error,
    Page,
    Playwright,
    sync_playwright,
)
from slugify import slugify
import re

# Load .env file from project root
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Infer environment name from BASE_URL for cookie file naming
_BASE_URL = os.environ.get("BASE_URL", "https://release.pear.us")
_ENV_MAP = {
    "https://staging.pear.us": "staging",
    "https://release.pear.us": "release",
    "https://pear.us": "prod",
}
CURRENT_ENV = _ENV_MAP.get(_BASE_URL, "release")

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    # execute all other hooks to obtain the report object
    outcome = yield
    rep = outcome.get_result()

    # set a report attribute for each phase of a call, which can
    # be "setup", "call", "teardown"
    setattr(item, "rep_" + rep.when, rep)

    if rep.when == "call":
        try:
            smokecases1 = item.funcargs['smokecases1']
            test_case_name = list(smokecases1.keys())[0] # e.g., testT3370
            match = re.search(r'T\d+', test_case_name)
            if not match:
                return
            test_case_id = match.group(0)

            status = "skipped" # Default status
            if rep.passed:
                status = "passed"
            elif rep.failed:
                status = "failed"
            
            logger.info(f"TEST_STATUS: {test_case_id} - {status}")
        except Exception:
            pass # Ignore errors if the fixture is not present



def pytest_addoption(parser):
    try:
        parser.addoption("--env", action="store", default="release", help="Test environment: release, staging, or local")
    except ValueError:
        pass
    try:
        parser.addoption("--storage-state", action="store", default=None, help="Path to the storage state file")
    except ValueError:
        pass
    try:
        parser.addoption("--yaml", action="store", default=None, help="Specific YAML file to load test cases from")
    except ValueError:
        pass
    try:
        parser.addoption("--step-capture", action="store", default="on-failure",
                         help="Step-level capture mode: on|on-failure|off (default: on-failure)")
    except ValueError:
        pass

@pytest.fixture()
def browser_context_args(browser_context_args, playwright, request):
    """
    Dynamic device emulation based on YAML 'is_mobile' flag.
    """
    is_mobile = False
    try:
        if "smokecases1" in request.fixturenames:
            smokecases1 = request.getfixturevalue("smokecases1")
            v = list(smokecases1.values())[0]
            is_mobile = v.get("is_mobile", False)
    except Exception:
        pass

    # Base arguments for all contexts
    base_args = {
        **browser_context_args,
        "permissions": ["camera", "microphone"],
        "ignore_https_errors": True,
    }

    if is_mobile:
        iphone_14 = playwright.devices['iPhone 14 Pro Max']
        res = {
            **base_args,
            **iphone_14,
        }
        logger.info("MOBILE_EMULATION: Enabled (iPhone 14 Pro Max)")
        return res
    else:
        logger.info("MOBILE_EMULATION: Disabled (Desktop)")
        return base_args


@pytest.fixture()
def page(context: BrowserContext, request) -> Generator[Page, None, None]:
    page = context.new_page()
    yield page
    # --- Step Capture Finalization ---
    # Finalize step capture after test completes (even on failure/exception)
    step_capture = getattr(page, "_step_capture", None)
    step_capture_mode = getattr(page, "_step_capture_mode", "off")
    if step_capture and step_capture._steps:
        # Determine if test failed from pytest report
        test_failed = False
        if hasattr(request.node, 'rep_call'):
            test_failed = request.node.rep_call.failed if hasattr(request.node.rep_call, 'failed') else True
        should_persist = (step_capture_mode == "on") or (step_capture_mode == "on-failure" and test_failed)
        if should_persist:
            # Get metadata from page attributes
            metadata = {
                "description": getattr(page, "_test_description", ""),
                "yaml_path": getattr(page, "_yaml_path", ""),
                "is_mobile": False,  # Not easily accessible here
            }
            try:
                step_capture.finalize(test_passed=not test_failed, case_metadata=metadata)
            except Exception as e:
                logger.warning(f"Step capture finalization failed: {e}")

def _build_artifact_test_folder(
    pytestconfig: Any, request: pytest.FixtureRequest, folder_or_file_name: str
) -> str:
    output_dir = pytestconfig.getoption("--output")
    return os.path.join(output_dir, slugify(request.node.nodeid), folder_or_file_name)

@pytest.fixture()
def context(
    browser: Browser,
    browser_context_args: Dict,
    pytestconfig: Any,
    request: pytest.FixtureRequest,
) -> Generator[BrowserContext, None, None]:
    pages: List[Page] = []
    storage_state = pytestconfig.getoption("--storage-state")
    if not storage_state:
        # Check if YAML specifies is_coseller flag
        is_coseller = False
        try:
            if "smokecases1" in request.fixturenames:
                smokecases1 = request.getfixturevalue("smokecases1")
                is_coseller = list(smokecases1.values())[0].get("is_coseller", False)
        except Exception:
            pass

        if is_coseller:
            coseller_cookie_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"cookie_{CURRENT_ENV}_co_seller.json")
            if os.path.exists(coseller_cookie_path):
                storage_state = coseller_cookie_path
                logger.info(f"COSeller MODE detected: Using cookie_{CURRENT_ENV}_co_seller.json")
            else:
                logger.warning(f"COSeller cookie file not found: {coseller_cookie_path}, falling back to default")

        # Optimize: automatically load the default cookie state if it exists
        if not storage_state:
            default_cookie_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"cookie_{CURRENT_ENV}.json")
            if os.path.exists(default_cookie_path):
                storage_state = default_cookie_path
            
    is_guest = False
    try:
        if "smokecases1" in request.fixturenames:
            smokecases1 = request.getfixturevalue("smokecases1")
            is_guest = list(smokecases1.values())[0].get("guest", False)
    except Exception:
        pass

    # Only use storage-state if authenticated and NOT a guest
    if storage_state and not is_guest:
        context = browser.new_context(storage_state=storage_state, **browser_context_args)
    else:
        # Use full mobile emulation args even for guests as requested
        context = browser.new_context(**browser_context_args)

    # --- Guest context: inject minimal non-auth cookies so Pear SPA can route to
    # the correct tenant. Without `release_katana_vanity_url` the client-side
    # router falls back to a 404 "Page could not be found" page even though SSR
    # returns 200. This injects visitor_id + vanity_url (and other harmless
    # non-auth cookies like katana_cookie_consent) but NOT access/refresh tokens,
    # keeping the user effectively unauthenticated for permission checks.
    if is_guest:
        try:
            default_cookie_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                f"cookie_{CURRENT_ENV}.json",
            )
            if os.path.exists(default_cookie_path):
                state = json.load(open(default_cookie_path, encoding="utf-8"))
                non_auth_names = {
                    # tenant routing — required so SPA recognizes /autotestshop
                    "release_katana_vanity_url",
                    "staging_katana_vanity_url",
                    "prod_katana_vanity_url",
                    # first-party visitor id
                    "release_katana_visitor_id",
                    "staging_katana_visitor_id",
                    "prod_katana_visitor_id",
                    # GDPR consent state — harmless
                    "katana_cookie_consent",
                    # analytics — harmless, NOT identifying
                    "_ga",
                    "_ga_RV17GL444M",
                    "_rdt_uuid",
                }
                guest_cookies = [
                    c for c in state.get("cookies", [])
                    if c.get("name") in non_auth_names
                ]
                if guest_cookies:
                    context.add_cookies(guest_cookies)
                    logger.info(
                        f"GUEST MODE: injected {len(guest_cookies)} non-auth "
                        f"cookies from {default_cookie_path} (vanity_url + visitor_id)"
                    )
                else:
                    logger.warning(
                        "GUEST MODE: no non-auth cookies found in storage state; "
                        "Pear SPA may render 404"
                    )
        except Exception as e:
            logger.warning(f"GUEST cookie injection failed: {e}")

    # Force grant permissions even if storage_state has restricted ones
    try:
        context.grant_permissions(["camera", "microphone"])
    except Exception as e:
        logger.warning(f"Failed to grant preset permissions: {e}")

    # --- KEY FIX: Patch getUserMedia to relax 'exact' constraints ---
    # The web app requests facingMode:{exact:"environment"} and deviceId:{exact:...}
    # which fails because Chromium's fake device doesn't declare a facing mode.
    # We intercept and change 'exact' to 'ideal' so the fake device can pass the check.
    context.add_init_script("""
        if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
            const _original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
            navigator.mediaDevices.getUserMedia = function(constraints) {
                if (constraints && constraints.video && typeof constraints.video === 'object') {
                    const v = JSON.parse(JSON.stringify(constraints.video));
                    // Relax facingMode: {exact: 'environment'} -> {ideal: 'environment'}
                    if (v.facingMode && v.facingMode.exact) {
                        v.facingMode = { ideal: v.facingMode.exact };
                    }
                    // Remove deviceId exact constraint (fake device has no real deviceId)
                    if (v.deviceId && v.deviceId.exact) {
                        delete v.deviceId;
                    }
                    // Delete width/height constraints so the fake camera ignores 16:9 
                    // requirements and doesn't crop or stretch 1:1 videos like Ticket_C.y4m
                    if (v.width) delete v.width;
                    if (v.height) delete v.height;
                    constraints = { ...constraints, video: v };
                }
                return _original(constraints);
            };
        }
    """)
    logger.info("CAMERA_PATCH: getUserMedia constraint relaxation injected.")

    context.on("page", lambda page: pages.append(page))
    tracing_option = pytestconfig.getoption("--tracing")
    capture_trace = tracing_option in ["on", "retain-on-failure"]
    if capture_trace:
        context.tracing.start(
            name=slugify(request.node.nodeid),
            screenshots=True,
            snapshots=True,
            sources=True,
        )

    yield context
    failed = request.node.rep_setup.failed or request.node.rep_call.failed if hasattr(request.node, 'rep_setup') and hasattr(request.node, 'rep_call') else True

    if capture_trace:
        retain_trace = tracing_option == "on" or (
            failed and tracing_option == "retain-on-failure"
        )
        if retain_trace:
            trace_path = _build_artifact_test_folder(pytestconfig, request, "trace.zip")
            context.tracing.stop(path=trace_path)
        else:
            context.tracing.stop()

    screenshot_option = pytestconfig.getoption("--screenshot")
    capture_screenshot = screenshot_option == "on" or (
        failed and screenshot_option == "only-on-failure"
    )
    if capture_screenshot:
        for i, page in enumerate(pages):
            screenshot_path = _build_artifact_test_folder(
                pytestconfig, request, f"screenshot-{i}.png"
            )
            try:
                page.screenshot(path=screenshot_path)
                allure.attach.file(
                    screenshot_path,
                    name=f"Screenshot {i}",
                    attachment_type=allure.attachment_type.PNG,
                )
            except Exception:
                pass

    # --- Video Attachment Fix ---
    # CRITICAL: video.path() must be called BEFORE context.close().
    # context.close() triggers Playwright to finalize and write the video file to disk.
    # After close(), we can safely read and attach the file to Allure.
    video_option = pytestconfig.getoption("--video")
    capture_video = video_option == "on" or (
        failed and video_option == "retain-on-failure"
    )
    video_paths = []
    if capture_video:
        for i, page in enumerate(pages):
            video = page.video
            if video:
                try:
                    # Record path BEFORE context.close() finalizes the file
                    video_paths.append((i, video.path()))
                except Exception as e:
                    logger.warning(f"Could not get video path for page {i}: {e}")

    # Close context: this is when Playwright writes the video to disk
    context.close()

    # Now attach the finalized video files to Allure
    for i, video_path in video_paths:
        try:
            if os.path.exists(video_path):
                allure.attach.file(
                    video_path,
                    name=f"Video {i}",
                    attachment_type=allure.attachment_type.WEBM,
                )
                logger.info(f"Video {i} attached to Allure: {video_path}")
            else:
                logger.warning(f"Video file not found after context close: {video_path}")
        except Exception as e:
            logger.warning(f"Failed to attach video {i} to Allure: {e}")
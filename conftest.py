#!usr/bin/env python3
# -*- encoding: utf-8 -*-
'''
Filename         : conftest.py
Description      : Root conftest with dynamic YAML loading & per-test emulation
Time             : 2023/12/14 14:24:12
Author           : AllenLuo
Version          : 2.2
'''
import os
import shutil
from loguru import logger
import warnings
from typing import Any, Callable, Dict, Generator, List, Optional
import allure
import yaml
import pytest
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
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load .env file from project root (does not override existing environment variables)
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _resolve_base_url():
    """
    Resolve BASE_URL with priority: system env > .env file > default value.
    Default: https://release.pear.us
    """
    return os.environ.get("BASE_URL", "https://release.pear.us")


# Infer environment name from BASE_URL for cookie file naming
_ENV_MAP = {
    "https://staging.pear.us": "staging",
    "https://release.pear.us": "release",
    "https://pear.us": "prod",
}
CURRENT_ENV = _ENV_MAP.get(_resolve_base_url(), "release")


def _replace_placeholders(obj, base_url, env_name):
    """Recursively replace {BASE_URL} and {ENV} placeholders in dicts, lists, and strings"""
    if isinstance(obj, str):
        return obj.replace("{BASE_URL}", base_url).replace("{ENV}", env_name)
    elif isinstance(obj, dict):
        return {k: _replace_placeholders(v, base_url, env_name) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_replace_placeholders(item, base_url, env_name) for item in obj]
    return obj


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    # Default to the trimmed small video to prevent OOM
    y4m_name = "Ticket_Small.y4m"
    
    # Fallback to Ticket_C.y4m if small one doesn't exist
    if not os.path.exists(os.path.join(BASE_DIR, "data", y4m_name)):
        y4m_name = "Ticket_C.y4m"
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
    if worker_id != "master":
        # Extract index from 'gw0', 'gw1' etc.
        try:
            worker_idx = int(re.sub(r'\D', '', worker_id)) + 1
            worker_y4m = f"Ticket_{worker_idx}.y4m"
            if os.path.exists(os.path.join(BASE_DIR, "data", worker_y4m)):
                y4m_name = worker_y4m
                logger.info(f"WORKER_ISOLATION: Worker {worker_id} using dedicated video: {y4m_name}")
        except Exception as e:
            logger.warning(f"Failed to determine worker-specific video: {e}")

    y4m_path = os.path.join(BASE_DIR, "data", y4m_name).replace("\\", "/")
    logger.info(f"Y4M_LOAD_PATH: {y4m_path}")

    return {
        **browser_type_launch_args,
        "args": [
            "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream",
            "--window-size=600,1100",
            "--start-maximized",
            "--disable-translate",
            "--disable-features=Translate",
            "--disable-gpu",
            "--no-sandbox"
        ],
    }

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, "rep_" + rep.when, rep)
    if rep.when == "call":
        try:
            smokecases1 = item.funcargs.get('smokecases1')
            if smokecases1:
                test_case_name = list(smokecases1.keys())[0]
                test_case_data = list(smokecases1.values())[0]
                match = re.search(r'T\d+', test_case_name)
                if match:
                    # Get YAML filename for log tracing
                    yaml_path = test_case_data.get("__yaml_path__", "")
                    yaml_name = os.path.basename(yaml_path) if yaml_path else "unknown"
                    logger.info(f"TEST_STATUS: [{yaml_name}] {match.group(0)} - {'passed' if rep.passed else 'failed'}")
        except Exception:
            pass

def pytest_addoption(parser):
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
    Root level dynamic device emulation.
    """
    is_mobile = False
    try:
        if "smokecases1" in request.fixturenames:
            smokecases1 = request.getfixturevalue("smokecases1")
            v = list(smokecases1.values())[0]
            is_mobile = v.get("is_mobile", False)
    except Exception:
        pass

    if is_mobile:
        iphone_14 = playwright.devices['iPhone 14 Pro Max']
        logger.info("ROOT_EMULATION: Enabled (iPhone 14 Pro Max)")
        return {
            **browser_context_args,
            **iphone_14,
            "permissions": ["camera", "microphone"],
        }
    else:
        logger.info("ROOT_EMULATION: Disabled (Desktop)")
        return {
            **browser_context_args,
            "permissions": ["camera", "microphone"],
        }

@pytest.fixture()
def page(context: BrowserContext) -> Generator[Page, None, None]:
    page = context.new_page()
    yield page

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
    
    is_guest = False
    try:
        if "smokecases1" in request.fixturenames:
            val = request.getfixturevalue("smokecases1")
            is_guest = list(val.values())[0].get("guest", False)
    except Exception:
        pass

    if is_guest:
        logger.info("GUEST MODE detected in fixture override: Bypassing cookie loading for pure context")
        context = browser.new_context(**browser_context_args)
    elif storage_state:
        context = browser.new_context(storage_state=storage_state, **browser_context_args)
    else:
        # Dynamically select cookie file based on CURRENT_ENV
        local_cookie = os.path.join(BASE_DIR, "test_case", "UI", "Test_Katana", f"cookie_{CURRENT_ENV}.json")
        if os.path.exists(local_cookie):
            context = browser.new_context(storage_state=local_cookie, **browser_context_args)
        else:
            context = browser.new_context(**browser_context_args)
            
    context.on("page", lambda page: pages.append(page))
    
    yield context
    context.close()

# --- THE DYNAMIC ENGINE ---
def pytest_generate_tests(metafunc):
    if "smokecases1" in metafunc.fixturenames:
        yaml_files = metafunc.config.getoption("--yaml")
        if not yaml_files:
            yaml_files = "Storefront_module.yaml"
        
        # Support comma-separated multiple yaml files
        yaml_file_list = [f.strip() for f in yaml_files.split(",") if f.strip()]
        
        all_argvalues = []
        all_ids = []
        
        for yaml_file in yaml_file_list:
            # Use os.sep to ensure correct path separator
            yaml_path = os.path.join(BASE_DIR, "test_case", "UI", "Test_Katana", yaml_file.replace('/', os.sep).replace('\\', os.sep))
            
            if os.path.exists(yaml_path):
                with open(yaml_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if data:
                    # Replace {BASE_URL} placeholder at runtime
                    base_url = _resolve_base_url()
                    data = _replace_placeholders(data, base_url, CURRENT_ENV)
                    for k, v in data.items():
                        if isinstance(v, dict):
                            v["__yaml_path__"] = yaml_path
                            all_argvalues.append({k: v})
                            # Add yaml prefix + short description slug to test ID for readability
                            desc = v.get("description", "")
                            if desc:
                                slug = slugify(desc, max_length=40, word_boundary=True, separator="_")
                                all_ids.append(f"{yaml_file}::{k}_{slug}")
                            else:
                                all_ids.append(f"{yaml_file}::{k}")
            else:
                logger.error(f"YAML file not found at: {yaml_path}")
        
        if all_argvalues:
            metafunc.parametrize("smokecases1", all_argvalues, ids=all_ids)


# ---------------------------------------------------------------------------
# WorkBuddy safe-delete sandbox: override pytest-playwright's delete_output_dir
#
# pytest-playwright ships a session-scoped autouse fixture `delete_output_dir`
# that runs `shutil.rmtree("test-results")` before any test executes. Under the
# WorkBuddy sandbox, `shutil.rmtree` is patched to move files to the recycle bin;
# with no recycle bin available it raises OSError, which is NOT caught by the
# fixture's `except FileNotFoundError`, so the fixture errors during session
# setup and every test is marked broken ("Test Execution") without ever running.
#
# Only override inside the sandbox (detected via sitecustomize._safe_shutil_rmtree);
# IDE / plain-terminal runs keep the original cleanup behavior. Leftover
# test-results artifacts are harmless.
# See .workbuddy/memory/2026-08-14.md for the full root-cause analysis.
# ---------------------------------------------------------------------------
import sys as _sys

_sitecustomize = _sys.modules.get("sitecustomize")
if _sitecustomize is not None and getattr(_sitecustomize, "_safe_shutil_rmtree", None) is not None:
    @pytest.fixture(scope="session", autouse=True)
    def delete_output_dir(pytestconfig):
        """no-op: skip test-results cleanup under WorkBuddy safe-delete sandbox."""
        return None
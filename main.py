#!usr/bin/env python3
import sys, os
_VENV_PYTHON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "python3")
if os.path.exists(_VENV_PYTHON) and sys.executable != _VENV_PYTHON:
    os.execv(_VENV_PYTHON, [_VENV_PYTHON] + sys.argv)
# -*- encoding: utf-8 -*-
'''
Filename         : main.py
Description      : 
Time             : 2024/01/26 09:24:52
Author           : Xiao
Version          : 2.0
'''


import os
import pytest
from tools import logger, BASE_DIR
import time
import subprocess # Import subprocess
import shutil
import sys
import socket
from dotenv import load_dotenv

# Load .env file from project root (does not override existing environment variables)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

def start_autotest():
    # Ensure subprocess can also access BASE_URL (.env already loaded at module level)
    if "BASE_URL" not in os.environ:
        os.environ["BASE_URL"] = "https://release.pear.us"

    logger.remove()
    create_date = time.strftime('%Y_%m_%d', time.localtime(time.time()))
    logger.add(f'log/{create_date}.log', enqueue=True, encoding='utf-8', retention=30)
    logger.info(f"Python executable: {shutil.which('python')}")
    logger.info(f"sys.path: {sys.path}")
    logger.info("""

     _   _   _ _____ ___    _____ _____ ____ _____ 
    / \ | | | |_   _/ _ \  |_   _| ____/ ___|_   _|
   / _ \| | | | | || | | |   | | |  _| \___ \ | |  
  / ___ \ |_| | | || |_| |   | | | |___ ___) || |  
 /_/   \_\___/  |_| \___/    |_| |_____|____/ |_|  
"`-0-0-'"`-0-0-'"`-0-0-'"`-0-0-'./o--000'"`-0-0-'"

      Starting      ...     ...     ...""")
    allure_path = os.path.join(BASE_DIR, 'allure', 'bin', 'allure')
    now_time = time.strftime('%Y%m%d_%H%M%S', time.localtime(time.time()))
    allure_data_dir = os.path.join(BASE_DIR, 'allure-results', now_time)
    allure_report_dir = os.path.join(BASE_DIR, 'report', 'html', now_time)
    test_results = os.path.join(BASE_DIR, 'report', 'video', now_time)

    logger.info(f"Allure data directory: {allure_data_dir}")
    
    # YAML file list to execute, comma-separated (paths relative to Test_Katana/All_YAML/)
    #yaml_files = "All_YAML/Post/Post_setting.yaml,All_YAML/Post/Post_content.yaml,All_YAML/Events/Scanner.yaml,All_YAML/Form/Storefront_form.yaml,All_YAML/Form/Storefront_product_with_form.yaml,All_YAML/Section/Section.yaml"
    yaml_files = "All_YAML/Post/Post_setting_for_venue_map.yaml"
    pytest_args = [
        sys.executable,
        "-m",
        "pytest",
        os.path.join(BASE_DIR, 'test_case', 'UI'),
        '--headed',
        '--tb=line',   # one line per failure, suppress long traceback/source dump
        f'--yaml={yaml_files}',
        f'--output={test_results}',
        f'--alluredir={allure_data_dir}',
        '--step-capture=on-failure'
    ]
    logger.info(f"Running with YAMLs: {yaml_files}")

    # ── 1. Fetch cookies for all 3 test accounts ──
    cookie_script = os.path.join(BASE_DIR, 'tools', 'get_all_cookies.py')
    logger.info(f"Fetching cookies for all 3 accounts via: {cookie_script}")
    cookie_result = subprocess.run(
        [sys.executable, cookie_script],
        capture_output=True, text=True
    )
    logger.info(f"Cookie script done: {cookie_result.stdout}")
    if cookie_result.returncode != 0:
        logger.error(f"Cookie script stderr: {cookie_result.stderr}")

    # ── 2. Login with latest cookies and dismiss EDU popups ──
    dismiss_script = os.path.join(BASE_DIR, 'tools', 'dismiss_edu.py')
    logger.info(f"Dismissing EDU popups for all 3 accounts via: {dismiss_script}")
    dismiss_result = subprocess.run(
        [sys.executable, dismiss_script],
        capture_output=True, text=True
    )
    logger.info(f"Dismiss EDU script done: {dismiss_result.stdout}")
    if dismiss_result.returncode != 0:
        logger.error(f"Dismiss EDU script stderr: {dismiss_result.stderr}")

    # ── 3. Run pytest ──
    result = subprocess.run(pytest_args, capture_output=True, text=True)
    logger.info(f"Pytest stdout: {result.stdout}")
    logger.error(f"Pytest stderr: {result.stderr}")
    
    # Call the status update script
    # status_script_path = os.path.join(BASE_DIR, 'tools', 'update_test_status.py')
    # logger.info(f"Calling test status update script: {status_script_path}")
    # try:
    #     # Added a 60-second timeout to prevent the script from hanging indefinitely
    #     subprocess.run(["python", status_script_path], timeout=60)
    # except subprocess.TimeoutExpired:
    #     logger.error(f"Status update script timed out after 60 seconds.")
    # except Exception as e:
    #     logger.error(f"Error running status update script: {e}")

    
    allure_bat = allure_path + (".bat" if sys.platform == "win32" else "")
    
    logger.info(f"Generating Allure report: {allure_report_dir}")
    # Using subprocess.run with list to safely handle Windows paths with spaces
    generate_cmd = [allure_bat, "generate", allure_data_dir, "-o", allure_report_dir, "-c"]
    logger.info(f"Running command: {' '.join(generate_cmd)}")
    subprocess.run(generate_cmd, check=True)

    # ── 4.1 Patch v4 custom layout into the freshly generated report ──
    # main.py already ran `allure generate` above, so we only inject styles/index
    # (patch-only) into the SAME report dir that will be auto-opened below.
    # This keeps the auto-opened report styled without re-running allure generate.
    gen_script = os.path.join(BASE_DIR, 'tools', 'gen_report.py')
    patch_cmd = [sys.executable, gen_script, "--patch-only", "--src", now_time]
    logger.info(f"Patching v4 layout into report: {' '.join(patch_cmd)}")
    patch_result = subprocess.run(patch_cmd, capture_output=True, text=True)
    if patch_result.returncode != 0:
        logger.error(f"gen_report patch failed: {patch_result.stderr}")
    else:
        logger.info(f"v4 layout patched: {patch_result.stdout.strip()}")

    # ---------------------------------------------------------
    # NEW: Analyze all failed cases from step captures
    # ---------------------------------------------------------
    logger.info(f"Analyzing failed cases from step captures...")
    analyze_script = os.path.join(BASE_DIR, 'tools', 'step_analyzer.py')
    analyze_cmd = [sys.executable, analyze_script, "analyze", "--all-failed"]
    logger.info(f"Running command: {' '.join(analyze_cmd)}")
    analyze_result = subprocess.run(analyze_cmd, text=True)
    if analyze_result.returncode != 0:
        logger.error(f"Analysis error: {analyze_result.stderr}")
    # ---------------------------------------------------------

    # Get LAN IP (192.168.x.x range, excluding virtual NICs/WSL)
    def get_lan_ip():
        try:
            addrs = socket.getaddrinfo(socket.gethostname(), None)
            for addr in addrs:
                ip = addr[4][0]
                # Exclude WSL/Hyper-V virtual subnets (172.16-31.x.x)
                if ip.startswith("172."):
                    octet2 = int(ip.split(".")[1])
                    if 16 <= octet2 <= 31:
                        continue
                # Prefer real LAN 192.168.x.x (exclude known virtual subnets)
                if ip.startswith("192.168.") and not any(ip.startswith(f"192.168.{x}.") for x in ["56", "88", "23"]):
                    return ip
            # Fallback: any address that is not 127.x, 172.16-31.x, or IPv6
            for addr in addrs:
                ip = addr[4][0]
                if ip.startswith("127.") or ":" in ip:
                    continue
                if ip.startswith("172."):
                    octet2 = int(ip.split(".")[1])
                    if 16 <= octet2 <= 31:
                        continue
                return ip
        except Exception:
            pass
        return "127.0.0.1"

    lan_ip = get_lan_ip()
    http_port = 8080

    logger.info(f"Opening Allure report (local only)...")
    open_cmd = [allure_bat, "open", allure_report_dir]
    logger.info(f"Running command: {' '.join(open_cmd)}")
    # Start HTTP server immediately (in separate window, not blocked by allure open)
    http_server_script = os.path.join(BASE_DIR, "http_server.py")
    http_cmd = [sys.executable, http_server_script, allure_report_dir, str(http_port)]
    subprocess.Popen(http_cmd, creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0)
    logger.info(f"====================================")
    logger.info(f"LAN report URL: http://{lan_ip}:{http_port}")
    logger.info(f"Local Allure: auto-opened")
    logger.info(f"====================================")
    try:
        subprocess.run(open_cmd)
    except Exception:
        pass



if __name__ == '__main__':
    start_autotest()
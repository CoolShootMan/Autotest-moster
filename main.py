#!usr/bin/env python3
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

def start_autotest():
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
    storage_state_path = os.path.join(BASE_DIR, 'test_case', 'UI', 'Test_Katana', 'cookie_release.json')

    logger.info(f"Allure data directory: {allure_data_dir}")
    
    pytest_args = [
        "python",
        "-m",
        "pytest",
        os.path.join(BASE_DIR, 'test_case', 'UI'),
        '--headed',
        f"--storage-state={storage_state_path}",
        f'--output={test_results}',
        f'--alluredir={allure_data_dir}'
    ]
    result = subprocess.run(pytest_args, capture_output=True, text=True)
    logger.info(f"Pytest stdout: {result.stdout}")
    logger.error(f"Pytest stderr: {result.stderr}")
    
    # Call the status update script
    status_script_path = os.path.join(BASE_DIR, 'tools', 'update_test_status.py')
    logger.info(f"Calling test status update script: {status_script_path}")
    subprocess.run(["python", status_script_path]) # Run the script
    
    os.system(f'{allure_path} generate {allure_data_dir} -o  {allure_report_dir} -c')
    os.system(f'{allure_path} open {allure_report_dir}')


if __name__ == '__main__':
    start_autotest()
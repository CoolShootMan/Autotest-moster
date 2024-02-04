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
from playwright.sync_api import expect
import allure
import subprocess

from page.home import *
import os
import yaml
from tools import BASE_DIR
from loguru import logger
from tools import allure_title, allure_step, allure_step_no

test_case_path = os.path.join(BASE_DIR, "test_case", "UI", "Test_Katana", "Katana_curator_smoke.yaml")
with open(test_case_path, "r", encoding="utf-8") as file:
    case_dict = yaml.load(file.read(), Loader=yaml.FullLoader)


# 自定义 expect 函数，用于验证元素是否可见
def expect_element_to_be_visible(element, visible):
    if visible:
        assert element.is_visible()
    else:
        assert not element.is_visible()

@allure.testcase('https://ones.cn/project/#/testcase/team/T7u1zXum/plan/QCuFwDdq/library/XcAFFViB/module/6mi4qiVp',
                 'ONS测试用例链接')
@allure.title("测试执行")
def test_case(smokecases1, page: Page):
    caseno = list(smokecases1.keys())[0]
    descrption = dict(list(smokecases1.values())[0])["descrption"]
    test_step = list(smokecases1.values())[0]["test_step"]
    expect_result = dict(list(smokecases1.values())[0])["expect_result"]
    allure_title(caseno)
    allure_step_no(f'descrption:{descrption}')
    allure_step_no(f'test_step:{str(test_step)}')
    for k, v in test_step.items():
        if k == "open":
            page_open(page, url=v)
        elif k.startswith("R_click"):
            page_element_role_click(page=page, role=v["role"], name=v["name"], index=v["index"])
        elif k.startswith("L_click"):
            page_element_label_click(page=page, text=v["text"], index=v["index"])
        elif k.startswith("S_click"):
            page_element_selector_click(page=page, selector=v)
        elif k.startswith("fill"):
            page_element_input_role_fill(page=page, role=v["role"], value=v["value"])
        elif k.startswith("swipe"):
            if isinstance(v, list):
                page_swipe(page, v[0], v[1])
            else:
                page_swipe(v["x"], v["y"])
        elif k.startswith("sleep"):
            page.wait_for_timeout(v)
        elif k.startswith("press"):
            page_element_input_role_press(page=page, role=v["role"], key=v["key"])

        page.wait_for_timeout(1000)
    allure_step_no(f'expect_result:{str(expect_result)}')
    element = page.get_by_role(role=expect_result["role"])
    expect(element).to_have_text(expect_result["value"])
    # 使用测试数据中的可见性状态进行断言
    expect_element_to_be_visible(element, expect_result["visible"])
    expect(element).to_have_attribute(expect_result["attribute"]["name"], expect_result["attribute"]["value"])
    # 测试运行完成后，自动生成 Allure 报告
    # reportdate = "pytest --alluredir D:\\project\\autotest-monster\\allure-report\\data"
    # subprocess.Popen(reportdate, shell=True)

    # reportgenerate = "allure generate ../allure-report/result -o ./allure-report/report/ --clean"
    # p2 = subprocess.Popen(reportgenerate, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # stdout, stderr = p2.communicate()
    # print(f"Command: {p2.args}, Return Code: {p2.returncode}")
    # print("Stdout:", stdout.decode().strip())
    # print("Stderr:", stderr.decode().strip())

    # report = subprocess.run("allure serve D:\\project\\autotest-monster\\allure-report", shell=True)
    # print(report)
    # "allure generate -c -o C:\\Users\\tester\\Downloads\\autotest-monster\\test_case\\UI/Test_Katana\\reports\\", shell=True
    # expect(element).to_be_visible(expect_result["visible"]["value"], expect_result["attribute"]["role"])
    # assert expect_result["value"] == page.get_by_role(role=expect_result["role"],name=expect_result["name"]).inner_text()
    # assert expect_result["value"] == page.query_selector(selector=expect_result["selector"]).inner_text()
    # assert expect_result["value"] == page.get_by_text(text=expect_result["text"]).inner_text()
    # 根据要验证的元素的属性或状态，动态地选择合适的断言方法
    # expect(page.get_by_text(text=expect_result["text"])).to_have_text(expect_result["value"])

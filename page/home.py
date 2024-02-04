#!usr/bin/env python3
# -*- encoding: utf-8 -*-
'''
Filename         : home.py
Description      : 
Time             : 2023/12/29 10:29:01
Author           : Xiao
Version          : 2.0
'''

from playwright.sync_api import Page, expect
import allure
from loguru import logger


def page_element_selector_click(page: Page, selector, index=0):
    """ 页面点击事件
        selector: 选择器
        index 匹配的选择器, 默认匹配第1个
    """
    with allure.step(f'点击了元素-{selector}'):
        logger.info(f'点击了元素-{selector}')
    page.locator(selector=selector).nth(index).click()

def page_element_role_click(page: Page, role, name, index):
    """ 页面点击事件
        role: 内置定位器，定位效果比selector更好
    """
    with allure.step(f'点击了元素-{role},出现文本-{name}'):
        logger.info(f'点击了元素-{role},出现文本-{name}')
    page.get_by_role(role=role, name=name).nth(index=index).click()

def page_element_label_click(page: Page, text, index):
    """ 页面点击事件
        label: 标签定位器，定位效果比selector更好
    """
    with allure.step(f'点击了元素-{text}'):
        logger.info(f'点击了元素-{text}')
    page.get_by_label(text=text).nth(index=index).click()

def page_element_input_fill(page: Page, selector,value):
    """ 页面input框文本填充(Demo用) """
    with allure.step(f'元素-{selector},填充文本-{value}'):
        logger.info(f'元素-{selector},填充文本-{value}')
    page.locator(selector=selector).fill(value=value)

def page_element_input_role_fill(page: Page, role, value):
    """ 页面input框文本填充 """
    with allure.step(f'元素-{role},填充文本-{value}'):
        logger.info(f'元素-{role},填充文本-{value}')
    page.get_by_role(role=role).fill(value=value)

def page_element_input_placeholder_fill(page: Page, placeholder_text, value, index=1):
    """ 页面input框文本填充
        placeholder：模拟真实用户输入，一个字符一个字符的输入
    """
    with allure.step(f'{placeholder_text}-输入框,填充文本-{value}'):
        logger.info(f'{placeholder_text}-输入框,填充文本-{value}')
    page.get_by_placeholder(text=placeholder_text).nth(index).fill(value=value)

def page_swipe(page: Page, x, y):
    """ 页面滚动条方法封装 """
    with allure.step(f'滑动元素,坐标-{x, y}'):
        logger.info(f'滑动元素,坐标-{x, y}')
    page.mouse.wheel(delta_x=x, delta_y=y)

def page_element_input_role_press(page: Page, role, key):
    """ 页面按键方法封装 """
    with allure.step(f'对元素使用了按键-{role}'):
        logger.info(f'对元素使用了按键-{role}')
    page.get_by_role(role=role).press(key=key)

def page_open(page: Page, url):
    """ 打开页面方法封装 """
    with allure.step(f'打开-{url}'):
        logger.info(f'打开-{url}')
    page.goto(url=url)

        

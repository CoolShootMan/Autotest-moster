#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
api_params.py —— cache-regression 统一参数中心。

所有环境参数与接口参数按环境拆分为两个 CSV（单一事实来源）：
  - API_Parameter_Release.csv：release 环境参数表（API_ENV=release 时读取）
  - API_Parameter_Prod.csv：prod 环境参数表（API_ENV=prod 时读取）
本模块负责：
  1. 按 API_ENV（release | prod，默认 release）选择对应 CSV 文件
  2. 读取 CSV（category / param / value / description），value 列为该环境取值
  3. 渲染含 {PLACEHOLDER} 的路径模板（支持嵌套引用，如 {CURATOR_SHOP_URL}）
  4. 导出参数常量，供 conftest / precondition_login / test_* / verify_* 引用

取值优先级：进程环境变量 > .env > CSV(value 列)
敏感凭据（token / 密码）不入 CSV，仍由 .env 提供。

用法：
  from api_params import BASE_URL, POST_DETAIL_PATH, CONCURRENT_COUNT
  或：api_params.param("CURATOR_SHOP_URL") / api_params.path("STORE_PATH")
"""
from __future__ import annotations

import csv
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# 环境开关：release（默认）| prod。设置 API_ENV=prod 即读取 prod 参数表。
API_ENV = os.getenv("API_ENV", "release").strip().lower()

try:
    from dotenv import load_dotenv

    # 按 API_ENV 加载对应环境文件 .env.{API_ENV}；不存在时回退 .env。
    _env_file = BASE_DIR / f".env.{API_ENV}"
    load_dotenv(_env_file if _env_file.exists() else BASE_DIR / ".env")
except Exception:  # dotenv 不可用也不阻塞（环境变量仍可覆盖）
    pass

# 按环境选择参数表文件；未知 API_ENV 时回退 release 文件。
_CSV_NAME = {
    "release": "API_Parameter_Release.csv",
    "prod": "API_Parameter_Prod.csv",
}.get(API_ENV, "API_Parameter_Release.csv")
CSV_PATH = BASE_DIR / _CSV_NAME

_PLACEHOLDER_RE = re.compile(r"\{([A-Z0-9_]+)\}")

_ROWS: dict[str, dict] = {}
if CSV_PATH.exists():
    with open(CSV_PATH, newline="", encoding="utf-8") as _f:
        for _row in csv.DictReader(_f):
            _p = (_row.get("param") or "").strip()
            if _p:
                _ROWS[_p] = _row
else:
    raise FileNotFoundError(
        f"参数表不存在：{CSV_PATH}（API_ENV={API_ENV} 对应的 "
        f"{_CSV_NAME} 缺失，请确认文件已就位）"
    )


def raw(name: str) -> str:
    """取原始值（不做模板渲染）。

    优先级：进程环境变量 > .env > CSV(value 列)。
    对应环境 CSV 的 value 列为空时抛 KeyError，提示在对应文件补全。
    """
    env_val = os.environ.get(name)
    if env_val:
        return env_val
    row = _ROWS.get(name)
    if row is None:
        raise KeyError(
            f"{_CSV_NAME} 中未找到参数 {name!r}，请检查 CSV 或环境变量"
        )
    value = (row.get("value") or "").strip()
    if value:
        return value
    raise KeyError(
        f"参数 {name!r} 在 {_CSV_NAME} 的 value 列为空，"
        f"请在 {_CSV_NAME} 补全 {name} 的 value 列"
    )


def _resolve(template: str, seen: frozenset = frozenset()) -> str:
    """渲染 {PLACEHOLDER}，循环解析嵌套引用。"""
    def _repl(m: re.Match) -> str:
        key = m.group(1)
        if key in seen:
            raise ValueError(f"路径模板存在循环引用: {key}")
        return _resolve(raw(key), seen | {key})

    return _PLACEHOLDER_RE.sub(_repl, template)


def param(name: str) -> str:
    """取参数值（含模板渲染）。"""
    return _resolve(raw(name))


def path(name: str) -> str:
    """取接口路径（含模板渲染）。"""
    return _resolve(raw(name))


def as_int(name: str) -> int:
    return int(param(name))


# ---- 便捷常量导出（供各脚本 import） ----

# 环境参数（仅两个根：BASE_URL / ADMIN_URL；其余从 BASE_URL 派生或继承）
BASE_URL = param("BASE_URL")
ADMIN_URL = param("ADMIN_URL")


def _pear_url() -> str:
    """Pear SSR 页面根：默认继承 BASE_URL（与 BASE_URL 同根）。

    仅当页面域与 API 域不同时才需要在 CSV 中显式配置（如 release 的 pear.us）；
    value 列为空（或参数缺失）时自动取 BASE_URL。
    """
    row = _ROWS.get("PEAR_URL")
    if row is not None:
        value = (row.get("value") or "").strip()
        if value:
            return value
    return BASE_URL


PEAR_URL = _pear_url()


def _pdp_url() -> str:
    """PDP 商品详情页 URL：优先 CSV 显式配置，缺省回退 PEAR_URL + /resident/p/jjkbor。"""
    row = _ROWS.get("PDP_url")
    if row is not None:
        value = (row.get("value") or "").strip()
        if value:
            return value
    return f"{PEAR_URL}/resident/p/jjkbor"


PDP_URL = _pdp_url()

# 店铺 / 业务对象参数
CURATOR_SHOP_URL = param("CURATOR_SHOP_URL")
CURATOR_POST_ALIAS = param("CURATOR_POST_ALIAS")
POST_ALIAS_B = param("POST_ALIAS_B")
CONSUMER_EMAIL = param("CONSUMER_EMAIL")
CURATOR_EMAIL = param("CURATOR_EMAIL")

# 接口路径（成品，模板已渲染）
STORE_PATH = path("STORE_PATH")
POST_DETAIL_PATH = path("POST_DETAIL_PATH")
POST_B_PATH = path("POST_B_PATH")
CART_PATH = path("CART_PATH")
FEATURE_SETTING_SIGNUP_PATH = path("FEATURE_SETTING_SIGNUP_PATH")
PEAR_STORE_PATH = path("PEAR_STORE_PATH")
PEAR_POST_PATH = path("PEAR_POST_PATH")
SIGNIN_PATH = path("SIGNIN_PATH")
LOGIN_PATH = path("LOGIN_PATH")
ADMIN_PROMOTIONS_PATH = path("ADMIN_PROMOTIONS_PATH")

# 测试参数
CONCURRENT_COUNT = as_int("CONCURRENT_COUNT")
TIMEOUT = as_int("TIMEOUT")


if __name__ == "__main__":
    print(f"API_ENV = {API_ENV}")
    print(f"BASE_URL = {BASE_URL}")
    print(f"POST_DETAIL_PATH = {POST_DETAIL_PATH}")

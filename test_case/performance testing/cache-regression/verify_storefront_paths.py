#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_storefront_paths.py —— storefront 双链路路径冒烟校验。

用【正确路径】确认参数化后 storefront API 与 SSR 页面两条链路都可用：

  1. API 层  : GET {BASE_URL}{STORE_PATH}     → 200 JSON + x-db-query-count header
  2. SSR 层  : GET {PEAR_URL}{PEAR_STORE_PATH} → 200 HTML（SSR 渲染页面）

用途：
  - 切环境（API_ENV=prod）后快速验证 BASE_URL / PEAR_URL 参数是否生效；
  - 修改 API_Parameter_Release.csv（或对应环境参数表）后回归确认 storefront 路径未被破坏。

用法：
  python3 verify_storefront_paths.py            # 默认 release
  API_ENV=prod python3 verify_storefront_paths.py   # 切换 prod 验证
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from api_params import BASE_URL, PEAR_URL, STORE_PATH, PEAR_STORE_PATH  # noqa: E402

HEADERS = {
    "accept": "application/json",
    "from": "client",
    "timezone": "Asia/Shanghai",
}


def main() -> int:
    passed, failed = [], []

    def check(label: str, cond: bool, detail: str = "") -> None:
        (passed if cond else failed).append(label)
        print(f"[{'PASS' if cond else 'FAIL'}] {label} {detail}")

    print(f"BASE_URL        = {BASE_URL}")
    print(f"PEAR_URL        = {PEAR_URL}")
    print(f"STORE_PATH      = {STORE_PATH}")
    print(f"PEAR_STORE_PATH = {PEAR_STORE_PATH}")

    # ---- API 层 ----
    api_url = f"{BASE_URL}{STORE_PATH}"
    try:
        r = httpx.get(api_url, headers=HEADERS, timeout=15)
        ct = r.headers.get("content-type", "")
        dbq = r.headers.get("x-db-query-count", "<missing>")
        check("API: status 200", r.status_code == 200, f"-> {r.status_code}")
        check("API: content-type JSON", "application/json" in ct, f"-> {ct}")
        check("API: x-db-query-count header", dbq != "<missing>", f"-> {dbq}")
    except Exception as e:  # noqa: BLE001
        check(f"API: request {api_url}", False, f"ERR {type(e).__name__}: {e}")

    # ---- SSR 层 ----
    ssr_url = f"{PEAR_URL}{PEAR_STORE_PATH}"
    try:
        r2 = httpx.get(ssr_url, headers=HEADERS, timeout=15)
        ct2 = r2.headers.get("content-type", "")
        check("SSR: status 200", r2.status_code == 200, f"-> {r2.status_code}")
        check("SSR: content-type HTML", "text/html" in ct2, f"-> {ct2}")
    except Exception as e:  # noqa: BLE001
        check(f"SSR: request {ssr_url}", False, f"ERR {type(e).__name__}: {e}")

    print()
    print(f"结果: {len(passed)} passed, {len(failed)} failed")
    if failed:
        print("失败项:", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Cold-start header sanity 独立验证脚本。

用途：排查 x-db-query-count 始终返回 0 的根因。
用法：
    1. 等待 >5 分钟（让缓存过期）
    2. python verify_cold_start_header.py

不依赖 pytest、conftest、任何 fixture，纯 httpx 直连。
"""
import httpx
import sys
import time

# ---- 统一参数中心（按 API_ENV 分环境读取 API_Parameter_Release.csv / API_Parameter_Prod.csv，api_params.py 读取） ----
from api_params import BASE_URL, POST_B_PATH, POST_DETAIL_PATH, STORE_PATH, TIMEOUT
# 消费者 GUEST JWT：guest-login 动态签发（dynamic_ids.guest_token），不落 .env
from dynamic_ids import guest_token

# ---- 端点定义（环境/路径全部来自对应环境的 API_Parameter_*.csv） ----
STORE_URL = f"{BASE_URL}{STORE_PATH}"
POST_URL = f"{BASE_URL}{POST_DETAIL_PATH}"
POST_B_URL = f"{BASE_URL}{POST_B_PATH}"

ENDPOINTS = [
    ("Storefront", STORE_URL),
    ("Post A (11756)", POST_URL),
    ("Post B (ntxccrehh-charity-event)", POST_B_URL),
]

# ---- 公共 Header（消费者 GUEST JWT 由 guest-login 动态签发，不落 .env、不硬编码） ----
HEADERS = {
    "Content-Type": "application/json",
    "from": "client",
    "timezone": "Asia/Shanghai",
    "Authorization": f"Bearer {guest_token()}",
    "Pear-AutoTesting": "Lury",
}


def get_db_queries(resp: httpx.Response) -> str:
    """从响应头提取 x-db-query-count，缺失则返回 N/A。"""
    val = resp.headers.get("x-db-query-count")
    if val is None:
        return "N/A"
    return val


def main():
    results: list[dict] = []

    with httpx.Client(timeout=TIMEOUT) as client:
        for label, url in ENDPOINTS:
            r1 = client.get(url, headers=HEADERS)
            r2 = client.get(url, headers=HEADERS)

            db1 = get_db_queries(r1)
            db2 = get_db_queries(r2)

            results.append({
                "label": label,
                "r1_status": r1.status_code,
                "r1_db": db1,
                "r2_status": r2.status_code,
                "r2_db": db2,
            })

            print(f"=== {label} ===")
            print(f"  #1: status={r1.status_code}, x-db-query-count={db1}")
            print(f"  #2: status={r2.status_code}, x-db-query-count={db2}")
            print()

    # ---- Summary ----
    print("=== Summary ===")
    all_zero_first = all(r["r1_db"] == "0" for r in results)
    all_zero_second = all(r["r2_db"] == "0" for r in results)
    any_pos_first = any(
        r["r1_db"] != "0" and r["r1_db"] != "N/A" for r in results
    )
    second_all_zero_after_pos = any(
        r["r1_db"] != "0" and r["r1_db"] != "N/A" and r["r2_db"] == "0"
        for r in results
    )

    if all_zero_first:
        print("所有端点的 #1 都是 0 — 可能：")
        print("  - 中间件始终返回 0（x-db-query-count 仪表未生效）")
        print("  - 缓存 TTL 远超 5min，用户等待时间不足")
        print("  - 这些端点已被其他请求预热")
        print()
        print("建议：等更长时间（如 15-30min）再跑；或查后端/中间件配置确认 x-db-query-count 是否已部署。")

    # Post B 应最可能冷启动（它未被 cache-regression 套件中的其他测试覆盖）
    post_b = results[2]
    if post_b["r1_db"] != "0" and post_b["r1_db"] != "N/A":
        print(f"Post B 的 #1 DB={post_b['r1_db']} > 0 — 冷启动 header 正常。")
        print("Post A / Storefront 若 #1=0 则说明被其他测试预热过，属预期行为。")
    elif post_b["r1_db"] == "0":
        print("Post B（未被其他测试覆盖）的 #1 也为 0 — 强烈暗示中间件或缓存层存在全局问题。")

    if second_all_zero_after_pos:
        print("存在 #1 > 0 且 #2 = 0 的端点 → 缓存预热机制工作正常。")
    elif all_zero_second and any_pos_first:
        print("异常：#1 > 0 但 #2 也 > 0（未命中缓存）。")

    if any(r["r1_db"] == "N/A" or r["r2_db"] == "N/A" for r in results):
        print()
        print("警告：部分响应缺少 x-db-query-count header！请确认中间件已部署到该端点。")

    return results


if __name__ == "__main__":
    print(f"开始时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("提示：确保距上次请求这些端点已超过 5 分钟（缓存 TTL）。\n")
    main()
    print(f"\n结束时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")

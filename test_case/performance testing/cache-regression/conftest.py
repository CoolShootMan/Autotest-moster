"""
cache-regression 测试套件公共配置与 Fixture。

依赖后端在每个 API 响应的 Header 中注入 X-DB-Query-Count，
表示本次请求产生的数据库查询次数。缓存命中的请求该值必须为 0。
"""
import base64
import json
import os
import uuid

import pytest
import httpx

# ---- 环境变量（通过 export 或 pytest-env 设置，以下为默认值） ----
BASE_URL = os.getenv("PEAR_BASE_URL", "https://release.pear.us")
PEAR_BASE_URL = os.getenv("PEAR_BASE_URL", "https://release.pear.us")
AUTH_TOKEN = os.getenv(
    "PEAR_AUTH_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiIwMDllZWYxOS03MjNkLTQwMmYtOGYxNC1jOWVjM2RiMDhiYTUiLCJlbnYiOiJyZWxlYXNlIiwidXNlclJvbGUiOiJDT05TVU1FUiIsInVzZXJUeXBlIjoiR1VFU1QiLCJpYXQiOjE3ODQ3NzQ0MTEsImV4cCI6MTgxNjMzMjAxMX0._SO2j8P193ZLqSR6Wcm4IF7QzGKdkSnPoF8D3kY-L6w",
)
ORDER_API = os.getenv("PEAR_ORDER_API", "https://release.katana-api.1m.app")

# Admin 端点（用于缓存失效测试）
ADMIN_BASE_URL = os.getenv(
    "ADMIN_BASE_URL", "https://release.admin.katana-api.1m.app"
)
ADMIN_AUTH_HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {os.getenv('ADMIN_AUTH_TOKEN', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6ImxpbmRhLnpob3UuZXh0QDFtLmFwcCIsImFjY2Vzc1JvbGUiOiJTVVBFUl9BRE1JTiIsInNlc3Npb25JZCI6Ijc3MDFkNzRiLTQ3ZDgtNDE5Zi1hY2Q2LWRhZWRmMWRhYmFjMyIsImlhdCI6MTc4NDI1OTUyMH0.soY_4ZTHjb0nqSAlpNul5getiEUjRV5eL49MUkj_RHc')}",
}

# Promotion 端点（用于 promotion 缓存回归测试）
PROMO_BASE_URL = os.getenv(
    "PROMO_BASE_URL", "https://release.katana-api.1m.app"
)
PROMO_EMAIL = "linda.zhou.ext+05@1m.app"
PROMO_PASSWORD_HASH = "7EbE8F4BdE4A38768AcF9C2833aF2Db5"

# 公共 Header
COMMON_HEADERS = {
    "Content-Type": "application/json",
    "from": "client",
    "timezone": "Asia/Shanghai",
}

AUTH_HEADERS = {
    **COMMON_HEADERS,
    "Authorization": f"Bearer {AUTH_TOKEN}",
    "Pear-AutoTesting": "Lury",
}

# User B consumerId，用于 guest-login 签发缓存隔离测试专用 token
USER_B_CONSUMER_ID = "4094a2f4-382c-4df2-9536-2ff63ab643d4"

# 透传公共 header（不包含 Authorization token）
PEAR_AUTO_TESTING_HEADER = {"Pear-AutoTesting": "Lury"}


# Katana API（storefront → post detail 实际调用的业务 API）
KATANA_API = os.getenv("KATANA_API", "https://release.katana-api.1m.app")
KATANA_AUTH_HEADERS = AUTH_HEADERS  # katana API 复用同一鉴权 headers


# ---- Fixtures ----
@pytest.fixture(scope="function")
async def http_client():
    """函数级 httpx AsyncClient，避免 teardown 时 event loop 已关闭。"""
    async with httpx.AsyncClient(timeout=30) as client:
        yield client


@pytest.fixture(scope="session")
def user_b_auth_headers():
    """为 User B 签发 GUEST token，用于缓存隔离测试。

    每次测试会话启动时调用一次 guest-login，token 有效期约 1 年，
    实际单次测试会话远短于此，无需刷新。
    """
    import httpx

    resp = httpx.post(
        f"{KATANA_API}/auth/guest-login",
        json={"consumerId": USER_B_CONSUMER_ID},
        timeout=10,
    )
    assert resp.status_code in (200, 201), (
        f"User B guest-login failed: {resp.status_code} {resp.text}"
    )
    token = resp.json()["data"]
    return {
        **COMMON_HEADERS,
        "Authorization": f"Bearer {token}",
        **PEAR_AUTO_TESTING_HEADER,
    }


@pytest.fixture(scope="session")
def promo_auth_headers():
    """为 promoter 签发 token，用于 promotion 缓存测试。"""
    import httpx

    resp = httpx.post(
        f"{KATANA_API}/auth/sign-in",
        json={
            "email": PROMO_EMAIL,
            "password": PROMO_PASSWORD_HASH,
            "subdomainVanityUrl": "resident",
        },
        timeout=10,
    )
    assert resp.status_code in (200, 201), (
        f"Promoter sign-in failed: {resp.status_code} {resp.text}"
    )
    token = resp.json()["data"]["token"]
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


@pytest.fixture(scope="function")
async def pear_context():
    """Function-scoped Playwright browser context，用于 Pear SSR 测试。

    每个测试函数独立创建/销毁 browser context，避免跨测试 cookie 污染。
    """
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context()
    yield ctx
    await ctx.close()
    await browser.close()
    await pw.stop()


async def navigate_pear_page(context, path: str) -> tuple[int, int]:
    """用 Playwright 导航 Pear SSR 页面，从 console.log 抓取 x-db-query-count。

    通过 msg.args[5]（response headers dict）直接读取 x-db-query-count，
    不再依赖 msg.text + 正则（msg.text 有 ~150 chars 截断限制）。

    Args:
        context: Playwright browser context
        path: 页面路径，如 "/resident" 或 "/resident/post/11756"

    Returns:
        (db_queries, http_status) — db_queries 为 -1 表示未捕获到
    """
    from playwright.async_api import Page

    page: Page = await context.new_page()
    count = -1
    _console_msgs: list = []  # 收集候选 console 消息，稍后异步提取 args

    def on_console(msg):
        # 预筛选：args 长度 >= 7 且 args[5] 为 response headers 的候选消息
        if len(msg.args) >= 7:
            _console_msgs.append(msg)

    page.on("console", on_console)
    response = await page.goto(
        f"{PEAR_BASE_URL}{path}",
        wait_until="networkidle",
        timeout=30000
    )
    # 等 console 刷新
    import asyncio
    await asyncio.sleep(2)

    # 异步提取 args[5] 中的 x-db-query-count
    for msg in _console_msgs:
        try:
            headers = await msg.args[5].json_value()
            if isinstance(headers, dict) and "x-db-query-count" in headers:
                raw = headers["x-db-query-count"]
                count = int(raw) if raw is not None else -1
                break
        except Exception:
            continue

    status = response.status if response else 0
    await page.close()
    return count, status


# ---- 工具函数 ----
def get_db_queries(response: httpx.Response) -> int:
    """
    从响应头 X-DB-Query-Count 提取本次请求的 DB 查询次数。

    依赖后端始终返回该 Header，值为实际 DB 查询次数（包括 0）。
    返回 -1 表示 Header 缺失（中间件未部署，需告警）。
    """
    try:
        return int(response.headers.get("X-DB-Query-Count", -1))
    except (ValueError, TypeError):
        return -1


def assert_zero_db_queries(
    response: httpx.Response,
    resource: str,
    attempt: str = "verify",
):
    """
    断言本次请求未产生任何 DB 查询（缓存完全命中）。

    Args:
        response: httpx 响应对象。
        resource: 资源标识（如 URL 路径），用于错误信息。
        attempt: 请求阶段描述（如 "warm-up" / "verify" / "concurrent-3"）。
    """
    db_queries = get_db_queries(response)
    assert db_queries != -1, (
        f"X-DB-Query-Count header missing — backend instrumentation not deployed?\n"
        f"Resource: {resource}"
    )
    assert db_queries == 0, (
        f"Cache regression detected!\n"
        f"Resource: {resource}\n"
        f"Attempt: {attempt}\n"
        f"Expected DB queries: 0\n"
        f"Actual DB queries:   {db_queries}\n"
        f"Status: {response.status_code}"
    )


# ---- 全局前置检查 ----
@pytest.fixture(scope="session", autouse=True)
def header_integrity_check():
    """在所有测试之前探测 x-db-query-count header 是否可信。

    用随机 UUID 签发全新 GUEST token，解码 JWT 提取 userId，
    访问 per-user 资源 /feature-flag/user/{userId}。
    新 userId 从未被查询过，缓存不可能跨用户共享，保证 100% 冷启动。
    """
    # 1. 用随机 UUID 签发全新 GUEST token
    consumer_id = str(uuid.uuid4())
    resp = httpx.post(
        f"{KATANA_API}/auth/guest-login",
        json={"consumerId": consumer_id},
        timeout=10,
    )
    if resp.status_code not in (200, 201):
        pytest.exit(
            f"BLOCKED: header_integrity_check failed to get guest token "
            f"(status={resp.status_code}). Cannot verify x-db-query-count."
        )

    token = resp.json()["data"]

    # 2. 解码 JWT payload，提取 userId
    try:
        payload_b64 = token.split(".")[1]
        # base64url → base64 标准补齐
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload_json = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
        jwt_payload = json.loads(payload_json)
        user_id = jwt_payload["userId"]
    except Exception as exc:
        pytest.exit(
            f"BLOCKED: header_integrity_check failed to decode JWT "
            f"({exc}). Cannot extract userId."
        )

    integrity_headers = {
        **COMMON_HEADERS,
        "Authorization": f"Bearer {token}",
        **PEAR_AUTO_TESTING_HEADER,
    }

    FEATURE_FLAG_URL = f"{KATANA_API}/feature-flag/user/{user_id}"

    # 3. 访问 per-user 资源（新 userId，100% 冷启动）
    try:
        r = httpx.get(FEATURE_FLAG_URL, headers=integrity_headers, timeout=15)
    except Exception as exc:
        print(
            f"[header_integrity_check] WARNING: API call failed ({exc}). "
            "Network issue — skipping check, tests will proceed."
        )
        return

    if r.status_code != 200:
        print(
            f"[header_integrity_check] WARNING: API returned {r.status_code} "
            f"({FEATURE_FLAG_URL}). Skipping check."
        )
        return

    # 4. 检查 x-db-query-count
    try:
        db_count = int(r.headers.get("X-DB-Query-Count", -1))
    except (ValueError, TypeError):
        db_count = -1

    if db_count == -1:
        pytest.exit(
            "BLOCKED: x-db-query-count header missing. "
            "Check backend deployment."
        )
    if db_count == 0:
        pytest.exit(
            "BLOCKED: x-db-query-count header always returns 0 (BE bug). "
            "All cache regression tests are invalid until fixed."
        )

    # db_count > 0 → header 正常，放行

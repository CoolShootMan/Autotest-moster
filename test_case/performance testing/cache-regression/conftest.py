"""
cache-regression 测试套件公共配置与 Fixture。

依赖后端在每个 API 响应的 Header 中注入 X-DB-Query-Count，
表示本次请求产生的数据库查询次数。缓存命中的请求该值必须为 0。
"""
import base64
import collections
import json
import os
import uuid
from collections import OrderedDict
from datetime import datetime

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


# ---- 全局 GET 请求审计（network 层自动捞取所有 GET API） ----
# 记录每个请求的 method/url/status/x-db-query-count，测试结束后生成审计报告，
# 凡 GET 接口预热后仍读 DB 的，在最终报告中抛出。
REQUEST_LOG = []


def _record_request(method: str, url: str, status: int, db: int, source: str = "httpx"):
    """记录一次请求到全局审计日志。"""
    REQUEST_LOG.append(
        {"method": method, "url": url, "status": status, "db": db, "source": source}
    )


def _extract_db_from_response(response: httpx.Response) -> int:
    """从响应头提取 x-db-query-count，缺失返回 -1。"""
    try:
        return int(response.headers.get("X-DB-Query-Count", -1))
    except (ValueError, TypeError):
        return -1


def _is_integrity_probe(url: str) -> bool:
    """header_integrity_check 的探测请求（/feature-flag/）不纳入业务审计。"""
    return "/feature-flag/" in url


# ---- Fixtures ----
@pytest.fixture(scope="function")
async def http_client():
    """函数级 httpx AsyncClient，避免 teardown 时 event loop 已关闭。

    挂 response event hook 自动捞取所有请求（GET/PATCH/PUT 均记录）
    进入全局 REQUEST_LOG，供测试结束后的 GET API DB 审计报告使用。
    """
    async def _on_response(response):
        _record_request(
            method=response.request.method,
            url=str(response.request.url),
            status=response.status_code,
            db=_extract_db_from_response(response),
        )

    async with httpx.AsyncClient(
        timeout=30, event_hooks={"response": [_on_response]}
    ) as client:
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
    url: str = "",
    warmup_db_queries: int = None,
):
    """
    断言本次请求未产生任何 DB 查询（缓存完全命中）。

    Args:
        response: httpx 响应对象。
        resource: 资源标识（如 URL 路径），用于错误信息。
        attempt: 请求阶段描述（如 "warm-up" / "verify" / "concurrent-3"）。
        url: 完整请求 URL（可选，提供时为错误信息补充完整端点地址）。
        warmup_db_queries: 预热阶段的 DB 查询次数（可选）。提供时在错误信息中
            追加 warm-up → verify 对比，帮助诊断缓存未命中的根因。
    """
    db_queries = get_db_queries(response)
    full_url_line = f"\n  Endpoint: GET {url}" if url else ""
    assert db_queries != -1, (
        f"X-DB-Query-Count header missing — backend instrumentation not deployed?\n"
        f"  Resource: {resource}{full_url_line}"
    )

    # 构建预热 → 验证对比信息
    warmup_line = ""
    if warmup_db_queries is not None and warmup_db_queries >= 0:
        if warmup_db_queries == 0:
            warmup_line = (
                f"\n  Warm-up DB queries: 0 → Verify DB queries: {db_queries}\n"
                f"  Warning: warm-up also returned 0 — "
                f"header instrumentation may be broken on both phases, not a cache regression."
            )
        else:
            warmup_line = (
                f"\n  Warm-up DB queries: {warmup_db_queries} → Verify DB queries: {db_queries}\n"
                f"  Cache effectiveness: 0% "
                f"(warm-up populated {warmup_db_queries} DB queries but verify leaked {db_queries})"
            )

    assert db_queries == 0, (
        f"Cache regression detected!{full_url_line}{warmup_line}\n"
        f"  Phase: {attempt} (2nd read after warm-up)\n"
        f"  Expected: x-db-query-count = 0\n"
        f"  Actual:   x-db-query-count = {db_queries}\n"
        f"  Action: This endpoint leaked {db_queries} DB queries on a supposed cache hit.\n"
        f"  Check: 1) Is the cache middleware deployed for this endpoint?\n"
        f"         2) Is the cache TTL shorter than the interval between warm-up and verify?\n"
        f"         3) Did the warm-up response properly populate the cache?\n"
        f"         4) Redis connection lost or cache evicted between warm-up and verify?"
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


# ---- 测试结束后的 GET API DB 审计报告 ----
def _write_get_db_audit_report() -> str:
    """生成 GET API DB 审计报告，返回报告文件绝对路径。

    判定口径：
    - 首次请求（冷启动/预热）DB>0 视为正常穿透，仅记录不判定违规；
    - 同一 GET URL 第 2 次及以后仍 DB>0 → 缓存未命中，判定违规并抛出；
    - header_integrity_check 的 /feature-flag/ 探测请求已过滤，不纳入统计。
    """
    now = datetime.now()
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, f"get_api_db_audit_{now:%Y%m%d_%H%M%S}.md")

    # 筛选：GET 业务请求（排除 feature-flag 探测）
    get_entries = [
        e for e in REQUEST_LOG
        if e["method"] == "GET" and not _is_integrity_probe(e["url"])
    ]

    # 按 URL 分组（保持首次出现顺序）
    grouped = OrderedDict()
    for e in get_entries:
        grouped.setdefault(e["url"], []).append(e)

    lines = []
    lines.append("# GET API DB 读取审计报告")
    lines.append("")
    lines.append(f"- 生成时间：{now:%Y-%m-%d %H:%M:%S}")
    lines.append(f"- GET 请求总数：{len(get_entries)}")
    lines.append(f"- 去重 GET 接口数：{len(grouped)}")
    lines.append("")

    violations = []
    details = []
    for url, entries in grouped.items():
        db_seq = [e["db"] for e in entries]
        status_seq = [e["status"] for e in entries]
        # 仅 2xx 响应计入 DB 判定（非 2xx 时 DB 计数不可信）
        valid_indices = [i for i, s in enumerate(status_seq) if 200 <= s < 300]
        # 违规：第 2 次及以后的 2xx 请求 DB>0
        leaked = [
            (i + 1, db_seq[i], status_seq[i])
            for i in valid_indices
            if i >= 1 and db_seq[i] > 0
        ]
        # 首次是否冷启动穿透
        first_db = db_seq[0] if db_seq else -1
        first_ok = 200 <= status_seq[0] < 300
        is_violation = len(leaked) > 0
        dist_counter = collections.Counter(db_seq)
        dist = " | ".join(
            f"{q}DB×{c}次" for q, c in sorted(dist_counter.items())
        )
        if is_violation:
            violations.append((url, db_seq, status_seq))
        status_mark = "违规(预热后未命中)" if is_violation else "通过"
        details.append((url, len(entries), dist, status_mark))

    lines.append(f"## 结果总览")
    lines.append("")
    lines.append(f"- **违规接口数（预热后仍读 DB）：{len(violations)}**")
    lines.append("")
    if not violations:
        lines.append("### 全部 GET 均为 0 DB 读取（预热后缓存完全命中），无违规项。")
        lines.append("")
    else:
        lines.append("## 违规接口（预热后仍读 DB，需关注）")
        lines.append("")
        lines.append("| # | GET URL | 请求顺序→DB数 |")
        lines.append("|---|---------|--------------|")
        for idx, (url, db_seq, status_seq) in enumerate(violations, 1):
            seq_str = " → ".join(
                f"#{i + 1}(DB={db}, HTTP={s})" for i, (db, s) in enumerate(zip(db_seq, status_seq))
            )
            lines.append(f"| {idx} | `{url}` | {seq_str} |")
        lines.append("")

    lines.append("## 全部 GET 明细")
    lines.append("")
    lines.append("| # | GET URL | 请求次数 | DB 分布 | 状态 |")
    lines.append("|---|---------|---------|---------|------|")
    for idx, (url, count, dist, status_mark) in enumerate(details, 1):
        lines.append(f"| {idx} | `{url}` | {count} | {dist} | {status_mark} |")
    lines.append("")

    lines.append("## 判定口径")
    lines.append("")
    lines.append("- 首次请求（冷启动/预热）DB>0 视为正常穿透，仅记录不判定违规；")
    lines.append("- 同一 GET URL 第 2 次及以后仍 DB>0 → 缓存未命中，判定违规并抛出；")
    lines.append("- 非 2xx 响应的 DB 计数不可信，不参与违规判定；")
    lines.append("- header_integrity_check 的 /feature-flag/ 探测请求已过滤；")
    lines.append("- DB=-1 表示 X-DB-Query-Count header 缺失（后端埋点未部署）。")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return report_path


def pytest_sessionstart(session):
    """会话开始清空请求日志，避免跨会话累积。"""
    REQUEST_LOG.clear()


def pytest_sessionfinish(session, exitstatus):
    """测试结束后：tear-down 清理测试购物车 + 生成 GET API DB 审计报告。"""
    try:
        # tear-down：DELETE /cart 清空测试购物车，
        # 避免每日 CI 跑测中 PUT /cart 加购导致 quantity 无限累加
        resp = httpx.delete(f"{KATANA_API}/cart", headers=AUTH_HEADERS, timeout=15)
        print(f"\n[tear-down] DELETE {KATANA_API}/cart -> {resp.status_code}")
    except Exception as exc:  # 清理失败不阻断测试结果
        print(f"\n[tear-down] DELETE /cart 失败: {exc}")
    try:
        report_path = _write_get_db_audit_report()
        print(f"\n[GET API DB 审计] 报告已生成: {report_path}")
    except Exception as exc:  # 报告生成失败不阻断测试
        print(f"\n[GET API DB 审计] 报告生成失败: {exc}")

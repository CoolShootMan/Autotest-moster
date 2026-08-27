"""
cache-regression 测试套件公共配置与 Fixture。

依赖后端在每个 API 响应的 Header 中注入 X-DB-Query-Count，
表示本次请求产生的数据库查询次数。缓存命中的请求该值必须为 0。
"""
import base64
import collections
import hashlib
import json
import os
import re
import uuid
from collections import OrderedDict
from datetime import datetime

import pytest
import httpx
from dotenv import load_dotenv

# 按 API_ENV（release|prod，默认 release）加载对应环境文件 .env.{API_ENV}，
# 不存在时回退本目录 .env：admin 凭据与动态 token 由 precondition_login.py 维护，
# 避免写死 token（旧 token 会过期导致 401）。
_CONF_DIR = os.path.dirname(os.path.abspath(__file__))
_CONF_ENV = os.getenv("API_ENV", "release").strip().lower()
_conf_env_file = os.path.join(_CONF_DIR, f".env.{_CONF_ENV}")
load_dotenv(
    _conf_env_file if os.path.exists(_conf_env_file)
    else os.path.join(_CONF_DIR, ".env")
)

# ---- 统一参数中心（按 API_ENV 分环境读取 API_Parameter_Release.csv / API_Parameter_Prod.csv） ----
# 环境参数 / 店铺业务对象 / 接口路径全部收敛于对应环境 CSV，切生产环境仅需：
#   API_ENV=prod + 在 API_Parameter_Prod.csv 的 value 列填写生产值。
# 敏感凭据（token / 密码）不入 CSV，仍由 .env 提供。
from api_params import (
    ADMIN_URL,
    BASE_URL,
    CART_PATH,
    CONCURRENT_COUNT,
    CURATOR_EMAIL,
    CURATOR_SHOP_URL,
    PEAR_URL,
    POST_DETAIL_PATH,
)
# 动态业务 id（运行时从接口查询，不写死）：CURATOR_POST_ID / promo_path() / user_b_token()
from dynamic_ids import _admin_headers, _admin_token, guest_token, promo_path, user_b_token

# 统一 HTTP 审计模块：所有请求（http_client fixture / dynamic_ids 裸调用 / Playwright 页面
# 响应）集中记录到 REQUEST_LOG，测试结束后生成 GET API DB 审计报告。
from audit_http import REQUEST_LOG, get_async_client, get_sync_client, record_request

# curator（promoter）登录账号邮箱（敏感凭据由 .env 提供）
PROMO_EMAIL = CURATOR_EMAIL

# 消费者 GUEST JWT：不落 .env，由 guest-login 动态签发（dynamic_ids.guest_token）
AUTH_TOKEN = guest_token()

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

# 透传公共 header（不包含 Authorization token）
PEAR_AUTO_TESTING_HEADER = {"Pear-AutoTesting": "Lury"}


# Katana API（storefront → post detail 实际调用的业务 API）
KATANA_AUTH_HEADERS = AUTH_HEADERS  # katana API 复用同一鉴权 headers


# ---- 全局 GET 请求审计（network 层自动捞取所有 GET API） ----
# 请求日志统一由 audit_http.REQUEST_LOG 维护：http_client fixture（event hook）、
# dynamic_ids 裸调用（audit_http.get_sync_client()）、Playwright 页面响应
# （navigate_pear_page 的 response 监听）三类来源全部汇入同一日志，
# 使"预热后二次读取仍读 DB"的审计覆盖到全部真实 GET，不再有盲区。
# 兼容引用：保留 conftest._record_request 名称，实际指向 audit_http 的统一实现；
# conftest.REQUEST_LOG 即 audit_http.REQUEST_LOG（见上方 import）。

def _record_request(method: str, url: str, status: int, db: int, source: str = "httpx"):
    """记录一次请求到全局审计日志（audit_http 统一实现）。"""
    record_request(method=method, url=url, status=status, db=db, source=source)


def _is_integrity_probe(url: str) -> bool:
    """历史遗留：早期按 /feature-flag/ 子串过滤探测请求。

    已废弃：header_integrity_check 的探测请求使用独立 httpx.get（不经 event hook），
    天然不进 REQUEST_LOG；而 storefront 真实业务接口 feature-flag-user /
    feature-flag-public 是合法业务 GET，不应被过滤。故恒返回 False，仅保留占位。
    """
    return False


# ---- Fixtures ----
@pytest.fixture(scope="function")
async def http_client():
    """函数级 httpx AsyncClient，避免 teardown 时 event loop 已关闭。

    复用 audit_http.get_async_client()（挂 response event hook 自动捞取所有请求
    GET/PATCH/PUT/POST 均记录）进入全局 REQUEST_LOG，供审计报告使用。
    """
    async with get_async_client() as client:
        yield client


@pytest.fixture(scope="session")
def user_b_auth_headers():
    """为 User B 签发 GUEST token，用于缓存隔离测试。

    User B 每次会话由 dynamic_ids._user_b_guest() 动态创建全新 GUEST 用户
    （随机 UUID consumerId → guest-login → JWT 解码 userId），
    此处直接复用同一次 guest-login 签发的 token，保证 token 与 consumer id 一一对应。
    """
    token = user_b_token()
    return {
        **COMMON_HEADERS,
        "Authorization": f"Bearer {token}",
        **PEAR_AUTO_TESTING_HEADER,
    }


def _curator_password_hash() -> str:
    """sign-in 的 password 字段为 MD5(明文)；若已是 32 位 hex 则原样透传。"""
    pw = os.getenv("CURATOR_PASSWORD", "7EbE8F4BdE4A38768AcF9C2833aF2Db5")
    if re.fullmatch(r"[0-9a-fA-F]{32}", pw):
        return pw
    return hashlib.md5(pw.encode()).hexdigest()


def _curator_signin() -> str:
    """web 端 curator/promoter 登录：POST {BASE_URL}/auth/sign-in → data.token。

    注意：sign-in token TTL 约 2 分钟，故每次使用前动态签发最可靠；
    测试过程中由 promo_auth_headers fixture 复用会话级 token。
    """
    resp = get_sync_client().post(
        f"{BASE_URL}/auth/sign-in",
        json={
            "email": PROMO_EMAIL,
            "password": _curator_password_hash(),
            "subdomainVanityUrl": CURATOR_SHOP_URL,
        },
        timeout=10,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Promoter sign-in failed: {resp.status_code} {resp.text[:300]}")
    return resp.json()["data"]["token"]


@pytest.fixture(scope="session")
def promo_auth_headers():
    """promoter 会话级 token（web 端 sign-in）：TTL 短、不落 .env，每次会话重新签发。"""
    token = _curator_signin()
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


@pytest.fixture(scope="function")
async def pear_context():
    """Function-scoped Playwright browser context，用于 Pear SSR 测试。

    每个测试函数独立创建/销毁 browser context，避免跨测试 cookie 污染。

    注入统一鉴权 headers（与 http_client 用例同 token 口径）：页面内 GET（/cart、
    product-event、posts/consumer/detail 等）与 httpx 预热共享缓存 key，二次加载
    才能稳定命中缓存（DB=0）。2026-08-25 实测：匿名（无 Authorization）页面加载
    时这些接口以无会话 guest 身份每次新建缓存 key，二次读 DB 剧烈波动（0/1/3/11），
    非真实用户场景，故统一注入 AUTH 使 SSR 断言可靠。

    注意：token 必须"当前时刻"新鲜签发（绕过 _user_b_guest 的 lru_cache），
    不能复用模块级 AUTH_HEADERS 的会话级 token。完整测试套件耗时可达 2 分钟，
    guest JWT TTL 实测约 100s：靠后的 SSR 用例（如 test_storefront_ssr_hit_cache，
    位于 96%）若复用会话 token 已过期，页面内业务 XHR 全部 401（非 2xx），
    navigate_pear_page 统计不到任何带 X-DB-Query-Count 的 2xx GET → count2==-1
    误报"捕获失败"。每次创建 context 时现签发，保证页面内 XHR 恒 2xx。
    """
    from playwright.async_api import async_playwright
    import dynamic_ids

    token, _ = dynamic_ids._user_b_guest.__wrapped__()  # 绕过 lru_cache，取最新 guest JWT
    _headers = {
        **COMMON_HEADERS,
        "Authorization": f"Bearer {token}",
        **PEAR_AUTO_TESTING_HEADER,
    }

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(extra_http_headers=_headers)
    yield ctx
    await ctx.close()
    await browser.close()
    await pw.stop()


def attach_pear_page_audit(page) -> None:
    """给 Playwright 页面挂 response 监听：带 x-db-query-count 的响应写入全局审计日志。

    覆盖 SSR 文档请求与页面内 XHR（如 GET /cart、feature-setting-public 等），
    使浏览器侧真实 GET 也纳入"预热后二次读取仍读 DB"审计（source=playwright）。
    与 navigate_pear_page 的 console 抓取互不冲突：本监听负责全量记录，
    console 抓取只负责提取该页面的代表值。
    """
    def _on_page_response(response):
        db_raw = response.headers.get("x-db-query-count")
        if db_raw is None:
            return
        try:
            db = int(db_raw)
        except (ValueError, TypeError):
            db = -1
        _record_request(
            method=response.request.method,
            url=response.url,
            status=response.status,
            db=db,
            source="playwright",
        )

    page.on("response", _on_page_response)


async def navigate_pear_page(context, path: str, preprime: bool = False) -> tuple[int, int]:
    """用 Playwright 导航 Pear SSR 页面，返回页面级 DB 查询开销。

    页面代表值口径（2026-08-25 起，页面 console 不再打印 x-db-query-count 的
    headers dict，改为打印 status/duration/path/请求头，旧 args[5] 提取失效）：
    - 聚合本次加载期间所有 2xx GET 响应的 X-DB-Query-Count，count = 各值之和，
      即"该页面一次完整加载的 DB 查询总量"；二次加载 count==0 表示页面内全部
      GET 均命中缓存；
    - 页面文档请求本身由 Vercel ISR 预渲染（x-vercel-cache），不带 DB 埋点；
      DB 数据来自页面内 XHR/API 响应头（与 attach_pear_page_audit 同源）；
    - 已知 BE 缺口端点（/store-front/shop/resident?public=false，预热后二次读固定
      DB=2）从页面 count 中排除（由 test_storefront / test_concurrent_read 的
      xfail 用例显式上报），避免同一缺口在多处重复 FAIL；
    - 本次加载无任何带 X-DB-Query-Count 的 2xx GET 响应 → count=-1（埋点失效，
      后端未注入 header，无法判定）。

    preprime=True 时，正式加载前先做一次裸加载（不进审计日志、不计数），用于
    触发页面内的懒加载 XHR（如 PDP 的 feature-flag/user/{id}/public 仅在特定渲染
    时序下发起）完成冷读并填充缓存；否则该 XHR 首次发起恰在 verify 加载时，会
    被误判为"二次读泄漏"（2026-08-25 实测 count 在 0/1/5 间波动即因此）。SSR
    用例的 warm 调用统一 preprime=True，verify 调用保持默认。

    Args:
        context: Playwright browser context
        path: 页面路径，如 "/resident" 或 "/resident/post/11756"
        preprime: 是否先做一次不计审计的裸加载

    Returns:
        (page_db_total, http_status) — page_db_total 为 -1 表示未捕获到任何 DB 头
    """
    from playwright.async_api import Page
    import asyncio

    if preprime:
        # 裸加载：触发页面全部 XHR（含懒加载）冷读并填充缓存；不计审计、不计数。
        # 用 domcontentloaded + expect_response 在 goto 前注册等首个业务 XHR，确保
        # goto 期间已发出的业务响应不遗漏（wait_for_response 是调用后才开始监听）。
        _page: Page = await context.new_page()
        try:
            async with _page.expect_response(
                lambda r: r.request.method == "GET" and "katana-api" in r.url,
                timeout=30000,
            ):
                await _page.goto(
                    f"{PEAR_URL}{path}", wait_until="domcontentloaded", timeout=30000
                )
        except Exception:
            # 首个业务 XHR 超时未等到：页面已完成 domcontentloaded，多数冷读已在 goto
            # 期间完成；显式再走一次 goto 兜底，确保页面加载完成。
            try:
                await _page.goto(
                    f"{PEAR_URL}{path}", wait_until="domcontentloaded", timeout=30000
                )
            except Exception:
                pass
        await asyncio.sleep(2)
        await _page.close()

    page: Page = await context.new_page()
    attach_pear_page_audit(page)
    _db_gets: list[tuple[str, int]] = []  # 页面加载期间带 DB 头的 2xx GET（url, db）
    _skipped_gap: list[str] = []  # 已知 BE 缺口 / 专项兜底端点（排除，不参与页面 count）
    _all_gets: list[str] = []  # 页面加载期间全部 GET 响应（含非 2xx），供 count=-1 诊断

    # 已知 BE 缺口端点（预热后二次读固定 DB>0，由 httpx 用例 xfail 显式上报）与
    # 写-读联动/TTL 敏感资源（预热后二次读由 httpx 专项用例在受控短间隔下严格验证
    # DB=0，SSR 页面级断言纳入会因共享状态/TTL 波动产生 flaky 误报）：
    #   - /store-front/shop/resident         shop-config BE 缺口（固定 DB=2，xfail）
    #   - /cart                              用户购物车：coupon/cart 写操作即失效（test_second_read/buy_now 兜底）
    #   - /posts/consumer/detail             TTL ~10-15s，页面加载累计间隔易超 TTL（test_second_read 兜底）
    # SSR 页面级 count 聚焦其余稳定只读 GET 的缓存命中。
    _SSR_EXCLUDE = ("store-front/shop/resident", "/cart", "/posts/consumer/detail")

    def _on_response(r):
        if r.request.method == "GET":
            _all_gets.append(f"{r.status} {r.url[:110]}")
        if r.request.method != "GET" or not (200 <= r.status < 300):
            return
        db_raw = r.headers.get("x-db-query-count")
        if db_raw is None:
            return
        try:
            db = int(db_raw)
        except (ValueError, TypeError):
            return
        if any(tok in r.url for tok in _SSR_EXCLUDE):
            # 已知 BE 缺口 / 专项兜底端点：不参与页面 count（避免同一资源多处重复
            # FAIL/flaky；其预热后二次读由 httpx 专项用例断言，缺口由 xfail 上报）。
            _skipped_gap.append(f"{r.status} DB={db} {r.url[:90]}")
            return
        _db_gets.append((r.url, db))

    page.on("response", _on_response)

    # 页面业务 XHR 由 JS 懒加载触发，networkidle 常在 JS 执行前判定，固定 sleep
    # 会让统计窗口早于懒加载 XHR 关闭（CI 曾 count=-1 仅捕获静态资源，2026-08-26）。
    # 故改为：goto 用 domcontentloaded，随后轮询等待业务 GET 静默（1.5s 无新增即视为
    # 静默，上限 20s）；count=-1 且本次连业务 XHR 都未发起（纯静态资源）时，视为偶发
    # 渲染/时序失败，自动重载重试一次，消除 flaky。
    import time as _time

    final_count, final_status = -1, 0
    for attempt in range(2):
        response = await page.goto(
            f"{PEAR_URL}{path}",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        # ---- 两阶段统计窗口（消除残留时序 flaky，2026-08-27）----
        # 阶段1：等页面发起至少一个业务 GET（katana-api 域），最长 30s。旧实现
        #        "1.5s 无新增即静默"会在页面 JS 尚未执行到数据请求阶段时就误判静默、
        #        提前截断窗口（CI #25 捕获 171 条全静态、0 业务 XHR 即此），阶段1 确保
        #        JS 真正进入请求阶段后窗口才开放。
        _dl1 = _time.monotonic() + 30
        while _time.monotonic() < _dl1:
            if any("katana-api" in u for u in _all_gets):
                break
            await asyncio.sleep(0.5)
        # 阶段2：业务 XHR 出现后等其静默（1.5s 无新业务 GET，最多 15s），覆盖懒加载
        #        多请求；静默后即关闭窗口，不拖长验证间隔，保持对 TTL(~10-15s) 的敏感。
        _dl2 = _time.monotonic() + 15
        _prev_biz = sum(1 for u in _all_gets if "katana-api" in u)
        _last_changed = _time.monotonic()
        while _time.monotonic() < _dl2:
            _cur_biz = sum(1 for u in _all_gets if "katana-api" in u)
            if _cur_biz > _prev_biz:
                _prev_biz = _cur_biz
                _last_changed = _time.monotonic()
            elif _time.monotonic() - _last_changed >= 1.5:
                break
            await asyncio.sleep(0.25)

        if _skipped_gap:
            print(
                f"[ssr-audit] 已知 BE 缺口端点（已排除，由 httpx 用例 xfail 上报）: "
                f"{'; '.join(_skipped_gap)}"
            )

        _count = sum(db for _, db in _db_gets) if _db_gets else -1
        _status = response.status if response else 0
        if _count == -1 and _all_gets:
            # count=-1 表示未捕获到任何带 X-DB-Query-Count 的 2xx GET。打印本次加载
            # 全部 GET 响应（含 304/401/403/5xx），区分"页面 XHR 未发起/被 304/被 401
            # 拦截"等真实原因，避免再误判为 console/监听时机问题（2026-08-26 定位）。
            print(
                f"[ssr-audit] {path} count=-1 诊断：本次加载捕获 {len(_all_gets)} 条 GET"
                f"（含非 2xx），无任何带 X-DB-Query-Count 的 2xx："
            )
            for line in _all_gets[-40:]:
                print(f"    {line}")
        if _count > 0:
            detail = "; ".join(
                f"DB={db} {url[:80]}" for url, db in _db_gets if db > 0
            )
            print(f"[ssr-audit] {path} 本次加载 count={_count} 明细: {detail}")

        _has_biz_xhr = any("katana-api" in u for u in _all_gets)
        if _count != -1 or _has_biz_xhr:
            final_count, final_status = _count, _status
            break
        # count=-1 且无业务 XHR（纯静态资源）：页面 JS 未执行到数据请求阶段，偶发
        # 渲染失败，重载一次再试（同一 context 新 page）。
        print(
            f"[ssr-audit] {path} count=-1 且本次加载未发起任何业务 XHR"
            f"（{len(_all_gets)} 条 GET 均为静态资源），重载重试 attempt={attempt + 1}/2"
        )
        await page.close()
        page = await context.new_page()
        attach_pear_page_audit(page)
        page.on("response", _on_response)
        _db_gets.clear()
        _skipped_gap.clear()
        _all_gets.clear()
    else:
        final_count, final_status = _count, _status

    await page.close()
    return final_count, final_status


# ---- 工具函数 ----
def get_db_queries(response: httpx.Response) -> int:
    """从响应头 X-DB-Query-Count 提取 DB 查询次数；缺失返回 -1。"""
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


async def assert_zero_db_queries_async(
    response: httpx.Response,
    client,
    url: str,
    headers: dict | None = None,
    *,
    resource: str,
    attempt: str = "verify",
    warmup_db_queries: int = None,
    max_retries: int = 1,
):
    """预热后二次读断言（async 版，支持 BE 瞬态穿透即时重试）。

    语义：KAT-11756 验证"预热后二次读 DB=0"。真实环境下 BE 缓存偶发瞬态穿透——
    共享 token 的购物车 / coupon 缓存会被前序用例的写操作（PATCH coupons、
    PUT/DELETE /cart 等）周期性失效，或恰逢 TTL 边界抖动——单次 verify 偶发 DB>0
    并非持续泄漏。此时对**同一 URL、同鉴权态**毫秒级即时重试：

    - 重试命中 DB=0 → BE 瞬态穿透，缓存已回填，判定通过并打印 [retry-hit] 告警；
    - 重试仍 DB>0  → 判定为持续泄漏（真实缓存回归），抛原始断言（附重试结果）。

    Args:
        response: 原始 verify 的 httpx 响应（首读）。
        client: 与原始请求一致的 async httpx client（保证同鉴权态重放）。
        url: 完整请求 URL（重试目标）。
        headers: 与原始请求一致的请求头。
        resource / attempt / warmup_db_queries: 透传给 assert_zero_db_queries。
        max_retries: 即时重试次数（默认 1，穿透后缓存通常已回填）。
    """
    db = get_db_queries(response)
    if db == -1 or db == 0:
        # header 缺失（埋点失效）或已命中：走原断言（header 缺失照样抛）
        assert_zero_db_queries(
            response, resource=resource, attempt=attempt, url=url,
            warmup_db_queries=warmup_db_queries,
        )
        return

    # 首读 DB>0：即时重试至多 max_retries 次
    retried_db: int | None = None
    for _ in range(max_retries):
        retry_resp = await client.get(url, headers=headers or {})
        retried_db = get_db_queries(retry_resp)
        if retried_db == 0:
            print(
                f"[retry-hit] {url}\n"
                f"  首读 DB={db}（BE 瞬态穿透）→ 即时重试 DB={retried_db}，"
                f"缓存已回填，放行（attempt={attempt}）"
            )
            return

    # 重试仍 DB>0：持续泄漏，抛原断言并附重试结果
    try:
        assert_zero_db_queries(
            response, resource=resource, attempt=attempt, url=url,
            warmup_db_queries=warmup_db_queries,
        )
    except AssertionError as exc:
        raise AssertionError(
            f"{exc}\n  [retry] 同 URL 即时重试 {max_retries} 次后仍 DB={retried_db}"
            f"——判定为持续泄漏（非瞬态穿透）。"
        ) from exc


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
        f"{BASE_URL}/auth/guest-login",
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

    FEATURE_FLAG_URL = f"{BASE_URL}/feature-flag/user/{user_id}"

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
def _normalize_url(url: str) -> str:
    """URL 归一化：去除尾部空 query（如 `cart?` → `cart`），避免同接口被拆散。"""
    return url[:-1] if url.endswith("?") else url


def _write_get_db_audit_report() -> str:
    """生成 GET API DB 审计报告，返回报告文件绝对路径。

    判定口径：
    - 同一归一化 GET URL 的 2xx 请求序列中，第 1 次（冷启动/预热）DB>0 视为正常穿透；
    - 第 2 次及以后仍 DB>0 → 缓存未命中，判定违规（大流量涌入时会打到 DB，风险接口）；
    - 仅 1 次 2xx 请求的接口：无二次读取样本，标记"未验证"，不判通过也不判违规；
    - 非 2xx 响应的 DB 计数不可信，不参与违规判定；
    - 请求来源含 http_client / dynamic_ids 裸调用 / Playwright 页面响应三类
      （source ∈ {httpx, playwright}），全部纳入统计，不再有审计盲区。
    """
    now = datetime.now()
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, f"get_api_db_audit_{now:%Y%m%d_%H%M%S}.md")

    # 筛选：GET 业务请求（探测请求本就经独立 httpx 发出、不进日志，无需再过滤）
    get_entries = [e for e in REQUEST_LOG if e["method"] == "GET"]

    # 按归一化 URL 分组（保持首次出现顺序）
    grouped = OrderedDict()
    for e in get_entries:
        grouped.setdefault(_normalize_url(e["url"]), []).append(e)

    source_counter = collections.Counter(e["source"] for e in REQUEST_LOG)

    lines = []
    lines.append("# GET API DB 读取审计报告")
    lines.append("")
    lines.append(f"- 生成时间：{now:%Y-%m-%d %H:%M:%S}")
    lines.append(f"- 请求来源分布：{dict(source_counter)}")
    lines.append(f"- GET 请求总数：{len(get_entries)}")
    lines.append(f"- 去重 GET 接口数：{len(grouped)}")
    lines.append("")

    violations = []
    unverified = []
    passed = []
    details = []
    for url, entries in grouped.items():
        db_seq = [e["db"] for e in entries]
        status_seq = [e["status"] for e in entries]
        # 仅 2xx 响应计入 DB 判定（非 2xx 时 DB 计数不可信）
        valid_indices = [i for i, s in enumerate(status_seq) if 200 <= s < 300]
        # 违规：按 2xx 有效请求序列的第 2 次及以后 DB>0 判定；
        # 首个 2xx（无论其在原始序列中的位置）视为冷启动/预热穿透，不判违规。
        leaked = [
            (i + 1, db_seq[i], status_seq[i])
            for n, i in enumerate(valid_indices)
            if n >= 1 and db_seq[i] > 0
        ]
        first_db = db_seq[0] if db_seq else -1
        first_ok = 200 <= status_seq[0] < 300
        is_violation = len(leaked) > 0
        dist_counter = collections.Counter(db_seq)
        dist = " | ".join(
            f"{q}DB×{c}次" for q, c in sorted(dist_counter.items())
        )
        n_2xx = len(valid_indices)
        if is_violation:
            status_mark = "违规(预热后未命中)"
            violations.append((url, db_seq, status_seq))
        elif n_2xx < 2:
            # 仅 1 次 2xx 请求：无二次读取样本，无法验证预热后是否命中缓存
            status_mark = "未验证(仅1次请求)"
            unverified.append((url, len(entries), dist, status_mark))
        else:
            status_mark = "通过(预热后DB=0)"
            passed.append((url, len(entries), dist, status_mark))
        details.append((url, len(entries), dist, status_mark))

    lines.append(f"## 结果总览")
    lines.append("")
    lines.append(f"- **违规接口数（预热后仍读 DB）：{len(violations)}**")
    lines.append(f"- 未验证接口数（仅 1 次请求，无二次读取样本）：{len(unverified)}")
    lines.append(f"- 通过接口数（预热后 DB=0）：{len(passed)}")
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

    lines.append("## 未验证接口（仅 1 次请求，大流量前建议补二次读取验证）")
    lines.append("")
    lines.append("| # | GET URL | 请求次数 | DB 分布 |")
    lines.append("|---|---------|---------|---------|")
    for idx, (url, count, dist, _) in enumerate(unverified, 1):
        lines.append(f"| {idx} | `{url}` | {count} | {dist} |")
    lines.append("")

    lines.append("## 全部 GET 明细")
    lines.append("")
    lines.append("| # | GET URL | 请求次数 | DB 分布 | 状态 |")
    lines.append("|---|---------|---------|---------|------|")
    for idx, (url, count, dist, status_mark) in enumerate(details, 1):
        lines.append(f"| {idx} | `{url}` | {count} | {dist} | {status_mark} |")
    lines.append("")

    # ---- 写接口（PUT/PATCH/POST）DB 读取明细 ----
    # 写接口读 DB 是期望行为，不判违规；此处用于暴露 promotion/coupon 读取实际发生在
    # 哪条接口——例如 PUT /cart 加购时 promotion service 自动读 coupon 计算折扣
    # （totalCouponDiscount 即其产物），该 DB 查询不在独立 GET 接口上。
    write_entries = [e for e in REQUEST_LOG if e["method"] != "GET"]
    write_grouped = OrderedDict()
    for e in write_entries:
        key = f"{e['method']} {_normalize_url(e['url'])}"
        write_grouped.setdefault(key, []).append(e)

    lines.append("## 写接口（PUT/PATCH/POST）DB 读取明细")
    lines.append("")
    lines.append("- 写接口读 DB 是期望行为，不判违规；用于暴露 promotion/coupon 配置读取发生在哪条接口。")
    lines.append("")
    if not write_grouped:
        lines.append("无写接口请求。")
        lines.append("")
    else:
        lines.append("| # | Method URL | 请求次数 | DB 分布 |")
        lines.append("|---|-----------|---------|---------|")
        for idx, (key, entries) in enumerate(write_grouped.items(), 1):
            db_seq = [e["db"] for e in entries]
            dist_counter = collections.Counter(db_seq)
            dist = " | ".join(
                f"{q}DB×{c}次" for q, c in sorted(dist_counter.items())
            )
            lines.append(f"| {idx} | `{key}` | {len(entries)} | {dist} |")
        lines.append("")

    lines.append("## 判定口径")
    lines.append("")
    lines.append("- 同一归一化 GET URL 的 2xx 请求序列中，第 1 次（冷启动/预热）DB>0 视为正常穿透；")
    lines.append("- 第 2 次及以后仍 DB>0 → 缓存未命中，判定违规；")
    lines.append("- 仅 1 次 2xx 请求的接口标记'未验证'（无二次读取样本，不判通过/违规）；")
    lines.append("- 非 2xx 响应的 DB 计数不可信，不参与违规判定；")
    lines.append("- 请求来源覆盖 http_client / dynamic_ids 裸调用 / Playwright 页面响应三类；")
    lines.append("- DB=-1 表示 X-DB-Query-Count header 缺失（后端埋点未部署）。")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return report_path


def pytest_sessionstart(session):
    """会话开始清空请求日志，避免跨会话累积。"""
    REQUEST_LOG.clear()


# ---- Admin 凭据与 promotion id 动态匹配（禁写死 promotionId / token） ----
# admin token 统一复用 dynamic_ids._admin_token()（lru_cache 会话内缓存；
# 401 时清缓存强制刷新）。凭据 ADMIN_EMAIL/ADMIN_PASSWORD 由 .env 提供。


def _admin_login(force: bool = False) -> str:
    """复用 dynamic_ids 的 admin 动态登录；force=True 时清缓存强制刷新。"""
    if force:
        _admin_token.cache_clear()
    return _admin_token()


def _admin_auth_headers() -> dict:
    """admin 请求头：复用 dynamic_ids 的动态登录头。"""
    return _admin_headers()


def _admin_find_promotion_id(title: str, description: str = "") -> str:
    """通过 admin GET /promotions 按 title + description 唯一匹配 promotionId。

    searchTerm 用 title（或 description）做关键字过滤，再精确校验 title/description，
    返回匹配项的 id；匹配不到抛出 AssertionError。

    token 过期防护：首次请求若返回 401，自动强制重新登录（POST /auth/login）后重试一次，
    确保不会因旧 token 过期而失败。
    """
    from urllib.parse import quote

    search = title or description
    url = f"{ADMIN_URL}/promotions?searchTerm={quote(search)}&pageSize=20&pageNumber=1"

    def _query(headers: dict) -> tuple[int, list]:
        resp = get_sync_client().get(url, headers=headers, timeout=20)
        if resp.status_code != 200:
            return resp.status_code, []
        data = resp.json()
        items = data.get("data", data.get("items", data.get("list", [])))
        if isinstance(items, dict):
            items = items.get("list") or items.get("items") or items.get("records") or []
        return resp.status_code, items

    # 第一次：用现有 token（.env / 环境变量 / 缓存）
    status, items = _query(_admin_auth_headers())

    # 401 → token 过期：清缓存强制重新登录后重试一次
    if status == 401:
        token = _admin_login(force=True)
        status, items = _query(_admin_auth_headers())
        if status == 200:
            print(f"[admin] token 过期已自动刷新（新 token 长度 {len(token)}）")

    if status != 200:
        raise RuntimeError(f"admin GET /promotions failed: {status}")

    for it in items:
        if it.get("title") == title and (not description or it.get("description") == description):
            return str(it["id"])
    raise AssertionError(
        f"admin 中未匹配到 promotion: title={title!r} description={description!r}。"
        f"searchTerm={search!r} 返回 {len(items)} 条"
    )


def _clear_promotions() -> None:
    """tear-down：清空 promotion 测试 post 的 coupons（PATCH 空 promotions 数组）。

    - 空数组 PATCH 已验证可用（200）且真实落库（GET 穿透 DB 后确认 0 个残留），
      不触发带数据 PATCH 的服务端事务超时（503）；
    - 与 DELETE /cart 同理，避免每日 CI 反复跑导致 auto coupon 无限累积；
    - 注意：全量清空会同时删除该 post 的既有 coupon 配置（含测试基线），
      若 web 端对该 post 配置了真实运营 coupon 会被一并清掉。
    """
    try:
        try:
            token = _curator_signin()
        except Exception as exc:
            print(f"[tear-down] promotion sign-in failed: {exc}")
            return
        promo_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        patch = get_sync_client().patch(
            promo_path(),
            headers=promo_headers,
            json={"announcements": [], "promotions": [], "hideCouponBox": False},
            timeout=60,
        )
        print(f"[tear-down] PATCH {promo_path()} 清空 coupons -> {patch.status_code}")
    except Exception as exc:  # 清理失败不阻断测试结果
        print(f"[tear-down] promotion 清空失败: {exc}")


def pytest_sessionfinish(session, exitstatus):
    """测试结束后：tear-down 清理测试购物车 + 清空测试 coupons + 生成审计报告。"""
    try:
        # tear-down：DELETE /cart 清空测试购物车，
        # 避免每日 CI 跑测中 PUT /cart 加购导致 quantity 无限累加
        resp = get_sync_client().delete(f"{BASE_URL}/cart", headers=AUTH_HEADERS, timeout=15)
        print(f"\n[tear-down] DELETE {BASE_URL}/cart -> {resp.status_code}")
    except Exception as exc:  # 清理失败不阻断测试结果
        print(f"\n[tear-down] DELETE /cart 失败: {exc}")
    # tear-down：清空 promotion 测试 post 的 coupons，避免 auto coupon 累积
    _clear_promotions()
    try:
        report_path = _write_get_db_audit_report()
        print(f"\n[GET API DB 审计] 报告已生成: {report_path}")
    except Exception as exc:  # 报告生成失败不阻断测试
        print(f"\n[GET API DB 审计] 报告生成失败: {exc}")

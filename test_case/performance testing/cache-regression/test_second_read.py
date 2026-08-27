"""
KAT-11756 Task 6: 未验证接口显式补"连续读两次"用例。

背景：审计报告（get_api_db_audit_*.md）中，部分 GET 接口只被请求 1 次
（仅 1 个 2xx 响应），无二次读取样本，被标记为"未验证（仅1次请求）"——
无法证明预热后是否缓存命中。本模块为这些接口显式补"预热 → 二次读取"用例，
断言二次读取 DB=0（缓存命中），消除审计盲区。

覆盖接口（2026-08-21 / 2026-08-27 release 审计未验证项）：
1. GET /feature-flag/user/{userId}              （storefront 审计仅 1 次请求）
2. GET /feature-flag/user/{userId}/public       （storefront 审计仅 1 次请求）
3. GET admin /promotions?searchTerm=...         （admin 匹配 promotionId 时仅 1 次）
4. GET /posts/curator/{postId}/promotions       （storefront BE 仅注册 PATCH，
                                                 GET 路由 404 → @xfail BE 缺口）

特殊处理：
- admin 域（release.admin.katana-api.1m.app）整体未部署 X-DB-Query-Count 埋点
  （db=-1），无法做 DB=0 断言。本用例对 admin 接口仅断言 HTTP 200，并记录
  "admin 域无 DB 埋点"为 BE 埋点缺口（不判违规也不判通过）。
- /posts/curator/{postId}/promotions 当前 BE 仅注册 PATCH（全量替换），
  GET 路由返回 404 且无 X-DB-Query-Count 埋点。本用例对其连续读两次都
  断言 HTTP 200，@xfail(strict=False) 标注 BE 缺口；BE 补齐 GET 路由 +
  部署 DB 埋点后，自动升级为预热→二次读 DB=0 验证（XPASS 提示）。
- feature-flag-user 的 verify 用与 warmup 完全相同的 userId/URL，确保缓存 key
  一致，二次读取才能真正命中。

注：/order/checkout?fbAdParams[...]（报告未验证 #1/#2/#5）依赖购物车 cookie
session（无 cookie httpx 直发返回 400 "checkout not found"），由
test_checkout_journey.py:130 test_checkout_page_second_load_hits_cache 用
Playwright page.request.get() 走完整旅程+固定 URL 重放覆盖（@xfail BE
缓存 key 未对 fbAdParams 归一化），不在本文件复制。
"""
import pytest

from conftest import (
    _admin_auth_headers,
    assert_zero_db_queries_async,
    get_db_queries,
    KATANA_AUTH_HEADERS,
    BASE_URL,
)
from api_params import POST_DETAIL_PATH
from dynamic_ids import (
    curator_post_id,
    feature_flag_public_path,
    feature_flag_user_path,
    promo_path,
)


class TestSecondReadUnverified:
    """为审计"未验证"接口显式补连续读两次（预热 → 二次读取 DB=0）。"""

    @pytest.mark.asyncio
    async def test_feature_flag_user_second_read_hits_cache(self, http_client):
        """GET /feature-flag/user/{userId} 连续读两次：预热（可穿透）→ 二次读取 DB=0。

        feature-flag-user 是 per-user 资源：userId 固定（users/search 查 CONSUMER_EMAIL），
        预热后二次读取必须命中缓存，否则每个访客每次进店都直连 DB。
        """
        path = feature_flag_user_path()
        url = f"{BASE_URL}{path}"

        # 预热 — 允许穿透 DB
        resp_warm = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
        assert resp_warm.status_code == 200, (
            f"feature-flag-user warm-up failed: {resp_warm.status_code} {resp_warm.text[:200]}"
        )
        warmup_db = get_db_queries(resp_warm)

        # 验证 — 二次读取必须缓存命中（DB=0），吸收 BE 瞬态穿透
        resp_verify = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
        assert resp_verify.status_code == 200, (
            f"feature-flag-user verify failed: {resp_verify.status_code} {resp_verify.text[:200]}"
        )
        await assert_zero_db_queries_async(
            resp_verify, http_client, url, KATANA_AUTH_HEADERS,
            resource=path, attempt="verify", warmup_db_queries=warmup_db,
        )
        print(
            f"[second-read] GET {path}: warmup_db={warmup_db} -> verify_db="
            f"{get_db_queries(resp_verify)} ✓"
        )

    @pytest.mark.asyncio
    async def test_feature_flag_public_second_read_hits_cache(self, http_client):
        """GET /feature-flag/user/{userId}/public 连续读两次：二次读取 DB=0。"""
        path = feature_flag_public_path()
        url = f"{BASE_URL}{path}"

        resp_warm = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
        assert resp_warm.status_code == 200, (
            f"feature-flag-public warm-up failed: {resp_warm.status_code} {resp_warm.text[:200]}"
        )
        warmup_db = get_db_queries(resp_warm)

        # 验证 — 二次读取必须缓存命中（DB=0），吸收 BE 瞬态穿透
        resp_verify = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
        assert resp_verify.status_code == 200, (
            f"feature-flag-public verify failed: {resp_verify.status_code} {resp_verify.text[:200]}"
        )
        await assert_zero_db_queries_async(
            resp_verify, http_client, url, KATANA_AUTH_HEADERS,
            resource=path, attempt="verify", warmup_db_queries=warmup_db,
        )
        print(
            f"[second-read] GET {path}: warmup_db={warmup_db} -> verify_db="
            f"{get_db_queries(resp_verify)} ✓"
        )

    @pytest.mark.asyncio
    async def test_admin_promotions_second_read_status_ok(self, http_client):
        """admin GET /promotions 连续读两次：断言 HTTP 200 + 记录无 DB 埋点缺口。

        背景：admin 域未部署 X-DB-Query-Count 埋点（db=-1），无法做 DB=0 断言。
        本用例验证接口可用性（200），并打印缺口说明，供 BE 补齐埋点后接入 DB 断言。
        """
        from urllib.parse import quote

        from api_params import ADMIN_URL

        search = quote("automation test by linda")
        url = f"{ADMIN_URL}/promotions?searchTerm={search}&pageSize=1&pageNumber=1"
        headers = _admin_auth_headers()

        db_seq = []
        for attempt in ("warmup", "verify"):
            resp = await http_client.get(url, headers=headers)
            assert resp.status_code == 200, (
                f"admin GET /promotions {attempt} failed: {resp.status_code} {resp.text[:300]}\n"
                f"  Endpoint: GET {url}\n"
                f"  Action: admin promotions 查询接口不可用，无法验证 promotionId 匹配链路。"
            )
            db_seq.append(get_db_queries(resp))

        assert db_seq[0] == -1, (
            f"admin 域出现 X-DB-Query-Count 埋点（db={db_seq[0]}）！\n"
            f"  此前 admin 域整体无埋点（db=-1）；若现已部署，应改用 assert_zero_db_queries_async "
            f"做预热后二次读取 DB=0 断言，并移除本特殊处理。"
        )
        print(
            f"[second-read] admin GET /promotions: HTTP 200 OK；"
            f"db={db_seq}（admin 域无 X-DB-Query-Count 埋点，DB 断言留待 BE 补齐）\n"
            f"  BE 缺口：release.admin.katana-api.1m.app 未部署 DB 计数埋点，"
            f"admin 侧 GET 无法纳入 0-DB 违规判定。"
        )

    @pytest.mark.asyncio
    async def test_posts_consumer_detail_second_read_hits_cache(self, http_client):
        """GET /posts/consumer/detail 连续读两次：二次读取 DB=0。

        post detail 读接口是 storefront 主内容读取，冷启动 DB 高（实测 17），
        审计中该接口每次会话仅由 dynamic_ids.curator_post_id() 触发 1 次查询，
        无二次读取样本被标"未验证"。补预热 → 二次读取：预热后必须命中缓存，
        否则每个访客每次进店都直连 DB 打库（大流量缓存击穿隐患）。
        """
        url = f"{BASE_URL}{POST_DETAIL_PATH}"

        # 预热 — 允许穿透 DB
        resp_warm = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
        assert resp_warm.status_code == 200, (
            f"posts/consumer/detail warm-up failed: {resp_warm.status_code} {resp_warm.text[:200]}"
        )
        warmup_db = get_db_queries(resp_warm)

        # 验证 — 二次读取必须缓存命中（DB=0），吸收 BE 瞬态穿透
        resp_verify = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
        assert resp_verify.status_code == 200, (
            f"posts/consumer/detail verify failed: {resp_verify.status_code} {resp_verify.text[:200]}"
        )
        await assert_zero_db_queries_async(
            resp_verify, http_client, url, KATANA_AUTH_HEADERS,
            resource=POST_DETAIL_PATH, attempt="verify", warmup_db_queries=warmup_db,
        )
        print(
            f"[second-read] GET {POST_DETAIL_PATH}: warmup_db={warmup_db} -> verify_db="
            f"{get_db_queries(resp_verify)} ✓"
        )

    @pytest.mark.asyncio
    async def test_product_event_list_second_read_hits_cache(self, http_client):
        """GET /product-event/list（curator 登录态）连续读两次：预热 → 二次读取 DB=0。

        product-event/list 是审计报告"未验证"接口（dynamic_ids.event_id 仅 1 次样本）：
        按登录用户店铺维度过滤的真实读接口，预热后必须命中缓存，否则每次进店
        都直连 DB 查询事件列表。

        注意：list 按店铺维度过滤，guest 视角恒为空，必须用 curator sign-in token。
        """
        import os as _os

        if not _os.getenv("CURATOR_PASSWORD"):
            pytest.skip(
                "CURATOR_PASSWORD 未配置（CI 无 .env）：跳过 product-event/list 二次读验证"
            )

        from dynamic_ids import _curator_token

        path = "/product-event/list?keyword=&pageSize=50&pageNumber=1"
        url = f"{BASE_URL}{path}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_curator_token()}",
        }

        # 预热 — 允许穿透 DB
        resp_warm = await http_client.get(url, headers=headers)
        assert resp_warm.status_code == 200, (
            f"product-event/list warm-up failed: {resp_warm.status_code} {resp_warm.text[:200]}"
        )
        warmup_db = get_db_queries(resp_warm)

        # 验证 — 二次读取必须缓存命中（DB=0），吸收 BE 瞬态穿透
        resp_verify = await http_client.get(url, headers=headers)
        assert resp_verify.status_code == 200, (
            f"product-event/list verify failed: {resp_verify.status_code} {resp_verify.text[:200]}"
        )
        await assert_zero_db_queries_async(
            resp_verify, http_client, url, headers,
            resource=path, attempt="verify", warmup_db_queries=warmup_db,
        )
        print(
            f"[second-read] GET {path}: warmup_db={warmup_db} -> verify_db="
            f"{get_db_queries(resp_verify)} ✓"
        )

    @pytest.mark.xfail(
        reason=(
            "BE 缺口：GET /posts/curator/{postId}/promotions 未注册路由（2026-08-25 release "
            "仅 PATCH 全量替换），GET 返回 404 'Cannot GET .../promotions' 且无 "
            "X-DB-Query-Count 埋点，无法验证该读路径缓存命中；BE 实现 GET 路由并"
            "部署埋点后，本用例自动升级为预热→二次读 DB=0 验证（XPASS 提示）。"
        ),
        strict=False,
    )
    @pytest.mark.asyncio
    async def test_posts_curator_promotions_second_read_hits_cache(
        self, http_client, promo_auth_headers,
    ):
        """GET /posts/curator/{postId}/promotions 连续读两次：预热→二次读 DB=0。

        背景：promotion 配置的读接口（GET promotions）当前 BE 仅注册 PATCH
        （全量替换语义），GET 路由返回 404。审计报告标记为'未验证（仅 1 次请求）'
        —— 这"1 次"也是其他用例 PATCH 触发后的 404 副作用，并非真实读路径。

        本用例对 promo_path() 显式 GET 两次（warm-up + verify），断言 HTTP 200；
        当前 BE 给 404 → 用例按 xfail 处理；BE 修复后两次均应 200，且二次读
        DB=0（缓存命中），由 assert_zero_db_queries_async 验证。

        注意：与 test_promotion.py:410 test_promotion_get_direct_read_hit_cache
        功能等价；本文件作为'未验证接口二次读'的中央注册表，重复一份便于
        BE 修复时统一移除 xfail 与关注度聚合。
        """
        url = promo_path()

        # 预热 — 允许穿透 DB（实际当前 BE 在此步就返回 404，触发 xfail）
        resp_warm = await http_client.get(url, headers=promo_auth_headers)
        assert resp_warm.status_code == 200, (
            f"GET /posts/curator/{{postId}}/promotions warm-up failed: "
            f"HTTP {resp_warm.status_code}\n"
            f"  Endpoint: GET {url}\n"
            f"  Response body: {resp_warm.text[:300]}\n"
            f"  Action: BE 未注册 GET promotions 路由（当前仅 PATCH 全量替换），"
            f"无法验证该读路径缓存命中。"
        )
        warmup_db = get_db_queries(resp_warm)

        # 验证 — 二次读取必须缓存命中（DB=0），吸收 BE 瞬态穿透
        resp_verify = await http_client.get(url, headers=promo_auth_headers)
        assert resp_verify.status_code == 200, (
            f"GET /posts/curator/{{postId}}/promotions verify failed: "
            f"HTTP {resp_verify.status_code} {resp_verify.text[:200]}"
        )
        await assert_zero_db_queries_async(
            resp_verify, http_client, url, promo_auth_headers,
            resource=f"/posts/curator/{curator_post_id()}/promotions",
            attempt="verify", warmup_db_queries=warmup_db,
        )
        print(
            f"[second-read] GET /posts/curator/{{curator_post_id()}}/promotions: "
            f"warmup_db={warmup_db} -> verify_db={get_db_queries(resp_verify)} ✓"
        )

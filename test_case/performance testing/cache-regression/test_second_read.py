"""
KAT-11756 Task 6: 未验证接口显式补"连续读两次"用例。

背景：审计报告（get_api_db_audit_*.md）中，部分 GET 接口只被请求 1 次
（仅 1 个 2xx 响应），无二次读取样本，被标记为"未验证（仅1次请求）"——
无法证明预热后是否缓存命中。本模块为这些接口显式补"预热 → 二次读取"用例，
断言二次读取 DB=0（缓存命中），消除审计盲区。

覆盖接口（2026-08-21 release 审计未验证项）：
1. GET /feature-flag/user/{userId}              （storefront 审计仅 1 次请求）
2. GET /feature-flag/user/{userId}/public       （storefront 审计仅 1 次请求）
3. GET admin /promotions?searchTerm=...         （admin 匹配 promotionId 时仅 1 次）

特殊处理：
- admin 域（release.admin.katana-api.1m.app）整体未部署 X-DB-Query-Count 埋点
  （db=-1），无法做 DB=0 断言。本用例对 admin 接口仅断言 HTTP 200，并记录
  "admin 域无 DB 埋点"为 BE 埋点缺口（不判违规也不判通过）。
- feature-flag-user 的 verify 用与 warmup 完全相同的 userId/URL，确保缓存 key
  一致，二次读取才能真正命中。
"""
import pytest

from conftest import (
    _admin_auth_headers,
    assert_zero_db_queries,
    assert_zero_db_queries_async,
    get_db_queries,
    KATANA_AUTH_HEADERS,
    BASE_URL,
)
from api_params import POST_DETAIL_PATH
from dynamic_ids import (
    feature_flag_public_path,
    feature_flag_user_path,
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

        # 验证 — 二次读取必须缓存命中（DB=0）
        resp_verify = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
        assert resp_verify.status_code == 200, (
            f"feature-flag-user verify failed: {resp_verify.status_code} {resp_verify.text[:200]}"
        )
        assert_zero_db_queries(
            resp_verify, resource=path, attempt="verify", url=url,
            warmup_db_queries=warmup_db,
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

        resp_verify = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
        assert resp_verify.status_code == 200, (
            f"feature-flag-public verify failed: {resp_verify.status_code} {resp_verify.text[:200]}"
        )
        assert_zero_db_queries(
            resp_verify, resource=path, attempt="verify", url=url,
            warmup_db_queries=warmup_db,
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
            f"  此前 admin 域整体无埋点（db=-1）；若现已部署，应改用 assert_zero_db_queries "
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

        # 验证 — 二次读取必须缓存命中（DB=0）
        resp_verify = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
        assert resp_verify.status_code == 200, (
            f"posts/consumer/detail verify failed: {resp_verify.status_code} {resp_verify.text[:200]}"
        )
        assert_zero_db_queries(
            resp_verify, resource=POST_DETAIL_PATH, attempt="verify", url=url,
            warmup_db_queries=warmup_db,
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

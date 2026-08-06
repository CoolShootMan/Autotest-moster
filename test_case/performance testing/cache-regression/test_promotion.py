"""
KAT-11756 Task 3: Promotion Cache Validation.

验证 PATCH /posts/curator/{postId}/promotions 的连续调用完全命中缓存。

Promotion 有两个读路径：
- 创建 coupon 时：PATCH /posts/curator/{postId}/promotions（幂等）
- 结算时：POST /order/update-promotions（会修改订单状态）

本测试使用 PATCH 端点做缓存回归验证（无副作用，幂等）。
"""
import asyncio
import collections
import time

import pytest
from conftest import PROMO_BASE_URL, assert_zero_db_queries, get_db_queries


PROMO_PATH = "/posts/curator/21ff913d-b9bc-4f97-9246-f7438e2106f9/promotions"

PROMO_BODY = {
    "announcements": [],
    "promotions": [
        {
            "promotionId": "2523",
            "amountThresholdDiscounts": [
                {"amountThreshold": 100, "discountPercentage": 10}
            ],
            "applicableCode": "NMGsJeLy",
            "codeAliases": [],
            "title": "",
            "description": "",
            "autoApplied": False,
            "oneTimeUsePerCustomer": False,
            "isExtend": False,
            "startTime": "2026-07-23T03:42:03.102Z",
        }
    ],
    "hideCouponBox": False,
}


class TestPromotionCache:
    """Promotion 缓存回归检测。"""

    @pytest.mark.asyncio
    async def test_promotion_cold_start_header_sanity(self, http_client, promo_auth_headers):
        """Sanity: 确认 promotion PATCH 端点 header 存在（DB != -1）。

        header_integrity_check（session 级）已用全新 userId 验证 x-db-query-count
        真实反映 DB 查询次数，本函数仅做补充：确保 promotion 端点部署了 header。

        注意：此端点可能被前序测试预热（如 purchase_funnel 的 promotion_read_impact
        或 test_promotion_concurrent_reads 等），不硬断言 DB>0。若 DB=0 说明已预热，
        仅打印 WARNING 并跳过。
        """
        url = f"{PROMO_BASE_URL}{PROMO_PATH}"
        resp = await http_client.patch(url, headers=promo_auth_headers, json=PROMO_BODY)
        assert resp.status_code == 200
        db = get_db_queries(resp)
        assert db != -1, (
            f"X-DB-Query-Count header missing on promotion PATCH.\n"
            f"  Endpoint: PATCH {url}\n"
            f"  Action: Backend instrumentation not deployed for this endpoint."
        )
        if db == 0:
            import warnings
            warnings.warn(
                f"Promotion cold-start returned DB=0 — endpoint already warmed by prior tests. "
                f"Skipping cold-start sanity check. header_integrity_check already verified "
                f"the x-db-query-count header is trustworthy at session scope."
            )

    @pytest.mark.asyncio
    async def test_consecutive_reads_hit_cache(self, http_client, promo_auth_headers):
        """
        第一次 PATCH（预热，穿透 DB）后，第二次 PATCH 必须 0 DB 查询。

        注意：若 promoter token 在 warm-up 和 verify 之间过期，katana 会签发
        新 token，可能触发额外的 DB 查询（如 token 写入或相关权限校验），导致
        verify 阶段返回 DB>0。若看到此情况，请检查 promo_auth_headers fixture
        中 PROMO_EMAIL/PROMO_PASSWORD_HASH 的账号是否稳定。
        """
        url = f"{PROMO_BASE_URL}{PROMO_PATH}"

        # 预热 — 允许穿透 DB
        resp_warm = await http_client.patch(
            url, headers=promo_auth_headers, json=PROMO_BODY
        )
        assert resp_warm.status_code == 200, f"Warm-up failed: {resp_warm.status_code}"
        warmup_db = get_db_queries(resp_warm)

        # 验证 — 断言缓存命中（DB=0）
        resp_verify = await http_client.patch(
            url, headers=promo_auth_headers, json=PROMO_BODY
        )
        assert resp_verify.status_code == 200, f"Verify failed: {resp_verify.status_code}"
        assert_zero_db_queries(
            resp_verify, resource=PROMO_PATH, attempt="verify", url=url,
            warmup_db_queries=warmup_db,
        )

    @pytest.mark.asyncio
    async def test_promotion_concurrent_reads_hit_cache_after_warmup(
        self, http_client, promo_auth_headers
    ):
        """预热后并发 10 个 PATCH 请求，穿透数应 ≤ 1。"""
        url = f"{PROMO_BASE_URL}{PROMO_PATH}"

        # 预热
        resp_warm = await http_client.patch(
            url, headers=promo_auth_headers, json=PROMO_BODY
        )
        assert resp_warm.status_code == 200, f"Warm-up failed: {resp_warm.status_code}"
        warmup_db = get_db_queries(resp_warm)

        # 并发 10 个 PATCH
        async def _patch():
            return await http_client.patch(
                url, headers=promo_auth_headers, json=PROMO_BODY
            )

        t0 = time.monotonic()
        responses = await asyncio.gather(*[_patch() for _ in range(10)])
        t1 = time.monotonic()

        # 统计穿透数
        db_queries_list = [
            get_db_queries(r) for r in responses if r.status_code == 200
        ]
        penetration_count = sum(1 for q in db_queries_list if q > 0)

        # 按 DB 查询值分组汇总
        dist_counter = collections.Counter(db_queries_list)
        dist_summary = " | ".join(
            f"{q} queries × {cnt} requests"
            for q, cnt in sorted(dist_counter.items())
        )
        assert penetration_count <= 1, (
            f"Promotion 并发缓存击穿:\n"
            f"  Endpoint: PATCH {url}\n"
            f"  Warm-up DB queries: {warmup_db}\n"
            f"  Total requests: 10\n"
            f"  Penetrations: {penetration_count}/10\n"
            f"  DB query distribution: {dist_summary}\n"
            f"  Concurrent request timing: {t1 - t0:.2f}s\n"
            f"  Expected: ≤ 1, got {penetration_count}.\n"
            f"  Action: {penetration_count} concurrent PATCH requests bypassed cache.\n"
            f"  Check: 1) Is the cache lock/mutex properly implemented for promotion PATCH?\n"
            f"         2) Are concurrent warm-up requests serialized to avoid cache stampede?\n"
            f"         3) Does the promoter token remain valid across all 10 concurrent requests?"
        )

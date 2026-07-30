"""
KAT-11756 Task 3: Promotion Cache Validation.

验证 PATCH /posts/curator/{postId}/promotions 的连续调用完全命中缓存。

Promotion 有两个读路径：
- 创建 coupon 时：PATCH /posts/curator/{postId}/promotions（幂等）
- 结算时：POST /order/update-promotions（会修改订单状态）

本测试使用 PATCH 端点做缓存回归验证（无副作用，幂等）。
"""
import asyncio

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
        """Sanity: 确认 promotion PATCH 端点 header 有效（DB>0）。"""
        url = f"{PROMO_BASE_URL}{PROMO_PATH}"
        resp = await http_client.patch(url, headers=promo_auth_headers, json=PROMO_BODY)
        assert resp.status_code == 200
        db = get_db_queries(resp)
        assert db > 0, f"Promotion cold start 预期 DB>0, 实际 {db}"

    @pytest.mark.asyncio
    async def test_consecutive_reads_hit_cache(self, http_client, promo_auth_headers):
        """
        第一次 PATCH（预热，穿透 DB）后，第二次 PATCH 必须 0 DB 查询。
        """
        url = f"{PROMO_BASE_URL}{PROMO_PATH}"

        # 预热 — 允许穿透 DB
        resp_warm = await http_client.patch(
            url, headers=promo_auth_headers, json=PROMO_BODY
        )
        assert resp_warm.status_code == 200, f"Warm-up failed: {resp_warm.status_code}"

        # 验证 — 断言缓存命中（DB=0）
        resp_verify = await http_client.patch(
            url, headers=promo_auth_headers, json=PROMO_BODY
        )
        assert resp_verify.status_code == 200, f"Verify failed: {resp_verify.status_code}"
        assert_zero_db_queries(resp_verify, resource=PROMO_PATH, attempt="verify")

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

        # 并发 10 个 PATCH
        async def _patch():
            return await http_client.patch(
                url, headers=promo_auth_headers, json=PROMO_BODY
            )

        responses = await asyncio.gather(*[_patch() for _ in range(10)])

        # 统计穿透数
        penetrations = sum(
            1 for r in responses
            if r.status_code == 200 and get_db_queries(r) > 0
        )
        assert penetrations <= 1, (
            f"并发缓存击穿：预期穿透数 ≤ 1，实际 {penetrations}/10\n"
        )

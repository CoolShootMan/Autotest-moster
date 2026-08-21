"""
KAT-11756 Task: Storefront → Post Detail User Journey Cache Validation.

模拟消费者从 Storefront 点击 post 进入 Post Detail 的完整路径，
双层覆盖：katana 业务 API（httpx）+ Pear SSR 页面（Playwright）。

流程：
1. 预热 Pear SSR 页面 → 预热 storefront katana → 预热 post detail katana
2. 验证 post detail katana → 验证 storefront katana → 验证 Pear SSR 页面
"""
import pytest
from conftest import (
    assert_zero_db_queries,
    get_db_queries,
    KATANA_API,
    KATANA_AUTH_HEADERS,
)
from test_storefront import STOREFRONT_ENDPOINTS, USER_ID, PROMOTER_ID


# ---- 端点定义 ----
# Pear SSR 页面
PEAR_ENDPOINTS = [
    {"path": "/resident", "label": "storefront"},
    {"path": "/resident/post/11756", "label": "post-detail"},
]

# Post Detail 阶段 — 4 个 katana API
POST_DETAIL_ENDPOINTS = [
    {"path": "/posts/consumer/detail?vanityUrl=resident&urlAlias=11756", "label": "post-detail-main"},
    {"path": "/product-event/3c902839-4847-48a0-b6fe-fba03122053b/public-details",
     "label": "product-event"},
    {"path": "/cart", "label": "cart-post-detail"},
    {"path": f"/promoter-subscription/setting/{USER_ID}?settingType=SUBSCRIPTION",
     "label": "promoter-sub-post-detail"},
]


# ---- 测试类 ----
class TestUserJourneyCache:
    """Storefront → Post Detail 端到端（katana + SSR）缓存回归检测。"""

    @pytest.mark.asyncio
    async def test_full_user_journey_all_hit_cache(self, pear_context, http_client):
        """
        katana API（httpx）+ SSR（Playwright）全链路缓存回归检测。

        流程：
        1. 预热 Pear SSR 页面（Playwright）
        2. 预热 Storefront 的 7 个 katana API（httpx）
        3. 预热 Post Detail 的 4 个 katana API（httpx）
        4. 验证 Post Detail katana（模拟用户点击进入）
        5. 验证 Storefront katana（确认缓存未被污染）
        6. 验证 Pear SSR 页面（Playwright）
        """
        from conftest import navigate_pear_page

        failures = []

        # ==================== 预热阶段 ====================
        # Step 1: 预热 Pear SSR 页面（Playwright）
        for ep in PEAR_ENDPOINTS:
            count, status = await navigate_pear_page(pear_context, ep["path"])
            assert status == 200, (
                f"SSR warmup failed [{ep['label']}]: status={status}"
            )

        # Step 2: 预热 Storefront katana API
        for ep in STOREFRONT_ENDPOINTS:
            url = f"{KATANA_API}{ep['path']}"
            resp = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
            assert resp.status_code == 200, (
                f"Storefront warm-up failed [{ep['label']}]: status={resp.status_code}"
            )
            ep["warmup_db"] = get_db_queries(resp)

        # Step 3: 预热 Post Detail katana API
        for ep in POST_DETAIL_ENDPOINTS:
            url = f"{KATANA_API}{ep['path']}"
            resp = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
            assert resp.status_code == 200, (
                f"Post-detail warm-up failed [{ep['label']}]: status={resp.status_code}"
            )
            ep["warmup_db"] = get_db_queries(resp)

        # ==================== 验证阶段 ====================
        # Step 4: 先验证 Post Detail katana（模拟用户点击进入）
        for ep in POST_DETAIL_ENDPOINTS:
            url = f"{KATANA_API}{ep['path']}"
            resp = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
            assert resp.status_code == 200, (
                f"Post-detail verify failed [{ep['label']}]: status={resp.status_code}"
            )
            try:
                assert_zero_db_queries(
                    resp, resource=ep["path"], attempt="verify", url=url,
                    warmup_db_queries=ep.get("warmup_db"),
                )
            except AssertionError as exc:
                failures.append(f"[{ep['label']}] {exc}")

        # Step 5: 再验证 Storefront katana（确认缓存未被污染）
        for ep in STOREFRONT_ENDPOINTS:
            url = f"{KATANA_API}{ep['path']}"
            resp = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
            assert resp.status_code == 200, (
                f"Storefront verify failed [{ep['label']}]: status={resp.status_code}"
            )
            try:
                assert_zero_db_queries(
                    resp, resource=ep["path"], attempt="verify", url=url,
                    warmup_db_queries=ep.get("warmup_db"),
                )
            except AssertionError as exc:
                failures.append(f"[{ep['label']}] {exc}")

        # Step 6: 验证 Pear SSR 页面（Playwright）
        for ep in PEAR_ENDPOINTS:
            count, status = await navigate_pear_page(pear_context, ep["path"])
            assert status == 200, (
                f"SSR verify failed [{ep['label']}]: status={status}"
            )
            if count != 0:
                if count == -1:
                    failures.append(
                        f"SSR console capture failed!\n"
                        f"Resource: {ep['path']}  [{ep['label']}]\n"
                        f"  navigate_pear_page 返回 count=-1，console 未捕获到 x-db-query-count。\n"
                        f"  请确认 Pear SSR 页面（{ep['path']}）是否仍在 console.log 中输出 x-db-query-count 响应头。"
                    )
                else:
                    failures.append(
                        f"SSR cache regression detected!\n"
                        f"Resource: {ep['path']}\n"
                        f"Attempt: {ep['label']}-verify\n"
                        f"Expected DB queries: 0\n"
                        f"Actual DB queries:   {count}"
                    )

        # ==================== 汇总失败 ====================
        if failures:
            summary = (
                f"User journey cache regression — "
                f"{len(failures)} endpoint(s) leaked DB queries:\n\n"
                + "\n".join(failures)
            )
            pytest.fail(summary)

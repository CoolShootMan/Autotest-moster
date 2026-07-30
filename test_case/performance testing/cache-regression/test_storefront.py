"""
KAT-11756 Task 1: Storefront Cache Validation.

双层覆盖：
1. 底层 7 个 katana 业务 API（httpx，严格 DB=0 断言）
2. Pear SSR 页面 /resident（Playwright，console.log 抓取）
"""
import pytest
from conftest import (
    assert_zero_db_queries,
    KATANA_API,
    KATANA_AUTH_HEADERS,
)


USER_ID = "009eef19-723d-402f-8f14-c9ec3db08ba5"
PROMOTER_ID = "84a0de44-47e4-4a38-883e-d99ed194d7d7"

STOREFRONT_ENDPOINTS = [
    {"path": "/store-front/shop/resident?public=false", "label": "shop-config"},
    {"path": f"/feature-flag/user/{USER_ID}", "label": "feature-flag-user"},
    {"path": f"/feature-flag/user/{USER_ID}/public", "label": "feature-flag-public"},
    {"path": f"/feature-setting/consumer-public?scene=SCENE_GUEST_SHOP&promoterId={PROMOTER_ID}",
     "label": "feature-setting-public"},
    {"path": "/feature-setting/consumer-signup?lead=default", "label": "feature-setting-signup"},
    {"path": "/cart", "label": "cart-storefront"},
    {"path": f"/promoter-subscription/setting/{USER_ID}?settingType=SUBSCRIPTION",
     "label": "promoter-sub-storefront"},
]


@pytest.mark.asyncio
async def test_cold_start_header_sanity(http_client):
    """Sanity: 冷启动确认 header 有效（DB>0）且缓存生效（DB=0）。
    防止 header 永远返回 "0" 导致的假绿。"""
    from conftest import get_db_queries, assert_zero_db_queries

    STOREFRONT_API = f"{KATANA_API}/store-front/shop/resident?public=false"

    # Cold: 首次请求必须穿透 DB
    resp = await http_client.get(STOREFRONT_API)
    assert resp.status_code == 200
    db_cold = get_db_queries(resp)
    assert db_cold > 0, (
        f"Cold start 预期 DB>0, 实际 {db_cold}。"
        "x-db-query-count header 可能损坏或端点已被预热。"
    )

    # Warm: 二次请求必须命中缓存
    resp2 = await http_client.get(STOREFRONT_API)
    assert resp2.status_code == 200
    assert_zero_db_queries(resp2, context="冷启动后缓存验证")


class TestStorefrontCache:
    """Storefront 双层（katana API + SSR）缓存回归检测。"""

    @pytest.mark.asyncio
    async def test_storefront_katana_apis_hit_cache(self, http_client):
        """预热 storefront 7 个 katana API，验证全部 DB=0（严格断言）。"""
        failures = []

        # ---- 预热：全部 7 个端点 ----
        for ep in STOREFRONT_ENDPOINTS:
            url = f"{KATANA_API}{ep['path']}"
            resp = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
            assert resp.status_code == 200, (
                f"Warm-up failed [{ep['label']}]: status={resp.status_code}"
            )

        # ---- 验证：全部 7 个端点 DB=0 ----
        for ep in STOREFRONT_ENDPOINTS:
            url = f"{KATANA_API}{ep['path']}"
            resp = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
            assert resp.status_code == 200, (
                f"Verify failed [{ep['label']}]: status={resp.status_code}"
            )
            try:
                assert_zero_db_queries(resp, resource=ep["path"], attempt="verify")
            except AssertionError as exc:
                failures.append(str(exc))

        if failures:
            summary = (
                f"Storefront cache regression — "
                f"{len(failures)} endpoint(s) leaked DB queries:\n\n"
                + "\n".join(failures)
            )
            pytest.fail(summary)

    @pytest.mark.asyncio
    async def test_storefront_ssr_hit_cache(self, pear_context):
        """SSR 页面缓存回归 — 通过浏览器 console.log 读取 x-db-query-count"""
        from conftest import navigate_pear_page

        path = "/resident"

        # 预热：首次加载，触发缓存填充
        count1, status1 = await navigate_pear_page(pear_context, path)
        assert status1 == 200, f"SSR warmup failed: status={status1}"

        # 验证：二次加载，应命中缓存
        count2, status2 = await navigate_pear_page(pear_context, path)
        assert status2 == 200, f"SSR verify failed: status={status2}"
        assert count2 == 0, f"SSR cache regression: expected DB=0, got DB={count2}"

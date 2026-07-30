"""
KAT-11756 Task 2: Post Detail Cache Validation.

双层覆盖：
1. katana API /posts/consumer/detail（httpx，严格 DB=0 断言）
2. Pear SSR 页面 /resident/post/11756（Playwright，console.log 抓取）
"""
import pytest
from conftest import (
    assert_zero_db_queries,
    get_db_queries,
    KATANA_API,
    KATANA_AUTH_HEADERS,
)


# katana API 路径
POST_PATH = "/posts/consumer/detail?vanityUrl=resident&urlAlias=11756"
POST_B_PATH = "/posts/consumer/detail?vanityUrl=resident&urlAlias=ntxccrehh-charity-event"


class TestPostCache:
    """Post Detail 双层（katana API + SSR）缓存回归检测。"""

    @pytest.mark.asyncio
    async def test_post_cold_start_header_sanity(self, http_client):
        """Sanity: 冷启动确认 header 有效（DB>0），二次请求命中缓存（DB=0）。"""
        url = f"{KATANA_API}{POST_PATH}"

        # 冷启动：首次 GET 必须穿透 DB
        resp_cold = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
        assert resp_cold.status_code == 200, f"Cold start failed: {resp_cold.status_code}"
        db_cold = get_db_queries(resp_cold)
        assert db_cold > 0, (
            f"Post cold start 预期 DB>0, 实际 {db_cold}。"
            "x-db-query-count header 可能损坏或端点已被预热。"
        )

        # 二次请求：必须命中缓存
        resp_warm = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
        assert resp_warm.status_code == 200, f"Cold-verify failed: {resp_warm.status_code}"
        assert_zero_db_queries(resp_warm, resource=POST_PATH, attempt="cold-verify")

    @pytest.mark.asyncio
    async def test_katana_consecutive_reads_hit_cache(self, http_client):
        """
        katana API：第一次读取（预热）后，第二次读取必须 0 DB 查询（严格断言）。
        """
        url = f"{KATANA_API}{POST_PATH}"

        # 预热
        resp_warm = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
        assert resp_warm.status_code == 200, f"Warm-up failed: {resp_warm.status_code}"

        # 验证
        resp_verify = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
        assert resp_verify.status_code == 200, f"Verify failed: {resp_verify.status_code}"
        assert_zero_db_queries(resp_verify, resource=POST_PATH, attempt="verify")

    @pytest.mark.asyncio
    async def test_different_posts_cached_independently(self, http_client):
        """
        不同 post 各自独立缓存：预热 post A 和 post B 后，各自验证 DB=0，
        并确认 post A 缓存未被 post B 操作污染。
        """
        url_a = f"{KATANA_API}{POST_PATH}"
        url_b = f"{KATANA_API}{POST_B_PATH}"

        # 1. 预热 post A
        resp_a_warm = await http_client.get(url_a, headers=KATANA_AUTH_HEADERS)
        assert resp_a_warm.status_code == 200, f"Warm-up A failed: {resp_a_warm.status_code}"

        # 2. 验证 post A 缓存命中（DB=0）
        resp_a_verify = await http_client.get(url_a, headers=KATANA_AUTH_HEADERS)
        assert resp_a_verify.status_code == 200, f"Verify A failed: {resp_a_verify.status_code}"
        assert_zero_db_queries(resp_a_verify, resource=POST_PATH, attempt="post-A verify")

        # 3. 预热 post B
        resp_b_warm = await http_client.get(url_b, headers=KATANA_AUTH_HEADERS)
        assert resp_b_warm.status_code == 200, f"Warm-up B failed: {resp_b_warm.status_code}"

        # 4. 验证 post B 缓存命中（DB=0）
        resp_b_verify = await http_client.get(url_b, headers=KATANA_AUTH_HEADERS)
        assert resp_b_verify.status_code == 200, f"Verify B failed: {resp_b_verify.status_code}"
        assert_zero_db_queries(resp_b_verify, resource=POST_B_PATH, attempt="post-B verify")

        # 5. 再次读 post A — 确认仍然 DB=0（缓存未被 B 污染）
        resp_a_final = await http_client.get(url_a, headers=KATANA_AUTH_HEADERS)
        assert resp_a_final.status_code == 200, f"Final read A failed: {resp_a_final.status_code}"
        assert_zero_db_queries(resp_a_final, resource=POST_PATH, attempt="post-A final")

    @pytest.mark.asyncio
    async def test_auth_isolation_between_users(self, http_client, user_b_auth_headers):
        """
        验证不同用户共享同一缓存空间（GUEST 角色，缓存 key 不含 userId）。

        Step 1: User A 请求 → 预热缓存
        Step 2: User A 再次请求 → DB=0（缓存命中）
        Step 3: User B 请求 → DB=0（共享缓存命中）
        """
        from conftest import AUTH_HEADERS

        url = f"{KATANA_API}{POST_PATH}"

        # 1. User A 预热
        resp_a_warm = await http_client.get(url, headers=AUTH_HEADERS)
        assert resp_a_warm.status_code == 200, f"User A warm-up failed: {resp_a_warm.status_code}"

        # 2. User A 验证缓存命中（DB=0）
        resp_a_verify = await http_client.get(url, headers=AUTH_HEADERS)
        assert resp_a_verify.status_code == 200, f"User A verify failed: {resp_a_verify.status_code}"
        assert_zero_db_queries(resp_a_verify, resource=POST_PATH, attempt="user-A verify")

        # 3. User B 首次读取 — 预期 DB=0（共享缓存）
        resp_b = await http_client.get(url, headers=user_b_auth_headers)
        assert resp_b.status_code == 200, f"User B read failed: {resp_b.status_code}"
        assert_zero_db_queries(resp_b, resource=POST_PATH, attempt="user-B shared-cache")

    @pytest.mark.asyncio
    async def test_ssr_consecutive_reads_hit_cache(self, pear_context):
        """SSR Post Detail 连续两次读取 — 第二次应命中缓存"""
        from conftest import navigate_pear_page

        path = "/resident/post/11756"

        # 预热：首次加载，触发缓存填充
        count1, status1 = await navigate_pear_page(pear_context, path)
        assert status1 == 200, f"SSR warmup failed: status={status1}"

        # 验证：二次加载，应命中缓存
        count2, status2 = await navigate_pear_page(pear_context, path)
        assert status2 == 200, f"SSR verify failed: status={status2}"
        assert count2 == 0, f"SSR cache regression: expected DB=0, got DB={count2}"

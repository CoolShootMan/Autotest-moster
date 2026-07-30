"""
KAT-11756 扩展场景：Post Detail 并发读取缓存击穿检测（katana API）。

验证 post detail API 在并发场景下的缓存行为：
- 预热后并发读：绝大多数请求应命中缓存（DB=0）。
"""
import pytest
import asyncio
from conftest import (
    get_db_queries,
    KATANA_API,
    KATANA_AUTH_HEADERS,
)

CONCURRENT_COUNT = 10
POST_PATH = "/posts/consumer/detail?vanityUrl=resident&urlAlias=11756"


class TestPostConcurrentRead:
    """Post Detail 并发读取缓存击穿检测（katana API）。"""

    @pytest.mark.asyncio
    async def test_post_concurrent_reads_hit_cache_after_warmup(self, http_client):
        """预热后发起 10 个并发读取，至少 9 个请求必须 0 DB 查询。"""
        url = f"{KATANA_API}{POST_PATH}"

        # 预热
        resp_warm = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
        assert resp_warm.status_code == 200, f"Warm-up failed: {resp_warm.status_code}"

        # 并发读
        async def read_and_check(i: int):
            resp = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
            assert resp.status_code == 200, f"Concurrent read {i} failed: {resp.status_code}"
            db_queries = get_db_queries(resp)
            return i, db_queries

        tasks = [read_and_check(i) for i in range(CONCURRENT_COUNT)]
        results = await asyncio.gather(*tasks)

        penetrations = [(i, q) for i, q in results if q > 0]
        penetration_count = len(penetrations)

        assert penetration_count <= 1, (
            f"Post cache regression under concurrency!\n"
            f"Resource: {POST_PATH}\n"
            f"Concurrent requests: {CONCURRENT_COUNT}\n"
            f"Penetrations (index, db_queries): {penetrations}\n"
            f"Expected ≤ 1 requests to hit DB, but {penetration_count} bypassed cache."
        )

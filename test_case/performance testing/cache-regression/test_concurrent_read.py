"""
KAT-11756 扩展场景：并发读取缓存击穿检测（katana API）。

验证 katana storefront API 在并发场景下的缓存行为：
- 预热后并发读：绝大多数请求应命中缓存（DB=0）。
"""
import collections
import time
import pytest
import asyncio
from conftest import (
    get_db_queries,
    KATANA_API,
    KATANA_AUTH_HEADERS,
)

CONCURRENT_COUNT = 10  # 并发数
STORE_PATH = "/store-front/shop/resident?public=false"


class TestConcurrentRead:
    """并发读取缓存击穿检测（katana API）。"""

    @pytest.mark.asyncio
    async def test_concurrent_reads_hit_cache_after_warmup(self, http_client):
        """
        预热后发起 N 个并发读取，至少 N-1 个请求必须 0 DB 查询。
        """
        url = f"{KATANA_API}{STORE_PATH}"

        # 预热
        resp_warm = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
        assert resp_warm.status_code == 200, f"Warm-up failed: {resp_warm.status_code}"
        warmup_db = get_db_queries(resp_warm)

        # 并发读
        async def read_and_check(i: int):
            resp = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
            assert resp.status_code == 200, f"Concurrent read {i} failed: {resp.status_code}"
            db_queries = get_db_queries(resp)
            return i, db_queries

        tasks = [read_and_check(i) for i in range(CONCURRENT_COUNT)]
        t0 = time.monotonic()
        results = await asyncio.gather(*tasks)
        t1 = time.monotonic()

        # 统计 DB>0 的请求（允许最多 1 次穿透）
        penetrations = [(i, q) for i, q in results if q > 0]
        penetration_count = len(penetrations)

        # 按 DB 查询值分组汇总（如 "2 queries × 10 requests"）
        dist_counter = collections.Counter(q for _, q in results)
        dist_summary = " | ".join(
            f"{q} queries × {cnt} requests" for q, cnt in sorted(dist_counter.items())
        )

        assert penetration_count <= 1, (
            f"Cache regression under concurrency!\n"
            f"  Endpoint: GET {url}\n"
            f"  Warm-up DB queries: {warmup_db}\n"
            f"  Total requests: {CONCURRENT_COUNT}\n"
            f"  Penetrations: {penetration_count}/{CONCURRENT_COUNT}\n"
            f"  DB query distribution: {dist_summary}\n"
            f"  Concurrent request timing: {t1 - t0:.2f}s\n"
            f"  Expected: ≤ 1 request to hit DB, got {penetration_count}.\n"
            f"  Action: {penetration_count} concurrent requests bypassed cache.\n"
            f"  Check: 1) Is the cache lock/mutex properly implemented for this endpoint?\n"
            f"         2) Are concurrent warm-up requests serialized to avoid cache stampede?\n"
            f"         3) Is the cache populate atomic (first writer wins, rest read from cache)?"
        )

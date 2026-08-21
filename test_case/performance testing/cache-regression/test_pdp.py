"""
KAT-11756 缺口1：PDP 商品页连续读缓存验证（Pear SSR /resident/p/{...}）。

PDP 页无独立 promotion 计算接口（计算发生在 cart/checkout 阶段），
但页面 SSR 本身必须缓存：首次加载（预热穿透 DB）后再次加载必须命中
缓存（x-db-query-count=0），防止每次进店都直连 DB。

页面 URL 由 api_params.PDP_url 提供（缺省回退 PEAR_URL/resident/p/jjkbor）。
"""
import pytest
from urllib.parse import urlparse

from api_params import PDP_URL
from conftest import navigate_pear_page

PDP_PATH = urlparse(PDP_URL).path


class TestPdpCache:
    """PDP 页面缓存回归检测（缺口1 覆盖）。"""

    @pytest.mark.asyncio
    async def test_pdp_ssr_second_load_hits_cache(self, pear_context):
        """PDP 首次加载（预热）后，二次加载必须 0 DB 查询。"""
        # 预热：首次加载，触发缓存填充
        count1, status1 = await navigate_pear_page(pear_context, PDP_PATH)
        assert status1 == 200, f"PDP warmup failed: status={status1}"

        # 验证：二次加载，应命中缓存
        count2, status2 = await navigate_pear_page(pear_context, PDP_PATH)
        assert status2 == 200, f"PDP verify failed: status={status2}"
        if count2 == -1:
            pytest.fail(
                f"PDP SSR console capture failed for {PDP_URL}.\n"
                f"  Check: 1) PDP SSR page logs x-db-query-count to console,\n"
                f"         2) console msg.args[5] is response headers dict."
            )
        assert count2 == 0, (
            f"PDP cache regression detected!\n"
            f"  Endpoint: GET {PDP_URL}\n"
            f"  Phase: verify (2nd page load after warm-up)\n"
            f"  Expected: x-db-query-count = 0\n"
            f"  Actual:   x-db-query-count = {count2}\n"
            f"  Action: PDP SSR page leaked {count2} DB queries on a supposed cache hit."
        )

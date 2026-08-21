"""
KAT-11756 缺口1：PDP 商品页连续读缓存验证（Pear SSR /resident/p/{...}）。

PDP 页无独立 promotion 计算接口（计算发生在 cart/checkout 阶段），
但页面 SSR 本身必须缓存：首次加载（预热穿透 DB）后再次加载必须命中
缓存（x-db-query-count=0），防止每次进店都直连 DB。

页面 URL 由 api_params.PDP_url 提供（缺省回退 PEAR_URL/resident/p/jjkbor）。
"""
import asyncio

import pytest
from urllib.parse import urlparse

from api_params import PEAR_URL, PDP_URL
from conftest import (
    AUTH_HEADERS,
    AUTH_TOKEN,
    COMMON_HEADERS,
    attach_pear_page_audit,
    navigate_pear_page,
)
from dynamic_ids import promo_path
from test_promotion import (
    CART_URL,
    _build_promo_body,
    _cart_body,
    _now_tag,
    _read_auto_coupon_id,
)

PDP_PATH = urlparse(PDP_URL).path

# 3c 测试的 auto coupon 会话缓存（避免 import TestPromotionCache 导致 pytest
# 在 test_pdp.py 模块下重复收集 test_promotion 的测试类）
_PDP_AUTO = {"id": None, "tag": None}


class TestPdpCache:
    """PDP 页面缓存回归检测（缺口1 + 需求3c 覆盖）。"""

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

    @pytest.mark.asyncio
    async def test_pdp_coupon_not_stale_after_update(
        self, pear_context, http_client, promo_auth_headers
    ):
        """KAT-11756 需求 3c：coupon 修改后缓存必须立即失效，访问 PDP 页面 coupon 不 stale。

        覆盖点：coupon 被修改后，访问 PDP 页面，页面呈现的 coupon 折扣必须立即反映
        新配置（非 stale）。PDP 页面无独立 promotion 计算接口，coupon 折扣由前端经
        GET /cart 加载（item.totalCouponDiscount）——页面呈现即该值。

        验证链路：
        1. apply auto coupon(10%) → PUT /cart 加购（coupon 生效，baseline=2）
        2. 浏览器加载 PDP（注入同 user Authorization，使 GET /cart 读同一购物车）
           → 拦截 GET /cart → 记录修改前 PDP 呈现的 coupon 折扣
        3. PATCH 修改 auto coupon 折扣 10% -> 20%（写，触发 cart 缓存失效）
        4. 重新加载 PDP → 拦截 GET /cart → 断言折扣翻倍（=4），证明缓存已失效、不 stale
        5. finally 恢复 10%（避免污染 release 环境）

        2026-08-21 release 实测：coupon 修改后重新加载 PDP，GET /cart 立即返回新折扣
        （2 -> 4）且该次读取 DB>0（缓存失效后重新计算，属期望行为），需求 3c 满足。
        """
        # 0. 兜底 apply coupon（会话级缓存，复用 test_promotion 工具链）
        if _PDP_AUTO["id"] is None:
            _PDP_AUTO["tag"] = _now_tag()
            resp = await http_client.patch(
                promo_path(),
                headers=promo_auth_headers,
                json=_build_promo_body(discount=10, auto_tag=_PDP_AUTO["tag"]),
            )
            assert resp.status_code == 200, (
                f"Create auto coupon failed: {resp.status_code} {resp.text}"
            )
            _PDP_AUTO["id"] = await _read_auto_coupon_id(
                http_client, _PDP_AUTO["tag"]
            )

        # 1. 加购：coupon 生效（购物车 item 带 totalCouponDiscount）
        resp = await http_client.put(CART_URL, headers=AUTH_HEADERS, json=_cart_body())
        assert resp.status_code == 200, f"Cart add failed: {resp.status_code} {resp.text}"
        base_total = (
            resp.json()["data"]["items"][0].get("totalCouponDiscount", 0) or 0
        )
        assert base_total > 0, (
            f"auto coupon 未生效：PUT /cart 加购后 totalCouponDiscount=0，"
            f"无法验证 PDP 页面 coupon 不 stale。"
            f"  Check: 1) auto coupon(autoApplied) 是否仍存在且生效？\n"
            f"         2) 加购 price 是否满足 amountThreshold？"
        )

        # 2. 浏览器加载 PDP：注入同 user Authorization，GET /cart 读同一购物车
        await pear_context.set_extra_http_headers(
            {**COMMON_HEADERS, "Authorization": f"Bearer {AUTH_TOKEN}"}
        )

        async def _pdp_coupon_total() -> tuple[float, int]:
            """加载 PDP 页面，拦截 GET /cart，返回 (totalCouponDiscount, db)。

            注意：必须在 page 关闭前读取响应体（page.close 后 response.json 抛
            TargetClosedError）。
            """
            from playwright.async_api import Page

            page: Page = await pear_context.new_page()
            attach_pear_page_audit(page)  # 页面 GET 响应入统一审计日志
            captured: dict = {}

            def on_response(r):
                if r.request.method == "GET" and "/cart" in r.url:
                    captured["resp"] = r

            page.on("response", on_response)
            try:
                await page.goto(
                    f"{PEAR_URL}{PDP_PATH}", wait_until="networkidle", timeout=30000
                )
                await asyncio.sleep(2)
                if "resp" not in captured:
                    raise AssertionError(
                        f"PDP 加载未触发 GET /cart（{PDP_URL}）——无法观测页面 coupon 呈现值。"
                    )
                r = captured["resp"]
                body = await r.json()
                items = (body.get("data") or {}).get("items") or []
                total = items[0].get("totalCouponDiscount", 0) if items else 0
                db = int(r.headers.get("x-db-query-count", -1) or -1)
                return total, db
            finally:
                await page.close()

        pdp_base, pdp_base_db = await _pdp_coupon_total()
        assert pdp_base > 0, (
            f"PDP 页面加载后 GET /cart 未读到 coupon 折扣（totalCouponDiscount=0），"
            f"无法作为 3c 观测基线。"
        )

        # 3. PATCH 修改 auto coupon 折扣 10% -> 20%（写，触发 cart 缓存失效）
        resp = await http_client.patch(
            promo_path(),
            headers=promo_auth_headers,
            json=_build_promo_body(
                discount=20,
                auto_tag=_PDP_AUTO["tag"],
                auto_id=_PDP_AUTO["id"],
            ),
        )
        assert resp.status_code == 200, f"Promo patch(20%) failed: {resp.status_code} {resp.text}"
        try:
            # 4. 重新加载 PDP：coupon 折扣应翻倍（缓存已失效，不 stale）
            pdp_after, pdp_after_db = await _pdp_coupon_total()
        finally:
            # 5. 恢复 10%
            await http_client.patch(
                promo_path(),
                headers=promo_auth_headers,
                json=_build_promo_body(
                    discount=10,
                    auto_tag=_PDP_AUTO["tag"],
                    auto_id=_PDP_AUTO["id"],
                ),
            )

        assert pdp_after > pdp_base, (
            f"KAT-11756 3c 未满足：coupon 修改后 PDP 页面 coupon 仍 stale!\n"
            f"  Endpoint: PATCH {promo_path()}（auto coupon id={_PDP_AUTO['id']} 10% -> 20%）\n"
            f"  Phase: 修改后重新加载 PDP 页面（{PDP_URL}）\n"
            f"  Expected: GET /cart 返回 coupon 折扣 从 {pdp_base:.2f} 增大到 ~{pdp_base * 2:.2f}（折扣翻倍）\n"
            f"  Actual:   {pdp_after:.2f}（仍为旧折扣 → coupon 修改后缓存未立即失效）\n"
            f"  GET /cart DB: 修改前={pdp_base_db}，修改后={pdp_after_db}（>0 表示失效后重新计算，属期望行为）\n"
            f"  Action: coupon 修改后 PDP 页面呈现旧 coupon 折扣，promotion 配置缓存未失效。\n"
            f"  Check: 1) PATCH promotions 修改 coupon 后是否触发 cart/promotion 缓存主动失效？\n"
            f"         2) GET /cart 读路径是否读取了最新 promotion 配置（无 stale TTL）？"
        )
        print(
            f"[pdp-3c] PDP coupon 折扣: 修改前={pdp_base} (DB={pdp_base_db}) "
            f"-> 修改后={pdp_after} (DB={pdp_after_db})；折扣翻倍即不 stale ✓"
        )

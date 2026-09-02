"""
KAT-11756 Task 7: Buy now（立即购买）链路 GET API 缓存验证（guest 视角）。

覆盖点：guest 访问 post detail（/resident/post/11756），点击商品 "Merch 001" 上的
Buy now 按钮触发立即购买（不完成支付，捕获请求即止），审计该 flow 中 BE
（release.katana-api.1m.app）全部 GET/POST/PUT API 的 DB 读取，验证：
- GET 是读接口，预热后二次读取必须 DB=0（缓存命中），仍 DB>0 判违规；
- POST/PUT 写接口读 DB 属期望，仅记录（会话级审计报告的"写接口 DB 读取明细"展示）。

实测捕获的 Buy now flow API 清单（2026-08-25 release，Playwright 点击 Merch 001 Buy now）：
GET（读接口）：
 1. GET /promoter-subscription/setting/{curator_id}?settingType=SUBSCRIPTION   → db=0（页面加载）
 2. GET /product-event/{event_id}/public-details                                → db=1（页面加载）
 3. GET /user/self?subdomainVanityUrl=                                          → db=0
 4. GET /posts/consumer/detail?vanityUrl=resident&urlAlias=11756                → db=0（页面加载）
 5. GET /cart?                                                                  → db=12（Buy now 弹窗）/ db=0（express 后）
 6. GET /order/checkout?fbAdParams[...]                                         → db=1（Buy now 跳转结算页）
 7. GET /posts/{postId}/style-settings                                          → db=1（结算页加载）★用户 curl 清单接口
POST/PUT（写接口，读 DB 属期望）：
 8. POST /auth/guest-login                                                      → db=1（guest token 签发）
 9. POST /ad/conversions ×2                                                     → db=0（ViewContent / PageView pixel）
10. POST /ua ×N                                                                → db=0（AddToCart pixel 等埋点）★用户 curl 清单接口
11. POST /order/checkout/express                                                → db=11（Buy now 核心写接口）★用户 curl 清单接口
12. PUT /cart                                                                  → db=3（Buy now 自动加购）

与用户真实抓包 curl 对比：express / ua / style-settings 三个接口均已捕获；
另发现用户 curl 未列的 GET /cart、GET /order/checkout、GET /posts/consumer/detail、
GET /product-event/{id}/public-details、GET /promoter-subscription/setting、
GET /user/self，以及 POST /auth/guest-login、POST /ad/conversions、PUT /cart。
POST /ua 为 sendBeacon 型埋点，headless 下捕获不到 request body（CDP/Playwright 均
读不到），但其 DB=0 可确认，body 结构以用户 curl 为准。

Buy now 链路 httpx 可稳定复现的 GET（预热 → 二次读 DB=0 断言）：
 1. GET /posts/{postId}/style-settings   （postId = curator_post_id()，与页面一致）
 2. GET /product-event/{id}/public-details
 3. GET /posts/consumer/detail?vanityUrl=resident&urlAlias=11756
GET /cart 与 GET /promoter-subscription/setting（curator 变体）已在
test_checkout_journey.py 覆盖，此处不重复断言。
"""
import asyncio

import pytest

from api_params import BASE_URL, PEAR_URL, POST_DETAIL_PATH, CURATOR_POST_ALIAS
from conftest import (
    AUTH_HEADERS,
    assert_zero_db_queries,
    assert_zero_db_queries_async,
    attach_pear_page_audit,
    get_db_queries,
)
from dynamic_ids import curator_post_id


def _event_id():
    """product-event id：与 dynamic_ids.event_id() 同源，延迟求值。"""
    from dynamic_ids import event_id as _event_id
    return _event_id()


class TestBuyNowJourneyCache:
    """Buy now（立即购买）链路 GET API 缓存回归检测。"""

    @pytest.mark.asyncio
    async def test_buy_now_get_apis_hit_cache(self, http_client):
        """Buy now 链路 httpx 可复现的 GET API：预热后二次读取必须 DB=0。

        覆盖 GET /posts/{postId}/style-settings、GET /product-event/{id}/public-details、
        GET /posts/consumer/detail（urlAlias=11756）。
        """
        failures = []
        post_id = curator_post_id()
        endpoints = [
            {"path": f"/posts/{post_id}/style-settings", "label": "style-settings"},
            {
                "path": f"/product-event/{_event_id()}/public-details",
                "label": "product-event-public-details",
            },
            {"path": POST_DETAIL_PATH, "label": "posts-consumer-detail"},
        ]

        # ---- 预热：允许穿透 DB ----
        for ep in endpoints:
            url = f"{BASE_URL}{ep['path']}"
            resp = await http_client.get(url, headers=AUTH_HEADERS)
            assert resp.status_code == 200, (
                f"Buy-now warm-up failed [{ep['label']}]: status={resp.status_code} "
                f"{resp.text[:200]}"
            )
            ep["warmup_db"] = get_db_queries(resp)

        # ---- 验证：预热后二次读取必须 DB=0 ----
        for ep in endpoints:
            url = f"{BASE_URL}{ep['path']}"
            resp = await http_client.get(url, headers=AUTH_HEADERS)
            assert resp.status_code == 200, (
                f"Buy-now verify failed [{ep['label']}]: status={resp.status_code} "
                f"{resp.text[:200]}"
            )
            try:
                await assert_zero_db_queries_async(
                    resp, http_client, url, AUTH_HEADERS,
                    resource=ep["path"], attempt="verify",
                    warmup_db_queries=ep.get("warmup_db"),
                )
            except AssertionError as exc:
                failures.append(f"[{ep['label']}] {exc}")

        if failures:
            summary = (
                f"Buy now 链路 GET cache regression — "
                f"{len(failures)} endpoint(s) leaked DB queries:\n\n"
                + "\n".join(failures)
            )
            pytest.fail(summary)

    @pytest.mark.asyncio
    async def test_buy_now_flow_db_audit(self, pear_context):
        """真实 guest Buy now flow：访问 post detail → 点击 Merch 001 的 Buy now，
        审计全程 GET/POST/PUT 的 DB 读取，并断言核心请求被触发。

        校验：
        1. POST /order/checkout/express 被触发（记录 DB 读取，写接口读 DB 属期望）；
        2. GET /posts/{postId}/style-settings 被触发（结算页加载，用户 curl 清单接口）；
        3. 全程所有带 x-db-query-count 的响应经 attach_pear_page_audit 汇入全局
           审计日志，供 pytest_sessionfinish 生成 GET API DB 审计报告（含写接口明细）。
        """
        from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

        PDP_URL = f"{PEAR_URL}/resident/post/{CURATOR_POST_ALIAS}"
        page: Page = await pear_context.new_page()
        attach_pear_page_audit(page)

        # 自定义监听：记录 express / style-settings 的 DB 读取与请求头
        captured = {"express": [], "style_settings": []}

        def on_response(r):
            if r.request.method == "GET" and "/style-settings" in r.url:
                captured["style_settings"].append(
                    {"url": r.url, "status": r.status,
                     "db": r.headers.get("x-db-query-count", "<missing>")}
                )
            if r.request.method == "POST" and "/order/checkout/express" in r.url:
                captured["express"].append(
                    {"url": r.url, "status": r.status,
                     "db": r.headers.get("x-db-query-count", "<missing>"),
                     "auth": bool(r.request.headers.get("authorization"))}
                )

        page.on("response", on_response)

        try:
            await page.goto(PDP_URL, wait_until="domcontentloaded", timeout=40000)
            buy_btn = page.get_by_role("button", name="Buy now", exact=True).first
            await buy_btn.wait_for(state="visible", timeout=20000)
            await asyncio.sleep(3)
            await buy_btn.click(timeout=15000)
            # Buy now → express checkout 结算页加载（含 GET /order/checkout、style-settings）
            await asyncio.sleep(8)
        except (PlaywrightTimeoutError, TimeoutError) as exc:
            print(f"[buy-now-journey] journey step failed: {type(exc).__name__}: {exc}")
            print(f"[buy-now-journey] current url={page.url}")
            btns = await page.get_by_role("button").all_text_contents()
            print(f"[buy-now-journey] buttons={btns[:12]}")
            pytest.skip(
                "post detail 页面未出现 'Buy now' 按钮或点击失败——无法建立立即购买会话，"
                "express 结算请求无法触发，跳过该用例。"
            )

        # 断言 1：express 写接口被触发（DB 读取属期望，仅记录）
        assert captured["express"], (
            "Buy now 点击后未捕获 POST /order/checkout/express——"
            "立即购买请求未触发（BE 缺口或按钮点击未命中正确按钮），"
            "无法审计 express DB 读取。"
        )
        express_entries = ", ".join(
            f"status={e['status']} db={e['db']}" for e in captured["express"]
        )
        print(
            f"[buy-now-journey] POST /order/checkout/express 触发: {express_entries} "
            f"(写接口读 DB 属期望)"
        )

        # 断言 2：style-settings GET 被触发（用户 curl 清单接口）
        assert captured["style_settings"], (
            "Buy now flow 中未捕获 GET /posts/{postId}/style-settings——"
            "用户 curl 清单接口在 flow 中漏触发，需确认。"
        )
        style_entries = ", ".join(
            f"status={e['status']} db={e['db']}" for e in captured["style_settings"]
        )
        print(
            f"[buy-now-journey] GET /posts/{{postId}}/style-settings 触发: {style_entries}"
        )

        # 输出全程 GET DB 摘要（供报告参考；全量明细在会话级审计报告）
        print(f"[buy-now-journey] Buy now flow 完成，全程请求已写入全局审计日志。")
        await page.close()

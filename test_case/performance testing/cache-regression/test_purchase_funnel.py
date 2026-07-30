"""
KAT-11756 Task 4: 全链路漏斗缓存验证。

验证读流量增加时 DB 查询量跟随写入（订单）而非读取。

场景 A：纯读冲击 — 高读阶段 DB 查询量不应随 QPS 线性增长
场景 B：纯写冲击（对照组）— 高写阶段 DB 查询量应显著高于低写阶段

依赖后端在每个 API 响应的 Header 中注入 X-DB-Query-Count。
"""
import asyncio
import time
import uuid
import pytest
import httpx
from conftest import get_db_queries, AUTH_HEADERS, KATANA_API, KATANA_AUTH_HEADERS


# ---- 模块级常量 ----
READ_TARGET = f"{KATANA_API}/store-front/shop/resident?public=false"
POST_READ_TARGET = f"{KATANA_API}/posts/consumer/detail?vanityUrl=resident&urlAlias=11756"
PROMO_READ_TARGET = f"{KATANA_API}/posts/curator/21ff913d-b9bc-4f97-9246-f7438e2106f9/promotions"
CHECKOUT_URL = "https://release.katana-api.1m.app/order/checkout"
ORDER_URL = "https://release.katana-api.1m.app/order"

LOW_QPS = 2
HIGH_QPS = 10
DURATION_SEC = 10


# ---- 并发请求工具 ----
async def _send_read(client: httpx.AsyncClient, url: str, headers: dict) -> int:
    """单次读请求，返回本次 DB 查询次数。"""
    resp = await client.get(url, headers=headers)
    resp.raise_for_status()
    return get_db_queries(resp)


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


async def _send_promo_read(client: httpx.AsyncClient, headers: dict) -> int:
    """单次 promotion 读请求（PATCH，幂等），返回本次 DB 查询次数。"""
    resp = await client.patch(PROMO_READ_TARGET, headers=headers, json=PROMO_BODY)
    resp.raise_for_status()
    return get_db_queries(resp)


async def _send_checkout(client: httpx.AsyncClient) -> int:
    """Step 1：checkout，返回 DB 查询次数。"""
    resp = await client.post(
        CHECKOUT_URL, headers=AUTH_HEADERS, json={"subdomainVanityUrl": ""}
    )
    resp.raise_for_status()
    return get_db_queries(resp)


async def _send_order(client: httpx.AsyncClient) -> int:
    """Step 2：下单，每单替换 eventID 为新 UUID。"""
    body = {
        "inviterCampaign": {},
        "id": "1b603372-da0c-4130-87cc-ed0397512875",
        "contact": {
            "firstName": "linda",
            "lastName": "4650",
            "phoneNumber": "+12527130222",
            "email": "linda.zhou.ext@1m.app",
        },
        "fbAdParams": {
            "eventID": str(uuid.uuid4()),
            "pixelId": ["268933192948110"],
            "fbBrowserId": "fb.1.1784774413629.797980804257619138",
            "externalId": "009eef19-723d-402f-8f14-c9ec3db08ba5",
            "eventSourceUrl": (
                "https://release.pear.us/checkout"
                "?postId=21ff913d-b9bc-4f97-9246-f7438e2106f9"
            ),
        },
    }
    resp = await client.post(ORDER_URL, headers=AUTH_HEADERS, json=body)
    resp.raise_for_status()
    return get_db_queries(resp)


async def _run_phase(worker_coro, qps: int, duration: int) -> int:
    """
    按目标 QPS 持续 duration 秒执行 worker_coro，汇总所有请求的 X-DB-Query-Count。

    worker_coro: async callable(client) -> int  （返回单次 DB 查询次数）。
    返回：本阶段所有请求的 DB 查询总次数。
    """
    interval = 1.0 / qps
    async with httpx.AsyncClient(timeout=30) as client:
        tasks = []
        start = time.monotonic()
        while time.monotonic() - start < duration:
            task = asyncio.create_task(worker_coro(client))
            tasks.append(task)
            await asyncio.sleep(interval)
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            total = 0
            for r in results:
                if isinstance(r, Exception):
                    continue
                if r and r > 0:
                    total += r
            return max(1, total)
        return 1


# ---- 场景 A：纯读冲击 ----

@pytest.mark.asyncio
async def test_read_impact_does_not_scale_with_qps():
    """场景 A：高读阶段 DB 查询总量不应随 QPS 线性增长。"""
    # 预热：先发一次读请求填充缓存，避免低读阶段前几次穿透 DB 污染 low_total
    async with httpx.AsyncClient(timeout=30) as client:
        await _send_read(client, READ_TARGET, KATANA_AUTH_HEADERS)

    low_total = await _run_phase(
        lambda c: _send_read(c, READ_TARGET, KATANA_AUTH_HEADERS), LOW_QPS, DURATION_SEC
    )
    high_total = await _run_phase(
        lambda c: _send_read(c, READ_TARGET, KATANA_AUTH_HEADERS), HIGH_QPS, DURATION_SEC
    )

    ratio = high_total / low_total if low_total else float("inf")
    assert ratio <= 1.5, (
        f"DB 查询量随读 QPS 异常增长:\n"
        f"  低读({LOW_QPS} QPS) DB 查询总量={low_total}\n"
        f"  高读({HIGH_QPS} QPS) DB 查询总量={high_total}\n"
        f"  比率={ratio:.2f} > 1.5"
    )


# ---- 场景 A-2：Post Detail 读冲击 ----

@pytest.mark.asyncio
async def test_post_read_impact_does_not_scale_with_qps():
    """Post Detail 高读阶段 DB 查询总量不应随 QPS 线性增长。"""
    # 预热
    async with httpx.AsyncClient(timeout=30) as client:
        await _send_read(client, POST_READ_TARGET, KATANA_AUTH_HEADERS)

    low_total = await _run_phase(
        lambda c: _send_read(c, POST_READ_TARGET, KATANA_AUTH_HEADERS),
        LOW_QPS, DURATION_SEC,
    )
    high_total = await _run_phase(
        lambda c: _send_read(c, POST_READ_TARGET, KATANA_AUTH_HEADERS),
        HIGH_QPS, DURATION_SEC,
    )

    ratio = high_total / low_total if low_total else float("inf")
    assert ratio <= 1.5, (
        f"Post DB 查询量随读 QPS 异常增长:\n"
        f"  低读({LOW_QPS} QPS) DB 查询总量={low_total}\n"
        f"  高读({HIGH_QPS} QPS) DB 查询总量={high_total}\n"
        f"  比率={ratio:.2f} > 1.5"
    )


# ---- 场景 A-3：Promotion 读冲击 ----

@pytest.mark.asyncio
async def test_promotion_read_impact_does_not_scale_with_qps(promo_auth_headers):
    """Promotion 高读阶段 DB 查询总量不应随 QPS 线性增长。"""
    # 预热
    async with httpx.AsyncClient(timeout=30) as client:
        await _send_promo_read(client, promo_auth_headers)

    low_total = await _run_phase(
        lambda c: _send_promo_read(c, promo_auth_headers),
        LOW_QPS, DURATION_SEC,
    )
    high_total = await _run_phase(
        lambda c: _send_promo_read(c, promo_auth_headers),
        HIGH_QPS, DURATION_SEC,
    )

    ratio = high_total / low_total if low_total else float("inf")
    assert ratio <= 1.5, (
        f"Promotion DB 查询量随读 QPS 异常增长:\n"
        f"  低读({LOW_QPS} QPS) DB 查询总量={low_total}\n"
        f"  高读({HIGH_QPS} QPS) DB 查询总量={high_total}\n"
        f"  比率={ratio:.2f} > 1.5"
    )


# ---- 场景 B：纯写冲击（对照组） ----

async def _checkout_and_order(client: httpx.AsyncClient) -> int:
    """一次完整下单（checkout + order），返回总 DB 查询次数。"""
    c = await _send_checkout(client)
    o = await _send_order(client)
    return (c if c > 0 else 0) + (o if o > 0 else 0)


@pytest.mark.asyncio
async def test_write_impact_scales_with_qps():
    """场景 B：高写阶段 DB 查询总量应约为低写阶段的 10 倍。"""
    low_total = await _run_phase(_checkout_and_order, LOW_QPS, DURATION_SEC)
    high_total = await _run_phase(_checkout_and_order, HIGH_QPS, DURATION_SEC)

    ratio = high_total / low_total if low_total else float("inf")
    assert 5 <= ratio <= 20, (
        f"DB 查询量未跟随写入线性增长:\n"
        f"  低写({LOW_QPS} QPS) DB 查询总量={low_total}\n"
        f"  高写({HIGH_QPS} QPS) DB 查询总量={high_total}\n"
        f"  比率={ratio:.2f}（预期约 10）"
    )

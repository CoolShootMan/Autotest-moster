#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_http.py —— 全局 HTTP 请求审计模块（单点入口）。

所有 HTTP 请求统一经本模块记录到 REQUEST_LOG，供测试结束后生成 GET API DB 审计报告。
目标：暴露"任何 GET 接口预热后二次读取仍读 DB"的违规——这是大流量涌入时
缓存击穿/穿透导致系统瘫痪的隐患点。

动机（审计盲区历史）：
早期审计只覆盖 http_client fixture（httpx AsyncClient event hook）发出的请求，
以下三类真实 GET 全部漏采，导致"违规 0 读取"数量被严重低估：
  1. dynamic_ids.py / conftest.py 里的裸 httpx 调用（POST_DETAIL、PDP SSR、
     admin product/search、product-event/list、promotions 等辅助查询）；
  2. Playwright 页面内的 SSR 文档 + XHR（GET /cart、feature-setting-public 等），
     navigate_pear_page 只抓 console 数值、从不写审计日志；
  3. 只请求 1 次的接口按旧口径必判"通过"（无第 2 次读取 → 实际未验证）。

本模块将记录逻辑收敛到一处：
  - get_sync_client()  ：会话级同步 client 单例，dynamic_ids / conftest 裸调用复用，
                         自动记录（GET/POST/PATCH/DELETE 全部入日志）；
  - get_async_client() ：http_client fixture 使用的异步 client（函数级新建/关闭）；
  - record_request()   ：Playwright 侧（页面响应）与其它手动场景记录。
"""
import httpx

# 全局请求日志：每个条目 {method, url, status, db, source}
#   source ∈ {"httpx", "playwright"} —— httpx 经 event hook 自动记录，
#   playwright 由页面 response 监听手动 record_request。
REQUEST_LOG = []


def _extract_db(response) -> int:
    """从响应头 X-DB-Query-Count 提取 DB 查询次数；缺失返回 -1。"""
    try:
        return int(response.headers.get("X-DB-Query-Count", -1))
    except (ValueError, TypeError):
        return -1


def record_request(method: str, url: str, status: int, db: int, source: str = "httpx") -> None:
    """记录一次请求到全局审计日志。"""
    REQUEST_LOG.append(
        {"method": method, "url": url, "status": status, "db": db, "source": source}
    )


def _on_response(response) -> None:
    """httpx 同步 event hook：自动记录所有请求（GET/POST/PATCH/DELETE）。"""
    record_request(
        method=response.request.method,
        url=str(response.request.url),
        status=response.status_code,
        db=_extract_db(response),
    )


async def _on_response_async(response) -> None:
    """httpx 异步 event hook：同步调用 _on_response（其内部无 await，纯记录）。"""
    _on_response(response)


_sync_client = None


def get_sync_client() -> httpx.Client:
    """会话级同步 client 单例：dynamic_ids / conftest 裸调用复用，所有请求自动入审计。"""
    global _sync_client
    if _sync_client is None:
        _sync_client = httpx.Client(
            timeout=30, event_hooks={"response": [_on_response]}
        )
    return _sync_client


def get_async_client() -> httpx.AsyncClient:
    """http_client fixture 使用的异步 client（每次 fixture 新建，用完关闭）。"""
    return httpx.AsyncClient(timeout=30, event_hooks={"response": [_on_response_async]})

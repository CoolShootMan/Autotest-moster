#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dynamic_ids.py —— 运行时动态业务 ID 获取模块。

所有业务 id 不写死，运行时从接口查询，适配多环境（release / prod）：
  - curator_post_id()   : GET POST_DETAIL_PATH → data.id（主 post）
  - product_variant_id() : POST_DETAIL → relatedProducts[0].displayVariantId（consumer 侧加购）
  - pdp_product_variant_id(): PDP SSR HTML 提取 displayVariantId（PDP 页主商品）
  - admin_pdp_product_id()/admin_pdp_variant_id(): admin 侧 product / variant id
  - user_id()/curator_id(): users/search 按账号邮箱查 consumer / curator id
  - user_b_token()/guest_token(): guest-login 动态签发 GUEST JWT（每次会话全新用户）
  - event_id(): product-event/list 按 title 匹配事件 id
  引用动态 id 的读接口路径由 *_path() 函数运行时拼接。

用法：
  from dynamic_ids import curator_post_id, promo_path, user_id, product_event_path

敏感凭据：Bearer token 由 guest-login 动态签发；Pear-Client-Id / Secret 由 .env 提供。
均不入 CSV、不写死。
"""
import base64
import hashlib
import json
import os
import re
import uuid
from functools import lru_cache

import httpx
from dotenv import load_dotenv

from api_params import (
    ADMIN_URL,
    BASE_URL,
    CONSUMER_EMAIL,
    CURATOR_EMAIL,
    CURATOR_SHOP_URL,
    PDP_URL,
    POST_DETAIL_PATH,
)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 按 API_ENV（release|prod，默认 release）加载对应环境文件 .env.{API_ENV}，不存在时回退 .env。
_ENV_NAME = os.getenv("API_ENV", "release").strip().lower()
_ENV_FILE = os.path.join(_BASE_DIR, f".env.{_ENV_NAME}")
load_dotenv(_ENV_FILE if os.path.exists(_ENV_FILE) else os.path.join(_BASE_DIR, ".env"))

# 敏感凭据：由 .env 提供（消费者 Bearer token 不再落 .env，运行时 guest-login 动态签发）
_PEAR_CLIENT_ID = os.getenv("PEAR_CLIENT_ID", "")
_PEAR_CLIENT_SECRET = os.getenv("PEAR_CLIENT_SECRET", "")


@lru_cache(maxsize=1)
def _curator_token() -> str:
    """web 端 curator/promoter 登录：POST /auth/sign-in → data.token。

    product-event/list 按登录用户店铺维度过滤：guest 视角恒为空（totalCount=0），
    必须用 curator 登录态才能查到店铺事件。CURATOR_EMAIL 由 CSV 提供，
    CURATOR_PASSWORD 由 .env 提供；password 需 MD5（若已是 32 位 hex 则原样透传）。
    """
    import hashlib
    import re as _re

    email = CURATOR_EMAIL
    password = os.getenv("CURATOR_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("CURATOR_EMAIL / CURATOR_PASSWORD 未配置（.env），无法 curator sign-in")
    if not _re.fullmatch(r"[0-9a-fA-F]{32}", password):
        password = hashlib.md5(password.encode()).hexdigest()
    resp = httpx.post(
        f"{BASE_URL}/auth/sign-in",
        json={
            "email": email,
            "password": password,
            "subdomainVanityUrl": CURATOR_SHOP_URL,
        },
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"curator sign-in failed: {resp.status_code} {resp.text[:300]}")
    data = resp.json()
    token = (
        data.get("token")
        or data.get("data", {}).get("token")
        or (data.get("data") if isinstance(data.get("data"), str) else None)
    )
    if not token:
        raise RuntimeError(f"curator sign-in 响应无 token: {resp.text[:300]}")
    return token


def _post_detail_headers() -> dict:
    """POST_DETAIL 读接口鉴权头：Bearer（guest-login 动态签发）+ Pear-Client-Id/Secret（若 .env 已配置）。"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {guest_token()}",
    }
    if _PEAR_CLIENT_ID and _PEAR_CLIENT_SECRET:
        headers["Pear-Client-Id"] = _PEAR_CLIENT_ID
        headers["Pear-Client-Secret"] = _PEAR_CLIENT_SECRET
    return headers


@lru_cache(maxsize=1)
def curator_post_id() -> str:
    """GET POST_DETAIL_PATH，返回 $.data.id（主 post 的 UUID）。

    进程内只查询一次（lru_cache），post id 在运行期间不变。
    """
    resp = httpx.get(
        f"{BASE_URL}{POST_DETAIL_PATH}",
        headers=_post_detail_headers(),
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    post_id = (payload.get("data") or {}).get("id")
    if not post_id:
        raise RuntimeError(
            f"GET {POST_DETAIL_PATH} 未返回 data.id "
            f"(status={resp.status_code}): {resp.text[:300]}"
        )
    print(
        f"[dynamic_ids] CURATOR_POST_ID = {post_id} "
        f"(来自 GET {POST_DETAIL_PATH})"
    )
    return post_id


@lru_cache(maxsize=1)
def product_variant_id() -> str:
    """PUT /cart 加购的商品变体 id：GET POST_DETAIL_PATH → data.relatedProducts[0].displayVariantId。

    替代 test_promotion.py 写死的 promoterProductVariantId（28227f32...），
    运行时从 post detail 的第一个关联商品动态获取，避免环境 id 漂移。
    """
    resp = httpx.get(
        f"{BASE_URL}{POST_DETAIL_PATH}",
        headers=_post_detail_headers(),
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    related = (payload.get("data") or {}).get("relatedProducts") or []
    if not related:
        raise RuntimeError(
            f"GET {POST_DETAIL_PATH} 未返回 relatedProducts "
            f"(status={resp.status_code}): {resp.text[:300]}"
        )
    vid = (related[0] or {}).get("displayVariantId")
    if not vid:
        raise RuntimeError(
            f"GET {POST_DETAIL_PATH} relatedProducts[0] 无 displayVariantId: "
            f"{resp.text[:300]}"
        )
    print(
        f"[dynamic_ids] PRODUCT_VARIANT_ID = {vid} "
        f"(来自 POST_DETAIL relatedProducts[0].displayVariantId)"
    )
    return vid


def promo_path() -> str:
    """promotion 写接口完整 URL：{BASE_URL}/posts/curator/{curator_post_id()}/promotions。"""
    return f"{BASE_URL}/posts/curator/{curator_post_id()}/promotions"


@lru_cache(maxsize=1)
def admin_pdp_product_id() -> str:
    """PDP 商品（test 11756）的 admin product id：search?query=test+11756 唯一匹配。"""
    import urllib.parse

    query = urllib.parse.quote("test 11756")
    resp = httpx.get(
        f"{ADMIN_URL}/merchant/product/search?query={query}",
        headers=_admin_headers(),
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 200:
        raise RuntimeError(
            f"merchant/product/search(test 11756) 非 200: code={payload.get('code')} "
            f"{resp.text[:300]}"
        )
    items = (payload.get("data") or {}).get("items") or []
    if not items:
        raise RuntimeError(
            f"merchant/product/search(test 11756) 无匹配商品: {resp.text[:300]}"
        )
    pid = items[0].get("id")
    if not pid:
        raise RuntimeError(
            f"merchant/product/search(test 11756) items[0] 无 id: {resp.text[:300]}"
        )
    print(f"[dynamic_ids] ADMIN_PDP_PRODUCT_ID = {pid}（来自 admin product/search test 11756）")
    return pid


@lru_cache(maxsize=1)
def admin_pdp_variant_id() -> str:
    """PDP 商品 admin 侧 merchantProductVariantId：GET /merchant/product/{pid} → variants[0].id。

    注意：与 consumer 加购用的 displayVariantId（pdp_product_variant_id）不同，切勿混用。
    """
    resp = httpx.get(
        f"{ADMIN_URL}/merchant/product/{admin_pdp_product_id()}",
        headers=_admin_headers(),
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data") or {}
    variants = data.get("variants") or []
    if not variants:
        raise RuntimeError(
            f"GET /merchant/product/{admin_pdp_product_id()} 无 variants: {resp.text[:300]}"
        )
    vid = (variants[0] or {}).get("id")
    if not vid:
        raise RuntimeError(
            f"GET /merchant/product/{admin_pdp_product_id()} variants[0] 无 id: {resp.text[:300]}"
        )
    print(
        f"[dynamic_ids] ADMIN_PDP_VARIANT_ID = {vid} "
        f"(来自 admin GET /merchant/product/{admin_pdp_product_id()})"
    )
    return vid


@lru_cache(maxsize=1)
def pdp_product_variant_id() -> str:
    """PDP 商品详情页主商品的 variant id：从 PDP SSR HTML 的 displayVariantId 动态提取。

    替代 test_promotion.py 写死的 9b39c18a-...（PDP 页 /resident/p/jjkbor 商品
    test 11756 的 displayVariantId），运行时从 PDP 页面 HTML 的
    __NEXT_DATA__ 内嵌 JSON（product.displayVariantId）解析，避免环境 id 漂移。
    """
    resp = httpx.get(PDP_URL, timeout=20, follow_redirects=True)
    resp.raise_for_status()
    html = resp.text
    # PDP SSR 内嵌 JSON 以转义形式出现（\\"displayVariantId\\":\\"...\\"），
    # 也兼容未转义形式，两种都尝试。
    m = re.search(r'\\?"displayVariantId\\?":\\?"([0-9a-fA-F-]{36})\\"?', html)
    if not m:
        m = re.search(r'"displayVariantId":"([0-9a-fA-F-]{36})"', html)
    if not m:
        raise RuntimeError(
            f"GET {PDP_URL} 未找到 displayVariantId (status={resp.status_code})"
        )
    vid = m.group(1)
    print(f"[dynamic_ids] PDP_PRODUCT_VARIANT_ID = {vid} (来自 PDP SSR {PDP_URL})")
    return vid


# ---- admin 登录 / users/search：按账号邮箱动态获取 user / curator id ----

# curator 账号邮箱：与 conftest.PROMO_EMAIL 同源（来自 API_Parameter_Release.csv / API_Parameter_Prod.csv）
_CURATOR_EMAIL = CURATOR_EMAIL


@lru_cache(maxsize=1)
def _admin_token() -> str:
    """POST {ADMIN_URL}/auth/login 获取 admin token（凭据由 .env 提供，会话内缓存）。"""
    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASSWORD")
    if not email or not password:
        raise RuntimeError(
            "ADMIN_EMAIL / ADMIN_PASSWORD 未设置（.env），无法登录 admin 获取用户 id。"
        )
    resp = httpx.post(
        f"{ADMIN_URL}/auth/login",
        json={"email": email, "password": password},
        headers={
            "Content-Type": "application/json",
            "from": "client",
            "timezone": "Asia/Shanghai",
        },
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"admin login failed: {resp.status_code} {resp.text[:300]}")
    data = resp.json()
    token = (
        data.get("token")
        or data.get("accessToken")
        or data.get("data", {}).get("token")
        or data.get("data", {}).get("accessToken")
    )
    if not token:
        raise RuntimeError(f"admin login 响应无 token: {resp.text[:300]}")
    return token


def _admin_headers() -> dict:
    """admin 请求头：不落 .env，统一走动态登录（_admin_token）。"""
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_admin_token()}",
        "from": "client",
        "timezone": "Asia/Shanghai",
        "Pear-AutoTesting": "Lury",
    }


def _search_user(email: str) -> str:
    """POST {ADMIN_URL}/users/search 按账号邮箱查用户，返回 data.items[0].id。"""
    headers = _admin_headers()
    body = {
        "query": email,
        "filter": {
            "userRoles": ["PROMOTER", "BUSINESS_PARTNER", "CONSUMER"],
            "userType": "ALL",
        },
        "pageSize": 100,
        "pageNumber": 1,
    }
    resp = httpx.post(f"{ADMIN_URL}/users/search", json=body, headers=headers, timeout=20)
    payload = resp.json()
    if payload.get("code") != 200:
        raise RuntimeError(
            f"users/search({email}) 非 200: code={payload.get('code')} {resp.text[:300]}"
        )
    items = (payload.get("data") or {}).get("items") or []
    if not items:
        raise RuntimeError(f"users/search({email}) 无匹配用户: {resp.text[:300]}")
    user_id = items[0].get("id")
    if not user_id:
        raise RuntimeError(f"users/search({email}) items[0] 无 id: {resp.text[:300]}")
    return user_id


@lru_cache(maxsize=1)
def user_id() -> str:
    """storefront 消费者 USER_ID：按账号邮箱（CONSUMER_EMAIL）查 users/search。"""
    if not CONSUMER_EMAIL:
        raise RuntimeError("CONSUMER_EMAIL 未配置（请检查对应环境的 API_Parameter_*.csv）")
    uid = _search_user(CONSUMER_EMAIL)
    print(f"[dynamic_ids] USER_ID = {uid}（来自 users/search {CONSUMER_EMAIL}）")
    return uid


@lru_cache(maxsize=1)
def curator_id() -> str:
    """curator（promoter）id：按账号邮箱（CURATOR_EMAIL）查 users/search。

    原 PROMOTER_ID 更名而来，语义为 curator 店铺的 promoter id。
    """
    email = _CURATOR_EMAIL
    if not email:
        raise RuntimeError("CURATOR_EMAIL 未配置（.env）")
    cid = _search_user(email)
    print(f"[dynamic_ids] CURATOR_ID = {cid}（来自 users/search {email}）")
    return cid


@lru_cache(maxsize=1)
def _user_b_guest() -> tuple:
    """User B 的 GUEST 用户信息：每次会话动态创建，返回 (token, user_id)。

    用随机 UUID 作为 consumerId 调 POST {BASE_URL}/auth/guest-login，
    服务端签发全新 GUEST token；解码 JWT payload 提取 userId，
    该 userId 即 User B 的 consumer id（缓存隔离测试隔离主体）。
    与 conftest.header_integrity_check 完全同模式，保证每次会话都是全新 guest、id 不写死。
    """
    consumer_id = str(uuid.uuid4())
    resp = httpx.post(
        f"{BASE_URL}/auth/guest-login",
        json={"consumerId": consumer_id},
        timeout=10,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"User B guest-login failed: {resp.status_code} {resp.text[:300]}"
        )
    token = resp.json()["data"]
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload_json = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
        user_id = json.loads(payload_json)["userId"]
    except Exception as exc:
        raise RuntimeError(f"User B guest JWT 解码失败: {exc}") from exc
    return token, user_id


@lru_cache(maxsize=1)
def user_b_id() -> str:
    """缓存隔离测试用户 B 的 consumer id：guest-login 动态创建获取，不写死。"""
    _, bid = _user_b_guest()
    print(f"[dynamic_ids] USER_B_CONSUMER_ID = {bid}（guest-login 动态创建）")
    return bid


def user_b_token() -> str:
    """User B 同一次 guest-login 签发的 GUEST token，供 conftest 复用 Authorization。"""
    token, _ = _user_b_guest()
    return token


def guest_token() -> str:
    """通用消费者 GUEST JWT：guest-login 动态签发，供公共 Authorization 头复用。"""
    token, _ = _user_b_guest()
    return token


# ---- 动态 id 引用的读接口路径（运行时拼接） ----

def feature_flag_user_path() -> str:
    return f"/feature-flag/user/{user_id()}"


def feature_flag_public_path() -> str:
    return f"/feature-flag/user/{user_id()}/public"


def feature_setting_public_path() -> str:
    return (
        f"/feature-setting/consumer-public?scene=SCENE_GUEST_SHOP"
        f"&promoterId={curator_id()}"
    )


def promoter_sub_path() -> str:
    return f"/promoter-subscription/setting/{user_id()}?settingType=SUBSCRIPTION"


@lru_cache(maxsize=1)
def event_id() -> str:
    """product-event 事件 id：GET /product-event/list（curator 登录态）按 title 匹配。

    注意：list 按店铺维度过滤，guest 视角恒为空，必须用 curator sign-in token 查询。
    """
    event_title = os.getenv("EVENT_TITLE", "cache regression - auto test")
    resp = httpx.get(
        f"{BASE_URL}/product-event/list?keyword=&pageSize=50&pageNumber=1",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {_curator_token()}"},
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    items = (payload.get("data") or {}).get("items") or []
    for item in items:
        if item.get("title") == event_title and item.get("id"):
            print(
                f"[dynamic_ids] EVENT_ID = {item['id']} "
                f"(来自 GET /product-event/list，title={event_title!r})"
            )
            return item["id"]
    raise RuntimeError(
        f"GET /product-event/list 未找到 title={event_title!r} 的事件 "
        f"(status={resp.status_code}): {resp.text[:300]}"
    )


def product_event_path() -> str:
    """product-event 公开详情读接口路径：/product-event/{event_id()}/public-details。"""
    return f"/product-event/{event_id()}/public-details"


if __name__ == "__main__":
    print(f"BASE_URL        = {BASE_URL}")
    print(f"POST_DETAIL_PATH= {POST_DETAIL_PATH}")
    print(f"CURATOR_POST_ID = {curator_post_id()}")
    print(f"PROMO_URL       = {promo_path()}")
    print(f"USER_ID         = {user_id()}")
    print(f"CURATOR_ID      = {curator_id()}")
    print(f"USER_B_CONSUMER_ID = {user_b_id()}")
    print(f"FEATURE_FLAG_USER_PATH  = {feature_flag_user_path()}")
    print(f"FEATURE_SETTING_PUBLIC  = {feature_setting_public_path()}")
    print(f"PROMOTER_SUB_PATH       = {promoter_sub_path()}")
    print(f"PRODUCT_EVENT_PATH      = {product_event_path()}")

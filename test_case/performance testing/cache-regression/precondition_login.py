#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
precondition_login.py —— 统一前置准备脚本：动态登录 admin + curator 并校验。

token 全部由登录 API 动态签发、不落 .env（均为临时凭据，TTL 短）：
  1. admin token   ：POST {ADMIN_URL}/auth/login（email+password → data.token）
  2. curator token ：POST {BASE_URL}/auth/sign-in（web 端 curator/promoter 登录，
                     subdomainVanityUrl=curator 店铺 vanity URL（CURATOR_SHOP_URL，默认 resident）
                     → data.token；password 字段需 MD5 哈希）

凭据（建议首次用 --set-credentials 写入对应环境文件 .env.{API_ENV}）：
  ADMIN_EMAIL   / ADMIN_PASSWORD
  CURATOR_PASSWORD（curator 邮箱统一走 CSV：api_params.CURATOR_EMAIL，.env 不再维护）

职责边界（框架结构）：
- 运行时 token 自愈逻辑收敛在 conftest.py：admin 动态登录 + 401 自动重登、
  curator 每次会话动态 sign-in、消费者 GUEST token 由 guest-login 动态签发，
  因此即便不跑本脚本测试也能自愈；
- 本脚本定位为「凭据管理 + 动态登录验证」：CI 跑测前验证凭据可用、
  首次写入凭据。

说明：curator 的 sign-in token 实测 TTL 仅约 2 分钟，故一律动态签发、
不写入 .env 缓存。

用法：
  python precondition_login.py                         # 前置准备：动态登录 admin + curator 并校验
  python precondition_login.py --set-credentials admin   <email> <pwd>
  python precondition_login.py --set-credentials curator <email> <pwd>   # 存明文，登录时自动 MD5
  python precondition_login.py --print admin            # 仅打印 admin token（动态登录获取）
  python precondition_login.py --print curator          # 仅打印 curator token
  python precondition_login.py --verify                 # 验证凭据可动态登录
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

import httpx

# 统一参数中心（按 API_ENV 分环境读取 API_Parameter_Release.csv / API_Parameter_Prod.csv，api_params.py 读取）
# 环境/接口路径参数在此引用，切生产环境仅需 API_ENV=prod + 在 API_Parameter_Prod.csv 的 value 列填写生产值。
# 敏感凭据（邮箱/密码/token）仍由 .env 提供，不入 CSV。
from api_params import (
    ADMIN_URL,
    ADMIN_PROMOTIONS_PATH,
    CURATOR_SHOP_URL,
    CURATOR_EMAIL,
    BASE_URL,
    LOGIN_PATH,
    POST_DETAIL_PATH,
    SIGNIN_PATH,
)

BASE_DIR = Path(__file__).resolve().parent
# 按 API_ENV（release|prod，默认 release）选择对应环境文件 .env.{API_ENV}；不存在时回退 .env。
_ENV_NAME = os.getenv("API_ENV", "release").strip().lower()
ENV_PATH = BASE_DIR / f".env.{_ENV_NAME}"
if not ENV_PATH.exists():
    ENV_PATH = BASE_DIR / ".env"

# 各角色 .env 键（token 不落 .env，仅凭据持久化）
ROLE_KEYS = {
    "admin": {
        "email": "ADMIN_EMAIL",
        "password": "ADMIN_PASSWORD",
    },
    "curator": {
        # 邮箱统一走 CSV（api_params.CURATOR_EMAIL），.env 不再维护，避免双源冲突
        "password": "CURATOR_PASSWORD",
    },
}

_MD5_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def _to_md5(password: str) -> str:
    """sign-in 的 password 字段需为 MD5(明文)。若已是 32 位 hex 则原样返回。"""
    if _MD5_RE.fullmatch(password):
        return password
    return hashlib.md5(password.encode()).hexdigest()


def _load_env() -> dict:
    """读取本目录 .env（简易解析，兼容注释与空行）。"""
    data = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            data[k.strip()] = v.strip()
    return data


def _save_env(updates: dict) -> None:
    """把 updates 写回当前环境文件 ENV_PATH（.env.{API_ENV}）：已存在键原位替换，新键追加到末尾。"""
    env = _load_env()
    env.update(updates)
    lines = []
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k = line.partition("=")[0].strip()
                if k in updates:
                    lines.append(f"{k}={updates[k]}")
                    updates.pop(k)
                    continue
            lines.append(line)
    for k, v in updates.items():
        lines.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[precondition] 已更新 {ENV_PATH}")


def _get_credentials(env: dict, role: str) -> tuple[str, str]:
    keys = ROLE_KEYS[role]
    if role == "curator":
        # curator 邮箱统一走 CSV（api_params.CURATOR_EMAIL），.env 不再维护，避免双源冲突
        email = CURATOR_EMAIL
    else:
        email = os.getenv(keys["email"]) or env.get(keys["email"])
    password = os.getenv(keys["password"]) or env.get(keys["password"])
    if not email or not password:
        email_src = keys.get("email") or "CURATOR_EMAIL（由 CSV 提供）"
        print(
            f"[precondition] 错误：未找到 {role} 凭据。\n"
            f"  请设置 {email_src} / {keys['password']}，\n"
            f"  或用 --set-credentials {role} <email> <pwd> 写入环境文件。",
            file=sys.stderr,
        )
        sys.exit(1)
    return email, password


def _login_admin(email: str, password: str) -> str:
    """admin 登录：POST /auth/login → data.token"""
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
        raise RuntimeError(f"admin login 响应无 token 字段: {resp.text[:300]}")
    return token


def _login_curator(email: str, password: str) -> str:
    """curator（web 端 promoter）登录：POST /auth/sign-in → data.token

    password 传明文即可（如 Happy123），内部自动 MD5 哈希；
    传 32 位 hex（已是 MD5）则原样透传。
    """
    resp = httpx.post(
        f"{BASE_URL}/auth/sign-in",
        json={
            "email": email,
            "password": _to_md5(password),
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
        raise RuntimeError(f"curator sign-in 响应无 token 字段: {resp.text[:300]}")
    return token


def _verify_admin(token: str) -> bool:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "from": "client",
        "timezone": "Asia/Shanghai",
    }
    try:
        resp = httpx.get(
            f"{ADMIN_URL}{ADMIN_PROMOTIONS_PATH}",
            headers=headers,
            timeout=20,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _verify_curator(token: str) -> bool:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "from": "client",
        "timezone": "Asia/Shanghai",
    }
    try:
        resp = httpx.get(
            f"{BASE_URL}{POST_DETAIL_PATH}",
            headers=headers,
            timeout=20,
        )
        return resp.status_code in (200, 201)
    except Exception:
        return False


_VERIFIERS = {"admin": _verify_admin, "curator": _verify_curator}
_LOGINS = {"admin": _login_admin, "curator": _login_curator}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="统一前置准备：动态登录并校验 admin / curator 凭据（token 不落 .env）"
    )
    parser.add_argument("--print", choices=["admin", "curator"], help="动态登录并仅打印指定角色 token（不写文件）")
    parser.add_argument("--verify", action="store_true", help="验证 admin / curator 凭据可动态登录")
    parser.add_argument(
        "--set-credentials",
        nargs=3,
        metavar=("ROLE", "EMAIL", "PASSWORD"),
        help="写入指定角色凭据到当前环境文件 .env.{API_ENV}（ROLE=admin|curator；curator 邮箱走 CSV 仅存密码明文，登录时自动 MD5）",
    )
    args = parser.parse_args()

    env = _load_env()

    if args.set_credentials:
        role, email, password = args.set_credentials
        if role not in ROLE_KEYS:
            print(f"[precondition] 错误：未知角色 {role!r}（可选 admin|curator）", file=sys.stderr)
            return 1
        _updates = {ROLE_KEYS[role]["password"]: password}
        if "email" in ROLE_KEYS[role]:
            _updates[ROLE_KEYS[role]["email"]] = email
        _save_env(_updates)
        env = _load_env()

    if args.verify:
        # token 不落 .env，改为验证凭据能否动态登录
        for role in ROLE_KEYS:
            email, password = _get_credentials(env, role)
            token = _LOGINS[role](email, password)
            ok = _VERIFIERS[role](token)
            print(
                f"[precondition] {role} 动态登录校验：{'有效' if ok else '异常'}"
                f"（token 长度 {len(token)}）"
            )
        return 0

    if args.print:
        role = args.print
        email, password = _get_credentials(env, role)
        token = _LOGINS[role](email, password)
        print(token)
        return 0

    # 默认：前置准备 —— 动态登录 admin + curator 并校验，token 不写 .env
    for role in ("admin", "curator"):
        email, password = _get_credentials(env, role)
        token = _LOGINS[role](email, password)
        ok = _VERIFIERS[role](token)
        print(
            f"[precondition] {role} 动态登录成功（token 长度 {len(token)}），"
            f"校验：{'有效' if ok else '异常'}"
        )
    print("[precondition] 前置准备完成：admin / curator 均可动态登录（token 不落 .env）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

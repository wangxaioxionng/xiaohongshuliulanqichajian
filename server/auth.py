#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
鉴权模块（v4）

支持两条路径：
1. JWT 路径（新）：Authorization: Bearer <jwt>，从 SQLite 查用户
2. legacy token 路径（兼容）：X-Auth-Token: <token>，从 config.json 查老用户

两种路径都返回统一的 user dict：
    {
        "user_id": int | None,         # SQLite id（legacy 用户为 None）
        "legacy_id": str | None,       # config.json 里的 user_id（legacy 用户专用）
        "open_id": str | None,         # 飞书 open_id（新用户专用）
        "name": str,
        "spreadsheet_token": str,
        "default_sheet_id": str,
        "is_legacy": bool,
        "is_admin": bool,
    }
"""
import secrets
import time
from typing import Optional

import jwt as pyjwt
from fastapi import HTTPException, Header

import db


# JWT 配置
JWT_ALG = "HS256"
JWT_TTL = 60 * 60 * 24 * 30  # 30 天

# secret 从 config 读（运行时注入）
_jwt_secret: Optional[str] = None
_legacy_token_to_user: dict = {}
_admin_legacy_ids: set = set()


def configure(jwt_secret: str, legacy_token_to_user: dict,
              admin_legacy_ids: set) -> None:
    """从 app.py 启动时调用，注入运行时配置。"""
    global _jwt_secret, _legacy_token_to_user, _admin_legacy_ids
    _jwt_secret = jwt_secret
    _legacy_token_to_user = legacy_token_to_user
    _admin_legacy_ids = admin_legacy_ids


def get_or_generate_jwt_secret(config: dict) -> str:
    """JWT secret 从 config['jwt_secret'] 读；没有就自动生成。"""
    sec = config.get("jwt_secret")
    if sec:
        return sec
    # 自动生成并提示
    new = secrets.token_urlsafe(48)
    print(f"⚠️ config.json 缺 jwt_secret，已自动生成。请加到 config.json:")
    print(f'   "jwt_secret": "{new}"')
    return new


# ---------- JWT 签发与验证 ----------

def issue_jwt(user_id: int, open_id: str) -> str:
    """签发 JWT。"""
    now = int(time.time())
    payload = {
        "user_id": user_id,
        "open_id": open_id,
        "iat": now,
        "exp": now + JWT_TTL,
    }
    return pyjwt.encode(payload, _jwt_secret, algorithm=JWT_ALG)


def decode_jwt(token: str) -> Optional[dict]:
    """验证 JWT，返回 payload 或 None。"""
    if not _jwt_secret:
        return None
    try:
        return pyjwt.decode(token, _jwt_secret, algorithms=[JWT_ALG])
    except (pyjwt.InvalidTokenError, pyjwt.ExpiredSignatureError):
        return None


# ---------- 鉴权（统一入口）----------

def auth_legacy(token: str) -> Optional[dict]:
    """legacy X-Auth-Token 路径。legacy 用户永远是 active 状态。"""
    user = _legacy_token_to_user.get(token)
    if not user:
        return None
    return {
        "user_id": None,
        "legacy_id": user["legacy_id"],
        "open_id": None,
        "name": user["name"],
        "spreadsheet_token": user["spreadsheet_token"],
        "default_sheet_id": user["default_sheet_id"],
        "status": "active",
        "is_legacy": True,
        "is_admin": user["legacy_id"] in _admin_legacy_ids,
    }


def auth_jwt(token: str) -> Optional[dict]:
    """JWT 路径。返回 user dict 含 status 字段；不在此处拦截 pending（让上层 endpoint 自己决定）。

    被拦截的状态：
    - disabled / banned（明确禁用）→ 返回 None
    - pending / active → 返回 user dict（带 status 让上层判断）
    """
    payload = decode_jwt(token)
    if not payload:
        return None
    user_row = db.get_user_by_id(payload["user_id"])
    if not user_row:
        return None
    if user_row["status"] in ("disabled", "banned"):
        return None
    return {
        "user_id": user_row["id"],
        "legacy_id": None,
        "open_id": user_row["open_id"],
        "name": user_row["name"],
        "spreadsheet_token": user_row["spreadsheet_token"],
        "default_sheet_id": user_row["default_sheet_id"],
        "status": user_row["status"],
        "is_legacy": False,
        "is_admin": user_row["role"] == "admin",
    }


def require_user(authorization: Optional[str] = Header(None),
                 x_auth_token: Optional[str] = Header(None)) -> dict:
    """FastAPI 依赖：从 Authorization Bearer 或 X-Auth-Token 解出用户。

    优先 JWT（新用户）；fallback X-Auth-Token（legacy 用户）。
    """
    # 1. JWT 路径
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        u = auth_jwt(token)
        if u:
            return u
    # 2. legacy 路径
    if x_auth_token:
        u = auth_legacy(x_auth_token)
        if u:
            return u
    raise HTTPException(status_code=401, detail="未登录或凭证无效")


def require_active(authorization: Optional[str] = Header(None),
                    x_auth_token: Optional[str] = Header(None)) -> dict:
    """FastAPI 依赖：要求登录 + status=active（拦截 pending）。"""
    user = require_user(authorization, x_auth_token)
    if user.get("status") != "active":
        raise HTTPException(status_code=403,
                             detail="账号未激活，请先用激活码激活")
    return user


def require_active_with_sheet(authorization: Optional[str] = Header(None),
                              x_auth_token: Optional[str] = Header(None)) -> dict:
    """FastAPI 依赖：要求登录 + active + 已绑定飞书表。"""
    user = require_active(authorization, x_auth_token)
    if not user.get("spreadsheet_token"):
        raise HTTPException(status_code=403, detail="未绑定飞书表")
    return user


def require_admin(authorization: Optional[str] = Header(None),
                  x_auth_token: Optional[str] = Header(None)) -> dict:
    """FastAPI 依赖：要求 admin 身份。"""
    user = require_user(authorization, x_auth_token)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="需要 admin 权限")
    return user

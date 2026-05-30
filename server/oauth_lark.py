#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书 OAuth 流程（v4 用户自助登录）

参考飞书 OpenAPI 文档：
- 网页应用 OAuth：https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/web-app/web-app-overview

流程：
1. 用户访问 /auth/login → 重定向到飞书授权页
2. 飞书授权后回调 /auth/callback?code=xxx&state=yyy
3. 服务端用 code 换 user_access_token
4. 用 user_access_token 拿用户信息（open_id, name, avatar_url）
5. 创建/更新 SQLite user 记录
6. 签 JWT 返回给前端

OAuth scope（在飞书后台开通）：
- contact:user.base:readonly
- contact:user.id:readonly
"""
import urllib.parse
from typing import Optional

import requests

import db

LARK_BASE = "https://open.feishu.cn/open-apis"

# 飞书网页应用 OAuth 授权 URL
LARK_AUTHORIZE_URL = "https://open.feishu.cn/open-apis/authen/v1/authorize"
LARK_ACCESS_TOKEN_URL = "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
LARK_USERINFO_URL = "https://open.feishu.cn/open-apis/authen/v1/user_info"


class LarkOAuthError(Exception):
    pass


def build_authorize_url(app_id: str, redirect_uri: str) -> tuple:
    """构造飞书授权 URL。返回 (url, state) 元组。

    state 用 SQLite 持久化（防 CSRF + 防回放）：
    - 32 字节 hex nonce
    - TTL 10 分钟
    - 一次性消费（callback 命中即删）
    """
    state = db.create_oauth_state()
    params = {
        "app_id": app_id,
        "redirect_uri": redirect_uri,
        "scope": "contact:user.base:readonly contact:user.id:readonly",
        "state": state,
    }
    url = LARK_AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)
    return url, state


def validate_state(state: str) -> bool:
    """校验回调时的 state（防 CSRF + 防回放，原子消费）。"""
    return db.consume_oauth_state(state)


def exchange_code_for_token(app_id: str, app_secret: str, code: str,
                            redirect_uri: str) -> dict:
    """用 OAuth code 换 user_access_token。

    返回 {"access_token": "...", "expires_in": N, "refresh_token": "...",
          "open_id": "..."}.
    """
    resp = requests.post(
        LARK_ACCESS_TOKEN_URL,
        json={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
        },
        timeout=10,
    )
    data = resp.json()
    if data.get("code") and data["code"] != 0:
        raise LarkOAuthError(
            f"换 access_token 失败: code={data.get('code')} msg={data.get('error_description') or data.get('msg')}"
        )
    # 飞书 v2 OAuth 返回结构：{access_token, expires_in, refresh_token, ...}
    # 注意：error 字段也可能直接在顶层
    if data.get("error"):
        raise LarkOAuthError(
            f"换 access_token 失败: {data.get('error')} {data.get('error_description')}"
        )
    return data


def get_user_info(access_token: str) -> dict:
    """用 user_access_token 拿用户基本信息。"""
    resp = requests.get(
        LARK_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise LarkOAuthError(
            f"拿用户信息失败: code={data.get('code')} msg={data.get('msg')}"
        )
    return data.get("data", {})

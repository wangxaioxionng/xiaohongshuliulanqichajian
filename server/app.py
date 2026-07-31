#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xhs-collect 后端 API（FastAPI，OAuth 多租户 v4.0）

部署：
  uvicorn app:app --host 127.0.0.1 --port 8765

变更（v4.0）：
- 加入飞书 OAuth 用户自助登录（JWT 鉴权）
- 保留 X-Auth-Token 路径作为 legacy（v3.1 老用户继续可用）
- SQLite 持久化用户、激活码、偏好
- 新增 admin endpoints 管理激活码和用户
"""
import html
import json
import random
import re
import secrets as py_secrets
import threading
import time
import urllib.parse
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, Depends, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

import db
import auth
import oauth_lark
from collector import collect_one
from lark_writer import (
    LarkWriter, LarkAuthError, LarkAPIError,
    LAST_COL as LAST_COL_LETTER, NOTE_MULTI_IMAGE_MAX_COLS, NOTE_TOTAL_COLS,
    SHOP_PRODUCTS_SHEET_TITLE, flatten_desc, resolve_wiki_to_sheet_token,
    extract_hashtags,
)

# ---------- 配置 ----------
CONFIG_PATH = Path(__file__).parent / "config.json"
if not CONFIG_PATH.exists():
    raise SystemExit(f"config.json 不存在：{CONFIG_PATH}")
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

# 必备字段
for required in ("app_id", "app_secret"):
    if not CONFIG.get(required):
        raise SystemExit(f"config.json 缺少 {required} 字段")

# OAuth 配置
OAUTH_REDIRECT_URI = CONFIG.get("oauth_redirect_uri",
                                  "http://14.22.112.147:8866/auth/callback")
ADMIN_LEGACY_IDS = set(CONFIG.get("admins", []))

# 初始化 SQLite
db.init_schema()

# legacy 用户：从 config.json users 字段构建 token → user 映射
LEGACY_TOKEN_TO_USER = db.migrate_legacy_users(CONFIG)

# 注入 auth 模块运行时配置
auth.configure(
    jwt_secret=auth.get_or_generate_jwt_secret(CONFIG),
    legacy_token_to_user=LEGACY_TOKEN_TO_USER,
    admin_legacy_ids=ADMIN_LEGACY_IDS,
)

# 单例 LarkWriter
writer = LarkWriter(
    app_id=CONFIG["app_id"],
    app_secret=CONFIG["app_secret"],
)

# ---------- FastAPI ----------
app = FastAPI(title="xhs-collect API", version="4.9.0")

# CORS：v4 加 Authorization header（JWT 用）
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(chrome-extension://[a-z0-9]+|https?://(?:localhost|127\.0\.0\.1)(:\d+)?|https?://xaioxiongshutong\.cn(:\d+)?)$",
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["X-Auth-Token", "Authorization", "Content-Type"],
    allow_credentials=False,
    max_age=3600,
)


# ---------- 数据模型 ----------

class CollectRequest(BaseModel):
    url: str
    note: Optional[str] = ""
    tags: Optional[list] = None
    source: Optional[str] = "Extension"
    sheet_id: Optional[str] = None  # 默认用 user.default_sheet_id
    dup_strategy: Optional[str] = "skip"  # skip | update | always_new


class BatchRequest(BaseModel):
    urls: list
    note: Optional[str] = ""
    tags: Optional[list] = None
    source: Optional[str] = "Extension"
    sheet_id: Optional[str] = None
    dup_strategy: Optional[str] = "skip"


class ProfileCollectRequest(BaseModel):
    profile_url: str
    account_name: Optional[str] = ""
    note: Optional[str] = ""
    note_urls: Optional[list] = None
    max_items: Optional[int] = None
    source: Optional[str] = "账号全采集"


class ShopProductsCollectRequest(BaseModel):
    shop_info: Optional[dict] = {}
    products: Optional[list] = []
    source: Optional[str] = "店铺商品提取"
    remark: Optional[str] = ""


# ---------- 工具 ----------

MEOWLOAD_API_URL = CONFIG.get(
    "meowload_api_url",
    "https://api.meowload.net/openapi/extract/playlist",
)
MEOWLOAD_POST_API_URL = CONFIG.get(
    "meowload_post_api_url",
    "https://api.meowload.net/openapi/extract/post",
)
PROFILE_COLLECT_API_PROVIDER = (
    CONFIG.get("profile_collect_api_provider") or
    ("rnote" if CONFIG.get("rnote_api_key") else "meowload")
).strip().lower()
RNOTE_API_BASE = CONFIG.get("rnote_api_base", "https://rnote.dev").rstrip("/")
PROFILE_COLLECT_MAX_ITEMS = int(CONFIG.get("profile_collect_max_items", 400))
PROFILE_COLLECT_REQUEST_DELAY = float(CONFIG.get("profile_collect_delay", 2.5))
PROFILE_COLLECT_POST_RETRY_ATTEMPTS = max(
    1, int(CONFIG.get("profile_collect_post_retry_attempts", 3))
)
PROFILE_COLLECT_POST_RETRY_DELAY = float(
    CONFIG.get("profile_collect_post_retry_delay", 6.0)
)
PROFILE_COLLECT_POST_RETRY_JITTER = float(
    CONFIG.get("profile_collect_post_retry_jitter", 2.0)
)
PROFILE_COLLECT_MAX_IMAGE_COLS = int(
    CONFIG.get("profile_collect_max_image_cols", 20)
)
PROFILE_COLLECT_EMBED_IMAGES = bool(
    CONFIG.get("profile_collect_embed_images", True)
)
PROFILE_COLLECT_TASKS = {}
PROFILE_COLLECT_TASKS_LOCK = threading.Lock()

def _image_request_headers(headers: Optional[dict] = None) -> dict:
    """Build headers that can pass XHS image anti-hotlink checks."""
    safe = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.xiaohongshu.com/",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    if isinstance(headers, dict):
        for key in ("User-Agent", "Referer", "Accept", "Accept-Language"):
            value = headers.get(key) or headers.get(key.lower())
            if value:
                safe[key] = str(value)
    return safe


def _download_image(url: str, headers: Optional[dict] = None) -> Optional[bytes]:
    try:
        r = requests.get(
            url,
            timeout=15,
            headers=_image_request_headers(headers),
        )
        if r.status_code == 200 and len(r.content) > 1024:
            return r.content
    except Exception:
        pass
    return None


def _media_source_url(source) -> str:
    if isinstance(source, dict):
        return (source.get("url") or "").strip()
    return str(source or "").strip()


def _media_source_headers(source) -> dict:
    if isinstance(source, dict) and isinstance(source.get("headers"), dict):
        return source["headers"]
    return {}


def _download_images(sources: list, limit: Optional[int] = None) -> list:
    """按顺序下载图片，失败的跳过。"""
    images = []
    seen = set()
    for source in sources or []:
        if limit and len(images) >= limit:
            break
        url = _media_source_url(source)
        if not url or url in seen:
            continue
        seen.add(url)
        img = _download_image(url, _media_source_headers(source))
        if img:
            images.append(img)
    return images


def _sheet_saves_all_images(spreadsheet_token: str, sheet_id: str) -> bool:
    """普通笔记分类 sheet 都保存全部图片，工具专用表排除。"""
    title = writer.get_sheet_title(spreadsheet_token, sheet_id)
    return _is_note_category_sheet(title)


def _is_note_category_sheet(title: str) -> bool:
    """popup 的分类下拉只展示笔记收录分类，排除工具专用表。"""
    if not title:
        return False
    if title == SHOP_PRODUCTS_SHEET_TITLE:
        return False
    if title in getattr(writer, "ACCOUNT_LIB_SHEETS", ()):
        return False
    if title.endswith("全采集"):
        return False
    return True


def _prepare_images(data: dict, save_all_images: bool) -> tuple:
    """返回 (cover_bytes, all_image_bytes)。普通笔记最多嵌入 20 张图。"""
    if save_all_images:
        sources = data.get("image_items") or data.get("image_urls") or []
        if not sources and data.get("cover_url"):
            sources = [data["cover_url"]]
        images = _download_images(sources, limit=NOTE_MULTI_IMAGE_MAX_COLS)
        cover = images[0] if images else None
        return cover, images
    cover = None
    cover_source = None
    if data.get("image_items"):
        cover_source = data["image_items"][0]
    elif data.get("cover_url"):
        cover_source = data["cover_url"]
    if cover_source:
        cover = _download_image(
            _media_source_url(cover_source),
            _media_source_headers(cover_source),
        )
    return cover, None


def _get_meowload_api_key() -> str:
    key = (
        CONFIG.get("meowload_api_key") or
        CONFIG.get("henghengmao_api_key") or
        CONFIG.get("profile_collect_api_key") or
        ""
    ).strip()
    if not key:
        raise HTTPException(
            status_code=500,
            detail="服务器未配置整店采集 API key：请在 config.json 增加 meowload_api_key",
        )
    return key


def _get_rnote_api_key() -> str:
    key = (
        CONFIG.get("rnote_api_key") or
        CONFIG.get("profile_collect_api_key") or
        ""
    ).strip()
    if not key:
        raise HTTPException(
            status_code=500,
            detail="服务器未配置 Rnote API key：请在 config.json 增加 rnote_api_key",
        )
    return key


def _profile_collect_provider() -> str:
    provider = (PROFILE_COLLECT_API_PROVIDER or "meowload").strip().lower()
    if provider not in ("meowload", "rnote"):
        raise HTTPException(
            status_code=500,
            detail=f"不支持的整店采集 API provider：{provider}",
        )
    return provider


def _validate_xhs_profile_url(url: str) -> str:
    url = (url or "").strip()
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        raise HTTPException(status_code=400, detail="主页 URL 解析失败")
    allowed_hosts = {"www.xiaohongshu.com", "xiaohongshu.com"}
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="主页 URL 只允许 http/https")
    if parsed.hostname not in allowed_hosts:
        raise HTTPException(status_code=400, detail="只支持小红书账号主页")
    if not parsed.path.startswith("/user/profile/"):
        raise HTTPException(status_code=400, detail="请打开小红书账号主页后再采集")
    return url


def _extract_xhs_profile_user_id(profile_url: str) -> str:
    try:
        path = urllib.parse.urlparse(profile_url).path.strip("/")
    except Exception:
        return ""
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] == "user" and parts[1] == "profile":
        return parts[2].strip()
    return ""


def _validate_xhs_note_url(url: str) -> str:
    url = (url or "").strip()
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        raise ValueError("笔记 URL 解析失败")
    allowed_hosts = {"www.xiaohongshu.com", "xiaohongshu.com"}
    if parsed.scheme not in ("http", "https"):
        raise ValueError("笔记 URL 只允许 http/https")
    if parsed.hostname not in allowed_hosts:
        raise ValueError("只支持小红书笔记链接")
    if not (parsed.path.startswith("/explore/") or
            parsed.path.startswith("/discovery/item/")):
        raise ValueError("只支持小红书笔记详情链接")
    return url


def _xhs_note_id(url: str) -> str:
    try:
        path = urllib.parse.urlparse(url).path.strip("/")
    except Exception:
        return ""
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] in ("explore", "discovery"):
        return parts[-1]
    return ""


def _dedupe_note_urls(note_urls: list, max_items: int) -> list:
    """按笔记 ID 去重，优先保留带 xsec_token 的完整链接。"""
    by_id = {}
    ordered_ids = []
    fallback_urls = []
    for raw_url in note_urls or []:
        try:
            url = _validate_xhs_note_url(str(raw_url))
        except ValueError:
            continue
        note_id = _xhs_note_id(url)
        if not note_id:
            if url not in fallback_urls:
                fallback_urls.append(url)
            continue
        old = by_id.get(note_id)
        if old is None:
            by_id[note_id] = url
            ordered_ids.append(note_id)
        elif "xsec_token=" not in old and "xsec_token=" in url:
            by_id[note_id] = url
    deduped = [by_id[note_id] for note_id in ordered_ids]
    for url in fallback_urls:
        if len(deduped) >= max_items:
            break
        deduped.append(url)
    return deduped[:max_items]


def _format_profile_created_at(value: str) -> str:
    if not value:
        return ""
    try:
        ts = int(str(value).strip())
        if ts > 10_000_000_000:
            ts = ts / 1000
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value)


def _pick_profile_title(text: str, fallback: str) -> str:
    if not text:
        return fallback or ""
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    if not lines:
        return fallback or ""
    title = re.sub(r"#[^#\n]+?#", "", lines[0]).strip()
    if not title:
        title = lines[0].strip()
    return title[:80]


def _profile_media_items(medias: list) -> list:
    items = []
    seen = set()
    for media in medias or []:
        if not isinstance(media, dict):
            continue
        candidates = []
        media_type = (media.get("media_type") or "").lower()
        if media_type == "image":
            candidates = [media.get("resource_url") or media.get("preview_url")]
        else:
            candidates = [media.get("preview_url") or media.get("resource_url")]
        for url in candidates:
            if not url or url in seen:
                continue
            seen.add(url)
            items.append({
                "url": url,
                "headers": media.get("headers") if isinstance(media.get("headers"), dict) else {},
            })
    return items


def _profile_media_urls(medias: list) -> list:
    return [item["url"] for item in _profile_media_items(medias)]


def _rnote_image_url(image: dict) -> str:
    if not isinstance(image, dict):
        return ""
    for key in ("url", "original", "url_size_large", "origin_img"):
        value = image.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    levels = image.get("url_multi_level")
    if isinstance(levels, dict):
        for value in levels.values():
            if isinstance(value, str) and value.startswith("http"):
                return value
    if isinstance(levels, list):
        for item in levels:
            if isinstance(item, str) and item.startswith("http"):
                return item
            if isinstance(item, dict):
                url = _rnote_image_url(item)
                if url:
                    return url
    return ""


def _rnote_images_to_medias(images: list) -> list:
    medias = []
    seen = set()
    for image in images or []:
        url = _rnote_image_url(image)
        if not url or url in seen:
            continue
        seen.add(url)
        medias.append({
            "media_type": "image",
            "resource_url": url,
            "preview_url": url,
        })
    return medias


def _rnote_unwrap_response(data: dict, label: str):
    if not isinstance(data, dict):
        raise RuntimeError(f"Rnote {label} API 返回格式异常")
    if data.get("success") is False:
        msg = data.get("error") or data.get("message") or str(data)[:200]
        raise RuntimeError(f"Rnote {label} API 失败：{msg}")
    inner = data.get("data")
    if isinstance(inner, dict):
        if inner.get("success") is False or inner.get("code") not in (None, 0):
            msg = inner.get("msg") or inner.get("message") or str(inner)[:200]
            raise RuntimeError(f"Rnote {label} API 失败：{msg}")
        if "data" in inner:
            return inner.get("data")
    return inner


def _rnote_get(path: str, params: dict, label: str):
    api_key = _get_rnote_api_key()
    url = f"{RNOTE_API_BASE}{path}"
    headers = {
        "X-API-Key": api_key,
        "accept": "application/json",
    }
    try:
        resp = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=45,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"Rnote {label} API 请求失败：{e}") from e
    try:
        data = resp.json()
    except Exception as e:
        raise RuntimeError(
            f"Rnote {label} API 返回非 JSON：HTTP {resp.status_code}"
        ) from e
    if resp.status_code != 200:
        msg = data.get("error") or data.get("message") or data.get("detail")
        if not msg:
            msg = str(data)[:200]
        raise RuntimeError(f"Rnote {label} API 失败：{msg}")
    return _rnote_unwrap_response(data, label)


def _rnote_profile_note_to_post(note: dict) -> dict:
    note_id = str(note.get("id") or note.get("note_id") or "").strip()
    medias = _rnote_images_to_medias(note.get("images_list") or [])
    return {
        "id": note_id,
        "title": note.get("title") or note.get("display_title") or note_id,
        "text": note.get("desc") or note.get("content") or "",
        "post_url": f"https://www.xiaohongshu.com/explore/{note_id}" if note_id else "",
        "created_at": note.get("create_time") or note.get("created_time") or note.get("time") or "",
        "medias": medias,
        "liked_count": note.get("liked_count") or note.get("likes"),
        "collected_count": note.get("collected_count"),
        "comments_count": note.get("comments_count"),
        "shared_count": note.get("shared_count"),
    }


def _rnote_note_detail_to_post(detail) -> dict:
    entry = None
    if isinstance(detail, list) and detail:
        entry = detail[0]
    elif isinstance(detail, dict):
        entry = detail
    if not isinstance(entry, dict):
        raise RuntimeError("Rnote 图文详情 API data 字段异常")

    note = None
    note_list = entry.get("note_list") or []
    if note_list and isinstance(note_list[0], dict):
        note = note_list[0]
    elif isinstance(entry.get("note"), dict):
        note = entry["note"]
    elif entry.get("id") and (
        entry.get("title") or entry.get("content") or entry.get("desc") or entry.get("images_list")
    ):
        note = entry

    if not isinstance(note, dict):
        raise RuntimeError("Rnote 图文详情 API 未找到笔记详情字段")
    post = _rnote_profile_note_to_post(note)
    post["created_at"] = note.get("time") or note.get("create_time") or note.get("created_time") or ""
    return post


def _attach_profile_image_bytes(records: list, image_cols: int) -> dict:
    """Download images for profile collect rows before embedding into Feishu."""
    if not PROFILE_COLLECT_EMBED_IMAGES:
        return {"downloaded": 0, "records": 0}
    downloaded = 0
    records_with_images = 0
    max_images = max(1, int(image_cols or 1))
    for record in records or []:
        sources = record.get("image_items") or [
            {"url": url, "headers": {}}
            for url in (record.get("image_urls") or [])
        ]
        images = _download_images(sources, limit=max_images)
        if images:
            record["image_bytes_list"] = images
            downloaded += len(images)
            records_with_images += 1
    return {"downloaded": downloaded, "records": records_with_images}


def _fetch_profile_posts(profile_url: str, max_items: int) -> tuple:
    if _profile_collect_provider() == "rnote":
        return _fetch_rnote_profile_posts(profile_url, max_items)

    api_key = _get_meowload_api_key()
    cursor = None
    page = 1
    posts = []
    user_info = {}
    more_available = False
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "accept-language": "zh",
    }

    while len(posts) < max_items:
        payload = {"url": profile_url}
        if cursor:
            payload["cursor"] = cursor
        try:
            resp = requests.post(
                MEOWLOAD_API_URL,
                json=payload,
                headers=headers,
                timeout=45,
            )
        except requests.RequestException as e:
            raise HTTPException(
                status_code=502,
                detail=f"哼哼猫 API 请求失败：{e}",
            )
        try:
            data = resp.json()
        except Exception:
            raise HTTPException(
                status_code=502,
                detail=f"哼哼猫 API 返回非 JSON：HTTP {resp.status_code}",
            )
        if resp.status_code != 200:
            msg = data.get("message") or data.get("detail") or str(data)[:200]
            raise HTTPException(status_code=502, detail=f"哼哼猫 API 失败：{msg}")

        if isinstance(data.get("user"), dict) and data.get("user"):
            user_info = data["user"]
        page_posts = data.get("posts") or []
        if not isinstance(page_posts, list):
            raise HTTPException(status_code=502, detail="哼哼猫 API posts 字段异常")
        for post in page_posts:
            if len(posts) >= max_items:
                break
            if isinstance(post, dict):
                posts.append(post)

        more_available = bool(data.get("has_more"))
        if len(posts) >= max_items:
            break
        if not data.get("has_more"):
            more_available = False
            break
        cursor = data.get("next_cursor")
        if not cursor:
            more_available = False
            break
        page += 1
        if page > 1:
            time.sleep(PROFILE_COLLECT_REQUEST_DELAY)

    return posts, user_info, more_available


def _fetch_rnote_profile_posts(profile_url: str, max_items: int) -> tuple:
    user_id = _extract_xhs_profile_user_id(profile_url)
    if not user_id:
        raise HTTPException(
            status_code=400,
            detail="Rnote 需要账号主页里的用户 ID，请打开小红书账号主页后再采集",
        )
    cursor = ""
    posts = []
    more_available = False
    page_size = min(40, max(1, max_items))

    while len(posts) < max_items:
        payload = _rnote_get(
            "/api/v2/crawler/user/posted",
            {
                "user_id": user_id,
                "cursor": cursor,
                "num": page_size,
            },
            "用户笔记列表",
        )
        if not isinstance(payload, dict):
            raise HTTPException(status_code=502, detail="Rnote 用户笔记列表字段异常")
        notes = payload.get("notes") or []
        if not isinstance(notes, list):
            raise HTTPException(status_code=502, detail="Rnote notes 字段异常")
        for note in notes:
            if len(posts) >= max_items:
                break
            if isinstance(note, dict):
                posts.append(_rnote_profile_note_to_post(note))

        more_available = bool(payload.get("has_more"))
        if len(posts) >= max_items or not more_available:
            break
        next_cursor = ""
        for note in reversed(notes):
            if isinstance(note, dict):
                next_cursor = str(note.get("cursor") or note.get("id") or "").strip()
                if next_cursor:
                    break
        if not next_cursor or next_cursor == cursor:
            more_available = False
            break
        cursor = next_cursor
        if PROFILE_COLLECT_REQUEST_DELAY > 0:
            time.sleep(PROFILE_COLLECT_REQUEST_DELAY)

    return posts, {}, more_available


def _profile_posts_to_records(posts: list, profile_url: str,
                              account_name: str) -> list:
    records = []
    for post in posts:
        text = post.get("text") or post.get("desc") or post.get("caption") or ""
        post_url = post.get("post_url") or post.get("url") or ""
        image_items = _profile_media_items(post.get("medias") or [])
        image_urls = [item["url"] for item in image_items]
        records.append({
            "account_name": account_name,
            "profile_url": profile_url,
            "title": post.get("title") or _pick_profile_title(text, post.get("id", "")),
            "text": text,
            "post_url": post_url,
            "created_at": _format_profile_created_at(post.get("created_at", "")),
            "image_urls": image_urls,
            "image_items": image_items,
        })
    return records


def _fetch_note_post(note_url: str) -> dict:
    if _profile_collect_provider() == "rnote":
        return _fetch_rnote_note_post(note_url)

    api_key = _get_meowload_api_key()
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "accept-language": "zh",
    }
    try:
        resp = requests.post(
            MEOWLOAD_POST_API_URL,
            json={"url": note_url},
            headers=headers,
            timeout=45,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"哼哼猫单篇 API 请求失败：{e}") from e
    try:
        data = resp.json()
    except Exception as e:
        raise RuntimeError(
            f"哼哼猫单篇 API 返回非 JSON：HTTP {resp.status_code}"
        ) from e
    if resp.status_code != 200:
        msg = data.get("message") or data.get("detail") or str(data)[:200]
        raise RuntimeError(f"哼哼猫单篇 API 失败：{msg}")
    return data


def _fetch_rnote_note_post(note_url: str) -> dict:
    note_id = _xhs_note_id(note_url)
    if not note_id:
        raise RuntimeError("Rnote 单篇 API 需要笔记 ID，请确认链接是否为小红书笔记详情页")
    payload = _rnote_get(
        "/api/v2/crawler/note/image",
        {"note_id": note_id},
        "图文详情",
    )
    return _rnote_note_detail_to_post(payload)


def _is_non_retryable_meowload_error(error: Exception) -> bool:
    text = str(error)
    non_retryable_markers = (
        "API Key",
        "api key",
        "认证",
        "鉴权",
        "Authentication",
        "401",
        "余额",
        "次数",
        "Credits",
        "quota",
        "402",
        "参数",
        "422",
    )
    return any(marker in text for marker in non_retryable_markers)


def _fetch_note_post_with_retry(note_url: str) -> dict:
    attempts = max(1, int(PROFILE_COLLECT_POST_RETRY_ATTEMPTS or 1))
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            return _fetch_note_post(note_url)
        except Exception as e:
            errors.append(str(e)[:200])
            if attempt >= attempts or _is_non_retryable_meowload_error(e):
                break
            wait = max(0.0, PROFILE_COLLECT_POST_RETRY_DELAY * attempt)
            if PROFILE_COLLECT_POST_RETRY_JITTER > 0:
                wait += random.uniform(0, PROFILE_COLLECT_POST_RETRY_JITTER)
            print(
                "[profile_collect] post_api_retry "
                f"attempt={attempt + 1}/{attempts} wait={wait:.1f}s "
                f"error={str(e)[:120]}"
            )
            if wait > 0:
                time.sleep(wait)

    message = errors[-1] if errors else "未知错误"
    if len(errors) > 1:
        message = f"{message}（已重试 {len(errors) - 1} 次）"
    raise RuntimeError(message)


def _note_response_to_record(data: dict, note_url: str, profile_url: str,
                             account_name: str) -> dict:
    text = data.get("text") or data.get("desc") or data.get("caption") or ""
    note_id = data.get("id") or _xhs_note_id(note_url)
    image_items = _profile_media_items(data.get("medias") or [])
    image_urls = [item["url"] for item in image_items]
    return {
        "account_name": account_name,
        "profile_url": profile_url,
        "title": data.get("title") or _pick_profile_title(text, note_id),
        "text": text,
        "post_url": note_url,
        "created_at": _format_profile_created_at(data.get("created_at", "")),
        "liked_count": data.get("liked_count") or data.get("liked") or 0,
        "collected_count": data.get("collected_count") or data.get("collected") or 0,
        "comments_count": data.get("comments_count") or data.get("comment") or 0,
        "shared_count": data.get("shared_count") or data.get("share") or 0,
        "image_urls": image_urls,
        "image_items": image_items,
    }


def _task_update(task_id: str, **updates) -> None:
    with PROFILE_COLLECT_TASKS_LOCK:
        task = PROFILE_COLLECT_TASKS.get(task_id)
        if not task:
            return
        task.update(updates)
        task["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _task_snapshot(task_id: str) -> Optional[dict]:
    with PROFILE_COLLECT_TASKS_LOCK:
        task = PROFILE_COLLECT_TASKS.get(task_id)
        return dict(task) if task else None


def _append_profile_record_immediately(task_id: str, spreadsheet_token: str,
                                       account_name: str, record: dict,
                                       source: str,
                                       sheet_info: Optional[dict]) -> tuple:
    """API 成功一条就立刻写入飞书，避免长任务中断后丢数据。"""
    image_cols = max(1, PROFILE_COLLECT_MAX_IMAGE_COLS)
    if not sheet_info:
        _task_update(
            task_id,
            phase="feishu_prepare",
            message="已有 API 成功结果，正在创建或检查飞书表",
        )
        sheet_info = writer.ensure_profile_collect_sheet(
            spreadsheet_token, account_name, image_cols=image_cols,
        )
    sheet_url = (
        f"https://my.feishu.cn/sheets/{spreadsheet_token}"
        f"?sheet={sheet_info['sheet_id']}"
    )
    _task_update(
        task_id,
        phase="feishu_write",
        message=f"正在下载图片并保存到「{sheet_info['title']}」",
        sheet_title=sheet_info["title"],
        sheet_id=sheet_info["sheet_id"],
        sheet_url=sheet_url,
        created_sheet=sheet_info["created"],
    )
    image_download = _attach_profile_image_bytes([record], image_cols)
    result = writer.append_profile_collect_records(
        spreadsheet_token,
        sheet_info["sheet_id"],
        [record],
        source=source,
        image_cols=image_cols,
    )
    result["image_downloaded"] = image_download.get("downloaded", 0)
    return sheet_info, result, sheet_url


def _append_profile_records(task_id: str, spreadsheet_token: str,
                            account_name: str, records: list,
                            source: str) -> tuple:
    """一次写入主页批量接口返回的记录。"""
    image_cols = max(1, PROFILE_COLLECT_MAX_IMAGE_COLS)
    _task_update(
        task_id,
        phase="feishu_prepare",
        message="主页批量接口已有结果，正在创建或检查飞书表",
    )
    sheet_info = writer.ensure_profile_collect_sheet(
        spreadsheet_token,
        account_name,
        image_cols=image_cols,
    )
    sheet_url = (
        f"https://my.feishu.cn/sheets/{spreadsheet_token}"
        f"?sheet={sheet_info['sheet_id']}"
    )
    _task_update(
        task_id,
        phase="feishu_write",
        message=f"正在下载图片并保存到「{sheet_info['title']}」",
        sheet_title=sheet_info["title"],
        sheet_id=sheet_info["sheet_id"],
        sheet_url=sheet_url,
        created_sheet=sheet_info["created"],
    )
    image_download = _attach_profile_image_bytes(records, image_cols)
    result = writer.append_profile_collect_records(
        spreadsheet_token,
        sheet_info["sheet_id"],
        records,
        source=source,
        image_cols=image_cols,
    )
    result["image_downloaded"] = image_download.get("downloaded", 0)
    return sheet_info, result, sheet_url


def _run_profile_collect_task(task_id: str, spreadsheet_token: str,
                              profile_url: str, account_name: str,
                              note_urls: list, source: str) -> None:
    failures = []
    failure_rows = []
    sheet_info = None
    sheet_url = ""
    success_count = 0
    written_total = 0
    skipped_total = 0
    failed_saved = 0
    retry_processed = 0
    retry_success = 0
    retry_failed = 0
    total = len(note_urls)
    print(f"[profile_collect] task={task_id} start total={total} account={account_name}")
    _task_update(
        task_id,
        status="running",
        phase="api_extract",
        message="服务器已开始逐篇调用 API，失败会自动重试",
        total=total,
    )
    for idx, note_url in enumerate(note_urls, start=1):
        try:
            data = _fetch_note_post_with_retry(note_url)
            record = _note_response_to_record(
                data, note_url, profile_url, account_name,
            )
            sheet_info, result, sheet_url = _append_profile_record_immediately(
                task_id,
                spreadsheet_token,
                account_name,
                record,
                source,
                sheet_info,
            )
            success_count += 1
            written_total += int(result.get("written") or 0)
            skipped_total += int(result.get("skipped") or 0)
        except Exception as e:
            failures.append({
                "url": note_url,
                "error": str(e)[:200],
            })
        _task_update(
            task_id,
            processed=idx,
            success=success_count,
            failed=len(failures),
            failed_examples=failures[:20],
            failed_details=failures,
            written=written_total,
            skipped=skipped_total,
            partial_saved=written_total + skipped_total,
            failed_saved=failed_saved,
            retry_total=0,
            retry_processed=0,
            retry_success=0,
            retry_failed=0,
            phase="api_extract",
            message=f"正在调用 API：{idx}/{total}，已保存 {written_total + skipped_total} 条",
        )
        if idx < total and PROFILE_COLLECT_REQUEST_DELAY > 0:
            time.sleep(PROFILE_COLLECT_REQUEST_DELAY)

    try:
        image_cols = max(1, PROFILE_COLLECT_MAX_IMAGE_COLS)
        if failures:
            if not sheet_info:
                _task_update(
                    task_id,
                    phase="feishu_prepare",
                    message="没有 API 成功结果，正在创建飞书表保存失败链接",
                )
                sheet_info = writer.ensure_profile_collect_sheet(
                    spreadsheet_token, account_name, image_cols=image_cols,
                )
                sheet_url = (
                    f"https://my.feishu.cn/sheets/{spreadsheet_token}"
                    f"?sheet={sheet_info['sheet_id']}"
                )
            _task_update(
                task_id,
                phase="feishu_write",
                message=f"正在把 {len(failures)} 条失败链接保存到「{sheet_info['title']}」",
                sheet_title=sheet_info["title"],
                sheet_id=sheet_info["sheet_id"],
                sheet_url=sheet_url,
                created_sheet=sheet_info["created"],
            )
            for failure in failures:
                result = writer.append_profile_collect_failure(
                    spreadsheet_token,
                    sheet_info["sheet_id"],
                    failure,
                    account_name,
                    profile_url,
                    source=source,
                    image_cols=image_cols,
                )
                saved_failure = dict(failure)
                saved_failure["row"] = result["row"]
                saved_failure["seq"] = result["seq"]
                failure_rows.append(saved_failure)
                failed_saved += int(result.get("written") or 0)
            _task_update(
                task_id,
                failed_saved=failed_saved,
                partial_saved=written_total + skipped_total + len(failure_rows),
                failed=len(failure_rows),
                failed_examples=failure_rows[:20],
                failed_details=failure_rows,
                message=f"失败链接已落表 {failed_saved} 条，准备自动补采",
            )

        remaining_failures = list(failure_rows)
        if failure_rows:
            retry_total = len(failure_rows)
            _task_update(
                task_id,
                phase="retry_failed_rows",
                retry_total=retry_total,
                retry_processed=0,
                retry_success=0,
                retry_failed=0,
                message=f"正在自动补采失败笔记：0/{retry_total}",
            )
            remaining_failures = []
            for failure in failure_rows:
                retry_processed += 1
                try:
                    data = _fetch_note_post_with_retry(failure["url"])
                    record = _note_response_to_record(
                        data, failure["url"], profile_url, account_name,
                    )
                    image_download = _attach_profile_image_bytes(
                        [record], image_cols,
                    )
                    result = writer.overwrite_profile_collect_record(
                        spreadsheet_token,
                        sheet_info["sheet_id"],
                        failure["row"],
                        failure["seq"],
                        record,
                        source=f"{source}-失败补采",
                        image_cols=image_cols,
                    )
                    result["image_downloaded"] = image_download.get("downloaded", 0)
                    success_count += 1
                    retry_success += 1
                    written_total += int(result.get("written") or 0)
                except Exception as e:
                    retry_failed += 1
                    updated_failure = dict(failure)
                    updated_failure["error"] = f"补采仍失败：{str(e)[:180]}"
                    writer.overwrite_profile_collect_failure(
                        spreadsheet_token,
                        sheet_info["sheet_id"],
                        failure["row"],
                        failure["seq"],
                        updated_failure,
                        account_name,
                        profile_url,
                        source=f"{source}-失败补采",
                        image_cols=image_cols,
                    )
                    remaining_failures.append(updated_failure)

                still_failed = retry_total - retry_success
                _task_update(
                    task_id,
                    phase="retry_failed_rows",
                    processed=total,
                    success=success_count,
                    failed=still_failed,
                    written=written_total,
                    skipped=skipped_total,
                    partial_saved=written_total + skipped_total + still_failed,
                    retry_total=retry_total,
                    retry_processed=retry_processed,
                    retry_success=retry_success,
                    retry_failed=retry_failed,
                    failed_examples=remaining_failures[:20],
                    failed_details=remaining_failures,
                    message=(
                        f"正在自动补采失败笔记：{retry_processed}/{retry_total}，"
                        f"补采成功 {retry_success} 条，仍失败 {still_failed} 条"
                    ),
                )
                if (retry_processed < retry_total and
                        PROFILE_COLLECT_REQUEST_DELAY > 0):
                    time.sleep(PROFILE_COLLECT_REQUEST_DELAY)

        final_failed = len(remaining_failures)
        if sheet_info:
            _task_update(
                task_id,
                status="done",
                phase="done",
                message=(
                    "已写入飞书表"
                    if final_failed == 0 else
                    f"已写入飞书表，仍有 {final_failed} 条失败链接已保留"
                ),
                sheet_title=sheet_info["title"],
                sheet_id=sheet_info["sheet_id"],
                sheet_url=sheet_url,
                created_sheet=sheet_info["created"],
                fetched=success_count,
                written=written_total,
                skipped=skipped_total,
                failed=final_failed,
                failed_examples=remaining_failures[:20],
                failed_details=remaining_failures,
                failed_saved=failed_saved,
                retry_total=len(failure_rows),
                retry_processed=retry_processed,
                retry_success=retry_success,
                retry_failed=retry_failed,
                partial_saved=written_total + skipped_total + final_failed,
                image_columns=PROFILE_COLLECT_MAX_IMAGE_COLS,
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            print(
                f"[profile_collect] task={task_id} done "
                f"success={success_count} failed={final_failed} "
                f"written={written_total} skipped={skipped_total} "
                f"failed_saved={failed_saved} retry_success={retry_success}"
            )
        else:
            _task_update(
                task_id,
                status="failed",
                phase="failed",
                error="全部笔记都采集失败，请确认主页链接已加载出完整笔记链接",
                message="API 提取阶段全部失败，未创建飞书表",
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            print(f"[profile_collect] task={task_id} failed all api failed")
    except Exception as e:
        _task_update(
            task_id,
            status="failed",
            phase="failed",
            error=f"写入飞书失败：{e}",
            message="飞书创建或写入阶段失败",
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        print(f"[profile_collect] task={task_id} feishu_failed {e}")


def _run_profile_collect_playlist_task(task_id: str, spreadsheet_token: str,
                                       profile_url: str, account_name: str,
                                       max_items: int, source: str) -> None:
    print(
        f"[profile_collect] task={task_id} playlist start "
        f"max={max_items} account={account_name}"
    )
    _task_update(
        task_id,
        status="running",
        phase="playlist_extract",
        message="服务器已开始调用主页批量接口",
        total=max_items,
    )
    try:
        if _profile_collect_provider() == "rnote":
            posts, user_info, more_available = _fetch_profile_posts(
                profile_url,
                max_items,
            )
            resolved_account_name = (
                account_name or
                (user_info or {}).get("username") or
                (user_info or {}).get("nickname") or
                "小红书账号"
            )
            note_urls = [
                post.get("post_url")
                for post in posts
                if isinstance(post, dict) and post.get("post_url")
            ]
            _task_update(
                task_id,
                collect_mode="rnote_user_posted_then_detail",
                total=len(note_urls),
                processed=0,
                success=0,
                failed=0,
                more_available=more_available,
                message=(
                    f"Rnote 已返回 {len(note_urls)} 条笔记，"
                    "正在逐篇提取图文详情"
                ),
            )
            if not note_urls:
                _task_update(
                    task_id,
                    status="failed",
                    phase="failed",
                    error="Rnote 用户笔记列表没有返回可采集笔记",
                    message="Rnote 用户笔记列表没有返回可采集笔记，未创建飞书表",
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
                return
            _run_profile_collect_task(
                task_id,
                spreadsheet_token,
                profile_url,
                resolved_account_name,
                note_urls,
                source,
            )
            _task_update(task_id, more_available=more_available)
            return

        posts, user_info, more_available = _fetch_profile_posts(
            profile_url,
            max_items,
        )
        resolved_account_name = (
            account_name or
            (user_info or {}).get("username") or
            (user_info or {}).get("nickname") or
            "小红书账号"
        )
        records = _profile_posts_to_records(
            posts,
            profile_url,
            resolved_account_name,
        )
        _task_update(
            task_id,
            total=len(records),
            processed=0,
            success=0,
            failed=0,
            message=f"主页批量接口已返回 {len(records)} 条，正在写入飞书",
        )
        if not records:
            _task_update(
                task_id,
                status="failed",
                phase="failed",
                error="主页批量接口没有返回笔记，请确认账号主页链接可访问",
                message="主页批量接口没有返回笔记，未创建飞书表",
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            return
        sheet_info, result, sheet_url = _append_profile_records(
            task_id,
            spreadsheet_token,
            resolved_account_name,
            records,
            source,
        )
        written_total = int(result.get("written") or 0)
        skipped_total = int(result.get("skipped") or 0)
        _task_update(
            task_id,
            status="done",
            phase="done",
            message="已通过主页批量接口写入飞书表",
            sheet_title=sheet_info["title"],
            sheet_id=sheet_info["sheet_id"],
            sheet_url=sheet_url,
            created_sheet=sheet_info["created"],
            fetched=len(records),
            total=len(records),
            processed=len(records),
            success=len(records),
            failed=0,
            written=written_total,
            skipped=skipped_total,
            partial_saved=written_total + skipped_total,
            more_available=more_available,
            image_columns=PROFILE_COLLECT_MAX_IMAGE_COLS,
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        print(
            f"[profile_collect] task={task_id} playlist done "
            f"records={len(records)} written={written_total} skipped={skipped_total}"
        )
    except Exception as e:
        _task_update(
            task_id,
            status="failed",
            phase="failed",
            error=str(e)[:300],
            message="主页批量接口调用失败，未创建飞书表",
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        print(f"[profile_collect] task={task_id} playlist_failed {e}")


def _process_one(user: dict, url: str, note: str, tags: list,
                 source: str, sheet_id: Optional[str] = None,
                 dup_strategy: str = "skip") -> dict:
    """单条采集+写入。

    dup_strategy:
      - "skip"（默认）：发现已存在直接跳过
      - "update"：找到已有行，更新互动数（点赞/收藏/评论/分享/采集时间）
      - "always_new"：不去重，永远新增一行
    """
    ss_token = user["spreadsheet_token"]
    target_sheet = sheet_id or user["default_sheet_id"]
    if not target_sheet:
        return {"status": "failed", "url": url,
                "error": "用户没有配置 default_sheet_id 也未指定 sheet_id"}

    data = collect_one(url)
    if not data.get("url"):
        data["url"] = url
    note_id = data.get("note_id") or ""

    # 跨 sheet 去重（按策略决定后续动作）
    if note_id and dup_strategy != "always_new":
        existing = writer.find_row_across_sheets(ss_token, note_id)
        if existing:
            if dup_strategy == "update" and data["status"] == "ok":
                # 更新：D 标题、F 文案、G-J 三数+分享、L 采集时间
                # 不动 A 序号、B 链接、C 状态、E 封面图、K 笔记ID、M 来源、N 备注
                row_idx = existing["row"]
                ex_sheet = existing["sheet_id"]
                try:
                    # D 标题
                    writer.write_range(
                        ss_token, ex_sheet,
                        f"D{row_idx}:D{row_idx}",
                        [[data.get("title", "")]],
                    )
                    # F 文案 + O 话题标签 — v4.3.6 B037：extract hashtag 拆到 O 列
                    _clean_desc, _hashtags = extract_hashtags(flatten_desc(data.get("desc", "")))
                    writer.write_range(
                        ss_token, ex_sheet,
                        f"F{row_idx}:F{row_idx}",
                        [[_clean_desc]],
                    )
                    writer.write_range(
                        ss_token, ex_sheet,
                        f"O{row_idx}:O{row_idx}",
                        [[_hashtags]],
                    )
                    # G-L 三数+分享+笔记ID+时间
                    writer.write_range(
                        ss_token, ex_sheet,
                        f"G{row_idx}:L{row_idx}",
                        [[
                            data.get("liked", 0),
                            data.get("collected", 0),
                            data.get("comment", 0),
                            data.get("share", 0),
                            data.get("note_id", ""),
                            datetime.now().strftime("%Y-%m-%d %H:%M"),
                        ]],
                    )
                    writer.invalidate_cache(ss_token)
                    return {
                        "status": "updated",
                        "note_id": note_id,
                        "title": data.get("title", ""),
                        "row": row_idx,
                        "sheet_title": existing["sheet_title"],
                        "liked": data.get("liked"),
                        "collected": data.get("collected"),
                        "comment": data.get("comment"),
                        "share": data.get("share"),
                    }
                except Exception as e:
                    return {"status": "failed", "url": url,
                            "error": f"更新已有行失败: {e}"}
            return {
                "status": "duplicate",
                "note_id": note_id,
                "title": data.get("title", ""),
                "original_row": existing["row"],
                "original_sheet_title": existing["sheet_title"],
            }

    # 找目标 sheet 的下一空行
    existing_ids, next_row, max_seq = writer.load_existing_ids_and_next_row(
        ss_token, target_sheet,
    )

    if data["status"] == "ok":
        save_all_images = _sheet_saves_all_images(ss_token, target_sheet)
        img, image_list = _prepare_images(data, save_all_images)
        res = writer.write_record(
            spreadsheet_token=ss_token,
            sheet_id=target_sheet,
            row_idx=next_row,
            seq=max_seq + 1,
            data=data,
            source=source,
            note=note,
            tags=tags or [],
            image_bytes=img,
            image_bytes_list=image_list,
        )
        writer.invalidate_cache(ss_token)
        return {
            "status": "ok",
            "row": next_row,
            "sheet_id": target_sheet,
            "note_id": note_id,
            "title": data.get("title", ""),
            "liked": data.get("liked"),
            "collected": data.get("collected"),
            "comment": data.get("comment"),
            "share": data.get("share"),
            "cover_status": res["cover"],
        }
    else:
        writer.write_failure(
            spreadsheet_token=ss_token,
            sheet_id=target_sheet,
            row_idx=next_row,
            seq=max_seq + 1,
            url=data.get("url", url),
            error=data.get("error", ""),
            source=source,
            note=note,
        )
        writer.invalidate_cache(ss_token)
        return {
            "status": "failed",
            "row": next_row,
            "sheet_id": target_sheet,
            "url": url,
            "error": data.get("error", ""),
        }


# ---------- 路由 ----------

@app.get("/api/health")
def health():
    return {"ok": True, "ts": int(time.time()), "version": app.version,
            "legacy_users_count": len(LEGACY_TOKEN_TO_USER),
            "sqlite_users_count": len(db.list_users())}


# ---------- changelog（无需鉴权）----------

@app.get("/api/changelog")
def get_changelog(limit: int = Query(20, ge=1, le=100)):
    """更新日志列表（无需鉴权，未登录用户也能看）。

    按 released_at DESC 排序，最新版在最前。
    返回 current_latest 字段给扩展端做"有无新版本"对比。
    """
    items = db.list_changelogs(limit=limit)
    current_latest = items[0]["version"] if items else None
    return {
        "current_latest": current_latest,
        "items": items,
    }


class ChangelogCreateRequest(BaseModel):
    version: str
    version_type: str  # "major" | "minor" | "patch"
    title: str
    details: str
    released_at: Optional[str] = None  # ISO 日期，缺省今天


@app.post("/api/admin/changelog")
def admin_create_changelog(req: ChangelogCreateRequest,
                            admin: dict = Depends(auth.require_admin)):
    """admin 添加/更新一条 changelog（已存在的 version 会被覆盖）。"""
    version = (req.version or "").strip()
    if not version:
        raise HTTPException(status_code=400, detail="version 不能为空")
    if req.version_type not in ("major", "minor", "patch"):
        raise HTTPException(
            status_code=400,
            detail="version_type 必须是 major/minor/patch",
        )
    title = (req.title or "").strip()
    details = (req.details or "").strip()
    if not title or not details:
        raise HTTPException(status_code=400, detail="title 和 details 不能为空")
    try:
        db.insert_changelog(
            version=version,
            version_type=req.version_type,
            title=title,
            details=details,
            released_at=(req.released_at or None),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "version": version}


@app.get("/api/whoami")
def whoami(authorization: Optional[str] = Header(None),
x_auth_token: Optional[str] = Header(None)):
    """让扩展知道自己是哪个用户（用于 popup 顶部显示用户名）。

    v3.1.1：不再返回 spreadsheet_token；返回 sheet_url 供扩展打开飞书表。
    """
    user = auth.require_active_with_sheet(authorization, x_auth_token)
    return {
        "user_id": user["user_id"],
        "name": user["name"],
        "sheet_url": f"https://my.feishu.cn/sheets/{user['spreadsheet_token']}",
    }


@app.get("/api/sheets")
def list_sheets(authorization: Optional[str] = Header(None),
x_auth_token: Optional[str] = Header(None)):
    """列出当前用户飞书表里的所有 sheet（供 popup 分类下拉用）。"""
    user = auth.require_active_with_sheet(authorization, x_auth_token)
    try:
        sheets = [
            sheet for sheet in writer.get_sheets_info(user["spreadsheet_token"])
            if _is_note_category_sheet(sheet.get("title", ""))
        ]
        default_sheet_id = user["default_sheet_id"]
        if sheets and not any(s["sheet_id"] == default_sheet_id for s in sheets):
            default_sheet_id = sheets[0]["sheet_id"]
        return {"sheets": sheets,
                "default_sheet_id": default_sheet_id}
    except (LarkAuthError, LarkAPIError) as e:
        raise HTTPException(status_code=502, detail=str(e))


class CategoryCreateRequest(BaseModel):
    title: str  # 分类名 / sheet 名


@app.post("/api/categories")
def create_category(req: CategoryCreateRequest,
authorization: Optional[str] = Header(None),
                    x_auth_token: Optional[str] = Header(None)):
    """新建一个分类：在用户飞书表里新增一个 sheet + 应用模板。"""
    user = auth.require_active_with_sheet(authorization, x_auth_token)
    title = (req.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="分类名不能为空")
    if len(title) > 30:
        raise HTTPException(status_code=400, detail="分类名最多 30 字")
    # 检查重名 + 数量上限（飞书单表 200 sheet 上限）
    try:
        sheets = writer.get_sheets_info(user["spreadsheet_token"],
                                         use_cache=False)
        if len(sheets) >= 200:
            raise HTTPException(
                status_code=400,
                detail=f"飞书单表最多 200 个 sheet，当前已有 {len(sheets)} 个，请先删一些再加",
            )
        if any(s["title"] == title for s in sheets):
            raise HTTPException(status_code=409,
                                detail=f"已有同名分类「{title}」")
        new_sheet = writer.create_sheet(user["spreadsheet_token"], title)
        # 应用模板
        writer.setup_sheet_template(user["spreadsheet_token"],
                                    new_sheet["sheet_id"])
        writer.invalidate_cache(user["spreadsheet_token"])
        return {
            "status": "ok",
            "sheet_id": new_sheet["sheet_id"],
            "title": new_sheet["title"],
            "index": new_sheet["index"],
        }
    except HTTPException:
        raise
    except (LarkAuthError, LarkAPIError) as e:
        raise HTTPException(status_code=502, detail=str(e))


# ============ 对标账号库（v4.4.0 新增）============

class AccountLibAddRequest(BaseModel):
    account_type: str          # "潜力店铺" / "爆款跟品"
    account_name: str          # 必填
    profile_url: str           # 必填，用于跨 sheet 去重
    xhs_id: Optional[str] = ""
    notes_count: Optional[str] = ""
    fans_count: Optional[str] = ""
    likes_count: Optional[str] = ""
    ip_location: Optional[str] = ""
    bio: Optional[str] = ""
    note: Optional[str] = ""         # 备注（用户手填）


@app.post("/api/account-lib/add")
def account_lib_add(req: AccountLibAddRequest,
                    authorization: Optional[str] = Header(None),
                    x_auth_token: Optional[str] = Header(None)):
    """把对标账号写入用户的飞书账号库 sheet。

    流程：
    1. 校验用户已绑表 + active
    2. 校验 account_type 合法
    3. ensure 3 个账号库 sheet 都存在（缺则自建+套模板）
    4. 跨 3 个 sheet 查重 profile_url（归一化比对）
    5. 若已存在 → 返回 {duplicate:true, existing_sheet, existing_row}（不写入）
    6. 否则写入对应 sheet，返回新行号
    """
    user = auth.require_active_with_sheet(authorization, x_auth_token)

    # 校验 account_type
    if req.account_type not in writer.ACCOUNT_LIB_SHEETS:
        raise HTTPException(
            status_code=400,
            detail=f"account_type 必须是：{list(writer.ACCOUNT_LIB_SHEETS)}",
        )

    # 校验必填
    account_name = (req.account_name or "").strip()
    profile_url = (req.profile_url or "").strip()
    if not account_name:
        raise HTTPException(status_code=400, detail="账号名不能为空")
    if not profile_url:
        raise HTTPException(status_code=400, detail="主页 URL 不能为空")
    if not (profile_url.startswith("http://") or
            profile_url.startswith("https://")):
        raise HTTPException(status_code=400,
                            detail="主页 URL 必须以 http:// 或 https:// 开头")

    token = user["spreadsheet_token"]

    try:
        # ensure 3 sheet 存在 + 跨 sheet 查重
        existing = writer.check_account_exists_in_lib(token, profile_url)
        if existing:
            existing_title, existing_row = existing
            return {
                "ok": True,
                "duplicate": True,
                "message": f"已在「{existing_title}」第 {existing_row} 行",
                "existing_sheet": existing_title,
                "existing_row": existing_row,
            }

        # 写入对应 sheet
        new_row = writer.append_account_to_lib(
            token, req.account_type,
            {
                "account_name": account_name,
                "profile_url": profile_url,
                "xhs_id": req.xhs_id or "",
                "notes_count": req.notes_count or "",
                "fans_count": req.fans_count or "",
                "likes_count": req.likes_count or "",
                "ip_location": req.ip_location or "",
                "bio": req.bio or "",
                "note": req.note or "",
            },
        )
        return {
            "ok": True,
            "duplicate": False,
            "sheet_title": req.account_type,
            "row": new_row,
        }
    except HTTPException:
        raise
    except (LarkAuthError, LarkAPIError) as e:
        raise HTTPException(status_code=502, detail=f"飞书 API 失败：{e}")


@app.get("/api/account-lib/meta")
def account_lib_meta():
    """返回扩展前端表单需要的预设值（让前端不用硬编码 = 同步一处改）。"""
    return {
        "account_types": list(writer.ACCOUNT_LIB_SHEETS),
    }


@app.post("/api/profile-collect")
def profile_collect(req: ProfileCollectRequest,
                    authorization: Optional[str] = Header(None),
                    x_auth_token: Optional[str] = Header(None)):
    """账号主页整店采集：标题 / 文案 / 话题标签 / 图片下载链接。

    v4.7.0：前端拿到完整笔记链接时逐篇调用单篇接口并逐条落表；
    没拿到完整链接时才尝试哼哼猫主页批量接口兜底。
    """
    user = auth.require_active_with_sheet(authorization, x_auth_token)
    profile_url = _validate_xhs_profile_url(req.profile_url)

    try:
        requested_max = int(req.max_items or PROFILE_COLLECT_MAX_ITEMS)
    except Exception:
        raise HTTPException(status_code=400, detail="max_items 必须是数字")
    if requested_max < 1:
        raise HTTPException(status_code=400, detail="max_items 必须大于 0")
    max_items = min(requested_max, PROFILE_COLLECT_MAX_ITEMS)

    account_name = (req.account_name or "").strip()
    if not account_name:
        account_name = "小红书账号"
    note = (req.note or "").strip()
    note_urls = _dedupe_note_urls(req.note_urls or [], max_items)
    api_ready_note_urls = [
        url for url in note_urls
        if "xsec_token=" in url
    ]
    provider = _profile_collect_provider()
    use_single_post_api = bool(api_ready_note_urls)
    collect_mode = (
        "single_post"
        if use_single_post_api else
        "rnote_user_posted_then_detail" if provider == "rnote" else
        "playlist"
    )

    task_id = uuid.uuid4().hex
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with PROFILE_COLLECT_TASKS_LOCK:
        PROFILE_COLLECT_TASKS[task_id] = {
            "ok": True,
            "task_id": task_id,
            "user_id": user["user_id"],
            "status": "queued",
            "phase": "queued",
            "message": (
                "服务器已收到完整笔记链接，等待逐篇调用单篇 API"
                if use_single_post_api else
                "服务器将通过 Rnote 先取账号笔记列表，再逐篇提取图文详情"
                if provider == "rnote" else
                "服务器未收到完整笔记链接，等待尝试主页批量接口"
            ),
            "collect_mode": collect_mode,
            "account_name": account_name,
            "note": note,
            "profile_url": profile_url,
            "total": len(api_ready_note_urls) if use_single_post_api else max_items,
            "processed": 0,
            "success": 0,
            "failed": 0,
            "failed_examples": [],
            "failed_details": [],
            "failed_saved": 0,
            "retry_total": 0,
            "retry_processed": 0,
            "retry_success": 0,
            "retry_failed": 0,
            "written": 0,
            "skipped": 0,
            "partial_saved": 0,
            "created_at": now,
            "updated_at": now,
        }
    if use_single_post_api:
        worker = threading.Thread(
            target=_run_profile_collect_task,
            args=(
                task_id,
                user["spreadsheet_token"],
                profile_url,
                account_name,
                api_ready_note_urls,
                req.source or "账号全采集",
            ),
            daemon=True,
        )
    else:
        worker = threading.Thread(
            target=_run_profile_collect_playlist_task,
            args=(
                task_id,
                user["spreadsheet_token"],
                profile_url,
                account_name,
                max_items,
                req.source or "账号全采集",
            ),
            daemon=True,
        )
    worker.start()
    task = _task_snapshot(task_id) or {}
    task.pop("user_id", None)
    return task


@app.get("/api/profile-collect/tasks/{task_id}")
def profile_collect_task(task_id: str,
                         authorization: Optional[str] = Header(None),
                         x_auth_token: Optional[str] = Header(None)):
    user = auth.require_active_with_sheet(authorization, x_auth_token)
    task = _task_snapshot(task_id)
    if not task or task.get("user_id") != user["user_id"]:
        raise HTTPException(status_code=404, detail="采集任务不存在")
    task.pop("user_id", None)
    return task


@app.get("/api/failures")
def failures(authorization: Optional[str] = Header(None),
x_auth_token: Optional[str] = Header(None)):
    """获取当前用户表里所有失败行。"""
    user = auth.require_active_with_sheet(authorization, x_auth_token)
    try:
        return {"failures": writer.load_failures(user["spreadsheet_token"])}
    except (LarkAuthError, LarkAPIError) as e:
        raise HTTPException(status_code=502, detail=str(e))


class RetryRequest(BaseModel):
    sheet_id: str
    row: int
    dup_strategy: Optional[str] = "skip"


@app.post("/api/retry")
def retry(req: RetryRequest,
authorization: Optional[str] = Header(None),
          x_auth_token: Optional[str] = Header(None)):
    """重试某一条失败的笔记。从 B 列读 URL，重新采集 + 覆盖原行。"""
    user = auth.require_active_with_sheet(authorization, x_auth_token)
    ss_token = user["spreadsheet_token"]
    try:
        url = writer.retry_failure(ss_token, req.sheet_id, req.row)
        if not url:
            raise HTTPException(status_code=400, detail="原行没有有效 URL")
        # 重新采集
        data = collect_one(url)
        if not data.get("url"):
            data["url"] = url
        note_id = data.get("note_id") or ""
        # 强制刷新缓存，防止误把 retry 行自己当成 existing
        writer.invalidate_cache(ss_token)
        # 找已有的（跳过 retry 行自己）
        if note_id:
            existing = writer.find_row_across_sheets(ss_token, note_id)
            if existing and not (existing["sheet_id"] == req.sheet_id and
                                  existing["row"] == req.row):
                # 该笔记已在别处成功收录，清空当前失败行 A-N（视为重复，无需保留）
                try:
                    writer.write_range(
                        ss_token, req.sheet_id,
                        f"A{req.row}:{LAST_COL_LETTER}{req.row}",
                        [[""] * NOTE_TOTAL_COLS],
                    )
                except Exception:
                    pass
                writer.invalidate_cache(ss_token)
                return {
                    "status": "duplicate",
                    "note_id": note_id,
                    "title": data.get("title", ""),
                    "original_row": existing["row"],
                    "original_sheet_title": existing["sheet_title"],
                    "cleaned_row": req.row,
                }
        # 覆盖原行
        rows = writer.read_range(ss_token, req.sheet_id,
                                  f"A{req.row}:A{req.row}")
        seq = 0
        if rows and rows[0]:
            v = rows[0][0]
            if isinstance(v, (int, float)):
                seq = int(v)
        if not seq:
            _, _, seq = writer.load_existing_ids_and_next_row(
                ss_token, req.sheet_id,
            )
            seq += 1
        if data["status"] == "ok":
            save_all_images = _sheet_saves_all_images(ss_token, req.sheet_id)
            img, image_list = _prepare_images(data, save_all_images)
            res = writer.write_record(
                spreadsheet_token=ss_token,
                sheet_id=req.sheet_id,
                row_idx=req.row,
                seq=seq,
                data=data,
                source="Retry",
                image_bytes=img,
                image_bytes_list=image_list,
            )
            writer.invalidate_cache(ss_token)
            return {
                "status": "ok",
                "row": req.row,
                "sheet_id": req.sheet_id,
                "title": data.get("title", ""),
                "liked": data.get("liked"),
                "collected": data.get("collected"),
            }
        else:
            writer.write_failure(
                spreadsheet_token=ss_token,
                sheet_id=req.sheet_id,
                row_idx=req.row,
                seq=seq,
                url=url,
                error=data.get("error", ""),
                source="Retry",
            )
            writer.invalidate_cache(ss_token)
            return {"status": "failed", "row": req.row,
                    "error": data.get("error", "")}
    except HTTPException:
        raise
    except (LarkAuthError, LarkAPIError) as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/dashboard")
def dashboard(limit: int = Query(5, ge=1, le=50),
authorization: Optional[str] = Header(None),
              x_auth_token: Optional[str] = Header(None)):
    """返回当前用户的统计数据 + 最近 N 条记录。"""
    user = auth.require_active_with_sheet(authorization, x_auth_token)
    try:
        return writer.load_dashboard(user["spreadsheet_token"], recent_limit=limit)
    except (LarkAuthError, LarkAPIError) as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/shop-products/collect")
def shop_products_collect(req: ShopProductsCollectRequest,
authorization: Optional[str] = Header(None),
                          x_auth_token: Optional[str] = Header(None)):
    """把插件提取到的店铺商品写入专用「店铺商品提取」sheet。"""
    user = auth.require_active_with_sheet(authorization, x_auth_token)
    products = req.products or []
    if not products:
        raise HTTPException(status_code=400, detail="没有可写入的店铺商品")
    try:
        return {
            "status": "ok",
            **writer.append_shop_products(
                user["spreadsheet_token"],
                req.shop_info or {},
                products,
                source=req.source or "店铺商品提取",
                remark=req.remark or "",
            ),
        }
    except (LarkAuthError, LarkAPIError) as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.delete("/api/categories/{sheet_id}")
def delete_category(sheet_id: str,
authorization: Optional[str] = Header(None),
                    x_auth_token: Optional[str] = Header(None)):
    """删除一个分类（连同 sheet 一起删，慎用）。"""
    user = auth.require_active_with_sheet(authorization, x_auth_token)
    # 保护 default_sheet_id
    if sheet_id == user["default_sheet_id"]:
        raise HTTPException(status_code=400,
                            detail="不能删除默认分类（你的「总库」）")
    try:
        writer.delete_sheet(user["spreadsheet_token"], sheet_id)
        writer.invalidate_cache(user["spreadsheet_token"])
        return {"status": "ok", "deleted_sheet_id": sheet_id}
    except LarkAPIError as e:
        # 飞书 sheet_id 不存在错误码 90215 → 转为 404
        if "90215" in str(e) or "not exist" in str(e):
            raise HTTPException(status_code=404,
                                detail=f"分类 sheet_id={sheet_id} 不存在")
        raise HTTPException(status_code=502, detail=str(e))
    except LarkAuthError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/check")
def check(url: str = Query(...),
authorization: Optional[str] = Header(None),
          x_auth_token: Optional[str] = Header(None)):
    """快速检测笔记是否已存在（跨所有 sheet 查）。"""
    user = auth.require_active_with_sheet(authorization, x_auth_token)
    m = re.search(r"/(?:item|explore|discovery/item)/([0-9a-f]{24})", url)
    if not m:
        return {"exists": False, "note_id": None, "row": None,
                "reason": "URL 中提取不到笔记 ID"}
    note_id = m.group(1)
    try:
        existing = writer.find_row_across_sheets(
            user["spreadsheet_token"], note_id,
        )
        if existing:
            return {
                "exists": True,
                "note_id": note_id,
                "row": existing["row"],
                "sheet_title": existing["sheet_title"],
            }
        return {"exists": False, "note_id": note_id, "row": None}
    except (LarkAuthError, LarkAPIError) as e:
        raise HTTPException(status_code=502, detail=str(e))


XHS_URL_RE = re.compile(r"^https?://(?:www\.)?(?:xiaohongshu\.com|xhslink\.com)/", re.I)


def _validate_xhs_url(url: str):
    """非法 URL 直接拒（400），不污染飞书表。"""
    if not XHS_URL_RE.match(url or ""):
        raise HTTPException(
            status_code=400,
            detail=f"非小红书链接：{url[:120]}",
        )


@app.post("/api/collect")
def collect(req: CollectRequest,
authorization: Optional[str] = Header(None),
            x_auth_token: Optional[str] = Header(None)):
    user = auth.require_active_with_sheet(authorization, x_auth_token)
    _validate_xhs_url(req.url)
    try:
        return _process_one(user, req.url, req.note or "",
                            req.tags or [], req.source or "Extension",
                            sheet_id=req.sheet_id,
                            dup_strategy=req.dup_strategy or "skip")
    except (LarkAuthError, LarkAPIError) as e:
        raise HTTPException(status_code=502, detail=str(e))


MAX_BATCH_URLS = 50


@app.post("/api/collect-batch")
def collect_batch(req: BatchRequest,
authorization: Optional[str] = Header(None),
                  x_auth_token: Optional[str] = Header(None)):
    user = auth.require_active_with_sheet(authorization, x_auth_token)
    if len(req.urls) > MAX_BATCH_URLS:
        raise HTTPException(
            status_code=400,
            detail=f"批量上限 {MAX_BATCH_URLS} 条，当前传了 {len(req.urls)} 条",
        )
    # 预校验所有 URL：有非法的直接 400 拒绝
    for u in req.urls:
        _validate_xhs_url(u)
    results = []
    for i, url in enumerate(req.urls):
        if i > 0:
            time.sleep(1.5)
        try:
            results.append(_process_one(
                user, url, req.note or "", req.tags or [],
                req.source or "Extension", sheet_id=req.sheet_id,
                dup_strategy=req.dup_strategy or "skip",
            ))
        except Exception as e:
            results.append({"status": "failed", "url": url, "error": str(e)})
    return {
        "total": len(results),
        "ok": sum(1 for r in results if r.get("status") == "ok"),
        "duplicate": sum(1 for r in results if r.get("status") == "duplicate"),
        "failed": sum(1 for r in results if r.get("status") == "failed"),
        "results": results,
    }


@app.get("/")
def root():
    return {"service": "xhs-collect API",
            "version": app.version,
            "endpoints": ["/api/health", "/api/whoami", "/api/sheets",
                          "/api/check", "/api/collect", "/api/collect-batch",
                          "/auth/login", "/auth/callback", "/auth/activate",
                          "/auth/bind-sheet", "/api/me",
                          "/admin/codes", "/admin/users"]}


# ===========================================================================
# v4 OAuth 路由
# ===========================================================================

@app.get("/auth/login")
def auth_login():
    """重定向到飞书 OAuth 授权页。

    扩展把用户引导到 http://14.22.112.147:8866/auth/login，
    用户飞书扫码授权后，飞书会回调 /auth/callback。
    """
    url, _state = oauth_lark.build_authorize_url(
        app_id=CONFIG["app_id"],
        redirect_uri=OAUTH_REDIRECT_URI,
    )
    return RedirectResponse(url, status_code=302)


@app.get("/auth/callback")
def auth_callback(code: str = Query(...),
                  state: str = Query(...),
                  error: Optional[str] = Query(None)):
    """飞书 OAuth 回调。

    成功后渲染一个 HTML 页面，前端 JS 自动把 JWT 通过 postMessage 或
    localStorage 传回 Chrome 扩展（扩展 popup 轮询 chrome.tabs 拿到）。
    """
    if error:
        # 飞书侧返回的 error 不直接渲染（防 XSS），写日志即可
        print(f"[oauth_callback] provider error: {error!r}")
        return HTMLResponse(_callback_html_error("oauth_provider_error", error),
                             status_code=400)
    if not oauth_lark.validate_state(state):
        return HTMLResponse(_callback_html_error("state_invalid"),
                             status_code=400)
    try:
        token_resp = oauth_lark.exchange_code_for_token(
            app_id=CONFIG["app_id"],
            app_secret=CONFIG["app_secret"],
            code=code,
            redirect_uri=OAUTH_REDIRECT_URI,
        )
    except oauth_lark.LarkOAuthError as e:
        print(f"[oauth_callback] token exchange failed: {e}")
        return HTMLResponse(_callback_html_error("lark_token_exchange_failed", str(e)),
                             status_code=502)

    access_token = token_resp.get("access_token")
    if not access_token:
        return HTMLResponse(_callback_html_error("lark_empty_access_token"),
                             status_code=502)
    try:
        info = oauth_lark.get_user_info(access_token)
    except oauth_lark.LarkOAuthError as e:
        print(f"[oauth_callback] userinfo failed: {e}")
        return HTMLResponse(_callback_html_error("lark_userinfo_failed", str(e)),
                             status_code=502)

    open_id = info.get("open_id") or info.get("user_id")
    if not open_id:
        return HTMLResponse(_callback_html_error("lark_no_open_id"),
                             status_code=502)
    name = info.get("name", "")
    avatar_url = info.get("avatar_url", "")
    union_id = info.get("union_id", "")

    # 查找或创建用户
    user_row = db.get_user_by_open_id(open_id)
    if not user_row:
        # 新用户：创建为 pending 状态，等激活码
        user_id = db.create_user(
            open_id=open_id, name=name, avatar_url=avatar_url,
            union_id=union_id, status="pending",
        )
        is_new = True
    else:
        # 老用户：更新登录时间和姓名/头像
        db.update_user_login(open_id, name=name, avatar_url=avatar_url)
        user_id = user_row["id"]
        is_new = False

    # 签发 JWT（即使 pending 也签，让前端能调 /auth/activate）
    jwt_token = auth.issue_jwt(user_id, open_id)

    # 重定向到 /auth/done，把 token 放在 query string 里
    # 让扩展 background.js 监听这个 URL 自动收 token + 关闭 tab + 切到 onboarding
    qs = urllib.parse.urlencode({
        "token": jwt_token,
        "name": name or "",
    })
    return RedirectResponse(url=f"/auth/done?{qs}", status_code=302)


@app.get("/auth/done")
def auth_done(token: str = Query(""), name: str = Query("")):
    """登录完成中转页。扩展 background.js 监听这个 URL 自动拦截 token。

    如果用户没装扩展或扩展未在监听，仍然显示一个友好的「手动复制」页面。
    """
    return HTMLResponse(_done_html(token, name))


def _done_html(jwt_token: str, name: str) -> str:
    # 注意：此页面被扩展 background.js 监听到后会自动关闭。
    # 这里渲染一个友好的"等待中"页面，附带手动复制兜底。
    safe_name = (name or "").replace("<", "&lt;")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>登录完成</title>
<style>
body{{font-family:-apple-system,sans-serif;max-width:520px;margin:80px auto;padding:0 20px;color:#333;text-align:center}}
.ok{{background:#F0FDF4;color:#16A34A;padding:20px;border-radius:8px;border:1px solid #BBF7D0;margin:20px 0;font-size:15px}}
.spin{{display:inline-block;width:18px;height:18px;border:2px solid #E4E4E7;border-top-color:#16A34A;border-radius:50%;animation:s 1s linear infinite;vertical-align:middle;margin-right:8px}}
@keyframes s{{to{{transform:rotate(360deg)}}}}
.token-box{{background:#F4F4F5;padding:12px;border-radius:6px;font-family:monospace;font-size:11px;word-break:break-all;text-align:left;margin:16px 0;color:#3F3F46;cursor:pointer}}
.fallback{{margin-top:30px;font-size:12px;color:#71717A;border-top:1px solid #E4E4E7;padding-top:20px}}
.btn{{display:inline-block;background:#FF2442;color:white;padding:8px 16px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:500;border:none;cursor:pointer;margin:4px}}
</style>
</head><body>
<h2>✅ 飞书登录成功，欢迎 {safe_name}</h2>
<div class="ok"><span class="spin"></span>正在自动返回扩展…</div>
<p style="color:#71717A;font-size:13px">浏览器应当在 2 秒内自动关闭此页面，并切到扩展继续。</p>

<div class="fallback">
<p>⚠️ <b>如果 5 秒后还停在这里没动</b>（扩展可能没在监听）：</p>
<div class="token-box" id="jwt" onclick="selectAll()">{jwt_token}</div>
<button class="btn" onclick="copy()">📋 复制 Token</button>
<button class="btn" style="background:#71717A" onclick="selectAll()">🔍 选中手动 Cmd+C</button>
<div id="status" style="margin-top:10px;color:#16A34A;font-size:12px"></div>
<p style="margin-top:12px">复制后回到扩展的 onboarding 标签页，粘贴到 Token 框。</p>
</div>

<script>
function selectAll() {{
  const el = document.getElementById('jwt');
  const range = document.createRange();
  range.selectNodeContents(el);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
}}
function copy() {{
  const text = document.getElementById('jwt').textContent.trim();
  const status = document.getElementById('status');
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(text).then(() => {{
      status.textContent = '✅ 已复制';
    }}).catch(() => fallback(text, status));
  }} else {{
    fallback(text, status);
  }}
}}
function fallback(text, status) {{
  selectAll();
  try {{
    const ok = document.execCommand('copy');
    status.textContent = ok ? '✅ 已复制（兜底）' : '⚠️ 自动复制失败，请手动 Cmd+C';
  }} catch (e) {{
    status.textContent = '⚠️ 自动复制失败：' + e.message;
  }}
}}
</script>
</body></html>"""


# 错误码 → 用户可见的安全白名单文案。
# 这样原始 error 永远不进 HTML，彻底消灭 XSS 注入面。
_ERROR_WHITELIST = {
    "state_invalid": "登录链接已过期或无效，请重新发起登录",
    "lark_token_exchange_failed": "飞书换 token 失败，请稍后重试",
    "lark_empty_access_token": "飞书返回空 access_token，请重新登录",
    "lark_userinfo_failed": "飞书拉取用户信息失败，请稍后重试",
    "lark_no_open_id": "飞书未返回 open_id，请联系管理员",
    "oauth_provider_error": "飞书授权流程异常，请重新登录",
}


def _callback_html_error(error_code: str, raw_detail: str = "") -> str:
    """渲染登录失败页。

    error_code 走白名单（不含用户输入）；raw_detail 仅在日志里用，
    不会被插入 HTML —— 彻底消灭 XSS。
    """
    safe_msg = _ERROR_WHITELIST.get(error_code, "登录失败，请重新尝试")
    # 双重保险：即使误用了非白名单字符串也强制 escape
    safe_msg = html.escape(safe_msg)
    safe_code = html.escape(error_code or "unknown")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>登录失败</title>
<style>body{{font-family:-apple-system,sans-serif;max-width:480px;margin:80px auto;padding:0 20px;color:#333}}
.err{{background:#FEF2F2;color:#DC2626;padding:16px;border-radius:8px;border:1px solid #FECACA}}
.code{{color:#71717A;font-size:12px;margin-top:8px;font-family:monospace}}</style>
</head><body>
<h2>登录失败</h2>
<div class="err">{safe_msg}<div class="code">错误码：{safe_code}</div></div>
<p><a href="/auth/login">重新登录</a></p>
</body></html>"""


def _callback_html_success(jwt_token: str, name: str, avatar: str,
                            needs_activation: bool, needs_bind_sheet: bool,
                            is_new: bool) -> str:
    next_step = ""
    if needs_activation:
        next_step = "请输入激活码"
    elif needs_bind_sheet:
        next_step = "请绑定你的飞书表"
    else:
        next_step = "已就绪，可关闭此页"
    avatar_html = f'<img src="{avatar}" style="width:64px;height:64px;border-radius:50%">' if avatar else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>登录成功</title>
<style>
body{{font-family:-apple-system,sans-serif;max-width:520px;margin:60px auto;padding:0 20px;color:#333;text-align:center}}
.ok{{background:#F0FDF4;color:#16A34A;padding:16px;border-radius:8px;border:1px solid #BBF7D0;margin:20px 0}}
.token-box{{background:#F4F4F5;padding:14px;border-radius:6px;font-family:ui-monospace,monospace;font-size:12px;word-break:break-all;text-align:left;margin:16px 0;color:#3F3F46;border:1px solid #E4E4E7;line-height:1.5}}
.btn{{display:inline-block;background:#FF2442;color:white;padding:10px 24px;border-radius:6px;text-decoration:none;font-weight:500;border:none;font-size:14px;cursor:pointer;margin:4px}}
.btn:hover{{background:#E61E3C}}
.next{{color:#71717A;margin:12px 0;font-size:13px}}
.tip{{background:#FEF7E6;color:#92400E;padding:10px 14px;border-radius:6px;font-size:12px;text-align:left;margin:16px 0;border:1px solid #FED7AA}}
#copyStatus{{font-size:13px;color:#16A34A;margin-top:8px;min-height:20px}}
</style>
</head><body>
{avatar_html}
<h2>✅ 飞书登录成功</h2>
<p>欢迎，<b>{name}</b></p>
<div class="ok">下一步：{next_step}</div>
<p class="next">把下面这串 Login Token 复制到 Chrome 扩展的 onboarding 页面：</p>
<textarea id="jwt" readonly style="display:none">{jwt_token}</textarea>
<div class="token-box" id="jwtDisplay" onclick="selectAll()" style="cursor:pointer">{jwt_token}</div>
<button class="btn" id="copyBtn" onclick="copyToken()">📋 复制 Token</button>
<button class="btn" onclick="selectAll()" style="background:#71717A">🔍 选中（手动 Cmd+C 复制）</button>
<div id="copyStatus"></div>
<div class="tip">
  💡 <b>如果"复制"按钮没反应</b>（HTTP 环境某些浏览器不支持自动复制）：<br>
  &nbsp;&nbsp;1. 点上面那个长方框（自动全选）<br>
  &nbsp;&nbsp;2. 按 Cmd+C（Mac）/ Ctrl+C（Win）手动复制<br>
  &nbsp;&nbsp;3. 回 Chrome 扩展 onboarding 页面，Cmd+V 粘贴
</div>
<p style="margin-top:30px;color:#999;font-size:12px">复制后回到 Chrome 扩展的 onboarding 页面，粘贴到 Token 框</p>
<script>
function selectAll() {{
  // 把 token 放到 textarea 选中（HTTP 环境也能用）
  const ta = document.getElementById('jwt');
  ta.style.display = 'block';
  ta.style.width = '100%';
  ta.style.minHeight = '60px';
  ta.style.fontSize = '12px';
  ta.style.fontFamily = 'monospace';
  ta.focus();
  ta.select();
}}
function copyToken() {{
  const text = document.getElementById('jwtDisplay').textContent.trim();
  const status = document.getElementById('copyStatus');
  // 优先用 navigator.clipboard（HTTPS / localhost / 部分宽容浏览器）
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(text).then(() => {{
      status.textContent = '✅ 已复制，回扩展 onboarding 页面粘贴';
      document.getElementById('copyBtn').textContent = '✅ 已复制';
    }}).catch((e) => {{
      tryFallback(text, status);
    }});
    return;
  }}
  tryFallback(text, status);
}}
function tryFallback(text, status) {{
  // Fallback：textarea + execCommand
  const ta = document.getElementById('jwt');
  ta.style.display = 'block';
  ta.select();
  try {{
    const ok = document.execCommand('copy');
    if (ok) {{
      status.textContent = '✅ 已复制（兜底方式）';
      document.getElementById('copyBtn').textContent = '✅ 已复制';
    }} else {{
      status.textContent = '⚠️ 自动复制失败，请点"选中"按钮后手动 Cmd+C 复制';
    }}
  }} catch (e) {{
    status.textContent = '⚠️ 自动复制失败：' + e.message + '，请手动选中复制';
  }}
}}
</script>
</body></html>"""


# ===========================================================================
# v4 激活 + 绑表
# ===========================================================================

class ActivateRequest(BaseModel):
    code: str


@app.post("/auth/activate")
def auth_activate(req: ActivateRequest,
                  user: dict = Depends(auth.require_user)):
    """用激活码激活当前 pending 用户。"""
    if not user.get("open_id"):
        raise HTTPException(status_code=400, detail="legacy 用户无需激活")
    # 查询当前 SQLite 用户状态
    row = db.get_user_by_open_id(user["open_id"])
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    if row["status"] == "active":
        return {"status": "ok", "message": "已经是激活状态", "needs_bind_sheet": not row["spreadsheet_token"]}
    # 消耗激活码
    consumed = db.consume_activation_code(req.code.strip(), user["open_id"])
    if not consumed:
        raise HTTPException(status_code=400, detail="激活码无效、已用或过期")
    db.activate_user(row["id"])
    return {"status": "ok", "message": "激活成功",
            "needs_bind_sheet": not row["spreadsheet_token"]}


class BindSheetRequest(BaseModel):
    spreadsheet_url: str


def _classify_lark_error(err_str: str) -> str:
    """根据飞书错误字符串提取分类码（用于前端展示）。"""
    if "91403" in err_str or "Forbidden" in err_str:
        return "FORBIDDEN_91403"
    if "91402" in err_str or "NOTEXIST" in err_str.upper():
        return "NOT_FOUND_91402"  # 表不存在或 bot 没权限看到
    if "91404" in err_str or "not found" in err_str.lower():
        return "NOT_FOUND_91404"
    if "1254" in err_str:  # 1254xxx 系列是 sheet 相关错误
        return "SHEET_ERROR"
    if "timeout" in err_str.lower() or "connection" in err_str.lower():
        return "NETWORK_ERROR"
    return "UNKNOWN"


def parse_token_from_url(url_or_token: str) -> tuple:
    """v4.3.5 B036：从 URL 提取 token，标记 kind。

    支持：
    - https://xxx.feishu.cn/sheets/{token} → ("sheet", token)
    - https://xxx.feishu.cn/wiki/{wiki_token} → ("wiki", wiki_token)
    - 裸 token 字符串 → ("unknown", token)

    返回 (kind, token)，kind ∈ {"sheet", "wiki", "unknown"}
    """
    if not url_or_token:
        return ("unknown", "")
    s = url_or_token.strip()
    m_sheet = re.search(r"/sheets/([A-Za-z0-9]+)", s)
    if m_sheet:
        return ("sheet", m_sheet.group(1))
    m_wiki = re.search(r"/wiki/([A-Za-z0-9]+)", s)
    if m_wiki:
        return ("wiki", m_wiki.group(1))
    # 裸 token（无 / 无空格）→ 当成 unknown，后续会先试 sheet 再 fallback wiki
    return ("unknown", s)


def resolve_to_spreadsheet_token(url_or_token: str) -> str:
    """v4.3.5 B036：把任意输入解析成 spreadsheet_token。

    流程：
    1. parse URL → 拿 kind + token
    2. kind == "wiki" → 调 wiki API 解析 obj_token
    3. kind == "sheet" 或 "unknown" → 直接当 spreadsheet_token

    抛 HTTPException 如果 wiki 解析失败 / token 不是 sheet 类型
    """
    kind, token = parse_token_from_url(url_or_token)
    if not token:
        raise HTTPException(status_code=400, detail="无效的飞书表 URL")
    if kind == "wiki":
        try:
            return resolve_wiki_to_sheet_token(token, writer)
        except (LarkAuthError, LarkAPIError) as e:
            raise HTTPException(
                status_code=502,
                detail={
                    "status": "wiki_resolve_failed",
                    "user_message": (
                        f"❌ 这是飞书知识库（Wiki）里的表格，bot 还不能访问。\n"
                        f"请把 bot「小红书收录助手」加为该 Wiki 知识库的协作者，或者把表格分享给 bot。\n"
                        f"原始错误：{str(e)[:200]}"
                    ),
                    "raw_error": str(e)[:300],
                },
            )
    return token


@app.post("/auth/bind-sheet")
def auth_bind_sheet(req: BindSheetRequest,
                    user: dict = Depends(auth.require_user)):
    """绑定用户的飞书表 URL。

    解析 URL 拿 spreadsheet_token → 探测 default sheet → 自动 init 7 个分类 sheet。

    B017 修复：严格校验。任何分类 sheet 建失败 → 返回 502 partial_failure 且
    不更新 user.spreadsheet_token（让用户保持"未绑表"状态可重试）。
    """
    if not user.get("user_id"):
        raise HTTPException(status_code=400, detail="legacy 用户不支持自助绑表")
    row = db.get_user_by_open_id(user["open_id"])
    if not row or row["status"] != "active":
        raise HTTPException(status_code=403, detail="先用激活码激活")

    # v4.3.5 B036：支持 /sheets/ 和 /wiki/ 两种 URL
    spreadsheet_token = resolve_to_spreadsheet_token(req.spreadsheet_url)
    if not spreadsheet_token:
        raise HTTPException(status_code=400, detail="无效的飞书表 URL")

    # 测试 bot 能否访问该表 + 拿 default sheet_id
    try:
        sheets = writer.get_sheets_info(spreadsheet_token, use_cache=False)
    except (LarkAuthError, LarkAPIError) as e:
        err_str = str(e)
        raise HTTPException(
            status_code=502,
            detail={
                "status": "access_denied",
                "error_code": _classify_lark_error(err_str),
                "user_message": (
                    "❌ bot 无法访问你的飞书表。\n"
                    "请确认：1) 在飞书表「···」→「添加协作者」里加上「小红书收录助手」（权限：可编辑）；"
                    "2) 在飞书表「···」→「更多」→「添加文档应用」里也添加「小红书收录助手」。\n"
                    f"原始错误：{err_str[:200]}"
                ),
                "next_action": "fix_permission_and_retry",
                "raw_error": err_str[:300],
            },
        )
    if not sheets:
        raise HTTPException(status_code=400, detail="该飞书表里没有任何 sheet")

    # 自动 init 默认笔记分类 sheet（已存在的跳过）
    DEFAULT_CATEGORIES = ["起号图文", "爆款图", "爆款文案", "同行精选",
                          "潜力款", "标题公式", "互动引导", "待研究"]
    existing_titles_to_id = {s["title"]: s["sheet_id"] for s in sheets}
    created = []
    failed = []  # B017: 记录每个失败的 sheet 及原因
    sheet_name_to_id = dict(existing_titles_to_id)  # 包含已有 + 新建
    for cat_name in DEFAULT_CATEGORIES:
        if cat_name in existing_titles_to_id:
            continue
        # B017 修复：分开 try create + try template，create 失败就记录
        try:
            new_sheet = writer.create_sheet(spreadsheet_token, cat_name)
        except (LarkAuthError, LarkAPIError) as e:
            failed.append({
                "name": cat_name,
                "reason": str(e)[:200],
                "error_code": _classify_lark_error(str(e)),
            })
            continue
        except Exception as e:
            failed.append({
                "name": cat_name,
                "reason": f"未知错误：{str(e)[:200]}",
                "error_code": "UNKNOWN",
            })
            continue
        # create 成功 → 应用模板（模板失败不致命，sheet 已建好）
        sheet_name_to_id[cat_name] = new_sheet["sheet_id"]
        created.append(cat_name)
        try:
            writer.setup_sheet_template(spreadsheet_token,
                                         new_sheet["sheet_id"])
        except Exception:
            pass  # 模板失败不阻塞，sheet 已建好

    # B017 修复：如果有任何分类建失败 → 502 + 不写 DB
    if failed:
        primary_code = failed[0]["error_code"]
        if primary_code == "FORBIDDEN_91403":
            user_msg = (
                "❌ bot 没有写权限。\n"
                "你已经把 bot 加为协作者，但飞书新版还需要单独授权「应用访问」。\n"
                "操作：飞书表右上角「···」→「更多」→「添加文档应用」→ 添加「小红书收录助手」。\n"
                "添加完后重新绑表即可。"
            )
        else:
            need_total = len(DEFAULT_CATEGORIES) - len(existing_titles_to_id)
            user_msg = (
                f"❌ 自动建分类失败（{len(failed)}/{need_total} 个失败）。\n"
                "请检查 bot 权限设置，或联系管理员。\n"
                f"首个错误：{failed[0]['reason']}"
            )
        raise HTTPException(
            status_code=502,
            detail={
                "status": "partial_failure",
                "error_code": primary_code,
                "user_message": user_msg,
                "created": created,
                "failed": failed,
                "next_action": "fix_permission_and_retry",
            },
        )

    # 全部 OK → default sheet：优先「起号图文 / 起号」，其次表里第一个 sheet
    default_sheet_id = (
        sheet_name_to_id.get("起号图文")
        or sheet_name_to_id.get("起号")
        or sheets[0]["sheet_id"]
    )

    # 写入用户（只有全部成功才写）
    db.update_user_sheet(row["id"], spreadsheet_token, default_sheet_id)
    writer.invalidate_cache(spreadsheet_token)
    return {
        "status": "ok",
        "spreadsheet_token": spreadsheet_token,
        "default_sheet_id": default_sheet_id,
        "default_sheet_name": (
            "起号图文" if "起号图文" in sheet_name_to_id
            else ("起号" if "起号" in sheet_name_to_id else sheets[0]["title"])
        ),
        "categories_created": created,
    }


# ============================================================
# B018: 权限自检 endpoint
# ============================================================

@app.get("/api/permissions/check")
def check_permissions(spreadsheet_token: Optional[str] = Query(None),
                       user: dict = Depends(auth.require_user)):
    """检测 bot 对指定飞书表的读 + 写权限。

    v4.3.5 B036：spreadsheet_token 参数现在接受三种值：
    - 完整 sheet URL（/sheets/{token}）
    - 完整 wiki URL（/wiki/{wiki_token}）
    - 裸 spreadsheet_token

    流程：
    1. resolve_to_spreadsheet_token → 解析（含 wiki API 解析）
    2. get_sheets_info → 读权限
    3. create_sheet（临时名）→ 写权限
    4. delete_sheet 清理临时 sheet
    """
    # 默认用当前用户已绑定的表
    raw_input = spreadsheet_token or user.get("spreadsheet_token")
    if not raw_input:
        raise HTTPException(
            status_code=400,
            detail="未提供 spreadsheet_token 且当前用户未绑表",
        )
    # v4.3.5 B036：先尝试解析（含 wiki）
    try:
        ss_token = resolve_to_spreadsheet_token(raw_input)
    except HTTPException as e:
        # wiki 解析失败 → 转成 user_friendly 返回（不抛 502 让前端崩）
        detail = e.detail if isinstance(e.detail, dict) else {"user_message": str(e.detail)}
        return {
            "spreadsheet_token": raw_input,
            "read_ok": False,
            "write_ok": False,
            "missing": ["read", "write"],
            "user_message": detail.get("user_message", "解析 URL 失败"),
            "details": {"resolve_error": detail.get("raw_error", "")},
        }

    result = {
        "spreadsheet_token": ss_token,
        "read_ok": False,
        "write_ok": False,
        "missing": [],
        "user_message": "",
        "details": {},
    }

    # 1. 读权限测试
    try:
        sheets = writer.get_sheets_info(ss_token, use_cache=False)
        result["read_ok"] = True
        result["details"]["sheet_count"] = len(sheets)
    except (LarkAuthError, LarkAPIError) as e:
        result["details"]["read_error"] = str(e)[:200]
        result["missing"].extend(["read", "write"])
        result["user_message"] = (
            "❌ bot 连读权限都没有。\n"
            "请在飞书表「···」→「添加协作者」里加上「小红书收录助手」（权限：可编辑）。"
        )
        return result

    # 2. 写权限测试：建一个临时 sheet
    test_sheet_name = f"__permission_test_{py_secrets.token_hex(4)}"
    test_sheet_id = None
    try:
        new_sheet = writer.create_sheet(ss_token, test_sheet_name)
        test_sheet_id = new_sheet.get("sheet_id")
        result["write_ok"] = True
    except (LarkAuthError, LarkAPIError) as e:
        err_str = str(e)
        result["details"]["write_error"] = err_str[:200]
        result["missing"].append("write")
        if "91403" in err_str or "Forbidden" in err_str:
            result["user_message"] = (
                "❌ bot 没有写权限。\n"
                "操作：飞书表右上角「···」→「更多」→「添加文档应用」→ 添加「小红书收录助手」。\n"
                "添加完后再点这个按钮重测。"
            )
        else:
            result["user_message"] = f"❌ 写权限测试失败：{err_str[:150]}"
        return result
    except Exception as e:
        result["details"]["write_error"] = str(e)[:200]
        result["missing"].append("write")
        result["user_message"] = f"❌ 写权限测试异常：{str(e)[:150]}"
        return result

    # 3. 清理临时 sheet（失败不致命，但记录到 details）
    if test_sheet_id:
        try:
            writer.delete_sheet(ss_token, test_sheet_id)
            result["details"]["cleanup"] = "ok"
        except Exception as e:
            result["details"]["cleanup"] = f"删除测试 sheet 失败：{str(e)[:150]}"

    # 全部通过
    result["user_message"] = "✅ 权限完整：bot 可读 + 可写。"
    return result


@app.get("/api/me")
def api_me(user: dict = Depends(auth.require_user)):
    """当前用户信息（含状态/绑定情况）。"""
    if user.get("is_legacy"):
        has_sheet = bool(user.get("spreadsheet_token"))
        return {
            "user_id": None,
            "open_id": None,
            "name": user["name"],
            "is_legacy": True,
            "is_admin": user["is_admin"],
            "status": "active",
            "spreadsheet_token": user["spreadsheet_token"],
            "needs_activation": False,
            "needs_bind_sheet": not has_sheet,
            "sheet_url": (
                f"https://my.feishu.cn/sheets/{user['spreadsheet_token']}"
                if has_sheet else ""
            ),
        }
    row = db.get_user_by_open_id(user["open_id"])
    return {
        "user_id": row["id"],
        "open_id": row["open_id"],
        "name": row["name"],
        "avatar_url": row["avatar_url"],
        "is_legacy": False,
        "is_admin": user["is_admin"],
        "status": row["status"],
        "spreadsheet_token": row["spreadsheet_token"],
        "needs_activation": row["status"] != "active",
        "needs_bind_sheet": not row["spreadsheet_token"],
        "sheet_url": (
            f"https://my.feishu.cn/sheets/{row['spreadsheet_token']}"
            if row["spreadsheet_token"] else ""
        ),
    }


# ===========================================================================
# v4 Admin endpoints
# ===========================================================================

class CodeCreateRequest(BaseModel):
    note: Optional[str] = ""
    expires_in_days: Optional[int] = None


@app.post("/admin/codes")
def admin_create_code(req: CodeCreateRequest,
                       admin: dict = Depends(auth.require_admin)):
    """admin 生成激活码。"""
    expires_at = None
    if req.expires_in_days:
        expires_at = int(time.time()) + req.expires_in_days * 86400
    code = db.create_activation_code(
        note=req.note or "",
        created_by=admin.get("legacy_id") or admin.get("open_id", "admin"),
        expires_at=expires_at,
    )
    return {"code": code, "expires_at": expires_at}


@app.get("/admin/codes")
def admin_list_codes(admin: dict = Depends(auth.require_admin)):
    """admin 查看所有激活码（含已用/未用）。"""
    return {"codes": db.list_activation_codes()}


@app.get("/admin/users")
def admin_list_users(admin: dict = Depends(auth.require_admin)):
    """admin 查看所有用户（SQLite + legacy 合并）。"""
    sqlite_users = db.list_users()
    legacy_users = [
        {
            "id": None,
            "legacy_id": u["legacy_id"],
            "name": u["name"],
            "spreadsheet_token": u["spreadsheet_token"],
            "is_legacy": True,
            "is_admin": u["legacy_id"] in ADMIN_LEGACY_IDS,
        }
        for u in LEGACY_TOKEN_TO_USER.values()
    ]
    return {"sqlite_users": sqlite_users, "legacy_users": legacy_users}

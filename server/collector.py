#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书笔记采集核心模块

输入：1 个或多个小红书笔记链接
输出：每条笔记的结构化字典（含标题/文案/三数/封面URL/笔记ID 等）

实现原理：
1. 用 curl + 浏览器 UA 抓取笔记 H5 详情页 HTML
2. 从 HTML 里解析 window.__INITIAL_STATE__ 内嵌的 JSON
3. 提取 note.noteDetailMap[note_id].note 节点

兼容性：
- 支持的 URL 形态：discovery/item/<id>、explore/<id>、xhslink.com 短链
- 短链会先 HEAD 跟随重定向拿到真实 URL
"""
import json
import re
import subprocess
import sys
import time
from typing import Optional

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _http_get(url: str, timeout: int = 15) -> str:
    """带 UA 的 HTTP GET，跟随重定向（用 curl，避开 Python SSL 问题）。"""
    proc = subprocess.run(
        ["curl", "-sSL", "-A", USER_AGENT, "--max-time", str(timeout), url],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"curl 失败: {proc.stderr.decode('utf-8', errors='replace')[:200]}")
    return proc.stdout.decode("utf-8", errors="replace")


def _resolve_short_link(url: str) -> str:
    """xhslink.com 短链跟随重定向拿到真实 URL。"""
    if "xhslink.com" not in url:
        return url
    proc = subprocess.run(
        ["curl", "-sSLI", "-A", USER_AGENT, "--max-time", "10", "-o", "/dev/null",
         "-w", "%{url_effective}", url],
        capture_output=True,
    )
    if proc.returncode == 0 and proc.stdout:
        return proc.stdout.decode().strip() or url
    return url


def _extract_note_id(url: str) -> Optional[str]:
    """从 URL 提取 24 位笔记 ID。"""
    m = re.search(r"/(?:item|explore|discovery/item)/([0-9a-f]{24})", url)
    return m.group(1) if m else None


def _parse_initial_state(html: str) -> Optional[dict]:
    """解析 window.__INITIAL_STATE__。"""
    m = re.search(
        r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>",
        html, re.DOTALL,
    )
    if not m:
        return None
    raw = m.group(1).replace("undefined", "null")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _pick_image_url(image_item: dict) -> Optional[str]:
    """从单张 image item 挑出最高质量 URL（https）。"""
    if not image_item:
        return None
    first = image_item
    info_list = first.get("infoList") or []
    # 优先 WB_DFT（默认大图），其次 WB_PRV（预览），再次 urlDefault
    for scene in ("WB_DFT", "WB_PRV"):
        for info in info_list:
            if info.get("imageScene") == scene and info.get("url"):
                return info["url"].replace("http://", "https://")
    fallback = first.get("urlDefault") or first.get("url")
    if fallback:
        return fallback.replace("http://", "https://")
    return None


def _pick_image_urls(image_list: list) -> list:
    """从 imageList 提取全部可用图片 URL，保持原顺序并去重。"""
    urls = []
    seen = set()
    for item in image_list or []:
        url = _pick_image_url(item)
        if not url or url in seen:
            continue
        urls.append(url)
        seen.add(url)
    return urls


def _pick_cover_url(image_list: list) -> Optional[str]:
    """从 imageList[0] 挑出最高质量封面 URL（https）。"""
    urls = _pick_image_urls(image_list)
    return urls[0] if urls else None


def _parse_count(v):
    """解析小红书互动数（点赞/收藏/评论/分享）。

    小红书前端会把大数字格式化为人类可读字符串，如 "1.1万" / "10w" / "999+"。
    直接 int() 会抛 ValueError 让整条采集失败（B019）。

    返回值类型策略：
    - int: 能精确解析（1234 / "1234" / "1.1万" / "10w" / "10亿"）
    - str: 带 "+" 的模糊上限标记，原字符串入库（"1万+" / "999+" / "1.5w+"）
           — 用户决策："1万+" 不强行折算为 10000 或 15000，保留外观
    - 0:   None / "" / 完全无法解析（写 stderr 警告日志供追溯）
    """
    if v is None or v == "":
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    if not s:
        return 0
    if s.isdigit():
        return int(s)
    # 带 "+" 的模糊上限 → 原字符串入库（用户决策：保留外观）
    if "+" in s:
        return s
    # 带单位 ("万" / "w" / "W" / "亿")
    for unit, mul in (("万", 10_000), ("w", 10_000), ("W", 10_000), ("亿", 100_000_000)):
        if s.endswith(unit):
            try:
                num_part = s[: -len(unit)].strip()
                return int(round(float(num_part) * mul))
            except ValueError:
                break
    # 最后兜底：纯浮点字符串
    try:
        return int(float(s))
    except ValueError:
        print(
            f"[collector._parse_count] WARN: 无法解析互动数 {v!r}，返回 0",
            file=sys.stderr,
        )
        return 0


def collect_one(url: str) -> dict:
    """采集单条笔记。

    Returns:
        dict: {
            "status": "ok" | "error",
            "url": 原始 URL,
            "note_id": str | None,
            "title": str,
            "desc": str,                # 完整文案（含话题标签）
            "liked": int,
            "collected": int,
            "comment": int,
            "share": int,
            "cover_url": str | None,
            "image_urls": list[str],     # 全部图片 URL，第一张等于 cover_url
            "tags": list[str],          # 话题标签数组
            "error": str (仅 status=error 时),
        }
    """
    result = {
        "status": "error",
        "url": url,
        "note_id": _extract_note_id(url),
        "title": "",
        "desc": "",
        "liked": 0,
        "collected": 0,
        "comment": 0,
        "share": 0,
        "cover_url": None,
        "image_urls": [],
        "tags": [],
        "error": "",
    }

    try:
        # SSRF 防护：URL 必须是小红书域名（防止用户提交内网 URL 触发 SSRF）
        from urllib.parse import urlparse
        ALLOWED_HOSTS = {
            "www.xiaohongshu.com",
            "xiaohongshu.com",
            "xhslink.com",
            "www.xhslink.com",
        }
        try:
            parsed = urlparse(url)
        except Exception:
            result["error"] = "URL 解析失败"
            return result
        if parsed.scheme not in ("http", "https"):
            result["error"] = f"非法 scheme: {parsed.scheme}（只允许 http/https）"
            return result
        if parsed.hostname not in ALLOWED_HOSTS:
            result["error"] = f"非小红书域名: {parsed.hostname}"
            return result

        # 短链解析
        real_url = _resolve_short_link(url)
        if real_url != url:
            # 短链跳转后再次校验目标 host
            try:
                rp = urlparse(real_url)
                if rp.hostname not in ALLOWED_HOSTS:
                    result["error"] = f"短链跳转到非小红书域名: {rp.hostname}"
                    return result
            except Exception:
                pass
            result["url"] = real_url
            result["note_id"] = _extract_note_id(real_url) or result["note_id"]

        # 抓 HTML
        html = _http_get(real_url)

        # 解析 INITIAL_STATE
        state = _parse_initial_state(html)
        if not state:
            result["error"] = "未找到 __INITIAL_STATE__（页面结构变了或被风控）"
            return result

        note_map = state.get("note", {}).get("noteDetailMap", {})
        if not note_map:
            # fallback：尝试从 og:meta 提取（数据有限）
            og_title = re.search(r'<meta name="og:title" content="([^"]+)"', html)
            og_image = re.search(r'<meta name="og:image" content="([^"]+)"', html)
            if og_title:
                result["title"] = og_title.group(1).split("\t")[0].strip()
                result["desc"] = og_title.group(1).strip()
            if og_image:
                result["cover_url"] = og_image.group(1).replace("http://", "https://")
                result["image_urls"] = [result["cover_url"]]
            result["error"] = "noteDetailMap 为空（可能需要登录），已降级用 meta 标签"
            result["status"] = "partial"
            return result

        note_id = result["note_id"] or list(note_map.keys())[0]
        nd = note_map.get(note_id, {}).get("note", {})
        if not nd:
            result["error"] = f"笔记 {note_id} 在 noteDetailMap 中不存在"
            return result

        # 提取字段
        result["note_id"] = note_id
        desc = nd.get("desc", "") or ""
        result["desc"] = desc

        # 标题：noteCard 的 title 优先；为空则取 desc 第一行
        title = nd.get("title") or ""
        if not title and desc:
            title = desc.split("\n", 1)[0].strip()
        result["title"] = title

        # 话题标签
        tag_list = nd.get("tagList") or []
        result["tags"] = [t.get("name") for t in tag_list if t.get("name")]

        # 互动数（B019: 走 _parse_count，兼容 "1.1万" / "999+" 等格式）
        interact = nd.get("interactInfo") or {}
        result["liked"] = _parse_count(interact.get("likedCount"))
        result["collected"] = _parse_count(interact.get("collectedCount"))
        result["comment"] = _parse_count(interact.get("commentCount"))
        result["share"] = _parse_count(interact.get("shareCount"))

        # 图片：保留全部图片，默认封面取第一张
        image_urls = _pick_image_urls(nd.get("imageList") or [])
        result["image_urls"] = image_urls
        result["cover_url"] = image_urls[0] if image_urls else None

        result["status"] = "ok"
        return result

    except RuntimeError as e:
        result["error"] = str(e)
        return result
    except Exception as e:
        result["error"] = f"未知异常: {type(e).__name__}: {e}"
        return result


def collect_batch(urls: list, interval: float = 1.5) -> list:
    """批量采集，条间间隔（默认 1.5 秒，规避风控）。"""
    results = []
    for i, url in enumerate(urls):
        if i > 0:
            time.sleep(interval)
        results.append(collect_one(url))
    return results


if __name__ == "__main__":
    # CLI 用法：python collector.py "url1" "url2" ...
    # 输出：JSON 数组到 stdout
    if len(sys.argv) < 2:
        print("Usage: python collector.py <url> [<url2> ...]", file=sys.stderr)
        sys.exit(1)
    urls = sys.argv[1:]
    results = collect_batch(urls) if len(urls) > 1 else [collect_one(urls[0])]
    print(json.dumps(results, ensure_ascii=False, indent=2))

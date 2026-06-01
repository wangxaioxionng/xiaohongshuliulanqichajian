#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书电子表格写入器（Bot 身份，多租户版 v3.1）

v3.1 变更：
- 移除 __init__ 里固定的 spreadsheet_token / sheet_id
- 所有方法改为每次调用时传入用户对应的 spreadsheet_token / sheet_id
- 支持服务多个用户的不同飞书表

API 文档：https://open.feishu.cn/document/server-docs/docs/sheets-v3/
"""
import base64
import json
import time
from datetime import datetime
from typing import Optional

import requests

LARK_BASE = "https://open.feishu.cn/open-apis"

# 列定义
# v4.3.6 B037：加 O 列「话题标签」（hashtag 从 F 文案拆出来）
COL = {
    "seq": "A", "url": "B", "status": "C", "title": "D", "cover": "E",
    "desc": "F", "liked": "G", "collected": "H", "comment": "I",
    "share": "J", "note_id": "K", "time": "L", "source": "M", "note": "N",
    "tags": "O",
}
LAST_COL = "O"
NOTE_HEADERS = ["序号", "笔记链接", "状态", "标题", "封面图", "文案",
                "点赞", "收藏", "评论", "分享", "笔记ID", "采集时间",
                "来源", "我的备注", "话题标签"]
MULTI_IMAGE_SHEET_TITLES = ("爆款图", "爆款图片")
PROFILE_COLLECT_BASE_HEADERS = [
    "序号", "店铺/账号名", "主页链接", "笔记标题", "图文文案",
    "话题标签", "笔记链接", "图片数量", "封面图", "全部图片下载链接",
]
PROFILE_COLLECT_META_HEADERS = ["采集时间", "采集来源", "状态"]
SHOP_PRODUCTS_SHEET_TITLE = "店铺商品提取"
SHOP_PRODUCTS_LAST_COL = "K"
SHOP_PRODUCT_HEADERS = [
    "序号", "店铺名", "店铺ID", "商品名", "商品链接", "商品ID",
    "到手价", "已售数", "采集时间", "采集来源", "异常备注",
]

# v4.3.4 B034 v6：F 列文案预处理 — 把 \n 直接删除（无分隔符）
# 飞书 row height fixedSize 对超长 cellValue silent fail，唯一压住行高的办法是源头不写 \n
# v4 用 ' · ' 太密；v5 用空格仍有视觉断；v6 直接删除让飞书表呈现普通连续文案
# 配套 desc_backup 表存原文 → 想还原走 SQL 查表
DESC_SEPARATOR = ""

def resolve_wiki_to_sheet_token(wiki_token: str, lark_writer_instance) -> str:
    """v4.3.5 B036：把飞书 Wiki 节点 token 解析成 spreadsheet_token。

    飞书 wiki URL：https://xxx.feishu.cn/wiki/{wiki_node_token}
    通过 wiki API GET /open-apis/wiki/v2/spaces/get_node?token={wiki_node_token}
    返回 data.node.obj_token 才是真正的 spreadsheet_token

    参数 lark_writer_instance：LarkWriter 实例（用它的 _get_tenant_token）
    返回：spreadsheet_token (str)
    抛出：LarkAPIError 如果不是 sheet 类型或 bot 没权限
    """
    tok = lark_writer_instance._get_tenant_token()
    url = f"{LARK_BASE}/wiki/v2/spaces/get_node"
    resp = requests.get(
        url,
        params={"token": wiki_token},
        headers={"Authorization": f"Bearer {tok}"},
        timeout=15,
    )
    data = resp.json() if resp.content else {}
    if data.get("code") != 0:
        raise LarkAPIError(
            f"wiki/get_node 失败 code={data.get('code')} msg={data.get('msg')}"
        )
    node = data.get("data", {}).get("node", {})
    obj_token = node.get("obj_token", "")
    obj_type = node.get("obj_type", "")
    if not obj_token:
        raise LarkAPIError("wiki/get_node 返回空 obj_token")
    if obj_type not in ("sheet", "Sheet"):
        raise LarkAPIError(
            f"wiki 节点不是电子表格类型（obj_type={obj_type}）。"
            "请确认你分享的是飞书电子表格，不是文档/多维表格/思维笔记"
        )
    return obj_token


def extract_hashtags(text: str) -> tuple:
    """v4.3.6 B037：从文案里提取 hashtag（#xxx[话题]# 等），返回 (clean_text, tags_str)。

    小红书 hashtag 格式：`#内容[话题]#` 或 `#关键词#` 等，特征是首尾各一个 #
    正则：`#[^#\\n]+?#` (非贪婪匹配两个 # 之间内容，不跨行)

    返回：
      clean_text: 去掉所有 hashtag 并清理多余空格的文案
      tags_str: 所有 hashtag 用空格连接（保持单行不撑高 O 列行高）
    """
    import re as _re
    if not isinstance(text, str) or not text:
        return (text or "", "")
    # 提取所有 hashtag
    tags = _re.findall(r"#[^#\n]+?#", text)
    if not tags:
        return (text, "")
    # 从原文去除 hashtag
    clean = _re.sub(r"#[^#\n]+?#", "", text)
    # 折叠多个连续空格 + 去首尾空格（hashtag 删除后留下的空隙）
    clean = _re.sub(r"\s+", " ", clean).strip()
    # tags 用空格连接（保持单行）
    tags_str = " ".join(tags)
    return (clean, tags_str)


def flatten_desc(desc: str) -> str:
    """把 F 列文案的换行符替换为单行分隔符，防止飞书行高被撑高。

    - 多个连续 \\n 折叠成 1 个分隔符（去掉空段落）
    - \\r\\n / \\r 也一并处理
    - 非字符串原样返回
    """
    if not isinstance(desc, str):
        return desc
    if not desc:
        return desc
    # 统一换行符
    normalized = desc.replace("\r\n", "\n").replace("\r", "\n")
    # 折叠多个连续 \n
    lines = [line.strip() for line in normalized.split("\n")]
    # 去掉空行（小红书文案常有"."当段落分隔，这种保留；纯空行去掉）
    non_empty = [line for line in lines if line]
    return DESC_SEPARATOR.join(non_empty)


def col_letter(index: int) -> str:
    """1-based column index -> Excel/Sheets column letter."""
    if index < 1:
        raise ValueError("column index must be >= 1")
    letters = ""
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def sanitize_sheet_title(title: str, fallback: str = "账号全采集") -> str:
    """清理飞书 sheet 名：去掉不适合作为表名的字符，并控制长度。"""
    import re as _re
    cleaned = _re.sub(r"[\[\]\*?/\\:]", "", str(title or "")).strip()
    cleaned = _re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = fallback
    return cleaned[:30]


class LarkAuthError(Exception):
    pass


class LarkAPIError(Exception):
    pass


class LarkWriter:
    """飞书电子表格写入器（bot 身份，多租户版本）。

    使用方式：
        writer = LarkWriter(app_id, app_secret)  # 单例
        writer.write_record(user["spreadsheet_token"], user["default_sheet_id"], ...)
    """

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._token = None
        self._token_expires_at = 0
        # 缓存：sheet_id → set(note_id)，跨 sheet 查找加速
        # key: spreadsheet_token, value: (ts, {sheet_id: {note_id, ...}})
        self._notes_cache = {}
        self._notes_cache_ttl = 30  # 秒
        # 缓存：spreadsheet_token → (ts, sheets_info_list)
        self._sheets_cache = {}
        self._sheets_cache_ttl = 60  # 秒
        # Dashboard 缓存：(stats + recent)，每 30 秒重算
        self._dashboard_cache = {}
        self._dashboard_cache_ttl = 30  # 秒
        # Failures 缓存
        self._failures_cache = {}
        self._failures_cache_ttl = 30  # 秒

    def invalidate_cache(self, spreadsheet_token: str):
        """收录/更新数据后主动失效缓存（所有缓存一起清）。"""
        self._notes_cache.pop(spreadsheet_token, None)
        self._sheets_cache.pop(spreadsheet_token, None)
        self._dashboard_cache.pop(spreadsheet_token, None)
        self._failures_cache.pop(spreadsheet_token, None)

    # ---------- 认证 ----------

    def _get_tenant_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expires_at - 300:
            return self._token
        resp = requests.post(
            f"{LARK_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise LarkAuthError(f"获取 tenant_access_token 失败: {data}")
        self._token = data["tenant_access_token"]
        self._token_expires_at = now + int(data.get("expire", 7200))
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_tenant_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _api(self, method: str, path: str, **kwargs) -> dict:
        url = f"{LARK_BASE}{path}"
        kwargs.setdefault("timeout", 15)
        resp = requests.request(method, url, headers=self._headers(), **kwargs)
        try:
            data = resp.json()
        except Exception:
            raise LarkAPIError(
                f"飞书 API 返回非 JSON: {resp.status_code} {resp.text[:200]}"
            )
        if data.get("code") not in (0, None):
            raise LarkAPIError(
                f"飞书 API 错误: {data.get('code')} {data.get('msg')}"
            )
        return data

    # ---------- 表格基础操作 ----------

    def read_range(self, spreadsheet_token: str, sheet_id: str,
                   cell_range: str) -> list:
        """读取范围，返回二维数组。cell_range 例如 'A1:N1000'。"""
        full_range = f"{sheet_id}!{cell_range}"
        data = self._api(
            "GET",
            f"/sheets/v2/spreadsheets/{spreadsheet_token}/values/{full_range}",
        )
        return data.get("data", {}).get("valueRange", {}).get("values") or []

    def write_range(self, spreadsheet_token: str, sheet_id: str,
                    cell_range: str, values: list) -> dict:
        """写入范围（覆盖式）。values 是二维数组。"""
        full_range = f"{sheet_id}!{cell_range}"
        return self._api(
            "PUT",
            f"/sheets/v2/spreadsheets/{spreadsheet_token}/values",
            json={"valueRange": {"range": full_range, "values": values}},
        )

    def set_row_height(self, spreadsheet_token: str, sheet_id: str,
                       row_index: int, height: int = 260):
        """设置某行行高（像素）。row_index 是 1-indexed。"""
        return self._api(
            "POST",
            f"/sheets/v2/spreadsheets/{spreadsheet_token}/dimension_range",
            json={
                "dimension": {
                    "sheetId": sheet_id,
                    "majorDimension": "ROWS",
                    "startIndex": row_index,
                    "endIndex": row_index,
                },
                "dimensionProperties": {"fixedSize": height},
            },
        )

    def set_row_height_range(self, spreadsheet_token: str, sheet_id: str,
                             start_row: int, end_row: int, height: int = 32):
        """批量设置行高（像素）。start_row / end_row 都是 1-indexed 闭区间。

        飞书的 fixedSize 是"强制固定行高"，超长文案会被裁剪展示（用户双击单元格看全文）。
        用于 backfill：把数据区行高统一压成 32px，避免长 desc 撑高整行。
        注意：图片行 260px 由 write_record() 单独设置，不会被这个方法影响（除非显式覆盖）。

        飞书 API 90204 坑：更新已有行的属性时，dimension 必须用 length 字段（不能用 endIndex）。
        length 表示从 startIndex 开始连续修改的行数。
        """
        length = end_row - start_row + 1
        return self._api(
            "POST",
            f"/sheets/v2/spreadsheets/{spreadsheet_token}/dimension_range",
            json={
                "dimension": {
                    "sheetId": sheet_id,
                    "majorDimension": "ROWS",
                    "startIndex": start_row,
                    "length": length,
                },
                "dimensionProperties": {"fixedSize": height},
            },
        )

    # ---------- 单元格图片 ----------

    def upload_image_to_cell(self, spreadsheet_token: str, sheet_id: str,
                             row_index: int, image_bytes: bytes,
                             image_name: str = "cover.jpg",
                             col: str = None) -> dict:
        """把图片字节嵌入到指定单元格（cell-image）。默认写 E 列封面图。"""
        target_col = col or COL["cover"]
        full_range = f"{sheet_id}!{target_col}{row_index}:{target_col}{row_index}"
        b64 = base64.b64encode(image_bytes).decode("ascii")
        return self._api(
            "POST",
            f"/sheets/v2/spreadsheets/{spreadsheet_token}/values_image",
            json={"range": full_range, "image": b64, "name": image_name},
        )

    def get_sheet_title(self, spreadsheet_token: str, sheet_id: str) -> str:
        """按 sheet_id 找 sheet 名称，找不到返回空字符串。"""
        for sheet in self.get_sheets_info(spreadsheet_token):
            if sheet["sheet_id"] == sheet_id:
                return sheet["title"] or ""
        return ""

    def _get_sheet_col_count(self, spreadsheet_token: str,
                             sheet_id: str) -> int:
        """查询单个 sheet 当前列数。失败返回 20（飞书常见默认列数）。"""
        try:
            sheets = self.get_sheets_info(spreadsheet_token, use_cache=False)
            for s in sheets:
                if s["sheet_id"] == sheet_id:
                    return int(s.get("col_count") or 20)
        except Exception:
            pass
        return 20

    def _ensure_min_columns(self, spreadsheet_token: str, sheet_id: str,
                            min_cols: int) -> None:
        """确保 sheet 至少有 min_cols 列，用于多图追加列。"""
        actual_cols = self._get_sheet_col_count(spreadsheet_token, sheet_id)
        if actual_cols >= min_cols:
            return
        self._api(
            "POST",
            f"/sheets/v2/spreadsheets/{spreadsheet_token}/dimension_range",
            json={
                "dimension": {
                    "sheetId": sheet_id,
                    "majorDimension": "COLUMNS",
                    "length": min_cols - actual_cols,
                }
            },
        )
        self.invalidate_cache(spreadsheet_token)

    def setup_multi_image_columns(self, spreadsheet_token: str,
                                  sheet_id: str,
                                  image_count: int) -> None:
        """给爆款图 sheet 追加 图片2/图片3... 表头和基础样式。"""
        if image_count <= 1:
            return
        # A-O 是主表，P 起放第 2 张图。image_count=2 -> 需要到 P 列。
        last_col_index = 15 + image_count - 1
        last_col = col_letter(last_col_index)
        self._ensure_min_columns(spreadsheet_token, sheet_id, last_col_index)

        headers = [f"图片{i}" for i in range(2, image_count + 1)]
        try:
            self.write_range(spreadsheet_token, sheet_id, f"P1:{last_col}1",
                             [headers])
        except Exception as e:
            print(f"⚠️ 多图表头写入失败：{e}")

        try:
            self._set_cell_style(
                spreadsheet_token, sheet_id, f"P1:{last_col}1",
                font={"bold": True, "fontSize": "14pt/1.5", "clean": False},
                fore_color="#FFFFFF",
                back_color="#1F4E79",
                h_align=1,
                v_align=1,
                borders={"type": "FULL_BORDER", "color": "#FFFFFF", "style": "1"},
            )
        except Exception:
            pass

        try:
            self._set_cell_style(
                spreadsheet_token, sheet_id, f"P2:{last_col}200",
                font={"fontSize": "11pt/1.5", "clean": False},
                h_align=1,
                v_align=1,
                borders={"type": "FULL_BORDER", "color": "#D1D5DB", "style": "1"},
            )
        except Exception:
            pass

        for idx in range(16, last_col_index + 1):
            try:
                self._api(
                    "POST",
                    f"/sheets/v2/spreadsheets/{spreadsheet_token}/dimension_range",
                    json={
                        "dimension": {
                            "sheetId": sheet_id,
                            "majorDimension": "COLUMNS",
                            "startIndex": idx - 1,
                            "endIndex": idx,
                        },
                        "dimensionProperties": {"fixedSize": 220},
                    },
                )
            except Exception:
                pass

    def upload_images_to_cells(self, spreadsheet_token: str, sheet_id: str,
                               row_index: int, image_bytes_list: list,
                               note_id: str = "noid") -> dict:
        """上传一组图片：第 1 张写 E 列，后续写 P/Q/R...。"""
        if not image_bytes_list:
            return {"ok": 0, "failed": []}
        self.setup_multi_image_columns(
            spreadsheet_token, sheet_id, len(image_bytes_list),
        )
        ok = 0
        failed = []
        for idx, image_bytes in enumerate(image_bytes_list, start=1):
            target_col = COL["cover"] if idx == 1 else col_letter(14 + idx)
            try:
                self.upload_image_to_cell(
                    spreadsheet_token, sheet_id, row_index, image_bytes,
                    f"image_{idx}_{note_id}.jpg",
                    col=target_col,
                )
                ok += 1
            except Exception as e:
                failed.append({"index": idx, "error": str(e)[:200]})
        return {"ok": ok, "failed": failed}

    def upload_profile_collect_images_to_cells(
        self,
        spreadsheet_token: str,
        sheet_id: str,
        row_index: int,
        image_bytes_list: list,
        image_cols: int = 1,
    ) -> dict:
        """账号全采集表：第 1 张写 I 列封面，同时图片 1..N 写 K/L/M...。"""
        if not image_bytes_list:
            return {"ok": 0, "failed": []}

        max_images = max(1, int(image_cols or 1))
        images = list(image_bytes_list or [])[:max_images]
        ok = 0
        failed = []

        def upload_one(col: str, image_bytes: bytes, name: str, index: int):
            nonlocal ok
            try:
                self.upload_image_to_cell(
                    spreadsheet_token, sheet_id, row_index, image_bytes,
                    name,
                    col=col,
                )
                ok += 1
            except Exception as e:
                failed.append({
                    "index": index,
                    "col": col,
                    "error": str(e)[:200],
                })

        upload_one("I", images[0], f"profile_cover_{row_index}.jpg", 1)
        image_start_col = len(PROFILE_COLLECT_BASE_HEADERS) + 1
        for idx, image_bytes in enumerate(images, start=1):
            target_col = col_letter(image_start_col + idx - 1)
            upload_one(
                target_col,
                image_bytes,
                f"profile_image_{idx}_{row_index}.jpg",
                idx,
            )

        return {"ok": ok, "failed": failed}

    # ---------- Sheet 管理（v3.1 新增）----------

    def create_sheet(self, spreadsheet_token: str, title: str,
                     index: Optional[int] = None) -> dict:
        """新建一个 sheet。返回 {sheet_id, title, index}。"""
        body = {"requests": [{
            "addSheet": {
                "properties": {"title": title, **({"index": index} if index is not None else {})}
            }
        }]}
        data = self._api(
            "POST",
            f"/sheets/v2/spreadsheets/{spreadsheet_token}/sheets_batch_update",
            json=body,
        )
        replies = data.get("data", {}).get("replies", [])
        if not replies:
            raise LarkAPIError("create_sheet 返回 replies 为空")
        props = replies[0].get("addSheet", {}).get("properties", {})
        return {
            "sheet_id": props.get("sheetId"),
            "title": props.get("title"),
            "index": props.get("index"),
        }

    def rename_sheet(self, spreadsheet_token: str, sheet_id: str,
                     title: str) -> dict:
        """重命名一个 sheet。"""
        body = {
            "requests": [{
                "updateSheet": {
                    "properties": {
                        "sheetId": sheet_id,
                        "title": title,
                    }
                }
            }]
        }
        res = self._api(
            "POST",
            f"/sheets/v2/spreadsheets/{spreadsheet_token}/sheets_batch_update",
            json=body,
        )
        self.invalidate_cache(spreadsheet_token)
        return res

    def delete_sheet(self, spreadsheet_token: str, sheet_id: str) -> dict:
        """删除一个 sheet（高风险，慎用）。"""
        body = {"requests": [{"deleteSheet": {"sheetId": sheet_id}}]}
        return self._api(
            "POST",
            f"/sheets/v2/spreadsheets/{spreadsheet_token}/sheets_batch_update",
            json=body,
        )

    def setup_sheet_template(self, spreadsheet_token: str, sheet_id: str):
        """为新建的 sheet 应用统一模板：
        14 列表头 + 列宽 + 行高 + 冻结首行 + 状态下拉 +
        🆕 表头美化（加粗/居中/浅灰底/边框）+ 数据行斑马纹 + 全表边框。

        所有步骤失败都不抛异常，单步降级，确保至少写入表头。

        样式规格（v4.3.7 升级深蓝表头 + 修 O 列范围 bug）：
        - 表头 #1F4E79 深蓝底 / #FFFFFF 白字 / 14px / 加粗 / 居中 / 边框
        - 数据行 12px / #374151 字 / 偶数行 #F3F6FB 淡蓝灰底 / 全边框
        - 表头行高 32 / 列宽按内容定制
        - 冻结第 1 行 + 第 A 列
        """
        # 1. 写表头（v4.3.6 B037 加 O 列「话题标签」）
        try:
            self.write_range(spreadsheet_token, sheet_id, "A1:O1",
                             [list(NOTE_HEADERS)])
        except Exception:
            pass

        # 2. 列宽（按内容合理分配，参考 popup.js 实际写入字段）
        # A 序号窄 / B URL 中 / C 状态 / D 标题宽 / E 封面图 / F 文案最宽 / G-J 数字 / K note_id / L 时间 / M 来源 / N 备注宽 / O 标签宽
        col_widths = {
            "A": 60,   # 序号
            "B": 240,  # 笔记链接
            "C": 100,  # 状态
            "D": 280,  # 标题
            "E": 220,  # 封面图（保持原值，配合 260 行高）
            "F": 400,  # 文案
            "G": 70,   # 点赞
            "H": 70,   # 收藏
            "I": 70,   # 评论
            "J": 70,   # 分享
            "K": 180,  # 笔记ID
            "L": 130,  # 采集时间
            "M": 100,  # 来源
            "N": 220,  # 我的备注
            "O": 300,  # 话题标签（v4.3.6）
        }
        for col, width in col_widths.items():
            col_idx = ord(col) - ord("A")
            try:
                self._api(
                    "POST",
                    f"/sheets/v2/spreadsheets/{spreadsheet_token}/dimension_range",
                    json={
                        "dimension": {
                            "sheetId": sheet_id,
                            "majorDimension": "COLUMNS",
                            "startIndex": col_idx,
                            "endIndex": col_idx + 1,
                        },
                        "dimensionProperties": {"fixedSize": width},
                    },
                )
            except Exception:
                pass

        # 3. 冻结首行 + 冻结 A 列（序号列）
        try:
            self._api(
                "POST",
                f"/sheets/v2/spreadsheets/{spreadsheet_token}/sheets_batch_update",
                json={"requests": [{
                    "updateSheet": {
                        "properties": {
                            "sheetId": sheet_id,
                            "frozenRowCount": 1,
                            "frozenColCount": 1,
                        }
                    }
                }]},
            )
        except Exception:
            pass

        # 4. C 列状态下拉（待采集 / ✅ 已采集 / ❌ 失败）
        try:
            self._api(
                "POST",
                f"/sheets/v2/spreadsheets/{spreadsheet_token}/dataValidation",
                json={
                    "range": f"{sheet_id}!C2:C1000",
                    "dataValidationType": "list",
                    "dataValidation": {
                        "conditionValues": ["待采集", "✅ 已采集", "❌ 失败"],
                        "options": {
                            "multipleValues": False,
                            "highlightValidData": True,
                            "colors": ["#FFA940", "#52C41A", "#F5222D"],
                        },
                    },
                },
            )
        except Exception:
            pass

        # 5. 🆕 表头样式（v4.3.7 升级：深蓝底 + 白字 + 加粗 + 居中 + 边框）
        # ⚠️ 旧版本写的是 "A1:N1"，导致 O 列「话题标签」表头吃不到样式 — 这次顺手修
        try:
            self._set_cell_style(
                spreadsheet_token, sheet_id, f"A1:{LAST_COL}1",
                font={"bold": True, "fontSize": "14pt/1.5", "clean": False},
                fore_color="#FFFFFF",       # 白字
                back_color="#1F4E79",       # 深蓝底
                h_align=1,                  # 1=居中
                v_align=1,                  # 1=居中
                borders={
                    "type": "FULL_BORDER",
                    "color": "#FFFFFF",     # 白色细边（深蓝底上看着干净）
                    "style": "1",          # 1=细实线
                },
            )
        except Exception as e:
            print(f"⚠️ 表头样式设置失败：{e}")

        # 6. 🆕 表头行高（32px）
        try:
            self.set_row_height(spreadsheet_token, sheet_id, 1, height=32)
        except Exception:
            pass

        # 7. 🆕 数据行斑马纹 + 边框
        #    先查当前 sheet 实际行数，避免 90202 越界错误
        #    飞书新建 sheet 默认 200 行，超过会报 "range exceeds grid limits"
        actual_rows = self._get_sheet_row_count(spreadsheet_token, sheet_id)
        # 目标 row_end：扩到 1000 行（够用 5 年）
        target_end = 1000
        if actual_rows < target_end:
            # 用 dimension_range 追加行 → 飞书 API 接受 length 字段在 dimension 内
            try:
                self._api(
                    "POST",
                    f"/sheets/v2/spreadsheets/{spreadsheet_token}/dimension_range",
                    json={
                        "dimension": {
                            "sheetId": sheet_id,
                            "majorDimension": "ROWS",
                            "length": target_end - actual_rows,
                        }
                    },
                )
                actual_rows = target_end
                print(f"  ✓ 已扩展到 {target_end} 行")
            except Exception as e:
                print(f"⚠️ 扩展 sheet 行数失败（按现有 {actual_rows} 行处理）：{e}")

        row_end = min(actual_rows, target_end)
        try:
            self._apply_zebra_stripes(spreadsheet_token, sheet_id,
                                       row_start=2,
                                       row_end=row_end,
                                       last_col=LAST_COL)  # v4.3.6 B037：跟 O 列
        except Exception as e:
            print(f"⚠️ 斑马纹设置失败：{e}")

        # 8. 🆕 B034 v2 全表数据行行高强制 32px（用户选方案 A：行高完全统一）
        #
        # 飞书 style API 没有公开 wrap/wrapStrategy 字段（已查官方文档确认），
        # 唯一能压住长文案的办法 = 用 fixedSize 强制行高。
        # 飞书的 fixedSize 是"硬约束"：内容超出会被截断展示，用户双击单元格看全文。
        #
        # v1 设计错误：保护已有数据行 → 用户的"行高不统一"痛点没解决
        # v2 设计：全表数据行（含旧封面图行）一律 32px，接受封面图被压成 32px 缩略
        #          用户双击图片单元格可看完整大图（飞书标准行为）
        try:
            # 分段批量设（避免一次范围过大触发飞书 API 限制）
            BATCH = 100
            fail = 0
            for s in range(2, row_end + 1, BATCH):
                e = min(s + BATCH - 1, row_end)
                try:
                    self.set_row_height_range(spreadsheet_token, sheet_id,
                                               start_row=s, end_row=e,
                                               height=32)
                except Exception as ex:
                    fail += 1
                    if fail == 1:
                        print(f"⚠️ 行高段 {s}-{e} 失败：{ex}")
            print(f"  ✓ 全表数据行行高 32px（含所有旧封面图行）")
        except Exception as e:
            print(f"⚠️ 行高分段设置失败：{e}")

    def _get_sheet_row_count(self, spreadsheet_token: str,
                              sheet_id: str) -> int:
        """查询单个 sheet 的当前行数（metainfo API）。失败返回 200（飞书默认）。"""
        try:
            sheets = self.get_sheets_info(spreadsheet_token, use_cache=False)
            for s in sheets:
                if s["sheet_id"] == sheet_id:
                    return int(s.get("row_count") or 200)
        except Exception:
            pass
        return 200

    # ---------- 样式工具方法（v3.2 新增）----------

    def _set_cell_style(self, spreadsheet_token: str, sheet_id: str,
                        cell_range: str,
                        font: dict = None,
                        fore_color: str = None,
                        back_color: str = None,
                        h_align: int = None,
                        v_align: int = None,
                        borders: dict = None) -> dict:
        """统一封装的单元格样式设置（飞书 v2 style API）。

        参数：
          cell_range: 'A1:N1' 或 'A2:N1000'
          font: {'bold': True, 'fontSize': '13pt/1.5', 'italic': False, 'clean': bool}
          fore_color: 字体颜色（hex 字符串）
          back_color: 背景色（hex 字符串）
          h_align: 0=左 1=中 2=右
          v_align: 0=上 1=中 2=下
          borders: {'type': 'FULL_BORDER', 'color': '#E5E7EB', 'style': '1'}

        API 文档：https://open.feishu.cn/document/server-docs/docs/sheets-v3/data-operation/set-cell-style
        """
        style = {}
        if font:
            style["font"] = font
        if fore_color:
            style["foreColor"] = fore_color
        if back_color:
            style["backColor"] = back_color
        if h_align is not None:
            style["hAlign"] = h_align
        if v_align is not None:
            style["vAlign"] = v_align
        if borders:
            style["borderType"] = borders.get("type", "FULL_BORDER")
            style["borderColor"] = borders.get("color", "#E5E7EB")
            style["borderStyle"] = borders.get("style", "1")
        full_range = f"{sheet_id}!{cell_range}"
        body = {
            "appendStyle": {
                "range": full_range,
                "style": style,
            }
        }
        return self._api(
            "PUT",
            f"/sheets/v2/spreadsheets/{spreadsheet_token}/style",
            json=body,
        )

    def _apply_zebra_stripes(self, spreadsheet_token: str, sheet_id: str,
                              row_start: int = 2, row_end: int = 1000,
                              last_col: str = "N"):
        """数据区基础样式 + 斑马纹。

        策略：
        - Step 1：用 `appendStyle` 一次性给整段（A2:N1000）设 12px / 深灰字 / 垂直居中 / 细边框
        - Step 2：用 `condition_formats` 接口加条件格式公式 `=MOD(ROW(),2)=0`，
          偶数行自动刷 #F9FAFB 浅灰底（条件格式比静态上色性能高 100 倍）

        失败降级：condition_formats 接口部分租户/版本可能不支持，失败则只保留基础样式。
        """
        # 1. 整段加边框 + 深灰字 + 12px + 垂直居中（一次性覆盖整段，单次 API 调用）
        try:
            self._set_cell_style(
                spreadsheet_token, sheet_id,
                f"A{row_start}:{last_col}{row_end}",
                font={"fontSize": "12pt/1.5", "clean": False},
                fore_color="#374151",
                v_align=1,
                borders={
                    "type": "FULL_BORDER",
                    "color": "#E5E7EB",
                    "style": "1",
                },
            )
        except Exception as e:
            print(f"⚠️ 数据区基础样式失败：{e}")

        # 2. 斑马纹：用 batch styles API 批量上色偶数行
        #
        # 不走条件格式 API（接口字段名飞书文档前后不一致，9499 缺参数错误难修）。
        # 改用 styles_batch_update，一次可发多个 range（最多 100 个/次）。
        # 1000 行约 500 个偶数行 → 5 次 API 调用搞定，约 1-2 秒/sheet。
        even_rows = [r for r in range(row_start, row_end + 1) if r % 2 == 0]
        BATCH = 100
        success_batches = 0
        failed_batches = 0
        for i in range(0, len(even_rows), BATCH):
            chunk = even_rows[i:i + BATCH]
            data = [
                {
                    "ranges": [f"{sheet_id}!A{r}:{last_col}{r}"],
                    "style": {"backColor": "#F3F6FB"},  # v4.3.7 淡蓝灰，比 #F9FAFB 更明显
                }
                for r in chunk
            ]
            try:
                self._api(
                    "PUT",
                    f"/sheets/v2/spreadsheets/{spreadsheet_token}/styles_batch_update",
                    json={"data": data},
                )
                success_batches += 1
            except Exception as e:
                failed_batches += 1
                if failed_batches == 1:
                    print(f"⚠️ 斑马纹 batch 失败：{e}")
        if failed_batches == 0:
            print(f"  ✓ 斑马纹完成（{len(even_rows)} 行偶数底色 / {success_batches} batches）")

    # ---------- 元数据查询 ----------

    def get_sheets_info(self, spreadsheet_token: str,
                        use_cache: bool = True) -> list:
        """获取电子表格里所有 sheet 的列表，返回 [{sheet_id, title, index}, ...]"""
        if use_cache:
            cached = self._sheets_cache.get(spreadsheet_token)
            if cached and time.time() - cached[0] < self._sheets_cache_ttl:
                return cached[1]
        data = self._api(
            "GET",
            f"/sheets/v2/spreadsheets/{spreadsheet_token}/metainfo",
        )
        sheets = data.get("data", {}).get("sheets", [])
        result = [
            {
                "sheet_id": s.get("sheetId"),
                "title": s.get("title"),
                "index": s.get("index"),
                "row_count": s.get("rowCount"),
                "col_count": s.get("columnCount"),
            }
            for s in sheets
        ]
        self._sheets_cache[spreadsheet_token] = (time.time(), result)
        return result

    # ---------- 业务方法 ----------

    def load_existing_ids_and_next_row(self, spreadsheet_token: str,
                                       sheet_id: str) -> tuple:
        """读全表，返回 (已有 note_id 集合, 下一空行行号, 当前最大序号)。"""
        rows = self.read_range(spreadsheet_token, sheet_id, "A1:N1000")
        existing_ids = set()
        max_seq = 0
        next_row = 2
        for i, row in enumerate(rows[1:], start=2):
            if not row:
                continue
            seq_cell = row[0] if len(row) > 0 else None
            url_cell = row[1] if len(row) > 1 else None
            note_id_cell = row[10] if len(row) > 10 else None
            has_content = (seq_cell not in (None, "")) or (url_cell not in (None, ""))
            if has_content:
                next_row = i + 1
                if isinstance(seq_cell, (int, float)):
                    max_seq = max(max_seq, int(seq_cell))
                if isinstance(note_id_cell, str) and note_id_cell:
                    existing_ids.add(note_id_cell.strip())
        return existing_ids, next_row, max_seq

    def find_row_by_note_id(self, spreadsheet_token: str, sheet_id: str,
                            note_id: str) -> Optional[int]:
        """根据 note_id 找原始数据所在行号。"""
        rows = self.read_range(spreadsheet_token, sheet_id, "A1:K1000")
        for i, row in enumerate(rows[1:], start=2):
            if len(row) > 10 and isinstance(row[10], str) and row[10].strip() == note_id:
                return i
        return None

    def _build_notes_index(self, spreadsheet_token: str) -> dict:
        """构建 note_id → {sheet_id, sheet_title, row} 的索引（带缓存）。

        每 30 秒重建一次。一次性读所有 sheet 的 A1:K1000（只读到 K 列）。
        """
        cached = self._notes_cache.get(spreadsheet_token)
        if cached and time.time() - cached[0] < self._notes_cache_ttl:
            return cached[1]
        sheets = self.get_sheets_info(spreadsheet_token)
        index = {}
        for sheet in sheets:
            sid = sheet["sheet_id"]
            try:
                rows = self.read_range(spreadsheet_token, sid, "A1:K1000")
            except LarkAPIError:
                continue
            for i, row in enumerate(rows[1:], start=2):
                if not row or len(row) <= 10:
                    continue
                nid = row[10]
                if isinstance(nid, str) and nid.strip():
                    index[nid.strip()] = {
                        "sheet_id": sid,
                        "sheet_title": sheet["title"],
                        "row": i,
                    }
        self._notes_cache[spreadsheet_token] = (time.time(), index)
        return index

    def find_row_across_sheets(self, spreadsheet_token: str,
                               note_id: str) -> Optional[dict]:
        """跨所有 sheet 查找笔记。用缓存加速（30 秒 TTL）。"""
        index = self._build_notes_index(spreadsheet_token)
        return index.get(note_id)

    def build_row(self, seq: int, data: dict, source: str,
                  note: str = "", tags: list = None) -> list:
        url = data.get("url", "")
        notes_field = note or ""
        if tags:
            tag_str = " ".join(f"#{t}" for t in tags if t)
            notes_field = f"{tag_str} {notes_field}".strip() if notes_field else tag_str
        # v4.3.6 B037：F 列文案先 extract hashtag → O 列「话题标签」，F 只剩纯文案
        raw_desc = data.get("desc", "")
        clean_desc, hashtags = extract_hashtags(flatten_desc(raw_desc))
        return [
            seq,
            {"type": "url", "text": url, "link": url},
            "✅ 已采集",
            data.get("title", ""),
            "",  # E 列封面图占位
            clean_desc,  # F: 纯文案（hashtag 已拆出）
            data.get("liked", 0),
            data.get("collected", 0),
            data.get("comment", 0),
            data.get("share", 0),
            data.get("note_id", ""),
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            source,
            notes_field,
            hashtags,  # O: 话题标签
        ]

    def build_failure_row(self, seq: int, url: str, error: str,
                          source: str, note: str = "") -> list:
        return [
            seq,
            {"type": "url", "text": url, "link": url},
            "❌ 失败",
            "", "", "",
            0, 0, 0, 0, "",
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            source,
            f"采集失败：{error[:200]}" + (f" | 备注：{note}" if note else ""),
            "",  # O: 话题标签（失败行没有）
        ]

    def write_record(self, spreadsheet_token: str, sheet_id: str,
                     row_idx: int, seq: int, data: dict, source: str,
                     note: str = "", tags: list = None,
                     image_bytes: bytes = None,
                     image_bytes_list: list = None) -> dict:
        """写入一条成功的采集数据。"""
        row = self.build_row(seq, data, source, note=note, tags=tags)
        self.write_range(spreadsheet_token, sheet_id,
                         f"A{row_idx}:{LAST_COL}{row_idx}", [row])

        cover_status = "ok"
        images = list(image_bytes_list or [])
        if not images and image_bytes:
            images = [image_bytes]
        if images:
            try:
                img_res = self.upload_images_to_cells(
                    spreadsheet_token, sheet_id, row_idx, images,
                    data.get("note_id", "noid"),
                )
                if img_res["failed"]:
                    cover_status = (
                        f"图片部分失败: 成功 {img_res['ok']} 张，"
                        f"失败 {len(img_res['failed'])} 张"
                    )
            except Exception as e:
                cover_status = f"图片失败: {e}"
                self.write_range(
                    spreadsheet_token, sheet_id,
                    f"N{row_idx}:N{row_idx}",
                    [[f"⚠️ 封面图嵌入失败: {e}"]],
                )
        # v4.3.0 B034 v2 修订：删掉旧的 set_row_height(260)
        # 原本写入后强制 260px 让封面图大显示，但跟方案 A（全表 32px 统一行高）冲突
        # → 现在保持模板预设的 32px（backfill + setup_sheet_template 已批量设置）
        # 封面图被压成 32px 小缩略，用户双击图片单元格可看完整大图
        return {"row": row_idx, "cover": cover_status}

    def write_failure(self, spreadsheet_token: str, sheet_id: str,
                      row_idx: int, seq: int, url: str,
                      error: str, source: str, note: str = ""):
        row = self.build_failure_row(seq, url, error, source, note=note)
        self.write_range(spreadsheet_token, sheet_id,
                         f"A{row_idx}:{LAST_COL}{row_idx}", [row])

    # ---------- 整店/账号全采集（v4.5.0 新增）----------

    def profile_collect_sheet_title(self, account_name: str) -> str:
        base = sanitize_sheet_title(account_name or "账号")
        suffix = "全采集"
        max_base_len = 30 - len(suffix)
        return f"{base[:max_base_len]}{suffix}"

    def ensure_profile_collect_sheet(self, spreadsheet_token: str,
                                     account_name: str,
                                     image_cols: int = 1) -> dict:
        """确保「XX全采集」sheet 存在并套整店采集模板。"""
        title = self.profile_collect_sheet_title(account_name)
        sheets = self.get_sheets_info(spreadsheet_token, use_cache=False)
        for sheet in sheets:
            if sheet["title"] == title:
                self.setup_profile_collect_template(
                    spreadsheet_token, sheet["sheet_id"], image_cols=image_cols,
                )
                return {
                    "sheet_id": sheet["sheet_id"],
                    "title": title,
                    "created": False,
                }

        new_sheet = self.create_sheet(spreadsheet_token, title)
        self.setup_profile_collect_template(
            spreadsheet_token, new_sheet["sheet_id"], image_cols=image_cols,
        )
        self.invalidate_cache(spreadsheet_token)
        return {
            "sheet_id": new_sheet["sheet_id"],
            "title": title,
            "created": True,
        }

    def setup_profile_collect_template(self, spreadsheet_token: str,
                                       sheet_id: str,
                                       image_cols: int = 1) -> None:
        """整店采集表模板：标题/文案/标签/图片下载链接。"""
        image_cols = max(1, int(image_cols or 1))
        last_col_index = (
            len(PROFILE_COLLECT_BASE_HEADERS) + image_cols +
            len(PROFILE_COLLECT_META_HEADERS)
        )
        last_col = col_letter(last_col_index)
        self._ensure_min_columns(spreadsheet_token, sheet_id, last_col_index)

        headers = (
            list(PROFILE_COLLECT_BASE_HEADERS) +
            [f"图片{i}" for i in range(1, image_cols + 1)] +
            list(PROFILE_COLLECT_META_HEADERS)
        )
        try:
            self.write_range(spreadsheet_token, sheet_id,
                             f"A1:{last_col}1", [headers])
        except Exception as e:
            print(f"⚠️ 整店采集表头写入失败：{e}")

        try:
            self._set_cell_style(
                spreadsheet_token, sheet_id, f"A1:{last_col}1",
                font={"bold": True, "fontSize": "14pt/1.5", "clean": False},
                fore_color="#FFFFFF",
                back_color="#1F4E79",
                h_align=1,
                v_align=1,
                borders={"type": "FULL_BORDER", "color": "#FFFFFF", "style": "1"},
            )
        except Exception as e:
            print(f"⚠️ 整店采集表头样式失败：{e}")

        actual_rows = self._get_sheet_row_count(spreadsheet_token, sheet_id)
        target_end = 1000
        if actual_rows < target_end:
            try:
                self._api(
                    "POST",
                    f"/sheets/v2/spreadsheets/{spreadsheet_token}/dimension_range",
                    json={
                        "dimension": {
                            "sheetId": sheet_id,
                            "majorDimension": "ROWS",
                            "length": target_end - actual_rows,
                        }
                    },
                )
                actual_rows = target_end
            except Exception as e:
                print(f"⚠️ 整店采集扩展行数失败：{e}")
        row_end = min(actual_rows, target_end)

        try:
            self._apply_zebra_stripes(
                spreadsheet_token, sheet_id,
                row_start=2, row_end=row_end, last_col=last_col,
            )
        except Exception as e:
            print(f"⚠️ 整店采集斑马纹失败：{e}")

        col_widths = {
            1: 60,    # 序号
            2: 160,   # 店铺/账号名
            3: 240,   # 主页链接
            4: 280,   # 笔记标题
            5: 420,   # 图文文案
            6: 260,   # 话题标签
            7: 240,   # 笔记链接
            8: 80,    # 图片数量
            9: 220,   # 封面图
            10: 320,  # 全部图片下载链接
        }
        image_start = len(PROFILE_COLLECT_BASE_HEADERS) + 1
        for idx in range(image_start, image_start + image_cols):
            col_widths[idx] = 220
        meta_start = image_start + image_cols
        col_widths[meta_start] = 140
        col_widths[meta_start + 1] = 120
        col_widths[meta_start + 2] = 90
        for idx, width in col_widths.items():
            try:
                self._api(
                    "POST",
                    f"/sheets/v2/spreadsheets/{spreadsheet_token}/dimension_range",
                    json={
                        "dimension": {
                            "sheetId": sheet_id,
                            "majorDimension": "COLUMNS",
                            "startIndex": idx - 1,
                            "endIndex": idx,
                        },
                        "dimensionProperties": {"fixedSize": width},
                    },
                )
            except Exception:
                pass

        try:
            self.set_row_height(spreadsheet_token, sheet_id, 1, height=40)
        except Exception:
            pass
        try:
            self.set_row_height_range(
                spreadsheet_token, sheet_id, start_row=2,
                end_row=min(row_end, 1000), height=80,
            )
        except Exception:
            pass
        try:
            self._api(
                "POST",
                f"/sheets/v2/spreadsheets/{spreadsheet_token}/sheets_batch_update",
                json={"requests": [{
                    "updateSheet": {
                        "properties": {
                            "sheetId": sheet_id,
                            "frozenRowCount": 1,
                            "frozenColCount": 1,
                        }
                    }
                }]},
            )
        except Exception:
            pass

    @staticmethod
    def _url_cell(url: str, text: str = None):
        url = (url or "").strip()
        if not url:
            return ""
        return {"type": "url", "text": text or url, "link": url}

    def _profile_collect_existing_urls(self, spreadsheet_token: str,
                                       sheet_id: str) -> set:
        row_count = max(1000, self._get_sheet_row_count(
            spreadsheet_token, sheet_id,
        ))
        rows = self.read_range(
            spreadsheet_token, sheet_id, f"G1:G{row_count}",
        )
        existing = set()
        for row in rows[1:]:
            if not row:
                continue
            cell = row[0]
            url = ""
            if isinstance(cell, str):
                url = cell
            elif isinstance(cell, dict):
                url = cell.get("link") or cell.get("text") or ""
            elif isinstance(cell, list):
                for seg in cell:
                    if isinstance(seg, dict):
                        url = seg.get("link") or seg.get("text") or ""
                        if url:
                            break
            if url:
                existing.add(url.strip())
        return existing

    def _profile_collect_next_row(self, spreadsheet_token: str,
                                  sheet_id: str) -> tuple:
        row_count = max(1000, self._get_sheet_row_count(
            spreadsheet_token, sheet_id,
        ))
        rows = self.read_range(
            spreadsheet_token, sheet_id, f"A1:A{row_count}",
        )
        next_row = 2
        max_seq = 0
        for i, row in enumerate(rows[1:], start=2):
            if not row:
                continue
            seq = row[0]
            if seq in (None, ""):
                continue
            next_row = i + 1
            try:
                max_seq = max(max_seq, int(seq))
            except Exception:
                pass
        return next_row, max_seq

    def build_profile_collect_row(self, seq: int, record: dict,
                                  source: str, image_cols: int) -> list:
        text = flatten_desc(record.get("text", "") or "")
        clean_text, tags = extract_hashtags(text)
        image_urls = list(record.get("image_urls") or [])
        cover_url = image_urls[0] if image_urls else ""
        row = [
            seq,
            record.get("account_name", ""),
            self._url_cell(record.get("profile_url", ""), "主页"),
            record.get("title", ""),
            clean_text,
            tags,
            self._url_cell(record.get("post_url", ""), "打开笔记"),
            len(image_urls),
            self._url_cell(cover_url, "封面"),
            "  ".join(image_urls),
        ]
        for idx in range(image_cols):
            url = image_urls[idx] if idx < len(image_urls) else ""
            row.append(self._url_cell(url, f"图片{idx + 1}") if url else "")
        row.extend([
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            source,
            "✅ 已采集",
        ])
        return row

    def build_profile_collect_failure_row(self, seq: int, failure: dict,
                                          account_name: str,
                                          profile_url: str, source: str,
                                          image_cols: int) -> list:
        post_url = (failure.get("url") or "").strip()
        error = (failure.get("error") or "").strip()
        row = [
            seq,
            account_name,
            self._url_cell(profile_url, "主页"),
            "采集失败",
            f"失败原因：{error[:300]}",
            "",
            self._url_cell(post_url, "打开笔记"),
            0,
            "",
            "",
        ]
        for _ in range(image_cols):
            row.append("")
        row.extend([
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            source,
            "❌ 失败",
        ])
        return row

    def append_profile_collect_failure(self, spreadsheet_token: str,
                                       sheet_id: str, failure: dict,
                                       account_name: str,
                                       profile_url: str,
                                       source: str = "账号全采集",
                                       image_cols: int = 1) -> dict:
        next_row, max_seq = self._profile_collect_next_row(
            spreadsheet_token, sheet_id,
        )
        seq = max_seq + 1
        row = self.build_profile_collect_failure_row(
            seq, failure, account_name, profile_url,
            source=source, image_cols=image_cols,
        )
        last_col_index = (
            len(PROFILE_COLLECT_BASE_HEADERS) + image_cols +
            len(PROFILE_COLLECT_META_HEADERS)
        )
        last_col = col_letter(last_col_index)
        self.write_range(
            spreadsheet_token, sheet_id,
            f"A{next_row}:{last_col}{next_row}",
            [row],
        )
        self.invalidate_cache(spreadsheet_token)
        return {"written": 1, "row": next_row, "seq": seq}

    def overwrite_profile_collect_record(self, spreadsheet_token: str,
                                         sheet_id: str, row_idx: int,
                                         seq: int, record: dict,
                                         source: str = "账号全采集",
                                         image_cols: int = 1) -> dict:
        row = self.build_profile_collect_row(
            seq, record, source=source, image_cols=image_cols,
        )
        last_col_index = (
            len(PROFILE_COLLECT_BASE_HEADERS) + image_cols +
            len(PROFILE_COLLECT_META_HEADERS)
        )
        last_col = col_letter(last_col_index)
        self.write_range(
            spreadsheet_token, sheet_id,
            f"A{row_idx}:{last_col}{row_idx}",
            [row],
        )
        images = list(record.get("image_bytes_list") or [])
        image_failed = []
        image_ok = 0
        if images:
            try:
                img_res = self.upload_profile_collect_images_to_cells(
                    spreadsheet_token,
                    sheet_id,
                    row_idx,
                    images,
                    image_cols=image_cols,
                )
                image_ok = int(img_res.get("ok") or 0)
                image_failed = img_res.get("failed") or []
            except Exception as e:
                image_failed.append({"row": row_idx, "error": str(e)[:200]})
        self.invalidate_cache(spreadsheet_token)
        return {
            "written": 1,
            "row": row_idx,
            "image_uploaded": image_ok,
            "image_failed": image_failed,
        }

    def overwrite_profile_collect_failure(self, spreadsheet_token: str,
                                          sheet_id: str, row_idx: int,
                                          seq: int, failure: dict,
                                          account_name: str,
                                          profile_url: str,
                                          source: str = "账号全采集",
                                          image_cols: int = 1) -> dict:
        row = self.build_profile_collect_failure_row(
            seq, failure, account_name, profile_url,
            source=source, image_cols=image_cols,
        )
        last_col_index = (
            len(PROFILE_COLLECT_BASE_HEADERS) + image_cols +
            len(PROFILE_COLLECT_META_HEADERS)
        )
        last_col = col_letter(last_col_index)
        self.write_range(
            spreadsheet_token, sheet_id,
            f"A{row_idx}:{last_col}{row_idx}",
            [row],
        )
        self.invalidate_cache(spreadsheet_token)
        return {"written": 1, "row": row_idx}

    def append_profile_collect_records(self, spreadsheet_token: str,
                                       sheet_id: str,
                                       records: list,
                                       source: str = "账号全采集",
                                       image_cols: int = 1) -> dict:
        existing_urls = self._profile_collect_existing_urls(
            spreadsheet_token, sheet_id,
        )
        next_row, max_seq = self._profile_collect_next_row(
            spreadsheet_token, sheet_id,
        )
        rows = []
        written_records = []
        skipped = 0
        seq = max_seq
        for record in records:
            post_url = (record.get("post_url") or "").strip()
            if post_url and post_url in existing_urls:
                skipped += 1
                continue
            seq += 1
            rows.append(
                self.build_profile_collect_row(
                    seq, record, source=source, image_cols=image_cols,
                )
            )
            written_records.append(record)
            if post_url:
                existing_urls.add(post_url)

        if not rows:
            return {"written": 0, "skipped": skipped, "start_row": next_row}

        last_col_index = (
            len(PROFILE_COLLECT_BASE_HEADERS) + image_cols +
            len(PROFILE_COLLECT_META_HEADERS)
        )
        last_col = col_letter(last_col_index)
        end_row = next_row + len(rows) - 1
        self.write_range(
            spreadsheet_token, sheet_id,
            f"A{next_row}:{last_col}{end_row}",
            rows,
        )
        image_ok = 0
        image_failed = []
        for offset, record in enumerate(written_records):
            images = list(record.get("image_bytes_list") or [])
            if not images:
                continue
            row_index = next_row + offset
            try:
                img_res = self.upload_profile_collect_images_to_cells(
                    spreadsheet_token,
                    sheet_id,
                    row_index,
                    images,
                    image_cols=image_cols,
                )
                image_ok += int(img_res.get("ok") or 0)
                image_failed.extend(img_res.get("failed") or [])
            except Exception as e:
                image_failed.append({
                    "row": row_index,
                    "error": str(e)[:200],
                })
        self.invalidate_cache(spreadsheet_token)
        return {
            "written": len(rows),
            "skipped": skipped,
            "start_row": next_row,
            "end_row": end_row,
            "image_uploaded": image_ok,
            "image_failed": image_failed,
        }

    # ---------- 仪表盘 / 历史（v3.1 新增）----------

    def load_failures(self, spreadsheet_token: str,
                      use_cache: bool = True) -> list:
        """遍历所有 sheet，找出 C 列状态为「❌ 失败」的行（缓存 30 秒）。"""
        if use_cache:
            cached = self._failures_cache.get(spreadsheet_token)
            if cached and time.time() - cached[0] < self._failures_cache_ttl:
                return cached[1]
        sheets = self.get_sheets_info(spreadsheet_token)
        failures = []
        for sheet in sheets:
            sid = sheet["sheet_id"]
            try:
                rows = self.read_range(spreadsheet_token, sid, "A1:N1000")
            except LarkAPIError:
                continue
            header = rows[0] if rows else []
            def header_cell(idx):
                value = header[idx] if len(header) > idx else ""
                if isinstance(value, str):
                    return value
                if isinstance(value, list) and value:
                    first = value[0]
                    if isinstance(first, dict):
                        return first.get("text") or ""
                return ""
            if not (
                header_cell(1) == "笔记链接"
                and header_cell(2) == "状态"
                and header_cell(3) == "标题"
            ):
                continue
            for i, row in enumerate(rows[1:], start=2):
                if not row:
                    continue
                def cell(idx):
                    return row[idx] if len(row) > idx else None
                status_cell = cell(2)
                status_str = ""
                if isinstance(status_cell, str):
                    status_str = status_cell
                elif isinstance(status_cell, list) and status_cell:
                    first = status_cell[0]
                    if isinstance(first, dict):
                        status_str = first.get("text") or ""
                if "失败" not in status_str:
                    continue
                # 提取 URL（B 列）
                url_cell = cell(1)
                link_str = ""
                if isinstance(url_cell, list) and url_cell:
                    first = url_cell[0]
                    if isinstance(first, dict):
                        link_str = first.get("link") or ""
                elif isinstance(url_cell, str):
                    link_str = url_cell
                # 错误备注（N 列）
                note_cell = cell(13)
                note_str = note_cell if isinstance(note_cell, str) else ""
                time_cell = cell(11)
                time_str = time_cell if isinstance(time_cell, str) else ""
                failures.append({
                    "sheet_id": sid,
                    "sheet_title": sheet["title"],
                    "row": i,
                    "url": link_str,
                    "error": note_str,
                    "time": time_str,
                })
        # 时间倒序
        failures.sort(key=lambda r: r["time"], reverse=True)
        self._failures_cache[spreadsheet_token] = (time.time(), failures)
        return failures

    def retry_failure(self, spreadsheet_token: str, sheet_id: str,
                      row_idx: int) -> str:
        """读失败行的 B 列 URL（用于重试）。"""
        rows = self.read_range(spreadsheet_token, sheet_id,
                               f"B{row_idx}:B{row_idx}")
        if not rows or not rows[0]:
            return ""
        cell = rows[0][0]
        if isinstance(cell, str):
            return cell
        if isinstance(cell, list) and cell:
            first = cell[0]
            if isinstance(first, dict):
                return first.get("link") or ""
        return ""

    def load_dashboard(self, spreadsheet_token: str,
                       recent_limit: int = 5,
                       use_cache: bool = True) -> dict:
        """遍历所有 sheet，返回统计数据和最近 N 条记录（缓存 30 秒）。

        统计：
          - today: 今天采集数
          - this_week: 本周采集数
          - total: 累计采集数（不含失败、不含残缺数据）
          - failed_total: 累计失败数
        最近 N 条按时间倒序。
        """
        if use_cache:
            cached = self._dashboard_cache.get(spreadsheet_token)
            if cached and time.time() - cached[0] < self._dashboard_cache_ttl:
                # 仅 recent 数量可能跟请求不同，需要切片
                data = cached[1]
                return {
                    "stats": data["stats"],
                    "recent": data["all_records"][:recent_limit],
                }
        from datetime import datetime, timedelta
        sheets = self.get_sheets_info(spreadsheet_token)
        today_str = datetime.now().strftime("%Y-%m-%d")
        week_ago = datetime.now() - timedelta(days=7)
        today_count = 0
        week_count = 0
        total = 0
        failed_total = 0
        all_records = []

        for sheet in sheets:
            sid = sheet["sheet_id"]
            try:
                rows = self.read_range(spreadsheet_token, sid, "A1:N1000")
            except LarkAPIError:
                continue
            for i, row in enumerate(rows[1:], start=2):
                if not row:
                    continue
                # safe access
                def cell(idx):
                    return row[idx] if len(row) > idx else None
                seq_cell = cell(0)
                url_cell = cell(1)
                status_cell = cell(2)
                title_cell = cell(3)
                time_cell = cell(11)
                if not (seq_cell or url_cell):
                    continue
                # 解析状态
                status_str = ""
                if isinstance(status_cell, str):
                    status_str = status_cell
                elif isinstance(status_cell, list) and status_cell:
                    first = status_cell[0]
                    if isinstance(first, dict):
                        status_str = first.get("text") or ""
                if "失败" in status_str:
                    failed_total += 1
                    continue
                # 必要字段：时间或标题至少一个非空，否则视为残缺数据跳过
                time_str = time_cell if isinstance(time_cell, str) else ""
                title_str = title_cell if isinstance(title_cell, str) else ""
                if not time_str and not title_str:
                    continue  # 残缺数据
                # 成功记录
                total += 1
                if time_str.startswith(today_str):
                    today_count += 1
                # 本周
                try:
                    ts = datetime.strptime(time_str[:16], "%Y-%m-%d %H:%M")
                    if ts >= week_ago:
                        week_count += 1
                except Exception:
                    pass
                # 链接
                link_str = ""
                if isinstance(url_cell, list) and url_cell:
                    first = url_cell[0]
                    if isinstance(first, dict):
                        link_str = first.get("link") or ""
                elif isinstance(url_cell, str):
                    link_str = url_cell
                all_records.append({
                    "title": title_str,
                    "time": time_str,
                    "sheet_title": sheet["title"],
                    "sheet_id": sid,
                    "row": i,
                    "url": link_str,
                })
        # 按时间倒序
        all_records.sort(key=lambda r: r["time"], reverse=True)
        result_full = {
            "stats": {
                "today": today_count,
                "this_week": week_count,
                "total": total,
                "failed_total": failed_total,
            },
            "all_records": all_records,
        }
        self._dashboard_cache[spreadsheet_token] = (time.time(), result_full)
        return {
            "stats": result_full["stats"],
            "recent": all_records[:recent_limit],
        }

    # ============ 店铺商品提取（商品页工具） ============

    def setup_shop_products_template(self, spreadsheet_token: str,
                                     sheet_id: str):
        """为「店铺商品提取」sheet 写入表头和基础样式。"""
        try:
            self.write_range(spreadsheet_token, sheet_id,
                             f"A1:{SHOP_PRODUCTS_LAST_COL}1",
                             [list(SHOP_PRODUCT_HEADERS)])
        except Exception:
            pass

        col_widths = {
            "A": 60,   # 序号
            "B": 180,  # 店铺名
            "C": 160,  # 店铺ID
            "D": 280,  # 商品名
            "E": 260,  # 商品链接
            "F": 180,  # 商品ID
            "G": 90,   # 到手价
            "H": 90,   # 已售数
            "I": 150,  # 采集时间
            "J": 110,  # 采集来源
            "K": 260,  # 异常备注
        }
        for col, width in col_widths.items():
            col_idx = ord(col) - ord("A")
            try:
                self._api(
                    "POST",
                    f"/sheets/v2/spreadsheets/{spreadsheet_token}/dimension_range",
                    json={
                        "dimension": {
                            "sheetId": sheet_id,
                            "majorDimension": "COLUMNS",
                            "startIndex": col_idx,
                            "endIndex": col_idx + 1,
                        },
                        "dimensionProperties": {"fixedSize": width},
                    },
                )
            except Exception:
                pass

        try:
            self._api(
                "POST",
                f"/sheets/v2/spreadsheets/{spreadsheet_token}/sheets_batch_update",
                json={"requests": [{
                    "updateSheet": {
                        "properties": {
                            "sheetId": sheet_id,
                            "frozenRowCount": 1,
                            "frozenColCount": 1,
                        }
                    }
                }]},
            )
        except Exception:
            pass

        try:
            self._set_cell_style(
                spreadsheet_token, sheet_id, f"A1:{SHOP_PRODUCTS_LAST_COL}1",
                font={"bold": True, "fontSize": "14pt/1.5", "clean": False},
                fore_color="#FFFFFF",
                back_color="#1F4E79",
                h_align=1,
                v_align=1,
                borders={
                    "type": "FULL_BORDER",
                    "color": "#FFFFFF",
                    "style": "1",
                },
            )
        except Exception:
            pass

        try:
            self.set_row_height(spreadsheet_token, sheet_id, 1, height=40)
        except Exception:
            pass

        actual_rows = self._get_sheet_row_count(spreadsheet_token, sheet_id)
        row_end = min(max(actual_rows, 2), 1000)
        try:
            self._apply_zebra_stripes(spreadsheet_token, sheet_id,
                                      row_start=2, row_end=row_end,
                                      last_col=SHOP_PRODUCTS_LAST_COL)
        except Exception:
            pass
        try:
            self.set_row_height_range(spreadsheet_token, sheet_id, 2, row_end,
                                      height=80)
        except Exception:
            pass

    def ensure_shop_products_sheet(self, spreadsheet_token: str) -> dict:
        """确保专用「店铺商品提取」sheet 存在。"""
        sheets = self.get_sheets_info(spreadsheet_token, use_cache=False)
        for sheet in sheets:
            if sheet["title"] == SHOP_PRODUCTS_SHEET_TITLE:
                return {
                    "sheet_id": sheet["sheet_id"],
                    "title": sheet["title"],
                    "created": False,
                }
        new_sheet = self.create_sheet(spreadsheet_token,
                                      SHOP_PRODUCTS_SHEET_TITLE)
        self.setup_shop_products_template(spreadsheet_token,
                                          new_sheet["sheet_id"])
        return {
            "sheet_id": new_sheet["sheet_id"],
            "title": new_sheet["title"],
            "created": True,
        }

    def _next_shop_product_row_and_seq(self, spreadsheet_token: str,
                                       sheet_id: str) -> tuple:
        rows = self.read_range(spreadsheet_token, sheet_id, "A2:A10000")
        max_seq = 0
        last_row = 1
        for idx, row in enumerate(rows, start=2):
            if not row or row[0] in ("", None):
                continue
            last_row = idx
            try:
                max_seq = max(max_seq, int(float(row[0])))
            except Exception:
                pass
        return last_row + 1, max_seq + 1

    def build_shop_product_row(self, seq: int, shop_info: dict,
                               product: dict, source: str,
                               remark: str = "") -> list:
        shop_info = shop_info or {}
        product = product or {}
        shop_name = (
            shop_info.get("shopName")
            or shop_info.get("shop_name")
            or product.get("shopName")
            or ""
        )
        seller_id = (
            shop_info.get("sellerId")
            or shop_info.get("seller_id")
            or product.get("sellerId")
            or product.get("seller_id")
            or ""
        )
        product_name = (
            product.get("name")
            or product.get("title")
            or product.get("card_title")
            or ""
        )
        goods_url = product.get("goodsUrl") or product.get("goods_url") or ""
        item_id = (
            product.get("itemId")
            or product.get("item_id")
            or product.get("goodsId")
            or product.get("goods_id")
            or product.get("skuId")
            or product.get("sku_id")
            or ""
        )
        deal_price = (
            product.get("dealPrice")
            if product.get("dealPrice") not in (None, "")
            else product.get("deal_price", "")
        )
        sold_count = (
            product.get("soldCount")
            if product.get("soldCount") not in (None, "")
            else product.get("sold_count", "")
        )

        missing = []
        for label, value in [
            ("店铺名", shop_name),
            ("店铺ID", seller_id),
            ("商品名", product_name),
            ("商品链接", goods_url),
            ("商品ID", item_id),
            ("到手价", deal_price),
            ("已售数", sold_count),
        ]:
            if value in (None, ""):
                missing.append(label)
        notes = []
        if remark:
            notes.append(str(remark))
        if missing:
            notes.append("缺字段：" + "、".join(missing))
        product_warning = product.get("warning") or product.get("error") or ""
        if product_warning:
            notes.append(str(product_warning)[:180])

        product_link = (
            {"type": "url", "text": goods_url, "link": goods_url}
            if goods_url else ""
        )
        return [
            seq,
            shop_name,
            seller_id,
            product_name,
            product_link,
            item_id,
            deal_price,
            sold_count,
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            source,
            " | ".join(notes),
        ]

    def append_shop_products(self, spreadsheet_token: str, shop_info: dict,
                             products: list, source: str = "店铺商品提取",
                             remark: str = "") -> dict:
        sheet = self.ensure_shop_products_sheet(spreadsheet_token)
        next_row, next_seq = self._next_shop_product_row_and_seq(
            spreadsheet_token, sheet["sheet_id"],
        )
        rows = [
            self.build_shop_product_row(next_seq + idx, shop_info, product,
                                        source, remark=remark)
            for idx, product in enumerate(products or [])
        ]
        if rows:
            end_row = next_row + len(rows) - 1
            self.write_range(
                spreadsheet_token, sheet["sheet_id"],
                f"A{next_row}:{SHOP_PRODUCTS_LAST_COL}{end_row}",
                rows,
            )
        else:
            end_row = next_row - 1
        self.invalidate_cache(spreadsheet_token)
        return {
            "sheet_id": sheet["sheet_id"],
            "sheet_title": sheet["title"],
            "created": sheet["created"],
            "written": len(rows),
            "start_row": next_row,
            "end_row": end_row,
        }

    # ============ 对标账号库（v4.4.0 新增） ============
    # 「图文对标」已改为笔记收录类「爆款图」，不再归账号库。
    # 账号库只保留「潜力店铺 / 爆款跟品」两类。

    ACCOUNT_LIB_SHEETS = ("潜力店铺", "爆款跟品")
    ACCOUNT_LIB_HEADERS = [
        "序号", "账号名", "主页URL", "小红书号", "笔记数", "粉丝数",
        "获赞与收藏", "IP属地", "简介", "品类", "风格", "备注",
        "添加时间", "状态",
    ]
    ACCOUNT_LIB_CATEGORIES = ["饰品", "穿搭", "美妆", "生活", "美食",
                              "母婴", "数码", "家居"]
    ACCOUNT_LIB_STYLES = ["大字报", "真人种草", "攻略型", "带货",
                          "测评", "干货", "故事型"]
    ACCOUNT_LIB_STATUSES = ["活跃", "暂停", "黑名单"]
    ACCOUNT_LIB_LAST_COL = "N"  # 14 列

    @staticmethod
    def _normalize_profile_url(url: str) -> str:
        """归一化主页 URL 用于去重：
        - 去 http(s):// 前缀
        - 去末尾 /
        - 去 query string（?xsec_token=xxx 之类）
        - 全部小写
        """
        if not url:
            return ""
        u = str(url).strip().lower()
        # 去协议
        for prefix in ("https://", "http://"):
            if u.startswith(prefix):
                u = u[len(prefix):]
                break
        # 去 query
        if "?" in u:
            u = u.split("?", 1)[0]
        # 去末尾 /
        u = u.rstrip("/")
        return u

    def ensure_account_lib_sheets(self, spreadsheet_token: str) -> dict:
        """确保 3 个账号库 sheet 都存在；缺的自动建并套模板。
        返回 {sheet_title: sheet_id}。
        """
        existing = self.get_sheets_info(spreadsheet_token, use_cache=False)
        title_to_id = {s["title"]: s["sheet_id"] for s in existing}
        result = {}
        for title in self.ACCOUNT_LIB_SHEETS:
            if title in title_to_id:
                result[title] = title_to_id[title]
                continue
            # 建新 sheet
            new_sheet = self.create_sheet(spreadsheet_token, title)
            sid = new_sheet.get("sheet_id")
            if not sid:
                raise LarkAPIError(f"创建 sheet「{title}」返回空 sheet_id")
            # 套模板
            self.setup_account_lib_template(spreadsheet_token, sid)
            result[title] = sid
        # 失效 cache，下次 get_sheets_info 拿最新
        self.invalidate_cache(spreadsheet_token)
        return result

    def setup_account_lib_template(self, spreadsheet_token: str,
                                    sheet_id: str) -> None:
        """给单个账号库 sheet 套：表头 + 样式 + 斑马纹 + 下拉 + 列宽 + 行高。

        所有步骤 try/except 单步降级，失败不抛异常，确保至少写入表头。

        样式规格（跟 v4.3.7 setup_sheet_template 一致）：
        - 表头 #1F4E79 深蓝底 / #FFFFFF 白字 / 14pt / 加粗 / 居中
        - 数据行 11pt / 偶数行 #F3F6FB 淡蓝灰 / 全边框 #D1D5DB
        - 表头行高 40 / 数据行高 36（紧凑）
        - J 列品类多选 / K 列风格多选 / N 列状态单选
        """
        last_col = self.ACCOUNT_LIB_LAST_COL  # "N"

        # 1. 写表头
        try:
            self.write_range(spreadsheet_token, sheet_id, f"A1:{last_col}1",
                              [list(self.ACCOUNT_LIB_HEADERS)])
        except Exception as e:
            print(f"⚠️ 账号库表头写入失败：{e}")

        # 2. 表头样式
        try:
            self._set_cell_style(
                spreadsheet_token, sheet_id, f"A1:{last_col}1",
                font={"bold": True, "fontSize": "14pt/1.5", "clean": False},
                fore_color="#FFFFFF", back_color="#1F4E79",
                h_align=1, v_align=1,
                borders={"type": "FULL_BORDER", "color": "#FFFFFF", "style": "1"},
            )
        except Exception as e:
            print(f"⚠️ 账号库表头样式失败：{e}")

        # 3. 数据区基础样式
        try:
            self._set_cell_style(
                spreadsheet_token, sheet_id, f"A2:{last_col}200",
                font={"fontSize": "11pt/1.5", "clean": False},
                h_align=1, v_align=1,
                borders={"type": "FULL_BORDER", "color": "#D1D5DB", "style": "1"},
            )
        except Exception as e:
            print(f"⚠️ 账号库数据样式失败：{e}")

        # 4. 斑马纹（偶数数据行）
        try:
            self._apply_zebra_stripes(spreadsheet_token, sheet_id,
                                       row_start=2, row_end=200,
                                       last_col=last_col)
        except Exception as e:
            print(f"⚠️ 账号库斑马纹失败：{e}")

        # 5. 列宽（按内容分级）
        col_widths = {
            "A": 60, "B": 140, "C": 200, "D": 120, "E": 80, "F": 80,
            "G": 100, "H": 100, "I": 260, "J": 110, "K": 140, "L": 260,
            "M": 110, "N": 90,
        }
        for col, width in col_widths.items():
            col_idx = ord(col) - ord("A")
            try:
                self._api(
                    "POST",
                    f"/sheets/v2/spreadsheets/{spreadsheet_token}/dimension_range",
                    json={
                        "dimension": {
                            "sheetId": sheet_id,
                            "majorDimension": "COLUMNS",
                            "startIndex": col_idx,
                            "endIndex": col_idx + 1,
                        },
                        "dimensionProperties": {"fixedSize": width},
                    },
                )
            except Exception:
                pass

        # 6. 行高（表头 40 / 数据 36 紧凑）
        try:
            self.set_row_height(spreadsheet_token, sheet_id, 1, height=40)
        except Exception:
            pass
        try:
            self.set_row_height_range(spreadsheet_token, sheet_id,
                                       start_row=2, end_row=200, height=36)
        except Exception:
            pass

        # 7. 冻结表头
        try:
            self._api(
                "POST",
                f"/sheets/v2/spreadsheets/{spreadsheet_token}/sheets_batch_update",
                json={"requests": [{
                    "updateSheet": {
                        "properties": {
                            "sheetId": sheet_id,
                            "frozenRowCount": 1,
                        }
                    }
                }]},
            )
        except Exception:
            pass

        # 8. J 列品类下拉（多选）
        try:
            self._api(
                "POST",
                f"/sheets/v2/spreadsheets/{spreadsheet_token}/dataValidation",
                json={
                    "range": f"{sheet_id}!J2:J200",
                    "dataValidationType": "list",
                    "dataValidation": {
                        "conditionValues": self.ACCOUNT_LIB_CATEGORIES,
                        "options": {
                            "multipleValues": True,
                            "highlightValidData": True,
                            "colors": ["#FA8C16", "#1890FF", "#EB2F96",
                                       "#52C41A", "#FAAD14", "#13C2C2",
                                       "#722ED1", "#A0522D"],
                        },
                    },
                },
            )
        except Exception as e:
            print(f"⚠️ 账号库 J 列品类下拉失败：{e}")

        # 9. K 列风格下拉（多选）
        try:
            self._api(
                "POST",
                f"/sheets/v2/spreadsheets/{spreadsheet_token}/dataValidation",
                json={
                    "range": f"{sheet_id}!K2:K200",
                    "dataValidationType": "list",
                    "dataValidation": {
                        "conditionValues": self.ACCOUNT_LIB_STYLES,
                        "options": {
                            "multipleValues": True,
                            "highlightValidData": True,
                            "colors": ["#FF4D4F", "#52C41A", "#1890FF",
                                       "#FA8C16", "#722ED1", "#13C2C2",
                                       "#EB2F96"],
                        },
                    },
                },
            )
        except Exception as e:
            print(f"⚠️ 账号库 K 列风格下拉失败：{e}")

        # 10. N 列状态下拉（单选）
        try:
            self._api(
                "POST",
                f"/sheets/v2/spreadsheets/{spreadsheet_token}/dataValidation",
                json={
                    "range": f"{sheet_id}!N2:N200",
                    "dataValidationType": "list",
                    "dataValidation": {
                        "conditionValues": self.ACCOUNT_LIB_STATUSES,
                        "options": {
                            "multipleValues": False,
                            "highlightValidData": True,
                            "colors": ["#52C41A", "#FAAD14", "#F5222D"],
                        },
                    },
                },
            )
        except Exception as e:
            print(f"⚠️ 账号库 N 列状态下拉失败：{e}")

    def check_account_exists_in_lib(self, spreadsheet_token: str,
                                     profile_url: str) -> Optional[tuple]:
        """跨 3 个账号库 sheet 查 profile_url 是否已存在（归一化后比对）。
        返回 (sheet_title, row_index) 或 None。
        """
        if not profile_url:
            return None
        target = self._normalize_profile_url(profile_url)
        sheets = self.ensure_account_lib_sheets(spreadsheet_token)
        for title, sid in sheets.items():
            try:
                rows = self.read_range(spreadsheet_token, sid, "C1:C200")
            except Exception:
                continue
            for i, row in enumerate(rows[1:], start=2):
                if not row:
                    continue
                cell = row[0] if row else None
                # cell 可能是 string 或 dict（飞书 url 类型）
                url_str = ""
                if isinstance(cell, str):
                    url_str = cell
                elif isinstance(cell, dict):
                    url_str = cell.get("link") or cell.get("text") or ""
                elif isinstance(cell, list):
                    # 飞书可能返回 [{"type":"url",...}]
                    for seg in cell:
                        if isinstance(seg, dict):
                            url_str = seg.get("link") or seg.get("text") or ""
                            if url_str:
                                break
                if not url_str:
                    continue
                if self._normalize_profile_url(url_str) == target:
                    return (title, i)
        return None

    def append_account_to_lib(self, spreadsheet_token: str,
                               sheet_title: str,
                               data: dict) -> int:
        """往指定账号库 sheet 追加一行。返回 row_index。
        data 字段：account_name / profile_url / xhs_id / notes_count /
                  fans_count / likes_count / ip_location / bio /
                  categories(list) / styles(list) / note
        """
        if sheet_title not in self.ACCOUNT_LIB_SHEETS:
            raise ValueError(f"sheet_title 必须是 {self.ACCOUNT_LIB_SHEETS}")
        sheets = self.ensure_account_lib_sheets(spreadsheet_token)
        sheet_id = sheets[sheet_title]

        # 算下一空行 + 最大序号
        try:
            rows = self.read_range(spreadsheet_token, sheet_id, "A1:A200")
        except Exception:
            rows = []
        max_seq = 0
        next_row = 2
        for i, row in enumerate(rows[1:], start=2) if rows else []:
            if not row:
                continue
            seq = row[0] if row else None
            if seq not in (None, ""):
                next_row = i + 1
                if isinstance(seq, (int, float)):
                    max_seq = max(max_seq, int(seq))
                else:
                    try:
                        max_seq = max(max_seq, int(str(seq).strip()))
                    except Exception:
                        pass
        new_seq = max_seq + 1

        # URL cell：飞书 url 类型
        profile_url = (data.get("profile_url") or "").strip()
        url_cell = (
            {"type": "url", "text": profile_url, "link": profile_url}
            if profile_url else ""
        )

        # 多选下拉值：用 multipleValue 格式让 chip 样式生效
        categories = data.get("categories") or []
        styles = data.get("styles") or []
        category_cell = (
            {"type": "multipleValue", "values": list(categories)}
            if categories else ""
        )
        style_cell = (
            {"type": "multipleValue", "values": list(styles)}
            if styles else ""
        )

        new_row = [
            new_seq,
            (data.get("account_name") or "").strip(),
            url_cell,
            (data.get("xhs_id") or "").strip(),
            (data.get("notes_count") or "").strip(),
            (data.get("fans_count") or "").strip(),
            (data.get("likes_count") or "").strip(),
            (data.get("ip_location") or "").strip(),
            (data.get("bio") or "").strip(),
            category_cell,
            style_cell,
            (data.get("note") or "").strip(),
            time.strftime("%Y-%m-%d"),
            "活跃",
        ]
        cell_range = f"A{next_row}:{self.ACCOUNT_LIB_LAST_COL}{next_row}"
        self.write_range(spreadsheet_token, sheet_id, cell_range, [new_row])

        # 失效 dashboard cache（不影响 account-lib，但保持一致）
        self.invalidate_cache(spreadsheet_token)
        return next_row

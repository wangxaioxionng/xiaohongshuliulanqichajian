#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill 已绑表用户的所有 sheet 样式（一次性运行，跑一次即可）

用法：
    python3 backfill_sheet_style.py             # 默认 user_id=1（王小熊）
    python3 backfill_sheet_style.py 2           # 指定 user_id=2
    python3 backfill_sheet_style.py all         # 全部绑表的用户都跑一遍

跑了什么：
    遍历指定用户的飞书表里所有 sheet（含「起号」「测试」等等业务子表），
    对每一个 sheet 调用 lark_writer.setup_sheet_template() 重新应用样式：
      - 表头加粗 + 浅灰底 + 居中 + 边框
      - 数据行 12px / 深灰字 / 斑马纹 / 全边框
      - 冻结第 1 行 + 第 A 列
      - 列宽统一调整为内容友好版

注意：
    - 老 sheet 的旧数据不会被改动，只动样式
    - 单 sheet 失败不影响下一个 sheet，最后会汇总成功 / 失败列表
    - 飞书 API 有频率限制，整段约 1-3 秒/sheet
"""
import json
import sys
import time
from pathlib import Path

import db
from lark_writer import LarkWriter, LarkAPIError, LarkAuthError


def _load_writer() -> LarkWriter:
    """从 config.json 加载凭据并构造 LarkWriter 单例。"""
    config_path = Path(__file__).parent / "config.json"
    if not config_path.exists():
        raise SystemExit(f"❌ config.json 不存在：{config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    for k in ("app_id", "app_secret"):
        if not config.get(k):
            raise SystemExit(f"❌ config.json 缺少 {k}")
    return LarkWriter(app_id=config["app_id"], app_secret=config["app_secret"])


def backfill_one_user(writer: LarkWriter, user_id: int) -> dict:
    """对单个 user 跑所有 sheet 的样式 backfill。返回汇总 dict。"""
    user = db.get_user_by_id(user_id)
    if not user:
        print(f"❌ user_id={user_id} 不存在")
        return {"user_id": user_id, "ok": 0, "fail": 0, "skipped": True}
    if not user.get("spreadsheet_token"):
        print(f"⏭️  user_id={user_id} ({user.get('name')}) 没绑表，跳过")
        return {"user_id": user_id, "ok": 0, "fail": 0, "skipped": True}

    name = user.get("name") or f"user{user_id}"
    token = user["spreadsheet_token"]
    print(f"\n▶ 开始处理 user_id={user_id} ({name}) → 表 token={token[:12]}...")

    try:
        sheets = writer.get_sheets_info(token, use_cache=False)
    except (LarkAPIError, LarkAuthError) as e:
        print(f"❌ 获取 sheet 列表失败：{e}")
        return {"user_id": user_id, "name": name, "ok": 0, "fail": 0,
                "error": str(e)}

    if not sheets:
        print(f"⚠️  该表没有任何 sheet（异常）")
        return {"user_id": user_id, "name": name, "ok": 0, "fail": 0}

    print(f"  共 {len(sheets)} 个 sheet：{[s['title'] for s in sheets]}")

    ok_count = 0
    fail_count = 0
    fail_list = []
    for sheet in sheets:
        sid = sheet["sheet_id"]
        title = sheet["title"]
        try:
            writer.setup_sheet_template(token, sid)
            print(f"  ✅ {title} 样式已更新")
            ok_count += 1
            # 飞书 API 限流防护：每个 sheet 之间停 0.3 秒
            time.sleep(0.3)
        except Exception as e:
            print(f"  ❌ {title} 失败：{e}")
            fail_count += 1
            fail_list.append({"title": title, "error": str(e)})

    return {
        "user_id": user_id,
        "name": name,
        "ok": ok_count,
        "fail": fail_count,
        "fail_list": fail_list,
        "total": len(sheets),
    }


def backfill_all_users(writer: LarkWriter) -> list:
    """对所有绑表的用户跑 backfill。"""
    users = db.list_users()
    bound = [u for u in users if u.get("spreadsheet_token")]
    print(f"共 {len(users)} 个用户，其中 {len(bound)} 个已绑表")
    results = []
    for u in bound:
        result = backfill_one_user(writer, u["id"])
        results.append(result)
    return results


def _print_summary(results: list):
    """打印汇总表。"""
    print("\n" + "=" * 60)
    print("【汇总】")
    print("=" * 60)
    total_ok = sum(r.get("ok", 0) for r in results)
    total_fail = sum(r.get("fail", 0) for r in results)
    for r in results:
        if r.get("skipped"):
            continue
        name = r.get("name", f"user{r.get('user_id')}")
        ok = r.get("ok", 0)
        fail = r.get("fail", 0)
        total = r.get("total", ok + fail)
        flag = "✅" if fail == 0 else "⚠️"
        print(f"{flag} {name}: {ok}/{total} 成功，{fail} 失败")
        if r.get("fail_list"):
            for f in r["fail_list"]:
                print(f"    ↳ {f['title']}: {f['error'][:120]}")
    print("=" * 60)
    print(f"总计：{total_ok} 成功 / {total_fail} 失败")


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "1"
    writer = _load_writer()

    if target == "all":
        results = backfill_all_users(writer)
    else:
        try:
            user_id = int(target)
        except ValueError:
            raise SystemExit(f"❌ 参数必须是数字 user_id 或 'all'，收到：{target}")
        results = [backfill_one_user(writer, user_id)]

    _print_summary(results)


if __name__ == "__main__":
    main()

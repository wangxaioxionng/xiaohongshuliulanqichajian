#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于 desc_backup 表的原文重新 flatten 飞书 F 列（不依赖飞书当前内容）

用途：分隔符变更（如 ` · ` → 单空格）时，从 desc_backup 取原文重做替换。
避免基于"已被替换过的内容"做二次替换（会拿不到 \n）。

用法：
    python3 rerun_flatten_from_backup.py [user_id|all]
"""
import sys
import time
import json
import db
from lark_writer import LarkWriter, flatten_desc, DESC_SEPARATOR


def rerun_one_user(user_id: int):
    user = db.get_user_by_id(user_id)
    if not user or not user["spreadsheet_token"]:
        print(f"❌ user_id={user_id} 无效或未绑表")
        return

    cfg = json.load(open("config.json"))
    w = LarkWriter(app_id=cfg["app_id"], app_secret=cfg["app_secret"])

    # 从 desc_backup 拿每行最新的 original_desc（按 row_idx 取最新 created_at）
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT spreadsheet_token, sheet_id, row_idx, original_desc
               FROM desc_backup
               WHERE user_id = ?
               ORDER BY row_idx""",
            (user_id,)
        ).fetchall()

    print(f"\n{'='*60}")
    print(f"▶ rerun user_id={user_id} ({user['name']})")
    print(f"  desc_backup 中共 {len(rows)} 条记录")
    print(f"  当前 DESC_SEPARATOR = {repr(DESC_SEPARATOR)}")
    print(f"{'='*60}")

    success = 0
    fail = 0
    for r in rows:
        token = r["spreadsheet_token"]
        sid = r["sheet_id"]
        row_idx = r["row_idx"]
        original = r["original_desc"]
        new_replaced = flatten_desc(original)

        try:
            w.write_range(token, sid, f"F{row_idx}:F{row_idx}", [[new_replaced]])
            success += 1
            print(f"  ✅ 第 {row_idx} 行 已重写（{len(original)} → {len(new_replaced)} 字）")
            time.sleep(0.2)
        except Exception as e:
            fail += 1
            print(f"  ⚠️ 第 {row_idx} 行 写回失败：{e}")

    print(f"\n【汇总】成功 {success} / 失败 {fail}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    target = sys.argv[1]
    if target == "all":
        users = db.list_users() if hasattr(db, "list_users") else []
        for u in users:
            rerun_one_user(u["id"])
    else:
        rerun_one_user(int(target))


if __name__ == "__main__":
    main()

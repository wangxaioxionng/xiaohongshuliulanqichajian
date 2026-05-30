#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill 脚本：把所有用户飞书表的 F 列 \n 替换为 ' · '，原文存 desc_backup 表

⚠️ 风险等级：高（修改飞书表数据本体，不是样式）
执行前必做：
1. ssh 备份生产 db
2. 该脚本会先把每行原文 INSERT 到 desc_backup 表（结构化备份）
3. 然后才 write_range 回飞书表
4. 还原走 SQL 查表，不靠字符串反向 replace

用法：
    python3 backfill_flatten_desc.py [user_id|all] [--dry-run]
        --dry-run：只扫描不写入

例：
    python3 backfill_flatten_desc.py 1            # 王小熊
    python3 backfill_flatten_desc.py 1 --dry-run  # 预览
    python3 backfill_flatten_desc.py all          # 所有用户（慎用）
"""
import sys
import time
import json
import db
from lark_writer import LarkWriter, flatten_desc, DESC_SEPARATOR


def backfill_one_user(user_id: int, dry_run: bool = False):
    user = db.get_user_by_id(user_id)
    if not user:
        print(f"❌ user_id={user_id} 不存在")
        return
    if not user["spreadsheet_token"]:
        print(f"❌ user_id={user_id} ({user['name']}) 没绑表")
        return

    cfg = json.load(open("config.json"))
    w = LarkWriter(app_id=cfg["app_id"], app_secret=cfg["app_secret"])
    token = user["spreadsheet_token"]
    sheets = w.get_sheets_info(token)

    print(f"\n{'='*60}")
    print(f"▶ 处理 user_id={user_id} ({user['name']})")
    print(f"  共 {len(sheets)} 个 sheet" + (" [DRY RUN]" if dry_run else ""))
    print(f"{'='*60}")

    total_rows_changed = 0
    total_backup_inserted = 0

    for sh in sheets:
        sid = sh["sheet_id"]
        title = sh["title"]
        print(f"\n--- {title} ---")
        # 读 F2:F500（用户实际数据 < 100 行，500 足够）
        try:
            rows = w.read_range(token, sid, "F2:F500")
        except Exception as e:
            print(f"  ⚠️ 读取失败：{e}")
            continue

        for offset, row in enumerate(rows):
            if not row or not row[0] or not isinstance(row[0], str):
                continue
            original = row[0]
            if "\n" not in original and "\r" not in original:
                # 没换行符，跳过
                continue

            row_idx = 2 + offset  # 飞书行号 (1-indexed，从第 2 行开始)
            replaced = flatten_desc(original)
            nl_count = original.count("\n") + original.count("\r")

            if dry_run:
                print(f"  [DRY] 第 {row_idx} 行：{nl_count} 个换行符 → 会替换 ({len(original)} 字)")
                total_rows_changed += 1
                continue

            # Step 1: 先备份原文到 desc_backup 表
            try:
                with db.get_conn() as conn:
                    conn.execute(
                        """INSERT INTO desc_backup
                           (spreadsheet_token, sheet_id, row_idx, user_id,
                            original_desc, replaced_desc, newline_count, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (token, sid, row_idx, user_id,
                         original, replaced, nl_count, int(time.time()))
                    )
                total_backup_inserted += 1
            except Exception as e:
                print(f"  ❌ 第 {row_idx} 行 backup INSERT 失败，跳过：{e}")
                continue

            # Step 2: 写回飞书表
            try:
                w.write_range(token, sid, f"F{row_idx}:F{row_idx}", [[replaced]])
                total_rows_changed += 1
                print(f"  ✅ 第 {row_idx} 行 已替换（{nl_count} 个换行符）")
                time.sleep(0.2)  # 限流防护
            except Exception as e:
                print(f"  ⚠️ 第 {row_idx} 行 写回飞书失败：{e}（备份已落 db）")

    print(f"\n{'='*60}")
    print(f"【汇总 user_id={user_id}】")
    print(f"  替换行数：{total_rows_changed}")
    print(f"  备份落库：{total_backup_inserted}")
    if not dry_run and total_backup_inserted > 0:
        print(f"  ✅ 还原命令：SELECT original_desc FROM desc_backup")
        print(f"               WHERE user_id={user_id} ORDER BY row_idx;")
    print(f"{'='*60}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    target = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    if target == "all":
        users = db.list_users() if hasattr(db, "list_users") else []
        for u in users:
            backfill_one_user(u["id"], dry_run=dry_run)
    else:
        backfill_one_user(int(target), dry_run=dry_run)


if __name__ == "__main__":
    main()

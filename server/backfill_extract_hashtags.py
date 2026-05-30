#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill 脚本：把现有飞书表 F 列里的 hashtag 拆到 O 列

数据源：飞书表当前 F 列（不依赖 desc_backup，因为只有部分行历史 backfill 过）
做法：
1. 读 F2:F{N} 当前内容
2. 对每行 extract_hashtags() → (clean_desc, tags_str)
3. 如果 clean_desc != original 或 tags_str 非空 → 写回 F + 写 O
4. 否则跳过（idempotent，没 hashtag 的行不动）

用法：
    python3 backfill_extract_hashtags.py [user_id|all] [--dry-run]
"""
import sys
import time
import json
import db
from lark_writer import LarkWriter, extract_hashtags


def backfill_one_user(user_id: int, dry_run: bool = False):
    user = db.get_user_by_id(user_id)
    if not user or not user["spreadsheet_token"]:
        print(f"❌ user_id={user_id} 无效或未绑表")
        return

    cfg = json.load(open("config.json"))
    w = LarkWriter(app_id=cfg["app_id"], app_secret=cfg["app_secret"])
    token = user["spreadsheet_token"]
    sheets = w.get_sheets_info(token)

    print(f"\n{'='*60}")
    print(f"▶ 处理 user_id={user_id} ({user['name']}) {' [DRY RUN]' if dry_run else ''}")
    print(f"  共 {len(sheets)} 个 sheet")
    print(f"{'='*60}")

    total_changed = 0
    total_skipped = 0

    for sh in sheets:
        sid = sh["sheet_id"]
        title = sh["title"]
        print(f"\n--- {title} ---")
        try:
            rows = w.read_range(token, sid, "F2:F500")
        except Exception as e:
            print(f"  ⚠️ 读取失败：{e}")
            continue

        for offset, row in enumerate(rows):
            if not row or not row[0] or not isinstance(row[0], str):
                continue
            row_idx = 2 + offset
            original = row[0]
            clean, tags = extract_hashtags(original)

            if not tags and clean == original:
                # 没 hashtag，跳过
                total_skipped += 1
                continue

            if dry_run:
                print(f"  [DRY] 第 {row_idx} 行：{original[:40]}... → {len(tags.split())} 个 hashtag")
                total_changed += 1
                continue

            # 写 F (clean) + O (tags)
            try:
                w.write_range(token, sid, f"F{row_idx}:F{row_idx}", [[clean]])
                w.write_range(token, sid, f"O{row_idx}:O{row_idx}", [[tags]])
                total_changed += 1
                tag_count = len(tags.split()) if tags else 0
                print(f"  ✅ 第 {row_idx} 行 已拆分（{tag_count} 个 hashtag → O 列）")
                time.sleep(0.2)
            except Exception as e:
                print(f"  ⚠️ 第 {row_idx} 行 写入失败：{e}")

    print(f"\n{'='*60}")
    print(f"【汇总 user_id={user_id}】")
    print(f"  改动行：{total_changed}")
    print(f"  跳过行（无 hashtag）：{total_skipped}")
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

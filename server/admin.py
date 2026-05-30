#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xhs-collect 管理工具（admin CLI）

用途：admin（王小熊）用来管理团队用户。

常见操作：
  # 1. 添加一个新用户（团队成员）
  python admin.py add --id zhangsan --name "张三" \\
      --sheet-url "https://my.feishu.cn/sheets/XXXXXX"
  # → 输出 auth_token，告诉张三在扩展里填

  # 2. 列出所有用户
  python admin.py list

  # 3. 删除用户
  python admin.py remove --id zhangsan

  # 4. 重置某用户的 token（如怀疑泄露）
  python admin.py rotate --id zhangsan

  # 5. 给某用户的飞书表预建默认分类 sheets
  python admin.py init-sheets --id zhangsan

操作完后必须重启服务才能生效：
  pm2 restart xhs-collect-api
"""
import argparse
import json
import re
import secrets
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

DEFAULT_CATEGORIES = ["起号图文", "爆款图", "爆款文案", "同行精选",
                      "潜力款", "标题公式", "互动引导", "待研究"]


def load_config():
    if not CONFIG_PATH.exists():
        print(f"❌ config.json 不存在：{CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(cfg):
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    CONFIG_PATH.chmod(0o600)


def parse_sheet_url(url: str) -> str:
    """从飞书表 URL 提取 spreadsheet_token。"""
    m = re.search(r"/sheets/([A-Za-z0-9]+)", url)
    return m.group(1) if m else url.strip()


def get_lark_token(cfg: dict) -> str:
    """获取 bot 的 tenant_access_token（用于调飞书 API）。"""
    import requests
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": cfg["app_id"], "app_secret": cfg["app_secret"]},
        timeout=10,
    )
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 tenant token 失败: {data}")
    return data["tenant_access_token"]


def get_first_sheet_id(cfg: dict, spreadsheet_token: str) -> str:
    """获取一个表的第一个 sheet_id（作为 default_sheet_id）。"""
    import requests
    token = get_lark_token(cfg)
    r = requests.get(
        f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/metainfo",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"读表 metainfo 失败: {data}")
    sheets = data.get("data", {}).get("sheets", [])
    if not sheets:
        raise RuntimeError("该表没有任何 sheet")
    return sheets[0]["sheetId"]


# ---------- 命令实现 ----------

def cmd_add(args):
    cfg = load_config()
    if args.id in cfg.get("users", {}):
        print(f"❌ 用户 ID 「{args.id}」已存在", file=sys.stderr)
        sys.exit(1)
    ss_token = parse_sheet_url(args.sheet_url)
    auth_token = secrets.token_urlsafe(32)

    # 自动探测 default sheet
    default_sheet = args.default_sheet
    if not default_sheet:
        try:
            default_sheet = get_first_sheet_id(cfg, ss_token)
            print(f"📌 自动选用第一个 sheet 作为默认: {default_sheet}")
        except Exception as e:
            print(f"⚠️ 自动探测 default_sheet 失败: {e}")
            print(f"   请稍后手动编辑 config.json 填 default_sheet_id")
            default_sheet = ""

    cfg.setdefault("users", {})[args.id] = {
        "name": args.name,
        "auth_token": auth_token,
        "spreadsheet_token": ss_token,
        "default_sheet_id": default_sheet,
    }
    save_config(cfg)
    print()
    print(f"✅ 用户 {args.id}（{args.name}）已添加")
    print(f"   飞书表 token: {ss_token}")
    print(f"   默认 sheet: {default_sheet or '(待填)'}")
    print()
    print(f"📋 给 {args.name} 的 Auth Token（让 TA 在扩展设置页填）:")
    print(f"   {auth_token}")
    print()
    print(f"⚠️ 别忘了重启服务: ssh root@14.22.112.147 'pm2 restart xhs-collect-api'")


def cmd_list(_args):
    cfg = load_config()
    users = cfg.get("users", {})
    if not users:
        print("（暂无用户）")
        return
    print(f"共 {len(users)} 个用户：")
    for uid, u in users.items():
        token_preview = u.get("auth_token", "")[:8] + "..."
        print(f"  - {uid:<15} {u.get('name', ''):<10} token={token_preview} sheet={u.get('spreadsheet_token', '')[:20]}...")


def cmd_remove(args):
    cfg = load_config()
    users = cfg.get("users", {})
    if args.id not in users:
        print(f"❌ 用户 {args.id} 不存在", file=sys.stderr)
        sys.exit(1)
    name = users[args.id].get("name", args.id)
    confirm = input(f"⚠️ 确认删除用户「{name}」({args.id})？输入 yes 确认: ")
    if confirm.strip().lower() != "yes":
        print("取消")
        return
    del users[args.id]
    save_config(cfg)
    print(f"✅ 用户 {args.id} 已删除")
    print(f"⚠️ 别忘了重启服务: ssh root@14.22.112.147 'pm2 restart xhs-collect-api'")


def cmd_rotate(args):
    cfg = load_config()
    users = cfg.get("users", {})
    if args.id not in users:
        print(f"❌ 用户 {args.id} 不存在", file=sys.stderr)
        sys.exit(1)
    new_token = secrets.token_urlsafe(32)
    old_token_preview = users[args.id]["auth_token"][:8] + "..."
    users[args.id]["auth_token"] = new_token
    save_config(cfg)
    print(f"✅ 用户 {args.id} 的 token 已轮换（旧 {old_token_preview}）")
    print()
    print(f"📋 新 Auth Token（让 TA 在扩展设置页更新）:")
    print(f"   {new_token}")
    print()
    print(f"⚠️ 别忘了重启服务: ssh root@14.22.112.147 'pm2 restart xhs-collect-api'")


def cmd_gen_code(args):
    """v4：生成激活码（OAuth 用户首次注册时用）。"""
    import db
    db.init_schema()
    expires_at = None
    if args.expires_in_days:
        expires_at = int(time.time()) + args.expires_in_days * 86400
    code = db.create_activation_code(
        note=args.note or "",
        created_by="admin-cli",
        expires_at=expires_at,
    )
    print()
    print(f"✅ 激活码已生成（备注：{args.note or '无'}）")
    print()
    print(f"📋 给员工的激活码：")
    print(f"   {code}")
    print()
    if expires_at:
        from datetime import datetime as dt
        print(f"⏰ 过期时间：{dt.fromtimestamp(expires_at).strftime('%Y-%m-%d %H:%M')}")
    print()
    print("员工使用方式：扫码登录扩展 → 提示填激活码 → 粘贴")


def cmd_list_codes(args):
    """v4：列出所有激活码（已用 / 未用）。"""
    import db
    from datetime import datetime as dt
    db.init_schema()
    codes = db.list_activation_codes()
    if not codes:
        print("（暂无激活码）")
        return
    print(f"共 {len(codes)} 个激活码：")
    for c in codes:
        used = "✅ 已用" if c["used_by_open_id"] else "⭕ 未用"
        created = dt.fromtimestamp(c["created_at"]).strftime("%m-%d %H:%M")
        print(f"  {c['code'][:14]}...  {used}  备注={c['note'] or '-':<20}  创建={created}")


def cmd_revoke_code(args):
    """v4：撤销一个未使用的激活码。"""
    import db
    db.init_schema()
    ok = db.revoke_activation_code(args.code)
    if ok:
        print(f"✅ 已撤销激活码 {args.code[:14]}...")
    else:
        print(f"❌ 撤销失败：码不存在或已使用")
        sys.exit(1)


def cmd_list_sqlite_users(args):
    """v4：列出 SQLite 里的 OAuth 用户（区别于 legacy）。"""
    import db
    from datetime import datetime as dt
    db.init_schema()
    users = db.list_users()
    if not users:
        print("（暂无 OAuth 用户。员工还没通过飞书扫码登录）")
        return
    print(f"共 {len(users)} 个 OAuth 用户：")
    for u in users:
        login = dt.fromtimestamp(u["last_login_at"]).strftime("%m-%d %H:%M") if u["last_login_at"] else "-"
        sheet = (u["spreadsheet_token"] or "")[:14] + "..." if u["spreadsheet_token"] else "(未绑)"
        print(f"  #{u['id']:<3} {u['name']:<10} status={u['status']:<8} sheet={sheet}  上次登录={login}")


def cmd_init_sheets(args):
    """给某用户的飞书表预建 7 个默认分类 sheet。"""
    import requests
    cfg = load_config()
    users = cfg.get("users", {})
    if args.id not in users:
        print(f"❌ 用户 {args.id} 不存在", file=sys.stderr)
        sys.exit(1)
    user = users[args.id]
    ss_token = user["spreadsheet_token"]
    auth = user["auth_token"]
    endpoint = args.endpoint or "http://14.22.112.147:8866"

    print(f"为 {user['name']}（{args.id}）的表创建 {len(DEFAULT_CATEGORIES)} 个默认分类…")
    for name in DEFAULT_CATEGORIES:
        try:
            r = requests.post(
                f"{endpoint}/api/categories",
                headers={"Content-Type": "application/json",
                         "X-Auth-Token": auth},
                json={"title": name},
                timeout=20,
            )
            data = r.json()
            if r.ok and data.get("status") == "ok":
                print(f"  ✅ {name} → sheet_id={data['sheet_id']}")
            elif r.status_code == 409:
                print(f"  ⏭ {name}（已存在，跳过）")
            else:
                print(f"  ❌ {name}: {data}")
        except Exception as e:
            print(f"  ❌ {name}: {e}")
    print("完成")


# ---------- 主入口 ----------

def main():
    parser = argparse.ArgumentParser(
        description="xhs-collect 管理工具（仅 admin 使用）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="添加新用户")
    p_add.add_argument("--id", required=True, help="用户 ID（英文唯一，如 zhangsan）")
    p_add.add_argument("--name", required=True, help="姓名（用于显示）")
    p_add.add_argument("--sheet-url", required=True, help="该用户的飞书表 URL")
    p_add.add_argument("--default-sheet", default="", help="默认 sheet_id（不填自动取第一个 sheet）")
    p_add.set_defaults(func=cmd_add)

    sub.add_parser("list", help="列出所有用户").set_defaults(func=cmd_list)

    p_remove = sub.add_parser("remove", help="删除用户")
    p_remove.add_argument("--id", required=True)
    p_remove.set_defaults(func=cmd_remove)

    p_rotate = sub.add_parser("rotate", help="轮换用户 token")
    p_rotate.add_argument("--id", required=True)
    p_rotate.set_defaults(func=cmd_rotate)

    p_init = sub.add_parser("init-sheets",
                             help="给用户的飞书表预建 7 个默认分类 sheet")
    p_init.add_argument("--id", required=True)
    p_init.add_argument("--endpoint", default="",
                         help="API endpoint（默认 http://14.22.112.147:8866）")
    p_init.set_defaults(func=cmd_init_sheets)

    # v4 OAuth 命令组
    p_gen = sub.add_parser("gen-code", help="(v4) 生成激活码")
    p_gen.add_argument("--note", default="", help="备注（给谁/什么用途）")
    p_gen.add_argument("--expires-in-days", type=int, default=None,
                       help="过期天数（不填永久有效）")
    p_gen.set_defaults(func=cmd_gen_code)

    p_lc = sub.add_parser("list-codes", help="(v4) 列出所有激活码")
    p_lc.set_defaults(func=cmd_list_codes)

    p_rc = sub.add_parser("revoke-code", help="(v4) 撤销一个未使用的激活码")
    p_rc.add_argument("--code", required=True)
    p_rc.set_defaults(func=cmd_revoke_code)

    p_lu = sub.add_parser("list-oauth-users",
                          help="(v4) 列出 OAuth 注册的用户")
    p_lu.set_defaults(func=cmd_list_sqlite_users)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

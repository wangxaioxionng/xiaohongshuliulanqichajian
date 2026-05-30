#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SQLite 数据层（v4 OAuth 系统）

3 张表：
- users           飞书登录的用户（含 open_id + 飞书表绑定）
- activation_codes 一次性激活码（admin 颁发）
- user_prefs      跨设备同步的用户偏好

老用户兼容：v3.1 config.json users 字段保留为 legacy 路径，
v4 系统优先看 SQLite，找不到再 fallback 到 config.json。
"""
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "data.db"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    open_id TEXT UNIQUE NOT NULL,
    union_id TEXT,
    name TEXT,
    avatar_url TEXT,
    spreadsheet_token TEXT,
    default_sheet_id TEXT,
    role TEXT NOT NULL DEFAULT 'user',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at INTEGER NOT NULL,
    last_login_at INTEGER,
    last_active_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_users_open_id ON users(open_id);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

CREATE TABLE IF NOT EXISTS activation_codes (
    code TEXT PRIMARY KEY,
    note TEXT,
    created_by TEXT NOT NULL,
    used_by_open_id TEXT,
    used_at INTEGER,
    created_at INTEGER NOT NULL,
    expires_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_codes_unused ON activation_codes(used_by_open_id)
    WHERE used_by_open_id IS NULL;

CREATE TABLE IF NOT EXISTS user_prefs (
    user_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, key),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS changelogs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT NOT NULL UNIQUE,
    version_type TEXT NOT NULL,
    released_at TEXT NOT NULL,
    title TEXT NOT NULL,
    details TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_changelogs_released_at ON changelogs(released_at DESC);

CREATE TABLE IF NOT EXISTS oauth_states (
    nonce TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_oauth_states_created_at ON oauth_states(created_at);

-- v4.3.2 B034 v4 desc backup table
CREATE TABLE IF NOT EXISTS desc_backup (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spreadsheet_token TEXT NOT NULL,
    sheet_id TEXT NOT NULL,
    row_idx INTEGER NOT NULL,
    user_id INTEGER,
    original_desc TEXT NOT NULL,
    replaced_desc TEXT NOT NULL,
    newline_count INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL,
    UNIQUE(spreadsheet_token, sheet_id, row_idx, created_at)
);

CREATE INDEX IF NOT EXISTS idx_desc_backup_row ON desc_backup(spreadsheet_token, sheet_id, row_idx);
CREATE INDEX IF NOT EXISTS idx_desc_backup_user ON desc_backup(user_id);
"""


@contextmanager
def get_conn():
    """获取 SQLite 连接（autocommit 模式）。"""
    conn = sqlite3.connect(str(DB_PATH), isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        yield conn
    finally:
        conn.close()


def init_schema():
    """初始化数据库 schema（幂等，多次跑无害）。"""
    with get_conn() as conn:
        for stmt in SCHEMA_SQL.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
    DB_PATH.chmod(0o600)


# ---------- users ----------

def get_user_by_open_id(open_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE open_id = ?", (open_id,),
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,),
        ).fetchone()
        return dict(row) if row else None


def create_user(open_id: str, name: str, avatar_url: str = "",
                union_id: str = "", role: str = "user",
                status: str = "pending") -> int:
    """创建用户。status 默认 pending（待激活）。返回新 user_id。"""
    now = int(time.time())
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO users
               (open_id, union_id, name, avatar_url, role, status,
                created_at, last_login_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (open_id, union_id, name, avatar_url, role, status, now, now),
        )
        return cur.lastrowid


def update_user_login(open_id: str, name: str = None,
                       avatar_url: str = None) -> None:
    """记录登录时间，可选更新姓名/头像。"""
    now = int(time.time())
    with get_conn() as conn:
        if name is not None or avatar_url is not None:
            conn.execute(
                """UPDATE users SET last_login_at = ?,
                   name = COALESCE(?, name),
                   avatar_url = COALESCE(?, avatar_url)
                   WHERE open_id = ?""",
                (now, name, avatar_url, open_id),
            )
        else:
            conn.execute(
                "UPDATE users SET last_login_at = ? WHERE open_id = ?",
                (now, open_id),
            )


def update_user_sheet(user_id: int, spreadsheet_token: str,
                      default_sheet_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE users SET spreadsheet_token = ?, default_sheet_id = ?
               WHERE id = ?""",
            (spreadsheet_token, default_sheet_id, user_id),
        )


def activate_user(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET status = 'active' WHERE id = ?", (user_id,),
        )


def list_users() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


# ---------- activation_codes ----------

def create_activation_code(note: str = "", created_by: str = "admin",
                            expires_at: Optional[int] = None) -> str:
    """生成一个新激活码。返回激活码字符串。"""
    code = secrets.token_urlsafe(16)
    now = int(time.time())
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO activation_codes
               (code, note, created_by, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?)""",
            (code, note, created_by, now, expires_at),
        )
    return code


def consume_activation_code(code: str, open_id: str) -> Optional[dict]:
    """原子消耗激活码（单条 UPDATE，并发安全）。

    SQLite 单条 UPDATE 是原子的；WHERE 同时校验未用 + 未过期，
    rowcount == 1 才算抢到。返回 None 表示码无效（不存在/已用/过期）。
    返回 dict 表示成功消耗，含 code 和 note。

    并发场景：两个请求同时拿同一个码，只有一个 UPDATE 会命中
    （另一个的 used_by_open_id IS NULL 条件已被前者破坏）。
    """
    now = int(time.time())
    with get_conn() as conn:
        cur = conn.execute(
            """UPDATE activation_codes
               SET used_by_open_id = ?, used_at = ?
               WHERE code = ?
                 AND used_by_open_id IS NULL
                 AND (expires_at IS NULL OR expires_at > ?)""",
            (open_id, now, code, now),
        )
        if cur.rowcount != 1:
            return None  # 不存在 / 已用 / 过期
        row = conn.execute(
            "SELECT code, note, created_by, created_at, used_at, expires_at "
            "FROM activation_codes WHERE code = ?",
            (code,),
        ).fetchone()
        return dict(row) if row else None


def list_activation_codes() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM activation_codes ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def revoke_activation_code(code: str) -> bool:
    """撤销一个未使用的激活码。"""
    with get_conn() as conn:
        result = conn.execute(
            "DELETE FROM activation_codes WHERE code = ? AND used_by_open_id IS NULL",
            (code,),
        )
        return result.rowcount > 0


# ---------- user_prefs ----------

def get_prefs(user_id: int) -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT key, value FROM user_prefs WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        return {r["key"]: r["value"] for r in rows}


def set_pref(user_id: int, key: str, value: str) -> None:
    now = int(time.time())
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO user_prefs (user_id, key, value, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, key) DO UPDATE SET
                 value = excluded.value, updated_at = excluded.updated_at""",
            (user_id, key, value, now),
        )


# ---------- changelogs ----------

def list_changelogs(limit: int = 20) -> list:
    """按 released_at DESC 返回 changelog 列表。"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT version, version_type, released_at, title, details, created_at
               FROM changelogs
               ORDER BY released_at DESC, id DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_changelog_by_version(version: str) -> Optional[dict]:
    """单条 changelog 查询。"""
    with get_conn() as conn:
        row = conn.execute(
            """SELECT version, version_type, released_at, title, details, created_at
               FROM changelogs WHERE version = ?""",
            (version,),
        ).fetchone()
        return dict(row) if row else None


def insert_changelog(version: str, version_type: str, title: str,
                     details: str, released_at: Optional[str] = None) -> None:
    """插入 changelog，已存在则覆盖（INSERT OR REPLACE）。"""
    if not released_at:
        released_at = time.strftime("%Y-%m-%d")
    if version_type not in ("major", "minor", "patch"):
        raise ValueError(f"version_type 必须是 major/minor/patch，收到 {version_type}")
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO changelogs
               (version, version_type, released_at, title, details)
               VALUES (?, ?, ?, ?, ?)""",
            (version, version_type, released_at, title, details),
        )


# ---------- oauth_states（防 CSRF nonce 持久化）----------

OAUTH_STATE_TTL = 600  # 10 分钟


def create_oauth_state() -> str:
    """生成 OAuth state nonce 并持久化。返回 nonce。

    用 SQLite 持久化而非内存 dict，避免重启丢失 + 多 worker 共享。
    """
    nonce = secrets.token_hex(32)
    now = int(time.time())
    with get_conn() as conn:
        # 顺手清过期的（成本低）
        conn.execute(
            "DELETE FROM oauth_states WHERE created_at < ?",
            (now - OAUTH_STATE_TTL,),
        )
        conn.execute(
            "INSERT INTO oauth_states (nonce, created_at) VALUES (?, ?)",
            (nonce, now),
        )
    return nonce


def consume_oauth_state(nonce: str) -> bool:
    """原子消费 OAuth state nonce。返回 True 表示有效且已消费。

    单条 DELETE，rowcount == 1 即抢到（且未过期）。
    """
    if not nonce:
        return False
    now = int(time.time())
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM oauth_states WHERE nonce = ? AND created_at >= ?",
            (nonce, now - OAUTH_STATE_TTL),
        )
        return cur.rowcount == 1


# ---------- 老用户兼容（legacy migration）----------

def migrate_legacy_users(config: dict) -> dict:
    """把 config.json 里的 users 字段映射成 SQLite 路径。

    legacy 用户的 user.id（如 'xiaoxiong'）作为 open_id 前缀加 'legacy_' 标识。
    auth_token 保留在 config.json 里，由 app.py 的 X-Auth-Token 鉴权路径直接读。

    本函数返回 {auth_token: user_dict} 映射，让 app.py 能 O(1) 查到。
    """
    token_to_user = {}
    for user_id_str, user in (config.get("users") or {}).items():
        token = user.get("auth_token")
        if not token:
            continue
        token_to_user[token] = {
            "legacy_id": user_id_str,
            "user_id": None,  # legacy 没有 SQLite user_id
            "name": user.get("name", user_id_str),
            "spreadsheet_token": user.get("spreadsheet_token"),
            "default_sheet_id": user.get("default_sheet_id"),
            "is_legacy": True,
        }
    return token_to_user


if __name__ == "__main__":
    # 命令行用法：python3 db.py  → 初始化 schema
    init_schema()
    print(f"✓ SQLite schema 已初始化：{DB_PATH}")
    with get_conn() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        print(f"✓ 表列表：{[t['name'] for t in tables]}")

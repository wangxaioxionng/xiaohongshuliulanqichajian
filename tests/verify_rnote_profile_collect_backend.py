import importlib
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"


def main() -> None:
    sys.path.insert(0, str(SERVER))
    fake_jwt = types.SimpleNamespace(
        InvalidTokenError=Exception,
        ExpiredSignatureError=Exception,
        encode=lambda payload, secret, algorithm=None: "fake.jwt.token",
        decode=lambda token, secret, algorithms=None: {},
    )
    sys.modules.setdefault("jwt", fake_jwt)
    app = importlib.import_module("app")

    app.PROFILE_COLLECT_API_PROVIDER = "rnote"
    app.RNOTE_API_BASE = "https://rnote.dev"
    app.CONFIG["rnote_api_key"] = "fake-rnote-key"
    app.PROFILE_COLLECT_REQUEST_DELAY = 0

    assert app._extract_xhs_profile_user_id(
        "https://www.xiaohongshu.com/user/profile/61b46d790000000010008153?xsec_token=abc"
    ) == "61b46d790000000010008153"

    calls = []

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append({
            "url": url,
            "params": dict(params or {}),
            "headers": dict(headers or {}),
            "timeout": timeout,
        })
        assert headers["X-API-Key"] == "fake-rnote-key"
        if url.endswith("/api/v2/crawler/user/posted"):
            assert params["user_id"] == "61b46d790000000010008153"
            assert params["num"] == 40
            return FakeResponse(200, {
                "success": True,
                "billed": True,
                "data": {
                    "code": 0,
                    "success": True,
                    "data": {
                        "has_more": False,
                        "notes": [
                            {
                                "id": "note1",
                                "title": "列表标题",
                                "display_title": "列表展示标题",
                                "desc": "列表正文 #话题[话题]#",
                                "create_time": 1756598549,
                                "cursor": "note1-cursor",
                                "images_list": [
                                    {"url": "https://example.com/list.jpg"}
                                ],
                                "type": "normal",
                            }
                        ],
                    },
                    "msg": "success",
                },
            })
        if url.endswith("/api/v2/crawler/note/image"):
            assert params["note_id"] == "note1"
            return FakeResponse(200, {
                "success": True,
                "billed": True,
                "data": {
                    "code": 0,
                    "success": True,
                    "data": {
                        "id": "note1",
                        "title": "详情标题",
                        "content": "详情正文 #详情[话题]#",
                        "time": 1769737966,
                        "liked_count": 7514,
                        "collected_count": 381,
                        "comments_count": 67,
                        "shared_count": 199,
                        "images_list": [
                            {
                                "url": "https://example.com/detail.jpg",
                                "original": "https://example.com/original.jpg",
                            }
                        ],
                        "user": {"nickname": "测试账号"},
                        "type": "normal",
                    },
                    "msg": "成功",
                },
            })
        raise AssertionError(url)

    app.requests.get = fake_get

    posts, user_info, more_available = app._fetch_profile_posts(
        "https://www.xiaohongshu.com/user/profile/61b46d790000000010008153",
        400,
    )
    assert more_available is False
    assert user_info == {}
    assert len(posts) == 1
    assert posts[0]["id"] == "note1"
    assert posts[0]["post_url"] == "https://www.xiaohongshu.com/explore/note1"
    assert posts[0]["text"] == "列表正文 #话题[话题]#"
    assert posts[0]["medias"][0]["resource_url"] == "https://example.com/list.jpg"
    assert calls[-1]["params"]["cursor"] == ""

    detail = app._fetch_note_post(
        "https://www.xiaohongshu.com/explore/note1?xsec_token=abc"
    )
    assert detail["id"] == "note1"
    assert detail["title"] == "详情标题"
    assert detail["text"] == "详情正文 #详情[话题]#"
    assert detail["created_at"] == 1769737966
    assert detail["medias"][0]["resource_url"] == "https://example.com/detail.jpg"
    assert detail["liked_count"] == 7514
    assert detail["collected_count"] == 381
    assert detail["comments_count"] == 67

    class FakeWriter:
        def __init__(self):
            self.rows = []

        def ensure_profile_collect_sheet(self, spreadsheet_token, account_name,
                                         image_cols=1):
            return {
                "sheet_id": "fake_sheet",
                "title": f"{account_name}全采集",
                "created": True,
            }

        def append_profile_collect_records(self, spreadsheet_token, sheet_id,
                                           records, source="账号全采集",
                                           image_cols=1):
            self.rows.extend(records)
            return {
                "written": len(records),
                "skipped": 0,
                "start_row": 2,
                "end_row": len(records) + 1,
            }

    fake_writer = FakeWriter()
    app.writer = fake_writer
    app.PROFILE_COLLECT_EMBED_IMAGES = False
    app._fetch_profile_posts = lambda profile_url, max_items: ([
        {
            "id": "note1",
            "title": "列表标题",
            "text": "列表正文",
            "post_url": "https://www.xiaohongshu.com/explore/note1",
            "created_at": 1756598549,
            "medias": [{"media_type": "image", "resource_url": "https://example.com/list.jpg"}],
        }
    ], {}, False)
    app._fetch_note_post = lambda note_url: {
        "id": "note1",
        "title": "详情标题",
        "text": "详情正文 #详情[话题]#",
        "created_at": 1769737966,
        "medias": [{"media_type": "image", "resource_url": "https://example.com/detail.jpg"}],
    }

    task_id = "rnote-playlist-details"
    with app.PROFILE_COLLECT_TASKS_LOCK:
        app.PROFILE_COLLECT_TASKS[task_id] = {
            "task_id": task_id,
            "status": "queued",
            "phase": "queued",
            "processed": 0,
            "success": 0,
            "failed": 0,
            "written": 0,
            "skipped": 0,
            "partial_saved": 0,
        }
    app._run_profile_collect_playlist_task(
        task_id,
        "fake_token",
        "https://www.xiaohongshu.com/user/profile/61b46d790000000010008153",
        "测试账号",
        400,
        "账号全采集",
    )
    task = app._task_snapshot(task_id)
    assert task["status"] == "done"
    assert task["collect_mode"] == "rnote_user_posted_then_detail"
    assert fake_writer.rows[0]["title"] == "详情标题"
    assert fake_writer.rows[0]["text"] == "详情正文 #详情[话题]#"


if __name__ == "__main__":
    main()

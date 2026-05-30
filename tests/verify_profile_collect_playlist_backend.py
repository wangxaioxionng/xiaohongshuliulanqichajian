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

    class FakeWriter:
        def __init__(self):
            self.rows = []
            self.created = False

        def ensure_profile_collect_sheet(self, spreadsheet_token, account_name,
                                         image_cols=1):
            created = not self.created
            self.created = True
            return {
                "sheet_id": "fake_sheet",
                "title": f"{account_name}全采集",
                "created": created,
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
    app.PROFILE_COLLECT_REQUEST_DELAY = 0

    def fake_fetch_profile_posts(profile_url: str, max_items: int):
        assert profile_url == "https://www.xiaohongshu.com/user/profile/user1"
        assert max_items == 400
        return [
            {
                "id": "note1",
                "post_url": "https://www.xiaohongshu.com/explore/note1?xsec_token=t1",
                "text": "标题一\n正文一 #标签一#",
                "medias": [
                    {"media_type": "image", "resource_url": "https://example.com/1.jpg"}
                ],
            },
            {
                "id": "note2",
                "post_url": "https://www.xiaohongshu.com/explore/note2?xsec_token=t2",
                "text": "标题二\n正文二 #标签二#",
                "medias": [
                    {"media_type": "image", "resource_url": "https://example.com/2.jpg"}
                ],
            },
        ], {"username": "圆圆blue"}, False

    app._fetch_profile_posts = fake_fetch_profile_posts
    task_id = "playlist-test"
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
        "https://www.xiaohongshu.com/user/profile/user1",
        "圆圆blue",
        400,
        "账号全采集",
    )
    task = app._task_snapshot(task_id)
    assert task["status"] == "done"
    assert task["phase"] == "done"
    assert task["total"] == 2
    assert task["processed"] == 2
    assert task["success"] == 2
    assert task["written"] == 2
    assert task["partial_saved"] == 2
    assert len(fake_writer.rows) == 2
    assert fake_writer.rows[0]["account_name"] == "圆圆blue"
    assert fake_writer.rows[0]["title"] == "标题一"


if __name__ == "__main__":
    main()


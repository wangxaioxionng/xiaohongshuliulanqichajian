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
            start_row = len(self.rows) + 1
            return {
                "written": len(records),
                "skipped": 0,
                "start_row": start_row,
                "end_row": start_row + len(records) - 1,
            }

    fake_writer = FakeWriter()
    app.writer = fake_writer
    app.PROFILE_COLLECT_REQUEST_DELAY = 0

    def fake_fetch(note_url: str) -> dict:
        if "bad" in note_url:
            raise RuntimeError("fake api failed")
        return {
            "id": note_url.rsplit("/", 1)[-1],
            "title": "测试标题",
            "text": "测试文案 #测试#",
            "medias": [
                {
                    "media_type": "image",
                    "resource_url": "https://example.com/a.jpg",
                }
            ],
        }

    app._fetch_note_post = fake_fetch
    task_id = "incremental-test"
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

    app._run_profile_collect_task(
        task_id,
        "fake_token",
        "https://www.xiaohongshu.com/user/profile/user1",
        "测试账号",
        [
            "https://www.xiaohongshu.com/explore/good1",
            "https://www.xiaohongshu.com/explore/bad",
            "https://www.xiaohongshu.com/explore/good2",
        ],
        "账号全采集",
    )
    task = app._task_snapshot(task_id)
    assert task["status"] == "done"
    assert task["processed"] == 3
    assert task["success"] == 2
    assert task["failed"] == 1
    assert task["written"] == 2
    assert task["partial_saved"] == 2
    assert len(fake_writer.rows) == 2


if __name__ == "__main__":
    main()

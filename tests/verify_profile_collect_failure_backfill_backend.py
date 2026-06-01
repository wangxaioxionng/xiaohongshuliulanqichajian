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
            self.failure_rows_written = 0
            self.overwritten_rows = 0

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
            start_row = len(self.rows) + 2
            for record in records:
                self.rows.append({
                    "row": len(self.rows) + 2,
                    "seq": len(self.rows) + 1,
                    "status": "✅ 已采集",
                    "url": record["post_url"],
                    "title": record["title"],
                    "error": "",
                })
            return {
                "written": len(records),
                "skipped": 0,
                "start_row": start_row,
                "end_row": start_row + len(records) - 1,
            }

        def append_profile_collect_failure(self, spreadsheet_token, sheet_id,
                                           failure, account_name, profile_url,
                                           source="账号全采集", image_cols=1):
            row = len(self.rows) + 2
            seq = len(self.rows) + 1
            self.rows.append({
                "row": row,
                "seq": seq,
                "status": "❌ 失败",
                "url": failure["url"],
                "title": "",
                "error": failure["error"],
            })
            self.failure_rows_written += 1
            return {"written": 1, "row": row, "seq": seq}

        def overwrite_profile_collect_record(self, spreadsheet_token, sheet_id,
                                             row_idx, seq, record,
                                             source="账号全采集",
                                             image_cols=1):
            for row in self.rows:
                if row["row"] == row_idx:
                    row.update({
                        "seq": seq,
                        "status": "✅ 已采集",
                        "url": record["post_url"],
                        "title": record["title"],
                        "error": "",
                    })
                    self.overwritten_rows += 1
                    return {"written": 1, "row": row_idx}
            raise AssertionError(f"row {row_idx} not found")

        def overwrite_profile_collect_failure(self, spreadsheet_token, sheet_id,
                                              row_idx, seq, failure,
                                              account_name, profile_url,
                                              source="账号全采集",
                                              image_cols=1):
            for row in self.rows:
                if row["row"] == row_idx:
                    row.update({
                        "seq": seq,
                        "status": "❌ 失败",
                        "url": failure["url"],
                        "title": "",
                        "error": failure["error"],
                    })
                    return {"written": 1, "row": row_idx}
            raise AssertionError(f"row {row_idx} not found")

    fake_writer = FakeWriter()
    app.writer = fake_writer
    app.PROFILE_COLLECT_REQUEST_DELAY = 0
    app.PROFILE_COLLECT_POST_RETRY_ATTEMPTS = 1
    app.PROFILE_COLLECT_POST_RETRY_DELAY = 0
    app.PROFILE_COLLECT_POST_RETRY_JITTER = 0
    app.PROFILE_COLLECT_EMBED_IMAGES = False

    calls = {}

    def fake_fetch(note_url: str) -> dict:
        calls[note_url] = calls.get(note_url, 0) + 1
        if "late-success" in note_url and calls[note_url] == 1:
            raise RuntimeError("temporary api failure")
        return {
            "id": note_url.rsplit("/", 1)[-1],
            "title": f"标题-{note_url.rsplit('/', 1)[-1]}",
            "text": "测试文案 #测试#",
            "medias": [
                {
                    "media_type": "image",
                    "resource_url": "https://example.com/a.jpg",
                }
            ],
        }

    app._fetch_note_post = fake_fetch
    task_id = "failure-backfill-test"
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

    late_url = "https://www.xiaohongshu.com/explore/late-success"
    app._run_profile_collect_task(
        task_id,
        "fake_token",
        "https://www.xiaohongshu.com/user/profile/user1",
        "测试账号",
        [
            "https://www.xiaohongshu.com/explore/good",
            late_url,
        ],
        "账号全采集",
    )

    task = app._task_snapshot(task_id)
    assert calls[late_url] == 2
    assert task["status"] == "done"
    assert task["phase"] == "done"
    assert task["processed"] == 2
    assert task["success"] == 2
    assert task["failed"] == 0
    assert task["written"] == 2
    assert task["failed_saved"] == 1
    assert task["retry_total"] == 1
    assert task["retry_processed"] == 1
    assert task["retry_success"] == 1
    assert task["retry_failed"] == 0
    assert task["partial_saved"] == 2
    assert fake_writer.failure_rows_written == 1
    assert fake_writer.overwritten_rows == 1
    assert len(fake_writer.rows) == 2
    assert [row["status"] for row in fake_writer.rows] == ["✅ 已采集", "✅ 已采集"]
    assert fake_writer.rows[1]["url"] == late_url
    assert fake_writer.rows[1]["title"] == "标题-late-success"


if __name__ == "__main__":
    main()

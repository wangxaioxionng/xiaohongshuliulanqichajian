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
    lark_writer = importlib.import_module("lark_writer")

    calls = []

    class FakeResponse:
        status_code = 200
        content = b"x" * 2048

    def fake_get(url, timeout=15, headers=None):
        calls.append({"url": url, "headers": headers or {}})
        return FakeResponse()

    app.requests.get = fake_get
    app.PROFILE_COLLECT_EMBED_IMAGES = True

    api_data = {
        "id": "note1",
        "text": "正文",
        "medias": [
            {
                "media_type": "image",
                "resource_url": "https://ci.xiaohongshu.com/a.jpg",
                "headers": {
                    "Referer": "https://www.xiaohongshu.com/",
                    "User-Agent": "Meowload-UA",
                },
            }
        ],
    }
    record = app._note_response_to_record(
        api_data,
        "https://www.xiaohongshu.com/explore/note1?xsec_token=t",
        "https://www.xiaohongshu.com/user/profile/user1",
        "测试账号",
    )

    assert record["image_urls"] == ["https://ci.xiaohongshu.com/a.jpg"]
    assert record["image_items"][0]["headers"]["User-Agent"] == "Meowload-UA"

    result = app._attach_profile_image_bytes([record], image_cols=1)
    assert result["downloaded"] == 1
    assert record["image_bytes_list"] == [b"x" * 2048]
    assert calls[0]["headers"]["Referer"] == "https://www.xiaohongshu.com/"
    assert calls[0]["headers"]["User-Agent"] == "Meowload-UA"

    writer = lark_writer.LarkWriter("fake_app", "fake_secret")
    uploaded_cols = []

    def fake_upload(spreadsheet_token, sheet_id, row_index, image_bytes,
                    image_name="cover.jpg", col=None):
        uploaded_cols.append(col)
        return {"ok": True}

    writer.upload_image_to_cell = fake_upload
    upload_result = writer.upload_profile_collect_images_to_cells(
        "spreadsheet", "sheet", 7, [b"a", b"b"], image_cols=2,
    )
    assert upload_result["failed"] == []
    assert uploaded_cols == ["I", "K", "L"]


if __name__ == "__main__":
    main()

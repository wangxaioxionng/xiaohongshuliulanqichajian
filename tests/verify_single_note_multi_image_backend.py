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

    assert lark_writer.LAST_COL == "AK"
    assert lark_writer.NOTE_MULTI_IMAGE_MAX_COLS == 20
    assert lark_writer.NOTE_TOTAL_COLS == 37
    assert lark_writer.NOTE_HEADERS[15] == "图片数量"
    assert lark_writer.NOTE_HEADERS[16] == "全部图片下载链接"
    assert lark_writer.NOTE_HEADERS[17] == "图片1"
    assert lark_writer.NOTE_HEADERS[-1] == "图片20"

    writer = lark_writer.LarkWriter("fake_app", "fake_secret")
    image_urls = [
        "https://ci.xiaohongshu.com/a.jpg",
        "https://ci.xiaohongshu.com/b.jpg",
        "https://ci.xiaohongshu.com/c.jpg",
    ]
    row = writer.build_row(
        1,
        {
            "url": "https://www.xiaohongshu.com/explore/note1",
            "note_id": "note1",
            "title": "测试标题",
            "desc": "正文 #标签#",
            "image_urls": image_urls,
        },
        "Extension",
    )
    assert len(row) == lark_writer.NOTE_TOTAL_COLS
    # B 列「原文链接」必须是笔记链接，不能被图片循环变量覆盖。
    # 历史 bug：build_row 循环里复用了 url 变量，导致 B 列被写成
    # 空值（图片 < 20 张）或第 20 张图片链接（图片 >= 20 张）。
    assert row[1] == {
        "type": "url",
        "text": "https://www.xiaohongshu.com/explore/note1",
        "link": "https://www.xiaohongshu.com/explore/note1",
    }, f"B 列原文链接被写错：{row[1]}"
    assert row[14] == "#标签#"
    assert row[15] == 3
    assert row[16] == "  ".join(image_urls)
    assert row[17]["link"] == image_urls[0]
    assert row[17]["text"] == "图片1"
    assert row[19]["link"] == image_urls[2]

    empty_url_row = writer.build_row(
        1,
        {
            "url": "",
            "note_id": "note-empty-url",
            "title": "空链接兜底",
            "desc": "正文",
            "image_urls": image_urls[:1],
        },
        "Extension",
    )
    assert empty_url_row[1] == ""

    # 边界：图片数 >= 20（图片列填满）时，B 列仍必须是原文链接。
    # 这是历史 bug 的第二种表现：B 列会变成第 20 张图片的链接。
    many_images = [
        f"https://ci.xiaohongshu.com/full{idx}.jpg" for idx in range(25)
    ]
    full_row = writer.build_row(
        3,
        {
            "url": "https://www.xiaohongshu.com/explore/note-full",
            "note_id": "note-full",
            "title": "满图笔记",
            "desc": "正文",
            "image_urls": many_images,
        },
        "Extension",
    )
    assert full_row[1]["link"] == "https://www.xiaohongshu.com/explore/note-full", (
        f"满 20 图时 B 列原文链接被写错：{full_row[1]}"
    )
    assert full_row[-1]["link"] == many_images[19]
    assert full_row[15] == 25

    failure_row = writer.build_failure_row(
        2,
        "https://www.xiaohongshu.com/explore/fail",
        "失败原因",
        "Extension",
    )
    assert len(failure_row) == lark_writer.NOTE_TOTAL_COLS
    assert failure_row[15] == 0
    assert failure_row[16] == ""
    assert failure_row[-1] == ""

    uploaded_cols = []

    def fake_setup(spreadsheet_token, sheet_id, image_count):
        assert image_count == lark_writer.NOTE_MULTI_IMAGE_MAX_COLS

    def fake_upload(spreadsheet_token, sheet_id, row_index, image_bytes,
                    image_name="cover.jpg", col=None):
        uploaded_cols.append(col)
        return {"ok": True}

    writer.setup_multi_image_columns = fake_setup
    writer.upload_image_to_cell = fake_upload
    upload_result = writer.upload_images_to_cells(
        "spreadsheet", "sheet", 7, [b"a", b"b", b"c"], note_id="note1",
    )
    assert upload_result["failed"] == []
    assert upload_result["ok"] == 4
    assert uploaded_cols == ["E", "R", "S", "T"]

    class FakeWriter:
        ACCOUNT_LIB_SHEETS = ()

        def __init__(self, title: str):
            self.title = title

        def get_sheet_title(self, spreadsheet_token, sheet_id):
            return self.title

    old_writer = app.writer
    old_download_image = app._download_image
    try:
        app.writer = FakeWriter("爆款文案")
        assert app._sheet_saves_all_images("spreadsheet", "sheet") is True

        app.writer = FakeWriter("发誓当仙女全采集")
        assert app._sheet_saves_all_images("spreadsheet", "sheet") is False

        app.writer = FakeWriter(lark_writer.SHOP_PRODUCTS_SHEET_TITLE)
        assert app._sheet_saves_all_images("spreadsheet", "sheet") is False

        downloaded = []

        def fake_download_image(url, headers=None):
            downloaded.append(url)
            return b"x" * 2048

        app._download_image = fake_download_image
        all_urls = [
            f"https://ci.xiaohongshu.com/{idx}.jpg"
            for idx in range(25)
        ]
        cover, images = app._prepare_images({"image_urls": all_urls}, True)
        assert cover == b"x" * 2048
        assert len(images) == lark_writer.NOTE_MULTI_IMAGE_MAX_COLS
        assert downloaded == all_urls[:lark_writer.NOTE_MULTI_IMAGE_MAX_COLS]
    finally:
        app.writer = old_writer
        app._download_image = old_download_image


if __name__ == "__main__":
    main()

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

    lark_writer = importlib.import_module("lark_writer")
    app = importlib.import_module("app")
    popup_html = (ROOT / "extension/popup.html").read_text(encoding="utf-8")
    popup_js = (ROOT / "extension/popup.js").read_text(encoding="utf-8")

    headers = lark_writer.LarkWriter.ACCOUNT_LIB_HEADERS
    assert headers == [
        "序号", "账号名", "主页URL", "小红书号", "笔记数", "粉丝数",
        "获赞与收藏", "IP属地", "简介", "备注", "添加时间", "状态",
    ]
    assert "品类" not in headers
    assert "风格" not in headers
    assert lark_writer.LarkWriter.ACCOUNT_LIB_LAST_COL == "L"

    writer = lark_writer.LarkWriter("fake_app", "fake_secret")
    writes = []
    writer.ensure_account_lib_sheets = lambda token: {"爆款跟品": "sheet1", "潜力店铺": "sheet2"}
    writer.read_range = lambda token, sheet_id, cell_range: [["序号"]]
    writer.write_range = lambda token, sheet_id, cell_range, values: writes.append((cell_range, values))
    writer.invalidate_cache = lambda token: None

    next_row = writer.append_account_to_lib(
        "spreadsheet",
        "爆款跟品",
        {
            "account_name": "OOK Park",
            "profile_url": "https://www.xiaohongshu.com/user/profile/abc",
            "xhs_id": "ook123",
            "notes_count": "5264",
            "fans_count": "2.4万",
            "likes_count": "10.8万",
            "ip_location": "上海",
            "bio": "测试简介",
            "categories": ["饰品"],
            "styles": ["真人种草"],
            "note": "重点观察",
        },
    )
    assert next_row == 2
    assert writes[0][0] == "A2:L2"
    row = writes[0][1][0]
    assert len(row) == 12
    assert row[8] == "测试简介"
    assert row[9] == "重点观察"
    assert row[11] == "活跃"
    assert not any(isinstance(cell, dict) and cell.get("type") == "multipleValue" for cell in row)

    meta = app.account_lib_meta()
    assert set(meta.keys()) == {"account_types"}

    forbidden_ui = [
        "品类（多选）",
        "风格（多选）",
        'id="al-cat-group"',
        'id="al-style-group"',
    ]
    for needle in forbidden_ui:
        assert needle not in popup_html

    forbidden_js = [
        "selectedCategories",
        "selectedStyles",
        "al-cat-group",
        "al-style-group",
        "categories: AL_STATE.selectedCategories",
        "styles: AL_STATE.selectedStyles",
    ]
    for needle in forbidden_js:
        assert needle not in popup_js


if __name__ == "__main__":
    main()

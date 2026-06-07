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

    lw = importlib.import_module("lark_writer")
    expected_base_headers = [
        "序号",
        "店铺/账号名",
        "主页链接",
        "笔记标题",
        "图文文案",
        "话题标签",
        "笔记链接",
        "点赞",
        "收藏",
        "评论",
        "分享",
        "图片数量",
        "封面图",
        "全部图片下载链接",
    ]
    assert lw.PROFILE_COLLECT_BASE_HEADERS == expected_base_headers

    writer = lw.LarkWriter("app", "secret")
    row = writer.build_profile_collect_row(
        7,
        {
            "account_name": "雾野来信",
            "profile_url": "https://www.xiaohongshu.com/user/profile/u1",
            "title": "笔记标题",
            "text": "正文 #耳钉[话题]#",
            "post_url": "https://www.xiaohongshu.com/explore/n1",
            "liked_count": 11,
            "collected_count": 22,
            "comments_count": 33,
            "shared_count": 44,
            "image_urls": ["https://img.example/1.jpg"],
        },
        source="账号全采集",
        image_cols=2,
    )
    assert row[6]["link"] == "https://www.xiaohongshu.com/explore/n1"
    assert row[7:11] == [11, 22, 33, 44]
    assert row[11] == 1
    assert row[12]["link"] == "https://img.example/1.jpg"
    assert row[14]["link"] == "https://img.example/1.jpg"
    assert row[15] == ""
    assert row[16]  # 采集时间
    assert row[17] == "账号全采集"
    assert row[18] == "✅ 已采集"

    class FakeMigratingWriter(lw.LarkWriter):
        def __init__(self):
            super().__init__("app", "secret")
            self.api_calls = []
            self.invalidated = []

        def read_range(self, spreadsheet_token, sheet_id, cell_range):
            assert cell_range == "A1:N1"
            return [[
                "序号", "店铺/账号名", "主页链接", "笔记标题", "图文文案",
                "话题标签", "笔记链接", "图片数量", "封面图", "全部图片下载链接",
                "图片1", "图片2", "采集时间", "采集来源",
            ]]

        def _api(self, method, path, **kwargs):
            self.api_calls.append((method, path, kwargs))
            return {"code": 0}

        def invalidate_cache(self, spreadsheet_token):
            self.invalidated.append(spreadsheet_token)

    migrating = FakeMigratingWriter()
    migrating._migrate_profile_collect_interaction_columns("token", "sheet1")
    assert len(migrating.api_calls) == 1
    dimension = migrating.api_calls[0][2]["json"]["dimension"]
    assert dimension["majorDimension"] == "COLUMNS"
    assert dimension["startIndex"] == 7
    assert dimension["length"] == 4
    assert migrating.invalidated == ["token"]


if __name__ == "__main__":
    main()

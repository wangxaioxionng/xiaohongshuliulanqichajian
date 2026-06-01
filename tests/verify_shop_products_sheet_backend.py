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
    expected_headers = [
        "序号",
        "店铺名",
        "店铺ID",
        "商品名",
        "商品链接",
        "商品ID",
        "到手价",
        "已售数",
        "采集时间",
        "采集来源",
        "异常备注",
    ]
    assert lw.SHOP_PRODUCTS_SHEET_TITLE == "店铺商品提取"
    assert lw.SHOP_PRODUCT_HEADERS == expected_headers
    assert all("销售额" not in header for header in lw.SHOP_PRODUCT_HEADERS)

    app_module = importlib.import_module("app")
    routes = {getattr(route, "path", "") for route in app_module.app.routes}
    assert "/api/shop-products/collect" in routes

    class FakeWriter(lw.LarkWriter):
        def __init__(self):
            super().__init__("app", "secret")
            self.created = []
            self.template_calls = []
            self.ranges = []
            self.invalidated = []

        def get_sheets_info(self, spreadsheet_token, use_cache=True):
            return list(self.created)

        def create_sheet(self, spreadsheet_token, title, index=None):
            sheet = {"sheet_id": "shop_sheet", "title": title, "index": 0}
            self.created.append(sheet)
            return sheet

        def setup_shop_products_template(self, spreadsheet_token, sheet_id):
            self.template_calls.append((spreadsheet_token, sheet_id))

        def read_range(self, spreadsheet_token, sheet_id, cell_range):
            if cell_range == "A2:A10000":
                return [[1], [2]]
            return []

        def write_range(self, spreadsheet_token, sheet_id, cell_range, values):
            self.ranges.append((cell_range, values))

        def invalidate_cache(self, spreadsheet_token):
            self.invalidated.append(spreadsheet_token)

    fake = FakeWriter()
    result = fake.append_shop_products(
        "token",
        {"shopName": "小熊耳饰", "sellerId": "seller123", "shopLink": "https://www.xiaohongshu.com/vendor/seller123"},
        [
            {
                "name": "珍珠耳钉",
                "goodsUrl": "https://www.xiaohongshu.com/goods-detail/item1",
                "itemId": "item1",
                "dealPrice": 30.8,
                "soldCount": 120,
            }
        ],
        source="插件",
    )
    assert result["sheet_title"] == "店铺商品提取"
    assert result["written"] == 1
    assert result["start_row"] == 4
    assert result["end_row"] == 4
    assert fake.template_calls == [("token", "shop_sheet")]
    assert fake.ranges[0][0] == "A4:K4"
    row = fake.ranges[0][1][0]
    assert row[0] == 3
    assert row[1] == "小熊耳饰"
    assert row[2] == "seller123"
    assert row[3] == "珍珠耳钉"
    assert row[5] == "item1"
    assert row[6] == 30.8
    assert row[7] == 120
    assert row[9] == "插件"
    assert fake.invalidated == ["token"]


if __name__ == "__main__":
    main()

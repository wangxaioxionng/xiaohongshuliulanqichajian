import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def extract_function(source: str, name: str) -> str:
    start = source.find(f"function {name}(")
    if start < 0:
        raise AssertionError(f"missing function {name}")
    depth = 0
    body_started = False
    for idx in range(start, len(source)):
        char = source[idx]
        if char == "{":
            depth += 1
            body_started = True
        elif char == "}":
            depth -= 1
            if body_started and depth == 0:
                return source[start:idx + 1]
    raise AssertionError(f"function {name} not closed")


def main() -> None:
    probe = ROOT / "extension/xhs_commerce_probe.js"
    background = (ROOT / "extension/background.js").read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "extension/manifest.json").read_text(encoding="utf-8"))
    popup = (ROOT / "extension/popup.js").read_text(encoding="utf-8")
    popup_html = (ROOT / "extension/popup.html").read_text(encoding="utf-8")
    probe_source = probe.read_text(encoding="utf-8")
    interceptor_source = (ROOT / "extension/xhs_commerce_interceptor.js").read_text(encoding="utf-8")
    if "comment-picture img, .img-box img, img" in probe_source:
        raise AssertionError("comment image selector must not count every img because it includes avatars")

    content_scripts = manifest.get("content_scripts") or []
    commerce_scripts = [
        item for item in content_scripts
        if "xhs_commerce_interceptor.js" in item.get("js", [])
    ]
    if not commerce_scripts:
        raise AssertionError("manifest must inject xhs_commerce_interceptor.js on XHS pages")
    if commerce_scripts[0].get("run_at") != "document_start":
        raise AssertionError("commerce interceptor must run at document_start to catch goods detail API")
    if commerce_scripts[0].get("world") != "MAIN":
        raise AssertionError("commerce interceptor must run in MAIN world to patch page fetch/XHR")
    for needle in [
        "__xhs_intercepted_goods__",
        "/api/store/jpd/edith/detail",
        "xhs-goods-data",
    ]:
        if needle not in interceptor_source:
            raise AssertionError(f"commerce interceptor missing {needle}")

    for needle, label in [
        ("xhs_shop_products_extract_start", "background shop extraction message"),
        ("xhs_comments_extract_start", "background comments extraction message"),
        ("xhs_commerce_probe.js", "commerce probe injection file"),
        ('world: "MAIN"', "page MAIN world injection"),
    ]:
        if needle not in background:
            raise AssertionError(f"missing {label}: {needle}")

    for needle, label in [
        ('class="feature-tabs"', "feature tabs container"),
        ('id="tab-note-extract"', "note extraction tab"),
        ('id="tab-shop-products"', "shop products tab"),
        ('id="page-note-extract"', "note extraction page"),
        ('id="page-shop-products"', "shop products page"),
        ("笔记提取", "note extraction tab title"),
        ("店铺商品", "shop products tab title"),
        ('id="btn-shop-products-prototype"', "shop products button"),
        ('id="btn-comments-prototype"', "comments prototype button"),
        ('id="shop-products-status"', "shop products status area"),
        ('id="comments-prototype-status"', "comments status area"),
    ]:
        if needle not in popup_html:
            raise AssertionError(f"missing {label}: {needle}")
    for forbidden, label in [
        ('id="tab-settings"', "settings tab must be removed"),
        ('id="page-settings"', "settings page must be removed"),
        ("配置设置", "settings title must be removed"),
        ('id="btn-settings-page"', "settings page button must be removed"),
    ]:
        if forbidden in popup_html:
            raise AssertionError(f"{label}: {forbidden}")

    for needle, label in [
        ("setActiveFeatureTab", "popup tab switcher"),
        ("handleShopProductsPrototype", "popup shop handler"),
        ("apiShopProductsCollect", "shop products Feishu writer API"),
        ("/api/shop-products/collect", "shop products collect endpoint"),
        ("handleCommentsPrototype", "popup comments handler"),
        ("showToolStatus", "popup tool status renderer"),
        ('"shop-products-status"', "shop handler writes to its own status area"),
        ('"comments-prototype-status"', "comments handler writes to its own status area"),
        ("isXhsCommercePage", "popup commerce page detector"),
    ]:
        if needle not in popup:
            raise AssertionError(f"missing {label}: {needle}")
    shop_handler_source = extract_function(popup, "handleShopProductsPrototype")
    for forbidden, label in [
        ("本地原型不会写入飞书", "shop products must no longer be local-only"),
        ("暂未写入飞书", "shop products must no longer be local-only"),
    ]:
        if forbidden in shop_handler_source:
            raise AssertionError(f"{label}: {forbidden}")

    commerce_helper = extract_function(popup, "isXhsCommercePage")
    commerce_js = f"""
{commerce_helper}
const cases = [
  ["https://www.xiaohongshu.com/goods-detail/123", true],
  ["https://www.xiaohongshu.com/vendor/seller123", true],
  ["https://www.xiaohongshu.com/explore/abc", false],
  ["https://example.com/vendor/seller123", false],
];
for (const [url, expected] of cases) {{
  const got = isXhsCommercePage(url);
  if (got !== expected) throw new Error(`${{url}} expected ${{expected}} got ${{got}}`);
}}
"""
    commerce_result = subprocess.run(
        ["node", "-e", commerce_js],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if commerce_result.returncode != 0:
        raise AssertionError(commerce_result.stderr.strip() or commerce_result.stdout.strip())

    js = f"""
const probe = require({json.dumps(str(probe))});

const sharedUrl = "https://www.xiaohongshu.com/goods-detail/69bbbc3bff00dc00016e5a53?instation_link=xhsdiscover%3A%2F%2Fgoods_detail%2F69bbbc3bff00dc00016e5a53%3Frate_limit_meta%3DitemId%253D69bbbc3bff00dc00016e5a52%26source%3D";
const ids = probe.itemIdsFromGoodsUrl(sharedUrl);
if (ids[0] !== "69bbbc3bff00dc00016e5a53" || ids[1] !== "69bbbc3bff00dc00016e5a52") {{
  throw new Error(`bad goods url item ids: ${{JSON.stringify(ids)}}`);
}}

const soldCases = [
  ["1.2万已售", 12000],
  ["已售 856", 856],
  [37, 37],
  ["", 0],
];
for (const [input, expected] of soldCases) {{
  const got = probe.normalizeSoldCount(input);
  if (got !== expected) throw new Error(`sold ${{input}} expected ${{expected}} got ${{got}}`);
}}

const shopPayload = {{
  data: {{
    items: [{{
      shop: {{
        seller_id: "seller123",
        name: "小熊耳饰",
        logo: "https://img.example/logo.png",
        grade: "4.9",
        fans_amount: "3.4万",
        sales_volume: "11万"
      }}
    }}]
  }}
}};
const shop = probe.extractShopInfoFromGoodsPayload(shopPayload);
if (shop.sellerId !== "seller123" || shop.shopName !== "小熊耳饰") {{
  throw new Error(`bad shop info: ${{JSON.stringify(shop)}}`);
}}

const skuPayload = {{
  data: {{
    skus: [
      {{
        sku_id: "sku1",
        item_id: "item1",
        card_title: "珍珠耳钉",
        price_info: {{
          expected_price: {{ price: "30.8" }},
          minor_price: {{ price: "39.9" }}
        }},
        stock_status: "有库存",
        image: "https://img.example/a.jpg",
        on_shelf_time: "2026-05-01"
      }},
      {{
        skuId: "sku2",
        itemId: "item2",
        name: "银针耳钉",
        dealPrice: 19.9,
        stock: 6
      }}
    ]
  }}
}};
const products = probe.extractProductsFromSkuListPayload(skuPayload, "seller123");
if (products.length !== 2) throw new Error(`expected 2 products got ${{products.length}}`);
if (products[0].name !== "珍珠耳钉" || products[0].dealPrice !== 30.8) {{
  throw new Error(`bad product parse: ${{JSON.stringify(products[0])}}`);
}}
if (!products[0].goodsUrl.includes("/goods-detail/item1")) {{
  throw new Error(`missing goods url: ${{products[0].goodsUrl}}`);
}}

const merged = probe.mergeProductDetail(products[0], {{
  data: {{
    items: [{{
      descriptionH5: "长期主义耳饰",
      price_info: {{ expected_price: {{ price: "32" }} }},
      sold_count: "1.2万件已售",
      delivery: {{ from: "杭州", fee_text: "包邮", time: "48小时内发货", tag: "现货" }},
      shop: {{ name: "小熊耳饰" }}
    }}]
  }}
}});
if (merged.soldCount !== 12000 || merged.location !== "杭州" || merged.shippingFee !== "包邮") {{
  throw new Error(`bad detail merge: ${{JSON.stringify(merged)}}`);
}}

const summary = probe.computeShopProductSummary([
  {{ dealPrice: 30, soldCount: 100 }},
  {{ dealPrice: 20, soldCount: 5 }},
]);
if (summary.totalProducts !== 2 || summary.totalSoldCount !== 105 || summary.totalSalesAmount !== 3100) {{
  throw new Error(`bad summary: ${{JSON.stringify(summary)}}`);
}}

const linked = probe.attachParentContent([
  probe.normalizeCommentRecord({{ id: "comment-c1", content: " 主评 ", userName: "买家A", likeCount: "1.2万", level: 0, images: ["a.jpg", "a.jpg"] }}),
  probe.normalizeCommentRecord({{ id: "comment-r1", parentId: "comment-c1", content: " 回复 ", userName: "买家B", likeCount: "8", level: 1 }}),
]);
if (linked[0].id !== "c1" || linked[0].images.length !== 1 || linked[0].likeCountNumber !== 12000) {{
  throw new Error(`bad comment normalize: ${{JSON.stringify(linked[0])}}`);
}}
if (linked[1].parentContent !== "主评") {{
  throw new Error(`reply did not inherit parent content: ${{JSON.stringify(linked[1])}}`);
}}

console.log(JSON.stringify({{
  products: products.length,
  shopName: shop.shopName,
  comments: linked.length,
  totalSalesAmount: summary.totalSalesAmount
}}));
"""
    result = subprocess.run(
        ["node", "-e", js],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or result.stdout.strip())


if __name__ == "__main__":
    main()

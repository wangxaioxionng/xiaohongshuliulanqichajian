import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_node_check() -> None:
    js = r"""
const assert = require("assert");
const {
  CONTROLLER_KEY,
  PAGE_PROFILES,
  ROOT_MARKER,
  MENU_MARKER,
  TABLE_MARKER,
  isTargetHeaderList,
  resolvePageProfile,
  buildGridTemplate,
  createController,
} = require("./extension/qianfan_full_table.js");

const headers = [
  "笔记信息",
  "关联商品",
  "发布时间",
  "笔记加购件数",
  "笔记阅读数",
  "笔记支付金额",
  "笔记商品点击次数",
  "笔记支付人数",
  "笔记点击关注次数",
  "平均阅读(观播)时长",
  "评论次数",
  "点赞次数",
  "收藏次数",
  "操作",
];

assert.strictEqual(CONTROLLER_KEY, "__XHS_QIANFAN_FULL_TABLE_V4__");
assert.strictEqual(ROOT_MARKER, "data-xhs-qianfan-wide-workspace");
assert.strictEqual(MENU_MARKER, "data-xhs-qianfan-centered-menu");
assert.strictEqual(TABLE_MARKER, "data-xhs-qianfan-wide-table");
assert.strictEqual(PAGE_PROFILES.length, 15);
assert.strictEqual(new Set(PAGE_PROFILES.map((profile) => profile.path)).size, 15);
assert.deepStrictEqual(
  PAGE_PROFILES.map(({ path, name, minimumHeaders }) => [path, name, minimumHeaders]),
  [
    ["/app-datacenter/note-data/goods", "商品笔记", 14],
    ["/app-datacenter/good-data", "商品总览", 12],
    ["/app-datacenter/business-overview", "成交分析", 11],
    ["/app-datacenter/search-overview", "搜索总览", 9],
    ["/app-datacenter/note-blue-chain", "笔记蓝链", 10],
    ["/app-datacenter/business-refund/pay-time", "退款分析", 7],
    ["/app-datacenter/business-account", "账号分析", 9],
    ["/app-datacenter/live-list", "直播场次", 7],
    ["/app-datacenter/good-data/real-time", "实时商品", 8],
    ["/app-datacenter/search-overview/words", "引流搜索词", 7],
    ["/app-datacenter/business-cps", "买手分析", 9],
    ["/app-item/list/shelf", "售卖中商品", 9],
    ["/app-promotion/promotion-tools/analysis-index", "营销数据", 12],
    ["/app-distribution/create-promotion", "商品合作", 8],
    ["/app-distribution/live-broadcast/kol", "买手广场", 11],
  ]
);
assert.strictEqual(resolvePageProfile("/app-datacenter/good-data").name, "商品总览");
assert.strictEqual(
  resolvePageProfile("https://ark.xiaohongshu.com/app-distribution/live-broadcast/kol?from=menu").name,
  "买手广场"
);
assert.strictEqual(resolvePageProfile("/app-order/order/query"), null);
assert.strictEqual(isTargetHeaderList(headers), true);
assert.strictEqual(
  isTargetHeaderList(["笔记信息", "关联商品", "发布时间", "笔记阅读数"]),
  false
);
assert.ok(buildGridTemplate(14).includes("repeat(10, minmax(84px, 1fr))"));

function makeStyle(initialValues = {}) {
  const values = new Map(Object.entries(initialValues));
  const priorities = new Map();
  return {
    getPropertyValue(name) {
      return values.get(name) || "";
    },
    getPropertyPriority(name) {
      return priorities.get(name) || "";
    },
    setProperty(name, value, priority) {
      values.set(name, String(value));
      priorities.set(name, priority || "");
    },
    removeProperty(name) {
      const previous = values.get(name) || "";
      values.delete(name);
      priorities.delete(name);
      return previous;
    },
  };
}

function makeAttributes() {
  const attributes = new Map();
  return {
    attributes,
    hasAttribute(name) {
      return attributes.has(name);
    },
    getAttribute(name) {
      return attributes.has(name) ? attributes.get(name) : null;
    },
    setAttribute(name, value) {
      attributes.set(name, String(value));
    },
    removeAttribute(name) {
      attributes.delete(name);
    },
  };
}

function makeHeader(text) {
  const labelState = makeAttributes();
  const label = {
    ...labelState,
    textContent: text,
  };
  const header = {
    classList: {
      contains(name) {
        return name === "d-th";
      },
    },
    querySelector() {
      return label;
    },
  };
  Object.defineProperty(header, "textContent", {
    get() {
      return label.textContent;
    },
  });
  return header;
}

const originalColumns = "420px 200px 200px repeat(10, minmax(auto, 1fr)) 100px 0.01px";
const rootState = makeAttributes();
const root = {
  ...rootState,
  style: makeStyle({
    "margin-left": "624.5px",
    "margin-right": "482.5px",
    "min-width": "1234px",
    "overflow-x": "scroll",
  }),
  getBoundingClientRect() {
    return { left: 624.5, right: 1858.5, width: 1234 };
  },
};
const menuState = makeAttributes();
const menu = {
  ...menuState,
  id: "",
  style: makeStyle({
    "margin-left": "482.5px",
  }),
  getBoundingClientRect() {
    return { left: 482.5, right: 624.5, width: 142, height: 1008 };
  },
};
const gridState = makeAttributes();
const grid = {
  ...gridState,
  children: headers.map(makeHeader),
  style: makeStyle({ "grid-template-columns": originalColumns }),
  isConnected: true,
  closest(selector) {
    assert.strictEqual(selector, "#app-root-content-wrapper");
    return root;
  },
};

let styleNode = null;
let observerDisconnected = false;
const listeners = new Map();
const document = {
  body: {},
  documentElement: {
    appendChild(node) {
      styleNode = node;
    },
  },
  head: {
    appendChild(node) {
      styleNode = node;
    },
  },
  querySelectorAll(selector) {
    if (selector === ".d-grid.d-table") return [grid];
    if (selector === ".menu-wrapper-container, #root-menu-wrapper") return [menu];
    throw new Error(`unexpected selector: ${selector}`);
  },
  getElementById(id) {
    if (id === "app-root-content-wrapper") return root;
    return styleNode && styleNode.id === id ? styleNode : null;
  },
  createElement(tag) {
    assert.strictEqual(tag, "style");
    return {
      id: "",
      textContent: "",
      remove() {
        styleNode = null;
      },
    };
  },
};

class FakeMutationObserver {
  constructor(callback) {
    this.callback = callback;
  }
  observe() {}
  disconnect() {
    observerDisconnected = true;
  }
}

const fakeWindow = {
  document,
  location: { pathname: "/app-datacenter/note-data/goods" },
  innerWidth: 2341,
  MutationObserver: FakeMutationObserver,
  requestAnimationFrame(callback) {
    callback();
  },
  setTimeout(callback) {
    callback();
  },
  addEventListener(name, callback) {
    listeners.set(name, callback);
  },
  removeEventListener(name) {
    listeners.delete(name);
  },
};

const controller = createController(fakeWindow);
const enabled = controller.enable();
assert.strictEqual(enabled.ok, true);
assert.strictEqual(enabled.available, true);
assert.strictEqual(enabled.enabled, true);
assert.strictEqual(enabled.columnCount, 14);
assert.strictEqual(enabled.metricCount, 10);
assert.strictEqual(enabled.minimumMetricWidth, 84);
assert.strictEqual(enabled.workspaceWidth, 1692);
assert.strictEqual(enabled.menuAvailable, true);
assert.strictEqual(enabled.outerGap, 253.5);
assert.strictEqual(enabled.centeringError, 0);
assert.strictEqual(gridState.attributes.get("data-xhs-qianfan-full-table"), "on");
assert.strictEqual(rootState.attributes.get(ROOT_MARKER), "on");
assert.strictEqual(menuState.attributes.get(MENU_MARKER), "on");
assert.strictEqual(menu.style.getPropertyValue("margin-left"), "253.5px");
assert.strictEqual(root.style.getPropertyValue("margin-left"), "395.5px");
assert.strictEqual(root.style.getPropertyValue("margin-right"), "253.5px");
assert.strictEqual(root.style.getPropertyValue("min-width"), "0px");
assert.strictEqual(root.style.getPropertyValue("width"), "1692px");
assert.strictEqual(root.style.getPropertyValue("max-width"), "none");
assert.strictEqual(root.style.getPropertyValue("overflow-x"), "auto");
assert.strictEqual(
  grid.style.getPropertyPriority("grid-template-columns"),
  "important"
);
assert.ok(
  grid.style.getPropertyValue("grid-template-columns").includes(
    "repeat(10, minmax(84px, 1fr))"
  )
);
assert.deepStrictEqual(grid.children.map((item) => item.textContent), headers);
assert.ok(styleNode && styleNode.textContent.includes(ROOT_MARKER));
assert.ok(styleNode && styleNode.textContent.includes("white-space: normal !important"));
assert.ok(styleNode && styleNode.textContent.includes("overflow-wrap: anywhere !important"));
assert.strictEqual(listeners.has("resize"), true);

const disabled = controller.disable();
assert.strictEqual(disabled.ok, true);
assert.strictEqual(disabled.enabled, false);
assert.strictEqual(
  grid.style.getPropertyValue("grid-template-columns"),
  originalColumns
);
assert.strictEqual(gridState.attributes.has("data-xhs-qianfan-full-table"), false);
assert.strictEqual(rootState.attributes.has(ROOT_MARKER), false);
assert.strictEqual(root.style.getPropertyValue("margin-left"), "624.5px");
assert.strictEqual(root.style.getPropertyValue("margin-right"), "482.5px");
assert.strictEqual(root.style.getPropertyValue("min-width"), "1234px");
assert.strictEqual(root.style.getPropertyValue("width"), "");
assert.strictEqual(root.style.getPropertyValue("max-width"), "");
assert.strictEqual(root.style.getPropertyValue("overflow-x"), "scroll");
assert.strictEqual(menuState.attributes.has(MENU_MARKER), false);
assert.strictEqual(menu.style.getPropertyValue("margin-left"), "482.5px");
assert.deepStrictEqual(grid.children.map((item) => item.textContent), headers);
assert.strictEqual(styleNode, null);
assert.strictEqual(observerDisconnected, true);
assert.strictEqual(listeners.has("resize"), false);

const mainRootState = makeAttributes();
const mainRoot = {
  ...mainRootState,
  style: makeStyle({
    "margin-left": "1069px",
    "margin-right": "927px",
    "min-width": "1346px",
    "overflow-x": "scroll",
  }),
  getBoundingClientRect() {
    return { left: 1069, right: 2415, width: 1346 };
  },
};
const mainMenuState = makeAttributes();
const mainMenu = {
  ...mainMenuState,
  id: "",
  style: makeStyle({ "margin-left": "927px" }),
  getBoundingClientRect() {
    return { left: 927, right: 1069, width: 142, height: 1530 };
  },
};
const buyerHeaders = [
  "买手信息",
  "粉丝数",
  "场均销售额",
  "客单价",
  "合作品牌场均销售额",
  "单场最高销售额",
  "近期合作天数",
  "笔记阅读中位数",
  "单场观播人数",
  "活跃粉丝占比",
  "操作",
];
const buyerTableState = makeAttributes();
const buyerTable = {
  ...buyerTableState,
  classList: { contains() { return false; } },
  style: makeStyle(),
  clientWidth: 1258,
  scrollWidth: 2268,
  isConnected: true,
  getBoundingClientRect() {
    return { left: 1101, right: 2359, width: 1258, height: 700 };
  },
  closest(selector) {
    assert.strictEqual(selector, "#app-root-content-wrapper");
    return mainRoot;
  },
  querySelectorAll() {
    return buyerHeaders.map((text) => ({ textContent: text }));
  },
};
let mainStyleNode = null;
const mainDocument = {
  body: {},
  documentElement: { appendChild(node) { mainStyleNode = node; } },
  head: { appendChild(node) { mainStyleNode = node; } },
  querySelectorAll(selector) {
    if (selector === ".d-table__content, .d-grid.d-table") return [buyerTable];
    if (selector === ".menu-wrapper-container, #root-menu-wrapper") return [mainMenu];
    throw new Error(`unexpected main selector: ${selector}`);
  },
  getElementById(id) {
    if (id === "app-root-content-wrapper") return mainRoot;
    return mainStyleNode && mainStyleNode.id === id ? mainStyleNode : null;
  },
  createElement(tag) {
    assert.strictEqual(tag, "style");
    return {
      id: "",
      textContent: "",
      remove() { mainStyleNode = null; },
    };
  },
};
const mainController = createController({
  ...fakeWindow,
  document: mainDocument,
  location: { pathname: "/app-distribution/live-broadcast/kol" },
  innerWidth: 3342,
});
const mainEnabled = mainController.enable();
assert.strictEqual(mainEnabled.ok, true);
assert.strictEqual(mainEnabled.pageName, "买手广场");
assert.strictEqual(mainEnabled.columnCount, 11);
assert.strictEqual(mainEnabled.workspaceWidth, 2356);
assert.strictEqual(mainEnabled.requiredWorkspaceWidth, 2356);
assert.strictEqual(mainEnabled.fitsAllTables, true);
assert.strictEqual(mainEnabled.outerGap, 422);
assert.strictEqual(mainEnabled.centeringError, 0);
assert.strictEqual(mainRoot.style.getPropertyValue("margin-left"), "564px");
assert.strictEqual(mainRoot.style.getPropertyValue("margin-right"), "422px");
assert.strictEqual(mainMenu.style.getPropertyValue("margin-left"), "422px");
assert.strictEqual(buyerTableState.attributes.get(TABLE_MARKER), "on");
assert.strictEqual(buyerTable.style.getPropertyValue("width"), "100%");
mainController.disable();
assert.strictEqual(mainRoot.style.getPropertyValue("margin-left"), "1069px");
assert.strictEqual(mainRoot.style.getPropertyValue("margin-right"), "927px");
assert.strictEqual(mainMenu.style.getPropertyValue("margin-left"), "927px");
assert.strictEqual(buyerTableState.attributes.has(TABLE_MARKER), false);
assert.strictEqual(buyerTable.style.getPropertyValue("width"), "");

const emptyDocument = {
  ...mainDocument,
  querySelectorAll(selector) {
    if (selector === ".d-table__content, .d-grid.d-table") return [];
    if (selector === ".menu-wrapper-container, #root-menu-wrapper") return [mainMenu];
    throw new Error(`unexpected empty selector: ${selector}`);
  },
};
const emptyController = createController({
  ...fakeWindow,
  document: emptyDocument,
  location: { pathname: "/app-datacenter/good-data" },
  innerWidth: 3342,
});
const emptyEnabled = emptyController.enable();
assert.strictEqual(emptyEnabled.ok, true);
assert.strictEqual(emptyEnabled.available, true);
assert.strictEqual(emptyEnabled.enabled, true);
assert.strictEqual(emptyEnabled.waitingForTable, true);
assert.strictEqual(emptyEnabled.matchedCount, 0);
emptyController.disable();

for (const profile of PAGE_PROFILES.filter((item) => item.mode !== "note-grid")) {
  const routeRootState = makeAttributes();
  const routeRoot = {
    ...routeRootState,
    style: makeStyle({
      "margin-left": "1069px",
      "margin-right": "927px",
      "min-width": "1346px",
      "overflow-x": "scroll",
    }),
    getBoundingClientRect() {
      return { left: 1069, right: 2415, width: 1346 };
    },
  };
  const routeMenuState = makeAttributes();
  const routeMenu = {
    ...routeMenuState,
    id: "",
    style: makeStyle({ "margin-left": "927px" }),
    getBoundingClientRect() {
      return { left: 927, right: 1069, width: 142, height: 1530 };
    },
  };
  const routeTableState = makeAttributes();
  const shouldExpandContainer = ["promotion_analysis", "distribution_goods"].includes(
    profile.key
  );
  const routeContainer = {
    style: makeStyle({ "max-width": "1258px" }),
    parentElement: routeRoot,
  };
  const routeDirectHeaders = profile.key === "business_overview"
    ? Array.from(
        { length: profile.minimumHeaders },
        (_, index) => ({
          textContent: `${profile.name}${index + 1}`,
          classList: { contains(name) { return name === "d-th"; } },
        })
      )
    : [];
  const routeTable = {
    ...routeTableState,
    classList: { contains() { return false; } },
    children: routeDirectHeaders,
    parentElement: shouldExpandContainer ? routeContainer : null,
    style: makeStyle(),
    clientWidth: 1242,
    scrollWidth: 1730,
    getBoundingClientRect() {
      return { left: 1101, right: 2343, width: 1242, height: 600 };
    },
    closest() { return routeRoot; },
    querySelectorAll() {
      return Array.from(
        { length: profile.minimumHeaders },
        (_, index) => ({ textContent: `${profile.name}${index + 1}` })
      );
    },
  };
  let routeStyleNode = null;
  const routeDocument = {
    body: {},
    documentElement: { appendChild(node) { routeStyleNode = node; } },
    head: { appendChild(node) { routeStyleNode = node; } },
    querySelectorAll(selector) {
      if (selector === ".d-table__content, .d-grid.d-table") return [routeTable];
      if (selector === ".menu-wrapper-container, #root-menu-wrapper") {
        return [routeMenu];
      }
      throw new Error(`unexpected ${profile.name} selector: ${selector}`);
    },
    getElementById(id) {
      if (id === "app-root-content-wrapper") return routeRoot;
      return routeStyleNode && routeStyleNode.id === id ? routeStyleNode : null;
    },
    createElement() {
      return {
        id: "",
        textContent: "",
        remove() { routeStyleNode = null; },
      };
    },
  };
  const routeController = createController({
    ...fakeWindow,
    document: routeDocument,
    location: { pathname: profile.path },
    innerWidth: 3342,
  });
  const routeEnabled = routeController.enable();
  assert.strictEqual(routeEnabled.ok, true, `${profile.name} should enable`);
  assert.strictEqual(routeEnabled.pageKey, profile.key);
  assert.strictEqual(routeEnabled.pageName, profile.name);
  assert.strictEqual(routeEnabled.columnCount, profile.minimumHeaders);
  assert.strictEqual(routeEnabled.matchedCount, 1);
  assert.strictEqual(routeTableState.attributes.get(TABLE_MARKER), "on");
  if (shouldExpandContainer) {
    assert.strictEqual(routeContainer.style.getPropertyValue("width"), "100%");
    assert.strictEqual(routeContainer.style.getPropertyValue("max-width"), "none");
  }
  routeController.disable();
  if (shouldExpandContainer) {
    assert.strictEqual(routeContainer.style.getPropertyValue("width"), "");
    assert.strictEqual(routeContainer.style.getPropertyValue("max-width"), "1258px");
  }
  assert.strictEqual(routeTableState.attributes.has(TABLE_MARKER), false);
  assert.strictEqual(routeRoot.style.getPropertyValue("margin-left"), "1069px");
}

class ThrowingMutationObserver {
  observe() {
    throw new TypeError("offline fixture is not a live Node");
  }
  disconnect() {}
}
const resilientController = createController({
  ...fakeWindow,
  MutationObserver: ThrowingMutationObserver,
});
const resilientEnabled = resilientController.enable();
assert.strictEqual(resilientEnabled.ok, true);
assert.strictEqual(resilientEnabled.enabled, true);
resilientController.disable();

const orphanGridState = makeAttributes();
const orphanGrid = {
  ...orphanGridState,
  children: headers.map(makeHeader),
  style: makeStyle({ "grid-template-columns": originalColumns }),
  closest() { return null; },
};
const missingWorkspaceController = createController({
  location: { pathname: "/app-datacenter/note-data/goods" },
  document: {
    querySelectorAll() { return [orphanGrid]; },
    getElementById() { return null; },
  },
});
const missingWorkspace = missingWorkspaceController.enable();
assert.strictEqual(missingWorkspace.ok, false);
assert.strictEqual(missingWorkspace.code, "workspace_not_found");

const missingMenuController = createController({
  location: { pathname: "/app-datacenter/note-data/goods" },
  document: {
    querySelectorAll(selector) {
      if (selector === ".d-grid.d-table") return [grid];
      return [];
    },
    getElementById(id) {
      return id === "app-root-content-wrapper" ? root : null;
    },
  },
});
const missingMenu = missingMenuController.enable();
assert.strictEqual(missingMenu.ok, false);
assert.strictEqual(missingMenu.code, "menu_not_found");

const missingController = createController({
  location: { pathname: "/app-order/order/query" },
  document: {
    querySelectorAll() { return []; },
    getElementById() { return null; },
  },
});
const missing = missingController.enable();
assert.strictEqual(missing.ok, false);
assert.strictEqual(missing.code, "route_not_supported");
"""
    result = subprocess.run(
        ["node", "-e", js],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or result.stdout.strip())


def main() -> None:
    popup_html = (ROOT / "extension/popup.html").read_text(encoding="utf-8")
    popup_js = (ROOT / "extension/popup.js").read_text(encoding="utf-8")
    qianfan_js = (ROOT / "extension/qianfan_full_table.js").read_text(encoding="utf-8")

    if "font-size: 12px !important" in qianfan_js:
        raise AssertionError("wide-table mode must preserve Qianfan's original font size")

    required_testids = [
        'data-testid="qianfan-full-table-panel"',
        'data-testid="qianfan-full-table-toggle"',
        'data-testid="qianfan-full-table-status"',
    ]
    for testid in required_testids:
        if testid not in popup_html:
            raise AssertionError(f"missing popup acceptance hook: {testid}")

    popup_width_rules = [
        "html {\n      width: 360px;\n      min-width: 360px;\n      max-width: 360px;",
        "body {\n      margin: 0;\n      width: 360px;\n      min-width: 360px;\n      max-width: 360px;",
        "overflow-x: hidden;",
    ]
    for rule in popup_width_rules:
        if rule not in popup_html:
            raise AssertionError(f"missing compact popup width rule: {rule}")

    init_start = popup_js.find("async function init()")
    init_end = popup_js.find("\nasync function handleCollect", init_start)
    init_source = popup_js[init_start:init_end]
    route_pos = init_source.find("if (isQianfanWideTablePage(url))")
    auth_pos = init_source.find("if (!isAuthenticated(cfg))")
    if route_pos < 0 or auth_pos < 0 or route_pos > auth_pos:
        raise AssertionError("Qianfan display route must run before Feishu authentication")

    required_qianfan_paths = [
        "/app-datacenter/good-data",
        "/app-datacenter/business-overview",
        "/app-datacenter/search-overview",
        "/app-datacenter/note-blue-chain",
        "/app-datacenter/business-refund/pay-time",
        "/app-datacenter/business-account",
        "/app-datacenter/live-list",
        "/app-datacenter/good-data/real-time",
        "/app-datacenter/search-overview/words",
        "/app-datacenter/business-cps",
        "/app-item/list/shelf",
        "/app-promotion/promotion-tools/analysis-index",
        "/app-distribution/create-promotion",
        "/app-distribution/live-broadcast/kol",
    ]
    for path in required_qianfan_paths:
        if path not in popup_js:
            raise AssertionError(f"missing Qianfan wide-table route: {path}")

    required_states = [
        "正在检测表格",
        "重新检测并开启宽屏",
        "开启宽屏分析",
        "恢复官方布局",
        "调整失败",
    ]
    for text in required_states:
        if text not in popup_js:
            raise AssertionError(f"missing Qianfan UI state: {text}")

    run_node_check()


if __name__ == "__main__":
    main()

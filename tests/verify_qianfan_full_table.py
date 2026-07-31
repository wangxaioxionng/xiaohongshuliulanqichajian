import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_node_check() -> None:
    js = r"""
const assert = require("assert");
const {
  CONTROLLER_KEY,
  ROOT_MARKER,
  MENU_MARKER,
  isTargetHeaderList,
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

assert.strictEqual(CONTROLLER_KEY, "__XHS_QIANFAN_FULL_TABLE_V3__");
assert.strictEqual(ROOT_MARKER, "data-xhs-qianfan-wide-workspace");
assert.strictEqual(MENU_MARKER, "data-xhs-qianfan-centered-menu");
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
assert.strictEqual(root.style.getPropertyValue("width"), "auto");
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
  document: {
    querySelectorAll() { return [orphanGrid]; },
    getElementById() { return null; },
  },
});
const missingWorkspace = missingWorkspaceController.enable();
assert.strictEqual(missingWorkspace.ok, false);
assert.strictEqual(missingWorkspace.code, "workspace_not_found");

const missingMenuController = createController({
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
  document: {
    querySelectorAll() { return []; },
    getElementById() { return null; },
  },
});
const missing = missingController.enable();
assert.strictEqual(missing.ok, false);
assert.strictEqual(missing.code, "table_not_found");
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
    route_pos = init_source.find("if (isQianfanNoteDataPage(url, rawTitle))")
    auth_pos = init_source.find("if (!isAuthenticated(cfg))")
    if route_pos < 0 or auth_pos < 0 or route_pos > auth_pos:
        raise AssertionError("Qianfan display route must run before Feishu authentication")

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

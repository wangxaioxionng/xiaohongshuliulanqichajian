import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_node_check() -> None:
    js = r"""
const assert = require("assert");
const {
  CONTROLLER_KEY,
  isTargetHeaderList,
  buildGridTemplate,
  compactHeaderLabel,
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

assert.strictEqual(CONTROLLER_KEY, "__XHS_QIANFAN_FULL_TABLE_V1__");
assert.strictEqual(isTargetHeaderList(headers), true);
assert.strictEqual(
  isTargetHeaderList(["笔记信息", "关联商品", "发布时间", "笔记阅读数"]),
  false
);
assert.ok(buildGridTemplate(14).includes("repeat(10, minmax(56px, 1fr))"));
assert.strictEqual(compactHeaderLabel("笔记商品点击次数"), "商品点击");
assert.strictEqual(compactHeaderLabel("平均阅读(观播)时长"), "平均时长");
assert.strictEqual(compactHeaderLabel("操作"), "操作");

function makeStyle(initialValue) {
  const values = new Map([["grid-template-columns", initialValue]]);
  const priorities = new Map();
  return {
    getPropertyValue(name) {
      return values.get(name) || "";
    },
    getPropertyPriority(name) {
      return priorities.get(name) || "";
    },
    setProperty(name, value, priority) {
      values.set(name, value);
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

function makeHeader(text) {
  const labelAttributes = new Map();
  const label = {
    textContent: text,
    hasAttribute(name) {
      return labelAttributes.has(name);
    },
    getAttribute(name) {
      return labelAttributes.has(name) ? labelAttributes.get(name) : null;
    },
    setAttribute(name, value) {
      labelAttributes.set(name, String(value));
    },
    removeAttribute(name) {
      labelAttributes.delete(name);
    },
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
const attributes = new Map();
const grid = {
  children: headers.map(makeHeader),
  style: makeStyle(originalColumns),
  isConnected: true,
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
    assert.strictEqual(selector, ".d-grid.d-table");
    return [grid];
  },
  getElementById(id) {
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
assert.strictEqual(attributes.get("data-xhs-qianfan-full-table"), "on");
assert.strictEqual(
  grid.style.getPropertyPriority("grid-template-columns"),
  "important"
);
assert.ok(
  grid.style.getPropertyValue("grid-template-columns").includes(
    "repeat(10, minmax(56px, 1fr))"
  )
);
assert.ok(styleNode && styleNode.textContent.includes("min-width: 0 !important"));
assert.strictEqual(listeners.has("resize"), true);

const disabled = controller.disable();
assert.strictEqual(disabled.ok, true);
assert.strictEqual(disabled.enabled, false);
assert.strictEqual(
  grid.style.getPropertyValue("grid-template-columns"),
  originalColumns
);
assert.strictEqual(attributes.has("data-xhs-qianfan-full-table"), false);
assert.deepStrictEqual(grid.children.map((item) => item.textContent), headers);
assert.strictEqual(styleNode, null);
assert.strictEqual(observerDisconnected, true);
assert.strictEqual(listeners.has("resize"), false);
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

    init_start = popup_js.find("async function init()")
    init_end = popup_js.find("\nasync function handleCollect", init_start)
    init_source = popup_js[init_start:init_end]
    route_pos = init_source.find("if (isQianfanNoteDataPage(url, rawTitle))")
    auth_pos = init_source.find("if (!isAuthenticated(cfg))")
    if route_pos < 0 or auth_pos < 0 or route_pos > auth_pos:
        raise AssertionError("Qianfan display route must run before Feishu authentication")

    required_states = [
        "正在检测表格",
        "重新检测并全量显示",
        "恢复官方布局",
        "调整失败",
    ]
    for text in required_states:
        if text not in popup_js:
            raise AssertionError(f"missing Qianfan UI state: {text}")

    run_node_check()


if __name__ == "__main__":
    main()

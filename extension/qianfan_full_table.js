// 千帆「商品笔记 - 笔记列表」全量显示控制器。
// 仅修改当前浏览器标签页的展示，不读取、上传或改写店铺数据。
(function initQianfanFullTableModule() {
  "use strict";

  const CONTROLLER_KEY = "__XHS_QIANFAN_FULL_TABLE_V1__";
  const STYLE_ID = "xhs-qianfan-full-table-style";
  const GRID_MARKER = "data-xhs-qianfan-full-table";
  const TARGET_BASE_HEADERS = ["笔记信息", "关联商品", "发布时间", "操作"];
  const TARGET_METRIC_HEADERS = ["笔记加购件数", "笔记阅读数", "加购件数", "阅读数"];
  const COMPACT_HEADER_LABELS = {
    笔记加购件数: "加购件数",
    笔记阅读数: "阅读数",
    笔记支付金额: "支付金额",
    笔记商品点击次数: "商品点击",
    笔记支付人数: "支付人数",
    笔记点击关注次数: "点击关注",
    "平均阅读(观播)时长": "平均时长",
    评论次数: "评论",
    点赞次数: "点赞",
    收藏次数: "收藏",
  };

  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, "").trim();
  }

  function isTargetHeaderList(headerNames) {
    const normalized = (headerNames || []).map(normalizeText);
    const hasBaseHeaders = TARGET_BASE_HEADERS.every((name) => normalized.includes(name));
    const hasMetricHeader = TARGET_METRIC_HEADERS.some((name) => normalized.includes(name));
    return hasBaseHeaders && hasMetricHeader && normalized.length >= 6;
  }

  function buildGridTemplate(headerCount) {
    const safeHeaderCount = Math.max(5, Number(headerCount) || 0);
    const metricCount = Math.max(1, safeHeaderCount - 4);
    return [
      "minmax(220px, 2.4fr)",
      "80px",
      "124px",
      `repeat(${metricCount}, minmax(56px, 1fr))`,
      "72px",
      "0.01px",
    ].join(" ");
  }

  function compactHeaderLabel(value) {
    const normalized = normalizeText(value);
    return COMPACT_HEADER_LABELS[normalized] || String(value || "").trim();
  }

  function getDirectHeaders(grid) {
    return Array.from((grid && grid.children) || []).filter(
      (child) => child.classList && child.classList.contains("d-th")
    );
  }

  function createController(targetWindow) {
    const doc = targetWindow.document;
    const trackedGrids = new Map();
    const trackedLabels = new Map();
    let enabled = false;
    let observer = null;
    let resizeBound = false;
    let scheduled = false;

    function findTargetGrids() {
      return Array.from(doc.querySelectorAll(".d-grid.d-table")).filter((grid) => {
        const names = getDirectHeaders(grid).map((header) => header.textContent || "");
        return isTargetHeaderList(names);
      });
    }

    function ensureStyle() {
      if (doc.getElementById(STYLE_ID)) return;
      const style = doc.createElement("style");
      style.id = STYLE_ID;
      style.textContent = `
        .d-grid.d-table[${GRID_MARKER}="on"] > .d-th,
        .d-grid.d-table[${GRID_MARKER}="on"] > .d-td {
          min-width: 0 !important;
          padding-left: 6px !important;
          padding-right: 6px !important;
          font-size: 12px !important;
        }
        .d-grid.d-table[${GRID_MARKER}="on"] > .d-th .d-th-main {
          justify-content: center !important;
        }
        .d-grid.d-table[${GRID_MARKER}="on"] > .d-th .d-text,
        .d-grid.d-table[${GRID_MARKER}="on"] > .d-th .d-text-nowrap {
          min-width: 0 !important;
          white-space: nowrap !important;
          overflow: visible !important;
          text-overflow: clip !important;
          font-size: 11px !important;
          line-height: 15px !important;
          text-align: center !important;
        }
        .d-grid.d-table[${GRID_MARKER}="on"] > .d-td .d-text {
          min-width: 0 !important;
          font-size: 12px !important;
        }
      `;
      (doc.head || doc.documentElement).appendChild(style);
    }

    function rememberGrid(grid) {
      if (trackedGrids.has(grid)) return;
      trackedGrids.set(grid, {
        columnsValue: grid.style.getPropertyValue("grid-template-columns"),
        columnsPriority: grid.style.getPropertyPriority("grid-template-columns"),
        markerExisted: grid.hasAttribute(GRID_MARKER),
        markerValue: grid.getAttribute(GRID_MARKER),
      });
    }

    function applyGrid(grid) {
      const headerCount = getDirectHeaders(grid).length;
      if (headerCount < 5) return false;
      rememberGrid(grid);
      getDirectHeaders(grid).forEach((header) => {
        if (typeof header.querySelector !== "function") return;
        const label = header.querySelector(".d-th-main .d-text, .d-text");
        if (!label || trackedLabels.has(label)) return;
        const originalText = label.textContent || "";
        const compactText = compactHeaderLabel(originalText);
        if (!compactText || compactText === originalText.trim()) return;
        trackedLabels.set(label, {
          text: originalText,
          titleExisted: label.hasAttribute("title"),
          title: label.getAttribute("title"),
        });
        label.textContent = compactText;
        label.setAttribute("title", normalizeText(originalText));
      });
      grid.setAttribute(GRID_MARKER, "on");
      grid.style.setProperty(
        "grid-template-columns",
        buildGridTemplate(headerCount),
        "important"
      );
      return true;
    }

    function applyAll() {
      if (!enabled) return 0;
      ensureStyle();
      return findTargetGrids().reduce(
        (count, grid) => count + (applyGrid(grid) ? 1 : 0),
        0
      );
    }

    function scheduleApply() {
      if (!enabled || scheduled) return;
      scheduled = true;
      const run = () => {
        scheduled = false;
        applyAll();
      };
      if (typeof targetWindow.requestAnimationFrame === "function") {
        targetWindow.requestAnimationFrame(run);
      } else {
        targetWindow.setTimeout(run, 0);
      }
    }

    function restoreAll() {
      trackedGrids.forEach((original, grid) => {
        if (original.columnsValue) {
          grid.style.setProperty(
            "grid-template-columns",
            original.columnsValue,
            original.columnsPriority || ""
          );
        } else {
          grid.style.removeProperty("grid-template-columns");
        }
        if (original.markerExisted) {
          grid.setAttribute(GRID_MARKER, original.markerValue || "");
        } else {
          grid.removeAttribute(GRID_MARKER);
        }
      });
      trackedGrids.clear();
      trackedLabels.forEach((original, label) => {
        label.textContent = original.text;
        if (original.titleExisted) {
          label.setAttribute("title", original.title || "");
        } else {
          label.removeAttribute("title");
        }
      });
      trackedLabels.clear();
      const style = doc.getElementById(STYLE_ID);
      if (style) style.remove();
    }

    function startWatching() {
      if (!observer && typeof targetWindow.MutationObserver === "function") {
        observer = new targetWindow.MutationObserver(scheduleApply);
        observer.observe(doc.body || doc.documentElement, {
          childList: true,
          subtree: true,
        });
      }
      if (!resizeBound && typeof targetWindow.addEventListener === "function") {
        targetWindow.addEventListener("resize", scheduleApply);
        resizeBound = true;
      }
    }

    function stopWatching() {
      if (observer) {
        observer.disconnect();
        observer = null;
      }
      if (resizeBound && typeof targetWindow.removeEventListener === "function") {
        targetWindow.removeEventListener("resize", scheduleApply);
        resizeBound = false;
      }
    }

    function status() {
      const targets = findTargetGrids();
      const headerCounts = targets.map((grid) => getDirectHeaders(grid).length);
      const columnCount = headerCounts.length ? Math.max(...headerCounts) : 0;
      return {
        ok: true,
        available: targets.length > 0,
        enabled,
        matchedCount: targets.length,
        columnCount,
        metricCount: Math.max(0, columnCount - 4),
      };
    }

    function enable() {
      const availableTargets = findTargetGrids();
      if (!availableTargets.length) {
        return {
          ok: false,
          available: false,
          enabled: false,
          code: "table_not_found",
          message: "还没识别到“笔记列表”表格，请等页面加载完成后重试。",
        };
      }
      enabled = true;
      ensureStyle();
      const matchedCount = availableTargets.reduce(
        (count, grid) => count + (applyGrid(grid) ? 1 : 0),
        0
      );
      startWatching();
      return { ...status(), matchedCount };
    }

    function disable() {
      const previousStatus = status();
      enabled = false;
      stopWatching();
      restoreAll();
      return {
        ...previousStatus,
        ok: true,
        enabled: false,
      };
    }

    function toggle() {
      return enabled ? disable() : enable();
    }

    return { status, enable, disable, toggle };
  }

  const exportsForTest = {
    CONTROLLER_KEY,
    normalizeText,
    isTargetHeaderList,
    buildGridTemplate,
    compactHeaderLabel,
    createController,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = exportsForTest;
  }

  if (typeof window === "undefined" || !window.document) return;
  if (!window[CONTROLLER_KEY]) {
    window[CONTROLLER_KEY] = createController(window);
  }
})();

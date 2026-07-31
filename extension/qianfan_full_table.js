// 千帆「商品笔记 - 笔记列表」全量显示控制器。
// 仅修改当前浏览器标签页的展示，不读取、上传或改写店铺数据。
(function initQianfanFullTableModule() {
  "use strict";

  const CONTROLLER_KEY = "__XHS_QIANFAN_FULL_TABLE_V3__";
  const LEGACY_CONTROLLER_KEYS = [
    "__XHS_QIANFAN_FULL_TABLE_V1__",
    "__XHS_QIANFAN_FULL_TABLE_V2__",
  ];
  const STYLE_ID = "xhs-qianfan-wide-workspace-style";
  const GRID_MARKER = "data-xhs-qianfan-full-table";
  const ROOT_MARKER = "data-xhs-qianfan-wide-workspace";
  const MENU_MARKER = "data-xhs-qianfan-centered-menu";
  const WIDE_EDGE_GAP = 24;
  const TARGET_BASE_HEADERS = ["笔记信息", "关联商品", "发布时间", "操作"];
  const TARGET_METRIC_HEADERS = ["笔记加购件数", "笔记阅读数", "加购件数", "阅读数"];

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
      "minmax(280px, 2.5fr)",
      "110px",
      "152px",
      `repeat(${metricCount}, minmax(84px, 1fr))`,
      "88px",
      "0.01px",
    ].join(" ");
  }

  function getDirectHeaders(grid) {
    return Array.from((grid && grid.children) || []).filter(
      (child) => child.classList && child.classList.contains("d-th")
    );
  }

  function createController(targetWindow) {
    const doc = targetWindow.document;
    const trackedGrids = new Map();
    const trackedWorkspaceRoots = new Map();
    const trackedWorkspaceMenus = new Map();
    const layoutBaselines = new Map();
    let enabled = false;
    let observer = null;
    let resizeBound = false;
    let scheduled = false;
    let lastLayout = null;

    function findTargetGrids() {
      return Array.from(doc.querySelectorAll(".d-grid.d-table")).filter((grid) => {
        const names = getDirectHeaders(grid).map((header) => header.textContent || "");
        return isTargetHeaderList(names);
      });
    }

    function findWorkspaceRoot(grid) {
      if (grid && typeof grid.closest === "function") {
        const root = grid.closest("#app-root-content-wrapper");
        if (root) return root;
      }
      return doc.getElementById("app-root-content-wrapper");
    }

    function findWorkspaceMenu(root) {
      if (!root || typeof doc.querySelectorAll !== "function") return null;
      const candidates = Array.from(
        doc.querySelectorAll(".menu-wrapper-container, #root-menu-wrapper")
      ).map((candidate) => (
        candidate.id === "root-menu-wrapper"
        && typeof candidate.closest === "function"
        && candidate.closest(".menu-wrapper-container")
      ) || candidate);
      const rootRect = typeof root.getBoundingClientRect === "function"
        ? root.getBoundingClientRect()
        : null;
      return candidates.find((candidate) => {
        if (!candidate || typeof candidate.getBoundingClientRect !== "function") return false;
        const rect = candidate.getBoundingClientRect();
        if (!rect || Number(rect.width) <= 0 || Number(rect.height) <= 0) return false;
        if (!rootRect) return true;
        return Number(rect.right) <= Number(rootRect.left) + 4
          && Number(rootRect.left) - Number(rect.right) <= 48;
      }) || null;
    }

    function rememberWorkspaceRoot(root) {
      if (!root || trackedWorkspaceRoots.has(root)) return;
      const properties = {};
      [
        "margin-left",
        "margin-right",
        "min-width",
        "width",
        "max-width",
        "overflow-x",
      ].forEach((name) => {
        properties[name] = {
          value: root.style.getPropertyValue(name),
          priority: root.style.getPropertyPriority(name),
        };
      });
      trackedWorkspaceRoots.set(root, {
        properties,
        markerExisted: root.hasAttribute(ROOT_MARKER),
        markerValue: root.getAttribute(ROOT_MARKER),
      });
    }

    function rememberWorkspaceMenu(menu) {
      if (!menu || trackedWorkspaceMenus.has(menu)) return;
      trackedWorkspaceMenus.set(menu, {
        marginLeftValue: menu.style.getPropertyValue("margin-left"),
        marginLeftPriority: menu.style.getPropertyPriority("margin-left"),
        markerExisted: menu.hasAttribute(MENU_MARKER),
        markerValue: menu.getAttribute(MENU_MARKER),
      });
    }

    function readPixelValue(element, propertyName, fallback) {
      const inlineValue = element && element.style
        ? Number.parseFloat(element.style.getPropertyValue(propertyName))
        : Number.NaN;
      if (Number.isFinite(inlineValue)) return inlineValue;
      if (typeof targetWindow.getComputedStyle === "function" && element) {
        const computedValue = Number.parseFloat(
          targetWindow.getComputedStyle(element).getPropertyValue(propertyName)
        );
        if (Number.isFinite(computedValue)) return computedValue;
      }
      return fallback;
    }

    function rememberLayoutBaseline(root, menu) {
      if (layoutBaselines.has(root)) return layoutBaselines.get(root);
      const rootRect = root && typeof root.getBoundingClientRect === "function"
        ? root.getBoundingClientRect()
        : null;
      const menuRect = menu && typeof menu.getBoundingClientRect === "function"
        ? menu.getBoundingClientRect()
        : null;
      if (!rootRect || !menuRect) return null;
      const baseline = {
        rootLeft: Number(rootRect.left) || 0,
        menuLeft: Number(menuRect.left) || 0,
        rootMarginLeft: readPixelValue(root, "margin-left", Number(rootRect.left) || 0),
        menuMarginLeft: readPixelValue(menu, "margin-left", Number(menuRect.left) || 0),
      };
      layoutBaselines.set(root, baseline);
      return baseline;
    }

    function calculateCenteredLayout(root, menu) {
      const viewportWidth = Number(targetWindow.innerWidth) || 0;
      const baseline = rememberLayoutBaseline(root, menu);
      if (!baseline || !viewportWidth) {
        return {
          menuLeftGap: WIDE_EDGE_GAP,
          leftGap: 166,
          rightGap: WIDE_EDGE_GAP,
          workspaceWidth: 0,
          centeringError: 0,
        };
      }
      const normalizedMenuLeft = Math.round(baseline.menuLeft);
      const outerGap = Math.max(
        WIDE_EDGE_GAP,
        (normalizedMenuLeft + WIDE_EDGE_GAP) / 2
      );
      const shiftLeft = Math.max(0, baseline.menuLeft - outerGap);
      const menuLeftGap = Math.max(
        WIDE_EDGE_GAP,
        baseline.menuMarginLeft - shiftLeft
      );
      const leftGap = Math.max(
        menuLeftGap,
        baseline.rootMarginLeft - shiftLeft
      );
      const rightGap = outerGap;
      return {
        menuLeftGap,
        leftGap,
        rightGap,
        workspaceWidth: Math.max(0, viewportWidth - leftGap - rightGap),
        centeringError: Math.abs(menuLeftGap - rightGap),
      };
    }

    function applyWorkspaceLayout(root, menu) {
      if (!root || !menu) return null;
      rememberWorkspaceRoot(root);
      rememberWorkspaceMenu(menu);
      const layout = calculateCenteredLayout(root, menu);
      root.setAttribute(ROOT_MARKER, "on");
      menu.setAttribute(MENU_MARKER, "on");
      menu.style.setProperty("margin-left", `${layout.menuLeftGap}px`, "important");
      root.style.setProperty("margin-left", `${layout.leftGap}px`, "important");
      root.style.setProperty("margin-right", `${layout.rightGap}px`, "important");
      root.style.setProperty("min-width", "0px", "important");
      root.style.setProperty("width", "auto", "important");
      root.style.setProperty("max-width", "none", "important");
      root.style.setProperty("overflow-x", "auto", "important");
      lastLayout = layout;
      return layout;
    }

    function ensureStyle() {
      if (doc.getElementById(STYLE_ID)) return;
      const style = doc.createElement("style");
      style.id = STYLE_ID;
      style.textContent = `
        #app-root-content-wrapper[${ROOT_MARKER}="on"] {
          box-sizing: border-box !important;
          max-width: none !important;
        }
        #app-root-content-wrapper[${ROOT_MARKER}="on"] .page-container,
        #app-root-content-wrapper[${ROOT_MARKER}="on"] .dc-module-block,
        #app-root-content-wrapper[${ROOT_MARKER}="on"] .dc-module-block__content {
          width: 100% !important;
          max-width: none !important;
          box-sizing: border-box !important;
        }
        .d-grid.d-table[${GRID_MARKER}="on"] {
          width: 100% !important;
          max-width: none !important;
        }
        .d-grid.d-table[${GRID_MARKER}="on"] > .d-th,
        .d-grid.d-table[${GRID_MARKER}="on"] > .d-td {
          min-width: 0 !important;
          padding-left: 8px !important;
          padding-right: 8px !important;
          font-size: 12px !important;
        }
        .d-grid.d-table[${GRID_MARKER}="on"] > .d-th .d-th-main {
          min-width: 0 !important;
          justify-content: center !important;
        }
        .d-grid.d-table[${GRID_MARKER}="on"] > .d-th .d-text,
        .d-grid.d-table[${GRID_MARKER}="on"] > .d-th .d-text-nowrap {
          min-width: 0 !important;
          white-space: normal !important;
          overflow: visible !important;
          text-overflow: clip !important;
          word-break: normal !important;
          overflow-wrap: anywhere !important;
          font-size: 12px !important;
          line-height: 16px !important;
          text-align: center !important;
        }
        .d-grid.d-table[${GRID_MARKER}="on"] > .d-td .d-text {
          min-width: 0 !important;
          font-size: 12px !important;
          line-height: 18px !important;
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
      return findTargetGrids().reduce((count, grid) => {
        const workspaceRoot = findWorkspaceRoot(grid);
        applyWorkspaceLayout(workspaceRoot, findWorkspaceMenu(workspaceRoot));
        return count + (applyGrid(grid) ? 1 : 0);
      }, 0);
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
      trackedWorkspaceRoots.forEach((original, root) => {
        Object.entries(original.properties).forEach(([name, saved]) => {
          if (saved.value) {
            root.style.setProperty(name, saved.value, saved.priority || "");
          } else {
            root.style.removeProperty(name);
          }
        });
        if (original.markerExisted) {
          root.setAttribute(ROOT_MARKER, original.markerValue || "");
        } else {
          root.removeAttribute(ROOT_MARKER);
        }
      });
      trackedWorkspaceRoots.clear();
      trackedWorkspaceMenus.forEach((original, menu) => {
        if (original.marginLeftValue) {
          menu.style.setProperty(
            "margin-left",
            original.marginLeftValue,
            original.marginLeftPriority || ""
          );
        } else {
          menu.style.removeProperty("margin-left");
        }
        if (original.markerExisted) {
          menu.setAttribute(MENU_MARKER, original.markerValue || "");
        } else {
          menu.removeAttribute(MENU_MARKER);
        }
      });
      trackedWorkspaceMenus.clear();
      layoutBaselines.clear();
      lastLayout = null;
      const style = doc.getElementById(STYLE_ID);
      if (style) style.remove();
    }

    function startWatching() {
      if (!observer && typeof targetWindow.MutationObserver === "function") {
        observer = new targetWindow.MutationObserver(scheduleApply);
        try {
          observer.observe(doc.body || doc.documentElement, {
            childList: true,
            subtree: true,
          });
        } catch (error) {
          observer.disconnect();
          observer = null;
        }
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
      const workspaceRoot = targets.length ? findWorkspaceRoot(targets[0]) : null;
      const workspaceMenu = workspaceRoot ? findWorkspaceMenu(workspaceRoot) : null;
      const workspaceRect = workspaceRoot && typeof workspaceRoot.getBoundingClientRect === "function"
        ? workspaceRoot.getBoundingClientRect()
        : null;
      return {
        ok: true,
        available: targets.length > 0 && Boolean(workspaceRoot) && Boolean(workspaceMenu),
        tableAvailable: targets.length > 0,
        workspaceAvailable: Boolean(workspaceRoot),
        menuAvailable: Boolean(workspaceMenu),
        enabled,
        matchedCount: targets.length,
        columnCount,
        metricCount: Math.max(0, columnCount - 4),
        workspaceWidth: workspaceRect ? Math.round(Number(workspaceRect.width) || 0) : 0,
        minimumMetricWidth: 84,
        outerGap: lastLayout ? lastLayout.rightGap : 0,
        centeringError: lastLayout ? lastLayout.centeringError : 0,
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
      const workspaceRoot = findWorkspaceRoot(availableTargets[0]);
      if (!workspaceRoot) {
        return {
          ok: false,
          available: false,
          tableAvailable: true,
          workspaceAvailable: false,
          enabled: false,
          code: "workspace_not_found",
          message: "已经识别表格，但没有找到千帆页面外壳。请刷新千帆页面后重试。",
        };
      }
      const workspaceMenu = findWorkspaceMenu(workspaceRoot);
      if (!workspaceMenu) {
        return {
          ok: false,
          available: false,
          tableAvailable: true,
          workspaceAvailable: true,
          menuAvailable: false,
          enabled: false,
          code: "menu_not_found",
          message: "已经识别表格，但没有找到千帆左侧菜单。请刷新千帆页面后重试。",
        };
      }
      enabled = true;
      ensureStyle();
      const layout = applyWorkspaceLayout(workspaceRoot, workspaceMenu);
      const matchedCount = availableTargets.reduce(
        (count, grid) => count + (applyGrid(grid) ? 1 : 0),
        0
      );
      startWatching();
      return {
        ...status(),
        matchedCount,
        workspaceWidth: layout && layout.workspaceWidth
          ? layout.workspaceWidth
          : status().workspaceWidth,
      };
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
    ROOT_MARKER,
    MENU_MARKER,
    normalizeText,
    isTargetHeaderList,
    buildGridTemplate,
    createController,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = exportsForTest;
  }

  if (typeof window === "undefined" || !window.document) return;
  if (!window[CONTROLLER_KEY]) {
    LEGACY_CONTROLLER_KEYS.forEach((key) => {
      const legacyController = window[key];
      if (legacyController && typeof legacyController.disable === "function") {
        try {
          legacyController.disable();
        } catch (error) {
          // 旧版控制器恢复失败不阻断新版加载；新版仍会重新设置并保留恢复路径。
        }
      }
    });
    window[CONTROLLER_KEY] = createController(window);
  }
})();

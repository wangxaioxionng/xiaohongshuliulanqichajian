// 千帆宽表页面全量显示控制器。
// 仅修改当前浏览器标签页的展示，不读取、上传或改写店铺数据。
(function initQianfanFullTableModule() {
  "use strict";

  const CONTROLLER_KEY = "__XHS_QIANFAN_FULL_TABLE_V4__";
  const LEGACY_CONTROLLER_KEYS = [
    "__XHS_QIANFAN_FULL_TABLE_V1__",
    "__XHS_QIANFAN_FULL_TABLE_V2__",
    "__XHS_QIANFAN_FULL_TABLE_V3__",
  ];
  const STYLE_ID = "xhs-qianfan-wide-workspace-style";
  const GRID_MARKER = "data-xhs-qianfan-full-table";
  const TABLE_MARKER = "data-xhs-qianfan-wide-table";
  const ROOT_MARKER = "data-xhs-qianfan-wide-workspace";
  const MENU_MARKER = "data-xhs-qianfan-centered-menu";
  const WIDE_EDGE_GAP = 24;
  const TARGET_BASE_HEADERS = ["笔记信息", "关联商品", "发布时间", "操作"];
  const TARGET_METRIC_HEADERS = ["笔记加购件数", "笔记阅读数", "加购件数", "阅读数"];
  const PAGE_PROFILES = Object.freeze([
    { key: "note_goods", path: "/app-datacenter/note-data/goods", name: "商品笔记", minimumHeaders: 14, mode: "note-grid" },
    { key: "goods_overview", path: "/app-datacenter/good-data", name: "商品总览", minimumHeaders: 12 },
    { key: "business_overview", path: "/app-datacenter/business-overview", name: "成交分析", minimumHeaders: 11 },
    { key: "search_overview", path: "/app-datacenter/search-overview", name: "搜索总览", minimumHeaders: 9 },
    { key: "note_blue_chain", path: "/app-datacenter/note-blue-chain", name: "笔记蓝链", minimumHeaders: 10 },
    { key: "business_refund", path: "/app-datacenter/business-refund/pay-time", name: "退款分析", minimumHeaders: 7 },
    { key: "business_account", path: "/app-datacenter/business-account", name: "账号分析", minimumHeaders: 9 },
    { key: "live_list", path: "/app-datacenter/live-list", name: "直播场次", minimumHeaders: 7 },
    { key: "goods_realtime", path: "/app-datacenter/good-data/real-time", name: "实时商品", minimumHeaders: 8 },
    { key: "search_words", path: "/app-datacenter/search-overview/words", name: "引流搜索词", minimumHeaders: 7 },
    { key: "business_cps", path: "/app-datacenter/business-cps", name: "买手分析", minimumHeaders: 9 },
    { key: "item_shelf", path: "/app-item/list/shelf", name: "售卖中商品", minimumHeaders: 9 },
    { key: "promotion_analysis", path: "/app-promotion/promotion-tools/analysis-index", name: "营销数据", minimumHeaders: 12 },
    { key: "distribution_goods", path: "/app-distribution/create-promotion", name: "商品合作", minimumHeaders: 8 },
    { key: "buyer_square", path: "/app-distribution/live-broadcast/kol", name: "买手广场", minimumHeaders: 11 },
  ]);

  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, "").trim();
  }

  function isTargetHeaderList(headerNames) {
    const normalized = (headerNames || []).map(normalizeText);
    const hasBaseHeaders = TARGET_BASE_HEADERS.every((name) => normalized.includes(name));
    const hasMetricHeader = TARGET_METRIC_HEADERS.some((name) => normalized.includes(name));
    return hasBaseHeaders && hasMetricHeader && normalized.length >= 6;
  }

  function resolvePageProfile(rawLocation) {
    let pathname = "";
    if (typeof rawLocation === "string") {
      try {
        pathname = new URL(rawLocation, "https://ark.xiaohongshu.com").pathname;
      } catch (error) {
        pathname = rawLocation;
      }
    } else if (rawLocation && typeof rawLocation.pathname === "string") {
      pathname = rawLocation.pathname;
    }
    return PAGE_PROFILES.find((profile) => profile.path === pathname) || null;
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

  function getTableHeaders(table) {
    if (!table) return [];
    const directHeaders = getDirectHeaders(table);
    if (directHeaders.length) return directHeaders;
    if (typeof table.querySelectorAll !== "function") return [];
    return Array.from(
      table.querySelectorAll(
        "th, [role=\"columnheader\"], .d-table__header-cell, .d-th"
      )
    );
  }

  function createController(targetWindow) {
    const doc = targetWindow.document;
    const trackedTables = new Map();
    const trackedTableContainers = new Map();
    const trackedWorkspaceRoots = new Map();
    const trackedWorkspaceMenus = new Map();
    const layoutBaselines = new Map();
    let enabled = false;
    let observer = null;
    let resizeBound = false;
    let scheduled = false;
    let lastLayout = null;
    let activeProfileKey = "";
    let baseStyleText = "";

    function getCurrentProfile() {
      return resolvePageProfile(targetWindow.location || "");
    }

    function isVisibleTable(table) {
      if (!table || typeof table.getBoundingClientRect !== "function") return true;
      const rect = table.getBoundingClientRect();
      return Number(rect.width) > 300 && Number(rect.height) > 40;
    }

    function findTargetTables(profile = getCurrentProfile()) {
      if (!profile || typeof doc.querySelectorAll !== "function") return [];
      if (profile.mode === "note-grid") {
        return Array.from(doc.querySelectorAll(".d-grid.d-table")).filter((grid) => {
          const names = getDirectHeaders(grid).map((header) => header.textContent || "");
          return isVisibleTable(grid) && isTargetHeaderList(names);
        });
      }
      return Array.from(
        doc.querySelectorAll(".d-table__content, .d-grid.d-table")
      ).filter((table) => {
        return isVisibleTable(table)
          && getTableHeaders(table).length >= profile.minimumHeaders;
      });
    }

    function findWorkspaceRoot(table) {
      if (table && typeof table.closest === "function") {
        const root = table.closest("#app-root-content-wrapper");
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
      const markedMenu = candidates.find((candidate) => {
        if (!candidate || typeof candidate.getBoundingClientRect !== "function") return false;
        const rect = candidate.getBoundingClientRect();
        return candidate.getAttribute(MENU_MARKER) === "on"
          && Number(rect.width) > 0
          && Number(rect.height) > 0;
      });
      if (markedMenu) return markedMenu;
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
        rootWidth: Number(rootRect.width) || 0,
        menuWidth: Math.max(
          0,
          (Number(rootRect.left) || 0) - (Number(menuRect.left) || 0)
        ),
        rootMarginLeft: readPixelValue(root, "margin-left", Number(rootRect.left) || 0),
        menuMarginLeft: readPixelValue(menu, "margin-left", Number(menuRect.left) || 0),
      };
      layoutBaselines.set(root, baseline);
      return baseline;
    }

    function calculateCenteredLayout(root, menu, requiredWorkspaceWidth = 0) {
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
      const defaultOuterGap = Math.max(
        WIDE_EDGE_GAP,
        (normalizedMenuLeft + WIDE_EDGE_GAP) / 2
      );
      const maximumWorkspaceWidth = Math.max(
        0,
        viewportWidth - baseline.menuWidth - (WIDE_EDGE_GAP * 2)
      );
      const defaultWorkspaceWidth = Math.max(
        0,
        viewportWidth - baseline.menuWidth - (defaultOuterGap * 2)
      );
      const desiredWorkspaceWidth = Math.min(
        maximumWorkspaceWidth,
        Math.max(defaultWorkspaceWidth, Number(requiredWorkspaceWidth) || 0)
      );
      const outerGap = Math.max(
        WIDE_EDGE_GAP,
        (viewportWidth - baseline.menuWidth - desiredWorkspaceWidth) / 2
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
        requiredWorkspaceWidth: Number(requiredWorkspaceWidth) || 0,
        fitsAllTables: desiredWorkspaceWidth + 1 >= (Number(requiredWorkspaceWidth) || 0),
      };
    }

    function measureRequiredWorkspace(root, tables, profile) {
      if (!root || !tables.length || (profile && profile.mode === "note-grid")) {
        return 0;
      }
      const rootRect = typeof root.getBoundingClientRect === "function"
        ? root.getBoundingClientRect()
        : null;
      const rootWidth = rootRect ? Number(rootRect.width) || 0 : Number(root.clientWidth) || 0;
      return tables.reduce((required, table) => {
        const clientWidth = Number(table.clientWidth)
          || (typeof table.getBoundingClientRect === "function"
            ? Number(table.getBoundingClientRect().width) || 0
            : 0);
        const scrollWidth = Math.max(clientWidth, Number(table.scrollWidth) || 0);
        const surroundingWidth = Math.max(0, rootWidth - clientWidth);
        return Math.max(required, scrollWidth + surroundingWidth);
      }, 0);
    }

    function applyWorkspaceLayout(root, menu, requiredWorkspaceWidth = 0) {
      if (!root || !menu) return null;
      rememberWorkspaceRoot(root);
      rememberWorkspaceMenu(menu);
      const layout = calculateCenteredLayout(root, menu, requiredWorkspaceWidth);
      root.setAttribute(ROOT_MARKER, "on");
      menu.setAttribute(MENU_MARKER, "on");
      updateLayoutStyle(layout);
      menu.style.setProperty("margin-left", `${layout.menuLeftGap}px`, "important");
      root.style.setProperty("margin-left", `${layout.leftGap}px`, "important");
      root.style.setProperty("margin-right", `${layout.rightGap}px`, "important");
      root.style.setProperty("min-width", "0px", "important");
      root.style.setProperty("width", `${layout.workspaceWidth}px`, "important");
      root.style.setProperty("max-width", "none", "important");
      root.style.setProperty("overflow-x", "auto", "important");
      lastLayout = layout;
      return layout;
    }

    function ensureStyle() {
      const existingStyle = doc.getElementById(STYLE_ID);
      if (existingStyle) {
        if (!baseStyleText) baseStyleText = existingStyle.textContent || "";
        return existingStyle;
      }
      const style = doc.createElement("style");
      style.id = STYLE_ID;
      baseStyleText = `
        #app-root-content-wrapper[${ROOT_MARKER}="on"] {
          box-sizing: border-box !important;
          max-width: none !important;
        }
        #app-root-content-wrapper[${ROOT_MARKER}="on"] .page-container,
        #app-root-content-wrapper[${ROOT_MARKER}="on"] .dc-module-block,
        #app-root-content-wrapper[${ROOT_MARKER}="on"] .dc-module-block__content,
        #app-root-content-wrapper[${ROOT_MARKER}="on"] .single-spa-layout-slot-common,
        #app-root-content-wrapper[${ROOT_MARKER}="on"] .sub-app,
        #app-root-content-wrapper[${ROOT_MARKER}="on"] .item-list-page,
        #app-root-content-wrapper[${ROOT_MARKER}="on"] .list-wrapper {
          width: 100% !important;
          max-width: none !important;
          box-sizing: border-box !important;
        }
        #app-root-content-wrapper[${ROOT_MARKER}="on"] .d-table-v2,
        #app-root-content-wrapper[${ROOT_MARKER}="on"] .d-table-wrapper,
        #app-root-content-wrapper[${ROOT_MARKER}="on"] .d-table__content[${TABLE_MARKER}="on"],
        #app-root-content-wrapper[${ROOT_MARKER}="on"] .d-grid.d-table[${TABLE_MARKER}="on"] {
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
          text-align: center !important;
        }
        .d-grid.d-table[${GRID_MARKER}="on"] > .d-td .d-text {
          min-width: 0 !important;
        }
      `;
      style.textContent = baseStyleText;
      (doc.head || doc.documentElement).appendChild(style);
      return style;
    }

    function updateLayoutStyle(layout) {
      const style = ensureStyle();
      if (!style || !layout) return;
      style.textContent = `${baseStyleText}
        .menu-wrapper-container[${MENU_MARKER}="on"],
        #root-menu-wrapper[${MENU_MARKER}="on"] {
          margin-left: ${layout.menuLeftGap}px !important;
        }
        #app-root-content-wrapper[${ROOT_MARKER}="on"] {
          margin-left: ${layout.leftGap}px !important;
          margin-right: ${layout.rightGap}px !important;
          min-width: 0 !important;
          width: ${layout.workspaceWidth}px !important;
          max-width: none !important;
          overflow-x: auto !important;
        }
      `;
    }

    function rememberTable(table) {
      if (trackedTables.has(table)) return;
      const properties = {};
      ["grid-template-columns", "width", "max-width"].forEach((name) => {
        properties[name] = {
          value: table.style.getPropertyValue(name),
          priority: table.style.getPropertyPriority(name),
        };
      });
      trackedTables.set(table, {
        properties,
        gridMarkerExisted: table.hasAttribute(GRID_MARKER),
        gridMarkerValue: table.getAttribute(GRID_MARKER),
        tableMarkerExisted: table.hasAttribute(TABLE_MARKER),
        tableMarkerValue: table.getAttribute(TABLE_MARKER),
      });
    }

    function rememberTableContainer(container) {
      if (!container || trackedTableContainers.has(container)) return;
      const properties = {};
      ["width", "max-width", "box-sizing"].forEach((name) => {
        properties[name] = {
          value: container.style.getPropertyValue(name),
          priority: container.style.getPropertyPriority(name),
        };
      });
      trackedTableContainers.set(container, { properties });
    }

    function expandTableContainers(table, workspaceRoot) {
      for (
        let container = table && table.parentElement;
        container && container !== workspaceRoot;
        container = container.parentElement
      ) {
        rememberTableContainer(container);
        container.style.setProperty("width", "100%", "important");
        container.style.setProperty("max-width", "none", "important");
        container.style.setProperty("box-sizing", "border-box", "important");
      }
    }

    function applyTable(table, profile, workspaceRoot) {
      const headerCount = getTableHeaders(table).length;
      if (headerCount < 5) return false;
      rememberTable(table);
      expandTableContainers(table, workspaceRoot);
      table.setAttribute(TABLE_MARKER, "on");
      table.style.setProperty("width", "100%", "important");
      table.style.setProperty("max-width", "none", "important");
      if (profile && profile.mode === "note-grid") {
        table.setAttribute(GRID_MARKER, "on");
        table.style.setProperty(
          "grid-template-columns",
          buildGridTemplate(headerCount),
          "important"
        );
      }
      return true;
    }

    function applyAll() {
      if (!enabled) return 0;
      const profile = getCurrentProfile();
      if (!profile) {
        restoreAll();
        activeProfileKey = "";
        return 0;
      }
      if (activeProfileKey && activeProfileKey !== profile.key) {
        restoreAll();
      }
      activeProfileKey = profile.key;
      ensureStyle();
      const tables = findTargetTables(profile);
      const workspaceRoot = findWorkspaceRoot(tables[0]);
      const workspaceMenu = findWorkspaceMenu(workspaceRoot);
      applyWorkspaceLayout(
        workspaceRoot,
        workspaceMenu,
        measureRequiredWorkspace(workspaceRoot, tables, profile)
      );
      return tables.reduce(
        (count, table) => count + (applyTable(table, profile, workspaceRoot) ? 1 : 0),
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
      trackedTables.forEach((original, table) => {
        Object.entries(original.properties).forEach(([name, saved]) => {
          if (saved.value) {
            table.style.setProperty(name, saved.value, saved.priority || "");
          } else {
            table.style.removeProperty(name);
          }
        });
        if (original.gridMarkerExisted) {
          table.setAttribute(GRID_MARKER, original.gridMarkerValue || "");
        } else {
          table.removeAttribute(GRID_MARKER);
        }
        if (original.tableMarkerExisted) {
          table.setAttribute(TABLE_MARKER, original.tableMarkerValue || "");
        } else {
          table.removeAttribute(TABLE_MARKER);
        }
      });
      trackedTables.clear();
      trackedTableContainers.forEach((original, container) => {
        Object.entries(original.properties).forEach(([name, saved]) => {
          if (saved.value) {
            container.style.setProperty(name, saved.value, saved.priority || "");
          } else {
            container.style.removeProperty(name);
          }
        });
      });
      trackedTableContainers.clear();
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
      const profile = getCurrentProfile();
      const targets = findTargetTables(profile);
      const headerCounts = targets.map((table) => getTableHeaders(table).length);
      const columnCount = headerCounts.length ? Math.max(...headerCounts) : 0;
      const workspaceRoot = findWorkspaceRoot(targets[0]);
      const workspaceMenu = workspaceRoot ? findWorkspaceMenu(workspaceRoot) : null;
      const workspaceRect = workspaceRoot && typeof workspaceRoot.getBoundingClientRect === "function"
        ? workspaceRoot.getBoundingClientRect()
        : null;
      return {
        ok: true,
        available: Boolean(profile) && Boolean(workspaceRoot) && Boolean(workspaceMenu),
        supported: Boolean(profile),
        pageKey: profile ? profile.key : "",
        pageName: profile ? profile.name : "",
        tableAvailable: targets.length > 0,
        waitingForTable: Boolean(profile) && targets.length === 0,
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
        requiredWorkspaceWidth: lastLayout ? lastLayout.requiredWorkspaceWidth : 0,
        fitsAllTables: lastLayout ? lastLayout.fitsAllTables : false,
      };
    }

    function enable() {
      const profile = getCurrentProfile();
      if (!profile) {
        return {
          ok: false,
          available: false,
          enabled: false,
          supported: false,
          code: "route_not_supported",
          message: "当前页面不在千帆宽表适配清单中。",
        };
      }
      const availableTargets = findTargetTables(profile);
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
      activeProfileKey = profile.key;
      ensureStyle();
      const layout = applyWorkspaceLayout(
        workspaceRoot,
        workspaceMenu,
        measureRequiredWorkspace(workspaceRoot, availableTargets, profile)
      );
      const matchedCount = availableTargets.reduce(
        (count, table) => count + (applyTable(table, profile, workspaceRoot) ? 1 : 0),
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
      activeProfileKey = "";
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
    PAGE_PROFILES,
    ROOT_MARKER,
    MENU_MARKER,
    TABLE_MARKER,
    normalizeText,
    isTargetHeaderList,
    resolvePageProfile,
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

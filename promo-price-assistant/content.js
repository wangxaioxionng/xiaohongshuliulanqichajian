(function startPromoPriceAssistant() {
  "use strict";

  const isTestHarness = document.documentElement.dataset.xhsPromoTestHarness === "true";
  const isSupportedPage = () =>
    location.hostname === "ark.xiaohongshu.com" &&
    location.pathname.startsWith("/app-promotion/single-item-special-price/");

  const core = globalThis.XhsPromoPriceCore;
  if (!core) {
    return;
  }

  let dismissedPath = "";
  let lastPath = location.pathname;

  function mountAssistant() {
    if (
      (!isSupportedPage() && !isTestHarness) ||
      document.getElementById("xhs-promo-price-assistant")
    ) {
      return;
    }

  const state = {
    scannedRows: [],
    plan: null,
    undoValues: new Map(),
    busy: false,
  };

  const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

  function compactText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function extractId(text, label) {
    const match = compactText(text).match(new RegExp(`${label}：([0-9a-zA-Z_-]+)`));
    return match ? match[1] : "";
  }

  function describeRow(row) {
    const text = compactText(row.innerText);
    const cells = Array.from(row.querySelectorAll(":scope > td"));
    const promoInput = row.querySelector('input[placeholder="请输入促销价"]');
    const skuId = extractId(text, "规格ID");
    const productId = extractId(text, "商品ID");
    const isSku = Boolean(skuId);
    const originalPrice = isSku && cells[2] ? compactText(cells[2].innerText) : "";
    const label = cells[1] ? compactText(cells[1].innerText).split("规格ID：")[0].trim() : "未命名规格";
    return {
      skuId,
      productId,
      label,
      originalPrice,
      currentValue: promoInput ? promoInput.value.trim() : "",
      isSku,
      rowElement: row,
      inputElement: promoInput,
    };
  }

  function visiblePromoRows() {
    return Array.from(document.querySelectorAll("tr"))
      .filter((row) => row.querySelector('input[placeholder="请输入促销价"]'))
      .map(describeRow);
  }

  function findScrollContainer() {
    const table = document.querySelector("table");
    let current = table ? table.parentElement : null;
    while (current && current !== document.body) {
      const style = getComputedStyle(current);
      const canScroll = /auto|scroll/.test(style.overflowY || "");
      if (canScroll && current.scrollHeight > current.clientHeight + 20) {
        return current;
      }
      current = current.parentElement;
    }
    return document.scrollingElement || document.documentElement;
  }

  function hasExpandedSkuAfter(rowDescriptor) {
    const nextRow = rowDescriptor.rowElement.nextElementSibling;
    if (!nextRow || !rowDescriptor.productId) {
      return false;
    }
    const nextText = compactText(nextRow.innerText);
    return nextText.includes(`商品ID：${rowDescriptor.productId}`) && nextText.includes("规格ID：");
  }

  function findExpandTarget(rowDescriptor) {
    const row = rowDescriptor.rowElement;
    const selectors = [
      '[aria-expanded="false"]',
      '[aria-label*="展开"]',
      ".d-table__expand-icon",
      ".d-table__expand-btn",
      '[class*="expandIcon"]',
      '[class*="expand-icon"]',
      '[class*="Expand"]',
    ];
    for (const selector of selectors) {
      const target = row.querySelector(selector);
      if (target && !target.matches("input, a")) {
        return target;
      }
    }

    const cells = row.querySelectorAll(":scope > td");
    const infoCell = cells[1];
    if (!infoCell) {
      return null;
    }
    const compactIcon = Array.from(infoCell.querySelectorAll("svg")).find((svg) => {
      const rect = svg.getBoundingClientRect();
      return rect.width > 0 && rect.width <= 24 && rect.height > 0 && rect.height <= 24;
    });
    return compactIcon ? compactIcon.closest("button, [role='button'], span, div") || compactIcon : null;
  }

  async function expandVisibleProductRows(expandedProductIds, expandAttempts) {
    let expanded = 0;
    for (const rowDescriptor of visiblePromoRows()) {
      if (rowDescriptor.isSku || !rowDescriptor.productId || expandedProductIds.has(rowDescriptor.productId)) {
        continue;
      }
      if (hasExpandedSkuAfter(rowDescriptor)) {
        expandedProductIds.add(rowDescriptor.productId);
        continue;
      }
      const attemptCount = expandAttempts.get(rowDescriptor.productId) || 0;
      if (attemptCount >= 2) {
        continue;
      }
      const target = findExpandTarget(rowDescriptor);
      if (target) {
        expandAttempts.set(rowDescriptor.productId, attemptCount + 1);
        target.click();
        await wait(160);
        const didExpand =
          hasExpandedSkuAfter(rowDescriptor) ||
          visiblePromoRows().some(
            (row) => row.isSku && row.productId === rowDescriptor.productId,
          );
        if (didExpand) {
          expandedProductIds.add(rowDescriptor.productId);
          expanded += 1;
        }
      }
    }
    return expanded;
  }

  function setNativeInputValue(input, value) {
    const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
    if (descriptor && descriptor.set) {
      descriptor.set.call(input, value);
    } else {
      input.value = value;
    }
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    input.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  async function walkAllRows(onRows) {
    const container = findScrollContainer();
    const originalTop = container.scrollTop;
    const seenRows = new Map();
    const expandedProductIds = new Set();
    const expandAttempts = new Map();
    let stableBottomPasses = 0;
    let previousSignature = "";

    container.scrollTop = 0;
    await wait(180);

    for (let pass = 0; pass < 180; pass += 1) {
      await expandVisibleProductRows(expandedProductIds, expandAttempts);
      const rows = visiblePromoRows();
      for (const row of rows) {
        if (row.isSku && row.skuId) {
          seenRows.set(row.skuId, { ...row, rowElement: undefined, inputElement: undefined });
        }
      }
      if (typeof onRows === "function") {
        await onRows(rows);
      }

      const atBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 6;
      const signature = `${container.scrollTop}:${container.scrollHeight}:${seenRows.size}`;
      if (atBottom && signature === previousSignature) {
        stableBottomPasses += 1;
      } else {
        stableBottomPasses = 0;
      }
      if (stableBottomPasses >= 2) {
        break;
      }
      previousSignature = signature;
      const step = Math.max(220, Math.floor(container.clientHeight * 0.72));
      container.scrollTop = Math.min(container.scrollTop + step, container.scrollHeight);
      await wait(150);
    }

    container.scrollTop = originalTop;
    await wait(80);
    return Array.from(seenRows.values());
  }

  function createPanel() {
    const panel = document.createElement("section");
    panel.id = "xhs-promo-price-assistant";
    panel.dataset.testid = "promo-assistant-panel";
    panel.innerHTML = `
      <div class="xhs-promo-header">
        <h2 class="xhs-promo-title">小红书促销价助手</h2>
        <button class="xhs-promo-close" type="button" aria-label="关闭促销价助手" data-testid="promo-close">×</button>
      </div>
      <div class="xhs-promo-body">
        <p class="xhs-promo-rule">规则：原价 × 95%，再向下取不超过上限的 9 毛尾数。</p>
        <div class="xhs-promo-stats" data-testid="promo-stats">
          <div class="xhs-promo-stat"><strong data-stat="total">0</strong><span>规格总数</span></div>
          <div class="xhs-promo-stat"><strong data-stat="pending">0</strong><span>待填写</span></div>
          <div class="xhs-promo-stat"><strong data-stat="existing">0</strong><span>已有价格</span></div>
        </div>
        <div class="xhs-promo-status" data-state="idle" data-testid="promo-status">点击“扫描页面”开始，只读取价格，不会提交活动。</div>
        <label class="xhs-promo-overwrite">
          <input type="checkbox" data-testid="promo-overwrite" />
          覆盖已有促销价（高风险，默认关闭）
        </label>
        <div class="xhs-promo-actions">
          <button class="xhs-promo-button" type="button" data-testid="promo-scan">扫描页面</button>
          <button class="xhs-promo-button xhs-promo-button-primary" type="button" data-testid="promo-fill" disabled>填写空白促销价</button>
        </div>
        <div class="xhs-promo-secondary-actions">
          <button class="xhs-promo-link-button" type="button" data-testid="promo-preview" disabled>查看价格预览</button>
          <button class="xhs-promo-link-button" type="button" data-testid="promo-undo" disabled>撤销本次填写</button>
        </div>
        <div class="xhs-promo-preview" data-testid="promo-preview-panel" hidden>
          <strong>本次价格预览</strong>
          <ul class="xhs-promo-preview-list"></ul>
        </div>
      </div>`;
    document.body.appendChild(panel);
    return panel;
  }

  const panel = createPanel();
  const statusElement = panel.querySelector('[data-testid="promo-status"]');
  const scanButton = panel.querySelector('[data-testid="promo-scan"]');
  const fillButton = panel.querySelector('[data-testid="promo-fill"]');
  const previewButton = panel.querySelector('[data-testid="promo-preview"]');
  const undoButton = panel.querySelector('[data-testid="promo-undo"]');
  const overwriteCheckbox = panel.querySelector('[data-testid="promo-overwrite"]');
  const previewPanel = panel.querySelector('[data-testid="promo-preview-panel"]');
  const previewList = panel.querySelector(".xhs-promo-preview-list");

  function setBusy(busy) {
    state.busy = busy;
    const hasBlockingErrors = Boolean(state.plan && state.plan.errors.length > 0);
    scanButton.disabled = busy;
    fillButton.disabled =
      busy || !state.plan || hasBlockingErrors || state.plan.actions.length === 0;
    previewButton.disabled = busy || !state.plan;
    overwriteCheckbox.disabled = busy;
  }

  function setStatus(message, type = "idle") {
    statusElement.textContent = message;
    statusElement.dataset.state = type;
  }

  function renderStats(summary) {
    panel.querySelector('[data-stat="total"]').textContent = String(summary.totalSkuCount);
    panel.querySelector('[data-stat="pending"]').textContent = String(summary.pendingCount);
    panel.querySelector('[data-stat="existing"]').textContent = String(summary.existingCount);
  }

  function renderPreview() {
    previewList.innerHTML = "";
    const actions = state.plan ? state.plan.actions : [];
    for (const action of actions.slice(0, 80)) {
      const item = document.createElement("li");
      item.textContent = `${action.label}：${action.originalPrice} → ${action.promoPrice}`;
      previewList.appendChild(item);
    }
    if (actions.length > 80) {
      const remainder = document.createElement("li");
      remainder.innerHTML = `<strong>其余 ${actions.length - 80} 个规格将在填写时一并处理。</strong>`;
      previewList.appendChild(remainder);
    }
  }

  async function scanPage() {
    if (state.busy) return;
    setBusy(true);
    setStatus("正在展开商品并扫描全部规格，请稍候……");
    try {
      state.scannedRows = await walkAllRows();
      state.plan = core.buildFillPlan(state.scannedRows, {
        overwriteExisting: overwriteCheckbox.checked,
      });
      const summary = core.summarizePlan(state.plan, state.scannedRows.length);
      renderStats(summary);
      renderPreview();
      if (summary.totalSkuCount === 0) {
        setStatus("没有识别到具体规格。请确认已添加商品并展开规格。", "error");
      } else if (summary.errorCount > 0) {
        setStatus(`扫描到 ${summary.errorCount} 个无法识别的价格，已暂停填写。`, "error");
      } else if (summary.pendingCount === 0) {
        setStatus("所有规格都已有促销价，没有需要填写的空白项。", "success");
      } else {
        setStatus(`扫描完成：${summary.pendingCount} 个规格待填写。请先看预览，再执行填写。`, "success");
      }
    } catch (error) {
      state.plan = null;
      setStatus(`扫描失败：${error && error.message ? error.message : "页面结构无法识别"}`, "error");
    } finally {
      setBusy(false);
    }
  }

  async function fillPrices() {
    if (
      state.busy ||
      !state.plan ||
      state.plan.errors.length > 0 ||
      state.plan.actions.length === 0
    ) {
      return;
    }
    if (overwriteCheckbox.checked) {
      const confirmed = window.confirm("将覆盖页面上已有的促销价。确认继续吗？不会自动点击“创建”。");
      if (!confirmed) return;
    }

    setBusy(true);
    setStatus("正在填写并触发千帆校验，请不要切换页面……");
    const actionMap = new Map(state.plan.actions.map((action) => [action.skuId, action]));
    let appliedCount = 0;
    try {
      await walkAllRows(async (rows) => {
        for (const row of rows) {
          const action = actionMap.get(row.skuId);
          if (!action || !row.inputElement) continue;
          if (!state.undoValues.has(row.skuId)) {
            state.undoValues.set(row.skuId, row.inputElement.value);
          }
          if (row.inputElement.value !== action.promoPrice) {
            setNativeInputValue(row.inputElement, action.promoPrice);
            appliedCount += 1;
            await wait(25);
          }
        }
      });

      const verifiedRows = await walkAllRows();
      const validation = core.validateAppliedRows(verifiedRows);
      const pageErrors = Array.from(document.querySelectorAll("tr"))
        .map((row) => compactText(row.innerText))
        .filter((text) => /促销价需在|必填字段/.test(text));
      if (validation.issues.length > 0 || pageErrors.length > 0) {
        const issueCount = validation.issues.length + pageErrors.length;
        setStatus(`已填写 ${appliedCount} 个，但发现 ${issueCount} 个异常；请不要点击创建。`, "error");
      } else {
        setStatus(`填写完成并通过校验：本次写入 ${appliedCount} 个规格。活动尚未创建。`, "success");
      }
      undoButton.disabled = state.undoValues.size === 0;
      state.scannedRows = verifiedRows;
      state.plan = core.buildFillPlan(verifiedRows, {
        overwriteExisting: overwriteCheckbox.checked,
      });
      renderStats(core.summarizePlan(state.plan, verifiedRows.length));
    } catch (error) {
      setStatus(`填写失败：${error && error.message ? error.message : "页面交互异常"}`, "error");
    } finally {
      setBusy(false);
    }
  }

  async function undoFill() {
    if (state.busy || state.undoValues.size === 0) return;
    setBusy(true);
    setStatus("正在撤销本次填写……");
    const restoredSkuIds = new Set();
    try {
      await walkAllRows(async (rows) => {
        for (const row of rows) {
          if (
            !row.inputElement ||
            !state.undoValues.has(row.skuId) ||
            restoredSkuIds.has(row.skuId)
          ) {
            continue;
          }
          setNativeInputValue(row.inputElement, state.undoValues.get(row.skuId));
          restoredSkuIds.add(row.skuId);
          await wait(20);
        }
      });
      state.undoValues.clear();
      undoButton.disabled = true;
      state.scannedRows = await walkAllRows();
      state.plan = core.buildFillPlan(state.scannedRows, {
        overwriteExisting: overwriteCheckbox.checked,
      });
      renderStats(core.summarizePlan(state.plan, state.scannedRows.length));
      renderPreview();
      setStatus(
        `已撤销 ${restoredSkuIds.size} 个规格，页面恢复到本次填写前。`,
        "success",
      );
    } catch (error) {
      setStatus(`撤销失败：${error && error.message ? error.message : "页面交互异常"}`, "error");
    } finally {
      setBusy(false);
    }
  }

  scanButton.addEventListener("click", scanPage);
  fillButton.addEventListener("click", fillPrices);
  undoButton.addEventListener("click", undoFill);
  previewButton.addEventListener("click", () => {
    previewPanel.hidden = !previewPanel.hidden;
  });
  overwriteCheckbox.addEventListener("change", () => {
    state.plan = null;
    fillButton.disabled = true;
    previewButton.disabled = true;
    setStatus("覆盖规则已变化，请重新扫描页面。", "idle");
  });
  panel.querySelector('[data-testid="promo-close"]').addEventListener("click", () => {
    dismissedPath = location.pathname;
    panel.remove();
  });
  }

  function syncAssistantToRoute() {
    if (location.pathname !== lastPath) {
      lastPath = location.pathname;
      dismissedPath = "";
    }
    if (isSupportedPage() || isTestHarness) {
      if (dismissedPath !== location.pathname) {
        mountAssistant();
      }
    } else {
      document.getElementById("xhs-promo-price-assistant")?.remove();
    }
  }

  syncAssistantToRoute();
  if (!isTestHarness) {
    const routeObserver = new MutationObserver(syncAssistantToRoute);
    routeObserver.observe(document.documentElement, { childList: true, subtree: true });
    window.addEventListener("popstate", syncAssistantToRoute);
  }
})();

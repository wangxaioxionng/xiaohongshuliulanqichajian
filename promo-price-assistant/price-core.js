(function attachPromoPriceCore(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.XhsPromoPriceCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createPromoPriceCore() {
  "use strict";

  const DEFAULT_DISCOUNT_PERCENT = 95;
  const DEFAULT_ENDING_CENTS = 90;

  function parseYuanToCents(rawValue) {
    if (typeof rawValue !== "string" && typeof rawValue !== "number") {
      return null;
    }
    const normalized = String(rawValue).trim().replace(/^¥\s*/, "");
    if (!/^\d+(?:\.\d{1,2})?$/.test(normalized)) {
      return null;
    }
    const parts = normalized.split(".");
    const yuan = Number(parts[0]);
    const cents = Number((parts[1] || "").padEnd(2, "0"));
    if (!Number.isSafeInteger(yuan) || !Number.isSafeInteger(cents)) {
      return null;
    }
    return yuan * 100 + cents;
  }

  function formatCents(cents) {
    if (!Number.isSafeInteger(cents) || cents < 0) {
      return null;
    }
    const yuan = Math.floor(cents / 100);
    const remainder = cents % 100;
    if (remainder % 10 === 0) {
      return `${yuan}.${Math.floor(remainder / 10)}`;
    }
    return `${yuan}.${String(remainder).padStart(2, "0")}`;
  }

  function calculatePromoPrice(
    originalPrice,
    discountPercent = DEFAULT_DISCOUNT_PERCENT,
    endingCents = DEFAULT_ENDING_CENTS,
  ) {
    const originalCents = parseYuanToCents(originalPrice);
    if (originalCents === null) {
      return { ok: false, reason: "原价无法识别" };
    }
    if (!Number.isInteger(discountPercent) || discountPercent <= 0 || discountPercent > 100) {
      return { ok: false, reason: "折扣比例无效" };
    }
    if (!Number.isInteger(endingCents) || endingCents < 0 || endingCents > 99) {
      return { ok: false, reason: "尾数规则无效" };
    }

    const upperLimitCents = Math.floor((originalCents * discountPercent) / 100);
    const candidateCents =
      Math.floor((upperLimitCents - endingCents) / 100) * 100 + endingCents;
    if (candidateCents <= 0 || candidateCents > upperLimitCents) {
      return { ok: false, reason: "没有满足规则的正数价格" };
    }

    return {
      ok: true,
      originalCents,
      upperLimitCents,
      promoCents: candidateCents,
      promoPrice: formatCents(candidateCents),
    };
  }

  function hasNineMaoEnding(priceValue) {
    const cents = parseYuanToCents(priceValue);
    return cents !== null && cents % 100 === DEFAULT_ENDING_CENTS;
  }

  function normalizeRowDescriptor(row) {
    return {
      skuId: row && row.skuId ? String(row.skuId) : "",
      productId: row && row.productId ? String(row.productId) : "",
      label: row && row.label ? String(row.label) : "未命名规格",
      originalPrice: row && row.originalPrice != null ? String(row.originalPrice).trim() : "",
      currentValue: row && row.currentValue != null ? String(row.currentValue).trim() : "",
      isSku: Boolean(row && row.isSku),
    };
  }

  function buildFillPlan(rows, options = {}) {
    const overwriteExisting = Boolean(options.overwriteExisting);
    const actions = [];
    const skipped = [];
    const errors = [];
    const seenSkuIds = new Set();

    for (const rawRow of Array.isArray(rows) ? rows : []) {
      const row = normalizeRowDescriptor(rawRow);
      if (!row.isSku || !row.skuId) {
        skipped.push({ row, reason: "商品汇总行或非规格行" });
        continue;
      }
      if (seenSkuIds.has(row.skuId)) {
        skipped.push({ row, reason: "滚动加载重复规格" });
        continue;
      }
      seenSkuIds.add(row.skuId);

      const calculated = calculatePromoPrice(row.originalPrice);
      if (!calculated.ok) {
        errors.push({ row, reason: calculated.reason });
        continue;
      }
      if (row.currentValue && !overwriteExisting) {
        skipped.push({ row, reason: "已有促销价，默认不覆盖" });
        continue;
      }
      actions.push({
        ...row,
        previousValue: row.currentValue,
        promoPrice: calculated.promoPrice,
        upperLimitCents: calculated.upperLimitCents,
      });
    }

    return { actions, skipped, errors };
  }

  function summarizePlan(plan, totalSkuCount) {
    const actions = plan && Array.isArray(plan.actions) ? plan.actions : [];
    const skipped = plan && Array.isArray(plan.skipped) ? plan.skipped : [];
    const errors = plan && Array.isArray(plan.errors) ? plan.errors : [];
    const existingCount = skipped.filter((item) => item.reason === "已有促销价，默认不覆盖").length;
    return {
      totalSkuCount: Number.isInteger(totalSkuCount) ? totalSkuCount : 0,
      pendingCount: actions.length,
      existingCount,
      errorCount: errors.length,
    };
  }

  function validateAppliedRows(rows) {
    const issues = [];
    const checkedSkuIds = new Set();
    for (const rawRow of Array.isArray(rows) ? rows : []) {
      const row = normalizeRowDescriptor(rawRow);
      if (!row.isSku || !row.skuId || checkedSkuIds.has(row.skuId)) {
        continue;
      }
      checkedSkuIds.add(row.skuId);
      const calculated = calculatePromoPrice(row.originalPrice);
      const currentCents = parseYuanToCents(row.currentValue);
      if (!calculated.ok) {
        issues.push({ row, reason: calculated.reason });
      } else if (currentCents === null) {
        issues.push({ row, reason: "促销价仍为空或格式错误" });
      } else if (currentCents > calculated.upperLimitCents) {
        issues.push({ row, reason: "促销价超过95折上限" });
      } else if (!hasNineMaoEnding(row.currentValue)) {
        issues.push({ row, reason: "促销价不是9毛尾数" });
      }
    }
    return { checkedCount: checkedSkuIds.size, issues };
  }

  return {
    DEFAULT_DISCOUNT_PERCENT,
    DEFAULT_ENDING_CENTS,
    parseYuanToCents,
    formatCents,
    calculatePromoPrice,
    hasNineMaoEnding,
    normalizeRowDescriptor,
    buildFillPlan,
    summarizePlan,
    validateAppliedRows,
  };
});

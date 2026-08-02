import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const core = require("../price-core.js");

test("把常见原价格式精确转换为分", () => {
  assert.equal(core.parseYuanToCents("55"), 5500);
  assert.equal(core.parseYuanToCents("59.4"), 5940);
  assert.equal(core.parseYuanToCents("¥ 93.72"), 9372);
  assert.equal(core.parseYuanToCents(71.5), 7150);
});

test("拒绝范围、空值和超过两位小数的价格", () => {
  assert.equal(core.parseYuanToCents("37.18 ~ 93.72"), null);
  assert.equal(core.parseYuanToCents(""), null);
  assert.equal(core.parseYuanToCents(null), null);
  assert.equal(core.parseYuanToCents("9.999"), null);
});

test("把分格式化为页面需要的价格", () => {
  assert.equal(core.formatCents(5590), "55.9");
  assert.equal(core.formatCents(5512), "55.12");
  assert.equal(core.formatCents(-1), null);
  assert.equal(core.formatCents(1.2), null);
});

test("95折后向下取9毛尾数", () => {
  const examples = new Map([
    ["59.4", "55.9"],
    ["71.5", "67.9"],
    ["90.2", "84.9"],
    ["93.72", "88.9"],
    ["55", "51.9"],
    ["63.36", "59.9"],
  ]);
  for (const [original, expected] of examples) {
    const result = core.calculatePromoPrice(original);
    assert.equal(result.ok, true);
    assert.equal(result.promoPrice, expected);
    assert.ok(result.promoCents <= result.upperLimitCents);
  }
});

test("拒绝无效折扣和无效尾数", () => {
  assert.equal(core.calculatePromoPrice("abc").ok, false);
  assert.equal(core.calculatePromoPrice("10", 0).reason, "折扣比例无效");
  assert.equal(core.calculatePromoPrice("10", 101).reason, "折扣比例无效");
  assert.equal(core.calculatePromoPrice("10", 95.5).reason, "折扣比例无效");
  assert.equal(core.calculatePromoPrice("10", 95, -1).reason, "尾数规则无效");
  assert.equal(core.calculatePromoPrice("10", 95, 100).reason, "尾数规则无效");
  assert.equal(core.calculatePromoPrice("0.5").reason, "没有满足规则的正数价格");
});

test("识别9毛尾数", () => {
  assert.equal(core.hasNineMaoEnding("65.9"), true);
  assert.equal(core.hasNineMaoEnding("65.90"), true);
  assert.equal(core.hasNineMaoEnding("65.8"), false);
  assert.equal(core.hasNineMaoEnding("无"), false);
});

test("默认计划只填写空白规格并跳过汇总行和重复行", () => {
  const rows = [
    { productId: "p1", isSku: false, originalPrice: "55 ~ 102.3" },
    { skuId: "s1", productId: "p1", label: "白色 S", isSku: true, originalPrice: "55", currentValue: "" },
    { skuId: "s2", productId: "p1", label: "白色 M", isSku: true, originalPrice: "59.4", currentValue: "55.9" },
    { skuId: "s1", productId: "p1", label: "重复 S", isSku: true, originalPrice: "55", currentValue: "" },
    { skuId: "s3", productId: "p1", label: "异常", isSku: true, originalPrice: "价格未知", currentValue: "" },
  ];
  const plan = core.buildFillPlan(rows);
  assert.deepEqual(plan.actions.map((item) => item.skuId), ["s1"]);
  assert.equal(plan.actions[0].promoPrice, "51.9");
  assert.equal(plan.skipped.length, 3);
  assert.equal(plan.errors.length, 1);
});

test("覆盖模式会把已有价格加入计划", () => {
  const plan = core.buildFillPlan(
    [{ skuId: "s1", isSku: true, originalPrice: "71.5", currentValue: "59.9" }],
    { overwriteExisting: true },
  );
  assert.equal(plan.actions.length, 1);
  assert.equal(plan.actions[0].previousValue, "59.9");
  assert.equal(plan.actions[0].promoPrice, "67.9");
});

test("计划摘要分别统计待填、已有和错误", () => {
  const summary = core.summarizePlan(
    {
      actions: [{ skuId: "s1" }, { skuId: "s2" }],
      skipped: [
        { reason: "已有促销价，默认不覆盖" },
        { reason: "商品汇总行或非规格行" },
      ],
      errors: [{ reason: "原价无法识别" }],
    },
    4,
  );
  assert.deepEqual(summary, {
    totalSkuCount: 4,
    pendingCount: 2,
    existingCount: 1,
    errorCount: 1,
  });
  assert.equal(core.summarizePlan(null).pendingCount, 0);
});

test("验证填写后缺失、超上限和非9毛尾数", () => {
  const result = core.validateAppliedRows([
    { skuId: "ok", isSku: true, originalPrice: "71.5", currentValue: "67.9" },
    { skuId: "blank", isSku: true, originalPrice: "55", currentValue: "" },
    { skuId: "high", isSku: true, originalPrice: "90.2", currentValue: "85.9" },
    { skuId: "ending", isSku: true, originalPrice: "90.2", currentValue: "84.8" },
    { skuId: "invalid", isSku: true, originalPrice: "未知", currentValue: "1.9" },
    { skuId: "ok", isSku: true, originalPrice: "71.5", currentValue: "" },
    { productId: "p1", isSku: false, originalPrice: "55 ~ 90" },
  ]);
  assert.equal(result.checkedCount, 5);
  assert.deepEqual(
    result.issues.map((item) => item.reason),
    ["促销价仍为空或格式错误", "促销价超过95折上限", "促销价不是9毛尾数", "原价无法识别"],
  );
});

test("规范化缺失字段，避免页面异常导致脚本崩溃", () => {
  assert.deepEqual(core.normalizeRowDescriptor(null), {
    skuId: "",
    productId: "",
    label: "未命名规格",
    originalPrice: "",
    currentValue: "",
    isSku: false,
  });
});

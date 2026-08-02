import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const rootDirectory = path.resolve(testDirectory, "..");

test("清单仅覆盖千帆域名，面板只在单品特价页面挂载且不申请多余权限", async () => {
  const manifest = JSON.parse(await readFile(path.join(rootDirectory, "manifest.json"), "utf8"));
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.version, "1.0.0");
  assert.deepEqual(manifest.content_scripts[0].matches, ["https://ark.xiaohongshu.com/*"]);
  assert.equal("permissions" in manifest, false);
  assert.deepEqual(manifest.content_scripts[0].js, ["price-core.js", "content.js"]);
});

test("页面脚本具备所有验收定位标记和安全保护", async () => {
  const source = await readFile(path.join(rootDirectory, "content.js"), "utf8");
  for (const testId of [
    "promo-assistant-panel",
    "promo-status",
    "promo-overwrite",
    "promo-scan",
    "promo-fill",
    "promo-preview",
    "promo-undo",
  ]) {
    assert.match(source, new RegExp(testId));
  }
  assert.match(source, /window\.confirm/);
  assert.match(source, /不会自动点击“创建”/);
  assert.match(source, /MutationObserver\(syncAssistantToRoute\)/);
  assert.match(source, /single-item-special-price/);
  assert.match(source, /hasBlockingErrors/);
  assert.match(source, /state\.plan\.errors\.length > 0/);
  assert.doesNotMatch(source, /querySelector\([^\n]*创建/);
  assert.doesNotMatch(source, /getByText\([^\n]*创建/);
});

test("本地验收页包含加载、空数据和多商品模拟入口", async () => {
  const harness = await readFile(path.join(testDirectory, "qianfan-promo-harness.html"), "utf8");
  assert.match(harness, /data-xhs-promo-test-harness="true"/);
  assert.match(harness, /模拟添加第二件商品/);
  assert.match(harness, /d-table__expand-icon/);
});

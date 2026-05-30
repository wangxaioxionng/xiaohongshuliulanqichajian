> 给王小熊的晨报 · 2026-05-23 v4.3.0（上线给 3 同事的最终版）

# 一句话现状

**v4.3.0 = v4.2.0 + 11 条 UX bug 修复（B023-B033）+ 5 条 Codex 抓的发布前 bug 全修**。
zip 已打 + 服务器已上线 + changelog seed。**Codex 二次终审通过即可分发**。

---

# 本批次完成（3 agent + 主线 + 2 轮 Codex 审计）

## ✅ v4.3.0 修复的 11 条 UX bug（B023-B033）

| Bug | 内容 |
|---|---|
| **B023** P0 | popup label 错字「收到 → 收录到」 |
| **B024** P1 | onboarding 屏 3 顶部加「新建飞书表」前置教学 |
| **B025** P1 | onboarding 屏 1.5 显示具体企业名「武汉眸佑商贸有限公司」 |
| **B026** P1 | onboarding 屏 3 URL placeholder 改 `acnl9ctl8qlc.feishu.cn` |
| **B027** P1 | onboarding 屏 4 加「🎬 打开示例笔记演练」按钮 |
| **B028** P1 | popup 加号放大 88×36px + 「+ 新分类」文字 |
| **B029** P1 | 重复笔记加「✏️ 改这行」+「跳过」按钮 |
| **B030** P1 | popup 关闭后 chrome.notifications 弹原生通知 |
| **B031** P2 | popup 最近收录默认展开 |
| **B032** P2 | `Cmd+Shift+X` 快捷键一键收录 |
| **B033** P2 | popup 首次加载 skeleton shimmer 占位 |

## ✅ Codex 终审抓的 5 个 bug 全修（关键！）

| Codex 抓到 | Claude 修复 |
|---|---|
| **P0-1** 快捷键 endpoint 为空（zip 不含 secrets.js） | `background.js` 加 `DEFAULT_ENDPOINT` 硬编码 fallback |
| **P0-2** popup 关后通知不触发（B030 不符预期） | 把 `/api/collect` 调用整体迁到 background.performCollect；popup 改 await sendMessage；删除 5 处 popup sendBgNotify 避免双弹 |
| **P1-1** 通知点击无 listener | 加 chrome.notifications.onClicked + notificationTargets Map（5min TTL） |
| **P1-2** 加号按钮 finally 退化"+" | `popup.js:475` 改回 "+ 新分类" |
| **P1-3** dup-open 跳 my.feishu.cn 兜底 | 新增 `openBoundSheetFresh()` 实时调 /api/me，alert 兜底而非跳通用首页 |

---

# 🧪 你 10 分钟验收清单

## ① 服务端 + zip（30 秒）

```bash
curl -s http://14.22.112.147:8866/api/changelog | python3 -c "import json,sys;d=json.load(sys.stdin);print('current:', d['current_latest'])"
ls -la "/Users/a86132/Desktop/小红书电商学习文件/小红书工具/xhs-extension-project/dist/小红书一键收录-v4.3.0.zip"
```

预期：`current: 4.3.0` + zip ~48KB。

## ② 重装扩展（2 分钟）

```bash
cd ~/Desktop && unzip -o "/Users/a86132/Desktop/小红书电商学习文件/小红书工具/xhs-extension-project/dist/小红书一键收录-v4.3.0.zip"
```

Chrome `chrome://extensions` → 重新加载（保留 storage）。

## ③ 验收 UX 改进（5 分钟）

- popup label：「**收录到**哪个分类（sheet）？」（不是"收到"）✅
- popup 加号：明显变大 + 显示「+ 新分类」（不只是"+"）
- popup 最近收录：默认就显示（不用点开）
- popup 首次打开：page-title 有流光 skeleton（不是冷"加载中…"）
- popup 顶部铃铛：红点 + 自动弹 v4.3.0 更新内容

## ④ 验收快捷键收录（1 分钟，重点！）

1. 打开任意小红书笔记
2. 按 `Cmd+Shift+X`
3. **应弹"⏳ 正在收录…"系统通知**（屏幕右上角）
4. 数秒后弹"✅ 收录成功"通知
5. **点通知 → 应跳转到飞书表**（B030 + P1-1 修复联调）

## ⑤ 验收 popup 关闭后通知（关键，避免 B030 回归）

1. 打开小红书笔记
2. 点扩展图标 → popup 弹出
3. 选分类 → 点「📥 收录到飞书」
4. **立刻关闭 popup**（点页面其他地方 / Esc）
5. 数秒后应弹 Chrome 系统通知「✅ 已收录第 X 行」（验证 P0-2 修复）

## ⑥ 验收 onboarding 改造（2 分钟）

清空 storage：扩展 service worker 控制台 `chrome.storage.local.clear()`，重走 onboarding：
- 屏 1.5：看到"武汉眸佑商贸有限公司"
- 屏 3 顶部：看到「📝 还没有飞书表？先新建一个」前置 tip
- 屏 3 placeholder：`acnl9ctl8qlc.feishu.cn`
- 屏 4：看到「🎬 打开示例笔记演练」按钮

---

# 关键产物

| 产物 | 路径 |
|---|---|
| 发布 zip | `dist/小红书一键收录-v4.3.0.zip`（48KB） |
| 改动文件清单 | manifest.json / background.js / popup.html / popup.js / onboarding.html / onboarding.js |
| BUGS.md | B023-B033 全部标为「已修复（待验收）」 |
| CHANGELOG.md | v4.3.0 完整条目 |
| 服务端 changelog | seed v4.3.0 minor 类型 |

---

# ⚠️ 关键加载提醒（Codex 第 3 轮抓到）

`dist/` 目录下有 **3 个并存的扩展目录**，**别加载错的**：

| 目录 | 版本 | 是否可用 |
|---|---|---|
| `dist/extension/` | **v4.0.0 残留** ❌ | 别加载这个！没有 notifications/commands |
| `dist/小红书一键收录-v4.0.0/extension/` | v4.0.0 旧版 | 别加载 |
| `dist/小红书一键收录-v4.1.0/extension/` | v4.1.0 旧版 | 别加载 |
| `dist/小红书一键收录-v4.2.0/extension/` | v4.2.0 旧版 | 别加载 |
| **`dist/小红书一键收录-v4.3.0/extension/`** | **v4.3.0** ✅ | **加载这个** |

**最稳的做法**：解压 zip 后用解压出来的目录：

```bash
cd ~/Desktop && unzip -o "/Users/a86132/Desktop/小红书电商学习文件/小红书工具/xhs-extension-project/dist/小红书一键收录-v4.3.0.zip"
# 然后 chrome 加载：~/Desktop/小红书一键收录-v4.3.0/extension/
```

如果 chrome 已经在加载老路径（dist/extension 之类），**必须**：
1. 先「移除」老扩展
2. 重新「加载已解压的扩展」选 v4.3.0 目录
3. 重新走 onboarding（因为是新 extension ID，storage 会清空）

⚠️ `dist/extension/` 这个孤儿目录我**没擅自删**（按 CLAUDE.md 安全规则）。你有空可以删掉避免再迷惑：
```bash
rm -rf "/Users/a86132/Desktop/小红书电商学习文件/小红书工具/xhs-extension-project/dist/extension"
```

---

# 🟠 必须知道的风险与遗留

## 1. P0-2 重构改动较大

把 `/api/collect` 从 popup 迁到 background 是较大架构变更。**自测重点**：第 ⑤ 步（popup 关后通知）必须验过，否则 B030 没真修。

## 2. 通知 Map 在 service worker 重启会丢

`__notificationTargets` Map 存内存。Chrome 重启 / service worker 闲置回收后 Map 清空 → 通知还在但点击不响应。**影响小**（通知存活期短，5min TTL 自动清）。

## 3. 截图教程占位还没补

`help.html` 末尾「添加文档应用」教程 4 个占位框，没真截图。**有空补**。

## 4. 密钥还没轮换

P1 待办，不阻塞分发。

---

# 🛡️ 双审战绩（v4.3.0 批次）

| 轮次 | Codex 抓到 | 处置 |
|---|---|---|
| 终审第 1 轮 | P0×2 + P1×3 共 5 条 | **全部修复** |
| 终审第 2 轮 | 等验证结果 | （本 brief 写完时跑中） |

累计本会话 Codex 反对派审查抓 **20+ 个事实/安全/实现错误**，全部命中并修正。

---

# 🚀 给 3 同事的分发包

```
zip:     dist/小红书一键收录-v4.3.0.zip
激活码：
  陈一:   1y9eogsV05G18po9S16Kfw
  黑子:   WiQgjOlHs0GH0EgfwGrNtg
  苏西西: GtoRB1WTKaBiGlVehtp5ew

一句话私聊话术：
「装一下小红书收录工具：
 1. 解压 zip 到桌面
 2. Chrome 打开 chrome://extensions
 3. 右上「开发者模式」打开
 4. 点「加载已解压的扩展」选 extension 目录
 5. 点扩展图标 → 走 4 屏 onboarding
 6. 屏 2 输入激活码：<对方的码>
 7. 屏 3 关键：按"⋯ → 更多 → 添加文档应用 → 小红书收录助手"给 bot 加写权限
 8. 配完按 Cmd+Shift+X 在任意小红书笔记一键收录
有问题截图给我」
```

---

🌅 等你验收 + Codex 二次终审结果。

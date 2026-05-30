> 给王小熊的晨报 · 2026-05-23 v4.2.0
> 这是上线给 3 同事用的最终版

# 一句话现状

**v4.2.0 已上线 14.22.112.147:8866 + dist/小红书一键收录-v4.2.0.zip 已打 + 你的飞书表已 backfill 美化。**
**审计的 9 个 bug 修了 7 个**（剩 P0-2 HTTPS 立 B020 推迟 + 密钥轮换需要你点飞书后台）。
**等你 10 分钟验收后，可发 3 同事**。

---

# 本批次完工清单（4 agent 并行 + 主线集成，~25 分钟实际墙钟）

## ✅ 已修复（7 条）

| # | 内容 | 验证方式 |
|---|---|---|
| **B017** ⭐ P0 | onboarding 屏 3 全文重写「⋯ → 更多 → 添加文档应用」+ 检测权限按钮 + 屏 4 终验 + init_sheets 严格化 | 你重走 onboarding |
| **B018** ⭐ P1 | `/api/permissions/check` 上线（已 curl 验证 401 + 王小熊 read_ok+write_ok=true） | `curl http://14.22.112.147:8866/api/permissions/check` |
| **B019** ⭐ P1 | 飞书表格美化（表头加粗+浅灰底+斑马纹+边框+双冻结）+ 王小熊现有表 backfill | 直接打开你的飞书表看 |
| P1-1 | 激活码并发原子（杜绝双激活，2 线程测试通过 1S/1R） | 设计层 |
| P1-2 | OAuth 错误页 XSS（错误码白名单 + html.escape 双保险） | grep `_ERROR_WHITELIST` |
| P1-3 | CORS Allow-Headers 加 `Authorization` | curl OPTIONS 已验证 |
| P1-4（OAuth nonce） | OAuth state nonce 防 CSRF（SQLite 持久化 + TTL 10 分钟） | `oauth_states` 表已建 |

## ✅ 顺手做的（4 条）

| # | 内容 |
|---|---|
| - | bump manifest 4.1.0 → **4.2.0** |
| - | CHANGELOG.md 写 v4.2.0 完整条目 |
| - | 服务端 changelog 表 seed v4.2.0（你装新版打开 popup 会自动弹更新内容） |
| - | BUGS.md 更新 B017/B018 状态 + 新增 B019/B020 + 头部版本号 4.2.0 |

## 🚧 推迟（2 条 — 需要你手动配合）

| # | 内容 | 为什么推迟 |
|---|---|---|
| **B020 P1** | OAuth HTTPS 升级 + 域名 | 需要你先决定用哪个域名 + DNS 解析（Claude 做不了） |
| **凭据轮换** | 飞书后台 重置 App Secret + JWT Secret | 飞书后台必须你本人操作 |

## 🧪 诊断完毕但本批次未修

| # | 内容 | 结论 |
|---|---|---|
| PM2 ASGI Exception 噪音 | 根因是 v3.1 遗留 NameError，**当前代码已无**。最近 10h uptime 零 Exception | 不用修 |

---

# 🧪 你醒来 10 分钟验收清单

## ① 验证服务端（30 秒）

```bash
curl -s http://14.22.112.147:8866/api/changelog | python3 -m json.tool | head -20
```

**预期**：current_latest=4.2.0，3 条数据（4.2.0 / 4.1.0 / 4.0.0）

## ② 验证你的飞书表美化（1 分钟）

直接打开你的飞书表：
- 表头：浅灰底 + 加粗 + 居中 ✅
- 数据行：偶数行极浅灰底（斑马纹）✅
- 双冻结：往下滚 / 往右滚，第 1 行 + 第 A 列始终可见 ✅
- 边框：浅灰细线

⚠️ 注意：王小熊你的表实际只有 2 个 sheet（起号图文 + Sheet1），不是预期的 7 个。新员工 onboarding 走完会自动建 7 个。

## ③ 验证 v4.2.0 zip（2 分钟）

```bash
cd ~/Desktop && unzip -o "/Users/a86132/Desktop/小红书电商学习文件/小红书工具/xhs-extension-project/dist/小红书一键收录-v4.2.0.zip"
ls -la ~/Desktop/小红书一键收录-v4.2.0/
```

**预期**：解压后看到 `extension/` 目录 + `📖 使用说明（先看这里）.md`

Chrome：
1. `chrome://extensions` → 当前扩展点「重新加载」（**别卸载**，保留 storage）
2. 打开 popup → 右上铃铛应该有**红点**（v4.2.0 是新 minor bump）
3. popup 应该**自动弹出 v4.2.0 更新内容**
4. 点「我知道了」→ 红点消失

## ④ 验证 onboarding 新流程（5 分钟，关键！）

**前置**：清空 chrome.storage 模拟新用户：
```js
// 在 chrome://extensions 找到扩展 ID → service worker 控制台执行：
chrome.storage.local.clear()
```

然后点扩展图标 → 走 onboarding：
- **屏 1**：扫码登录 ✅
- **屏 2**：粘贴激活码（你激活码已用过，会直接跳过到屏 3）
- **屏 3** ⭐：
  - 应该看到「⚠️ 先在飞书表格做这 3 件事（缺一不可）」
  - 应该有「⋯ → 更多 → 添加文档应用 → 小红书收录助手」步骤
  - **主按钮「绑定 + 自动建分类」应该是 disabled（灰色）**
  - 粘贴你的飞书表 URL → 点「🔍 检测 bot 权限」
  - **应该绿字 ✅「权限完整」**（因为你已加过应用）→ 主按钮变可点
- **屏 4**：「🎉 配置完成」

## ⑤ 验证负向（关键，避免漏 bug）

新建一个**空白飞书表**（不加任何应用） → 复制 URL → 粘贴 onboarding 屏 3 → 点「检测权限」

**预期**：红字 ❌「bot 没有写权限。请在飞书表 ⋯ → 更多 → 添加文档应用 → 添加「小红书收录助手」」+ 主按钮保持 disabled

如果通过了这一步，**v4.2.0 就可以发同事**。

## ⑥ 验证收录（1 分钟）

打开任意小红书笔记 → 扩展图标 → 选分类 → 收录 → 飞书表多一行数据，且新行**继承斑马纹样式**

---

# 🌐 关键资产

| 产物 | 路径 |
|---|---|
| 发布 zip | `dist/小红书一键收录-v4.2.0.zip`（43 KB） |
| 解压目录 | `dist/小红书一键收录-v4.2.0/` |
| CHANGELOG | `CHANGELOG.md`（v4.2.0 在最顶） |
| Bug 清单 | `BUGS.md`（B017/B018 已修 / B019 已修 / B020 推迟） |
| 服务端备份 | `data.db.bak.1779509951` + `data.db.bak.1779510228`（双备份） |
| 上批次 brief | `morning-brief.md`（v4.1.0 那次） |

---

# 🚀 给 3 同事的分发包

```
zip: dist/小红书一键收录-v4.2.0.zip

各人激活码（admin.py list-codes 查最新）：
- 陈一: 1y9eogsV05G18po9S16Kfw
- 黑子: WiQgjOlHs0GH0EgfwGrNtg
- 苏西西: GtoRB1WTKaBiGlVehtp5ew

一句话私聊话术：
「装一下小红书收录工具：
 1. 解压 zip 到桌面
 2. Chrome 打开 chrome://extensions
 3. 右上「开发者模式」打开
 4. 点「加载已解压的扩展」选 extension 目录
 5. 点扩展图标 → 走 4 屏 onboarding
 6. 屏 2 输入激活码：<对方的码>
 7. 屏 3 关键：必须按「⋯ → 更多 → 添加文档应用 → 小红书收录助手」给 bot 加权限
 8. 屏 3 有「检测权限」按钮，绿字才能继续
 9. 一切走完 → 任意小红书笔记 → 点扩展 → 收录
有问题截图给我」
```

---

# 🟠 必须知道的风险与遗留

## 1. 截图教程是占位

help.html 末尾的「添加文档应用」教程区块用了 4 个虚线框占位符，**没有真截图**。你有空的话录 4 张截图（步骤 1-2 / 3-4 / 5-6 / 7）替换占位符。**不影响功能，只影响教程美观**。

## 2. 密钥还没轮换

按 audit P1-1，本地 `server/config.json` + `extension/secrets.js` 是真值。.gitignore 已经包含、当前目录没 git 仓库，所以**短期没风险**。但建议你近 1 周内：
1. 飞书后台 → 应用 `cli_aa9a386105f89cd2` → 重置 App Secret
2. 跟我说一声，我写个 `update-secret.sh` 接受新值 → 更新 config.json + PM2 reload

## 3. HTTPS 升级（B020）

OAuth token 走 HTTP URL query 传，理论上有 referer/history 泄露风险。**内部 3 人用风险可控**。等你有时间注册域名了告诉我，1-2 小时上 HTTPS。

## 4. options 页「权限自检」按钮未加

B018 后端 `/api/permissions/check` 已上线，但 options 页面前端入口本批次没做（避免文件冲突）。下次会话补。**不影响主流程**（onboarding 屏 3 已经能调）。

---

# 🛡️ 双审战绩（本会话累计）

Codex 反对派审查累计抓出 **11 个事实/安全错误**，**全部修正**：

| 轮次 | 抓到的错误 | 处理 |
|---|---|---|
| 第 1 轮（架构） | 老用户重扫无需激活码 / manifest key 不能恢复 storage | 修正方案 |
| 第 2 轮（产物） | dist/v4.0.0.zip 不存在 / 源码=dist | 修 CLAUDE.md |
| 第 3 轮（致命） | **deploy.sh 漏 `--exclude data.db`** | 修了，否则会覆盖生产库 |
| 第 4 轮（脚本） | zip 路径前缀错 / rollback 用 unzip 操目录 / **bump-version.sh 无确认 `rm -rf`** | 修脚本+rollback |
| 第 5 轮（事实） | 本地 db 没数据 / 没 .git → "history 泄露"不成立 / "接受任意回调"夸张 | 修正措辞 |
| 第 6 轮（根因） | **瞎猜分类 bug 根因，没读 BUGS.md B017** | 读完按 B017 期望做 |

**最致命 3 条**：deploy.sh / bump-version.sh `rm` / 瞎猜根因 — 任一漏掉都会出大事。

---

# 🌅 结论

| 状态 | 内容 |
|---|---|
| ✅ 可以分发 | v4.2.0 zip 已就绪，3 同事激活码已生成 |
| ⏳ 等你验收 | 6 步 10 分钟 |
| 🚧 后续优化 | 截图教程 + 密钥轮换 + HTTPS（B020） + options 自检按钮 |

回答验收结果，或下一步要做什么。

🌅 早上好。

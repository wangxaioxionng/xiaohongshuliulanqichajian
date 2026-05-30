# v3.1 双审审查检查表

> 这一轮新做了 10 个 task（T1-T10），全面审查。

---

## 一、本轮新做的所有功能（待审清单）

### 后端代码改动
- `app.py` 重写（多租户 + 10 个 endpoints）
- `lark_writer.py` 重构（实例不再绑死单一 spreadsheet_token；增加 create_sheet / delete_sheet / load_failures / retry_failure / load_dashboard）
- `admin.py` 新增（CLI 管理 5 个子命令）
- `config.json` 结构改为 `users` dict
- `collector.py` 未改

### 后端 API（11 个）
| 接口 | 是否新增 | 是否改动 |
|---|---|---|
| GET /api/health | 否 | 加了 users_count |
| GET /api/whoami | ✅ 新增 | — |
| GET /api/sheets | ✅ 新增 | — |
| POST /api/categories | ✅ 新增 | — |
| DELETE /api/categories/{sheet_id} | ✅ 新增 | — |
| GET /api/check | 否 | 改：跨 sheet 查找 + 返回 sheet_title |
| POST /api/collect | 否 | 改：加 sheet_id 和 dup_strategy |
| POST /api/collect-batch | 否 | 改：同 collect |
| GET /api/dashboard | ✅ 新增 | — |
| GET /api/failures | ✅ 新增 | — |
| POST /api/retry | ✅ 新增 | — |

### 扩展前端改动
- `manifest.json`：版本 → 2.2.0
- `popup.html`：加仪表盘 / 加分类下拉 / 加失败列表 / 加历史折叠
- `popup.js`：完全重写（分类、仪表盘、失败、重试、备注、重复策略）
- `options.html`：加重复策略下拉
- `options.js`：保存重复策略到 chrome.storage.sync
- `background.js`：未改
- `secrets.js`：内置 token

---

## 二、Claude 自审发现的潜在问题（按风险分级）

### 🔴 P0 必须立刻修

| # | 问题 | 影响 |
|---|---|---|
| P0-1 | **dashboard 4 秒响应**（遍历 8 sheet 各读 A1:N1000） | 每次打开 popup 卡 4 秒，体验严重恶化 |
| P0-2 | **retry 失败行不会被清除**：调 retry 时若发现笔记已在别处存在，返回 duplicate 但原失败行不动 | 用户重试后失败列表不变，反复看到同一行 |
| P0-3 | **find_row_across_sheets 没缓存** | /api/check 每次扫 8 sheet，扩展图标徽标响应慢 |

### 🟠 P1 重要

| # | 问题 | 影响 |
|---|---|---|
| P1-1 | dashboard cache 用 chrome.storage.local，每次开 popup 至少有 IPC 开销 | 体验略卡 |
| P1-2 | 删除分类后 chrome.storage 的 lastCategorySheetId 可能指向已删 sheet | 下次打开默认选不到 |
| P1-3 | dup_strategy=update 只更新 G-L 列，不更新标题/文案/封面 | 设计选择，但用户可能误以为全更新 |
| P1-4 | popup 顶部「已连接」太抽象，应显示用户名 | 多用户切换时分不清当前是谁 |
| P1-5 | 新建分类没检查飞书 200 sheet 上限 | 极端场景报错不友好 |
| P1-6 | 失败重试 UI 重试成功后失败列表 visual stale | 用户需重开 popup 才看到失败数减少 |

### 🟡 P2 优化

| # | 问题 |
|---|---|
| P2-1 | load_dashboard 读 A1:N1000（全列），可只读需要列 |
| P2-2 | retry 没 backoff（连续重试同一条立刻又会失败） |
| P2-3 | manifest version 跳跃，缺 changelog |
| P2-4 | dashboard 第 4 个 stat-failed 显示时宽度跳变 |

---

## 三、运行时验证清单（我手动跑）

### 数据一致性（真账号 e2e）
- [ ] 当前飞书表 8 sheet 是否完整
- [ ] 飞书表第 3 行耳钉笔记数据完整且封面图嵌入
- [ ] /api/dashboard 返回的 total 与飞书表实际记录数对得上
- [ ] /api/check 跨 sheet 找到该笔记

### 鉴权
- [ ] 无 token → 401
- [ ] 旧 token（已轮换的）→ 401
- [ ] 正确 token → 200

### 边界
- [ ] 新建重名分类 → 409
- [ ] 删除 default_sheet_id → 400
- [ ] 删除不存在的 sheet_id → 500/200
- [ ] 收录非小红书 URL → 失败处理

### 性能
- [ ] /api/dashboard 实测耗时
- [ ] /api/check 实测耗时（含跨 sheet 扫描）
- [ ] /api/collect 完整流程耗时

### 不影响现有业务
- [ ] bookboy / gold-rush / workbench 仍 online
- [ ] 主 nginx 站点未受影响
- [ ] 磁盘 / 内存 余量正常

---

## 四、待 Codex 独立审计补充

下方留给 Codex 输出。

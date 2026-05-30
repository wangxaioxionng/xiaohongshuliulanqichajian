# 小红书一键收录扩展 · 项目宪法

> 📜 **本文件 = 项目宪法，只装稳态规范**。
> 进度 / TODO / Bug / 版本号细节 / 工时 / 批次说明请看：
> - 会话交接：`.claude/handoff/`
> - Bug 清单：`BUGS.md`
> - 更新日志：`CHANGELOG.md`
>
> 项目根目录：`/Users/a86132/Desktop/小红书电商学习文件/小红书工具/xhs-extension-project/`

---

## 基础设施

### 服务端

| 项 | 值 |
|---|---|
| 服务器 IP | `14.22.112.147`（Ubuntu 22.04） |
| 后端对外 API | `http://14.22.112.147:8866` |
| 内部 uvicorn | `127.0.0.1:8765`（nginx 反代） |
| PM2 进程 | `xhs-collect-api`（与 `bookboy` / `gold-rush` / `xiaoxiong-workbench` 并存） |
| 部署目录 | `/opt/xhs-collect/` |
| 配置文件 | `/opt/xhs-collect/config.json`（chmod 600） |
| 数据库 | `/opt/xhs-collect/data.db`（SQLite 单文件） |
| nginx 配置 | `/etc/nginx/sites-enabled/xhs-collect` |

### 飞书

| 项 | 值 |
|---|---|
| 主企业 | 王小熊新建的飞书企业（v4 OAuth 体系） |
| Bot 应用名 | **小红书收录助手** |
| Bot App ID | `cli_aa9a386105f89cd2` |
| Bot App Secret | 见服务器 `/opt/xhs-collect/config.json`（**禁止发对话**） |
| 旧 Bot（兼容） | `cli_a90ee8a787225bd8`（"刘亦菲"，留给 admin 王小熊一人继续用旧个人版账号） |

### 激活码体系

- 表：SQLite `activation_codes`，按 `code` 主键
- 一次性：用过即废，`used_by_open_id` 落地后不可复用
- 真实值查询：`python3 admin.py list-codes`（服务器 `/opt/xhs-collect/`）
- 当前已发激活码备注：王小熊自测 / 陈一 / 黑子 / 苏西西（实时状态走 admin.py 查）

---

## 架构核心

### 鉴权双轨制

| 路径 | 用途 | 例子 |
|---|---|---|
| `X-Auth-Token` | Legacy 老用户（v3.1）+ admin bootstrap | 王小熊保留 admin 身份发激活码 |
| `Authorization: Bearer <JWT>` | v4 OAuth 用户 | 扫码登录后的所有员工 |

### 用户状态机（SQLite `users.status`）

```
pending（扫码后） → active（填激活码后）
```

- `pending`：只能调 `/auth/activate` 和 `/api/me`
- `active`：能调业务 endpoint，但仍需 `spreadsheet_token` 已绑才能写飞书表

### v4 OAuth 自动化流程

```
扩展点登录 → 飞书扫码 → /auth/callback 签 JWT →
redirect /auth/done?token=xxx →
background.js 严格校验（protocol+hostname+port+pathname+JWT格式+state nonce） →
chrome.storage.local.set({jwt}) → 关闭 callback tab → 切到 onboarding → routeByState
```

- state nonce：SQLite `oauth_states` 表持久化，TTL 10 分钟，单消费
- 15 秒兜底：onboarding 显示手动粘贴框（防 background 监听失败）

### 数据持久化（SQLite `data.db` 表）

| 表 | 用途 |
|---|---|
| `users` | 飞书登录用户 + 绑定的飞书表 + role |
| `activation_codes` | admin 发的一次性激活码 |
| `oauth_states` | OAuth state nonce（防 CSRF，TTL 10min） |
| `changelogs` | 服务端版本更新日志（v4.1.0 起） |
| `collect_logs` | 收录历史记录 |
| `user_prefs` | 跨设备同步偏好（**架构已建，待启用**） |

### 飞书表权限模型（v4.2.0 起严格化）

- **仅"协作者-可编辑"权限不够**
- 必须在表格 `⋯ → 更多 → 添加文档应用 → 添加「小红书收录助手」` 才有写权限
- onboarding 屏 3 强制走「检测 bot 权限」预检按钮，写权限不通过禁止绑表

---

## 已锁定决策（不可推翻）

### 产品决策

1. **不存所有图，只存封面**
2. **不做 AI 自动分类**，用户手动选分类
3. **同租户限制**：所有员工都在王小熊新建的飞书企业里（不再"个人版"）
4. **default sheet 是「起号」**（不是空 Sheet1）
5. **每个员工独立飞书表**（多租户设计）

### 技术决策

1. **JWT 30 天 TTL**，过期后用户重扫码（自动续签 JWT，无需重新激活/绑表）
2. **激活码一次性**，用了就废；并发安全靠单条原子 UPDATE
3. **SQLite 单文件 `data.db`**（10 人规模够用，不引 Postgres）
4. **legacy X-Auth-Token 路径保留**（admin bootstrap + 兼容老配置）
5. **bot 名称硬编码「小红书收录助手」** 在多处代码里，未来改名需全局替换
6. **绑表流程 fail-fast**：建分类失败必须返回 502，**不能 try/except 吞错**；失败时不写 `spreadsheet_token`，让用户可重试
7. **changelog 走服务端 SQLite + `GET /api/changelog`**，不在扩展包内嵌（让以后改 changelog 不用重发扩展）
8. **自动弹窗只在 minor/major bump 触发**，patch 静默更新（避免烦扰）

---

## 安全规则（不可违反）

1. **App Secret / JWT Secret / Auth Token 绝不发对话**（轮换走 `update-secret.sh` 脚本，本地写入 → PM2 reload）
2. **`config.json` chmod 600**（服务器 + 本地）
3. **扩展打包前必须 grep 真凭据**（dist 安全扫描）
4. **每人 token 独立**，怀疑泄露用 `admin.py rotate` 或 `revoke-code`
5. **数据库 schema 变更只能增量**（`CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN`），按全局 CLAUDE.md 数据库安全规则
6. **`server/deploy.sh` 必须含 `--exclude data.db` 等**，禁止把本地 dev db 覆盖生产
7. **`bump-version.sh` 不会自动 `rm` 旧产物**，需要 `--force` 才移到 `dist/.trash/<ts>/`（不真删）
8. **部署只 restart 目标 PM2 进程**，禁止 `pm2 restart all`（影响 bookboy / gold-rush / xiaoxiong-workbench）

---

## 工程流程

### 插件交付验收红线

1. **新增或改动采集链路时，必须跑完整端到端流程后才能说完成**：从 Atlas/Chrome 插件点击开始，到后端收到任务、第三方 API 返回、飞书表创建或写入完成，最终用真实结果验收。只跑静态检查、只看代码、只打包插件，都不能算交付完成。
2. **所有长流程采集必须有用户可见进度和失败原因**：至少显示当前步骤、已收集链接/账号数量、是否已提交后端、API 已处理/成功/失败数量、是否正在创建飞书表、是否正在写入飞书、最终飞书链接或具体失败点。失败时不能只报“失败”，必须说明卡在哪一步、已完成多少、能否重试。

### 多 sub-agent 并行规范

- **主线负责集成**：sub-agent 不互相协调，由主线打包 + 部署 + 自测
- **明确文件边界**：每个 agent 只改自己的文件域
- **共改同一文件**：用「拉远端 `cat` + 本地 diff + scp」流程，禁止盲覆盖
- 本项目历史验证 ROI 3-4× 串行速度

### 审计前必读 `BUGS.md`

任何代码审计 / bug 排查 / 上线前 audit 任务，**必须先全文读 `BUGS.md`**，把"已知 bug 清单"作为审计基线。避免重复诊断 + 避免跟用户已验证的事实相反。

### CHANGELOG 维护

- CHANGELOG 由 `bump-version.sh` 交互式输入，**不走 git commit message 自动生成**
- 服务端 changelog 通过 `POST /api/admin/changelog` 同步到 SQLite `changelogs` 表

### 部署流程

1. ssh 备份生产 db：`cp /opt/xhs-collect/data.db data.db.bak.$(date +%s)`
2. 精确 scp 改动文件（默认不跑 `deploy.sh` 全量同步）
3. 如有 schema 变更：`ssh ... "python -c 'import db; db.init_schema()'"`
4. `pm2 restart xhs-collect-api`（按安全规则只重启目标进程）
5. `curl /api/health` 健康检查

---

## Codex 反对派审查机制

每次 Claude 完成动作时会触发 `~/.claude/hooks/codex-review.sh` 自动审查。本项目历史上 Codex 多次抓住 P0 安全漏洞（deploy.sh 漏 `--exclude data.db` / `rm -rf` 无确认 / OAuth 鉴权漏洞 / 瞎猜 bug 根因等），**ROI 极高**。所有 Claude 输出在发布前必须经过 Codex 审查。

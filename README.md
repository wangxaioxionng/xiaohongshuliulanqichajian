# 小红书一键收录 — 浏览器扩展项目

把小红书笔记一键收录到飞书表《小红书文案收集》。

## 当前状态

- 当前开发版本：v4.9.1
- 千帆「笔记数据-商品笔记」改为宽屏分析模式：先利用浏览器右侧空白扩展工作区，再以可读列宽显示当前 14 列
- 插件弹窗固定为 360px 紧凑宽度，不会被千帆宽屏功能撑大
- 本功能只调整当前浏览器标签页的展示，不调用采集接口、不修改店铺数据、不写飞书
- 后端部署方式与接口均未变化

## 项目结构

```
xhs-extension-project/
├── server/                    # 后端 API（部署在 14.22.112.147）
│   ├── app.py                 # FastAPI 入口
│   ├── collector.py           # 采集核心（复用本地 skill）
│   ├── lark_writer.py         # 飞书写入器（bot 身份）
│   ├── config.json.example    # 配置模板（不含密钥）
│   ├── config.json            # 真实配置（⚠️ 含 app_secret 和 auth_token，本地 + 服务器各一份，不提交 git）
│   ├── ecosystem.config.js    # PM2 进程配置
│   ├── nginx-xhs-collect.conf # nginx 站点配置
│   └── deploy.sh              # 一键部署脚本
└── extension/                 # Chrome 扩展（Manifest V3）
    ├── manifest.json
    ├── popup.html / popup.js     # 弹窗（备注+标签）
    ├── options.html / options.js # 设置页（API endpoint + token）
    ├── help.html                 # 帮助文档
    ├── background.js             # service worker（右键菜单、徽标）
    ├── qianfan_full_table.js     # 千帆商品笔记宽屏分析与官方布局恢复
    └── icons/                    # 4 个尺寸的扩展图标
```

## 部署流程

### 一、服务端

**1. 飞书 bot 身份准备**（你需要在飞书开发者后台做）：

- 应用：`cli_a90ee8a787225bd8`
- 开通 scope：
  - `sheets:spreadsheet:read`
  - `sheets:spreadsheet:write_only`
  - `drive:file:upload`
  - `drive:drive`
- 把表《小红书文案收集》加 bot 为「可编辑」协作者

**2. 配置 config.json**：

```bash
cd server/
cp config.json.example config.json
# 编辑 config.json，填入 app_secret（从飞书开发者后台 → 凭证与基础信息 → App Secret）
```

**3. 部署到服务器**：

```bash
cd server/
bash deploy.sh
```

部署后：
- API 监听 `http://14.22.112.147:8866`
- 健康检查 `curl http://14.22.112.147:8866/api/health`

### 二、Chrome 扩展

1. 打开 Chrome → 地址栏输入 `chrome://extensions`
2. 右上角打开「开发者模式」
3. 点「加载已解压的扩展程序」
4. 选 `xhs-extension-project/extension/` 目录
5. 扩展安装后，点扩展图标 → ⚙️ 设置页
6. 填 API Endpoint（`http://14.22.112.147:8866`）和 Auth Token（来自 server config.json）
7. 点「测试连接」验证 → 「保存」

## 使用

- **方式 1**：在小红书笔记页点扩展图标 → 写备注、加标签 → 「收录到飞书」
- **方式 2**：在小红书页面右键 → 「收录这条小红书笔记到飞书」（无 popup，直接采集）
- **方式 3**：浏览小红书时，扩展图标自动显示 ✓ 徽标表示「已收录」
- **方式 4**：在千帆「笔记数据-商品笔记」页面点扩展图标 → 「开启宽屏分析」；需要回到原页面时点「恢复官方布局」

### 千帆宽屏分析说明

- 只作用于当前千帆标签页，整页刷新后自动回到小红书官方布局
- 保留主内容区原来的左侧位置，把右侧安全边距收窄到约 24px，优先利用原页面右侧空白
- 笔记信息、商品、发布时间和操作列保留独立宽度；指标列最低 84px，在用户当前宽屏页面上实际约 100px
- 表头保留官方完整名称并允许两行展示，不再用 56px 窄列强行压缩
- 如果屏幕本身不足以容纳可读列宽，会保留横向滚动，不以牺牲可读性换取“强行同屏”
- 页面筛选、排序、翻页和「笔记详情」继续使用小红书原有功能
- 如果页面尚未加载出「笔记列表」或未识别到千帆页面外壳，插件会显示具体错误和重新检测入口，不会出现空白页
- 点击「恢复官方布局」会还原页面外壳边距、宽度、滚动方式和表格原始列宽

## API 接口

| 接口 | 说明 |
|---|---|
| `GET /api/health` | 健康检查（无鉴权） |
| `GET /api/check?url=<url>` | 检测是否已存在 |
| `POST /api/collect` | 单条采集+写入 |
| `POST /api/collect-batch` | 批量采集+写入 |

所有写接口需要 Header：`X-Auth-Token: <config.json 里的 auth_token>`

## 安全注意

- `config.json` **绝不提交到 git**（含 app_secret + auth_token）
- 服务器 token 文件权限设 600（部署脚本会自动做）
- API 暴露在公网 8866 端口，靠 auth_token 鉴权 — 不要泄露 token

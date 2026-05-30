# 小红书一键收录 — 浏览器扩展项目

把小红书笔记一键收录到飞书表《小红书文案收集》。

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

> 给王小熊的晨报 · 2026-05-23 凌晨批次
> 醒来按这份从上往下看，每步都附验收命令

# 一句话现状

**v4.1.0 已上线**：popup 加号 bug 修了 + 更新日志面板（铃铛 + 弹窗）+ 版本号管理体系 + deploy.sh 致命安全 fix。后端已部署 `14.22.112.147:8866`，本地 zip 已打。**等你 5 分钟验收**。

---

# 本批次完成清单（4 个 agent 并行干完，1 小时）

| 任务 | 完成情况 |
|---|---|
| **B016 popup「+」加号无响应** | ✅ 根因 = Chrome MV3 禁用 `window.prompt`。已改自定义模态框（同时把 `confirm()` 也换了） |
| **B014 版本号管理** | ✅ manifest 4.0.0→4.1.0；新建 `bump-version.sh`（交互式 patch/minor/major）+ `CHANGELOG.md` |
| **B015 更新日志面板** | ✅ popup 顶部加铃铛+红点，minor/major bump 自动弹窗。后端 `/api/changelog` 已上线，前端 fallback 到 mock 数据 |
| **deploy.sh 致命 fix** | ✅ 加 `--exclude data.db` 等，防止跑 deploy 时本地空 SQLite 覆盖生产数据库（这是 Codex 抓到的 P0） |
| **CLAUDE.md 修正** | ✅ 修了「v4.0.0.zip（35KB）」的虚假记录（实际只有未压缩目录） |

---

# 你的验收清单（5 分钟）

## ① 验证后端 changelog endpoint（30 秒）

```bash
curl -s http://14.22.112.147:8866/api/changelog | python3 -m json.tool
```

**预期**：返回 `current_latest: "4.1.0"` + 2 条 changelog 数据。

## ② 重装扩展（2 分钟）

```bash
# 解压新 zip 到桌面
cd ~/Desktop
unzip -o "/Users/a86132/Desktop/小红书电商学习文件/小红书工具/xhs-extension-project/dist/小红书一键收录-v4.1.0.zip"
```

Chrome 操作：
1. 打开 `chrome://extensions`
2. 找到当前扩展 → 点「重新加载」按钮（**不要删了重装**，保留 storage）
3. 如果想要彻底新装：先卸载 → 加载已解压扩展 → 选 `~/Desktop/小红书一键收录-v4.1.0/extension/` 目录

## ③ 验收 B016 加号 bug（1 分钟）

1. 打开任意小红书笔记
2. 点扩展图标 → 弹窗出现
3. 看分类下拉旁的「+」→ **点它**
4. **预期**：弹出红色品牌色模态框「新建分类」，输入框 autofocus
5. 输入「测试分类」+ 回车 → 应该新建成功 + 下拉自动选中

## ④ 验收 B015 更新日志面板（1 分钟）

1. 关闭弹窗再打开（重新触发 popup 初始化）
2. **预期**：因为是新版本 + 没读过 → **自动弹出更新日志弹窗**，标题「🎉 v4.1.0 更新内容」
3. 点「我知道了」 → 弹窗关闭
4. 再次打开 popup → **不再自动弹**（已读）
5. 看顶部「🚪 退出登录」左边 → 有一个铃铛图标，点它 → 弹窗再次出现

## ⑤ 验收 deploy.sh 安全 fix（10 秒）

```bash
grep "exclude.*data.db" "/Users/a86132/Desktop/小红书电商学习文件/小红书工具/xhs-extension-project/server/deploy.sh"
```

**预期**：输出 `--exclude 'data.db' --exclude 'data.db-journal'`

---

# 关键产物路径

| 产物 | 路径 |
|---|---|
| 发布包 zip | `dist/小红书一键收录-v4.1.0.zip`（40 KB） |
| 发布包目录 | `dist/小红书一键收录-v4.1.0/` |
| 一键发版脚本 | `bump-version.sh`（交互式输入 changelog） |
| 更新日志 | `CHANGELOG.md`（含 v4.1.0 / v4.0.0 / v3.1.0 / v2.3.2 历史） |
| Bug 清单 | `BUGS.md`（B014/B015/B016 已录入 + 标为「已修复（待验收）」） |
| 项目状态 | `CLAUDE.md`（已修虚假 zip 记录 + 本批次完工说明） |
| 生产数据库备份 | 服务器 `/opt/xhs-collect/data.db.bak.1779472567` |

---

# 🟠 必须知道的风险与遗留问题

## 1. 你账号当前的 changelog_read_version 是空的

第一次重装打开 popup 会**自动弹一次** v4.1.0 更新内容。这是设计预期，但如果你不想被弹烦，直接点「我知道了」就再也不弹了。

## 2. 同事拿到 v4.1.0 zip 后也会自动弹一次

陈一/黑子/苏西西首次装时都会自动弹 v4.1.0 弹窗。这是好事（让他们知道更新了啥）。

## 3. Agent 1 顺手发现的另一个 bug（不在本批次范围）

**「分类初始化缺失」**：你截图里下拉框只有「Sheet1」，说明 onboarding 绑表时**默认 7 个分类 sheet 没建出来**。
- 这跟加号 bug 是两回事（加号修好后你能手动建分类绕过）
- **建议另开 B017 跟进**：让 Agent 1 报告里也提到了
- 短期 workaround：你点加号挨个建「起号 / 爆款 / 同行精选 / 潜力款 / 标题公式 / 互动引导 / 待研究」

## 4. bump-version.sh 还没在生产用过

只跑了语法检查，**还没真跑过 bump**。下次你要发 v4.1.1 时直接 `./bump-version.sh patch`，遇到问题告诉我。

---

# 🔴 如果出问题怎么 rollback

## 后端 rollback（如果 /api/changelog 把生产搞挂了）

```bash
# 备份还原
ssh root@14.22.112.147 "
  cp /opt/xhs-collect/data.db.bak.1779472567 /opt/xhs-collect/data.db &&
  pm2 restart xhs-collect-api
"
# 检查
curl -s http://14.22.112.147:8866/api/health
```

## 扩展 rollback（如果新 zip 有问题）

⚠️ v4.0.0 **没有打过 zip**，只有未压缩目录 `dist/小红书一键收录-v4.0.0/`。

正确的回滚方式：

```bash
# 方法 A：直接在 chrome://extensions 加载 v4.0.0 未压缩目录
# 1. 浏览器打开 chrome://extensions
# 2. 卸载当前 v4.1.0
# 3. 点「加载已解压的扩展」
# 4. 选择路径：/Users/a86132/Desktop/小红书电商学习文件/小红书工具/xhs-extension-project/dist/小红书一键收录-v4.0.0/extension

# 方法 B：把 v4.0.0 拷贝到桌面再加载
cp -r "/Users/a86132/Desktop/小红书电商学习文件/小红书工具/xhs-extension-project/dist/小红书一键收录-v4.0.0" ~/Desktop/
# 然后 chrome://extensions 加载 ~/Desktop/小红书一键收录-v4.0.0/extension/
```

⚠️ 回滚 v4.0.0 后**铃铛和加号 bug 会回来**，所以只在 v4.1.0 出严重问题时才回滚。

---

# 接下来怎么走

## 短期（今天/明天）

1. **你验收上面 5 个 checkbox**，反馈通过/失败
2. **B017 分类初始化缺失** → 我下次会话来修（让默认 7 个分类在绑表时一定建出来）
3. **3 同事分发** v4.1.0 zip + 激活码（按 [CLAUDE.md:96-130](xhs-extension-project/CLAUDE.md:96) 流程）

## 中期（本周）

按 BUGS.md 优先级啃 B001-B013：
- **B001/B004/B005**（P1，UI 整页重做）
- **B003/B011**（P1，emoji 换 SVG icon）
- **B002**（P1，扩展图标 AI 生图，需要你做主观选择）

## 长期

按 CLAUDE.md 项目状态文档的 backlog 推进（批量收录搜索页 / AI 文案拆解 / 爆款分级等）。

---

# Codex 反对派审查本批次表现

本次会话 Codex 反对派审查共抓出 **8 个事实错误**，我已**逐条修正**：

**第一轮**（架构/事实层）：
| # | Codex 指出 | 我的处理 |
|---|---|---|
| 1 | 老用户重扫码无需重激活码 | ✅ 修正方案设计（取消防重登需求） |
| 2 | manifest key 不能恢复已删 storage | ✅ 修正话术，不再过度承诺 |
| 3 | `dist/v4.0.0.zip` 不存在 | ✅ 更新 CLAUDE.md 虚假记录 |
| 4 | 源码 ≈ dist（只差 secrets） | ✅ 修正"对账失控"过度断言 |
| 5 | **deploy.sh 漏 `--exclude data.db`** | ✅ **致命 fix，已修** |

**第二轮**（产物/脚本层）：
| # | Codex 指出 | 我的处理 |
|---|---|---|
| 6 | `bump-version.sh` zip 路径会带 `dist/` 前缀 | ✅ 改成 `cd $DIST_DIR` 再 zip。手动打的 v4.1.0.zip 实测无 dist 前缀，仍可用 |
| 7 | rollback 用 unzip 操作目录 | ✅ 改成 `cp -r` 或 chrome://extensions 直接加载未压缩目录 |
| 8 | **`bump-version.sh` 无确认 `rm -rf`** | ✅ 改成默认报错退出 + 加 `--force` 才移到 `dist/.trash/<ts>/`（不真删） |

**第 5 条 + 第 8 条是真正救命的**：
- 第 5：如果跑 deploy.sh 部署后端，会把本地空 SQLite 覆盖生产 → 所有用户/激活码/收录数据全丢
- 第 8：bump-version.sh 跑两次同版本会无确认删旧产物 → 违反 CLAUDE.md "不删文件" 底线

Codex 双审机制再次证明 ROI 巨大。

---

# 收尾

本批次 4 个并行 agent + 主线集成，实际耗时 ~1 小时。所有改动均**未 git commit**（按 CLAUDE.md 规则）。
醒来告诉我验收结果，或者下一步要做什么。

🌙 早。

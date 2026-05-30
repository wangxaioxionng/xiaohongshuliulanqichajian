// onboarding.js — v4 OAuth 注册流程（4 屏状态机）

// ---------- 工具：endpoint + token ----------

function getEndpoint() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["endpoint"], (data) => {
      // 兜底：admin 包自带 secrets.js；员工包从 popup.js 的 DEFAULT_ENDPOINT_FALLBACK 一致
      resolve(data.endpoint ||
        (typeof XHS_API_ENDPOINT !== "undefined" ? XHS_API_ENDPOINT : "http://14.22.112.147:8866")
      );
    });
  });
}

function getJwt() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["jwt"], (data) => resolve(data.jwt || ""));
  });
}

function setJwt(jwt) {
  return new Promise((resolve) => {
    chrome.storage.local.set({ jwt }, resolve);
  });
}

function clearJwt() {
  return new Promise((resolve) => {
    chrome.storage.local.remove(["jwt"], resolve);
  });
}

// ---------- API ----------

async function apiMe() {
  const endpoint = await getEndpoint();
  const jwt = await getJwt();
  if (!jwt) return null;
  const resp = await fetch(`${endpoint}/api/me`, {
    headers: { "Authorization": `Bearer ${jwt}` },
  });
  if (resp.status === 401) {
    await clearJwt();
    return null;
  }
  if (!resp.ok) throw new Error(`/api/me HTTP ${resp.status}`);
  return resp.json();
}

async function apiActivate(code) {
  const endpoint = await getEndpoint();
  const jwt = await getJwt();
  const resp = await fetch(`${endpoint}/auth/activate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${jwt}`,
    },
    body: JSON.stringify({ code }),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
  return data;
}

async function apiBindSheet(spreadsheet_url) {
  const endpoint = await getEndpoint();
  const jwt = await getJwt();
  const resp = await fetch(`${endpoint}/auth/bind-sheet`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${jwt}`,
    },
    body: JSON.stringify({ spreadsheet_url }),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
  return data;
}

// 调用后端权限自检接口（Agent B 提供）
// v4.3.5 B036 修订：参数从"裸 token"改成"完整 URL"，让后端 smart resolve（含 wiki API 调用）
// 前端只做 URL 格式预校验，不再前端 parse token（避免裸 wiki_token 落到后端被错当 spreadsheet_token）
async function apiCheckPermission(urlOrToken) {
  const endpoint = await getEndpoint();
  const jwt = await getJwt();
  const url = `${endpoint}/api/permissions/check?spreadsheet_token=${encodeURIComponent(urlOrToken)}`;
  const resp = await fetch(url, {
    headers: { "Authorization": `Bearer ${jwt}` },
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.detail || data.user_message || `HTTP ${resp.status}`);
  return data;
}

// 调用 /api/sheets 检查分类 sheet 数量
async function apiSheets() {
  const endpoint = await getEndpoint();
  const jwt = await getJwt();
  const resp = await fetch(`${endpoint}/api/sheets`, {
    headers: { "Authorization": `Bearer ${jwt}` },
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
  return data;
}

// 从飞书表 URL 解析 token（v4.3.5 B036：支持 /sheets/ 和 /wiki/ 两种）
// /sheets/{token} → 直接 spreadsheet_token
// /wiki/{wiki_token} → wiki 节点 token，后端会调 wiki API 解析成 spreadsheet_token
// 返回 { token, kind }：kind ∈ "sheet" | "wiki" | null
function parseSpreadsheetToken(url) {
  if (!url) return null;
  const mSheet = url.match(/\/sheets\/([A-Za-z0-9]+)/);
  if (mSheet) return mSheet[1];
  const mWiki = url.match(/\/wiki\/([A-Za-z0-9]+)/);
  if (mWiki) return mWiki[1];
  return null;
}

// ---------- 屏切换 ----------

function showScreen(name) {
  document.querySelectorAll(".screen").forEach((el) => el.classList.remove("active"));
  document.getElementById(`screen-${name}`).classList.add("active");
  // 步骤指示器
  const steps = {
    login: 1, "paste-jwt": 1,
    activation: 2,
    "bind-sheet": 3,
    done: 3,
  };
  const active = steps[name] || 1;
  for (let i = 1; i <= 3; i++) {
    const el = document.getElementById(`step-indicator-${i}`);
    el.classList.remove("active", "done");
    if (i < active) el.classList.add("done");
    else if (i === active) el.classList.add("active");
  }
}

function showMsg(id, type, html) {
  const el = document.getElementById(id);
  el.className = `status-msg show ${type}`;
  el.innerHTML = html;
}

function escapeHTML(s) {
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderUserInfo(elId, user) {
  const el = document.getElementById(elId);
  el.innerHTML = `
    ${user.avatar_url ? `<img src="${user.avatar_url}">` : ""}
    <div>
      <div class="name">${escapeHTML(user.name || "（未命名）")}</div>
      <div class="status">${user.status === "active" ? "已激活" : "待激活"}</div>
    </div>
  `;
}

// ---------- 流程：路由到对应屏 ----------

async function routeByState() {
  const jwt = await getJwt();
  if (!jwt) {
    showScreen("login");
    return;
  }
  try {
    const me = await apiMe();
    if (!me) {
      showScreen("login");
      return;
    }
    if (me.needs_activation) {
      renderUserInfo("user-info-activation", me);
      showScreen("activation");
      return;
    }
    if (me.needs_bind_sheet) {
      renderUserInfo("user-info-bind", me);
      showScreen("bind-sheet");
      return;
    }
    // 完成态
    renderUserInfo("user-info-done", me);
    showScreen("done");
  } catch (err) {
    showMsg("msg-jwt", "error", `加载用户信息失败：${escapeHTML(err.message)}`);
    showScreen("login");
  }
}

// ---------- 事件绑定 ----------

document.addEventListener("DOMContentLoaded", () => {
  // 启动时路由
  routeByState();

  // 登录按钮
  document.getElementById("btn-login").addEventListener("click", async () => {
    const endpoint = await getEndpoint();
    // 新标签页打开飞书 OAuth 流程
    chrome.tabs.create({ url: `${endpoint}/auth/login` });
    // 切到「等待中」屏（background.js 收到 token 后会 reload 这个页面，自动跳到下一屏）
    showScreen("paste-jwt");
    // 15 秒后如果还没自动跳转，显示手动粘贴 fallback
    setTimeout(() => {
      // 如果当前还停在这一屏（说明 background 没监听到）
      if (document.getElementById("screen-paste-jwt").classList.contains("active")) {
        document.getElementById("manual-fallback-hint").style.display = "block";
      }
    }, 15000);
    // 监听 storage 变化：background.js 写入 jwt 后 → reload
    chrome.storage.onChanged.addListener(function listener(changes, area) {
      if (area === "local" && changes.jwt && changes.jwt.newValue) {
        chrome.storage.onChanged.removeListener(listener);
        // 直接 routeByState 而不是 reload（避免 reload 副作用）
        setTimeout(routeByState, 200);
      }
    });
  });

  // 提交 JWT
  document.getElementById("btn-submit-jwt").addEventListener("click", async () => {
    const jwt = document.getElementById("input-jwt").value.trim();
    if (!jwt) {
      showMsg("msg-jwt", "error", "请粘贴飞书返回的 Token");
      return;
    }
    if (jwt.split(".").length !== 3) {
      showMsg("msg-jwt", "error", "Token 格式不对，应该是三段用 . 分隔的字符串");
      return;
    }
    await setJwt(jwt);
    showMsg("msg-jwt", "success", "✅ Token 已保存，加载用户信息…");
    setTimeout(routeByState, 500);
  });

  // 激活码
  document.getElementById("btn-activate").addEventListener("click", async () => {
    const code = document.getElementById("input-code").value.trim();
    if (!code) {
      showMsg("msg-activate", "error", "请输入激活码");
      return;
    }
    const btn = document.getElementById("btn-activate");
    btn.disabled = true; btn.textContent = "激活中…";
    try {
      const r = await apiActivate(code);
      showMsg("msg-activate", "success", `✅ ${r.message}`);
      setTimeout(routeByState, 800);
    } catch (err) {
      showMsg("msg-activate", "error", `❌ ${escapeHTML(err.message)}`);
      btn.disabled = false; btn.textContent = "激活账号";
    }
  });

  // 输入框变动 → 主按钮重新置灰（必须重新检测权限）
  document.getElementById("input-sheet").addEventListener("input", () => {
    const bindBtn = document.getElementById("btn-bind");
    bindBtn.disabled = true;
    const statusEl = document.getElementById("permission-status");
    statusEl.className = "status-msg";
    statusEl.innerHTML = "";
  });

  // 检测 bot 权限按钮
  document.getElementById("btn-check-permission").addEventListener("click", async () => {
    const url = document.getElementById("input-sheet").value.trim();
    const bindBtn = document.getElementById("btn-bind");
    const checkBtn = document.getElementById("btn-check-permission");

    if (!url) {
      showMsg("permission-status", "error", "❌ 请先粘贴飞书表 URL");
      bindBtn.disabled = true;
      return;
    }
    const token = parseSpreadsheetToken(url);
    if (!token) {
      showMsg("permission-status", "error", "❌ URL 看着不像飞书表（应包含 /sheets/ 或 /wiki/）");
      bindBtn.disabled = true;
      return;
    }

    checkBtn.disabled = true;
    const oldHtml = checkBtn.innerHTML;
    checkBtn.innerHTML = '<span class="icon">⏳</span> 检测中…';
    showMsg("permission-status", "info", "正在检测 bot 是否有写权限，约 3-5 秒…");

    try {
      // v4.3.5 B036 修订：传完整 URL 给后端 smart resolve（含 wiki），不传裸 token
      const r = await apiCheckPermission(url);
      if (r.write_ok === true) {
        showMsg("permission-status", "success",
          "✅ 权限完整，可以绑表。点下面「绑定 + 自动建分类」按钮继续。");
        bindBtn.disabled = false;
      } else {
        const msg = r.user_message || "bot 没有写权限，无法建分类 sheet。";
        showMsg("permission-status", "error",
          `❌ ${escapeHTML(msg)}<br><br>` +
          `<b>解决</b>：飞书表右上角 ⋯ → 更多 → 添加文档应用 → 搜「小红书收录助手」→ 添加。` +
          `<a href="help.html#add-doc-app" target="_blank">📸 看图教程</a><br><br>` +
          `<a href="#" id="link-recheck">🔄 重新检测</a>`);
        bindBtn.disabled = true;
        // 重新检测链接（避免用户找不到按钮）
        const recheckLink = document.getElementById("link-recheck");
        if (recheckLink) {
          recheckLink.addEventListener("click", (e) => {
            e.preventDefault();
            document.getElementById("btn-check-permission").click();
          });
        }
      }
    } catch (err) {
      showMsg("permission-status", "error",
        `❌ 检测失败：${escapeHTML(err.message)}<br>` +
        `如果一直失败，可能是后端接口还没部署 / 网络问题，请联系王小熊。`);
      bindBtn.disabled = true;
    } finally {
      checkBtn.disabled = false;
      checkBtn.innerHTML = oldHtml;
    }
  });

  // 绑表
  document.getElementById("btn-bind").addEventListener("click", async () => {
    const url = document.getElementById("input-sheet").value.trim();
    if (!url) {
      showMsg("msg-bind", "error", "请输入飞书表 URL");
      return;
    }
    if (!url.includes("/sheets/") && !url.includes("/wiki/")) {
      showMsg("msg-bind", "error", "URL 看着不像飞书表（应包含 /sheets/ 或 /wiki/）");
      return;
    }
    const btn = document.getElementById("btn-bind");
    btn.disabled = true; btn.textContent = "绑定中（约 10 秒）…";
    try {
      const r = await apiBindSheet(url);
      const created = (r.categories_created || []).length;
      showMsg("msg-bind", "success",
        `✅ 绑定成功！自动创建了 ${created} 个分类 sheet${created ? "：" + r.categories_created.join("、") : "（已有的跳过）"}<br>⏳ 正在做最终自检（确认 7 个分类都在）…`);

      // Task C3：进屏 4 前最终自检
      btn.textContent = "自检中…";
      try {
        const me = await apiMe();
        if (!me || !me.spreadsheet_token) {
          throw new Error("/api/me 返回 spreadsheet_token 为空");
        }
        const sheetsData = await apiSheets();
        // 兼容多种返回结构（数组 / {sheets: []} / {data: []}）
        let sheets = [];
        if (Array.isArray(sheetsData)) sheets = sheetsData;
        else if (Array.isArray(sheetsData.sheets)) sheets = sheetsData.sheets;
        else if (Array.isArray(sheetsData.data)) sheets = sheetsData.data;
        else if (Array.isArray(sheetsData.categories)) sheets = sheetsData.categories;

        const sheetCount = sheets.length;
        const REQUIRED = 7;
        if (sheetCount < REQUIRED) {
          showMsg("msg-bind", "error",
            `❌ 绑表似乎没完全成功（只读到 <b>${sheetCount}</b> 个分类，期望 ${REQUIRED} 个）。<br><br>` +
            `<b>可能原因</b>：bot 写权限不完整，部分 sheet 没建出来。<br>` +
            `<b>建议</b>：检查飞书表是否按「添加文档应用」方式授权 bot，然后点「🔄 重新检测」+ 再点「绑定」重试。<br>` +
            `如多次失败请联系王小熊。`);
          btn.disabled = false; btn.textContent = "绑定 + 自动建分类";
          return;
        }
        // 自检通过 → 进屏 4
        showMsg("msg-bind", "success",
          `✅ 绑定成功 + 自检通过（${sheetCount} 个分类全部就位）！正在进入完成页…`);
        setTimeout(routeByState, 1200);
      } catch (selfCheckErr) {
        showMsg("msg-bind", "error",
          `❌ 绑表后自检失败：${escapeHTML(selfCheckErr.message)}<br><br>` +
          `请重新点「检测 bot 权限」+ 重新绑表，或联系王小熊。`);
        btn.disabled = false; btn.textContent = "绑定 + 自动建分类";
      }
    } catch (err) {
      showMsg("msg-bind", "error",
        `❌ ${escapeHTML(err.message)}<br><br><b>常见原因</b>：bot 没有写权限。回飞书表 → 右上角 ⋯ → 更多 → 添加文档应用 → 搜「小红书收录助手」→ 添加。<a href="help.html#add-doc-app" target="_blank">📸 看图教程</a>`);
      btn.disabled = false; btn.textContent = "绑定 + 自动建分类";
    }
  });

  document.getElementById("btn-close").addEventListener("click", () => {
    window.close();
  });

  // 完成屏：打开示例笔记
  document.getElementById("btn-try-demo")?.addEventListener("click", () => {
    // 用一条通用爆款笔记（公开可访问）
    // 用户点扩展图标 → 弹 popup → 直接体验收录
    chrome.tabs.create({
      url: "https://www.xiaohongshu.com/explore"  // 探索页，让用户挑一条试
    });
    // 顺手关闭 onboarding 这个 tab
    setTimeout(() => window.close(), 500);
  });
});

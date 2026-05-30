// popup.js — 小红书一键收录扩展的主交互逻辑
// 注意：先加载 secrets.js（提供 XHS_API_ENDPOINT 和 XHS_API_TOKEN 常量）

// SHEET_URL 不再硬编码，由 /api/whoami 返回（v3.1.1）。下面是兜底 fallback。
const SHEET_URL_FALLBACK = "https://my.feishu.cn";
let CACHED_SHEET_URL = "";
const XHS_HOST_RE = /(?:xiaohongshu\.com|xhslink\.com)/i;
// v4.4.0：小红书账号主页 URL pattern
const XHS_PROFILE_RE = /xiaohongshu\.com\/user\/profile\//i;
const PROFILE_COLLECT_LIMIT = 400;
const PROFILE_SCROLL_MIN_DELAY_MS = 1200;
const PROFILE_SCROLL_MAX_DELAY_MS = 2200;
const PROFILE_SCROLL_BATCH_PAUSE_MIN_MS = 4000;
const PROFILE_SCROLL_BATCH_PAUSE_MAX_MS = 7000;
const PROFILE_SCROLL_BATCH_LINKS = 25;
const PROFILE_SCROLL_BATCH_ROUNDS = 12;
const PROFILE_COLLECT_STATE_KEY = "profileCollectState";
let PROFILE_COLLECT_POLL_TIMER = null;

// ---------- 配置：默认值用内置凭证，允许 chrome.storage 覆盖 ----------

function getConfig() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["endpoint", "authToken", "jwt"], (data) => {
      // 兜底：admin 自用包里会带 secrets.js 提供这两个常量；团队成员包里没有
      const defaultEp = (typeof XHS_API_ENDPOINT !== "undefined")
        ? XHS_API_ENDPOINT
        : "http://14.22.112.147:8866";
      const defaultTok = (typeof XHS_API_TOKEN !== "undefined")
        ? XHS_API_TOKEN
        : "";
      resolve({
        endpoint: data.endpoint || defaultEp,
        authToken: data.authToken || defaultTok,
        jwt: data.jwt || "",
      });
    });
  });
}

// 统一构造请求头：JWT 优先，legacy token fallback
function authHeaders(cfg) {
  if (cfg.jwt) return { "Authorization": `Bearer ${cfg.jwt}` };
  if (cfg.authToken) return { "X-Auth-Token": cfg.authToken };
  return {};
}

function isAuthenticated(cfg) {
  return !!(cfg.jwt || cfg.authToken);
}

function openOnboarding() {
  chrome.tabs.create({ url: chrome.runtime.getURL("onboarding.html") });
  window.close();
}

async function logout() {
  await new Promise((r) =>
    chrome.storage.local.remove(["jwt", "lastCategorySheetId",
                                 "dashboardCache"], r));
  openOnboarding();
}

// ---------- 当前标签页 URL ----------

async function getCurrentTab() {
  const queries = [
    { active: true, currentWindow: true },
    { active: true, lastFocusedWindow: true },
    { active: true },
  ];
  let fallback = null;

  for (const query of queries) {
    const tabs = await new Promise((resolve) => {
      chrome.tabs.query(query, (items) => resolve(items || []));
    });
    const first = tabs && tabs[0] ? tabs[0] : null;
    if (!fallback && first) fallback = first;

    const xhsTab = (tabs || []).find((item) => XHS_HOST_RE.test(item.url || ""));
    if (xhsTab) return xhsTab;
  }

  return fallback || { url: "", title: "" };
}

function getCurrentTabUrl() {
  return getCurrentTab().then((t) => t.url || "");
}

function sendRuntimeMessage(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (resp) => {
      const err = chrome.runtime.lastError;
      if (err) {
        reject(new Error(err.message));
        return;
      }
      resolve(resp || {});
    });
  });
}

// 清洗小红书页面 title：去掉「| 小红书」「- 你的生活兴趣社区」等后缀
function cleanXhsTitle(rawTitle) {
  if (!rawTitle) return "";
  return rawTitle
    .replace(/\s*[|｜]\s*小红书.*$/i, "")
    .replace(/\s*-\s*你的生活兴趣社区.*$/i, "")
    .replace(/\s*-\s*小红书.*$/i, "")
    .trim() || rawTitle;
}

function normalizeXhsNoteUrl(rawUrl) {
  try {
    const u = new URL(String(rawUrl || ""), "https://www.xiaohongshu.com");
    if (!/xiaohongshu\.com$/i.test(u.hostname)) return "";
    const m = u.pathname.match(/\/(?:explore|discovery\/item)\/([a-zA-Z0-9]+)/);
    if (!m || !m[1]) return "";
    u.hash = "";
    return u.toString();
  } catch (e) {
    return "";
  }
}

function extractActiveNoteUrlFromPage() {
  function normalize(rawUrl) {
    try {
      const u = new URL(String(rawUrl || ""), location.origin);
      if (!/xiaohongshu\.com$/i.test(u.hostname)) return "";
      const m = u.pathname.match(/\/(?:explore|discovery\/item)\/([a-zA-Z0-9]+)/);
      if (!m || !m[1]) return "";
      u.hash = "";
      return u.toString();
    } catch (e) {
      return "";
    }
  }

  function hasToken(url) {
    try {
      return !!new URL(url).searchParams.get("xsec_token");
    } catch (e) {
      return false;
    }
  }

  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width < 80 || rect.height < 80) return false;
    const style = window.getComputedStyle ? window.getComputedStyle(el) : null;
    if (!style) return true;
    return style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0";
  }

  const direct = normalize(location.href);
  if (direct) return direct;

  const metaCandidates = Array.from(document.querySelectorAll(
    'meta[property="og:url"], meta[name="og:url"], link[rel="canonical"]',
  )).map((el) => el.content || el.href || "");
  for (const candidate of metaCandidates) {
    const url = normalize(candidate);
    if (url) return url;
  }

  const modalRoots = Array.from(document.querySelectorAll([
    '[role="dialog"]',
    '.note-detail-mask',
    '.note-detail-container',
    '.note-detail',
    '[class*="note-detail"]',
    '[class*="NoteDetail"]',
  ].join(","))).filter(isVisible);

  const urls = [];
  function add(rawUrl) {
    const url = normalize(rawUrl);
    if (url && !urls.includes(url)) urls.push(url);
  }

  for (const root of modalRoots) {
    add(root.getAttribute("href"));
    add(root.getAttribute("data-href"));
    add(root.getAttribute("data-url"));
    for (const a of Array.from(root.querySelectorAll('a[href*="/explore/"], a[href*="/discovery/item/"]'))) {
      add(a.href);
      add(a.getAttribute("href"));
      add(a.getAttribute("data-href"));
      add(a.getAttribute("data-url"));
    }
  }

  return urls.find(hasToken) || urls[0] || "";
}

async function resolveCurrentNoteUrl(tab) {
  const direct = normalizeXhsNoteUrl(tab?.url || "");
  if (direct) return direct;
  if (!tab || !tab.id || !XHS_HOST_RE.test(tab.url || "")) return "";
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: extractActiveNoteUrlFromPage,
    });
    return normalizeXhsNoteUrl(results?.[0]?.result || "");
  } catch (e) {
    return "";
  }
}

// ---------- 状态展示 ----------

function setStatus(type, html) {
  const el = document.getElementById("status");
  el.className = `status show ${type}`;
  el.innerHTML = html;
}

function hideStatus() {
  document.getElementById("status").className = "status";
}

// ---------- 后端 API 调用 ----------

async function apiCheck(url, cfg) {
  const params = new URLSearchParams({ url });
  const resp = await fetch(`${cfg.endpoint}/api/check?${params}`, {
    method: "GET",
    headers: authHeaders(cfg),
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function apiCollect(url, note, tags, cfg, sheetId, dupStrategy) {
  const body = { url, note, tags, source: "Extension" };
  if (sheetId) body.sheet_id = sheetId;
  if (dupStrategy) body.dup_strategy = dupStrategy;
  const resp = await fetch(`${cfg.endpoint}/api/collect`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(cfg),
},
    body: JSON.stringify(body),
  });
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || `HTTP ${resp.status}`);
  }
  return data;
}

async function getUserPref() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(["dupStrategy"], (d) =>
      resolve({ dupStrategy: d.dupStrategy || "skip" })
    );
  });
}

async function apiListSheets(cfg) {
  const resp = await fetch(`${cfg.endpoint}/api/sheets`, {
    headers: authHeaders(cfg),
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function apiDashboard(cfg, limit = 5) {
  const resp = await fetch(`${cfg.endpoint}/api/dashboard?limit=${limit}`, {
    headers: authHeaders(cfg),
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function apiFailures(cfg) {
  const resp = await fetch(`${cfg.endpoint}/api/failures`, {
    headers: authHeaders(cfg),
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function apiRetry(cfg, sheetId, row) {
  const resp = await fetch(`${cfg.endpoint}/api/retry`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(cfg),
},
    body: JSON.stringify({ sheet_id: sheetId, row }),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
  return data;
}

async function apiCreateCategory(title, cfg) {
  const resp = await fetch(`${cfg.endpoint}/api/categories`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(cfg),
},
    body: JSON.stringify({ title }),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
  return data;
}

// ---------- 分类下拉 ----------

const LAST_CATEGORY_KEY = "lastCategorySheetId";

async function loadCategories(cfg) {
  const select = document.getElementById("category-select");
  try {
    const data = await apiListSheets(cfg);
    const sheets = data.sheets || [];
    const defaultSheetId = data.default_sheet_id;
    // 上次用的分类
    const remembered = await new Promise((resolve) => {
      chrome.storage.local.get([LAST_CATEGORY_KEY], (d) =>
        resolve(d[LAST_CATEGORY_KEY])
      );
    });
    // 校验上次记忆的 sheet_id 是否还存在；不存在 fallback 到默认
    const validIds = new Set(sheets.map((s) => s.sheet_id));
    let initialId = remembered && validIds.has(remembered)
      ? remembered
      : defaultSheetId;
    if (remembered && !validIds.has(remembered)) {
      // 清理失效的记忆
      chrome.storage.local.remove(LAST_CATEGORY_KEY);
    }

    select.innerHTML = "";
    sheets.forEach((s) => {
      const opt = document.createElement("option");
      opt.value = s.sheet_id;
      opt.textContent = s.title;
      if (s.sheet_id === initialId) opt.selected = true;
      select.appendChild(opt);
    });
  } catch (err) {
    select.innerHTML = `<option value="">加载失败: ${err.message}</option>`;
  }
}

function getSelectedSheetId() {
  return document.getElementById("category-select").value || "";
}

function rememberCategory(sheetId) {
  chrome.storage.local.set({ [LAST_CATEGORY_KEY]: sheetId });
}

// ---------- 仪表盘 ----------

const DASHBOARD_CACHE_KEY = "dashboardCache";
const DASHBOARD_CACHE_TTL = 60 * 1000; // 60 秒

async function loadDashboard(cfg, force = false) {
  // 缓存读取
  if (!force) {
    const cached = await new Promise((resolve) =>
      chrome.storage.local.get([DASHBOARD_CACHE_KEY], (d) =>
        resolve(d[DASHBOARD_CACHE_KEY])
      )
    );
    if (cached && Date.now() - cached.ts < DASHBOARD_CACHE_TTL) {
      renderDashboard(cached.data);
      return;
    }
  }
  // 拉新数据
  try {
    const data = await apiDashboard(cfg, 5);
    chrome.storage.local.set({
      [DASHBOARD_CACHE_KEY]: { data, ts: Date.now() },
    });
    renderDashboard(data);
  } catch (err) {
    console.warn("dashboard 加载失败：", err);
  }
}

function renderDashboard(data) {
  const stats = data.stats || {};
  document.getElementById("stat-today").textContent = stats.today ?? "-";
  document.getElementById("stat-week").textContent = stats.this_week ?? "-";
  document.getElementById("stat-total").textContent = stats.total ?? "-";
  const failedBox = document.getElementById("stat-failed-box");
  const failedNum = stats.failed_total ?? 0;
  if (failedNum > 0) {
    document.getElementById("stat-failed").textContent = failedNum;
    failedBox.style.display = "block";
  } else {
    failedBox.style.display = "none";
  }

  const list = document.getElementById("recent-list");
  list.innerHTML = "";
  const recent = data.recent || [];
  if (!recent.length) {
    list.innerHTML = `<div style="color:var(--gray-500);text-align:center;padding:12px">还没有数据</div>`;
    return;
  }
  recent.forEach((item) => {
    const div = document.createElement("div");
    div.className = "recent-item";
    div.innerHTML = `
      <div class="title">${escapeHTML(item.title || "(无标题)")}</div>
      <div class="meta">
        <span class="sheet-tag">${escapeHTML(item.sheet_title || "")}</span>
        <span>${escapeHTML(item.time || "")}</span>
        <span>第 ${item.row} 行</span>
      </div>
    `;
    div.addEventListener("click", () => {
      if (item.url) chrome.tabs.create({ url: item.url });
    });
    list.appendChild(div);
  });
}

// ---------- 失败列表 ----------

async function toggleFailureList(cfg) {
  const list = document.getElementById("failure-list");
  if (list.style.display === "block") {
    list.style.display = "none";
    return;
  }
  list.style.display = "block";
  const itemsEl = document.getElementById("failure-items");
  itemsEl.innerHTML = `<div style="color:var(--gray-500);font-size:11px;text-align:center;padding:8px">加载中…</div>`;
  try {
    const data = await apiFailures(cfg);
    const failures = data.failures || [];
    if (!failures.length) {
      itemsEl.innerHTML = `<div style="color:var(--gray-500);font-size:11px;text-align:center;padding:8px">没有失败记录 🎉</div>`;
      return;
    }
    itemsEl.innerHTML = "";
    failures.forEach((f) => {
      const div = document.createElement("div");
      div.className = "failure-item";
      div.innerHTML = `
        <div class="url" title="${escapeHTML(f.url)}">${escapeHTML(f.url || "(无 URL)")}</div>
        <div class="err">${escapeHTML(f.error || "")}</div>
        <div class="actions">
          <button class="retry" data-sheet="${f.sheet_id}" data-row="${f.row}">🔄 重试</button>
          <span style="font-size:10px;color:var(--gray-500);align-self:center">${escapeHTML(f.sheet_title)} · 行 ${f.row}</span>
        </div>
      `;
      itemsEl.appendChild(div);
    });
    itemsEl.querySelectorAll("button.retry").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        btn.textContent = "⏳";
        const itemEl = btn.closest(".failure-item");
        try {
          const r = await apiRetry(cfg, btn.dataset.sheet, parseInt(btn.dataset.row, 10));
          if (r.status === "ok" || r.status === "duplicate") {
            // 重试成功/已存在 → 这一行不再是失败，从 UI 移除
            chrome.storage.local.remove(DASHBOARD_CACHE_KEY);
            if (itemEl) {
              itemEl.style.transition = "opacity 0.3s";
              itemEl.style.opacity = "0";
              setTimeout(() => itemEl.remove(), 300);
            }
            // 失败计数 -1
            const failedNum = document.getElementById("stat-failed");
            const cur = parseInt(failedNum.textContent, 10) || 0;
            const next = Math.max(0, cur - 1);
            failedNum.textContent = next;
            if (next === 0) {
              document.getElementById("stat-failed-box").style.display = "none";
              const list = document.getElementById("failure-list");
              setTimeout(() => { list.style.display = "none"; }, 500);
            }
          } else {
            btn.textContent = "❌ 仍失败";
            btn.disabled = false;
            btn.style.background = "#DC2626";
          }
        } catch (err) {
          btn.textContent = "❌ " + (err.message || "").slice(0, 20);
          btn.disabled = false;
        }
      });
    });
  } catch (err) {
    itemsEl.innerHTML = `<div style="color:var(--red);font-size:11px">加载失败：${escapeHTML(err.message)}</div>`;
  }
}

// ---------- 自定义模态框（MV3 popup 禁用 prompt/confirm/alert） ----------
// 返回 Promise：
//   - prompt 模式：用户填值并确定 → resolve(string)；取消/Esc/点遮罩 → resolve(null)
//   - confirm 模式：确定 → resolve(true)；取消/Esc/点遮罩 → resolve(false)
function showModal({ title, desc = "", mode = "confirm", placeholder = "",
                     defaultValue = "", confirmText = "确定", cancelText = "取消" }) {
  return new Promise((resolve) => {
    const overlay = document.getElementById("modal-overlay");
    const titleEl = document.getElementById("modal-title");
    const descEl = document.getElementById("modal-desc");
    const inputEl = document.getElementById("modal-input");
    const confirmBtn = document.getElementById("modal-confirm");
    const cancelBtn = document.getElementById("modal-cancel");

    titleEl.textContent = title || "提示";
    descEl.textContent = desc || "";
    descEl.style.display = desc ? "block" : "none";
    confirmBtn.textContent = confirmText;
    cancelBtn.textContent = cancelText;

    if (mode === "prompt") {
      inputEl.style.display = "block";
      inputEl.value = defaultValue;
      inputEl.placeholder = placeholder;
    } else {
      inputEl.style.display = "none";
    }

    overlay.classList.add("show");
    // autofocus 必须在 show 后；prompt 模式聚焦输入框，confirm 聚焦确定按钮
    setTimeout(() => {
      if (mode === "prompt") inputEl.focus();
      else confirmBtn.focus();
    }, 50);

    function cleanup() {
      overlay.classList.remove("show");
      confirmBtn.removeEventListener("click", onConfirm);
      cancelBtn.removeEventListener("click", onCancel);
      overlay.removeEventListener("click", onOverlayClick);
      document.removeEventListener("keydown", onKey);
      inputEl.removeEventListener("keydown", onInputKey);
    }
    function onConfirm() {
      const val = mode === "prompt" ? inputEl.value : true;
      cleanup();
      resolve(val);
    }
    function onCancel() {
      cleanup();
      resolve(mode === "prompt" ? null : false);
    }
    function onOverlayClick(e) {
      // 只在点击遮罩本身（非卡片内部）时关闭
      if (e.target === overlay) onCancel();
    }
    function onKey(e) {
      if (e.key === "Escape") onCancel();
      else if (e.key === "Enter" && mode === "confirm") onConfirm();
    }
    function onInputKey(e) {
      if (e.key === "Enter") {
        e.preventDefault();
        onConfirm();
      }
    }

    confirmBtn.addEventListener("click", onConfirm);
    cancelBtn.addEventListener("click", onCancel);
    overlay.addEventListener("click", onOverlayClick);
    document.addEventListener("keydown", onKey);
    inputEl.addEventListener("keydown", onInputKey);
  });
}

async function handleNewCategory(cfg) {
  const title = await showModal({
    title: "新建分类",
    desc: "会自动在你的飞书表里建一个 sheet",
    mode: "prompt",
    placeholder: "例如：穿搭灵感",
    confirmText: "确定",
    cancelText: "取消",
  });
  if (title === null) return;
  const trimmed = title.trim();
  if (!trimmed) return;
  const btn = document.getElementById("btn-new-category");
  btn.disabled = true;
  btn.textContent = "⏳";
  try {
    const r = await apiCreateCategory(trimmed, cfg);
    // 刷新下拉
    await loadCategories(cfg);
    // 选中新建的
    document.getElementById("category-select").value = r.sheet_id;
    rememberCategory(r.sheet_id);
    setStatus(
      "success",
      `<div class="title">✅ 已新建分类「${escapeHTML(r.title)}」</div>
       <div>飞书表里多了一个 sheet，已自动切到该分类</div>`,
    );
  } catch (err) {
    setStatus("error", `❌ 新建失败: ${escapeHTML(err.message)}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "+ 新分类";  // v4.3.0 修：与 popup.html 初始文案一致（B028 回归 fix）
  }
}

// ---------- 主流程 ----------

async function init() {
  const tab = await getCurrentTab();
  const url = tab.url || "";
  const rawTitle = tab.title || "";
  const cfg = await getConfig();

  // v4：未登录 → 跳 onboarding
  if (!isAuthenticated(cfg)) {
    openOnboarding();
    return;
  }

  // 顶部状态：拉 /api/me 拿用户名 + 检查激活/绑表 + sheet_url
  const endpointHint = document.getElementById("endpoint-hint");
  endpointHint.textContent = "已连接";
  fetch(`${cfg.endpoint}/api/me`, { headers: authHeaders(cfg) })
    .then((r) => {
      if (r.status === 401) {
        // token 失效 → 跳 onboarding
        chrome.storage.local.remove(["jwt"], () => openOnboarding());
        return null;
      }
      return r.ok ? r.json() : null;
    })
    .then((u) => {
      if (!u) return;
      // 状态不完整 → 跳 onboarding 完成
      if (u.needs_activation || u.needs_bind_sheet) {
        openOnboarding();
        return;
      }
      if (u.name) endpointHint.textContent = `👤 ${u.name}`;
      if (u.sheet_url) CACHED_SHEET_URL = u.sheet_url;
    })
    .catch(() => {});

  // 判断当前页是否小红书
  if (!XHS_HOST_RE.test(url)) {
    document.getElementById("not-xhs").style.display = "block";
    document.getElementById("main").style.display = "none";
    return;
  }

  const resolvedNoteUrl = await resolveCurrentNoteUrl(tab);
  AL_STATE.resolvedNoteUrl = resolvedNoteUrl || "";

  // v4.4.0：判断是不是小红书账号主页（/user/profile/xxx）
  // 如果是 → 显示账号库卡片，隐藏笔记收录 UI，但允许用户继续往下看（不强切）
  if (!resolvedNoteUrl && XHS_PROFILE_RE.test(url)) {
    document.getElementById("account-lib-card").style.display = "block";
    // 隐藏笔记收录主区
    document.getElementById("main").style.display = "none";
    // 异步抓账号信息填到卡片 + 预备表单数据
    initAccountLibForCurrentPage(tab, cfg);
    return;
  }

  if (!resolvedNoteUrl && !normalizeXhsNoteUrl(url) && !/xhslink\.com/i.test(url)) {
    document.getElementById("not-xhs").style.display = "block";
    document.getElementById("main").style.display = "none";
    return;
  }

  // 显示页面标题
  const titleEl = document.getElementById("page-title");
  const cleanTitle = cleanXhsTitle(rawTitle);
  if (cleanTitle) {
    titleEl.textContent = cleanTitle;
    titleEl.classList.remove("empty");
  } else {
    titleEl.textContent = "（无标题，正在加载）";
    titleEl.classList.add("empty");
  }

  const collectUrl = resolvedNoteUrl || url;
  document.getElementById("current-url").textContent = collectUrl;

  // 加载分类下拉 + 仪表盘（JWT 或 legacy 都行）
  if (isAuthenticated(cfg)) {
    loadCategories(cfg);
    loadDashboard(cfg);
  }

  // 加载更新日志（独立流程，不阻塞主功能；接口挂掉会自动 fallback 到 mock）
  loadChangelog(cfg).catch((e) => console.warn("changelog 加载异常：", e));

  // 自动检测重复（跨 sheet）
  if (isAuthenticated(cfg)) {
    try {
      const check = await apiCheck(collectUrl, cfg);
      if (check.exists) {
        const dupEl = document.getElementById("dup-hint");
        const safeTitle = escapeHTML(check.sheet_title || "");
        const safeRow = parseInt(check.row, 10) || 0;
        const sheetInfo = safeTitle
          ? `已在「${safeTitle}」第 <b>${safeRow}</b> 行`
          : `原始数据在第 <b>${safeRow}</b> 行`;
        document.getElementById("dup-detail").innerHTML = sheetInfo;
        dupEl.style.display = "block";
      }
    } catch (err) {
      console.warn("check 失败：", err);
    }
  } else {
    // 走到这里说明 init() 顶部已 openOnboarding；这是兜底
    setStatus(
      "error",
      `<div class="title">⚠️ 还没登录</div>
       <div style="margin-top:6px"><a id="goto-onboarding" href="#" style="color:#FF2442">→ 现在去登录</a></div>`
    );
    setTimeout(() => {
      const link = document.getElementById("goto-onboarding");
      if (link) link.addEventListener("click", (e) => {
        e.preventDefault();
        openOnboarding();
      });
    }, 50);
  }
}

async function handleCollect() {
  const tab = await getCurrentTab();
  const tabUrl = tab.url || "";
  let url = normalizeXhsNoteUrl(AL_STATE.resolvedNoteUrl || tabUrl);
  if (!url) {
    url = await resolveCurrentNoteUrl(tab);
    AL_STATE.resolvedNoteUrl = url || "";
  }
  if (!url && /xhslink\.com/i.test(tabUrl)) {
    url = tabUrl;
  }
  const cfg = await getConfig();
  const pref = await getUserPref();
  const note = document.getElementById("note-input").value.trim();
  const sheetId = getSelectedSheetId();
  const tags = [];  // v3.1 取消了标签 chip，全部走分类

  if (!isAuthenticated(cfg)) {
    setStatus("error", "⚠️ 还没登录，跳转到登录页…");
    setTimeout(openOnboarding, 500);
    return;
  }
  if (!sheetId) {
    setStatus("error", "⚠️ 请先选择一个分类（或新建一个）");
    return;
  }
  if (!url) {
    setStatus(
      "error",
      `<div class="title">当前没有识别到可收录的笔记</div>
       <div>请先打开具体笔记页，或在搜索页/主页里点开某篇笔记后再收录。</div>`
    );
    return;
  }
  // 记住这次选的分类
  rememberCategory(sheetId);

  const btn = document.getElementById("btn-collect");
  btn.disabled = true;
  btn.textContent = "⏳ 采集中…";
  setStatus(
    "loading",
    `<div>正在采集 + 写入飞书表…</div><div style="font-size:11px;margin-top:4px;color:#71717A">通常 3-5 秒</div>`
  );

  // v4.3.0 P0 fix（Codex P0-2）：API 调用迁到 background
  // popup 只 send message 让 background 调 API + 弹通知
  // background 用 sendResponse 把结果回传，popup await 拿到后更新 UI
  // 如果 popup 在等待期间关闭：sendResponse 收不到，但 background 已经完成 + 弹通知
  try {
    const bgResp = await new Promise((resolve, reject) => {
      chrome.runtime.sendMessage({
        type: "collect-start",
        source: "Popup",
        payload: { url, note, tags, sheet_id: sheetId, dupStrategy: pref.dupStrategy },
      }, (resp) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message || "background 通信失败"));
        } else {
          resolve(resp);
        }
      });
    });
    // bgResp = { ok: true, data: {...} } 或 { ok: false, error: "..." }
    if (!bgResp || !bgResp.ok) {
      throw new Error((bgResp && bgResp.error) || "收录任务失败");
    }
    const r = bgResp.data;
    // 收录成功/重复/更新 → 清掉仪表盘缓存
    if (["ok", "duplicate", "updated"].includes(r.status)) {
      chrome.storage.local.remove(DASHBOARD_CACHE_KEY);
    }
    if (r.status === "updated") {
      setStatus(
        "success",
        `<div class="title">🔄 已更新第 ${r.row} 行（在「${escapeHTML(r.sheet_title || "")}」）</div>
         <div>${escapeHTML(r.title || "")}</div>
         <div class="meta">
           <span>💖 ${r.liked || 0}</span>
           <span>⭐ ${r.collected || 0}</span>
           <span>💬 ${r.comment || 0}</span>
           <span>📤 ${r.share || 0}</span>
         </div>`
      );
      // v4.3.0: 通知已由 background.performCollect 处理（避免双弹）
      btn.textContent = "🔄 已更新";
      setTimeout(() => {
        btn.disabled = false;
        btn.textContent = "📥 收录到飞书";
      }, 1500);
    } else if (r.status === "ok") {
      setStatus(
        "success",
        `<div class="title">✅ 已收录到第 ${r.row} 行</div>
         <div>${escapeHTML(r.title || "")}</div>
         <div class="meta">
           <span>💖 ${r.liked || 0}</span>
           <span>⭐ ${r.collected || 0}</span>
           <span>💬 ${r.comment || 0}</span>
           <span>📤 ${r.share || 0}</span>
         </div>`
      );
      // v4.3.0: 通知已由 background.performCollect 处理（避免双弹）
      btn.textContent = "✅ 已收录";
      setTimeout(() => {
        btn.disabled = false;
        btn.textContent = "📥 再收录一条";
      }, 1500);
    } else if (r.status === "duplicate") {
      setStatus(
        "duplicate",
        `<div class="title">⏭ 已存在，跳过</div>
         <div>${escapeHTML(r.title || "")}</div>
         <div style="margin-top:4px">原始数据在第 <b>${r.original_row || "?"}</b> 行</div>`
      );
      // v4.3.0: 通知已由 background.performCollect 处理（避免双弹）
      btn.disabled = false;
      btn.textContent = "📥 收录到飞书";
    } else {
      setStatus(
        "error",
        `<div class="title">❌ 采集失败</div>
         <div>${escapeHTML(r.error || "未知错误")}</div>`
      );
      // v4.3.0: 通知已由 background.performCollect 处理
      btn.disabled = false;
      btn.textContent = "🔄 重试";
    }
  } catch (err) {
    setStatus(
      "error",
      `<div class="title">❌ 请求失败</div>
       <div>${escapeHTML(err.message)}</div>
       <div style="font-size:11px;margin-top:4px">检查 endpoint 配置是否正确、服务器是否在线</div>`
    );
    // v4.3.0: 通知已由 background.performCollect 处理（如失败原因是 background 不通则没通知，这是预期）
    btn.disabled = false;
    btn.textContent = "🔄 重试";
  }
}

// 给 background 发通知请求（popup 关了 sendMessage 可能失败，吞掉即可）
// background 收到后会调 chrome.notifications.create 弹系统原生通知
function sendBgNotify(level, title, message) {
  try {
    chrome.runtime.sendMessage({ type: "notify", level, title, message }, () => {
      // 静默丢弃 lastError（popup 关闭场景）
      if (chrome.runtime.lastError) { /* noop */ }
    });
  } catch (e) {
    /* noop */
  }
}

function escapeHTML(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---------- 绑定事件 ----------

document.addEventListener("DOMContentLoaded", () => {
  init();
  document.getElementById("btn-collect").addEventListener("click", handleCollect);
  document.getElementById("btn-open-sheet").addEventListener("click", () => {
    // 优先用 whoami 返回的；fallback 到默认飞书首页
    const target = CACHED_SHEET_URL || SHEET_URL_FALLBACK;
    chrome.tabs.create({ url: target });
  });
  document.getElementById("btn-settings").addEventListener("click", () => {
    // 直接打开新标签页（比 openOptionsPage 更稳）
    chrome.tabs.create({ url: chrome.runtime.getURL("options.html") });
  });
  document.getElementById("btn-logout").addEventListener("click", async () => {
    const ok = await showModal({
      title: "确认退出登录",
      desc: "退出登录会清掉本地 JWT，下次需要重新扫码。继续？",
      mode: "confirm",
      confirmText: "退出",
      cancelText: "取消",
    });
    if (ok) await logout();
  });
  document.getElementById("btn-new-category").addEventListener("click", async () => {
    const cfg = await getConfig();
    handleNewCategory(cfg);
  });
  document.getElementById("category-select").addEventListener("change", (e) => {
    rememberCategory(e.target.value);
  });
  document.getElementById("stat-failed-box").addEventListener("click", async () => {
    const cfg = await getConfig();
    toggleFailureList(cfg);
  });
  document.getElementById("recent-toggle").addEventListener("click", () => {
    const list = document.getElementById("recent-list");
    const icon = document.getElementById("recent-toggle-icon");
    list.classList.toggle("show");
    icon.textContent = list.classList.contains("show") ? "▼" : "▶";
  });
  document.getElementById("link-help").addEventListener("click", (e) => {
    e.preventDefault();
    chrome.tabs.create({ url: chrome.runtime.getURL("help.html") });
  });

  // 铃铛点击：手动打开更新日志弹窗（不管什么版本都弹）
  document.getElementById("btn-changelog").addEventListener("click", async () => {
    const cfg = await getConfig();
    showChangelogModal(await fetchChangelogData(cfg));
  });

  // 「我知道了」按钮：关闭 + 标记已读
  document.getElementById("cl-confirm").addEventListener("click", () => {
    hideChangelogModal();
    markChangelogRead();
  });

  // 点遮罩关闭（点卡片内部不关）
  document.getElementById("cl-overlay").addEventListener("click", (e) => {
    if (e.target.id === "cl-overlay") {
      hideChangelogModal();
      markChangelogRead();
    }
  });
});

// ==================== 更新日志（changelog）模块 ====================
// 此模块独立于其它逻辑，挂在 popup.js 末尾。
// 数据流：fetchChangelogData -> 服务端 /api/changelog（无鉴权）
//        失败 fallback 到内置 MOCK_CHANGELOG
//        启动时 loadChangelog 决定是否自动弹 + 是否亮红点
//        点铃铛永远手动弹；点「我知道了」标记已读

// 本地存储 key：用户已读到的最高版本
const CHANGELOG_READ_KEY = "changelog_read_version";
// 本次会话是否已自动弹过（防止用户关 popup 再开又弹）
let __changelogAutoShown = false;
// 缓存最近一次拿到的服务端版本（供 markChangelogRead 写入）
let __changelogLatestData = null;

// 接口挂掉时的 mock 兜底数据
const MOCK_CHANGELOG = {
  current_latest: "4.1.0",
  items: [
    {
      version: "4.1.0",
      version_type: "minor",
      released_at: "2026-05-23",
      title: "更新日志面板上线",
      details: "## 新增\n- 更新日志面板\n- 加号 bug 修复",
    },
    {
      version: "4.0.0",
      version_type: "major",
      released_at: "2026-05-22",
      title: "OAuth 上线",
      details: "## 重大变更\n- OAuth 自助登录",
    },
  ],
};

// 版本号比较：a > b 返回 1，a < b 返回 -1，相等返回 0，格式错误返回 null
function compareVersion(a, b) {
  if (!a || !b) return null;
  const pa = String(a).split(".").map(Number);
  const pb = String(b).split(".").map(Number);
  if (pa.length < 3 || pb.length < 3) return null;
  if (pa.some(isNaN) || pb.some(isNaN)) return null;
  for (let i = 0; i < 3; i++) {
    if (pa[i] > pb[i]) return 1;
    if (pa[i] < pb[i]) return -1;
  }
  return 0;
}

// 判断版本升级类型：major / minor / patch / null
function bumpType(oldV, newV) {
  if (!oldV || !newV) return null;
  const pa = String(oldV).split(".").map(Number);
  const pb = String(newV).split(".").map(Number);
  if (pa.length < 3 || pb.length < 3) return null;
  if (pa.some(isNaN) || pb.some(isNaN)) return null;
  if (pb[0] > pa[0]) return "major";
  if (pb[1] > pa[1]) return "minor";
  if (pb[2] > pa[2]) return "patch";
  return null;
}

// 读已读版本号
function getReadVersion() {
  return new Promise((resolve) => {
    chrome.storage.local.get([CHANGELOG_READ_KEY], (d) => {
      resolve(d[CHANGELOG_READ_KEY] || "");
    });
  });
}

// 标记已读 = 把最新的服务端版本号写到本地
function markChangelogRead() {
  if (!__changelogLatestData || !__changelogLatestData.current_latest) return;
  chrome.storage.local.set({
    [CHANGELOG_READ_KEY]: __changelogLatestData.current_latest,
  }, () => {
    // 标记后立即把红点关掉
    const dot = document.getElementById("btn-changelog");
    if (dot) dot.classList.remove("has-update");
  });
}

// 拉取 changelog 数据：服务端 → 失败 fallback mock
async function fetchChangelogData(cfg) {
  const endpoint = (cfg && cfg.endpoint) || "http://14.22.112.147:8866";
  try {
    // 注：/api/changelog 无需鉴权，不带 Authorization 头
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    const resp = await fetch(`${endpoint}/api/changelog`, {
      method: "GET",
      signal: controller.signal,
    });
    clearTimeout(timeout);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    // 简单校验结构
    if (!data || !data.current_latest || !Array.isArray(data.items)) {
      throw new Error("响应格式异常");
    }
    __changelogLatestData = data;
    return data;
  } catch (err) {
    console.warn("changelog 接口失败，降级到 mock：", err.message);
    __changelogLatestData = MOCK_CHANGELOG;
    return MOCK_CHANGELOG;
  }
}

// 把简化 markdown 渲染成 HTML（只处理 ## 标题、- 列表、`code`、链接）
function renderChangelogMarkdown(md) {
  if (!md) return "";
  // 先 escape，防 XSS
  let s = String(md)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

  // 行内代码 `xxx`
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  // 链接 [text](url)（只放行 http/https）
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

  // 按行处理：## 标题 + - 列表 + 普通段落
  const lines = s.split(/\r?\n/);
  const out = [];
  let inList = false;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      if (inList) { out.push("</ul>"); inList = false; }
      continue;
    }
    if (/^##\s+/.test(line)) {
      if (inList) { out.push("</ul>"); inList = false; }
      out.push(`<h2>${line.replace(/^##\s+/, "")}</h2>`);
      continue;
    }
    if (/^-\s+/.test(line)) {
      if (!inList) { out.push("<ul>"); inList = true; }
      out.push(`<li>${line.replace(/^-\s+/, "")}</li>`);
      continue;
    }
    if (inList) { out.push("</ul>"); inList = false; }
    out.push(`<div>${line}</div>`);
  }
  if (inList) out.push("</ul>");
  return out.join("");
}

// 渲染并展示弹窗
function showChangelogModal(data) {
  const overlay = document.getElementById("cl-overlay");
  const titleEl = document.getElementById("cl-title");
  const subEl = document.getElementById("cl-subtitle");
  const bodyEl = document.getElementById("cl-body");
  if (!overlay || !data) return;

  const items = Array.isArray(data.items) ? data.items : [];
  const latest = items[0] || {};
  titleEl.textContent = `🎉 v${data.current_latest || latest.version || "?"} 更新内容`;
  subEl.textContent = latest.released_at ? `发布日期：${latest.released_at}` : "";

  if (!items.length) {
    bodyEl.innerHTML = `<div class="cl-empty">暂无更新记录</div>`;
  } else {
    bodyEl.innerHTML = items.map((it) => {
      const vt = (it.version_type || "patch").toLowerCase();
      const badgeCls = (vt === "major" || vt === "minor") ? vt : "patch";
      const badgeText = vt.toUpperCase();
      const dateHtml = it.released_at
        ? `<span class="cl-date">${escapeHTML(it.released_at)}</span>` : "";
      return `
        <div class="cl-item">
          <div class="cl-item-head">
            <span class="cl-version">v${escapeHTML(it.version || "")}</span>
            <span class="cl-badge ${badgeCls}">${escapeHTML(badgeText)}</span>
            ${dateHtml}
          </div>
          <div class="cl-item-title">${escapeHTML(it.title || "")}</div>
          <div class="cl-item-detail">${renderChangelogMarkdown(it.details || "")}</div>
        </div>
      `;
    }).join("");
  }
  overlay.classList.add("show");
}

function hideChangelogModal() {
  const overlay = document.getElementById("cl-overlay");
  if (overlay) overlay.classList.remove("show");
}

// 启动入口：拉数据、决定红点、决定是否自动弹
async function loadChangelog(cfg) {
  const data = await fetchChangelogData(cfg);
  const latest = data && data.current_latest;
  if (!latest) return;

  const readVersion = await getReadVersion();
  const bell = document.getElementById("btn-changelog");

  // 没有 read_version → 当作首次打开，亮红点 + 自动弹
  if (!readVersion) {
    if (bell) bell.classList.add("has-update");
    if (!__changelogAutoShown) {
      __changelogAutoShown = true;
      showChangelogModal(data);
    }
    return;
  }

  // 有 read_version → 比较
  const cmp = compareVersion(latest, readVersion);
  if (cmp === 1) {
    // 服务端更新 → 亮红点
    if (bell) bell.classList.add("has-update");
    // 只在 minor/major bump 时自动弹（patch 只亮红点不打扰）
    const bt = bumpType(readVersion, latest);
    if ((bt === "minor" || bt === "major") && !__changelogAutoShown) {
      __changelogAutoShown = true;
      showChangelogModal(data);
    }
  } else {
    // 已读到最新或更新 → 红点关闭
    if (bell) bell.classList.remove("has-update");
  }
}

// ==================== 重复笔记提示：next action 按钮 ====================
// v4.3.0 P1 fix（Codex 抓到 P1-3）：CACHED_SHEET_URL 可能因 /api/me 还没返回为空
// → 兜底实时查 /api/me，确保不会跳到 my.feishu.cn 通用首页
async function openBoundSheetFresh() {
  // 1. 优先用缓存
  if (CACHED_SHEET_URL) {
    chrome.tabs.create({ url: CACHED_SHEET_URL });
    return;
  }
  // 2. 兜底实时调 /api/me
  try {
    const cfg = await getConfig();
    const r = await fetch(`${cfg.endpoint}/api/me`, { headers: authHeaders(cfg) });
    if (r.ok) {
      const me = await r.json();
      if (me.sheet_url) {
        chrome.tabs.create({ url: me.sheet_url });
        return;
      }
    }
  } catch (e) { /* fallthrough */ }
  // 3. 最后兜底（提示用户而不是跳到通用首页）
  alert("找不到你的飞书表 URL，请去 ⚙️ 设置里查看");
}

document.addEventListener("DOMContentLoaded", () => {
  const btnDupOpen = document.getElementById("btn-dup-open");
  if (btnDupOpen) {
    btnDupOpen.addEventListener("click", openBoundSheetFresh);
  }
  const btnDupSkip = document.getElementById("btn-dup-skip");
  if (btnDupSkip) {
    btnDupSkip.addEventListener("click", () => {
      const dupEl = document.getElementById("dup-hint");
      if (dupEl) dupEl.style.display = "none";
    });
  }
  // v4.3.0 B035 fix：dup-detail 整段（"已在「起号图文」第 6 行"）也可点击跳飞书表
  const dupDetail = document.getElementById("dup-detail");
  if (dupDetail) {
    dupDetail.addEventListener("click", openBoundSheetFresh);
  }
});

chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === "profile_collect_state" && msg.state) {
    renderProfileCollectState(msg.state);
    return;
  }
  if (!msg || msg.type !== "profile_collect_progress") return;
  const found = Number(msg.found || 0);
  const limit = Number(msg.limit || PROFILE_COLLECT_LIMIT);
  const apiReady = Number(msg.api_ready_count || 0);
  const incomplete = Math.max(0, found - apiReady);
  const percent = limit ? Math.min(35, (found / limit) * 35) : 0;
  if (msg.stage === "scan_start") {
    renderProfileProgress({
      title: "第 1 步：开始提取主页链接",
      step: `目标：最多前 ${limit} 篇`,
      detail: `正在读取当前页面里的笔记卡片；完整链接 ${apiReady} 条，短链接 ${incomplete} 条`,
      percent,
    });
    return;
  }
  if (msg.stage === "scanning") {
    renderProfileProgress({
      title: "第 1 步：慢速翻主页",
      step: `已找到 ${found}/${limit} 条链接，已滚动 ${msg.rounds || 0} 次`,
      detail: `完整链接 ${apiReady} 条，短链接 ${incomplete} 条；连续无新增 ${msg.stableRounds || 0} 次；长暂停 ${msg.longPauses || 0} 次`,
      percent,
    });
    return;
  }
  if (msg.stage === "batch_pause") {
    renderProfileProgress({
      title: "第 1 步：风控暂停中",
      step: `已找到 ${found}/${limit} 条链接`,
      detail: `完整链接 ${apiReady} 条，短链接 ${incomplete} 条；暂停约 ${msg.pauseSeconds || 0} 秒后继续滚动`,
      percent,
    });
    return;
  }
  if (msg.stage === "scan_done") {
    renderProfileProgress({
      title: "第 1 步完成：链接提取结束",
      step: `共找到 ${found} 条链接，滚动 ${msg.rounds || 0} 次`,
      detail: msg.reachedLimit
        ? `已达到 400 篇上限；完整链接 ${apiReady} 条，短链接 ${incomplete} 条，准备提交后台采集`
        : `主页看起来已经到底；完整链接 ${apiReady} 条，短链接 ${incomplete} 条，准备提交后台采集`,
      percent: 38,
    });
  }
});

// ============ v4.4.0 对标账号库 ============

// 抓取账号主页字段的函数（被 chrome.scripting.executeScript 注入到目标 tab 执行）
// 必须是 self-contained：内部不能依赖 popup 这边的任何变量/函数
function parseProfileStatsFromText(bodyText) {
  const text = String(bodyText || "").replace(/[,，]/g, "").replace(/\s+/g, " ");
  const numberPattern = "\\d+(?:\\.\\d+)?\\s*(?:万|w|W|m|M|k|K)?";
  const labelPattern = "获赞与收藏|获赞收藏|粉丝|关注|笔记|作品|获赞";
  const profileBlockRe = new RegExp(
    `(${numberPattern})\\s*关注\\s*(${numberPattern})\\s*粉丝\\s*(${numberPattern})\\s*(?:获赞与收藏|获赞收藏|获赞)`,
  );
  const profileBlockMatch = text.match(profileBlockRe);
  if (profileBlockMatch) {
    return {
      follow_count: profileBlockMatch[1].replace(/\s+/g, ""),
      notes_count: "",
      fans_count: profileBlockMatch[2].replace(/\s+/g, ""),
      likes_count: profileBlockMatch[3].replace(/\s+/g, ""),
    };
  }
  const tokenRe = new RegExp(`(${numberPattern})|(${labelPattern})`, "g");
  const tokens = [];
  let m;
  while ((m = tokenRe.exec(text)) !== null) {
    if (m[1]) {
      tokens.push({ type: "number", value: m[1].replace(/\s+/g, "") });
    } else if (m[2]) {
      tokens.push({ type: "label", value: m[2] });
    }
  }

  function keyForLabel(label) {
    if (label === "关注") return "follow_count";
    if (label === "粉丝") return "fans_count";
    if (label === "笔记" || label === "作品") return "notes_count";
    if (label === "获赞与收藏" || label === "获赞收藏" || label === "获赞") {
      return "likes_count";
    }
    return "";
  }

  let numberBeforeLabel = 0;
  let labelBeforeNumber = 0;
  for (let i = 0; i < tokens.length - 1; i += 1) {
    if (tokens[i].type === "number" && tokens[i + 1].type === "label") {
      numberBeforeLabel += 1;
    }
    if (tokens[i].type === "label" && tokens[i + 1].type === "number") {
      labelBeforeNumber += 1;
    }
  }

  const preferNumberBefore = numberBeforeLabel >= labelBeforeNumber;
  const stats = {
    follow_count: "",
    notes_count: "",
    fans_count: "",
    likes_count: "",
  };

  function fillFromNumberBefore(overwrite = false) {
    for (let i = 0; i < tokens.length - 1; i += 1) {
      if (tokens[i].type !== "number" || tokens[i + 1].type !== "label") continue;
      const key = keyForLabel(tokens[i + 1].value);
      if (key && (overwrite || !stats[key])) stats[key] = tokens[i].value;
    }
  }

  function fillFromLabelBefore(overwrite = false) {
    for (let i = 0; i < tokens.length - 1; i += 1) {
      if (tokens[i].type !== "label" || tokens[i + 1].type !== "number") continue;
      const key = keyForLabel(tokens[i].value);
      if (key && (overwrite || !stats[key])) stats[key] = tokens[i + 1].value;
    }
  }

  if (preferNumberBefore) {
    fillFromNumberBefore();
    fillFromLabelBefore();
  } else {
    fillFromLabelBefore();
    fillFromNumberBefore();
  }
  return stats;
}

function extractAccountInfoFromPage() {
  function pickText(selectors) {
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) {
        const t = (el.innerText || el.textContent || "").trim();
        if (t) return t;
      }
    }
    return "";
  }
  function pickAll(selectors) {
    for (const sel of selectors) {
      const els = document.querySelectorAll(sel);
      if (els && els.length > 0) return Array.from(els);
    }
    return [];
  }

  const bodyText = document.body ? (document.body.innerText || "") : "";

  function cleanAccountNameCandidate(value) {
    const text = String(value || "")
      .replace(/\s*[|｜-]\s*小红书.*$/i, "")
      .replace(/的小红书主页.*$/i, "")
      .replace(/小红书.*$/i, "")
      .trim();
    if (!text) return "";
    if (text.length > 40) return "";
    if (/^(首页|搜索|通知|我|笔记|收藏|关注|粉丝|获赞|获赞与收藏|编辑资料)$/.test(text)) return "";
    if (/小红书号|IP\s*属地|关注|粉丝|获赞|笔记/.test(text)) return "";
    if (/^\d+(?:\.\d+)?\s*(?:万|w|W|m|M|k|K)?$/.test(text)) return "";
    return text;
  }

  function inferAccountNameFromText() {
    const titleName = cleanAccountNameCandidate(document.title || "");
    if (titleName) return titleName;
    const lines = String(bodyText || "")
      .split(/[\n\r]+/)
      .map((line) => line.trim())
      .filter(Boolean);
    for (const line of lines.slice(0, 20)) {
      const beforeId = line.split(/小红书号[：:\s]*/)[0];
      const candidate = cleanAccountNameCandidate(beforeId || line);
      if (candidate) return candidate;
    }
    return "";
  }

  // 账号名
  let account_name = pickText([
    ".user-name", ".user-info-name",
    '[class*="user-name"]', '[class*="userName"]',
    '[class*="nickname"]', '[class*="nick-name"]',
    "h1", "h2",
  ]);
  if (!account_name) account_name = inferAccountNameFromText();

  // 简介
  const bio = pickText([
    ".user-desc", ".user-info-desc",
    '[class*="user-desc"]', '[class*="user-content"]',
    ".desc", ".bio",
  ]);

  // 小红书号：文本里搜 "小红书号：xxx"
  let xhs_id = "";
  const idMatch = bodyText.match(/小红书号[：:\s]*([a-zA-Z0-9_\-]+)/);
  if (idMatch) xhs_id = idMatch[1];

  // IP 属地：文本里搜 "IP 属地：xxx"
  let ip_location = "";
  const ipMatch = bodyText.match(/IP\s*[属:址]?\s*地[：:\s]*([^\s\n\r·,，|]+)/);
  if (ipMatch) ip_location = ipMatch[1];

  const profileStats = parseProfileStatsFromText(bodyText);
  const notes_count = profileStats.notes_count || "";
  const fans_count = profileStats.fans_count || "";
  const likes_count = profileStats.likes_count || "";

  return {
    account_name,
    profile_url: location.href,
    xhs_id,
    notes_count,
    fans_count,
    likes_count,
    ip_location,
    bio,
  };
}

async function extractProfileNoteLinksFromPage(options) {
  const cfg = (typeof options === "object" && options) ? options : { limit: options };
  const maxLinks = Math.max(1, Number(cfg.limit || 400));
  const minDelay = Math.max(500, Number(cfg.minDelayMs || 1200));
  const maxDelay = Math.max(minDelay, Number(cfg.maxDelayMs || 2200));
  const batchPauseMin = Math.max(1000, Number(cfg.batchPauseMinMs || 4000));
  const batchPauseMax = Math.max(batchPauseMin, Number(cfg.batchPauseMaxMs || 7000));
  const batchLinks = Math.max(5, Number(cfg.batchLinks || 25));
  const batchRounds = Math.max(3, Number(cfg.batchRounds || 12));
  const seen = new Map();

  function wait(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function randomBetween(min, max) {
    return Math.floor(min + Math.random() * (max - min + 1));
  }

  function emitProgress(stage, detail) {
    try {
      chrome.runtime.sendMessage({
        type: "profile_collect_progress",
        stage,
        ...detail,
      });
    } catch (e) {
      /* popup 关闭时静默 */
    }
  }

  function noteIdFromPath(pathname) {
    const m = pathname.match(/\/(?:explore|discovery\/item)\/([a-zA-Z0-9]+)/);
    return m ? m[1] : "";
  }

  function collectOnce() {
    const anchors = Array.from(document.querySelectorAll(
      'a[href*="/explore/"], a[href*="/discovery/item/"]',
    ));
    for (const a of anchors) {
      const href = a.getAttribute("href") || "";
      if (!href) continue;
      let u = null;
      try {
        u = new URL(href, location.origin);
      } catch (e) {
        continue;
      }
      if (!/xiaohongshu\.com$/i.test(u.hostname)) continue;
      const noteId = noteIdFromPath(u.pathname);
      if (!noteId) continue;
      u.hash = "";
      const fullUrl = u.toString();
      const old = seen.get(noteId);
      if (!old || (!old.includes("xsec_token=") && fullUrl.includes("xsec_token="))) {
        seen.set(noteId, fullUrl);
      }
      if (seen.size >= maxLinks) break;
    }
    return seen.size;
  }

  let lastCount = 0;
  let stableRounds = 0;
  let rounds = 0;
  let lastBatchCount = seen.size;
  let longPauses = 0;
  collectOnce();
  emitProgress("scan_start", {
    found: seen.size,
    limit: maxLinks,
    rounds,
  });
  while (seen.size < maxLinks && stableRounds < 10 && rounds < 220) {
    rounds += 1;
    const step = Math.max(
      420,
      Math.floor(window.innerHeight * (0.72 + Math.random() * 0.18)),
    );
    window.scrollBy(0, step);
    await wait(randomBetween(minDelay, maxDelay));
    const count = collectOnce();
    if (count === lastCount) {
      stableRounds += 1;
    } else {
      stableRounds = 0;
      lastCount = count;
    }
    if (rounds === 1 || rounds % 3 === 0) {
      emitProgress("scanning", {
        found: seen.size,
        limit: maxLinks,
        rounds,
        stableRounds,
        longPauses,
      });
    }
    if (
      seen.size < maxLinks &&
      (
        seen.size - lastBatchCount >= batchLinks ||
        rounds % batchRounds === 0
      )
    ) {
      longPauses += 1;
      lastBatchCount = seen.size;
      const pauseMs = randomBetween(batchPauseMin, batchPauseMax);
      emitProgress("batch_pause", {
        found: seen.size,
        limit: maxLinks,
        rounds,
        longPauses,
        pauseSeconds: Math.round(pauseMs / 1000),
      });
      await wait(pauseMs);
    }
  }

  collectOnce();
  const note_urls = Array.from(seen.values()).slice(0, maxLinks);
  emitProgress("scan_done", {
    found: note_urls.length,
    limit: maxLinks,
    rounds,
    longPauses,
    reachedLimit: note_urls.length >= maxLinks,
  });
  return {
    note_urls,
    total_found: seen.size,
    returned: note_urls.length,
    reached_limit: note_urls.length >= maxLinks,
    scroll_rounds: rounds,
    long_pauses: longPauses,
  };
}

async function apiAccountLibMeta(cfg) {
  const resp = await fetch(`${cfg.endpoint}/api/account-lib/meta`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function apiAccountLibAdd(payload, cfg) {
  const resp = await fetch(`${cfg.endpoint}/api/account-lib/add`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(cfg),
    },
    body: JSON.stringify(payload),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
  return data;
}

async function apiProfileCollect(payload, cfg) {
  const resp = await fetch(`${cfg.endpoint}/api/profile-collect`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(cfg),
    },
    body: JSON.stringify(payload),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
  return data;
}

async function apiProfileCollectTask(taskId, cfg) {
  const resp = await fetch(`${cfg.endpoint}/api/profile-collect/tasks/${taskId}`, {
    method: "GET",
    headers: authHeaders(cfg),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
  return data;
}

function showProfileCollectStatus(type, html) {
  const el = document.getElementById("profile-collect-status");
  if (!el) return;
  el.className = `profile-collect-status ${type}`;
  el.innerHTML = html;
}

function profileIdFromUrl(url) {
  try {
    const parsed = new URL(url);
    const match = parsed.pathname.match(/\/user\/profile\/([^/?#]+)/);
    return match ? match[1] : "";
  } catch (e) {
    return "";
  }
}

function isProfileStateForCurrentPage(state) {
  if (!state || !state.profile_url) return false;
  const current = AL_STATE.scrapedData?.profile_url || "";
  const currentId = profileIdFromUrl(current);
  const stateId = profileIdFromUrl(state.profile_url);
  return currentId && stateId && currentId === stateId;
}

function profilePhaseText(state) {
  const phase = state.phase || "";
  if (phase === "link_scan") return "第 1 步：慢速提取完整链接";
  if (phase === "backend_submit") return "第 2 步：提交服务器任务";
  if (phase === "playlist_extract") return "第 3 步：服务器尝试主页批量接口";
  if (phase === "api_extract") return "第 3 步：服务器逐篇调用单篇 API";
  if (phase === "feishu_prepare") return "第 4 步：创建或检查飞书表";
  if (phase === "feishu_write") return "第 5 步：写入飞书表";
  if (phase === "done") return "完成：已写入飞书";
  if (phase === "failed") return "采集失败";
  return "账号全采集中";
}

function renderProfileCollectState(state) {
  if (!isProfileStateForCurrentPage(state)) return;
  const status = state.status || "running";
  const totalLimit = Number(state.total_limit || PROFILE_COLLECT_LIMIT);
  const found = Number(state.found || state.link_result?.returned || 0);
  const total = Number(state.total || state.backend_task?.total || found || totalLimit || 1);
  const processed = Number(state.processed || state.backend_task?.processed || 0);
  const success = Number(state.success || state.backend_task?.success || 0);
  const failed = Number(state.failed || state.backend_task?.failed || 0);
  const written = Number(state.written || state.backend_task?.written || 0);
  const skipped = Number(state.skipped || state.backend_task?.skipped || 0);
  const checkpointSaved = Number(state.checkpoint_saved || state.link_result?.checkpoint_saved || 0);
  const partialSaved = Number(state.partial_saved || state.backend_task?.partial_saved || 0);
  const apiReadyCount = Number(state.api_ready_count || state.link_result?.api_ready_count || 0);
  const incompleteLinkCount = Number(state.incomplete_link_count || state.link_result?.incomplete_link_count || 0);
  const phase = state.phase || "";
  const collectMode = state.collect_mode || state.backend_task?.collect_mode || (apiReadyCount ? "single_post" : "playlist");
  let percent = 5;
  if (phase === "link_scan") percent = Math.min(38, (found / Math.max(1, totalLimit)) * 38);
  else if (phase === "backend_submit") percent = 42;
  else if (phase === "playlist_extract") percent = 58;
  else if (phase === "api_extract") percent = 42 + (processed / Math.max(1, total)) * 38;
  else if (phase === "feishu_prepare") percent = 84;
  else if (phase === "feishu_write") percent = 92;
  else if (status === "done") percent = 100;

  if (status === "failed") {
    showProfileCollectStatus(
      "error",
      `<div><b>${escapeHTML(profilePhaseText(state))}</b></div>
       <div class="profile-step">失败位置：${escapeHTML(profilePhaseText({ phase }))}</div>
       <div class="profile-step">主页返回 ${total || found} 条；已处理 ${processed}/${total}，成功 ${success}，失败 ${failed}，已落表 ${partialSaved || written} 条</div>
       <div class="profile-step">完整链接 ${apiReadyCount} 条；短链接 ${incompleteLinkCount} 条</div>
       <div class="profile-step">原因：${escapeHTML(state.error || state.message || "未知错误")}</div>
       ${renderProfileFailures(state.failed_examples || state.backend_task?.failed_examples)}
       ${profileProgressBar(percent)}`,
    );
    return;
  }

  if (status === "done") {
    const sheetTitle = state.sheet_title || state.backend_task?.sheet_title || "账号全采集";
    const doneDetail = collectMode === "single_post"
      ? `完整链接 ${apiReadyCount || success} 条；API 成功 ${success} 条，失败 ${failed} 条。`
      : `主页接口返回 ${total || success} 条；API 成功 ${success} 条，失败 ${failed} 条。`;
    const openButton = state.sheet_url
      ? `<button id="profile-open-sheet-direct" class="btn-mini" style="width:auto;height:28px;margin-top:8px;padding:0 10px;font-size:12px">打开飞书表</button>`
      : `<button id="profile-open-sheet" class="btn-mini" style="width:auto;height:28px;margin-top:8px;padding:0 10px;font-size:12px">打开飞书表</button>`;
    showProfileCollectStatus(
      "success",
      `<div><b>完成：已写入「${escapeHTML(sheetTitle)}」</b></div>
       <div class="profile-step">${escapeHTML(doneDetail)}</div>
       <div class="profile-step">新增 ${written} 条，跳过重复 ${skipped} 条。</div>
	       ${profileProgressBar(100)}
	       ${renderProfileFailures(state.failed_examples || state.backend_task?.failed_examples)}
	       ${openButton}`,
    );
    const directBtn = document.getElementById("profile-open-sheet-direct");
    if (directBtn) directBtn.addEventListener("click", () => chrome.tabs.create({ url: state.sheet_url }));
    const openBtn = document.getElementById("profile-open-sheet");
    if (openBtn) openBtn.addEventListener("click", openBoundSheetFresh);
    return;
  }

  const linkDetail = phase === "link_scan"
    ? `已找到 ${found}/${totalLimit} 条链接，完整链接 ${apiReadyCount} 条，短链接 ${incompleteLinkCount} 条；已保存 ${checkpointSaved} 条；已滚动 ${state.scroll_rounds || 0} 次；长暂停 ${state.long_pauses || 0} 次`
    : (collectMode === "single_post"
      ? `完整链接 ${apiReadyCount || total} 条；已处理 ${processed}/${total || totalLimit}，成功 ${success}，失败 ${failed}，已落表 ${partialSaved || written} 条`
      : `主页接口目标 ${total || totalLimit} 条；已处理 ${processed}/${total || totalLimit}，成功 ${success}，失败 ${failed}，已落表 ${partialSaved || written} 条`);
  const note = phase === "link_scan"
    ? "这一段在页面里慢速滚动，弹窗关闭后仍会继续。"
    : (state.message || "后台任务运行中，关闭弹窗后可重新打开查看进度。");
  showProfileCollectStatus(
    "loading",
    `<div><b>${escapeHTML(profilePhaseText(state))}</b></div>
     <div class="profile-step">${escapeHTML(linkDetail)}</div>
     <div class="profile-step">${escapeHTML(note)}</div>
     ${profileProgressBar(percent)}
     ${renderProfileFailures(state.failed_examples || state.backend_task?.failed_examples)}`,
  );
}

function backendTaskToProfileState(state, task) {
  const phase = task.phase || (task.status === "done" ? "done" : "playlist_extract");
  return {
    ...(state || {}),
    status: task.status || state?.status || "running",
    phase,
    backend_task: task,
    task_id: task.task_id || state?.task_id || "",
    collect_mode: task.collect_mode || state?.collect_mode || "",
    total: task.total || state?.total || 0,
    processed: task.processed || 0,
    success: task.success || 0,
    failed: task.failed || 0,
    written: task.written || 0,
    skipped: task.skipped || 0,
    api_ready_count: state?.api_ready_count || state?.link_result?.api_ready_count || 0,
    incomplete_link_count: state?.incomplete_link_count || state?.link_result?.incomplete_link_count || 0,
    failed_examples: task.failed_examples || [],
    sheet_title: task.sheet_title || state?.sheet_title || "",
    sheet_id: task.sheet_id || state?.sheet_id || "",
    sheet_url: task.sheet_url || state?.sheet_url || "",
    created_sheet: task.created_sheet,
    error: task.error || "",
    message: task.message || state?.message || "",
    finished_at: task.finished_at || state?.finished_at || "",
    updated_at: new Date().toISOString(),
  };
}

async function persistProfileCollectState(state) {
  await new Promise((resolve) =>
    chrome.storage.local.set({ [PROFILE_COLLECT_STATE_KEY]: state }, resolve));
  renderProfileCollectState(state);
}

function scheduleProfileCollectPoll(state, cfg) {
  if (PROFILE_COLLECT_POLL_TIMER) clearTimeout(PROFILE_COLLECT_POLL_TIMER);
  if (!state || !state.task_id) return;
  if (!(state.status === "queued" || state.status === "running")) return;
  PROFILE_COLLECT_POLL_TIMER = setTimeout(async () => {
    try {
      const task = await apiProfileCollectTask(state.task_id, cfg);
      const merged = backendTaskToProfileState(state, task);
      await persistProfileCollectState(merged);
      scheduleProfileCollectPoll(merged, cfg);
    } catch (e) {
      const merged = {
        ...state,
        message: `查询后台进度失败：${e.message || e}`,
        updated_at: new Date().toISOString(),
      };
      await persistProfileCollectState(merged);
      scheduleProfileCollectPoll(merged, cfg);
    }
  }, 2500);
}

async function restoreProfileCollectStateForCurrentPage(cfg) {
  try {
    const resp = await sendRuntimeMessage({ type: "profile_collect_get_state" });
    const state = resp.state;
    if (!state || !isProfileStateForCurrentPage(state)) return;
    renderProfileCollectState(state);
    scheduleProfileCollectPoll(state, cfg);
  } catch (e) {
    chrome.storage.local.get([PROFILE_COLLECT_STATE_KEY], (data) => {
      const state = data[PROFILE_COLLECT_STATE_KEY];
      if (!state || !isProfileStateForCurrentPage(state)) return;
      renderProfileCollectState(state);
      scheduleProfileCollectPoll(state, cfg);
    });
  }
}

function profileProgressBar(percent) {
  const value = Math.max(0, Math.min(100, Math.round(Number(percent || 0))));
  return `<div class="profile-progress"><div class="profile-progress-bar" style="width:${value}%"></div></div>`;
}

function renderProfileProgress({ title, step, detail = "", percent = 0,
                                 extra = "" }) {
  showProfileCollectStatus(
    "loading",
    `<div><b>${escapeHTML(title)}</b></div>
     <div class="profile-step">${escapeHTML(step)}</div>
     ${detail ? `<div class="profile-step">${escapeHTML(detail)}</div>` : ""}
     ${profileProgressBar(percent)}
     ${extra}`,
  );
}

function renderProfileFailures(failures) {
  const items = Array.isArray(failures) ? failures.slice(0, 3) : [];
  if (!items.length) return "";
  const lines = items.map((item) => {
    const err = item && item.error ? item.error : "未知错误";
    return `<div>失败：${escapeHTML(err)}</div>`;
  }).join("");
  return `<div class="profile-failures">${lines}</div>`;
}

// 全局状态（让初始化/提交共享）
const AL_STATE = {
  cfg: null,
  tabId: null,
  meta: null,            // {account_types, categories, styles}
  scrapedData: null,     // 抓到的账号字段
  resolvedNoteUrl: "",   // 当前页里实际打开的笔记链接（兼容主页/搜索页弹出的笔记浮层）
  selectedType: "",      // 当前选中的账号类型
  selectedCategories: [],
  selectedStyles: [],
};

async function initAccountLibForCurrentPage(tab, cfg) {
  AL_STATE.cfg = cfg;
  AL_STATE.tabId = tab.id;

  // 1. 拉 meta（预设清单）
  try {
    AL_STATE.meta = await apiAccountLibMeta(cfg);
  } catch (e) {
    console.warn("拉 meta 失败：", e);
    AL_STATE.meta = {
      account_types: ["潜力店铺", "爆款跟品"],
      categories: ["饰品", "穿搭", "美妆", "生活", "美食", "母婴", "数码", "家居"],
      styles: ["大字报", "真人种草", "攻略型", "带货", "测评", "干货", "故事型"],
    };
  }

  // 2. 抓账号主页字段（executeScript 注入）
  let scraped = null;
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: extractAccountInfoFromPage,
    });
    if (results && results[0] && results[0].result) {
      scraped = results[0].result;
    }
  } catch (e) {
    console.warn("抓页面失败：", e);
  }
  AL_STATE.scrapedData = scraped || { profile_url: tab.url || "" };

  // 3. 填卡片显示
  document.getElementById("al-detected-name").textContent =
    AL_STATE.scrapedData.account_name || "（未抓到，可手动填）";
  document.getElementById("al-detected-fans").textContent =
    AL_STATE.scrapedData.fans_count || "?";
  document.getElementById("al-detected-likes").textContent =
    AL_STATE.scrapedData.likes_count || "?";
  document.getElementById("al-detected-notes").textContent =
    AL_STATE.scrapedData.notes_count || "?";

  // 4. 绑定按钮
  const btn = document.getElementById("btn-open-al-modal");
  btn.onclick = openAccountLibModal;
  const collectBtn = document.getElementById("btn-profile-collect");
  if (collectBtn) collectBtn.onclick = handleProfileCollect;
  restoreProfileCollectStateForCurrentPage(cfg);
}

async function handleProfileCollect() {
  const cfg = AL_STATE.cfg || await getConfig();
  const data = AL_STATE.scrapedData || {};
  const profileUrl = (data.profile_url || "").trim();
  const accountName = (data.account_name || "").trim();

  if (!profileUrl) {
    showProfileCollectStatus("error", "未抓到账号主页链接，请刷新页面后重试");
    return;
  }

  const ok = await showModal({
    title: "采集这个账号图文？",
    desc: `会先慢速提取完整笔记链接，再逐篇调用 API，最多采集前 ${PROFILE_COLLECT_LIMIT} 篇图文，包含标题、文案、话题标签和图片链接。`,
    mode: "confirm",
    confirmText: "开始采集",
    cancelText: "取消",
  });
  if (!ok) return;

  const btn = document.getElementById("btn-profile-collect");
  const oldText = btn ? btn.textContent : "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "后台启动中…";
  }
  showProfileCollectStatus(
    "loading",
    `<div><b>正在交给后台任务</b></div>
     <div class="profile-step">会先提取完整链接，再调用 API 并写入飞书；弹窗关闭后也能继续。</div>
     ${profileProgressBar(2)}`,
  );

  try {
    if (!AL_STATE.tabId) {
      throw new Error("未找到当前小红书主页标签页，请刷新后重试");
    }
    const resp = await sendRuntimeMessage({
      type: "profile_collect_start",
      payload: {
        tab_id: AL_STATE.tabId,
        profile_url: profileUrl,
        account_name: accountName,
      },
    });
    if (!resp || !resp.ok) {
      throw new Error(resp?.error || "后台任务启动失败");
    }
    if (resp.state) {
      renderProfileCollectState(resp.state);
      scheduleProfileCollectPoll(resp.state, cfg);
    } else {
      showProfileCollectStatus(
        "loading",
        `<div><b>后台任务已启动</b></div>
         <div class="profile-step">正在调用主页批量接口，弹窗关闭后可以重新打开查看。</div>
         ${profileProgressBar(5)}`,
      );
    }
  } catch (e) {
    showProfileCollectStatus(
      "error",
      `采集失败：${escapeHTML(e.message || "未知错误")}`,
    );
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldText;
    }
  }
}

function openAccountLibModal() {
  const meta = AL_STATE.meta;
  const data = AL_STATE.scrapedData || {};

  // 渲染账号类型 radio
  const typeGroup = document.getElementById("al-type-group");
  typeGroup.innerHTML = "";
  meta.account_types.forEach((t) => {
    const btn = document.createElement("div");
    btn.className = "al-radio-btn";
    btn.textContent = t;
    btn.onclick = () => {
      typeGroup.querySelectorAll(".al-radio-btn").forEach((b) =>
        b.classList.remove("active"));
      btn.classList.add("active");
      AL_STATE.selectedType = t;
    };
    typeGroup.appendChild(btn);
  });

  // 渲染品类多选
  const catGroup = document.getElementById("al-cat-group");
  catGroup.innerHTML = "";
  AL_STATE.selectedCategories = [];
  meta.categories.forEach((c) => {
    const tag = document.createElement("div");
    tag.className = "al-tag";
    tag.textContent = c;
    tag.onclick = () => {
      tag.classList.toggle("active");
      if (tag.classList.contains("active")) {
        AL_STATE.selectedCategories.push(c);
      } else {
        AL_STATE.selectedCategories =
          AL_STATE.selectedCategories.filter((x) => x !== c);
      }
    };
    catGroup.appendChild(tag);
  });

  // 渲染风格多选
  const styleGroup = document.getElementById("al-style-group");
  styleGroup.innerHTML = "";
  AL_STATE.selectedStyles = [];
  meta.styles.forEach((s) => {
    const tag = document.createElement("div");
    tag.className = "al-tag";
    tag.textContent = s;
    tag.onclick = () => {
      tag.classList.toggle("active");
      if (tag.classList.contains("active")) {
        AL_STATE.selectedStyles.push(s);
      } else {
        AL_STATE.selectedStyles =
          AL_STATE.selectedStyles.filter((x) => x !== s);
      }
    };
    styleGroup.appendChild(tag);
  });

  // 填抓到的字段到表单
  document.getElementById("al-name-input").value = data.account_name || "";
  document.getElementById("al-xhsid-input").value = data.xhs_id || "";
  document.getElementById("al-ip-input").value = data.ip_location || "";
  document.getElementById("al-notes-input").value = data.notes_count || "";
  document.getElementById("al-fans-input").value = data.fans_count || "";
  document.getElementById("al-likes-input").value = data.likes_count || "";
  document.getElementById("al-bio-input").value = data.bio || "";
  document.getElementById("al-note-input").value = "";
  // 隐藏 result
  const resEl = document.getElementById("al-result");
  resEl.style.display = "none";
  resEl.className = "al-result";

  // 显示 modal
  document.getElementById("al-modal-overlay").classList.add("show");

  // 绑定按钮（每次绑新 handler，确保 state 清新）
  document.getElementById("al-cancel-btn").onclick = closeAccountLibModal;
  document.getElementById("al-submit-btn").onclick = submitAccountLib;
}

function closeAccountLibModal() {
  document.getElementById("al-modal-overlay").classList.remove("show");
}

function showAlResult(type, text) {
  const el = document.getElementById("al-result");
  el.className = "al-result " + type;
  el.textContent = text;
  el.style.display = "block";
}

async function submitAccountLib() {
  const submitBtn = document.getElementById("al-submit-btn");
  const originalText = submitBtn.textContent;
  submitBtn.disabled = true;
  submitBtn.textContent = "提交中…";

  try {
    // 校验
    if (!AL_STATE.selectedType) {
      showAlResult("error", "请选账号类型");
      return;
    }
    const accountName = document.getElementById("al-name-input").value.trim();
    if (!accountName) {
      showAlResult("error", "账号名不能为空");
      return;
    }
    const profileUrl = (AL_STATE.scrapedData?.profile_url || "").trim();
    if (!profileUrl) {
      showAlResult("error", "未抓到主页 URL，请刷新页面重试");
      return;
    }

    const payload = {
      account_type: AL_STATE.selectedType,
      account_name: accountName,
      profile_url: profileUrl,
      xhs_id: document.getElementById("al-xhsid-input").value.trim(),
      notes_count: document.getElementById("al-notes-input").value.trim(),
      fans_count: document.getElementById("al-fans-input").value.trim(),
      likes_count: document.getElementById("al-likes-input").value.trim(),
      ip_location: document.getElementById("al-ip-input").value.trim(),
      bio: document.getElementById("al-bio-input").value.trim(),
      categories: AL_STATE.selectedCategories,
      styles: AL_STATE.selectedStyles,
      note: document.getElementById("al-note-input").value.trim(),
    };

    const result = await apiAccountLibAdd(payload, AL_STATE.cfg);

    if (result.duplicate) {
      showAlResult(
        "duplicate",
        `⚠️ 已在「${result.existing_sheet}」第 ${result.existing_row} 行，未重复入库`,
      );
    } else {
      showAlResult(
        "success",
        `✅ 已加入「${result.sheet_title}」第 ${result.row} 行`,
      );
      // 2 秒后自动关闭
      setTimeout(closeAccountLibModal, 2000);
    }
  } catch (e) {
    showAlResult("error", "❌ " + (e.message || "提交失败"));
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = originalText;
  }
}

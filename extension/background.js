// background.js — service worker
// 职责：
//   1. 注册右键菜单「收录这条小红书笔记」
//   2. 监听标签页切换/更新，调 /api/check 在扩展图标上显示徽标（✓ 已收录 / 空 = 未收录）
// 注意：先 importScripts secrets.js（提供 XHS_API_ENDPOINT 和 XHS_API_TOKEN 常量）

try {
  importScripts("secrets.js");
} catch (e) {
  console.error("secrets.js 加载失败：", e);
}

const XHS_HOST_RE = /(?:xiaohongshu\.com|xhslink\.com)/i;

// v4.3.0 P0 fix: dist 包不含 secrets.js，secrets 常量在生产 zip 是 undefined
// 必须有硬编码 fallback，否则快捷键收录的 fetch URL 是空串
const DEFAULT_ENDPOINT = "http://14.22.112.147:8866";
const PROFILE_COLLECT_STATE_KEY = "profileCollectState";
const PROFILE_COLLECT_CHECKPOINTS_KEY = "profileCollectCheckpoints";
const PROFILE_COLLECT_LIMIT = 400;
const PROFILE_COLLECT_CHECKPOINT_BATCH_SIZE = 80;
const PROFILE_SCROLL_MIN_DELAY_MS = 1200;
const PROFILE_SCROLL_MAX_DELAY_MS = 2200;
const PROFILE_SCROLL_BATCH_PAUSE_MIN_MS = 4000;
const PROFILE_SCROLL_BATCH_PAUSE_MAX_MS = 7000;
const PROFILE_SCROLL_BATCH_LINKS = 25;
const PROFILE_SCROLL_BATCH_ROUNDS = 12;
let __profileCollectPollTimer = null;

async function getConfig() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["endpoint", "authToken", "jwt"], (data) => {
      resolve({
        endpoint: data.endpoint || (typeof XHS_API_ENDPOINT !== "undefined" ? XHS_API_ENDPOINT : DEFAULT_ENDPOINT),
        authToken: data.authToken || (typeof XHS_API_TOKEN !== "undefined" ? XHS_API_TOKEN : ""),
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

// ---------- v4 OAuth 自动接收 token ----------
// 监听 callback 回调 URL（/auth/done?token=xxx），自动收 JWT、关闭 tab、切到 onboarding
// 这样用户扫码后无需手动复制粘贴 Token

// 期望的 OAuth 回调来源（必须严格匹配，避免恶意页面伪造 token 覆盖 storage）
const OAUTH_DONE_HOSTNAME = "14.22.112.147";
const OAUTH_DONE_PORT = "8866";
const OAUTH_DONE_PATHNAME = "/auth/done";
// JWT 格式：三段 base64url 用 . 分隔（防御伪造的非 JWT 值写入 storage）
const JWT_FORMAT = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/;

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete") return;
  const url = tab.url || "";
  if (!url) return;
  let parsed;
  try {
    parsed = new URL(url);
  } catch (e) {
    return;
  }
  // 严格校验：协议 + 域 + 端口 + 路径完全匹配
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return;
  if (parsed.hostname !== OAUTH_DONE_HOSTNAME) return;
  if (parsed.port !== OAUTH_DONE_PORT) return;
  if (parsed.pathname !== OAUTH_DONE_PATHNAME) return;
  const jwt = parsed.searchParams.get("token");
  if (!jwt) return;
  if (!JWT_FORMAT.test(jwt)) {
    console.warn("[xhs-collect] 收到 /auth/done 但 token 不是合法 JWT 格式，已拒绝写入");
    return;
  }
  handleOAuthDone(tabId, jwt);
});

async function handleOAuthDone(callbackTabId, jwt) {
  // 1. 存 JWT 到 storage
  await new Promise((r) => chrome.storage.local.set({ jwt }, r));
  console.log("[xhs-collect] OAuth JWT 已收，跳到 onboarding");

  // 2. 找到 onboarding tab（如已开）→ 激活并刷新；否则新开
  const onboardingUrl = chrome.runtime.getURL("onboarding.html");
  chrome.tabs.query({}, (tabs) => {
    const obTab = tabs.find((t) => t.url && t.url.startsWith(onboardingUrl));
    if (obTab) {
      chrome.tabs.update(obTab.id, { active: true });
      chrome.tabs.reload(obTab.id);
    } else {
      chrome.tabs.create({ url: onboardingUrl, active: true });
    }
    // 3. 关闭 callback tab（延迟 800ms 让用户看到「正在返回扩展」提示）
    setTimeout(() => {
      chrome.tabs.remove(callbackTabId).catch(() => {});
    }, 800);
  });
}

// ---------- 右键菜单 ----------

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "xhs-collect-here",
    title: "📥 收录这条小红书笔记到飞书",
    contexts: ["page", "link"],
    documentUrlPatterns: [
      "https://www.xiaohongshu.com/*",
      "https://xhslink.com/*",
    ],
    targetUrlPatterns: [
      "https://www.xiaohongshu.com/*",
      "https://xhslink.com/*",
    ],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "xhs-collect-here") return;
  const url = info.linkUrl || info.pageUrl || (tab && tab.url);
  if (!url || !XHS_HOST_RE.test(url)) return;
  const cfg = await getConfig();
  if (!isAuthenticated(cfg)) {
    notify("⚠️ 未配置 auth token", "点扩展图标 → 设置页填写", "error");
    return;
  }
  try {
    notify("⏳ 采集中…", url.slice(0, 80), "loading");
    const resp = await fetch(`${cfg.endpoint}/api/collect`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(cfg),
        },
      body: JSON.stringify({ url, source: "RightClick" }),
    });
    const data = await resp.json();
    if (data.status === "ok") {
      notify(`✅ 已收录《${data.title || ""}》`,
        `💖 ${data.liked} · ⭐ ${data.collected} · 💬 ${data.comment}`,
        "success");
      // 更新 badge
      if (tab && tab.id) chrome.action.setBadgeText({ tabId: tab.id, text: "✓" });
    } else if (data.status === "duplicate") {
      notify(`⏭ 已存在《${data.title || ""}》`,
        `在第 ${data.original_row} 行`, "duplicate");
    } else {
      notify("❌ 采集失败", data.error || "未知错误", "error");
    }
  } catch (err) {
    notify("❌ 请求失败", String(err.message || err), "error");
  }
});

// ---------- 自动重复检测：tab 变化时更新 badge ----------

async function updateBadgeForTab(tabId, url) {
  if (!url || !XHS_HOST_RE.test(url)) {
    chrome.action.setBadgeText({ tabId, text: "" });
    return;
  }
  const cfg = await getConfig();
  if (!isAuthenticated(cfg)) return;
  try {
    const params = new URLSearchParams({ url });
    const resp = await fetch(`${cfg.endpoint}/api/check?${params}`, {
      headers: authHeaders(cfg),
    });
    if (!resp.ok) return;
    const data = await resp.json();
    if (data.exists) {
      chrome.action.setBadgeText({ tabId, text: "✓" });
      chrome.action.setBadgeBackgroundColor({ tabId, color: "#16A34A" });
    } else {
      chrome.action.setBadgeText({ tabId, text: "" });
    }
  } catch (err) {
    /* 静默失败，不打扰用户 */
  }
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && tab.url) {
    updateBadgeForTab(tabId, tab.url);
  }
});

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  if (tab && tab.url) updateBadgeForTab(tabId, tab.url);
});

// ---------- 通知（Chrome notifications API 需 permissions: ["notifications"]，这里用 storage 临时保存） ----------

function notify(title, body, type) {
  // Service Worker 不能直接弹 toast；用 storage 保存最近一次结果，popup 打开时显示
  chrome.storage.local.set({
    lastNotification: {
      title, body, type, ts: Date.now(),
    },
  });
  // 同时给扩展图标加个一闪即逝的角标提示
  chrome.action.setBadgeText({ text: type === "success" ? "+1" : "!" });
  setTimeout(() => chrome.action.setBadgeText({ text: "" }), 2500);
}

// ==================== chrome.notifications 工具函数（v4.3 新增） ====================
// 与上面的 notify() 区别：这套走系统原生通知（manifest 需 notifications 权限），
// 即使 popup 关了也能弹；专供快捷键收录 + popup 关后异步反馈使用。
function makeNotification(level, title, message) {
  const iconUrl = chrome.runtime.getURL("icons/icon-128.png");
  try {
    chrome.notifications.create({
      type: "basic",
      iconUrl,
      title: String(title || ""),
      message: String(message || ""),
      priority: level === "error" ? 2 : 1,
    });
  } catch (e) {
    console.error("[xhs-collect] chrome.notifications.create 失败：", e);
  }
}
function notifySuccess(title, message) { makeNotification("success", title, message); }
function notifyError(title, message) { makeNotification("error", title, message); }
function notifyInfo(title, message) { makeNotification("info", title, message); }

// v4.3.0 P1 fix（Codex P1-1）：notification 点击 → 打开飞书表
// 把 notificationId → sheet_url 的映射存内存（service worker 重启会丢，但通知本身也会消失）
const __notificationTargets = new Map();

function createNotificationWithTarget(level, title, message, targetUrl) {
  const iconUrl = chrome.runtime.getURL("icons/icon-128.png");
  try {
    chrome.notifications.create({
      type: "basic",
      iconUrl,
      title: String(title || ""),
      message: String(message || ""),
      priority: level === "error" ? 2 : 1,
    }, (notificationId) => {
      if (notificationId && targetUrl) {
        __notificationTargets.set(notificationId, targetUrl);
        // 5 分钟后自动清理（防内存泄漏）
        setTimeout(() => __notificationTargets.delete(notificationId), 5 * 60 * 1000);
      }
    });
  } catch (e) {
    console.error("[xhs-collect] chrome.notifications.create 失败：", e);
  }
}

chrome.notifications.onClicked.addListener((notificationId) => {
  const targetUrl = __notificationTargets.get(notificationId);
  if (targetUrl) {
    chrome.tabs.create({ url: targetUrl });
    __notificationTargets.delete(notificationId);
  }
  // 点了就关闭通知
  chrome.notifications.clear(notificationId);
});

// v4.3.0 P0 fix（Codex P0-2）：popup 关闭后通知不触发
// 把整个收录调用迁到 background，popup 仅"启动任务 + 等结果回推"
// 这样无论 popup 是否关闭，background 都能完成 API 调用并弹通知
async function performCollect(payload, sourceTag) {
  const cfg = await getConfig();
  if (!isAuthenticated(cfg)) {
    notifyError("收录失败", "请先在扩展里完成 onboarding");
    return { ok: false, error: "未登录" };
  }
  try {
    const resp = await fetch(`${cfg.endpoint}/api/collect`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders(cfg) },
      body: JSON.stringify({
        url: payload.url,
        note: payload.note || "",
        tags: payload.tags || [],
        source: sourceTag || "Popup",
        sheet_id: payload.sheet_id,
        dupStrategy: payload.dupStrategy,
      }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);

    // 弹通知（点击打开飞书表）
    // 先实时查 /api/me 拿 sheet_url（兜底）
    let sheetUrl = "";
    try {
      const meR = await fetch(`${cfg.endpoint}/api/me`, { headers: authHeaders(cfg) });
      if (meR.ok) sheetUrl = (await meR.json()).sheet_url || "";
    } catch (e) { /* noop */ }

    if (data.status === "ok") {
      createNotificationWithTarget("success", "✅ 小红书笔记已收录",
        `第 ${data.row || "?"} 行（「${data.sheet_title || "分类"}」）：${data.title || ""}`,
        sheetUrl);
    } else if (data.status === "updated") {
      createNotificationWithTarget("success", "🔄 笔记已更新",
        `第 ${data.row || "?"} 行（「${data.sheet_title || "分类"}」）`, sheetUrl);
    } else if (data.status === "duplicate") {
      createNotificationWithTarget("info", "⏭ 已存在，跳过",
        `原始数据在第 ${data.original_row || "?"} 行`, sheetUrl);
    } else {
      notifyError("❌ 收录失败", data.error || "未知错误");
    }
    return { ok: true, data };
  } catch (err) {
    notifyError("❌ 收录失败", String(err.message || err));
    return { ok: false, error: String(err.message || err) };
  }
}

function storageGet(keys) {
  return new Promise((resolve) => chrome.storage.local.get(keys, resolve));
}

function storageSet(data) {
  return new Promise((resolve) => chrome.storage.local.set(data, resolve));
}

function noteIdFromXhsUrl(rawUrl) {
  try {
    const u = new URL(rawUrl, "https://www.xiaohongshu.com");
    const m = u.pathname.match(/\/(?:explore|discovery\/item)\/([a-zA-Z0-9]+)/);
    return m ? m[1] : "";
  } catch (e) {
    return "";
  }
}

function noteUrlHasXsecToken(rawUrl) {
  try {
    const u = new URL(String(rawUrl || ""), "https://www.xiaohongshu.com");
    return !!u.searchParams.get("xsec_token");
  } catch (e) {
    return false;
  }
}

function dedupeNoteUrlsPreferFull(urls, limit = PROFILE_COLLECT_LIMIT) {
  const byId = new Map();
  const orderedIds = [];
  const fallback = [];
  for (const rawUrl of urls || []) {
    if (!rawUrl) continue;
    let fullUrl = "";
    try {
      const u = new URL(String(rawUrl), "https://www.xiaohongshu.com");
      if (!/xiaohongshu\.com$/i.test(u.hostname)) continue;
      u.hash = "";
      fullUrl = u.toString();
    } catch (e) {
      continue;
    }
    const noteId = noteIdFromXhsUrl(fullUrl);
    if (!noteId) {
      if (!fallback.includes(fullUrl)) fallback.push(fullUrl);
      continue;
    }
    const old = byId.get(noteId);
    if (!old) {
      if (orderedIds.length >= limit) continue;
      byId.set(noteId, fullUrl);
      orderedIds.push(noteId);
    } else if (!noteUrlHasXsecToken(old) && noteUrlHasXsecToken(fullUrl)) {
      byId.set(noteId, fullUrl);
    }
  }
  const result = orderedIds.map((id) => byId.get(id)).filter(Boolean);
  for (const url of fallback) {
    if (result.length >= limit) break;
    result.push(url);
  }
  return result.slice(0, limit);
}

function filterApiReadyNoteUrls(urls, limit = PROFILE_COLLECT_LIMIT) {
  return dedupeNoteUrlsPreferFull(urls, limit)
    .filter((url) => noteIdFromXhsUrl(url) && noteUrlHasXsecToken(url));
}

function profileCheckpointKey(profileUrl) {
  try {
    const u = new URL(profileUrl);
    const m = u.pathname.match(/\/user\/profile\/([^/?#]+)/);
    if (m && m[1]) return `xhs-profile:${m[1]}`;
    u.hash = "";
    u.search = "";
    return `xhs-profile:${u.toString()}`;
  } catch (e) {
    return "";
  }
}

async function getProfileCheckpoints() {
  const data = await storageGet([PROFILE_COLLECT_CHECKPOINTS_KEY]);
  return data[PROFILE_COLLECT_CHECKPOINTS_KEY] || {};
}

async function getProfileCheckpoint(profileUrl) {
  const key = profileCheckpointKey(profileUrl);
  if (!key) return null;
  const checkpoints = await getProfileCheckpoints();
  return checkpoints[key] || null;
}

async function saveProfileCheckpoint(profileUrl, patch) {
  const key = profileCheckpointKey(profileUrl);
  if (!key) return null;
  const checkpoints = await getProfileCheckpoints();
  const prev = checkpoints[key] || {};
  const noteUrls = dedupeNoteUrlsPreferFull([
    ...(prev.note_urls || []),
    ...((patch && patch.note_urls) || []),
  ]);
  const apiReadyUrls = filterApiReadyNoteUrls(noteUrls);
  const checkpoint = {
    ...prev,
    ...(patch || {}),
    profile_url: profileUrl || prev.profile_url || "",
    note_urls: noteUrls,
    checkpoint_saved: noteUrls.length,
    api_ready_count: apiReadyUrls.length,
    incomplete_link_count: Math.max(0, noteUrls.length - apiReadyUrls.length),
    updated_at: new Date().toISOString(),
  };
  checkpoints[key] = checkpoint;
  await storageSet({ [PROFILE_COLLECT_CHECKPOINTS_KEY]: checkpoints });
  return checkpoint;
}

function installXhsProfileApiInterceptor(options) {
  const cfg = (typeof options === "object" && options) ? options : {};
  const maxItems = Math.max(1, Number(cfg.limit || 400));
  const SOURCE = "xhs-collect-profile-interceptor";
  const REQUEST_SOURCE = "xhs-collect-profile-runner";
  const state = window.__xhsCollectProfileInterceptorState || {
    installed: false,
    byId: {},
    order: [],
    initialStateTimer: null,
    messageListenerAdded: false,
    historyPatched: false,
  };
  window.__xhsCollectProfileInterceptorState = state;
  state.maxItems = maxItems;

  function endpointKind(rawUrl) {
    try {
      const u = new URL(String(rawUrl || ""), location.href);
      const path = u.pathname || "";
      if (path.includes("/api/sns/web/v1/user_posted")) return "user_posted";
      if (path.includes("/api/sns/web/v1/search/notes")) return "search_notes";
      if (path.includes("/api/sns/web/v1/homefeed")) return "homefeed";
      if (path.includes("/api/sns/web/v1/feed")) return "feed";
    } catch (e) {}
    return "";
  }

  function unwrap(value) {
    if (!value || typeof value !== "object") return value;
    if (value.value !== undefined) return value.value;
    if (value._value !== undefined) return value._value;
    if (value._rawValue !== undefined) return value._rawValue;
    return value;
  }

  function firstString(values) {
    for (const value of values) {
      if (value === null || value === undefined) continue;
      const text = String(value).trim();
      if (text) return text;
    }
    return "";
  }

  function coverUrl(cover) {
    if (!cover || typeof cover !== "object") return "";
    return firstString([
      cover.url_default,
      cover.urlDefault,
      cover.url_pre,
      cover.urlPre,
      cover.url,
      cover.file_id,
      cover.fileId,
    ]);
  }

  function addCandidate(item, kind, out) {
    if (!item || typeof item !== "object") return;
    const card = item.note_card || item.noteCard || item.note || item;
    if (!card || typeof card !== "object") return;
    const noteId = firstString([
      card.note_id,
      card.noteId,
      card.id,
      item.note_id,
      item.noteId,
      item.id,
    ]);
    if (!noteId) return;
    const xsecToken = firstString([
      item.xsec_token,
      item.xsecToken,
      card.xsec_token,
      card.xsecToken,
    ]);
    const xsecSource = kind === "user_posted" ? "pc_user" : "pc_feed";
    let url = "";
    try {
      const u = new URL(`/explore/${noteId}`, location.origin);
      if (xsecToken) u.searchParams.set("xsec_token", xsecToken);
      u.searchParams.set("xsec_source", xsecSource);
      url = u.toString();
    } catch (e) {}
    const cover = card.cover || item.cover || {};
    out.push({
      id: noteId,
      note_id: noteId,
      title: firstString([
        card.display_title,
        card.displayTitle,
        card.title,
        item.display_title,
        item.displayTitle,
        item.title,
      ]),
      cover: coverUrl(cover),
      width: Number(cover.width || card.width || item.width || 0) || 0,
      height: Number(cover.height || card.height || item.height || 0) || 0,
      xsec_token: xsecToken,
      xsec_source: xsecSource,
      url,
      api: kind,
    });
  }

  function extractNotes(payload, kind) {
    const out = [];
    const root = payload && payload.data ? payload.data : payload;
    const lists = [];
    if (root && Array.isArray(root.notes)) lists.push(root.notes);
    if (root && Array.isArray(root.items)) lists.push(root.items);
    if (root && Array.isArray(root.feeds)) lists.push(root.feeds);
    if (Array.isArray(root)) lists.push(root);
    for (const list of lists) {
      for (const item of list) addCandidate(item, kind, out);
    }
    if (out.length) return out;

    const visited = new Set();
    function visit(value, depth) {
      value = unwrap(value);
      if (!value || typeof value !== "object" || depth > 6) return;
      if (visited.has(value)) return;
      visited.add(value);
      if (Array.isArray(value)) {
        for (const item of value) visit(item, depth + 1);
        return;
      }
      addCandidate(value, kind, out);
      for (const key of ["data", "items", "notes", "feeds", "list", "noteDetailMap", "value"]) {
        if (value[key] !== undefined) visit(value[key], depth + 1);
      }
    }
    visit(root, 0);
    return out;
  }

  function snapshotNotes() {
    return state.order.map((id) => state.byId[id]).filter(Boolean);
  }

  function postNotes(notes, stage) {
    if (!notes || !notes.length) return;
    window.postMessage({
      source: SOURCE,
      type: "xhs_profile_api_notes",
      stage,
      notes,
      total_captured: state.order.length,
    }, location.origin);
  }

  function storeNotes(notes, stage) {
    const changed = [];
    for (const note of notes || []) {
      if (!note || !note.id) continue;
      const old = state.byId[note.id];
      if (!old) {
        if (state.order.length >= state.maxItems) continue;
        state.byId[note.id] = note;
        state.order.push(note.id);
        changed.push(note);
      } else if (!old.xsec_token && note.xsec_token) {
        state.byId[note.id] = { ...old, ...note };
        changed.push(state.byId[note.id]);
      }
    }
    postNotes(changed, stage);
  }

  function handlePayload(rawUrl, payload) {
    const kind = endpointKind(rawUrl);
    if (!kind || !payload) return;
    storeNotes(extractNotes(payload, kind), `api:${kind}`);
  }

  function handleText(rawUrl, text) {
    if (!text || !endpointKind(rawUrl)) return;
    try {
      handlePayload(rawUrl, JSON.parse(text));
    } catch (e) {}
  }

  function scanInitialState() {
    const pageState = window.__INITIAL_STATE__;
    if (!pageState || typeof pageState !== "object") return;
    const kind = location.pathname.includes("/user/profile/") ? "user_posted" : "homefeed";
    const roots = [
      pageState.user && pageState.user.notes,
      pageState.feed && pageState.feed.feeds,
      pageState.search && pageState.search.feeds,
      pageState.note && pageState.note.noteDetailMap,
    ];
    for (const root of roots) {
      if (root !== undefined) storeNotes(extractNotes(root, kind), "initial_state");
    }
  }

  function startInitialStatePolling() {
    if (state.initialStateTimer) clearInterval(state.initialStateTimer);
    let rounds = 0;
    scanInitialState();
    state.initialStateTimer = setInterval(() => {
      rounds += 1;
      scanInitialState();
      if (rounds >= 20) {
        clearInterval(state.initialStateTimer);
        state.initialStateTimer = null;
      }
    }, 500);
  }

  function profileUserIdFromPage() {
    try {
      const pathMatch = location.pathname.match(/\/user\/profile\/([^/?#]+)/);
      const stateUser = window.__INITIAL_STATE__ && window.__INITIAL_STATE__.user;
      const queries = unwrap(stateUser && stateUser.noteQueries);
      const firstQuery = Array.isArray(queries) ? queries[0] : null;
      return firstString([
        firstQuery && firstQuery.userId,
        firstQuery && firstQuery.user_id,
        pathMatch && pathMatch[1],
      ]);
    } catch (e) {
      return "";
    }
  }

  function profileXsecTokenFromPage() {
    try {
      return new URL(location.href).searchParams.get("xsec_token") || "";
    } catch (e) {
      return "";
    }
  }

  function lastCapturedNoteId() {
    for (let i = state.order.length - 1; i >= 0; i -= 1) {
      const id = state.order[i];
      if (id) return id;
    }
    return "";
  }

  function initialProfilePageQuery() {
    const stateUser = window.__INITIAL_STATE__ && window.__INITIAL_STATE__.user;
    const queries = unwrap(stateUser && stateUser.noteQueries);
    const firstQuery = Array.isArray(queries) ? queries[0] : null;
    const cursor = firstString([
      firstQuery && firstQuery.cursor,
      lastCapturedNoteId(),
    ]);
    return {
      num: Math.min(50, Math.max(1, Number((firstQuery && firstQuery.num) || 30))),
      cursor,
      userId: profileUserIdFromPage(),
      page: Math.max(1, Number((firstQuery && firstQuery.page) || 1)),
      hasMore: !firstQuery || firstQuery.hasMore !== false,
      xsecToken: profileXsecTokenFromPage(),
    };
  }

  function noteIdFromApiItem(item) {
    if (!item || typeof item !== "object") return "";
    const card = item.note_card || item.noteCard || item.note || item;
    return firstString([
      item.id,
      item.note_id,
      item.noteId,
      card.id,
      card.note_id,
      card.noteId,
    ]);
  }

  function userPostedUrl(query) {
    const u = new URL("/api/sns/web/v1/user_posted", location.origin);
    u.searchParams.set("num", String(query.num || 30));
    u.searchParams.set("cursor", query.cursor || "");
    u.searchParams.set("user_id", query.userId || "");
    u.searchParams.set("image_formats", "jpg,webp,avif");
    if (query.xsecToken) u.searchParams.set("xsec_token", query.xsecToken);
    u.searchParams.set("xsec_source", "pc_user");
    return u.toString();
  }

  async function tryFetchUserPostedPage(query) {
    if (typeof fetch !== "function") return { ok: false, reason: "fetch_unavailable" };
    const url = userPostedUrl(query);
    const resp = await fetch(url, {
      credentials: "include",
      headers: {
        accept: "application/json, text/plain, */*",
      },
    });
    let payload = null;
    try {
      payload = await resp.clone().json();
    } catch (e) {
      try {
        payload = JSON.parse(await resp.text());
      } catch (e2) {}
    }
    if (!resp.ok || !payload) {
      return { ok: false, reason: `http_${resp.status || 0}` };
    }
    handlePayload(url, payload);
    const data = payload.data || {};
    const notes = Array.isArray(data.notes) ? data.notes : [];
    const lastNote = notes.length ? notes[notes.length - 1] : null;
    const nextCursor = firstString([
      data.cursor,
      data.next_cursor,
      data.nextCursor,
      lastNote && noteIdFromApiItem(lastNote),
    ]);
    const hasMore = data.has_more !== undefined
      ? !!data.has_more
      : (data.hasMore !== undefined ? !!data.hasMore : notes.length >= query.num);
    return {
      ok: true,
      notesCount: notes.length,
      nextCursor,
      hasMore,
    };
  }

  async function startActiveUserPostedPaging() {
    if (state.pagerRunning || state.pagerDone) return;
    scanInitialState();
    const query = initialProfilePageQuery();
    if (!query.userId || !query.cursor || !query.hasMore) {
      state.pagerDone = true;
      return;
    }
    state.pagerRunning = true;
    let pages = 0;
    const maxPages = Math.min(24, Math.ceil(state.maxItems / Math.max(1, query.num)) + 4);
    try {
      while (state.order.length < state.maxItems && query.hasMore && query.cursor && pages < maxPages) {
        pages += 1;
        const before = state.order.length;
        const result = await tryFetchUserPostedPage(query);
        if (!result.ok) break;
        query.page += 1;
        query.cursor = result.nextCursor || "";
        query.hasMore = !!result.hasMore;
        if (state.order.length <= before && !result.notesCount) break;
        await new Promise((resolve) => {
          setTimeout(resolve, 800 + Math.floor(Math.random() * 800));
        });
      }
    } catch (e) {
      console.warn("[xhs-collect] 主动分页 user_posted 失败，继续依赖页面滚动触发：", e);
    } finally {
      state.pagerRunning = false;
      state.pagerDone = true;
      postNotes(snapshotNotes(), "active_paging_done");
    }
  }

  if (!state.messageListenerAdded) {
    window.addEventListener("message", (event) => {
      if (event.source !== window) return;
      const data = event.data || {};
      if (data.source !== REQUEST_SOURCE) return;
      if (data.type === "xhs_profile_get_capture") {
        scanInitialState();
        postNotes(snapshotNotes(), "snapshot");
      }
      if (data.type === "xhs_profile_start_paging") {
        startActiveUserPostedPaging();
      }
    });
    state.messageListenerAdded = true;
  }

  if (!state.historyPatched) {
    const onRouteChange = () => setTimeout(startInitialStatePolling, 100);
    for (const name of ["pushState", "replaceState"]) {
      const original = history[name];
      if (typeof original !== "function") continue;
      history[name] = function patchedHistoryState() {
        const result = original.apply(this, arguments);
        onRouteChange();
        return result;
      };
    }
    window.addEventListener("popstate", onRouteChange);
    state.historyPatched = true;
  }

  if (!state.installed) {
    const originalOpen = XMLHttpRequest.prototype.open;
    const originalSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function patchedOpen(method, url) {
      try {
        this.__xhsCollectProfileUrl = String(url || "");
      } catch (e) {}
      return originalOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function patchedSend() {
      try {
        this.addEventListener("loadend", function onXhsProfileXhrLoadEnd() {
          try {
            const rawUrl = this.__xhsCollectProfileUrl || this.responseURL || "";
            if (!endpointKind(rawUrl)) return;
            if (this.responseType === "json") {
              handlePayload(rawUrl, this.response);
            } else if (!this.responseType || this.responseType === "text") {
              handleText(rawUrl, this.responseText || "");
            }
          } catch (e) {}
        }, { once: true });
      } catch (e) {}
      return originalSend.apply(this, arguments);
    };

    if (typeof window.fetch === "function") {
      const originalFetch = window.fetch;
      window.fetch = function patchedFetch(input) {
        const rawUrl = typeof input === "string" ? input : (input && input.url) || "";
        return originalFetch.apply(this, arguments).then((response) => {
          try {
            const responseUrl = rawUrl || response.url || "";
            if (endpointKind(responseUrl)) {
              response.clone().json().then((payload) => {
                handlePayload(responseUrl, payload);
              }).catch(() => {});
            }
          } catch (e) {}
          return response;
        });
      };
    }
    state.installed = true;
  }

  startInitialStatePolling();
  postNotes(snapshotNotes(), "installed");
  return { installed: true, captured: state.order.length };
}

async function getProfileCollectState() {
  const data = await storageGet([PROFILE_COLLECT_STATE_KEY]);
  return data[PROFILE_COLLECT_STATE_KEY] || null;
}

async function updateProfileCollectState(patch) {
  const prev = await getProfileCollectState();
  const state = {
    ...(prev || {}),
    ...patch,
    updated_at: new Date().toISOString(),
  };
  await storageSet({ [PROFILE_COLLECT_STATE_KEY]: state });
  chrome.runtime.sendMessage({
    type: "profile_collect_state",
    state,
  }).catch(() => {});
  return state;
}

function runProfileLinkExtractionInPage(options) {
  const cfg = (typeof options === "object" && options) ? options : {};
  const clientTaskId = cfg.clientTaskId || "";
  const maxLinks = Math.max(1, Number(cfg.limit || 400));
  const minDelay = Math.max(500, Number(cfg.minDelayMs || 1200));
  const maxDelay = Math.max(minDelay, Number(cfg.maxDelayMs || 2200));
  const batchPauseMin = Math.max(1000, Number(cfg.batchPauseMinMs || 4000));
  const batchPauseMax = Math.max(batchPauseMin, Number(cfg.batchPauseMaxMs || 7000));
  const batchLinks = Math.max(5, Number(cfg.batchLinks || 25));
  const batchRounds = Math.max(3, Number(cfg.batchRounds || 12));
  const checkpointBatchSize = Math.max(1, Number(cfg.checkpointBatchSize || 80));
  const existingNoteUrls = Array.isArray(cfg.existingNoteUrls) ? cfg.existingNoteUrls : [];

  if (window.__xhsProfileCollectRunning) {
    chrome.runtime.sendMessage({
      type: "profile_collect_links_failed",
      client_task_id: clientTaskId,
      error: "当前页面已有账号采集任务在运行，请等它结束后再点",
    });
    return { started: false, error: "already_running" };
  }
  window.__xhsProfileCollectRunning = true;

  function wait(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function randomBetween(min, max) {
    return Math.floor(min + Math.random() * (max - min + 1));
  }

  function send(type, detail) {
    try {
      chrome.runtime.sendMessage({
        type,
        client_task_id: clientTaskId,
        ...detail,
      });
    } catch (e) {
      // background 暂时不可用时忽略，下一次进度会继续发。
    }
  }

  function noteIdFromPath(pathname) {
    const m = pathname.match(/\/(?:explore|discovery\/item)\/([a-zA-Z0-9]+)/);
    return m ? m[1] : "";
  }

  function run() {
    const seen = new Map();

    function hasXsecToken(rawUrl) {
      try {
        const u = new URL(String(rawUrl || ""), location.origin);
        return !!u.searchParams.get("xsec_token");
      } catch (e) {
        return false;
      }
    }

    function addUrl(rawHref) {
      if (!rawHref) return;
      let u = null;
      try {
        u = new URL(rawHref, location.origin);
      } catch (e) {
        return;
      }
      if (!/xiaohongshu\.com$/i.test(u.hostname)) return;
      const noteId = noteIdFromPath(u.pathname);
      if (!noteId) return;
      u.hash = "";
      const fullUrl = u.toString();
      const old = seen.get(noteId);
      if (!old) {
        if (seen.size >= maxLinks) return;
        seen.set(noteId, fullUrl);
      } else if (!hasXsecToken(old) && hasXsecToken(fullUrl)) {
        seen.set(noteId, fullUrl);
      }
    }

    function addNoteWithToken(noteId, xsecToken, xsecSource) {
      if (!noteId || !xsecToken) return;
      try {
        const u = new URL(`/explore/${noteId}`, location.origin);
        u.searchParams.set("xsec_token", xsecToken);
        u.searchParams.set("xsec_source", xsecSource || "pc_user");
        addUrl(u.toString());
      } catch (e) {}
    }

    let capturedApiTotal = 0;

    function addCapturedNotes(notes) {
      const before = seen.size;
      for (const note of notes || []) {
        if (seen.size >= maxLinks) break;
        if (note && note.url) {
          addUrl(note.url);
        } else if (note) {
          addNoteWithToken(
            note.id || note.note_id || note.noteId,
            note.xsec_token || note.xsecToken,
            note.xsec_source || note.xsecSource,
          );
        }
      }
      return seen.size > before;
    }

    function requestCapturedNotes() {
      try {
        window.postMessage({
          source: "xhs-collect-profile-runner",
          type: "xhs_profile_get_capture",
        }, location.origin);
      } catch (e) {}
    }

    function requestActivePaging() {
      try {
        window.postMessage({
          source: "xhs-collect-profile-runner",
          type: "xhs_profile_start_paging",
        }, location.origin);
      } catch (e) {}
    }

    function onCapturedNotes(event) {
      if (event.source !== window) return;
      const data = event.data || {};
      if (data.source !== "xhs-collect-profile-interceptor") return;
      if (data.type !== "xhs_profile_api_notes") return;
      capturedApiTotal = Math.max(capturedApiTotal, Number(data.total_captured || 0));
      addCapturedNotes(data.notes || []);
    }
    window.addEventListener("message", onCapturedNotes);
    requestCapturedNotes();
    requestActivePaging();

    function unwrapStateValue(value) {
      if (!value || typeof value !== "object") return value;
      if (value.value !== undefined) return value.value;
      if (value._value !== undefined) return value._value;
      if (value._rawValue !== undefined) return value._rawValue;
      return value;
    }

    function collectFromInitialState() {
      const state = window.__INITIAL_STATE__;
      if (!state || typeof state !== "object") return;
      const roots = [
        state.user && state.user.notes,
        state.feed && state.feed.feeds,
        state.search && state.search.feeds,
        state.note && state.note.noteDetailMap,
      ];
      const visited = new Set();
      function visit(value, depth) {
        if (!value || depth > 8 || seen.size >= maxLinks) return;
        value = unwrapStateValue(value);
        if (!value || typeof value !== "object") return;
        if (visited.has(value)) return;
        visited.add(value);
        if (Array.isArray(value)) {
          for (const item of value) visit(item, depth + 1);
          return;
        }
        const noteId = value.id || value.noteId || value.note_id;
        const token = value.xsecToken || value.xsec_token;
        if (noteId && token) addNoteWithToken(noteId, token, value.xsecSource || value.xsec_source);
        for (const key of ["feeds", "notes", "items", "list", "data", "noteDetailMap"]) {
          if (value[key] !== undefined) visit(value[key], depth + 1);
        }
      }
      for (const root of roots) visit(root, 0);
    }

    for (const url of existingNoteUrls) {
      addUrl(url);
      if (seen.size >= maxLinks) break;
    }

    function collectOnce() {
      collectFromInitialState();
      requestCapturedNotes();
      const anchors = Array.from(document.querySelectorAll(
        'a[href*="/explore/"], a[href*="/discovery/item/"]',
      ));
      for (const a of anchors) {
        const candidates = [
          a.href,
          a.getAttribute("href"),
          a.getAttribute("data-href"),
          a.getAttribute("data-url"),
        ].filter(Boolean);
        for (const href of candidates) {
          addUrl(href);
        }
      }
      return seen.size;
    }

    let lastCheckpointSaved = Math.floor(seen.size / checkpointBatchSize) * checkpointBatchSize;
    function sendCheckpoint(stage) {
      const noteUrls = Array.from(seen.values()).slice(0, maxLinks);
      const apiReadyCount = noteUrls.filter(hasXsecToken).length;
      send("profile_collect_link_checkpoint", {
        stage,
        found: seen.size,
        limit: maxLinks,
        checkpoint_saved: noteUrls.length,
        api_ready_count: apiReadyCount,
        incomplete_link_count: Math.max(0, noteUrls.length - apiReadyCount),
        note_urls: noteUrls,
      });
    }

    function maybeSendCheckpoint(stage) {
      const checkpointCount = Math.floor(seen.size / checkpointBatchSize) * checkpointBatchSize;
      if (checkpointCount > lastCheckpointSaved) {
        lastCheckpointSaved = checkpointCount;
        sendCheckpoint(stage);
      }
    }

    (async () => {
      try {
        let lastCount = 0;
        let stableRounds = 0;
        let rounds = 0;
        let lastBatchCount = seen.size;
        let longPauses = 0;
        collectOnce();
        maybeSendCheckpoint("scan_start");
        send("profile_collect_link_progress", {
          stage: "scan_start",
          found: seen.size,
          limit: maxLinks,
          rounds,
          checkpoint_saved: lastCheckpointSaved,
          api_ready_count: Array.from(seen.values()).filter(hasXsecToken).length,
          captured_api_count: capturedApiTotal,
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
            send("profile_collect_link_progress", {
              stage: "scanning",
              found: seen.size,
              limit: maxLinks,
              rounds,
            stableRounds,
            longPauses,
            checkpoint_saved: lastCheckpointSaved,
            api_ready_count: Array.from(seen.values()).filter(hasXsecToken).length,
            captured_api_count: capturedApiTotal,
          });
        }
        maybeSendCheckpoint("scanning");
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
            send("profile_collect_link_progress", {
              stage: "batch_pause",
              found: seen.size,
              limit: maxLinks,
              rounds,
              longPauses,
              checkpoint_saved: lastCheckpointSaved,
              pauseSeconds: Math.round(pauseMs / 1000),
              api_ready_count: Array.from(seen.values()).filter(hasXsecToken).length,
              captured_api_count: capturedApiTotal,
            });
            await wait(pauseMs);
          }
        }

        collectOnce();
        const noteUrls = Array.from(seen.values()).slice(0, maxLinks);
        const apiReadyCount = noteUrls.filter(hasXsecToken).length;
        sendCheckpoint("done");
        send("profile_collect_links_done", {
          result: {
            note_urls: noteUrls,
            total_found: seen.size,
            returned: noteUrls.length,
            reached_limit: noteUrls.length >= maxLinks,
            scroll_rounds: rounds,
            long_pauses: longPauses,
            checkpoint_saved: noteUrls.length,
            api_ready_count: apiReadyCount,
            incomplete_link_count: Math.max(0, noteUrls.length - apiReadyCount),
            captured_api_count: capturedApiTotal,
          },
        });
      } catch (e) {
        send("profile_collect_links_failed", {
          error: String(e.message || e || "页面提取失败"),
        });
      } finally {
        window.removeEventListener("message", onCapturedNotes);
        window.__xhsProfileCollectRunning = false;
      }
    })();
  }

  run();
  return { started: true };
}

async function startProfileCollect(payload) {
  const cfg = await getConfig();
  if (!isAuthenticated(cfg)) {
    await updateProfileCollectState({
      status: "failed",
      phase: "auth",
      error: "未登录，请先在扩展里完成飞书登录和绑表",
    });
    return { ok: false, error: "未登录" };
  }
  if (!payload || !payload.tab_id) {
    return { ok: false, error: "未找到当前小红书主页标签页" };
  }
  const clientTaskId = (crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const profileUrl = (payload.profile_url || "").trim();
  const existingCheckpoint = await getProfileCheckpoint(profileUrl);
  const existingNoteUrls = dedupeNoteUrlsPreferFull(
    existingCheckpoint?.note_urls || [],
    PROFILE_COLLECT_LIMIT,
  );
  const existingApiReadyUrls = filterApiReadyNoteUrls(existingNoteUrls, PROFILE_COLLECT_LIMIT);
  await updateProfileCollectState({
    ok: true,
    client_task_id: clientTaskId,
    task_id: "",
    status: "running",
    phase: "link_scan",
    profile_url: profileUrl,
    account_name: (payload.account_name || "").trim() || "小红书账号",
    note: (payload.note || "").trim(),
    total_limit: PROFILE_COLLECT_LIMIT,
    found: existingNoteUrls.length,
    checkpoint_saved: existingNoteUrls.length,
    api_ready_count: existingApiReadyUrls.length,
    incomplete_link_count: Math.max(0, existingNoteUrls.length - existingApiReadyUrls.length),
    resume_from_checkpoint: existingNoteUrls.length > 0,
    processed: 0,
    success: 0,
    failed: 0,
    written: 0,
    skipped: 0,
    failed_examples: [],
    message: existingNoteUrls.length
      ? `已恢复 ${existingNoteUrls.length} 条历史链接，继续从页面补齐完整链接`
      : "正在从页面状态和笔记卡片提取完整链接",
    started_at: new Date().toISOString(),
  });
  if (existingApiReadyUrls.length >= PROFILE_COLLECT_LIMIT) {
    await submitProfileCollectFromLinks({
      note_urls: existingNoteUrls.slice(0, PROFILE_COLLECT_LIMIT),
      total_found: existingNoteUrls.length,
      returned: existingNoteUrls.length,
      reached_limit: true,
      scroll_rounds: 0,
      long_pauses: 0,
      checkpoint_saved: existingNoteUrls.length,
      api_ready_count: existingApiReadyUrls.length,
      incomplete_link_count: Math.max(0, existingNoteUrls.length - existingApiReadyUrls.length),
      resumed: true,
    });
    return { ok: true, state: await getProfileCollectState() };
  }
  try {
    await chrome.scripting.executeScript({
      target: { tabId: payload.tab_id },
      world: "MAIN",
      func: installXhsProfileApiInterceptor,
      args: [{ limit: PROFILE_COLLECT_LIMIT }],
    });
  } catch (e) {
    console.warn("[xhs-collect] MAIN world 小红书接口监听器注入失败，继续使用 DOM 兜底：", e);
  }
  const result = await chrome.scripting.executeScript({
    target: { tabId: payload.tab_id },
    func: runProfileLinkExtractionInPage,
    args: [{
      clientTaskId,
      limit: PROFILE_COLLECT_LIMIT,
      minDelayMs: PROFILE_SCROLL_MIN_DELAY_MS,
      maxDelayMs: PROFILE_SCROLL_MAX_DELAY_MS,
      batchPauseMinMs: PROFILE_SCROLL_BATCH_PAUSE_MIN_MS,
      batchPauseMaxMs: PROFILE_SCROLL_BATCH_PAUSE_MAX_MS,
      batchLinks: PROFILE_SCROLL_BATCH_LINKS,
      batchRounds: PROFILE_SCROLL_BATCH_ROUNDS,
      checkpointBatchSize: PROFILE_COLLECT_CHECKPOINT_BATCH_SIZE,
      existingNoteUrls,
    }],
  });
  const started = result && result[0] && result[0].result && result[0].result.started;
  if (!started) {
    const error = result?.[0]?.result?.error || "页面脚本未能启动";
    await updateProfileCollectState({
      status: "failed",
      phase: "link_scan",
      error,
    });
    return { ok: false, error };
  }
  return { ok: true, state: await getProfileCollectState() };
}

async function submitProfileCollectToBackend(options = {}) {
  const state = await getProfileCollectState();
  if (!state) return;
  const noteUrls = Array.isArray(options.noteUrls) ? options.noteUrls : [];
  const hasFullNoteLinks = noteUrls.length > 0;
  const cfg = await getConfig();
  await updateProfileCollectState({
    phase: "backend_submit",
    found: Number(options.found || 0),
    checkpoint_saved: Number(options.found || 0),
    api_ready_count: Number(options.apiReadyCount || noteUrls.length || 0),
    incomplete_link_count: Number(options.incompleteLinkCount || 0),
    link_result: options.linkResult || {},
    message: options.message || (
      hasFullNoteLinks
        ? "正在提交服务器，逐篇调用单篇 API 采集"
        : "正在提交服务器，尝试主页批量接口兜底"
    ),
  });
  try {
    const resp = await fetch(`${cfg.endpoint}/api/profile-collect`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders(cfg) },
      body: JSON.stringify({
        profile_url: state.profile_url,
        account_name: state.account_name,
        note: state.note || "",
        note_urls: noteUrls,
        max_items: PROFILE_COLLECT_LIMIT,
        source: "账号全采集",
      }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
    await updateProfileCollectState({
      phase: data.phase || "playlist_extract",
      task_id: data.task_id,
      backend_task: data,
      collect_mode: data.collect_mode || (hasFullNoteLinks ? "single_post" : "playlist"),
      total: data.total || PROFILE_COLLECT_LIMIT,
      processed: data.processed || 0,
      success: data.success || 0,
      failed: data.failed || 0,
      api_ready_count: Number(options.apiReadyCount || noteUrls.length || 0),
      incomplete_link_count: Number(options.incompleteLinkCount || 0),
      message: data.message || (
        hasFullNoteLinks
          ? "服务器已开始逐篇调用单篇 API"
          : "服务器已开始尝试主页批量接口"
      ),
    });
    pollProfileCollectTask(data.task_id);
  } catch (e) {
    await updateProfileCollectState({
      status: "failed",
      phase: "backend_submit",
      error: String(e.message || e),
    });
    notifyError("账号采集失败", String(e.message || e));
  }
}

async function submitProfileCollectFromLinks(linkResult) {
  const state = await getProfileCollectState();
  if (!state || !linkResult || !Array.isArray(linkResult.note_urls)) return;
  const checkpoint = await saveProfileCheckpoint(state.profile_url, {
    account_name: state.account_name,
    note_urls: linkResult.note_urls,
    status: "links_ready",
  });
  const noteUrls = dedupeNoteUrlsPreferFull(
    (checkpoint && checkpoint.note_urls) || linkResult.note_urls,
    PROFILE_COLLECT_LIMIT,
  );
  const apiReadyNoteUrls = filterApiReadyNoteUrls(noteUrls, PROFILE_COLLECT_LIMIT);
  const incompleteLinkCount = Math.max(0, noteUrls.length - apiReadyNoteUrls.length);
  if (!noteUrls.length) {
    await updateProfileCollectState({
      status: "failed",
      phase: "link_scan",
      error: "主页没有提取到笔记链接，请确认页面已登录并能看到笔记列表",
      link_result: linkResult,
    });
    return;
  }
  if (!apiReadyNoteUrls.length) {
    await submitProfileCollectToBackend({
      noteUrls: [],
      found: noteUrls.length,
      apiReadyCount: 0,
      incompleteLinkCount: noteUrls.length,
      linkResult: {
        ...linkResult,
        note_urls: noteUrls,
        returned: noteUrls.length,
        api_ready_count: 0,
        incomplete_link_count: noteUrls.length,
      },
      message: `已找到 ${noteUrls.length} 条短链接，先尝试服务器主页批量接口兜底`,
    });
    return;
  }
  await submitProfileCollectToBackend({
    noteUrls: apiReadyNoteUrls,
    found: noteUrls.length,
    apiReadyCount: apiReadyNoteUrls.length,
    incompleteLinkCount,
    linkResult: {
      ...linkResult,
      note_urls: noteUrls,
      returned: noteUrls.length,
      api_ready_count: apiReadyNoteUrls.length,
      incomplete_link_count: incompleteLinkCount,
    },
    message: "正在提交服务器，逐篇调用单篇 API 采集",
  });
}

function taskIsActive(status) {
  return status === "queued" || status === "running";
}

function normalizeBackendTask(state, task) {
  const phase = task.phase || (task.status === "done" ? "done" : "playlist_extract");
  return {
    ...state,
    status: task.status || state.status,
    phase,
    backend_task: task,
    task_id: task.task_id || state.task_id,
    collect_mode: task.collect_mode || state.collect_mode || "",
    total: task.total || state.total || 0,
    processed: task.processed || 0,
    success: task.success || 0,
    failed: task.failed || 0,
    written: task.written || 0,
    skipped: task.skipped || 0,
    partial_saved: task.partial_saved || 0,
    api_ready_count: state.api_ready_count || state.link_result?.api_ready_count || 0,
    incomplete_link_count: state.incomplete_link_count || state.link_result?.incomplete_link_count || 0,
    failed_examples: task.failed_examples || [],
    failed_details: task.failed_details || task.failed_examples || [],
    failed_saved: task.failed_saved || 0,
    retry_total: task.retry_total || 0,
    retry_processed: task.retry_processed || 0,
    retry_success: task.retry_success || 0,
    retry_failed: task.retry_failed || 0,
    sheet_title: task.sheet_title || state.sheet_title,
    sheet_id: task.sheet_id || state.sheet_id,
    sheet_url: task.sheet_url || state.sheet_url,
    created_sheet: task.created_sheet,
    error: task.error || "",
    message: task.message || state.message || "",
    finished_at: task.finished_at || state.finished_at,
  };
}

async function pollProfileCollectTask(taskId) {
  if (!taskId) return;
  if (__profileCollectPollTimer) clearTimeout(__profileCollectPollTimer);
  const cfg = await getConfig();
  const tick = async () => {
    const state = await getProfileCollectState();
    if (!state || state.task_id !== taskId) return;
    if (!taskIsActive(state.status)) return;
    try {
      const resp = await fetch(`${cfg.endpoint}/api/profile-collect/tasks/${taskId}`, {
        method: "GET",
        headers: authHeaders(cfg),
      });
      const task = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(task.detail || `HTTP ${resp.status}`);
      const merged = normalizeBackendTask(state, task);
      await updateProfileCollectState(merged);
      if (taskIsActive(task.status)) {
        __profileCollectPollTimer = setTimeout(tick, 2500);
      } else if (task.status === "done") {
        createNotificationWithTarget(
          "success",
          "账号全采集完成",
          `已写入「${task.sheet_title || "账号全采集"}」：新增 ${task.written || 0} 条`,
          task.sheet_url || "",
        );
      } else if (task.status === "failed") {
        notifyError("账号全采集失败", task.error || "后台任务失败");
      }
    } catch (e) {
      await updateProfileCollectState({
        phase: "playlist_extract",
        message: `查询后台进度失败：${String(e.message || e)}`,
      });
      __profileCollectPollTimer = setTimeout(tick, 5000);
    }
  };
  tick();
}

async function ensureXhsCommerceProbe(tabId) {
  if (!tabId) throw new Error("未找到当前小红书页面标签页");
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["xhs_commerce_probe.js"],
    world: "MAIN",
  });
}

function extractScriptResult(results) {
  const first = Array.isArray(results) ? results[0] : null;
  return first ? first.result : null;
}

async function runXhsShopProductsPrototype(tabId) {
  await ensureXhsCommerceProbe(tabId);
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    args: [{ maxPages: 5, maxDetailCount: 20 }],
    func: async (options) => {
      if (!window.__xhsCommercePrototype) throw new Error("店铺商品采集脚本未加载");
      return window.__xhsCommercePrototype.extractShopProducts(options);
    },
  });
  return extractScriptResult(results);
}

async function runXhsCommentsPrototype(tabId) {
  await ensureXhsCommerceProbe(tabId);
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    args: [{ limit: 500, scrollRounds: 8, expandRounds: 4 }],
    func: async (options) => {
      if (!window.__xhsCommercePrototype) throw new Error("评论采集脚本未加载");
      return window.__xhsCommercePrototype.extractComments(options);
    },
  });
  return extractScriptResult(results);
}

// 暴露给 popup 调用（popup 关闭后 background 仍能弹通知）
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "notify") {
    makeNotification(msg.level || "info", msg.title, msg.message);
    sendResponse({ ok: true });
    return true;
  }
  if (msg && msg.type === "xhs_shop_products_extract_start") {
    runXhsShopProductsPrototype(msg.payload && msg.payload.tab_id).then((result) => {
      sendResponse({ ok: !!(result && result.ok), result, error: result && result.error });
    }).catch((e) => {
      sendResponse({ ok: false, error: String(e.message || e) });
    });
    return true;
  }
  if (msg && msg.type === "xhs_comments_extract_start") {
    runXhsCommentsPrototype(msg.payload && msg.payload.tab_id).then((result) => {
      sendResponse({ ok: !!(result && result.ok), result, error: result && result.error });
    }).catch((e) => {
      sendResponse({ ok: false, error: String(e.message || e) });
    });
    return true;
  }
  if (msg && msg.type === "profile_collect_get_state") {
    getProfileCollectState().then((state) => {
      if (state && state.task_id && taskIsActive(state.status)) {
        pollProfileCollectTask(state.task_id);
      }
      sendResponse({ ok: true, state });
    });
    return true;
  }
  if (msg && msg.type === "profile_collect_start") {
    startProfileCollect(msg.payload || {}).then(sendResponse).catch((e) => {
      updateProfileCollectState({
        status: "failed",
        phase: "start",
        error: String(e.message || e),
      });
      sendResponse({ ok: false, error: String(e.message || e) });
    });
    return true;
  }
  if (msg && msg.type === "profile_collect_link_progress") {
    getProfileCollectState().then((state) => {
      if (!state || state.client_task_id !== msg.client_task_id) return;
      updateProfileCollectState({
        status: "running",
        phase: "link_scan",
        link_stage: msg.stage,
        found: msg.found || 0,
        total_limit: msg.limit || PROFILE_COLLECT_LIMIT,
        checkpoint_saved: msg.checkpoint_saved || state.checkpoint_saved || 0,
        api_ready_count: msg.api_ready_count || state.api_ready_count || 0,
        incomplete_link_count: Math.max(0, (msg.found || 0) - (msg.api_ready_count || state.api_ready_count || 0)),
        scroll_rounds: msg.rounds || 0,
        stable_rounds: msg.stableRounds || 0,
        long_pauses: msg.longPauses || 0,
        pause_seconds: msg.pauseSeconds || 0,
        captured_api_count: msg.captured_api_count || state.captured_api_count || 0,
        message: "正在慢速翻主页提取笔记链接",
      });
    });
    sendResponse({ ok: true });
    return true;
  }
  if (msg && msg.type === "profile_collect_link_checkpoint") {
    getProfileCollectState().then(async (state) => {
      if (!state || state.client_task_id !== msg.client_task_id) return;
      const checkpoint = await saveProfileCheckpoint(state.profile_url, {
        account_name: state.account_name,
        note_urls: msg.note_urls || [],
        status: "link_scan",
      });
      const saved = checkpoint?.checkpoint_saved || msg.checkpoint_saved || 0;
      const apiReadyCount = checkpoint?.api_ready_count || msg.api_ready_count || 0;
      await updateProfileCollectState({
        status: "running",
        phase: "link_scan",
        link_stage: msg.stage || "checkpoint",
        found: msg.found || saved,
        checkpoint_saved: saved,
        api_ready_count: apiReadyCount,
        incomplete_link_count: Math.max(0, saved - apiReadyCount),
        captured_api_count: msg.captured_api_count || state.captured_api_count || 0,
        total_limit: msg.limit || PROFILE_COLLECT_LIMIT,
        message: `已保存 ${saved} 条链接，其中 ${apiReadyCount} 条可提交 API，可断点续采`,
      });
    });
    sendResponse({ ok: true });
    return true;
  }
  if (msg && msg.type === "profile_collect_links_done") {
    getProfileCollectState().then(async (state) => {
      if (!state || state.client_task_id !== msg.client_task_id) return;
      const result = msg.result || {};
      const checkpoint = await saveProfileCheckpoint(state.profile_url, {
        account_name: state.account_name,
        note_urls: result.note_urls || [],
        status: "links_done",
      });
      submitProfileCollectFromLinks({
        ...result,
        note_urls: checkpoint?.note_urls || result.note_urls || [],
        returned: checkpoint?.checkpoint_saved || result.returned || 0,
        checkpoint_saved: checkpoint?.checkpoint_saved || result.checkpoint_saved || 0,
        api_ready_count: checkpoint?.api_ready_count || result.api_ready_count || 0,
        incomplete_link_count: checkpoint?.incomplete_link_count || result.incomplete_link_count || 0,
      });
    });
    sendResponse({ ok: true });
    return true;
  }
  if (msg && msg.type === "profile_collect_links_failed") {
    getProfileCollectState().then((state) => {
      if (!state || state.client_task_id !== msg.client_task_id) return;
      updateProfileCollectState({
        status: "failed",
        phase: "link_scan",
        error: msg.error || "页面提取链接失败",
      });
    });
    sendResponse({ ok: true });
    return true;
  }
  // v4.3.0 P0 fix：popup 启动收录任务，background 接管
  if (msg && msg.type === "collect-start") {
    performCollect(msg.payload, msg.source || "Popup").then((result) => {
      // 尝试把结果回推给 popup（popup 还活着才收得到）
      chrome.runtime.sendMessage({ type: "collect-result", result }).catch(() => {});
      sendResponse(result);
    });
    return true;  // 异步 sendResponse 必须返回 true
  }
  return false;
});

// ==================== Cmd+Shift+X 一键收录（v4.3 新增） ====================
chrome.commands.onCommand.addListener(async (command) => {
  if (command !== "collect-current") return;

  // 1. 拿当前活跃 tab
  let tab;
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    tab = tabs && tabs[0];
  } catch (e) {
    notifyError("快捷键收录失败", "无法获取当前标签页");
    return;
  }
  if (!tab || !tab.url || !XHS_HOST_RE.test(tab.url)) {
    notifyError("当前页面不是小红书笔记", "请打开小红书笔记后再按 ⌘⇧X");
    return;
  }

  // 2. 拿配置（复用现有 getConfig）
  const cfg = await getConfig();
  if (!isAuthenticated(cfg)) {
    notifyError("快捷键收录失败", "请先在扩展里完成 onboarding（点扩展图标登录）");
    return;
  }

  // 3. 拿上次选的分类（key 与 popup.js 的 LAST_CATEGORY_KEY 对齐）
  const { lastCategorySheetId } = await new Promise((r) =>
    chrome.storage.local.get(["lastCategorySheetId"], r)
  );
  if (!lastCategorySheetId) {
    notifyError(
      "请先在 popup 里选一次分类",
      "下次按 ⌘⇧X 就会自动用这个分类收录"
    );
    return;
  }

  // 4. 调收录 API（无备注、来源标 Shortcut）
  notifyInfo("⏳ 正在收录…", tab.title || tab.url || "小红书笔记");
  try {
    const resp = await fetch(`${cfg.endpoint}/api/collect`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(cfg),
      },
      body: JSON.stringify({
        url: tab.url,
        note: "",
        tags: [],
        source: "Shortcut",
        sheet_id: lastCategorySheetId,
      }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(data.detail || `HTTP ${resp.status}`);
    }
    // v4.3.0 P1 fix（Codex 第 3 轮抓到）：快捷键通知也要可点击跳飞书表
    // 先实时查 /api/me 拿 sheet_url（兜底），再用 createNotificationWithTarget 替代 notifySuccess/notifyInfo
    let sheetUrl = "";
    try {
      const meR = await fetch(`${cfg.endpoint}/api/me`, { headers: authHeaders(cfg) });
      if (meR.ok) sheetUrl = (await meR.json()).sheet_url || "";
    } catch (e) { /* noop */ }

    if (data.status === "ok") {
      createNotificationWithTarget("success", "✅ 收录成功",
        `已存到「${data.sheet_title || "分类"}」第 ${data.row || "?"} 行：${data.title || ""}`,
        sheetUrl);
      if (tab.id) chrome.action.setBadgeText({ tabId: tab.id, text: "✓" });
    } else if (data.status === "updated") {
      createNotificationWithTarget("success", "🔄 已更新",
        `第 ${data.row || "?"} 行（在「${data.sheet_title || "分类"}」）：${data.title || ""}`,
        sheetUrl);
    } else if (data.status === "duplicate") {
      createNotificationWithTarget("info", "⏭ 已存在，跳过",
        `原始数据在第 ${data.original_row || "?"} 行：${data.title || ""}`,
        sheetUrl);
    } else {
      notifyError("❌ 收录失败", data.error || data.detail || "未知错误");
    }
  } catch (err) {
    notifyError("❌ 收录失败", String((err && err.message) || err));
  }
});

// options.js — 设置页交互（一般用户不需要进入此页，内置凭证已可用）
// 默认值来自 secrets.js 的 XHS_API_ENDPOINT 和 XHS_API_TOKEN

// 默认 endpoint（团队成员可以在 UI 里改）。token 不能预填，必须用户自填。
const DEFAULT_ENDPOINT_FALLBACK = "http://14.22.112.147:8866";

function load() {
  // endpoint 和 token 用 local（这是设备绑定的）
  chrome.storage.local.get(["endpoint", "authToken"], (data) => {
    // 兼容旧版本里如果存在 XHS_API_ENDPOINT 全局变量（admin 自用）就用它
    const defaultEp = (typeof XHS_API_ENDPOINT !== "undefined")
      ? XHS_API_ENDPOINT
      : DEFAULT_ENDPOINT_FALLBACK;
    const defaultTok = (typeof XHS_API_TOKEN !== "undefined")
      ? XHS_API_TOKEN
      : "";
    document.getElementById("endpoint").value = data.endpoint || defaultEp;
    document.getElementById("token").value = data.authToken || defaultTok;
  });
  // 偏好用 sync（跨设备同步）
  chrome.storage.sync.get(["dupStrategy"], (data) => {
    document.getElementById("dup-strategy").value =
      data.dupStrategy || "skip";
  });
}

function showResult(type, html) {
  const el = document.getElementById("test-result");
  el.className = `test-result show ${type}`;
  el.innerHTML = html;
}

document.getElementById("btn-save").addEventListener("click", () => {
  const endpoint = document.getElementById("endpoint").value.trim().replace(/\/+$/, "");
  const authToken = document.getElementById("token").value.trim();
  const dupStrategy = document.getElementById("dup-strategy").value;
  if (!endpoint) {
    showResult("fail", "❌ endpoint 不能为空");
    return;
  }
  // 保存设备绑定 + 跨设备偏好
  chrome.storage.local.set({ endpoint, authToken }, () => {
    chrome.storage.sync.set({ dupStrategy }, () => {
      showResult("ok", "✅ 已保存（重复策略已跨设备同步）");
    });
  });
});

document.getElementById("btn-test").addEventListener("click", async () => {
  const endpoint = document.getElementById("endpoint").value.trim().replace(/\/+$/, "");
  const token = document.getElementById("token").value.trim();
  if (!endpoint) {
    showResult("fail", "❌ 先填 endpoint");
    return;
  }
  showResult("ok", "⏳ 测试中…");
  try {
    // 1. /api/health 无需鉴权
    const h = await fetch(`${endpoint}/api/health`);
    if (!h.ok) throw new Error(`/api/health 返回 ${h.status}`);
    const hd = await h.json();
    if (!hd.ok) throw new Error("/api/health 返回不正常");

    // 2. /api/check 验证 token
    if (token) {
      const c = await fetch(
        `${endpoint}/api/check?url=${encodeURIComponent("https://www.xiaohongshu.com/discovery/item/test")}`,
        { headers: { "X-Auth-Token": token } }
      );
      if (c.status === 401) throw new Error("token 不匹配（服务器返回 401）");
      if (!c.ok) throw new Error(`/api/check 返回 ${c.status}`);
    }
    // 防 XSS：version 来自后端但还是 escape
    const safeVersion = String(hd.version || "未知")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    showResult(
      "ok",
      `✅ 连接成功${token ? "，token 也对" : "，但未填 token，建议填一下"}<br>
       服务版本：${safeVersion}`
    );
  } catch (err) {
    showResult("fail", `❌ ${err.message}`);
  }
});

load();

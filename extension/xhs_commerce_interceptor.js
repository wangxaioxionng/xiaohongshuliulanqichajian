(function () {
  "use strict";

  if (window.__xhsCommerceInterceptorInstalled) return;
  window.__xhsCommerceInterceptorInstalled = true;

  function isGoodsDetailApi(url) {
    return String(url || "").includes("/api/store/jpd/edith/detail");
  }

  function publishGoodsPayload(payload, url) {
    try {
      if (!payload || typeof payload !== "object") return;
      window.__xhs_intercepted_goods__ = {
        url: String(url || ""),
        payload,
        capturedAt: Date.now(),
      };
      window.dispatchEvent(new CustomEvent("xhs-goods-data", {
        detail: window.__xhs_intercepted_goods__,
      }));
    } catch (e) {
      // The page should never break because this optional prototype probe failed.
    }
  }

  if (typeof window.fetch === "function" && !window.fetch.__xhsCommercePatched) {
    const originalFetch = window.fetch;
    const patchedFetch = async function () {
      const requestUrl = arguments[0] && arguments[0].url ? arguments[0].url : arguments[0];
      const response = await originalFetch.apply(this, arguments);
      if (isGoodsDetailApi(requestUrl)) {
        response.clone().json().then((payload) => {
          publishGoodsPayload(payload, requestUrl);
        }).catch(() => {});
      }
      return response;
    };
    patchedFetch.__xhsCommercePatched = true;
    window.fetch = patchedFetch;
  }

  if (window.XMLHttpRequest && !window.XMLHttpRequest.prototype.__xhsCommercePatched) {
    const originalOpen = window.XMLHttpRequest.prototype.open;
    const originalSend = window.XMLHttpRequest.prototype.send;
    window.XMLHttpRequest.prototype.open = function (method, url) {
      this.__xhsCommerceUrl = url;
      return originalOpen.apply(this, arguments);
    };
    window.XMLHttpRequest.prototype.send = function () {
      this.addEventListener("load", function () {
        if (!isGoodsDetailApi(this.__xhsCommerceUrl)) return;
        try {
          publishGoodsPayload(JSON.parse(this.responseText), this.__xhsCommerceUrl);
        } catch (e) {
          // Ignore non-JSON or blocked responses.
        }
      });
      return originalSend.apply(this, arguments);
    };
    window.XMLHttpRequest.prototype.__xhsCommercePatched = true;
  }
})();

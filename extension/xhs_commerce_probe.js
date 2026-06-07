(function (root) {
  "use strict";

  const API_VERSION = "0.1.0";

  function asObject(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function firstNonEmpty() {
    for (const value of arguments) {
      if (value === 0) return value;
      if (value === false) return value;
      if (value !== null && value !== undefined && String(value).trim() !== "") return value;
    }
    return "";
  }

  function cleanText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function uniqueList(items) {
    const seen = new Set();
    const out = [];
    for (const item of asArray(items)) {
      const value = String(item || "").trim();
      if (!value || seen.has(value)) continue;
      seen.add(value);
      out.push(value);
    }
    return out;
  }

  function normalizeSoldCount(value) {
    if (typeof value === "number" && Number.isFinite(value)) return Math.max(0, Math.round(value));
    const text = String(value || "").replace(/,/g, "").trim();
    if (!text) return 0;
    const wan = text.match(/([\d.]+)\s*[万wW]/);
    if (wan) return Math.round(parseFloat(wan[1]) * 10000);
    const num = text.match(/[\d.]+/);
    if (!num) return 0;
    return Math.max(0, Math.round(parseFloat(num[0])));
  }

  function normalizePrice(value) {
    if (value && typeof value === "object") {
      return normalizePrice(firstNonEmpty(value.price, value.amount, value.value, value.cent, value.centPrice));
    }
    if (typeof value === "number" && Number.isFinite(value)) {
      if (Number.isInteger(value) && value >= 1000) return Math.round(value) / 100;
      return Math.round(value * 100) / 100;
    }
    const text = String(value || "").replace(/,/g, "").trim();
    if (!text) return 0;
    const match = text.match(/[\d.]+/);
    if (!match) return 0;
    const parsed = parseFloat(match[0]);
    if (!Number.isFinite(parsed)) return 0;
    if (!text.includes(".") && parsed >= 1000) return Math.round(parsed) / 100;
    return Math.round(parsed * 100) / 100;
  }

  function firstPositivePrice() {
    for (const value of arguments) {
      const price = normalizePrice(value);
      if (price > 0) return price;
    }
    return 0;
  }

  function priceFromPriceInfo(priceInfo, keys) {
    const info = asObject(priceInfo);
    for (const key of keys) {
      const node = asObject(info[key]);
      const price = normalizePrice(firstNonEmpty(node.price, node.amount, node.value, info[key]));
      if (price > 0) return price;
    }
    return 0;
  }

  function pickImage(value) {
    if (!value) return "";
    if (typeof value === "string") return value;
    if (Array.isArray(value)) return pickImage(value[0]);
    const obj = asObject(value);
    return firstNonEmpty(obj.url, obj.src, obj.original, obj.thumbnail, obj.link);
  }

  function unwrapData(payload) {
    const body = asObject(payload);
    return body.data && typeof body.data === "object" && !Array.isArray(body.data) ? body.data : body;
  }

  function firstPayloadItem(payload) {
    const data = unwrapData(payload);
    return asObject(
      firstNonEmpty(
        asArray(data.items)[0],
        asArray(data.skus)[0],
        data.item,
        data.sku,
        data.goods,
      ),
    );
  }

  function extractShopInfoFromGoodsPayload(payload) {
    const data = unwrapData(payload);
    const item = firstPayloadItem(payload);
    const templateData = asObject(asArray(data.template_data)[0]);
    const sellerH5 = asObject(templateData.sellerH5);
    const bottomBarMain = asObject(templateData.bottomBarMainH5);
    const bottomSeller = asObject(bottomBarMain.seller);
    const graphicDetails = asObject(templateData.graphicDetailsV4);
    const headerBarMain = asObject(templateData.headerBarMainV2);
    const profitBarFollow = asObject(asObject(templateData.profitBarPopupH5).follow);
    const shop = asObject(firstNonEmpty(
      data.shop,
      data.seller,
      item.shop,
      item.seller,
      data.store,
      item.store,
      sellerH5,
      bottomSeller,
    ));
    const sellerId = String(firstNonEmpty(
      shop.seller_id,
      shop.sellerId,
      shop.seller_id_str,
      shop.id,
      data.seller_id,
      data.sellerId,
      item.seller_id,
      item.sellerId,
      sellerH5.id,
      sellerH5.sellerId,
      bottomSeller.sellerId,
      bottomSeller.id,
      graphicDetails.sellerId,
      headerBarMain.sellerId,
      profitBarFollow.sellerId,
    ) || "").trim();

    return {
      sellerId,
      shopName: cleanText(firstNonEmpty(
        sellerH5.name,
        shop.shopName,
        shop.shop_name,
        shop.name,
        shop.nickname,
        bottomSeller.name,
        data.shopName,
      )),
      shopLogo: String(firstNonEmpty(
        sellerH5.logo,
        bottomSeller.logo,
        shop.shopLogo,
        shop.shop_logo,
        shop.logo,
        shop.avatar,
        shop.image,
      ) || ""),
      shopGrade: String(firstNonEmpty(sellerH5.grade, shop.shopGrade, shop.shop_grade, shop.grade, shop.level) || ""),
      sellerScore: String(firstNonEmpty(sellerH5.sellerScore, sellerH5.seller_score, shop.sellerScore, shop.seller_score, shop.score) || ""),
      fansAmount: String(firstNonEmpty(sellerH5.fansAmount, sellerH5.fans_amount, shop.fansAmount, shop.fans_amount, shop.fans, shop.follower_count) || ""),
      salesVolume: String(firstNonEmpty(sellerH5.salesVolume, sellerH5.sales_volume, shop.salesVolume, shop.sales_volume, shop.sales, shop.sold_count) || ""),
      shopLink: String(firstNonEmpty(
        sellerH5.link,
        bottomSeller.link,
        shop.link,
        shop.shopLink,
        sellerId ? `https://www.xiaohongshu.com/vendor/${sellerId}` : "",
      ) || ""),
    };
  }

  function skuListFromPayload(payload) {
    const data = unwrapData(payload);
    return asArray(firstNonEmpty(data.skus, data.items, data.list, data.data, payload && payload.skus));
  }

  function extractProductsFromSkuListPayload(payload, sellerId) {
    return skuListFromPayload(payload).map((raw) => {
      const item = asObject(raw);
      const priceInfo = asObject(firstNonEmpty(item.price_info, item.priceInfo, item.price));
      const skuId = String(firstNonEmpty(item.sku_id, item.skuId, item.id) || "").trim();
      const itemId = String(firstNonEmpty(item.item_id, item.itemId, item.goods_id, item.goodsId, skuId) || "").trim();
      const name = cleanText(firstNonEmpty(item.name, item.card_title, item.title, item.desc, item.description));
      const originalPrice = firstPositivePrice(
        item.originalPrice,
        item.original_price,
        item.marketPrice,
        item.market_price,
        priceFromPriceInfo(priceInfo, ["minor_price", "origin_price", "market_price"]),
      );
      const dealPrice = firstPositivePrice(
        item.dealPrice,
        item.deal_price,
        item.salePrice,
        item.sale_price,
        priceFromPriceInfo(priceInfo, ["expected_price", "sale_price", "sku_price", "now_price"]),
        originalPrice,
      );
      const goodsId = itemId || skuId;

      return {
        sellerId: sellerId || "",
        skuId,
        itemId,
        name,
        originalPrice,
        dealPrice,
        stock: firstNonEmpty(item.stock, item.stock_num, item.stockNum, item.inventory, item.stock_status, item.stockStatus),
        stockStatus: String(firstNonEmpty(item.stock_status, item.stockStatus, item.stock_text) || ""),
        image: pickImage(firstNonEmpty(item.image, item.image_url, item.cover, item.images, item.imageInfo)),
        goodsUrl: firstNonEmpty(item.goodsUrl, item.goods_url, goodsId ? `https://www.xiaohongshu.com/goods-detail/${goodsId}` : ""),
        onShelfTime: String(firstNonEmpty(item.on_shelf_time, item.onShelfTime, item.create_time, item.createdAt) || ""),
      };
    }).filter((item) => item.itemId || item.skuId || item.name);
  }

  function mergeProductDetail(product, payload) {
    const item = firstPayloadItem(payload);
    const priceInfo = asObject(firstNonEmpty(item.price_info, item.priceInfo, item.price));
    const delivery = asObject(firstNonEmpty(item.delivery, item.delivery_info, item.logistics));
    const shop = asObject(firstNonEmpty(item.shop, item.seller, item.store));
    const soldText = String(firstNonEmpty(
      item.soldText,
      item.sold_text,
      item.sold_count_text,
      item.sales_text,
      item.sold_count,
      item.sales,
      asObject(item.sale_info).sold_count,
      asObject(item.saleInfo).soldCount,
    ) || "");
    const dealPrice = firstPositivePrice(
      priceFromPriceInfo(priceInfo, ["expected_price", "sale_price", "sku_price", "now_price"]),
      item.dealPrice,
      item.deal_price,
      product.dealPrice,
    );
    const originalPrice = firstPositivePrice(
      priceFromPriceInfo(priceInfo, ["minor_price", "origin_price", "market_price"]),
      item.originalPrice,
      item.original_price,
      product.originalPrice,
    );

    return {
      ...product,
      name: cleanText(firstNonEmpty(item.name, item.title, item.card_title, product.name)),
      originalPrice: originalPrice || product.originalPrice || 0,
      dealPrice: dealPrice || product.dealPrice || 0,
      soldCount: normalizeSoldCount(firstNonEmpty(item.soldCount, item.sold_count, item.sales, soldText)),
      soldText,
      location: cleanText(firstNonEmpty(delivery.from, delivery.location, delivery.address, item.location)),
      shippingFee: cleanText(firstNonEmpty(delivery.fee_text, delivery.feeText, delivery.fee, item.shippingFee)),
      shippingTime: cleanText(firstNonEmpty(delivery.time, delivery.time_text, delivery.delivery_time, item.shippingTime)),
      shippingTag: cleanText(firstNonEmpty(delivery.tag, delivery.tag_text, item.shippingTag)),
      image: pickImage(firstNonEmpty(item.image, item.image_url, item.cover, item.images, product.image)),
      stockStatus: cleanText(firstNonEmpty(item.stock_status, item.stockStatus, product.stockStatus)),
      shopName: cleanText(firstNonEmpty(shop.name, shop.shopName, product.shopName)),
      description: cleanText(firstNonEmpty(item.descriptionH5, item.description, item.desc, product.description)),
    };
  }

  function computeShopProductSummary(products) {
    const list = asArray(products);
    let totalSoldCount = 0;
    let totalSalesAmount = 0;
    for (const item of list) {
      const soldCount = normalizeSoldCount(item.soldCount);
      const dealPrice = normalizePrice(item.dealPrice);
      totalSoldCount += soldCount;
      totalSalesAmount += dealPrice * soldCount;
    }
    return {
      totalProducts: list.length,
      totalSoldCount,
      totalSalesAmount: Math.round(totalSalesAmount * 100) / 100,
    };
  }

  function normalizeCommentRecord(raw) {
    const item = asObject(raw);
    const rawId = String(firstNonEmpty(item.id, item.commentId, item.comment_id) || "").trim();
    const rawParentId = String(firstNonEmpty(item.parentId, item.parent_id) || "").trim();
    const content = cleanText(firstNonEmpty(item.content, item.text, item.noteText));
    const level = Number(item.level || (item.isReply ? 1 : 0));
    return {
      id: rawId.replace(/^comment-/, ""),
      parentId: rawParentId.replace(/^comment-/, ""),
      content,
      images: uniqueList(item.images),
      userName: cleanText(firstNonEmpty(item.userName, item.user_name, item.nickname, item.author)),
      isAuthor: !!item.isAuthor,
      date: cleanText(firstNonEmpty(item.date, item.time, item.createdAt)),
      likeCount: String(firstNonEmpty(item.likeCount, item.like_count, "") || ""),
      likeCountNumber: normalizeSoldCount(firstNonEmpty(item.likeCount, item.like_count)),
      isReply: level > 0 || !!rawParentId,
      level,
      replyToUser: cleanText(firstNonEmpty(item.replyToUser, item.reply_to_user)),
      parentContent: cleanText(item.parentContent),
    };
  }

  function attachParentContent(comments) {
    const parentContentById = new Map();
    for (const comment of asArray(comments)) {
      if (!comment.isReply && comment.id) parentContentById.set(comment.id, comment.content || "");
    }
    return asArray(comments).map((comment) => {
      if (!comment.isReply || comment.parentContent) return comment;
      return {
        ...comment,
        parentContent: parentContentById.get(comment.parentId) || "",
      };
    });
  }

  function queryText(base, selectors) {
    if (!base || !base.querySelector) return "";
    for (const selector of selectors) {
      const el = base.querySelector(selector);
      const text = cleanText(el && el.textContent);
      if (text) return text;
    }
    return "";
  }

  function queryImages(base) {
    if (!base || !base.querySelectorAll) return [];
    const nodes = base.querySelectorAll(".comment-picture img, .img-box img");
    return uniqueList(Array.from(nodes).map((img) => img.src || img.getAttribute("src") || ""));
  }

  function commentIdFromElement(el) {
    if (!el) return "";
    const id = el.id || el.getAttribute && el.getAttribute("id") || "";
    return String(id || "").replace(/^comment-/, "");
  }

  function extractCommentElement(el, level, parentId) {
    return normalizeCommentRecord({
      id: commentIdFromElement(el),
      parentId,
      content: queryText(el, [".content .note-text", ".content", ".note-text"]),
      images: queryImages(el),
      userName: queryText(el, [".author .name", ".user-name", ".nickname", ".name"]),
      isAuthor: !!(el && el.querySelector && el.querySelector(".author .tag")),
      date: queryText(el, [".info .date span", ".date", ".info .date"]),
      likeCount: queryText(el, [".like .count", ".like-count", ".count"]),
      level,
    });
  }

  function extractNoteInfoFromPage() {
    return {
      title: cleanText(queryText(document, [".note-content .title", ".title", "h1"]) || document.title || ""),
      author: cleanText(queryText(document, [".author-wrapper .name", ".author .name", ".user-name", ".nickname"])),
      url: String(location.href || ""),
    };
  }

  function getCommentScrollContainer() {
    return document.querySelector(".comments-container .list-container")
      || document.querySelector(".comments-container")
      || document.querySelector(".list-container")
      || document.scrollingElement
      || document.documentElement;
  }

  function wait(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function waitForCommentsContainer(timeoutMs) {
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
      const el = document.querySelector(".comments-container, .parent-comment, .comment-item");
      if (el) return el;
      await wait(250);
    }
    return null;
  }

  async function scrollComments(options) {
    const rounds = Math.max(1, Number(options && options.rounds) || 8);
    const pauseMs = Math.max(250, Number(options && options.pauseMs) || 650);
    const container = getCommentScrollContainer();
    let stable = 0;
    let lastCount = 0;
    for (let i = 0; i < rounds; i += 1) {
      const currentCount = document.querySelectorAll(".parent-comment, .comment-item").length;
      stable = currentCount <= lastCount ? stable + 1 : 0;
      lastCount = currentCount;
      if (stable >= 3) break;
      container.scrollTop = container.scrollHeight;
      window.scrollTo(0, document.body.scrollHeight);
      await wait(pauseMs);
    }
    return lastCount;
  }

  async function expandReplies(options) {
    const rounds = Math.max(1, Number(options && options.rounds) || 4);
    const pauseMs = Math.max(150, Number(options && options.pauseMs) || 300);
    let clicked = 0;
    for (let i = 0; i < rounds; i += 1) {
      const buttons = Array.from(document.querySelectorAll(".show-more"));
      const expandable = buttons.filter((btn) => /展开/.test(cleanText(btn.textContent)));
      if (!expandable.length) break;
      for (const btn of expandable.slice(0, 20)) {
        try {
          btn.click();
          clicked += 1;
        } catch (e) {
          // Ignore individual DOM click failures.
        }
      }
      await wait(pauseMs);
    }
    return clicked;
  }

  function extractCommentsFromDom(limit) {
    const comments = [];
    const parents = Array.from(document.querySelectorAll(".parent-comment"));
    if (parents.length) {
      for (const parent of parents) {
        const parentItem = parent.querySelector(":scope > .comment-item") || parent.querySelector(".comment-item");
        if (!parentItem) continue;
        const parentComment = extractCommentElement(parentItem, 0, "");
        if (!parentComment.content && !parentComment.userName) continue;
        comments.push(parentComment);
        const parentId = parentComment.id || commentIdFromElement(parent);
        for (const reply of Array.from(parent.querySelectorAll(".reply-container .comment-item-sub"))) {
          const replyComment = extractCommentElement(reply, 1, parentId);
          if (replyComment.content || replyComment.userName) comments.push(replyComment);
        }
      }
    } else {
      for (const el of Array.from(document.querySelectorAll(".comment-item, .comment-item-sub"))) {
        const comment = extractCommentElement(el, el.matches(".comment-item-sub") ? 1 : 0, "");
        if (comment.content || comment.userName) comments.push(comment);
      }
    }
    return attachParentContent(comments).slice(0, limit || 500);
  }

  async function extractComments(options) {
    const opts = asObject(options);
    const container = await waitForCommentsContainer(Number(opts.waitMs) || 5000);
    if (!container) {
      return { ok: false, error: "未找到评论区，请先打开笔记详情页并确认评论区已加载" };
    }
    const scrollCount = await scrollComments({ rounds: opts.scrollRounds || 8, pauseMs: opts.scrollPauseMs || 650 });
    const expandedReplies = await expandReplies({ rounds: opts.expandRounds || 4, pauseMs: opts.expandPauseMs || 300 });
    const comments = extractCommentsFromDom(Number(opts.limit) || 500);
    return {
      ok: true,
      version: API_VERSION,
      noteInfo: extractNoteInfoFromPage(),
      total: comments.length,
      scrollCount,
      expandedReplies,
      comments,
      extractedAt: new Date().toISOString(),
    };
  }

  function itemIdFromLocation() {
    return itemIdsFromGoodsUrl(String(location.href || ""))[0] || "";
  }

  function itemIdsFromGoodsUrl(rawUrl) {
    const ids = [];
    const add = (value) => {
      const id = String(value || "").trim();
      if (id && !ids.includes(id)) ids.push(id);
    };

    try {
      const url = new URL(String(rawUrl || ""), "https://www.xiaohongshu.com/");
      const pathMatch = url.pathname.match(/goods-detail\/([^/?#]+)/);
      if (pathMatch && pathMatch[1]) add(decodeURIComponent(pathMatch[1]));
      add(url.searchParams.get("item_id"));
      add(url.searchParams.get("itemId"));
      add(url.searchParams.get("goods_id"));

      let instation = url.searchParams.get("instation_link") || "";
      for (let i = 0; i < 3; i += 1) {
        try {
          const decoded = decodeURIComponent(instation);
          if (decoded === instation) break;
          instation = decoded;
        } catch (e) {
          break;
        }
      }
      const metaMatches = [
        instation.match(/(?:itemId|item_id)=([^&#]+)/),
        instation.match(/(?:itemId|item_id)%3D([^&#]+)/i),
      ];
      for (const meta of metaMatches) {
        if (meta && meta[1]) add(meta[1]);
      }
    } catch (e) {
      const fallbackMatch = String(rawUrl || "").match(/goods-detail\/([^/?#]+)/);
      if (fallbackMatch && fallbackMatch[1]) add(fallbackMatch[1]);
    }

    return ids;
  }

  function sellerIdFromPage() {
    const href = String(location.href || "");
    const vendorMatch = href.match(/\/vendor\/([^/?#]+)/);
    if (vendorMatch) return decodeURIComponent(vendorMatch[1]);
    const goods = asObject(root.__xhs_intercepted_goods__);
    const fromGoods = extractShopInfoFromGoodsPayload(goods).sellerId;
    if (fromGoods) return fromGoods;
    const text = document.body ? document.body.innerHTML.slice(0, 500000) : "";
    const match = text.match(/["']?(?:sellerId|seller_id)["']?\s*[:=]\s*["']?([A-Za-z0-9_-]{4,})/);
    return match ? match[1] : "";
  }

  async function fetchJson(url, headers) {
    const resp = await fetch(url, {
      method: "GET",
      credentials: "include",
      headers: headers || {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
      },
    });
    const text = await resp.text();
    let data = null;
    try {
      data = JSON.parse(text);
    } catch (e) {
      data = { rawText: text.slice(0, 500) };
    }
    if (!resp.ok) {
      const err = new Error(`HTTP ${resp.status}`);
      err.payload = data;
      throw err;
    }
    return data;
  }

  async function fetchDetail(itemId) {
    const url = `https://mall.xiaohongshu.com/api/store/jpd/edith/detail/h5/toc?version=0.0.5&item_id=${encodeURIComponent(itemId)}`;
    return fetchJson(url, {
      "Accept": "application/json, text/plain, */*",
      "Accept-Language": "zh-CN,zh;q=0.9",
      "detail-host": "https://www.xiaohongshu.com",
    });
  }

  async function fetchSkuPage(sellerId, page) {
    const url = `https://www.xiaohongshu.com/api/store/vs/${encodeURIComponent(sellerId)}/skus?page=${page}&filter_type=new_arrival&sort=new_arrival&anti_crawler=1`;
    return fetchJson(url, {
      "Accept": "application/json, text/plain, */*",
      "Accept-Language": "zh-CN,zh;q=0.9",
      "Referer": `https://www.xiaohongshu.com/vendor/${encodeURIComponent(sellerId)}`,
    });
  }

  async function extractShopProducts(options) {
    const opts = asObject(options);
    const maxPages = Math.max(1, Number(opts.maxPages) || 5);
    const maxDetailCount = Math.max(0, Number(opts.maxDetailCount) || 20);
    let shopInfo = extractShopInfoFromGoodsPayload(root.__xhs_intercepted_goods__);
    let sellerId = shopInfo.sellerId || sellerIdFromPage();
    const currentItemIds = itemIdsFromGoodsUrl(String(location.href || ""));
    const warnings = [];

    if (!sellerId && currentItemIds.length) {
      for (const currentItemId of currentItemIds) {
        try {
          const detailPayload = await fetchDetail(currentItemId);
          shopInfo = extractShopInfoFromGoodsPayload(detailPayload);
          sellerId = shopInfo.sellerId;
          if (sellerId) break;
          warnings.push(`商品 ${currentItemId} 详情未返回店铺 ID`);
        } catch (e) {
          warnings.push(`商品 ${currentItemId} 详情接口失败：${e.message || e}`);
        }
      }
    }

    if (!sellerId) {
      return {
        ok: false,
        error: "未识别到店铺 ID，请先打开小红书商品详情页或店铺页再试",
        warnings,
      };
    }

    if (!shopInfo.sellerId) shopInfo = { ...shopInfo, sellerId, shopLink: `https://www.xiaohongshu.com/vendor/${sellerId}` };

    const products = [];
    for (let page = 0; page < maxPages; page += 1) {
      const payload = await fetchSkuPage(sellerId, page);
      const pageProducts = extractProductsFromSkuListPayload(payload, sellerId);
      products.push(...pageProducts);
      if (pageProducts.length < 20) break;
      await wait(250);
    }

    const detailed = [];
    for (const product of products) {
      if (detailed.length >= maxDetailCount) {
        detailed.push(product);
        continue;
      }
      const detailId = product.itemId || product.skuId;
      if (!detailId) {
        detailed.push(product);
        continue;
      }
      try {
        const detailPayload = await fetchDetail(detailId);
        detailed.push(mergeProductDetail(product, detailPayload));
      } catch (e) {
        warnings.push(`商品 ${detailId} 详情失败：${e.message || e}`);
        detailed.push(product);
      }
      await wait(250);
    }

    return {
      ok: true,
      version: API_VERSION,
      shopInfo,
      products: detailed,
      summary: computeShopProductSummary(detailed),
      warnings,
      extractedAt: new Date().toISOString(),
    };
  }

  const api = {
    version: API_VERSION,
    normalizeSoldCount,
    extractShopInfoFromGoodsPayload,
    extractProductsFromSkuListPayload,
    mergeProductDetail,
    computeShopProductSummary,
    itemIdsFromGoodsUrl,
    normalizeCommentRecord,
    attachParentContent,
    extractComments,
    extractShopProducts,
  };

  root.__xhsCommercePrototype = api;

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);

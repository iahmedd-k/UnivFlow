// Uniflow Academic Companion - Background Service Worker (Manifest V3) (v1.3.7)

const DEFAULT_PRODUCTION_API = "https://univlfow.koreacentral.cloudapp.azure.com/api/v1";

// Helper: Normalize any backend URL to guarantee /api/v1 prefix without duplicate slashes
function normalizeApiUrl(rawUrl) {
  if (!rawUrl || typeof rawUrl !== "string") return DEFAULT_PRODUCTION_API;
  let clean = rawUrl.trim().replace(/\/+$/, "");
  if (!clean.endsWith("/api/v1")) {
    clean = `${clean}/api/v1`;
  }
  return clean;
}

// Store connection state locally
async function getStoredState() {
  return new Promise((resolve) => {
    chrome.storage.local.get(
      ["uniflowApiUrl", "uniflowAuthToken", "claudeConnected", "portalConnected", "gcrConnected", "uniflowGcrCookieFingerprint"],
      (data) => resolve(data || {})
    );
  });
}

async function setStoredState(updates) {
  return new Promise((resolve) => {
    chrome.storage.local.set(updates, () => resolve(true));
  });
}

async function fingerprintGoogleCookies(cookies) {
  const canonicalCookies = (cookies || [])
    .map((cookie) => ({
      name: cookie.name || "",
      value: cookie.value || "",
      domain: cookie.domain || "",
      path: cookie.path || "/",
      secure: Boolean(cookie.secure),
      httpOnly: Boolean(cookie.httpOnly),
      sameSite: cookie.sameSite || "unspecified",
    }))
    .sort((left, right) => `${left.domain}\n${left.path}\n${left.name}`.localeCompare(`${right.domain}\n${right.path}\n${right.name}`));
  const bytes = new TextEncoder().encode(JSON.stringify(canonicalCookies));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function syncGoogleCookiesToBackend(cookies, userAgent, apiUrl, token, { skipUnchanged = false } = {}) {
  const fingerprint = await fingerprintGoogleCookies(cookies);
  const previousFingerprint = (await getStoredState()).uniflowGcrCookieFingerprint;
  if (skipUnchanged && fingerprint === previousFingerprint) return { unchanged: true };

  const result = await sendToBackend(
    "/classroom/gcr-browser/sync-session",
    { cookies, user_agent: userAgent },
    apiUrl,
    token,
  );
  await setStoredState({ uniflowGcrCookieFingerprint: fingerprint });
  return result;
}

const GOOGLE_AUTH_NAMES = new Set([
  "OSID", "SID", "HSID", "SSID", "APISID", "SAPISID", "SIDCC",
  "__Secure-1PSID", "__Secure-3PSID", "__Secure-1PAPISID", "__Secure-3PAPISID",
  "__Secure-OSID", "__Secure-1PSIDCC", "__Secure-3PSIDCC"
]);

function hasGoogleAuthCookie(cookies) {
  return (cookies || []).some((c) => {
    const n = c?.name || "";
    return GOOGLE_AUTH_NAMES.has(n) || n.startsWith("__Secure-");
  });
}

// 1. Fetch Google Classroom, Accounts, and Google Drive/Docs auth cookies (targeted domain queries only)
async function getGoogleClassroomCookies() {
  const querySpecs = [
    { domain: ".google.com" },
    { domain: "google.com" },
    { domain: ".classroom.google.com" },
    { domain: "classroom.google.com" },
    { domain: ".accounts.google.com" },
    { domain: "accounts.google.com" },
    { domain: ".drive.google.com" },
    { domain: "drive.google.com" },
    { domain: ".docs.google.com" },
    { domain: "docs.google.com" },
    { url: "https://classroom.google.com" },
    { url: "https://accounts.google.com" },
    { url: "https://drive.google.com" },
    { url: "https://docs.google.com" },
  ];

  const results = await Promise.allSettled(
    querySpecs.map((spec) => {
      try {
        return chrome.cookies.getAll(spec);
      } catch (err) {
        return Promise.resolve([]);
      }
    })
  );

  const combined = results.flatMap((r) => (r.status === "fulfilled" && Array.isArray(r.value) ? r.value : []));
  const unique = [];
  const seen = new Set();
  for (const c of combined) {
    if (!c || !c.name || !c.domain) continue;
    const key = `${c.name}@${c.domain}${c.path || ""}`;
    if (!seen.has(key)) {
      seen.add(key);
      unique.push(c);
    }
  }

  // Filter to all Google-related domains (Classroom, Drive, Docs, Accounts, top-level Google)
  const googleCookies = unique.filter((c) => {
    const dom = (c.domain || "").toLowerCase();
    return (
      dom === "google.com" ||
      dom === ".google.com" ||
      dom.endsWith(".google.com")
    );
  });

  return googleCookies.map((c) => ({
    name: c.name,
    value: c.value,
    domain: c.domain,
    path: c.path || "/",
    secure: Boolean(c.secure),
    httpOnly: Boolean(c.httpOnly),
    sameSite: c.sameSite || "unspecified",
  }));
}

// 2. Fetch Claude sessionKey
async function getClaudeSessionKey() {
  const cookie = await chrome.cookies.get({ url: "https://claude.ai", name: "sessionKey" });
  return cookie && cookie.value ? cookie.value : null;
}

// 3. Fetch Portal cookies
async function getPortalCookies() {
  const cookies = await chrome.cookies.getAll({ domain: "portals.au.edu.pk" });
  if (!cookies || cookies.length === 0) return null;
  return cookies.map((c) => `${c.name}=${c.value}`).join("; ");
}

// 4. Auto-visit a URL and wait for target cookies
async function autoVisitAndExtract(service, maxWaitMs = 15000) {
  let targetUrl = "https://classroom.google.com";
  if (service === "claude") targetUrl = "https://claude.ai";
  if (service === "portal") targetUrl = "https://portals.au.edu.pk/students/";

  const tab = await chrome.tabs.create({ url: targetUrl, active: true });

  const startTime = Date.now();
  while (Date.now() - startTime < maxWaitMs) {
    await new Promise((r) => setTimeout(r, 1200));

    if (service === "gcr") {
      const cookies = await getGoogleClassroomCookies();
      if (cookies.length >= 2 && hasGoogleAuthCookie(cookies)) {
        return { success: true, cookies, tabId: tab.id };
      }
    } else if (service === "claude") {
      const key = await getClaudeSessionKey();
      if (key) {
        return { success: true, sessionKey: key, tabId: tab.id };
      }
    } else if (service === "portal") {
      const pCookies = await getPortalCookies();
      if (pCookies && pCookies.includes("ASP.NET_SessionId")) {
        return { success: true, cookies: pCookies, tabId: tab.id };
      }
    }
  }

  return { success: false, error: `Timed out waiting for ${service} login cookies`, tabId: tab.id };
}

// Helper: Verify if a Clerk JWT or manual token has expired
function isTokenExpired(token) {
  if (!token || typeof token !== "string") return true;
  try {
    const raw = token.startsWith("Bearer ") ? token.slice(7).trim() : token.trim();
    const parts = raw.split(".");
    if (parts.length < 2) return true;
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    const payload = JSON.parse(jsonPayload);
    if (!payload.exp) return false;
    return payload.exp * 1000 <= Date.now() + 10000;
  } catch (e) {
    return true;
  }
}

// Helper: Auto-detect fresh, non-expired JWT session token from browser cookies (__session or uniflow_manual_token)
async function detectFreshAuthToken(baseUrl) {
  try {
    const candidateCookieNames = ["__session", "uniflow_manual_token"];

    for (const cookieName of candidateCookieNames) {
      // 1. Direct query across all domains
      const cookies = await chrome.cookies.getAll({ name: cookieName });
      if (cookies && cookies.length > 0) {
        const valid = cookies.filter((c) => c.value && !isTokenExpired(c.value));
        if (valid.length > 0) {
          let targetHost = "";
          try { targetHost = new URL(baseUrl).hostname; } catch (_) {}
          const best =
            valid.find((c) => targetHost && c.domain && c.domain.includes(targetHost)) ||
            valid.find((c) => c.domain && (
              c.domain.includes("vercel.app") ||
              c.domain.includes("localhost") ||
              c.domain.includes("127.0.0.1") ||
              c.domain.includes("cloudapp.azure.com") ||
              c.domain.includes("univlfow")
            )) ||
            valid[0];
          if (best && best.value) return best.value;
        }
      }
    }
  } catch (e) {
    console.debug("detectFreshAuthToken error:", e);
  }
  return null;
}

// 5. Send synced cookies to Uniflow backend with auto-token detection and 401 retry
async function sendToBackend(endpoint, payload, baseUrl, token) {
  const normalizedBase = normalizeApiUrl(baseUrl || (await getStoredState()).uniflowApiUrl);
  const cleanEndpoint = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
  const fullUrl = `${normalizedBase}${cleanEndpoint}`;

  let activeToken = token;
  if (!activeToken || isTokenExpired(activeToken)) {
    const detected = await detectFreshAuthToken(baseUrl || normalizedBase);
    if (detected) activeToken = detected;
  }

  const makeRequest = async (tok) => {
    const headers = { "Content-Type": "application/json" };
    if (tok) {
      const cleanTok = tok.startsWith("Bearer ") ? tok.slice(7).trim() : tok.trim();
      headers["Authorization"] = `Bearer ${cleanTok}`;
      headers["X-Manual-Auth-Token"] = cleanTok;
    }
    return fetch(fullUrl, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
  };

  let resp = await makeRequest(activeToken);

  // If 401 Unauthorized, detect fresh token and retry once
  if (resp.status === 401) {
    const freshToken = await detectFreshAuthToken(baseUrl || normalizedBase);
    if (freshToken && freshToken !== activeToken) {
      activeToken = freshToken;
      resp = await makeRequest(freshToken);
      if (resp.ok) {
        await setStoredState({ uniflowAuthToken: freshToken });
      }
    }
  }

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    if (resp.status === 401) {
      throw new Error(
        "Authentication token has expired. Please open or refresh your Uniflow web dashboard, or click '1-Click Sync' from Settings."
      );
    }
    throw new Error(err.detail || `Server error ${resp.status}`);
  }
  return resp.json();
}

// Message handler for Content Scripts and Popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  const { action, payload } = request;

  (async () => {
    try {
      const state = await getStoredState();
      const apiUrl = normalizeApiUrl(payload?.apiUrl || state.uniflowApiUrl);
      const token = payload?.token || state.uniflowAuthToken || "";

      if (action === "PING") {
        sendResponse({ success: true, version: chrome.runtime.getManifest()?.version || "1.3.7" });
      } else if (action === "DETECT_AUTH_TOKEN") {
        const detected = await detectFreshAuthToken(payload?.apiUrl || apiUrl);
        if (detected) {
          await setStoredState({ uniflowAuthToken: detected });
          sendResponse({ success: true, token: detected });
        } else {
          sendResponse({ success: false, error: "No active Uniflow __session or manual auth cookie found in browser." });
        }
      } else if (action === "SET_CONFIG") {
        await setStoredState({
          ...(payload?.apiUrl ? { uniflowApiUrl: normalizeApiUrl(payload.apiUrl) } : {}),
          ...(payload?.token ? { uniflowAuthToken: payload.token } : {}),
        });
        sendResponse({ success: true });
      } else if (action === "GET_STATUS") {
        const [gcr, claude, portal] = await Promise.all([
          getGoogleClassroomCookies(),
          getClaudeSessionKey(),
          getPortalCookies(),
        ]);
        sendResponse({
          success: true,
          version: chrome.runtime.getManifest()?.version || "1.3.7",
          status: {
            gcrCount: gcr.length,
            claudeConnected: Boolean(claude || state.claudeConnected),
            portalConnected: Boolean(portal || state.portalConnected),
            hasGcr: gcr.length > 0 && hasGoogleAuthCookie(gcr),
            hasClaude: Boolean(claude),
            hasPortal: Boolean(portal),
          },
        });
      } else if (action === "SYNC_GCR") {
        let cookies = await getGoogleClassroomCookies();
        let autoVisited = false;

        if ((!cookies || cookies.length === 0 || !hasGoogleAuthCookie(cookies)) && payload?.autoVisit) {
          const visitRes = await autoVisitAndExtract("gcr", 20000);
          if (visitRes.success) {
            cookies = visitRes.cookies;
            autoVisited = true;
          }
        }

        if (!cookies || cookies.length === 0 || !hasGoogleAuthCookie(cookies)) {
          sendResponse({
            success: false,
            needsLogin: true,
            error: "No Google Classroom session cookies found. Please log into classroom.google.com.",
          });
          return;
        }

        const res = await syncGoogleCookiesToBackend(cookies, navigator.userAgent, apiUrl, token);
        await setStoredState({
          gcrConnected: true,
          uniflowApiUrl: apiUrl,
          ...(token ? { uniflowAuthToken: token } : {}),
        });
        sendResponse({ success: true, message: res.message || "Classroom session synced!", count: cookies.length, autoVisited });
      } else if (action === "AUTO_VISIT_GCR") {
        const visitRes = await autoVisitAndExtract("gcr", 25000);
        if (!visitRes.success) {
          sendResponse({ success: false, error: visitRes.error });
          return;
        }
        const res = await syncGoogleCookiesToBackend(visitRes.cookies, navigator.userAgent, apiUrl, token);
        await setStoredState({
          gcrConnected: true,
          uniflowApiUrl: apiUrl,
          ...(token ? { uniflowAuthToken: token } : {}),
        });
        sendResponse({ success: true, message: res.message || "Classroom session captured & synced!" });
      } else if (action === "SYNC_SELECTED") {
        const results = { gcr: null, claude: null, portal: null };
        const forceClaude = Boolean(payload?.forceClaude);
        const forcePortal = Boolean(payload?.forcePortal);

        await setStoredState({
          ...(apiUrl ? { uniflowApiUrl: apiUrl } : {}),
          ...(token ? { uniflowAuthToken: token } : {}),
        });

        // 1. Google Classroom
        if (payload?.syncGcr !== false) {
          let gcrCookies = await getGoogleClassroomCookies();
          if ((!gcrCookies || gcrCookies.length === 0 || !hasGoogleAuthCookie(gcrCookies)) && payload?.autoVisit) {
            const vRes = await autoVisitAndExtract("gcr", 15000);
            if (vRes.success) gcrCookies = vRes.cookies;
          }
          if (gcrCookies && gcrCookies.length > 0 && hasGoogleAuthCookie(gcrCookies)) {
            results.gcr = await syncGoogleCookiesToBackend(gcrCookies, navigator.userAgent, apiUrl, token);
            await setStoredState({ gcrConnected: true });
          } else {
            results.gcr = { skipped: true, reason: "No active Google Classroom cookies found in browser" };
          }
        }

        // 2. Claude (only fetch if not connected before or forced)
        const claudeAlreadyConnected = Boolean(payload?.claudeAlreadyConnected ?? state.claudeConnected);
        if (payload?.syncClaude && (!claudeAlreadyConnected || forceClaude)) {
          let key = await getClaudeSessionKey();
          if (!key && payload?.autoVisit) {
            const vRes = await autoVisitAndExtract("claude", 15000);
            if (vRes.success) key = vRes.sessionKey;
          }
          if (key) {
            results.claude = await sendToBackend(
              "/classroom/claude-browser/sync-session",
              { session_key: key, user_agent: navigator.userAgent },
              apiUrl,
              token
            );
            await setStoredState({ claudeConnected: true });
          } else {
            results.claude = { skipped: true, reason: "No sessionKey found" };
          }
        } else {
          results.claude = { skipped: true, reason: "Claude already connected (kept active)" };
        }

        // 3. Portal (only fetch if not connected before or forced)
        const portalAlreadyConnected = Boolean(payload?.portalAlreadyConnected ?? state.portalConnected);
        if (payload?.syncPortal && (!portalAlreadyConnected || forcePortal)) {
          let pCookies = await getPortalCookies();
          if (!pCookies && payload?.autoVisit) {
            const vRes = await autoVisitAndExtract("portal", 15000);
            if (vRes.success) pCookies = vRes.cookies;
          }
          if (pCookies) {
            results.portal = await sendToBackend(
              "/portal/sync-cookies",
              { cookies: pCookies },
              apiUrl,
              token
            );
            await setStoredState({ portalConnected: true });
          } else {
            results.portal = { skipped: true, reason: "No portal cookies found" };
          }
        } else {
          results.portal = { skipped: true, reason: "Portal already connected (kept active)" };
        }

        sendResponse({ success: true, results });
      } else if (action === "TURN_IN_CLASSROOM") {
        const classroomUrl = payload?.classroom_url || payload?.url;
        const assignmentId = payload?.assignment_id;
        if (!classroomUrl) {
          sendResponse({ success: false, error: "Missing classroom_url" });
          return;
        }

        const cleanTarget = classroomUrl.split("?")[0].replace(/\/+$/, "");
        const tabs = await chrome.tabs.query({ url: "*://classroom.google.com/*" });
        let targetTab = tabs.find((t) => t.url && t.url.includes(cleanTarget));

        if (!targetTab) {
          targetTab = await chrome.tabs.create({ url: classroomUrl, active: true });
          await new Promise((resolve) => {
            const listener = (tabId, info) => {
              if (tabId === targetTab.id && info.status === "complete") {
                chrome.tabs.onUpdated.removeListener(listener);
                resolve();
              }
            };
            chrome.tabs.onUpdated.addListener(listener);
            setTimeout(resolve, 8000);
          });
        } else {
          await chrome.tabs.update(targetTab.id, { url: classroomUrl, active: true });
          await new Promise((resolve) => {
            const listener = (tabId, info) => {
              if (tabId === targetTab.id && info.status === "complete") {
                chrome.tabs.onUpdated.removeListener(listener);
                resolve();
              }
            };
            chrome.tabs.onUpdated.addListener(listener);
            setTimeout(resolve, 4000);
          });
        }

        await new Promise((r) => setTimeout(r, 1200));

        let turnInResult = null;
        try {
          turnInResult = await chrome.tabs.sendMessage(targetTab.id, { action: "CLASSROOM_CLICK_TURN_IN" });
        } catch (msgErr) {
          try {
            await chrome.scripting.executeScript({
              target: { tabId: targetTab.id },
              files: ["classroom_content.js"],
            });
            await new Promise((r) => setTimeout(r, 800));
            turnInResult = await chrome.tabs.sendMessage(targetTab.id, { action: "CLASSROOM_CLICK_TURN_IN" });
          } catch (e) {
            turnInResult = { success: false, error: "Could not execute turn-in on Classroom page: " + e.message };
          }
        }

        if (turnInResult?.success && assignmentId) {
          try {
            await sendToBackend(
              `/classroom/assignments/${assignmentId}/confirm-turn-in`,
              {},
              apiUrl,
              token
            );
          } catch (backendErr) {
            console.warn("Could not confirm turn-in with backend:", backendErr);
          }
        }

        sendResponse(turnInResult || { success: false, error: "Unknown turn-in error" });
      } else if (action === "OPEN_CLASSROOM_TAB") {
        const classroomUrl = payload?.classroom_url || payload?.url || "https://classroom.google.com";
        const tab = await chrome.tabs.create({ url: classroomUrl, active: true });
        sendResponse({ success: true, tabId: tab.id });
      } else {
        sendResponse({ success: false, error: `Unknown action: ${action}` });
      }
    } catch (err) {
      sendResponse({ success: false, error: err.message });
    }
  })();

  return true; // Keep message channel open for async response
});

// ==========================================
// BACKGROUND AUTOMATIC SESSION AUTO-RENEWAL
// ==========================================
const autoRenewTimers = {
  gcr: null,
  claude: null,
  portal: null,
};

chrome.cookies.onChanged.addListener((changeInfo) => {
  if (changeInfo.removed) return;

  const cookie = changeInfo.cookie;
  if (!cookie) return;

  const domain = (cookie.domain || "").toLowerCase();
  const name = cookie.name || "";

  const isGoogleAuth =
    (domain.includes("google.com") || domain.includes("classroom.google.com")) &&
    (GOOGLE_AUTH_NAMES.has(name) || name.startsWith("__Secure-"));

  const isClaudeAuth = domain.includes("claude.ai") && name === "sessionKey";
  const isPortalAuth = domain.includes("portals.au.edu.pk") && (name.includes("Session") || name.includes("ASP"));

  if (!isGoogleAuth && !isClaudeAuth && !isPortalAuth) return;

  // 1. Google Classroom Auto-Renew
  if (isGoogleAuth) {
    if (autoRenewTimers.gcr) clearTimeout(autoRenewTimers.gcr);
    autoRenewTimers.gcr = setTimeout(async () => {
      try {
        const state = await getStoredState();
        if (state.gcrConnected) {
          const apiUrl = normalizeApiUrl(state.uniflowApiUrl);
          let token = state.uniflowAuthToken;
          if (!token || isTokenExpired(token)) {
            token = await detectFreshAuthToken(apiUrl);
          }
          if (token) {
            const cookies = await getGoogleClassroomCookies();
            if (cookies && cookies.length > 0 && hasGoogleAuthCookie(cookies)) {
              const result = await syncGoogleCookiesToBackend(
                cookies,
                navigator.userAgent,
                apiUrl,
                token,
                { skipUnchanged: true },
              );
              if (!result.unchanged) console.log("[Uniflow Companion] Auto-renewed Google Classroom session in background.");
            }
          }
        }
      } catch (err) {
        console.warn("[Uniflow Companion] Auto-renew GCR warning:", err.message);
      }
    }, 6000);
  }

  // 2. Claude.ai Auto-Renew
  if (isClaudeAuth) {
    if (autoRenewTimers.claude) clearTimeout(autoRenewTimers.claude);
    autoRenewTimers.claude = setTimeout(async () => {
      try {
        const state = await getStoredState();
        if (state.claudeConnected) {
          const apiUrl = normalizeApiUrl(state.uniflowApiUrl);
          let token = state.uniflowAuthToken;
          if (!token || isTokenExpired(token)) {
            token = await detectFreshAuthToken(apiUrl);
          }
          if (token) {
            const key = await getClaudeSessionKey();
            if (key) {
              await sendToBackend(
                "/classroom/claude-browser/sync-session",
                { session_key: key, user_agent: navigator.userAgent },
                apiUrl,
                token
              );
              console.log("[Uniflow Companion] Auto-renewed Claude session in background.");
            }
          }
        }
      } catch (err) {
        console.warn("[Uniflow Companion] Auto-renew Claude warning:", err.message);
      }
    }, 6000);
  }

  // 3. University Portal Auto-Renew
  if (isPortalAuth) {
    if (autoRenewTimers.portal) clearTimeout(autoRenewTimers.portal);
    autoRenewTimers.portal = setTimeout(async () => {
      try {
        const state = await getStoredState();
        if (state.portalConnected) {
          const apiUrl = normalizeApiUrl(state.uniflowApiUrl);
          let token = state.uniflowAuthToken;
          if (!token || isTokenExpired(token)) {
            token = await detectFreshAuthToken(apiUrl);
          }
          if (token) {
            const cookies = await getPortalCookies();
            if (cookies) {
              await sendToBackend(
                "/portal/sync-cookies",
                { cookies },
                apiUrl,
                token
              );
              console.log("[Uniflow Companion] Auto-renewed Portal session in background.");
            }
          }
        }
      } catch (err) {
        console.warn("[Uniflow Companion] Auto-renew Portal warning:", err.message);
      }
    }, 6000);
  }
});

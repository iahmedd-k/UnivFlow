// Uniflow Academic Companion - Background Service Worker (Manifest V3)

// Store connection state locally
async function getStoredState() {
  return new Promise((resolve) => {
    chrome.storage.local.get(
      ["uniflowApiUrl", "uniflowAuthToken", "claudeConnected", "portalConnected", "gcrConnected"],
      (data) => resolve(data || {})
    );
  });
}

async function setStoredState(updates) {
  return new Promise((resolve) => {
    chrome.storage.local.set(updates, () => resolve(true));
  });
}

// 1. Fetch Google Classroom auth cookies
async function getGoogleClassroomCookies() {
  const gCookies = await chrome.cookies.getAll({ domain: "google.com" });
  const cCookies = await chrome.cookies.getAll({ url: "https://classroom.google.com" });
  const combined = [...(gCookies || []), ...(cCookies || [])];
  const unique = [];
  const seen = new Set();
  for (const c of combined) {
    const key = `${c.name}@${c.domain}`;
    if (!seen.has(key)) {
      seen.add(key);
      unique.push(c);
    }
  }

  const authCookies = unique.filter((c) => {
    const n = c.name;
    return (
      n === "OSID" || n === "SID" || n === "HSID" || n === "SSID" ||
      n === "APISID" || n === "SAPISID" || n === "SIDCC" ||
      n.startsWith("__Secure-")
    );
  });

  return authCookies.map((c) => ({
    name: c.name,
    value: c.value,
    domain: c.domain,
    path: c.path,
    secure: c.secure,
    httpOnly: c.httpOnly,
    sameSite: c.sameSite,
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

  // Create an active tab to visit the service
  const tab = await chrome.tabs.create({ url: targetUrl, active: true });

  const startTime = Date.now();
  while (Date.now() - startTime < maxWaitMs) {
    await new Promise((r) => setTimeout(r, 1200));

    if (service === "gcr") {
      const cookies = await getGoogleClassroomCookies();
      if (cookies.length >= 2) {
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

// Helper: Verify if a Clerk JWT token has expired
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
    // Expired or expiring within 10 seconds
    return payload.exp * 1000 <= Date.now() + 10000;
  } catch (e) {
    return true;
  }
}

// Helper: Auto-detect fresh, non-expired Clerk JWT session token from browser cookies
async function detectFreshAuthToken(baseUrl) {
  try {
    // 1. Check exact baseUrl domain for __session cookie
    if (baseUrl) {
      try {
        const u = new URL(baseUrl);
        const cookie = await chrome.cookies.get({ url: u.origin, name: "__session" });
        if (cookie && cookie.value && !isTokenExpired(cookie.value)) {
          return cookie.value;
        }
      } catch (_) {}
    }

    // 2. Query all __session cookies across all domains
    const sessionCookies = await chrome.cookies.getAll({ name: "__session" });
    if (sessionCookies && sessionCookies.length > 0) {
      // Filter out any expired tokens
      const validCookies = sessionCookies.filter((c) => c.value && !isTokenExpired(c.value));
      if (validCookies.length > 0) {
        let targetHost = "";
        try { targetHost = new URL(baseUrl).hostname; } catch (_) {}
        const best = validCookies.find((c) => targetHost && c.domain && c.domain.includes(targetHost))
          || validCookies.find((c) => c.domain && (c.domain.includes("cloudapp.azure.com") || c.domain.includes("univlfow") || c.domain.includes("vercel.app") || c.domain.includes("localhost")))
          || validCookies[0];
        if (best && best.value) return best.value;
      }
    }
  } catch (e) {
    console.debug("detectFreshAuthToken error:", e);
  }
  return null;
}

// 5. Send synced cookies to Uniflow backend with auto-token detection and 401 retry
async function sendToBackend(endpoint, payload, baseUrl, token) {
  if (!baseUrl) throw new Error("Uniflow Backend URL not configured.");
  const cleanBase = baseUrl.replace(/\/+$/, "");

  let activeToken = token;
  // If no token or provided token is expired, auto-detect a fresh one!
  if (!activeToken || isTokenExpired(activeToken)) {
    const detected = await detectFreshAuthToken(baseUrl);
    if (detected) activeToken = detected;
  }

  const makeRequest = async (tok) => {
    const headers = { "Content-Type": "application/json" };
    if (tok) {
      headers["Authorization"] = tok.startsWith("Bearer ") ? tok : `Bearer ${tok}`;
    }
    return fetch(`${cleanBase}${endpoint}`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
  };

  let resp = await makeRequest(activeToken);

  // If 401 Unauthorized (e.g. token expired), try to auto-detect a fresh token and retry once
  if (resp.status === 401) {
    const freshToken = await detectFreshAuthToken(baseUrl);
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
      const apiUrl = payload?.apiUrl || state.uniflowApiUrl || "http://localhost:8000";
      const token = payload?.token || state.uniflowAuthToken || "";

      if (action === "PING") {
        sendResponse({ success: true, version: "1.3.1" });
      } else if (action === "DETECT_AUTH_TOKEN") {
        const detected = await detectFreshAuthToken(payload?.apiUrl || apiUrl);
        if (detected) {
          await setStoredState({ uniflowAuthToken: detected });
          sendResponse({ success: true, token: detected });
        } else {
          sendResponse({ success: false, error: "No active Uniflow __session cookie found in browser." });
        }
      } else if (action === "SET_CONFIG") {
        await setStoredState({
          ...(payload?.apiUrl ? { uniflowApiUrl: payload.apiUrl } : {}),
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
          version: "1.3.0",
          status: {
            gcrCount: gcr.length,
            claudeConnected: Boolean(claude || state.claudeConnected),
            portalConnected: Boolean(portal || state.portalConnected),
            hasGcr: gcr.length > 0,
            hasClaude: Boolean(claude),
            hasPortal: Boolean(portal),
          },
        });
      } else if (action === "SYNC_GCR") {
        let cookies = await getGoogleClassroomCookies();
        let autoVisited = false;

        // If autoVisit requested or no cookies found and autoVisit allowed
        if ((!cookies || cookies.length === 0) && payload?.autoVisit) {
          const visitRes = await autoVisitAndExtract("gcr", 20000);
          if (visitRes.success) {
            cookies = visitRes.cookies;
            autoVisited = true;
          }
        }

        if (!cookies || cookies.length === 0) {
          sendResponse({
            success: false,
            needsLogin: true,
            error: "No Google Classroom session cookies found. Please log into classroom.google.com.",
          });
          return;
        }

        const res = await sendToBackend(
          "/classroom/gcr-browser/sync-session",
          { cookies, user_agent: navigator.userAgent },
          apiUrl,
          token
        );
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
        const res = await sendToBackend(
          "/classroom/gcr-browser/sync-session",
          { cookies: visitRes.cookies, user_agent: navigator.userAgent },
          apiUrl,
          token
        );
        await setStoredState({
          gcrConnected: true,
          uniflowApiUrl: apiUrl,
          ...(token ? { uniflowAuthToken: token } : {}),
        });
        sendResponse({ success: true, message: res.message || "Classroom session captured & synced!" });
      } else if (action === "SYNC_SELECTED") {
        // Enforce rule: Portal and Claude should only be fetched if not connected before!
        const results = { gcr: null, claude: null, portal: null };
        const forceClaude = Boolean(payload?.forceClaude);
        const forcePortal = Boolean(payload?.forcePortal);

        // Store apiUrl and token for background auto-renewal
        await setStoredState({
          ...(apiUrl ? { uniflowApiUrl: apiUrl } : {}),
          ...(token ? { uniflowAuthToken: token } : {}),
        });

        // 1. Google Classroom
        if (payload?.syncGcr !== false) {
          let gcrCookies = await getGoogleClassroomCookies();
          if ((!gcrCookies || gcrCookies.length === 0) && payload?.autoVisit) {
            const vRes = await autoVisitAndExtract("gcr", 15000);
            if (vRes.success) gcrCookies = vRes.cookies;
          }
          if (gcrCookies && gcrCookies.length > 0) {
            results.gcr = await sendToBackend(
              "/classroom/gcr-browser/sync-session",
              { cookies: gcrCookies, user_agent: navigator.userAgent },
              apiUrl,
              token
            );
            await setStoredState({ gcrConnected: true });
          } else {
            results.gcr = { skipped: true, reason: "No cookies found in browser" };
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
// Watches active browser cookies. When Google Classroom, Claude, or Student Portal
// sessions rotate during normal browsing, automatically and silently synchronizes
// fresh cookies to the Uniflow backend.
const autoRenewTimers = {
  gcr: null,
  claude: null,
  portal: null,
};

chrome.cookies.onChanged.addListener((changeInfo) => {
  if (changeInfo.removed) return; // Ignore deletions / expirations

  const cookie = changeInfo.cookie;
  if (!cookie) return;

  const domain = (cookie.domain || "").toLowerCase();
  const name = cookie.name || "";

  const isGoogleAuth =
    (domain.includes("google.com") || domain.includes("classroom.google.com")) &&
    (name === "OSID" || name === "SID" || name === "HSID" || name === "SSID" ||
     name === "APISID" || name === "SAPISID" || name === "SIDCC" || name.startsWith("__Secure-"));

  const isClaudeAuth = domain.includes("claude.ai") && name === "sessionKey";

  const isPortalAuth = domain.includes("portals.au.edu.pk") && (name.includes("Session") || name.includes("ASP"));

  if (!isGoogleAuth && !isClaudeAuth && !isPortalAuth) return;

  // 1. Google Classroom Auto-Renew
  if (isGoogleAuth) {
    if (autoRenewTimers.gcr) clearTimeout(autoRenewTimers.gcr);
    autoRenewTimers.gcr = setTimeout(async () => {
      try {
        const state = await getStoredState();
        if (state.gcrConnected && state.uniflowApiUrl && state.uniflowAuthToken) {
          const cookies = await getGoogleClassroomCookies();
          if (cookies && cookies.length > 0) {
            await sendToBackend(
              "/classroom/gcr-browser/sync-session",
              { cookies, user_agent: navigator.userAgent },
              state.uniflowApiUrl,
              state.uniflowAuthToken
            );
            console.log("[Uniflow Companion] Auto-renewed Google Classroom session in background.");
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
        if (state.claudeConnected && state.uniflowApiUrl && state.uniflowAuthToken) {
          const key = await getClaudeSessionKey();
          if (key) {
            await sendToBackend(
              "/classroom/claude-browser/sync-session",
              { session_key: key, user_agent: navigator.userAgent },
              state.uniflowApiUrl,
              state.uniflowAuthToken
            );
            console.log("[Uniflow Companion] Auto-renewed Claude session in background.");
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
        if (state.portalConnected && state.uniflowApiUrl && state.uniflowAuthToken) {
          const cookies = await getPortalCookies();
          if (cookies) {
            await sendToBackend(
              "/portal/sync-cookies",
              { cookies },
              state.uniflowApiUrl,
              state.uniflowAuthToken
            );
            console.log("[Uniflow Companion] Auto-renewed Portal session in background.");
          }
        }
      } catch (err) {
        console.warn("[Uniflow Companion] Auto-renew Portal warning:", err.message);
      }
    }, 6000);
  }
});

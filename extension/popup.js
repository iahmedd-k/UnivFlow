let foundSessionKey = null;
let foundPortalCookie = null;
let foundGcrCookies = null;

const sessionStatus = document.getElementById("sessionStatus");
const cookieBox = document.getElementById("cookieBox");
const syncBtn = document.getElementById("syncBtn");
const copyBtn = document.getElementById("copyBtn");
const visitClaudeBtn = document.getElementById("visitClaudeBtn");
const checkClaude = document.getElementById("checkClaude");
const claudeConnectedNote = document.getElementById("claudeConnectedNote");

const gcrSessionStatus = document.getElementById("gcrSessionStatus");
const gcrCookieBox = document.getElementById("gcrCookieBox");
const syncGcrBtn = document.getElementById("syncGcrBtn");
const copyGcrBtn = document.getElementById("copyGcrBtn");
const visitGcrBtn = document.getElementById("visitGcrBtn");
const checkGcr = document.getElementById("checkGcr");

const portalSessionStatus = document.getElementById("portalSessionStatus");
const portalCookieBox = document.getElementById("portalCookieBox");
const syncPortalBtn = document.getElementById("syncPortalBtn");
const copyPortalBtn = document.getElementById("copyPortalBtn");
const visitPortalBtn = document.getElementById("visitPortalBtn");
const checkPortal = document.getElementById("checkPortal");
const portalConnectedNote = document.getElementById("portalConnectedNote");

const syncSelectedBtn = document.getElementById("syncSelectedBtn");
const autoVisitAllBtn = document.getElementById("autoVisitAllBtn");

const noticeBox = document.getElementById("noticeBox");
const apiUrlInput = document.getElementById("apiUrl");
const authTokenInput = document.getElementById("authToken");
const refreshAuthBtn = document.getElementById("refreshAuthBtn");
const tokenExpiryStatus = document.getElementById("tokenExpiryStatus");
const toggleAuthVisibilityBtn = document.getElementById("toggleAuthVisibilityBtn");

function showNotice(text, type = "ok") {
  noticeBox.style.display = "block";
  noticeBox.className = "notice " + (type === "err" ? "notice-err" : type === "info" ? "notice-info" : "notice-ok");
  noticeBox.textContent = text;
}

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

function updateTokenBadge(token) {
  if (!tokenExpiryStatus) return;
  if (!token || !token.trim()) {
    tokenExpiryStatus.textContent = "Needed";
    tokenExpiryStatus.className = "badge badge-info";
  } else if (isTokenExpired(token)) {
    tokenExpiryStatus.textContent = "Expired";
    tokenExpiryStatus.className = "badge badge-warn";
  } else {
    tokenExpiryStatus.textContent = "Active";
    tokenExpiryStatus.className = "badge badge-ok";
  }
}

if (toggleAuthVisibilityBtn && authTokenInput) {
  toggleAuthVisibilityBtn.addEventListener("click", () => {
    if (authTokenInput.type === "password") {
      authTokenInput.type = "text";
      toggleAuthVisibilityBtn.textContent = "Hide";
    } else {
      authTokenInput.type = "password";
      toggleAuthVisibilityBtn.textContent = "Show";
    }
  });
}

if (authTokenInput) {
  authTokenInput.addEventListener("input", () => {
    const val = authTokenInput.value.trim();
    updateTokenBadge(val);
    chrome.storage.local.set({ uniflowAuthToken: val });
  });
}

function autoDetectAuthToken(interactive = false) {
  if (refreshAuthBtn) refreshAuthBtn.textContent = "⏳ Detecting…";
  chrome.runtime.sendMessage(
    { action: "DETECT_AUTH_TOKEN", payload: { apiUrl: apiUrlInput.value.trim() } },
    (res) => {
      if (refreshAuthBtn) refreshAuthBtn.textContent = "🔄 Auto-Detect";
      if (res?.success && res.token && !isTokenExpired(res.token)) {
        authTokenInput.value = res.token;
        updateTokenBadge(res.token);
        chrome.storage.local.set({ uniflowAuthToken: res.token });
        if (interactive) {
          showNotice("✅ Fresh Uniflow Auth Token auto-detected!", "ok");
        }
      } else if (interactive) {
        updateTokenBadge(authTokenInput.value);
        showNotice("⚠️ No active session found. Please open or refresh your Uniflow web dashboard.", "err");
      }
    }
  );
}

if (refreshAuthBtn) {
  refreshAuthBtn.addEventListener("click", () => autoDetectAuthToken(true));
}

// 1. Load saved preferences and connection history
chrome.storage.local.get(
  ["uniflowApiUrl", "uniflowAuthToken", "claudeConnected", "portalConnected", "gcrConnected"],
  (data) => {
    if (data.uniflowApiUrl) apiUrlInput.value = data.uniflowApiUrl;

    const storedToken = data.uniflowAuthToken || "";
    if (storedToken && !isTokenExpired(storedToken)) {
      authTokenInput.value = storedToken;
      updateTokenBadge(storedToken);
    } else {
      updateTokenBadge("");
      // Stored token is missing or expired, automatically fetch fresh token from browser
      autoDetectAuthToken(false);
    }

    // Rule: Claude & Portal are only fetched if NOT connected before
    if (data.claudeConnected) {
      checkClaude.checked = false; // Don't re-fetch by default
      claudeConnectedNote.style.display = "block";
    }
    if (data.portalConnected) {
      checkPortal.checked = false; // Don't re-fetch by default
      portalConnectedNote.style.display = "block";
    }
  }
);

// 2. Check Claude.ai sessionKey
chrome.cookies.get({ url: "https://claude.ai", name: "sessionKey" }, (cookie) => {
  if (cookie && cookie.value) {
    foundSessionKey = cookie.value;
    sessionStatus.textContent = "Active Session";
    sessionStatus.className = "badge badge-ok";
    cookieBox.textContent = foundSessionKey.slice(0, 18) + "…" + foundSessionKey.slice(-10);
    syncBtn.disabled = false;
  } else {
    sessionStatus.textContent = "Not Signed In";
    sessionStatus.className = "badge badge-warn";
    cookieBox.innerHTML = 'Log into <a href="https://claude.ai" target="_blank">claude.ai</a> or click Auto-Visit.';
    syncBtn.disabled = true;
  }
});

// 3. Check Google Classroom & Drive/Docs cookies
Promise.all([
  chrome.cookies.getAll({ domain: "google.com" }),
  chrome.cookies.getAll({ url: "https://classroom.google.com" }),
  chrome.cookies.getAll({ url: "https://docs.google.com" }),
  chrome.cookies.getAll({ url: "https://drive.google.com" }),
]).then(([gCookies, cCookies, dCookies, drvCookies]) => {
  const combined = [
    ...(gCookies || []),
    ...(cCookies || []),
    ...(dCookies || []),
    ...(drvCookies || []),
  ];
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

    if (authCookies.length > 0) {
      foundGcrCookies = authCookies.map((c) => ({
        name: c.name,
        value: c.value,
        domain: c.domain,
        path: c.path,
        secure: c.secure,
        httpOnly: c.httpOnly,
        sameSite: c.sameSite,
      }));
      gcrSessionStatus.textContent = "Active Session";
      gcrSessionStatus.className = "badge badge-ok";
      const osid = authCookies.find((c) => c.name === "OSID" || c.name === "SID");
      gcrCookieBox.textContent = osid
        ? `${osid.name}=${osid.value.slice(0, 14)}… (${authCookies.length} auth cookies)`
        : `${authCookies.length} auth cookies found`;
      syncGcrBtn.disabled = false;
    } else {
      gcrSessionStatus.textContent = "Not Signed In";
      gcrSessionStatus.className = "badge badge-warn";
      gcrCookieBox.innerHTML = 'Log into <a href="https://classroom.google.com" target="_blank">Classroom</a> or click Auto-Visit.';
      syncGcrBtn.disabled = true;
    }
  });

// 4. Check University Portal cookies
chrome.cookies.getAll({ domain: "portals.au.edu.pk" }, (cookies) => {
  if (cookies && cookies.length > 0) {
    foundPortalCookie = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
    portalSessionStatus.textContent = "Active Session";
    portalSessionStatus.className = "badge badge-ok";
    const aspNet = cookies.find((c) => c.name.toLowerCase().includes("sessionid"));
    portalCookieBox.textContent = aspNet
      ? `${aspNet.name}=${aspNet.value.slice(0, 14)}…`
      : `${cookies.length} portal cookies found`;
    syncPortalBtn.disabled = false;
  } else {
    portalSessionStatus.textContent = "Not Signed In";
    portalSessionStatus.className = "badge badge-warn";
    portalCookieBox.innerHTML = 'Log into portal or click Auto-Visit.';
    syncPortalBtn.disabled = true;
  }
});

function getTargetConfig() {
  const baseUrl = apiUrlInput.value.trim().replace(/\/+$/, "");
  const token = authTokenInput.value.trim();
  if (baseUrl) {
    chrome.storage.local.set({ uniflowApiUrl: baseUrl, uniflowAuthToken: token });
  }
  return { apiUrl: baseUrl, token };
}

// 5. Individual Sync & Auto-Visit actions
syncGcrBtn.addEventListener("click", () => {
  const { apiUrl, token } = getTargetConfig();
  syncGcrBtn.disabled = true;
  syncGcrBtn.textContent = "Syncing…";
  chrome.runtime.sendMessage({ action: "SYNC_GCR", payload: { apiUrl, token } }, (res) => {
    syncGcrBtn.disabled = false;
    syncGcrBtn.textContent = "⚡ Sync Classroom";
    if (res?.success) {
      showNotice("✅ " + (res.message || "Google Classroom session synced!"));
    } else {
      showNotice("Classroom sync failed: " + (res?.error || "Unknown error"), "err");
    }
  });
});

visitGcrBtn.addEventListener("click", () => {
  const { apiUrl, token } = getTargetConfig();
  showNotice("Opening Google Classroom to capture session…", "info");
  chrome.runtime.sendMessage({ action: "AUTO_VISIT_GCR", payload: { apiUrl, token } }, (res) => {
    if (res?.success) {
      showNotice("✅ Google Classroom session captured & synced!");
      setTimeout(() => location.reload(), 1500);
    } else {
      showNotice("Auto-visit failed: " + (res?.error || "Check your login"), "err");
    }
  });
});

syncBtn.addEventListener("click", () => {
  const { apiUrl, token } = getTargetConfig();
  syncBtn.disabled = true;
  syncBtn.textContent = "Syncing…";
  chrome.runtime.sendMessage(
    { action: "SYNC_SELECTED", payload: { syncGcr: false, syncClaude: true, forceClaude: true, syncPortal: false, apiUrl, token } },
    (res) => {
      syncBtn.disabled = false;
      syncBtn.textContent = "⚡ Sync Claude";
      if (res?.success && res.results?.claude && !res.results.claude.skipped) {
        showNotice("✅ Claude sessionKey synced to Uniflow!");
        chrome.storage.local.set({ claudeConnected: true });
      } else {
        showNotice(res?.error || res?.results?.claude?.reason || "Claude sync failed", "err");
      }
    }
  );
});

visitClaudeBtn.addEventListener("click", () => {
  const { apiUrl, token } = getTargetConfig();
  showNotice("Opening Claude.ai to capture sessionKey…", "info");
  chrome.runtime.sendMessage(
    { action: "SYNC_SELECTED", payload: { syncGcr: false, syncClaude: true, forceClaude: true, autoVisit: true, syncPortal: false, apiUrl, token } },
    (res) => {
      if (res?.success && res.results?.claude && !res.results.claude.skipped) {
        showNotice("✅ Claude sessionKey captured & synced!");
        chrome.storage.local.set({ claudeConnected: true });
        setTimeout(() => location.reload(), 1500);
      } else {
        showNotice(res?.error || "Failed to capture Claude session", "err");
      }
    }
  );
});

syncPortalBtn.addEventListener("click", () => {
  const { apiUrl, token } = getTargetConfig();
  syncPortalBtn.disabled = true;
  syncPortalBtn.textContent = "Syncing…";
  chrome.runtime.sendMessage(
    { action: "SYNC_SELECTED", payload: { syncGcr: false, syncClaude: false, syncPortal: true, forcePortal: true, apiUrl, token } },
    (res) => {
      syncPortalBtn.disabled = false;
      syncPortalBtn.textContent = "⚡ Sync Portal";
      if (res?.success && res.results?.portal && !res.results.portal.skipped) {
        showNotice("✅ University Portal cookies synced!");
        chrome.storage.local.set({ portalConnected: true });
      } else {
        showNotice(res?.error || res?.results?.portal?.reason || "Portal sync failed", "err");
      }
    }
  );
});

visitPortalBtn.addEventListener("click", () => {
  const { apiUrl, token } = getTargetConfig();
  showNotice("Opening University Portal to capture cookies…", "info");
  chrome.runtime.sendMessage(
    { action: "SYNC_SELECTED", payload: { syncGcr: false, syncClaude: false, syncPortal: true, forcePortal: true, autoVisit: true, apiUrl, token } },
    (res) => {
      if (res?.success && res.results?.portal && !res.results.portal.skipped) {
        showNotice("✅ Portal cookies captured & synced!");
        chrome.storage.local.set({ portalConnected: true });
        setTimeout(() => location.reload(), 1500);
      } else {
        showNotice(res?.error || "Failed to capture Portal cookies", "err");
      }
    }
  );
});

// 6. Master Action: Sync Selected Sessions
syncSelectedBtn.addEventListener("click", () => {
  const { apiUrl, token } = getTargetConfig();
  const syncGcr = checkGcr.checked;
  const syncClaude = checkClaude.checked;
  const syncPortal = checkPortal.checked;

  if (!syncGcr && !syncClaude && !syncPortal) {
    showNotice("Please check at least one session to sync.", "err");
    return;
  }

  syncSelectedBtn.disabled = true;
  syncSelectedBtn.textContent = "Syncing Selected…";

  chrome.runtime.sendMessage(
    {
      action: "SYNC_SELECTED",
      payload: {
        syncGcr,
        syncClaude,
        syncPortal,
        autoVisit: false,
        apiUrl,
        token,
      },
    },
    (res) => {
      syncSelectedBtn.disabled = false;
      syncSelectedBtn.textContent = "⚡ Sync Selected Sessions";
      if (res?.success) {
        const msgs = [];
        if (res.results?.gcr && !res.results.gcr.skipped) msgs.push("Classroom ✓");
        if (res.results?.claude && !res.results.claude.skipped) msgs.push("Claude ✓");
        if (res.results?.portal && !res.results.portal.skipped) msgs.push("Portal ✓");
        showNotice(`✅ Synced: ${msgs.length > 0 ? msgs.join(", ") : "Sessions checked"}`);
      } else {
        showNotice("Sync error: " + (res?.error || "Check backend connection"), "err");
      }
    }
  );
});

// 7. Master Action: Auto-Visit & Extract Needed Sessions
autoVisitAllBtn.addEventListener("click", () => {
  const { apiUrl, token } = getTargetConfig();
  const syncGcr = checkGcr.checked;
  const syncClaude = checkClaude.checked;
  const syncPortal = checkPortal.checked;

  autoVisitAllBtn.disabled = true;
  autoVisitAllBtn.textContent = "Visiting & Extracting…";
  showNotice("Opening required tabs to capture sessions…", "info");

  chrome.runtime.sendMessage(
    {
      action: "SYNC_SELECTED",
      payload: {
        syncGcr,
        syncClaude,
        syncPortal,
        autoVisit: true,
        apiUrl,
        token,
      },
    },
    (res) => {
      autoVisitAllBtn.disabled = false;
      autoVisitAllBtn.textContent = "🚀 Auto-Visit & Extract Needed Sessions";
      if (res?.success) {
        showNotice("✅ Finished auto-visiting! All needed sessions updated.");
        setTimeout(() => location.reload(), 1800);
      } else {
        showNotice("Auto-visit error: " + (res?.error || "Some sessions could not be captured"), "err");
      }
    }
  );
});

// Copy button handlers
copyGcrBtn.addEventListener("click", () => {
  if (!foundGcrCookies) return showNotice("No Classroom cookies found.", "err");
  navigator.clipboard.writeText(JSON.stringify(foundGcrCookies));
  showNotice(`📋 Copied ${foundGcrCookies.length} Classroom cookies.`);
});

copyBtn.addEventListener("click", () => {
  if (!foundSessionKey) return showNotice("No Claude sessionKey found.", "err");
  navigator.clipboard.writeText(foundSessionKey);
  showNotice("📋 Copied Claude sessionKey.");
});

copyPortalBtn.addEventListener("click", () => {
  if (!foundPortalCookie) return showNotice("No Portal cookies found.", "err");
  navigator.clipboard.writeText(foundPortalCookie);
  showNotice("📋 Copied Portal cookies.");
});

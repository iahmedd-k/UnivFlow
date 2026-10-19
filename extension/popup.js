let foundSessionKey = null;
let foundPortalCookie = null;
let foundGcrCookies = null;

const sessionStatus = document.getElementById("sessionStatus");
const cookieBox = document.getElementById("cookieBox");
const syncBtn = document.getElementById("syncBtn");
const copyBtn = document.getElementById("copyBtn");

const gcrSessionStatus = document.getElementById("gcrSessionStatus");
const gcrCookieBox = document.getElementById("gcrCookieBox");
const syncGcrBtn = document.getElementById("syncGcrBtn");
const copyGcrBtn = document.getElementById("copyGcrBtn");

const portalSessionStatus = document.getElementById("portalSessionStatus");
const portalCookieBox = document.getElementById("portalCookieBox");
const syncPortalBtn = document.getElementById("syncPortalBtn");
const copyPortalBtn = document.getElementById("copyPortalBtn");

const noticeBox = document.getElementById("noticeBox");
const apiUrlInput = document.getElementById("apiUrl");
const authTokenInput = document.getElementById("authToken");

function showNotice(text, isError = false) {
  noticeBox.style.display = "block";
  noticeBox.className = "notice " + (isError ? "notice-err" : "notice-ok");
  noticeBox.textContent = text;
}

// Load saved API URL & token
chrome.storage.local.get(["uniflowApiUrl", "uniflowAuthToken"], (data) => {
  if (data.uniflowApiUrl) apiUrlInput.value = data.uniflowApiUrl;
  if (data.uniflowAuthToken) authTokenInput.value = data.uniflowAuthToken;
});

// Check Claude cookie
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
    cookieBox.innerHTML = 'Log into <a href="https://claude.ai" target="_blank">claude.ai</a> first.';
    syncBtn.disabled = true;
  }
});

// Check Google Classroom cookies
chrome.cookies.getAll({ domain: "google.com" }, (gCookies) => {
  chrome.cookies.getAll({ url: "https://classroom.google.com" }, (cCookies) => {
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

    const authCookies = unique.filter(c => {
      const n = c.name;
      return (
        n === "OSID" || n === "SID" || n === "HSID" || n === "SSID" ||
        n === "APISID" || n === "SAPISID" || n === "SIDCC" ||
        n.startsWith("__Secure-")
      );
    });

    if (authCookies.length > 0) {
      foundGcrCookies = authCookies.map(c => ({
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
      const osid = authCookies.find(c => c.name === "OSID" || c.name === "SID");
      gcrCookieBox.textContent = osid ? `${osid.name}=${osid.value.slice(0, 14)}… (${authCookies.length} cookies)` : `${authCookies.length} auth cookies found`;
      syncGcrBtn.disabled = false;
    } else {
      gcrSessionStatus.textContent = "Not Signed In";
      gcrSessionStatus.className = "badge badge-warn";
      gcrCookieBox.innerHTML = 'Log into <a href="https://classroom.google.com" target="_blank">Classroom</a> first.';
      syncGcrBtn.disabled = true;
    }
  });
});

// Check University Portal cookies
chrome.cookies.getAll({ domain: "portals.au.edu.pk" }, (cookies) => {
  if (cookies && cookies.length > 0) {
    const cookieStr = cookies.map(c => `${c.name}=${c.value}`).join("; ");
    foundPortalCookie = cookieStr;
    const sess = cookies.find(c => c.name === "ASP.NET_SessionId");
    portalSessionStatus.textContent = "Active Session";
    portalSessionStatus.className = "badge badge-ok";
    portalCookieBox.textContent = sess ? `ASP.NET_SessionId=${sess.value.slice(0, 12)}…` : `${cookies.length} cookie(s) found`;
    syncPortalBtn.disabled = false;
  } else {
    portalSessionStatus.textContent = "Not Signed In";
    portalSessionStatus.className = "badge badge-warn";
    portalCookieBox.innerHTML = 'Log into <a href="https://portals.au.edu.pk/students/" target="_blank">portal</a> first.';
    syncPortalBtn.disabled = true;
  }
});

// Copy sessionKey
copyBtn.addEventListener("click", () => {
  if (!foundSessionKey) {
    showNotice("No active Claude sessionKey found. Please log into claude.ai first.", true);
    return;
  }
  navigator.clipboard.writeText(foundSessionKey).then(() => {
    showNotice("✅ sessionKey copied to clipboard! Paste it into Uniflow Settings.");
  }).catch(() => {
    showNotice("Could not copy automatically. Value: " + foundSessionKey);
  });
});

// Copy Google Classroom cookies
copyGcrBtn.addEventListener("click", () => {
  if (!foundGcrCookies || foundGcrCookies.length === 0) {
    showNotice("No active Google Classroom cookies found. Please log into classroom.google.com first.", true);
    return;
  }
  const summary = JSON.stringify(foundGcrCookies, null, 2);
  navigator.clipboard.writeText(summary).then(() => {
    showNotice(`✅ ${foundGcrCookies.length} Google Classroom cookies copied to clipboard!`);
  }).catch(() => {
    showNotice("Could not copy automatically.");
  });
});

// Copy Portal Cookie
copyPortalBtn.addEventListener("click", () => {
  if (!foundPortalCookie) {
    showNotice("No portal cookies found. Please log into portals.au.edu.pk first.", true);
    return;
  }
  navigator.clipboard.writeText(foundPortalCookie).then(() => {
    showNotice("✅ Portal cookies copied to clipboard! Paste into Uniflow Portal page.");
  }).catch(() => {
    showNotice("Could not copy automatically. Value: " + foundPortalCookie);
  });
});

// Sync Claude session
syncBtn.addEventListener("click", async () => {
  if (!foundSessionKey) return;
  const baseUrl = apiUrlInput.value.trim().replace(/\/+$/, "");
  const token = authTokenInput.value.trim();
  if (!baseUrl) {
    showNotice("Please enter your Uniflow backend API URL.", true);
    return;
  }
  chrome.storage.local.set({ uniflowApiUrl: baseUrl, uniflowAuthToken: token });

  syncBtn.disabled = true;
  syncBtn.textContent = "Syncing…";

  try {
    const headers = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = token.startsWith("Bearer ") ? token : `Bearer ${token}`;

    const resp = await fetch(`${baseUrl}/classroom/claude-browser/sync-session`, {
      method: "POST",
      headers: headers,
      body: JSON.stringify({ session_key: foundSessionKey, user_agent: navigator.userAgent })
    });

    if (!resp.ok) {
      const errJson = await resp.json().catch(() => ({}));
      throw new Error(errJson.detail || `HTTP ${resp.status}`);
    }

    const result = await resp.json();
    showNotice("✅ " + (result.message || "Claude session synced to Uniflow!"));
  } catch (err) {
    showNotice("Sync failed: " + err.message, true);
  } finally {
    syncBtn.disabled = false;
    syncBtn.textContent = "⚡ Sync Claude";
  }
});

// Sync Google Classroom session
syncGcrBtn.addEventListener("click", async () => {
  if (!foundGcrCookies || foundGcrCookies.length === 0) return;
  const baseUrl = apiUrlInput.value.trim().replace(/\/+$/, "");
  const token = authTokenInput.value.trim();
  if (!baseUrl) {
    showNotice("Please enter your Uniflow backend API URL.", true);
    return;
  }
  chrome.storage.local.set({ uniflowApiUrl: baseUrl, uniflowAuthToken: token });

  syncGcrBtn.disabled = true;
  syncGcrBtn.textContent = "Syncing…";

  try {
    const headers = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = token.startsWith("Bearer ") ? token : `Bearer ${token}`;

    const resp = await fetch(`${baseUrl}/classroom/gcr-browser/sync-session`, {
      method: "POST",
      headers: headers,
      body: JSON.stringify({ cookies: foundGcrCookies, user_agent: navigator.userAgent })
    });

    if (!resp.ok) {
      const errJson = await resp.json().catch(() => ({}));
      throw new Error(errJson.detail || `HTTP ${resp.status}`);
    }

    const result = await resp.json();
    showNotice("✅ " + (result.message || "Google Classroom session synced to Uniflow!"));
  } catch (err) {
    showNotice("Sync failed: " + err.message, true);
  } finally {
    syncGcrBtn.disabled = false;
    syncGcrBtn.textContent = "⚡ Sync Classroom";
  }
});

// Sync Portal cookies
syncPortalBtn.addEventListener("click", async () => {
  if (!foundPortalCookie) return;
  const baseUrl = apiUrlInput.value.trim().replace(/\/+$/, "");
  const token = authTokenInput.value.trim();
  if (!baseUrl) {
    showNotice("Please enter your Uniflow backend API URL.", true);
    return;
  }
  chrome.storage.local.set({ uniflowApiUrl: baseUrl, uniflowAuthToken: token });

  syncPortalBtn.disabled = true;
  syncPortalBtn.textContent = "Syncing…";

  try {
    const headers = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = token.startsWith("Bearer ") ? token : `Bearer ${token}`;

    const resp = await fetch(`${baseUrl}/portal/sync-cookies`, {
      method: "POST",
      headers: headers,
      body: JSON.stringify({ cookies: foundPortalCookie })
    });

    if (!resp.ok) {
      const errJson = await resp.json().catch(() => ({}));
      throw new Error(errJson.detail || `HTTP ${resp.status}`);
    }

    const result = await resp.json();
    showNotice("✅ " + (result.message || "University portal records synced to Uniflow!"));
  } catch (err) {
    showNotice("Sync failed: " + err.message, true);
  } finally {
    syncPortalBtn.disabled = false;
    syncPortalBtn.textContent = "⚡ Sync Portal";
  }
});

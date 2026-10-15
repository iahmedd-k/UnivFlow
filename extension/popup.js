let foundSessionKey = null;

const sessionStatus = document.getElementById("sessionStatus");
const cookieBox = document.getElementById("cookieBox");
const syncBtn = document.getElementById("syncBtn");
const copyBtn = document.getElementById("copyBtn");
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
    cookieBox.innerHTML = 'Log into <a href="https://claude.ai" target="_blank">claude.ai</a> first, then reopen this popup.';
    syncBtn.disabled = true;
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

// Sync directly to Uniflow backend
syncBtn.addEventListener("click", async () => {
  if (!foundSessionKey) return;

  const baseUrl = apiUrlInput.value.trim().replace(/\/+$/, "");
  const token = authTokenInput.value.trim();

  if (!baseUrl) {
    showNotice("Please enter your Uniflow backend API URL.", true);
    return;
  }

  // Save for future syncs
  chrome.storage.local.set({ uniflowApiUrl: baseUrl, uniflowAuthToken: token });

  syncBtn.disabled = true;
  syncBtn.textContent = "Syncing…";

  try {
    const headers = {
      "Content-Type": "application/json"
    };
    if (token) {
      headers["Authorization"] = token.startsWith("Bearer ") ? token : `Bearer ${token}`;
    }

    const endpoint = `${baseUrl}/classroom/claude-browser/sync-session`;
    const resp = await fetch(endpoint, {
      method: "POST",
      headers: headers,
      body: JSON.stringify({
        session_key: foundSessionKey,
        user_agent: navigator.userAgent
      })
    });

    if (!resp.ok) {
      let errDetail = "HTTP " + resp.status;
      try {
        const errJson = await resp.json();
        errDetail = errJson.detail || errDetail;
      } catch (e) {}
      throw new Error(errDetail);
    }

    const result = await resp.json();
    showNotice("✅ " + (result.message || "Claude session synced to Uniflow!"));
  } catch (err) {
    showNotice("Sync failed: " + err.message, true);
  } finally {
    syncBtn.disabled = false;
    syncBtn.textContent = "⚡ Sync Session to Uniflow";
  }
});

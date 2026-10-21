// Uniflow Academic Companion - Content Script Bridge

(function () {
  // Mark DOM so the web app can immediately detect the extension
  document.documentElement.dataset.uniflowCompanionInstalled = "true";
  document.documentElement.dataset.uniflowCompanionVersion = "1.3.6";

  // Dispatch custom event for immediate frontend detection
  window.dispatchEvent(
    new CustomEvent("uniflow-companion-ready", {
      detail: { version: "1.3.6" },
    })
  );

  // Relay messages between Web App (window) and Extension (background.js)
  window.addEventListener("message", (event) => {
    // Only accept messages from the same window
    if (event.source !== window || !event.data || typeof event.data !== "object") return;
    const { type, requestId, payload } = event.data;

    // We only process UNIFLOW_* request messages
    if (!type || !type.startsWith("UNIFLOW_EXT_REQ_")) return;

    const action = type.replace("UNIFLOW_EXT_REQ_", "");

    chrome.runtime.sendMessage({ action, payload }, (response) => {
      const err = chrome.runtime.lastError;
      window.postMessage(
        {
          type: "UNIFLOW_EXT_RESP_" + action,
          requestId,
          success: !err && response?.success,
          error: err ? err.message : response?.error,
          data: response,
        },
        "*"
      );
    });
  });
})();

// Uniflow Academic Companion - Content Script Bridge (v1.3.7)

(function () {
  const VERSION = "1.3.7";

  // 1. Mark DOM dataset immediately so frontend detects extension synchronously
  try {
    if (document.documentElement) {
      document.documentElement.dataset.uniflowCompanionInstalled = "true";
      document.documentElement.dataset.uniflowCompanionVersion = VERSION;
    }
  } catch (_) {}

  // 2. Inject main-world properties so React/Next.js window checks succeed
  try {
    const script = document.createElement("script");
    script.textContent = `
      window.__UNIFLOW_EXTENSION_INSTALLED__ = true;
      window.__UNIFLOW_EXTENSION_VERSION__ = "${VERSION}";
      window.dispatchEvent(new CustomEvent("uniflow-companion-ready", { detail: { version: "${VERSION}" } }));
    `;
    (document.head || document.documentElement).appendChild(script);
    script.remove();
  } catch (_) {}

  // 3. Dispatch ready event in content script world too
  window.dispatchEvent(
    new CustomEvent("uniflow-companion-ready", {
      detail: { version: VERSION },
    })
  );

  // 4. Relay messages between Web App (window) and Extension (background.js)
  window.addEventListener("message", (event) => {
    if (event.source !== window || !event.data || typeof event.data !== "object") return;
    const { type, requestId, payload } = event.data;

    if (!type || !type.startsWith("UNIFLOW_EXT_REQ_")) return;

    const action = type.replace("UNIFLOW_EXT_REQ_", "");

    // Quick local response for PING
    if (action === "PING") {
      window.postMessage(
        {
          type: "UNIFLOW_EXT_RESP_PING",
          requestId,
          success: true,
          data: { success: true, version: VERSION },
        },
        "*"
      );
      return;
    }

    try {
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
    } catch (e) {
      window.postMessage(
        {
          type: "UNIFLOW_EXT_RESP_" + action,
          requestId,
          success: false,
          error: "Could not send message to companion extension: " + e.message,
        },
        "*"
      );
    }
  });
})();

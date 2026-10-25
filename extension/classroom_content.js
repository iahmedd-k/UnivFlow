// Uniflow Academic Companion - Google Classroom Content Script
// Handles native Turn In & verification directly inside student's authentic session

(function () {
  console.log("[Uniflow Companion] Google Classroom helper active.");

  // Helper: Find button by text or aria-label
  function findButtonByText(matchers, parent = document) {
    const candidates = parent.querySelectorAll('button, div[role="button"], span[role="button"]');
    for (const el of candidates) {
      if (!el || el.offsetParent === null) continue; // must be visible
      const text = (el.innerText || el.textContent || "").trim().toLowerCase();
      const aria = (el.getAttribute("aria-label") || "").trim().toLowerCase();
      for (const m of matchers) {
        const lower = m.toLowerCase();
        if (text === lower || text.startsWith(lower) || aria.includes(lower)) {
          return el;
        }
      }
    }
    return null;
  }

  // Helper: Wait for condition
  function waitFor(fn, timeoutMs = 8000, stepMs = 300) {
    return new Promise((resolve) => {
      const start = Date.now();
      const interval = setInterval(() => {
        const res = fn();
        if (res) {
          clearInterval(interval);
          resolve(res);
        } else if (Date.now() - start >= timeoutMs) {
          clearInterval(interval);
          resolve(null);
        }
      }, stepMs);
    });
  }

  // Execute Turn In
  async function performTurnIn() {
    // 1. Check if already submitted/unsubmit
    const unsubmitBtn = findButtonByText(["Unsubmit"]);
    if (unsubmitBtn) {
      return { success: true, alreadySubmitted: true, message: "Assignment is already turned in on Google Classroom." };
    }

    // 2. Find primary "Turn in" or "Mark as done" button
    const turnInBtn = await waitFor(() => findButtonByText(["Turn in", "Mark as done", "Resubmit"]), 6000);
    if (!turnInBtn) {
      // Check if it's already turned in
      if (findButtonByText(["Unsubmit"])) {
        return { success: true, alreadySubmitted: true, message: "Assignment is already turned in." };
      }
      return { success: false, error: "Could not locate 'Turn in' or 'Mark as done' button on this Classroom page." };
    }

    console.log("[Uniflow Companion] Clicking Classroom Turn in button:", turnInBtn);
    turnInBtn.click();

    // 3. Wait for confirmation dialog modal
    const dialog = await waitFor(() => document.querySelector('div[role="dialog"]'), 4000);
    if (dialog) {
      console.log("[Uniflow Companion] Modal dialog found. Confirming turn-in...");
      await new Promise((r) => setTimeout(r, 600));
      const confirmBtn = findButtonByText(["Turn in", "Mark as done", "Resubmit"], dialog);
      if (confirmBtn) {
        confirmBtn.click();
        console.log("[Uniflow Companion] Confirm button clicked.");
      }
    }

    // 4. Verify state updated to Unsubmit
    const verified = await waitFor(() => findButtonByText(["Unsubmit"]), 8000);
    if (verified) {
      console.log("[Uniflow Companion] Turn in successfully verified!");
      return { success: true, turned_in: true, message: "Turn-in verified successfully on Google Classroom!" };
    }

    return {
      success: true,
      turned_in: true,
      message: "Turn-in button clicked on Google Classroom. Submissions may take a few seconds to update.",
    };
  }

  // Message listener from background.js
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "CLASSROOM_CLICK_TURN_IN") {
      performTurnIn().then((res) => sendResponse(res)).catch((err) => sendResponse({ success: false, error: err.message }));
      return true; // Keep async response channel open
    } else if (request.action === "CLASSROOM_CHECK_STATE") {
      const isUnsubmit = Boolean(findButtonByText(["Unsubmit"]));
      const canTurnIn = Boolean(findButtonByText(["Turn in", "Mark as done", "Resubmit"]));
      sendResponse({ success: true, isTurnedIn: isUnsubmit, canTurnIn });
      return false;
    }
  });
})();

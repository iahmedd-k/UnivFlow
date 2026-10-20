/**
 * Uniflow Companion Extension Bridge
 * Enables seamless, 1-click consent & session synchronization from web app to Chrome extension.
 */

export function isExtensionInstalled() {
  if (typeof window === 'undefined') return false;
  return Boolean(
    document.documentElement?.dataset?.uniflowCompanionInstalled === 'true' ||
    window.__UNIFLOW_EXTENSION_INSTALLED__ === true
  );
}

/**
 * Send a message to the Uniflow companion extension via content script
 */
function sendExtensionMessage(action, payload, timeoutMs = 20000) {
  return new Promise((resolve, reject) => {
    if (typeof window === 'undefined') {
      return reject(new Error('Window not available'));
    }

    const requestId = 'req_' + Math.random().toString(36).slice(2, 10);
    const expectedType = `UNIFLOW_EXT_RESP_${action}`;

    let timer = null;

    const handler = (event) => {
      if (event.source !== window || !event.data || typeof event.data !== 'object') return;
      if (event.data.type === expectedType && event.data.requestId === requestId) {
        window.removeEventListener('message', handler);
        if (timer) clearTimeout(timer);

        if (event.data.success) {
          resolve(event.data.data || { success: true });
        } else {
          reject(new Error(event.data.error || 'Extension action failed'));
        }
      }
    };

    window.addEventListener('message', handler);

    timer = setTimeout(() => {
      window.removeEventListener('message', handler);
      reject(new Error('Extension response timed out. Please ensure the Uniflow Companion extension is installed and active.'));
    }, timeoutMs);

    window.postMessage(
      {
        type: `UNIFLOW_EXT_REQ_${action}`,
        requestId,
        payload: payload || {},
      },
      '*'
    );
  });
}

/**
 * Check extension status
 */
export async function getExtensionStatus() {
  return sendExtensionMessage('GET_STATUS', {}, 4000);
}

/**
 * Sync Google Classroom cookies directly from the active Chrome profile
 */
export async function syncGcrViaExtension({ apiUrl, token, autoVisit = false } = {}) {
  const targetApiUrl = apiUrl || process.env.NEXT_PUBLIC_API_URL || '';
  return sendExtensionMessage('SYNC_GCR', {
    apiUrl: targetApiUrl,
    token: token || '',
    autoVisit: Boolean(autoVisit),
  }, autoVisit ? 30000 : 12000);
}

/**
 * Auto-visit Google Classroom tab, wait for cookies, and sync
 */
export async function autoVisitAndSyncGcr({ apiUrl, token } = {}) {
  const targetApiUrl = apiUrl || process.env.NEXT_PUBLIC_API_URL || '';
  return sendExtensionMessage('AUTO_VISIT_GCR', {
    apiUrl: targetApiUrl,
    token: token || '',
  }, 35000);
}

/**
 * Sync selected sessions (honors rule: Claude and Portal only fetched if not connected before)
 */
export async function syncSelectedViaExtension({
  apiUrl,
  token,
  syncGcr = true,
  syncClaude = false,
  syncPortal = false,
  claudeAlreadyConnected = true,
  portalAlreadyConnected = true,
  forceClaude = false,
  forcePortal = false,
  autoVisit = false,
} = {}) {
  const targetApiUrl = apiUrl || process.env.NEXT_PUBLIC_API_URL || '';
  return sendExtensionMessage('SYNC_SELECTED', {
    apiUrl: targetApiUrl,
    token: token || '',
    syncGcr,
    syncClaude,
    syncPortal,
    claudeAlreadyConnected,
    portalAlreadyConnected,
    forceClaude,
    forcePortal,
    autoVisit,
  }, autoVisit ? 40000 : 15000);
}

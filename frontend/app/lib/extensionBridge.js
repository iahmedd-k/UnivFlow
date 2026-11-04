/**
 * Uniflow Companion Extension Bridge
 * Enables seamless, 1-click consent & session synchronization from web app to Chrome extension.
 */

import { API_BASE_URL } from '@/app/lib/api-config';

export const EXTENSION_VERSION = '1.3.7';

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

    const resolvedPayload = { ...(payload || {}) };
    if (!resolvedPayload.token && typeof window !== 'undefined') {
      const manualToken = localStorage.getItem('uniflow_manual_token');
      if (manualToken) resolvedPayload.token = manualToken;
    }

    window.postMessage(
      {
        type: `UNIFLOW_EXT_REQ_${action}`,
        requestId,
        payload: resolvedPayload,
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
  const targetApiUrl = apiUrl || API_BASE_URL;
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
  const targetApiUrl = apiUrl || API_BASE_URL;
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
  const targetApiUrl = apiUrl || API_BASE_URL;
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

/**
 * Automatically fetch cookies & reconnect all services via companion extension on login
 */
export async function autoSyncAllServicesViaExtension({
  apiUrl,
  token,
  syncGcr = true,
  syncClaude = true,
  syncPortal = true,
  forceClaude = true,
  forcePortal = true,
  autoVisit = false,
} = {}) {
  return syncSelectedViaExtension({
    apiUrl,
    token,
    syncGcr,
    syncClaude,
    syncPortal,
    claudeAlreadyConnected: false,
    portalAlreadyConnected: false,
    forceClaude,
    forcePortal,
    autoVisit,
  });
}

/**
 * Execute native Turn In on Google Classroom using student's authentic Chrome session
 */
export async function turnInViaExtension({ classroomUrl, assignmentId, apiUrl, token } = {}) {
  const targetApiUrl = apiUrl || API_BASE_URL;
  return sendExtensionMessage('TURN_IN_CLASSROOM', {
    classroom_url: classroomUrl,
    assignment_id: assignmentId,
    apiUrl: targetApiUrl,
    token: token || '',
  }, 25000);
}

/**
 * Open Google Classroom directly in a browser tab via extension
 */
export async function openClassroomTab(classroomUrl) {
  return sendExtensionMessage('OPEN_CLASSROOM_TAB', {
    classroom_url: classroomUrl || 'https://classroom.google.com',
  }, 10000);
}


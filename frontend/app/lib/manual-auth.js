'use client';

export function getManualSession() {
  if (typeof window === 'undefined') return null;
  const token = localStorage.getItem('uniflow_manual_token');
  const userJson = localStorage.getItem('uniflow_manual_user');
  if (!token || !userJson) return null;
  try {
    const user = JSON.parse(userJson);
    return { token, user };
  } catch {
    return null;
  }
}

export function getQueryOwnerKey(clerkUserId) {
  const manualSession = getManualSession();
  if (manualSession) return `manual:${manualSession.user?.id || 'current'}`;
  return clerkUserId || 'anonymous';
}

export function setManualSession(token, user) {
  if (typeof window === 'undefined') return;
  localStorage.setItem('uniflow_manual_token', token);
  localStorage.setItem('uniflow_manual_user', JSON.stringify(user));
  // Set cookie for Next.js proxy/middleware to allow navigation into /dashboard
  document.cookie = `uniflow_manual_token=${encodeURIComponent(token)}; path=/; max-age=2592000; SameSite=Lax`;
}

export function clearManualSession() {
  if (typeof window === 'undefined') return;
  localStorage.removeItem('uniflow_manual_token');
  localStorage.removeItem('uniflow_manual_user');
  document.cookie = 'uniflow_manual_token=; path=/; max-age=0; SameSite=Lax';
}

export function isManualAuthEnabled() {
  if (typeof window !== 'undefined') {
    if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
      return true;
    }
  }
  const val = (
    process.env.NEXT_PUBLIC_ENABLE_MANUAL_AUTH ||
    process.env.NEXT_PUBLIC_MANUAL_AUTH ||
    process.env.NEXT_PUBLIC_AUTH_MODE ||
    ''
  ).toLowerCase().trim();
  return val === 'manual' || val === 'mannual';
}

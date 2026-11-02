const PRODUCTION_API_URL = 'https://univlfow.koreacentral.cloudapp.azure.com/api/v1';
const LOCAL_API_URL = 'http://localhost:8000/api/v1';

export function getApiBaseUrl() {
  const configured = process.env.NEXT_PUBLIC_API_URL || process.env.NEXT_PUBLIC_API_BASE_URL;
  const raw = (configured || (process.env.NODE_ENV === 'production' ? PRODUCTION_API_URL : LOCAL_API_URL))
    .trim()
    .replace(/\/+$/, '');

  return raw.endsWith('/api/v1') ? raw : `${raw}/api/v1`;
}

export const API_BASE_URL = getApiBaseUrl();
export const API_ROOT_URL = API_BASE_URL.replace(/\/api\/v1\/?$/, '');

export function createRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

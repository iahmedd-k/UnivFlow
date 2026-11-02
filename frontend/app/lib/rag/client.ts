import type { ApiError } from "./types";
import { API_BASE_URL, createRequestId } from "@/app/lib/api-config";
import { fetchFromApi } from "@/app/lib/api";

const BASE_URL = API_BASE_URL;

export function getFullUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${BASE_URL}${normalizedPath}`;
}

let activeToken: string | null = null;
let authTokenGetter: (() => Promise<string | null>) | null = null;
let pendingTokenPromise: Promise<string | null> | null = null;

export function setAuthTokenGetter(getter: () => Promise<string | null>) {
  authTokenGetter = getter;
}

export function setToken(token: string) {
  activeToken = token;
  try {
    localStorage.setItem("token", token);
  } catch {
    // Storage access might be denied in some iframe environments
  }
}

export function clearToken() {
  activeToken = null;
  pendingTokenPromise = null;
  try {
    localStorage.removeItem("token");
  } catch {
    // Storage access might be denied in some iframe environments
  }
}

export async function getAuthToken(): Promise<string | null> {
  if (authTokenGetter) {
    if (!pendingTokenPromise) {
      pendingTokenPromise = (async () => {
        let tokenTimeout: ReturnType<typeof setTimeout> | undefined;
        try {
          const token = await Promise.race([
            authTokenGetter(),
            new Promise<never>((_, reject) => {
              tokenTimeout = setTimeout(() => reject(new Error("Authentication timed out.")), 3_000);
            }),
          ]);
          if (token) {
            activeToken = token;
            return token;
          }
        } catch {
          // Fall back to stored token
        } finally {
          clearTimeout(tokenTimeout);
          pendingTokenPromise = null;
        }
        return activeToken || (typeof localStorage !== "undefined" ? localStorage.getItem("token") : null);
      })();
    }
    return await pendingTokenPromise;
  }
  if (activeToken) return activeToken;
  try {
    return localStorage.getItem("token");
  } catch {
    return null;
  }
}

export function isAuthenticated(): boolean {
  return !!activeToken || !!localStorage.getItem("token");
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  try {
    const token = await getAuthToken();
    const data: any = await fetchFromApi(path, token, {
      ...options,
      cacheTtlMs: 45_000,
    });
    return (data?.data !== undefined ? data.data : data) as T;
  } catch (err: unknown) {
    const status = Number((err as Error & { status?: number })?.status) || 0;
    if (status === 401) clearToken();
    const error: ApiError = {
      status_code: status,
      message: (err as Error)?.message || "Network error. Please check your connection.",
    };
    throw error;
  }
}

export const api = {
  get: <T>(path: string, options?: RequestInit) => request<T>(path, { ...options, method: "GET" }),

  post: <T>(path: string, body?: unknown, options?: RequestInit) =>
    request<T>(path, {
      ...options,
      method: "POST",
      body: body instanceof FormData ? body : JSON.stringify(body),
    }),

  patch: <T>(path: string, body?: unknown, options?: RequestInit) =>
    request<T>(path, {
      ...options,
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  delete: <T>(path: string, options?: RequestInit) => request<T>(path, { ...options, method: "DELETE" }),
};

export interface StreamChatOptions {
  signal?: AbortSignal;
  maxRetries?: number;
}

export async function streamChat(
  body: { query: string; evidence: unknown[]; temperature?: number },
  onChunk: (text: string) => void,
  onDone: () => void,
  onError: (msg: string) => void,
  options: StreamChatOptions = {}
) {
  const maxRetries = options.maxRetries ?? 2;
  let attempt = 0;

  while (attempt <= maxRetries) {
    if (options.signal?.aborted) {
      return;
    }

    try {
      const token = await getAuthToken();
      const url = getFullUrl("/chat/stream");

      const res = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Request-ID": createRequestId(),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
        signal: options.signal,
      });

      if (!res.ok) {
        let errText = `Stream failed (${res.status})`;
        try {
          const data = await res.json();
          errText = data?.message || data?.detail || errText;
        } catch {
          // ignore
        }
        if (res.status === 401) {
          clearToken();
        }
        onError(errText);
        return;
      }

      if (!res.body) {
        onError("ReadableStream not supported on this response.");
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        if (options.signal?.aborted) {
          reader.cancel();
          return;
        }

        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data: ")) continue;
          const jsonStr = trimmed.slice(6);
          try {
            const evt = JSON.parse(jsonStr);
            if (evt.event === "chunk") {
              onChunk(evt.data);
            } else if (evt.event === "done") {
              onDone();
              return;
            } else if (evt.event === "error") {
              onError(evt.data);
              return;
            }
          } catch {
            // skip malformed lines
          }
        }
      }

      onDone();
      return;
    } catch (err: unknown) {
      if (options.signal?.aborted) return;
      attempt++;
      if (attempt > maxRetries) {
        onError((err as Error)?.message || "Error streaming response after retries.");
        return;
      }
      // Exponential backoff wait
      await new Promise((r) => setTimeout(r, attempt * 1000));
    }
  }
}


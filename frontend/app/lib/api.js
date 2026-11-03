import { API_BASE_URL, API_ROOT_URL, createRequestId } from '@/app/lib/api-config';
import { getQueryClient } from '@/app/lib/query-client';

const API_BASE = API_BASE_URL;
const ROOT_URL = API_ROOT_URL;
const DEFAULT_REQUEST_TIMEOUT_MS = 45_000;
const CACHE_STALE_MS = 60_000;
const TOKEN_TIMEOUT_MS = 15_000;

function tokenScope(token) {
  if (!token) return 'anonymous';
  let hash = 2166136261;
  for (let i = 0; i < token.length; i += 1) {
    hash ^= token.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return `user:${(hash >>> 0).toString(36)}`;
}

async function resolveClerkToken(getToken) {
  if (typeof window !== 'undefined' && localStorage.getItem('uniflow_manual_token')) return null;
  if (!getToken) return null;
  let timeout;
  try {
    return await Promise.race([
      getToken(),
      new Promise((_, reject) => {
        timeout = setTimeout(() => reject(new DOMException('Authentication is taking too long. Please try again.', 'TimeoutError')), TOKEN_TIMEOUT_MS);
      }),
    ]);
  } finally {
    clearTimeout(timeout);
  }
}

function httpQueryKey(method, url, token) {
  return ['http', method, url, tokenScope(token)];
}

function invalidateHttpQueries(prefix = null) {
  const queryClient = getQueryClient();
  if (!prefix) {
    void queryClient.invalidateQueries();
    return;
  }

  const normalized = String(prefix).replace(/^\//, '').split('?')[0];
  void queryClient.invalidateQueries({ queryKey: [normalized] });
  queryClient.invalidateQueries({
    queryKey: ['http'],
    predicate: (query) => {
      const url = query.queryKey[2];
      if (typeof url !== 'string') return false;
      const path = url.split('/api/v1/')[1] || '';
      return path === normalized || path.startsWith(`${normalized}/`) || path.startsWith(`${normalized}?`);
    },
  });
}

export function clearApiCache(prefix = null) {
  invalidateHttpQueries(prefix);
}

export async function fetchFromApi(endpoint, token = null, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;
  let authToken = token;
  if (!authToken && typeof window !== 'undefined') {
    const manualToken = localStorage.getItem('uniflow_manual_token');
    if (manualToken) {
      authToken = manualToken;
    } else if (window.Clerk?.session?.getToken) {
      try {
        authToken = await resolveClerkToken(() => window.Clerk.session.getToken());
      } catch {
        throw new DOMException('Authentication is taking too long. Please try again.', 'TimeoutError');
      }
    }
  }

  const { noCache = false, direct = false, timeoutMs, signal, cacheTtlMs = CACHE_STALE_MS, ...requestOptions } = options;
  const queryClient = getQueryClient();

  if (method !== 'GET' || direct) {
    return fetchApiRequest(endpoint, authToken, requestOptions, true, timeoutMs, signal);
  }

  const queryKey = httpQueryKey(method, url, authToken);
  const fetchQuery = () => queryClient.fetchQuery({
    queryKey,
    staleTime: noCache ? 0 : cacheTtlMs,
    queryFn: ({ signal: querySignal }) => fetchApiRequest(endpoint, authToken, requestOptions, true, timeoutMs, signal || querySignal),
  });

  if (signal?.aborted) throw signal.reason || new DOMException('The request was cancelled.', 'AbortError');
  return fetchQuery();
}

async function fetchApiRequest(endpoint, token = null, options = {}, tokenResolved = false, timeoutMs, callerSignal) {
  const method = (options.method || 'GET').toUpperCase();
  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;

  let authToken = token;
  if (!tokenResolved && !authToken && typeof window !== 'undefined') {
    const manualToken = localStorage.getItem('uniflow_manual_token');
    if (manualToken) {
      authToken = manualToken;
    } else if (window.Clerk?.session?.getToken) {
      try {
        authToken = await window.Clerk.session.getToken();
      } catch {
        // anonymous or session pending
      }
    }
  }

  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  const fetchOptions = { ...options };
  delete fetchOptions.noCache;
  delete fetchOptions.direct;
  delete fetchOptions.timeoutMs;
  delete fetchOptions.cacheTtlMs;
  const headers = {
    ...(!isFormData ? { 'Content-Type': 'application/json' } : {}),
    'X-Request-ID': createRequestId(),
    ...(options.headers || {}),
  };

  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }

  // Automatic retry with exponential backoff for network resilience
  let attempts = 0;
  const maxAttempts = method === 'GET' ? 2 : 1;
  const deadline = Date.now() + (timeoutMs || options.timeoutMs || DEFAULT_REQUEST_TIMEOUT_MS);
  let delay = 600;

  while (attempts < maxAttempts) {
    attempts++;
    const controller = new AbortController();
    const remainingMs = deadline - Date.now();
    if (remainingMs <= 0) throw new DOMException('The server took too long to respond.', 'TimeoutError');
    const timeout = setTimeout(() => controller.abort(new DOMException('The server took too long to respond.', 'TimeoutError')), remainingMs);
    const abortFromCaller = () => controller.abort(callerSignal.reason || new DOMException('The request was cancelled.', 'AbortError'));
    callerSignal?.addEventListener('abort', abortFromCaller, { once: true });
    try {
      const res = await fetch(url, { ...fetchOptions, headers, signal: controller.signal });

      if (!res.ok) {
        const errorText = await res.text();
        let errorData;
        try {
          errorData = JSON.parse(errorText);
        } catch {
          errorData = { detail: errorText };
        }
        const msg = typeof errorData?.detail === 'string'
          ? errorData.detail
          : (Array.isArray(errorData?.detail)
              ? errorData.detail.map((d) => d.msg || JSON.stringify(d)).join(', ')
              : (errorData?.detail ? JSON.stringify(errorData.detail) : `Request failed with status ${res.status}`));
        const error = new Error(msg);
        error.status = res.status;
        throw error;
      }

      const json = res.status === 204 ? null : await res.json();
      const isMutation = ['POST', 'PUT', 'DELETE', 'PATCH'].includes(method);

      if (isMutation) {
        const cleanPath = endpoint.startsWith('http') ? new URL(endpoint).pathname.replace('/api/v1', '') : endpoint;
        const endpointPrefix = cleanPath.replace(/^\//, '').split('/')[0].split('?')[0];
        const relatedPrefixes = new Set([endpointPrefix, 'dashboard']);
        if (endpointPrefix === 'classroom' || endpointPrefix === 'assignments' || endpointPrefix === 'courses') {
          relatedPrefixes.add('classroom');
          relatedPrefixes.add('assignments');
          relatedPrefixes.add('courses');
        }
        if (endpointPrefix === 'portal') relatedPrefixes.add('attendance');
        if (endpointPrefix === 'timetable') relatedPrefixes.add('attendance');
        if (endpointPrefix === 'portal' && endpoint.includes('sync_timetable=true')) relatedPrefixes.add('timetable');
        relatedPrefixes.forEach((prefix) => invalidateHttpQueries(prefix));

        const featureQueries = new Set();
        if (['classroom', 'courses'].includes(endpointPrefix)) {
          ['classroom', 'assignments', 'dashboard'].forEach((key) => featureQueries.add(key));
        } else if (endpointPrefix === 'assignments') {
          ['assignments', 'dashboard'].forEach((key) => featureQueries.add(key));
        } else if (endpointPrefix === 'timetable') {
          ['timetable', 'attendance', 'dashboard'].forEach((key) => featureQueries.add(key));
        } else if (endpointPrefix === 'attendance') {
          ['attendance', 'dashboard'].forEach((key) => featureQueries.add(key));
        } else if (endpointPrefix === 'portal') {
          ['portal', 'attendance', 'dashboard'].forEach((key) => featureQueries.add(key));
          if (endpoint.includes('sync_timetable=true')) featureQueries.add('timetable');
        } else if (endpointPrefix === 'rag') {
          featureQueries.add('rag');
        } else {
          featureQueries.add(endpointPrefix);
        }
        const queryClient = getQueryClient();
        featureQueries.forEach((key) => {
          void queryClient.invalidateQueries({ queryKey: [key] });
        });
      }
      return json;
    } catch (err) {
      if (callerSignal?.aborted || err?.name === 'AbortError') throw err;
      const isNetworkError = err instanceof TypeError || err?.name === 'TypeError' || err?.name === 'TimeoutError' || err?.message?.includes('fetch') || err?.status == null;
      const retryableStatus = [429, 502, 503, 504].includes(err?.status);
      const shouldRetry = isNetworkError || retryableStatus;
      if (attempts >= maxAttempts || !shouldRetry) {
        console.warn(`API request issue for ${endpoint}:`, err?.message || err);
        throw err;
      }
      if (Date.now() + delay >= deadline) throw err;
      await new Promise((r) => setTimeout(r, delay));
      delay *= 1.8;
    } finally {
      clearTimeout(timeout);
      callerSignal?.removeEventListener('abort', abortFromCaller);
    }
  }
}

export const api = {
  // Cache utility
  clearCache: clearApiCache,
  getRequestToken: resolveClerkToken,

  // Health
  checkHealth: async () => {
    try {
      const res = await fetch(`${ROOT_URL}/health`, { signal: AbortSignal.timeout(5_000) });
      return res.ok ? await res.json() : { status: 'unreachable' };
    } catch {
      return { status: 'unreachable' };
    }
  },

  // Auth & Sync
  syncUser: async (userData, token = null) => {
    return fetchFromApi('/auth/sync-user', token, {
      method: 'POST',
      body: JSON.stringify(userData),
    });
  },

  getAuthStatus: async (token = null, options = {}) => {
    return fetchFromApi('/auth/status', token, { cacheTtlMs: 15_000, ...options });
  },

  getPrivateAccessStatus: async (token = null, options = {}) => fetchFromApi('/auth/access/status', token, { cacheTtlMs: 15_000, ...options }),
  requestPrivateAccess: async (token = null) => fetchFromApi('/auth/access/request', token, { method: 'POST', body: JSON.stringify({}) }),
  redeemPrivateAccess: async (code, token = null) => fetchFromApi('/auth/access/redeem', token, {
    method: 'POST', body: JSON.stringify({ code }),
  }),

  getGoogleAuthUrl: async (token = null, redirectTo = null) => {
    const query = redirectTo ? `?redirect_to=${encodeURIComponent(redirectTo)}` : '';
    return fetchFromApi(`/auth/google${query}`, token);
  },

  disconnectGoogle: async (token = null) => {
    return fetchFromApi('/auth/google/disconnect', token, { method: 'POST' });
  },

  // Notification Email Preferences
  getNotificationEmail: async (token = null, options = {}) => {
    return fetchFromApi('/auth/notification-email', token, { cacheTtlMs: 60_000, ...options });
  },

  setNotificationEmail: async (email, token = null) => {
    return fetchFromApi('/auth/notification-email', token, {
      method: 'PUT',
      body: JSON.stringify({ email }),
    });
  },

  deleteNotificationEmail: async (token = null) => {
    return fetchFromApi('/auth/notification-email', token, { method: 'DELETE' });
  },

  // Student Academic Profile
  getStudentProfile: async (token = null, options = {}) => {
    return fetchFromApi('/classroom/student-profile', token, { cacheTtlMs: 60_000, ...options });
  },

  updateStudentProfile: async (data, token = null) => {
    return fetchFromApi('/classroom/student-profile', token, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  // Onboarding Setup Flow
  getOnboardingStatus: async (token = null) => fetchFromApi('/classroom/onboarding-status', token),
  dismissOnboarding: async (token = null) => fetchFromApi('/classroom/onboarding-dismiss', token, { method: 'POST' }),
  saveOnboarding: async (data, token = null) => fetchFromApi('/classroom/onboarding-save', token, {
    method: 'POST',
    body: JSON.stringify(data),
  }),

  // Dashboard
  getOverview: async (token = null, noCache = false, options = {}) => {
    return fetchFromApi('/dashboard/overview', token, { cacheTtlMs: 45_000, ...options, ...(noCache ? { noCache: true } : {}) });
  },

  getUpcoming: async (days = 7, token = null) => {
    return fetchFromApi(`/dashboard/upcoming?days=${days}`, token);
  },
  getAutomationHistory: async (limit = 40, token = null, options = {}) => fetchFromApi(`/dashboard/automation-history?limit=${limit}`, token, options),

  getAttendanceSummary: async (token = null, options = {}) => {
    return fetchFromApi('/dashboard/attendance-summary', token, { cacheTtlMs: 60_000, ...options });
  },

  dismissActiveCrewRun: async (assignmentId, token = null) => {
    return fetchFromApi(`/dashboard/active-crew-runs/${assignmentId}/dismiss`, token, { method: 'POST', noCache: true });
  },

  getAgentRuns: async (limit = 20, token = null, options = {}) => fetchFromApi(`/agent/runs?limit=${Math.min(100, Math.max(1, Number(limit) || 20))}`, token, options),
  getAgentRunStats: async (token = null, options = {}) => fetchFromApi('/agent/stats', token, options),
  getAgentRunEvents: async (runId, token = null, options = {}) => fetchFromApi(`/agent/runs/${encodeURIComponent(runId)}/events`, token, options),

  // Classroom & Courses
  getCourses: async (token = null, since = null, options = {}) => {
    const { limit = 500, offset = 0, ...requestOptions } = options || {};
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (since) params.set('since', since);
    return fetchFromApi(`/classroom/courses?${params.toString()}`, token, { cacheTtlMs: 120_000, ...requestOptions });
  },

  getCourseStudents: async (courseId, token = null) => fetchFromApi(`/classroom/courses/${courseId}/students`, token),

  getClassroomAnnouncements: async (token = null, since = null) => fetchFromApi(`/classroom/announcements${since ? `?since=${encodeURIComponent(since)}` : ''}`, token),

  getClassroomSettings: async (token = null, options = {}) => fetchFromApi('/classroom/settings', token, { cacheTtlMs: 30_000, ...options }),

  saveClassroomSettings: async (settings, token = null) => fetchFromApi('/classroom/settings', token, {
    method: 'POST',
    body: JSON.stringify(settings),
  }),

  getTimetableClasses: async (token = null, options = {}) => fetchFromApi('/timetable/classes', token, { cacheTtlMs: 120_000, ...options }),

  getTimetableClassById: async (id, token = null) => fetchFromApi(`/timetable/classes/${id}`, token),

  updateTimetableClass: async (id, entry, token = null) => fetchFromApi(`/timetable/classes/${id}`, token, {
    method: 'PUT', body: JSON.stringify(entry),
  }),

  createSingleTimetableClass: async (entry, token = null) => fetchFromApi('/timetable/classes/single', token, {
    method: 'POST', body: JSON.stringify(entry),
  }),

  getTodaysClasses: async (token = null) => fetchFromApi('/timetable/today', token),

  parseTimetableImage: async (file, token = null) => {
    const form = new FormData();
    form.append('image', file);
    return fetchFromApi('/timetable/parse-image', token, { method: 'POST', body: form });
  },

  saveTimetableClasses: async (entries, token = null, override = false) => fetchFromApi(`/timetable/classes?override=${override ? 'true' : 'false'}`, token, {
    method: 'POST', body: JSON.stringify(entries),
  }),

  deleteTimetableClass: async (id, token = null) => fetchFromApi(`/timetable/classes/${id}`, token, { method: 'DELETE' }),

  clearAllTimetableClasses: async (token = null) => fetchFromApi('/timetable/classes/all', token, { method: 'DELETE' }),

  clearDashboardTimetable: async (token = null) => fetchFromApi('/dashboard/clear-timetable', token, { method: 'POST' }),

  getPortalSettings: async (token = null, options = {}) => fetchFromApi('/portal/settings', token, { cacheTtlMs: 30_000, ...options }),

  savePortalUrl: async (url, token = null, options = {}) => fetchFromApi('/portal/settings', token, {
    method: 'PUT', body: JSON.stringify({ url, ...options }),
  }),

  syncPortalCookies: async (cookies, portalUrl = null, token = null) => fetchFromApi('/portal/sync-cookies', token, {
    method: 'POST', body: JSON.stringify({ cookies, portal_url: portalUrl }),
  }),

  disconnectPortalCookies: async (token = null) => fetchFromApi('/portal/cookies', token, {
    method: 'DELETE',
  }),


  openPortalBrowser: async (token = null) => fetchFromApi('/portal/open', token, { method: 'POST' }),
  getPortalConnectionStatus: async (token = null) => fetchFromApi('/portal/connection-status', token, { cacheTtlMs: 15_000 }),

  capturePortalReport: async (token = null) => fetchFromApi('/portal/capture', token, { method: 'POST' }),

  syncPortalHeadless: async (token = null, syncTimetable = false) => fetchFromApi(`/portal/sync-headless${syncTimetable ? '?sync_timetable=true' : ''}`, token, { method: 'POST' }),
  queuePortalSync: async (token = null) => fetchFromApi('/portal/sync', token, { method: 'POST' }),
  getPortalSyncStatus: async (jobId, token = null, options = {}) => fetchFromApi(`/portal/sync/${encodeURIComponent(jobId)}`, token, { noCache: true, ...options }),

  closePortalBrowser: async (token = null) => fetchFromApi('/portal/close', token, { method: 'POST' }),

  getTodaySchedules: async (token = null) => {
    return fetchFromApi('/classroom/schedules/today', token);
  },

  getSyncStatus: async (token = null, options = {}) => fetchFromApi('/classroom/sync/status', token, { cacheTtlMs: 15_000, ...options }),

  triggerSync: async (semesterStartDate = null, token = null) => {
    return fetchFromApi('/classroom/sync', token, {
      method: 'POST',
      body: JSON.stringify(semesterStartDate ? { semester_start_date: semesterStartDate } : {}),
      timeoutMs: 120_000,
    });
  },

  triggerAgentRun: async (trigger = 'manual', token = null) => {
    return fetchFromApi('/classroom/sync', token, { method: 'POST', timeoutMs: 120_000 });
  },

  // Assignments
  getAssignments: async (status = null, token = null, since = null, options = {}) => {
    const { limit = 500, offset = 0, ...requestOptions } = options || {};
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    if (since) params.set('since', since);
    params.set('limit', String(limit));
    params.set('offset', String(offset));
    const query = params.toString();
    const url = query ? `/assignments?${query}` : '/assignments';
    return fetchFromApi(url, token, { cacheTtlMs: 45_000, ...requestOptions });
  },

  getAssignment: async (id, token = null, options = {}) => fetchFromApi(`/assignments/${id}`, token, options),

  // University
  getExams: async (token = null, since = null, options = {}) => {
    const { limit = 500, offset = 0, ...requestOptions } = options || {};
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (since) params.set('since', since);
    return fetchFromApi(`/university/exams?${params.toString()}`, token, requestOptions);
  },

  getQuizzes: async (token = null, since = null, options = {}) => {
    const { limit = 500, offset = 0, ...requestOptions } = options || {};
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (since) params.set('since', since);
    return fetchFromApi(`/university/quizzes?${params.toString()}`, token, requestOptions);
  },

  getAnnouncements: async (token = null, since = null, options = {}) => {
    return fetchFromApi(`/university/announcements${since ? `?since=${encodeURIComponent(since)}` : ''}`, token, options);
  },

  getRecentEmails: async (token = null, since = null, category = null, options = {}) => {
    const params = new URLSearchParams();
    if (since) params.set('since', since);
    if (category && category !== 'all') params.set('category', category);
    const q = params.toString();
    return fetchFromApi(`/integrations/google/emails${q ? `?${q}` : ''}`, token, options);
  },

  getRecentDriveFiles: async (token = null, options = {}) => fetchFromApi('/integrations/google/drive', token, options),
  getClassroomStudyMaterials: async (token = null, options = {}) => {
    const { courseId, query, category, limit = 500, ...requestOptions } = typeof options === 'object' && options !== null ? options : {};
    const params = new URLSearchParams({ limit: String(limit) });
    if (courseId) params.set('course_id', String(courseId));
    if (query) params.set('query', String(query));
    if (category && category !== 'all') params.set('category', String(category));
    return fetchFromApi(`/rag/materials?${params.toString()}`, token, requestOptions);
  },
  syncStudyMaterials: async (token = null) => fetchFromApi('/rag/sync-materials', token, { method: 'POST' }),
  uploadStudyMaterial: async (courseId, file, token = null) => {
    const form = new FormData();
    form.append('course_id', String(courseId));
    form.append('file', file);
    return fetchFromApi('/rag/materials/upload', token, {
      method: 'POST',
      body: form,
    });
  },
  askCourseMaterials: async (data, token = null) => fetchFromApi('/rag/chat', token, { method: 'POST', body: JSON.stringify(data) }),
  getRagConversationMessages: async (conversationId, token = null) => fetchFromApi(`/rag/conversations/${conversationId}/messages`, token),

  // RAG v2 (DocSense)
  getRagDocuments: async (token = null, options = {}) => fetchFromApi('/rag/documents', token, { cacheTtlMs: 45_000, direct: true, ...options }),
  uploadRagDocument: async (file, token = null) => {
    const form = new FormData();
    form.append('file', file);
    return fetchFromApi('/rag/documents', token, { method: 'POST', body: form });
  },
  getRagDocumentStatus: async (documentId, token = null) => fetchFromApi(`/rag/documents/${documentId}/status`, token, { noCache: true }),
  deleteRagDocument: async (documentId, token = null) => fetchFromApi(`/rag/documents/${documentId}`, token, { method: 'DELETE' }),
  ragChat: async (data, token = null) => fetchFromApi('/rag/chat', token, { method: 'POST', body: JSON.stringify(data), timeoutMs: 90_000 }),
  ragChatStream: async (data, token = null) => {
    const url = `${API_BASE}/rag/chat/stream`;
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Request-ID': createRequestId(),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(data),
    });
    return res;
  },
  ragSearch: async (params, token = null) => {
    const query = new URLSearchParams(params).toString();
    return fetchFromApi(`/rag/search?${query}`, token);
  },
  getRagConversations: async (token = null, offset = 0, limit = 20, options = {}) => fetchFromApi(`/rag/conversations?offset=${offset}&limit=${limit}`, token, { direct: true, ...options }),
  createRagConversation: async (data, token = null) => fetchFromApi('/rag/conversations', token, { method: 'POST', body: JSON.stringify(data) }),
  getRagConversation: async (conversationId, token = null) => fetchFromApi(`/rag/conversations/${conversationId}`, token),
  updateRagConversation: async (conversationId, data, token = null) => fetchFromApi(`/rag/conversations/${conversationId}`, token, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteRagConversation: async (conversationId, token = null) => fetchFromApi(`/rag/conversations/${conversationId}`, token, { method: 'DELETE' }),
  getRagUsage: async (token = null, options = {}) => fetchFromApi('/rag/usage', token, { cacheTtlMs: 60_000, direct: true, ...options }),
  syncRagClassroom: async (token = null) => fetchFromApi('/rag/sync-classroom', token, { method: 'POST', timeoutMs: 120_000 }),
  generateStudyPlan: async (payload, token = null, options = {}) => fetchFromApi('/rag/study-plans', token, {
    method: 'POST',
    body: JSON.stringify(payload),
    ...options,
  }),
  getStudyPlans: async (token = null, limit = 50, options = {}) => fetchFromApi(`/rag/study-plans?limit=${limit}`, token, options),
  getStudyPlan: async (planId, token = null, options = {}) => fetchFromApi(`/rag/study-plans/${encodeURIComponent(planId)}`, token, options),
  updateStudyPlanSession: async (planId, sessionId, payload, token = null) => fetchFromApi(`/rag/study-plans/${encodeURIComponent(planId)}/sessions/${encodeURIComponent(sessionId)}`, token, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }),

  // Assignment Templates
  getAssignmentTemplates: async (token = null, options = {}) => fetchFromApi('/classroom/templates', token, options),

  createAssignmentTemplate: async (data, token = null) => fetchFromApi('/classroom/templates', token, {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  createStarterAssignmentTemplate: async (token = null) => fetchFromApi('/classroom/templates/starter', token, { method: 'POST' }),

  setDefaultTemplate: async (templateId, token = null) => fetchFromApi(`/classroom/templates/${templateId}/default`, token, {
    method: 'PUT',
  }),

  deleteAssignmentTemplate: async (templateId, token = null) => fetchFromApi(`/classroom/templates/${templateId}`, token, {
    method: 'DELETE',
  }),

  listDriveDocsForTemplates: async (query = null, token = null) => {
    const params = query ? `?query=${encodeURIComponent(query)}` : '';
    return fetchFromApi(`/classroom/templates/drive-files${params}`, token);
  },

  // Student Turn-in
  turnInAssignment: async (assignmentId, data, token = null) => {
    let body;
    if (typeof FormData !== 'undefined' && data instanceof FormData) {
      body = data;
    } else if (Array.isArray(data?.files)) {
      body = new FormData();
      if (data.template_id != null) body.append('template_id', String(data.template_id));
      data.files.forEach((file) => body.append('files', file, file.name));
    } else {
      body = JSON.stringify(data);
    }
    return fetchFromApi(`/classroom/assignments/${assignmentId}/turn-in`, token, {
      method: 'POST',
      body,
    });
  },

  unsubmitAssignment: async (assignmentId, token = null) => fetchFromApi(`/classroom/assignments/${assignmentId}/unsubmit`, token, { method: 'POST' }),
  quickTurnInAssignment: async (assignmentId, token = null, action = 'turn_in') => fetchFromApi(`/classroom/assignments/${assignmentId}/quick-turn-in`, token, { method: 'POST', body: JSON.stringify({ confirm_submission: true, action }) }),
  confirmAssignmentTurnIn: async (assignmentId, token = null) => fetchFromApi(`/classroom/assignments/${assignmentId}/confirm-turn-in`, token, { method: 'POST' }),
  emailAssignmentSolution: async (assignmentId, token = null) => fetchFromApi(`/classroom/assignments/${assignmentId}/solution/email`, token, { method: 'POST' }),
  getCourseAutoTurnIn: async (courseId, token = null) => fetchFromApi(`/classroom/courses/${courseId}/auto-turn-in`, token),
  updateCourseAutoTurnIn: async (courseId, data, token = null) => fetchFromApi(`/classroom/courses/${courseId}/auto-turn-in`, token, {
    method: 'PUT',
    body: JSON.stringify(data),
  }),
  checkCourseAutoTurnIn: async (courseId, token = null) => fetchFromApi(`/classroom/courses/${courseId}/check-auto-turn-in`, token, { method: 'POST', body: JSON.stringify({ confirm_submission: true }) }),

  // AI Tutor & Review Panels
  getAssignmentBreakdown: async (assignmentId, token = null) => fetchFromApi(`/assignments/${assignmentId}/breakdown`, token),

  askTutor: async (assignmentId, payload, token = null) => fetchFromApi(`/assignments/${assignmentId}/tutor`, token, {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  getTutorConversations: async (assignmentId, token = null) => fetchFromApi(`/assignments/${assignmentId}/conversations`, token),
  getTutorConversationMessages: async (assignmentId, conversationId, token = null) => fetchFromApi(`/assignments/${assignmentId}/conversations/${conversationId}/messages`, token),

  scheduleTurnIn: async (assignmentId, payload, token = null) => fetchFromApi(`/assignments/${assignmentId}/schedule-turn-in`, token, {
    method: 'POST',
    body: JSON.stringify(payload),
  }),

  uploadAssignmentMaterial: async (assignmentId, file, token = null) => {
    const form = new FormData();
    form.append('file', file);
    return fetchFromApi(`/classroom/assignments/${assignmentId}/materials/upload`, token, {
      method: 'POST',
      body: form,
    });
  },

  // AI Solution Generation & Agentic Export
  generateAssignmentSolution: async (assignmentId, data = {}, token = null) => fetchFromApi(`/classroom/assignments/${assignmentId}/solution/generate`, token, {
    method: 'POST',
    body: JSON.stringify(data),
  }),

  generateAssignmentImage: async (assignmentId, prompt, token = null) => fetchFromApi(`/classroom/assignments/${assignmentId}/solution/images`, token, {
    method: 'POST',
    body: JSON.stringify({ prompt }),
  }),

  exportAssignmentDoc: async (assignmentId, token = null) => fetchFromApi(`/classroom/assignments/${assignmentId}/export-doc`, token, {
    method: 'POST',
  }),

  getSolutionStatus: async (assignmentId, token = null, options = {}) => fetchFromApi(`/classroom/assignments/${assignmentId}/solution/status`, token, options),
  clearSolutionError: async (assignmentId, token = null) => fetchFromApi(`/classroom/assignments/${assignmentId}/solution/clear-error`, token, { method: 'POST' }),

  openClaudeBrowser: async (token = null) => fetchFromApi('/classroom/claude-browser/open', token, {
    method: 'POST',
  }),

  getClassroomBrowserStatus: async (token = null, options = {}) => fetchFromApi('/classroom/gcr-browser/status', token, { cacheTtlMs: 10_000, ...options }),
  getServicesStatus: async (token = null, options = {}) => fetchFromApi('/classroom/services-status', token, { direct: true, noCache: true, ...options }),

  syncClassroomSession: async (cookies, userAgent = null, token = null) => fetchFromApi('/classroom/gcr-browser/sync-session', token, {
    method: 'POST',
    body: JSON.stringify({ cookies, user_agent: userAgent }),
  }),

  disconnectClassroomSession: async (token = null) => fetchFromApi('/classroom/gcr-browser/session', token, {
    method: 'DELETE',
  }),

  getClaudeBrowserStatus: async (token = null, options = {}) => fetchFromApi('/classroom/claude-browser/status', token, { cacheTtlMs: 10_000, ...options }),

  setAutomaticClaudeSolving: async (enabled, token = null) => fetchFromApi('/classroom/claude-browser/automatic-solving', token, {
    method: 'PUT',
    body: JSON.stringify({ enabled }),
  }),

  resumeClaudeJobs: async (token = null) => fetchFromApi('/classroom/claude-browser/jobs/resume', token, {
    method: 'POST',
  }),

  deleteClaudeBrowserProfile: async (token = null) => fetchFromApi('/classroom/claude-browser/profile', token, {
    method: 'DELETE',
  }),

  syncClaudeSession: async (sessionKey, userAgent = null, token = null) => fetchFromApi('/classroom/claude-browser/sync-session', token, {
    method: 'POST',
    body: JSON.stringify({ session_key: sessionKey, user_agent: userAgent }),
  }),

  disconnectClaudeSession: async (token = null) => fetchFromApi('/classroom/claude-browser/session', token, {
    method: 'DELETE',
  }),

  // Notifications & sync activity
  getNotifications: async (status = null, limit = 50, token = null, options = {}) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (status) params.set('status', status);
    return fetchFromApi(`/notifications?${params}`, token, options);
  },
  getNotificationStats: async (token = null, options = {}) => fetchFromApi('/notifications/stats/summary', token, options),
  sendNotification: async (id, token = null) => fetchFromApi(`/notifications/send/${id}`, token, { method: 'POST' }),
  sendPendingNotifications: async (limit = 50, token = null) => fetchFromApi(`/notifications/send-pending?limit=${limit}`, token, { method: 'POST' }),
  getMyNotificationEmail: async (token = null) => fetchFromApi('/notifications/my-email', token),
  createNotificationForMe: async (data, token = null) => fetchFromApi('/notifications/create-for-me', token, {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  checkAlerts: async (token = null) => fetchFromApi('/notifications/check-alerts', token, { method: 'POST' }),
  sendTestEmail: async (recipient = null, token = null) => {
    const params = recipient ? `?recipient=${encodeURIComponent(recipient)}` : '';
    return fetchFromApi(`/notifications/test-email${params}`, token, { method: 'POST' });
  },
  triggerDailyDigest: async (token = null) => fetchFromApi('/notifications/daily-digest', token, { method: 'POST' }),
  getDailyBriefingPreferences: async (token = null, options = {}) => fetchFromApi('/notifications/daily-briefing-preferences', token, { cacheTtlMs: 30_000, ...options }),
  saveDailyBriefingPreferences: async (data, token = null) => fetchFromApi('/notifications/daily-briefing-preferences', token, { method: 'PUT', body: JSON.stringify(data) }),
  previewAlerts: async (targetDate = null, token = null) => {
    const params = targetDate ? `?target_date=${encodeURIComponent(targetDate)}` : '';
    return fetchFromApi(`/notifications/preview-alerts${params}`, token);
  },

  // Manual / Seeded Fallback Authentication
  manualLogin: async (email, password) => fetchFromApi('/auth/manual/login', null, {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  }),
  manualSignup: async (userData) => fetchFromApi('/auth/manual/signup', null, {
    method: 'POST',
    body: JSON.stringify(userData),
  }),
  getSeededUsers: async () => fetchFromApi('/auth/manual/seeded-users'),

};

export const getRagDocuments = api.getRagDocuments;
export const uploadRagDocument = api.uploadRagDocument;
export const getRagDocumentStatus = api.getRagDocumentStatus;
export const deleteRagDocument = api.deleteRagDocument;
export const ragChat = api.ragChat;
export const ragChatStream = api.ragChatStream;
export const ragSearch = api.ragSearch;
export const getRagConversations = api.getRagConversations;
export const createRagConversation = api.createRagConversation;
export const getRagConversation = api.getRagConversation;
export const updateRagConversation = api.updateRagConversation;
export const deleteRagConversation = api.deleteRagConversation;
export const getRagUsage = api.getRagUsage;
export const syncRagClassroom = api.syncRagClassroom;
export const triggerSync = api.triggerSync;
export const manualLogin = api.manualLogin;
export const manualSignup = api.manualSignup;
export const getSeededUsers = api.getSeededUsers;

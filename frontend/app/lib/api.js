function getApiBase() {
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  const isProduction = process.env.NODE_ENV === 'production';
  
  if (envUrl) {
    return envUrl;
  }

  // Graceful fallback so Next.js static prerender and Vercel builds do not crash
  if (isProduction) {
    return 'https://univlfow.koreacentral.cloudapp.azure.com/api/v1';
  }
  
  return 'http://localhost:8000/api/v1';
}

const API_BASE = getApiBase();
const ROOT_URL = API_BASE.replace('/api/v1', '');

// In-memory client cache with TTL
const clientCache = new Map();
const CACHE_TTL_MS = 25000; // 25 seconds

export function clearApiCache(prefix = null) {
  if (!prefix) {
    clientCache.clear();
    return;
  }
  for (const [key] of clientCache) {
    if (key.includes(prefix)) {
      clientCache.delete(key);
    }
  }
}

export async function fetchFromApi(endpoint, token = null, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;
  const cacheKey = `${method}:${url}:${token || 'anon'}`;

  // Check cache for GET requests
  if (method === 'GET' && !options.noCache) {
    const cached = clientCache.get(cacheKey);
    if (cached && Date.now() - cached.timestamp < CACHE_TTL_MS) {
      return cached.data;
    }
  }

  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  const fetchOptions = { ...options };
  delete fetchOptions.noCache;
  const headers = {
    ...(!isFormData ? { 'Content-Type': 'application/json' } : {}),
    ...(options.headers || {}),
  };

  let authToken = token;
  if (!authToken && typeof window !== 'undefined' && window.Clerk?.session?.getToken) {
    try {
      authToken = await window.Clerk.session.getToken();
    } catch {
      // anonymous or session pending
    }
  }

  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }

  // Automatic retry with exponential backoff for network resilience
  let attempts = 0;
  const maxAttempts = method === 'GET' ? 3 : 1;
  let delay = 600;

  while (attempts < maxAttempts) {
    attempts++;
    try {
      const res = await fetch(url, {
        ...fetchOptions,
        headers,
      });

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

      const json = await res.json();
      if (method === 'GET' && !options.noCache) {
        clientCache.set(cacheKey, { timestamp: Date.now(), data: json });
      } else {
        // Targeted cache invalidation: clear related keys across coupled domains (assignments, classroom, courses, dashboard)
        const cleanPath = endpoint.startsWith('http') ? new URL(endpoint).pathname.replace('/api/v1', '') : endpoint;
        const endpointPrefix = cleanPath.replace(/^\//, '').split('/')[0].split('?')[0];
        const relatedPrefixes = new Set([endpointPrefix, 'dashboard']);
        if (endpointPrefix === 'classroom' || endpointPrefix === 'assignments' || endpointPrefix === 'courses') {
          relatedPrefixes.add('classroom');
          relatedPrefixes.add('assignments');
          relatedPrefixes.add('courses');
        }
        for (const [key] of clientCache) {
          for (const prefix of relatedPrefixes) {
            if (prefix && key.includes(prefix)) {
              clientCache.delete(key);
              break;
            }
          }
        }
      }
      return json;
    } catch (err) {
      const isNetworkError = err instanceof TypeError || err?.name === 'TypeError' || err?.message?.includes('fetch') || err?.status == null;
      const retryableStatus = [429, 502, 503, 504].includes(err?.status);
      const shouldRetry = isNetworkError || retryableStatus;
      if (attempts >= maxAttempts || !shouldRetry) {
        console.warn(`API request issue for ${endpoint}:`, err?.message || err);
        throw err;
      }
      await new Promise((r) => setTimeout(r, delay));
      delay *= 1.8;
    }
  }
}

export const api = {
  // Cache utility
  clearCache: clearApiCache,

  // Health
  checkHealth: async () => {
    try {
      const res = await fetch(`${ROOT_URL}/health`);
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

  getAuthStatus: async (token = null) => {
    return fetchFromApi('/auth/status', token);
  },

  getPrivateAccessStatus: async (token = null) => fetchFromApi('/auth/access/status', token, { noCache: true }),
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
  getNotificationEmail: async (token = null) => {
    return fetchFromApi('/auth/notification-email', token);
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
  getStudentProfile: async (token = null) => {
    return fetchFromApi('/classroom/student-profile', token);
  },

  updateStudentProfile: async (data, token = null) => {
    return fetchFromApi('/classroom/student-profile', token, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  // Onboarding Setup Flow
  getOnboardingStatus: async (token = null) => fetchFromApi('/classroom/onboarding-status', token, { noCache: true }),
  dismissOnboarding: async (token = null) => fetchFromApi('/classroom/onboarding-dismiss', token, { method: 'POST' }),
  saveOnboarding: async (data, token = null) => fetchFromApi('/classroom/onboarding-save', token, {
    method: 'POST',
    body: JSON.stringify(data),
  }),

  // Dashboard
  getOverview: async (token = null, noCache = false) => {
    return fetchFromApi('/dashboard/overview', token, noCache ? { noCache: true } : {});
  },

  getUpcoming: async (days = 7, token = null) => {
    return fetchFromApi(`/dashboard/upcoming?days=${days}`, token);
  },
  getAutomationHistory: async (limit = 40, token = null) => fetchFromApi(`/dashboard/automation-history?limit=${limit}`, token),

  getAttendanceSummary: async (token = null) => {
    return fetchFromApi('/dashboard/attendance-summary', token);
  },

  dismissActiveCrewRun: async (assignmentId, token = null) => {
    return fetchFromApi(`/dashboard/active-crew-runs/${assignmentId}/dismiss`, token, { method: 'POST', noCache: true });
  },

  // Classroom & Courses
  getCourses: async (token = null, since = null) => {
    return fetchFromApi(`/classroom/courses${since ? `?since=${encodeURIComponent(since)}` : ''}`, token);
  },

  getCourseStudents: async (courseId, token = null) => fetchFromApi(`/classroom/courses/${courseId}/students`, token),

  getClassroomAnnouncements: async (token = null, since = null) => fetchFromApi(`/classroom/announcements${since ? `?since=${encodeURIComponent(since)}` : ''}`, token),

  getClassroomSettings: async (token = null) => fetchFromApi('/classroom/settings', token),

  saveClassroomSettings: async (settings, token = null) => fetchFromApi('/classroom/settings', token, {
    method: 'POST',
    body: JSON.stringify(settings),
  }),

  getTimetableClasses: async (token = null) => fetchFromApi('/timetable/classes', token),

  getTimetableClassById: async (id, token = null) => fetchFromApi(`/timetable/classes/${id}`, token),

  createSingleTimetableClass: async (entry, token = null) => fetchFromApi('/timetable/classes/single', token, {
    method: 'POST', body: JSON.stringify(entry),
  }),

  getTodaysClasses: async (token = null) => fetchFromApi('/timetable/today', token),

  parseTimetableImage: async (file, token = null) => {
    const form = new FormData();
    form.append('image', file);
    return fetchFromApi('/timetable/parse-image', token, { method: 'POST', body: form });
  },

  saveTimetableClasses: async (entries, token = null, override = true) => fetchFromApi(`/timetable/classes?override=${override ? 'true' : 'false'}`, token, {
    method: 'POST', body: JSON.stringify(entries),
  }),

  deleteTimetableClass: async (id, token = null) => fetchFromApi(`/timetable/classes/${id}`, token, { method: 'DELETE' }),

  clearAllTimetableClasses: async (token = null) => fetchFromApi('/timetable/classes/all', token, { method: 'DELETE' }),

  clearDashboardTimetable: async (token = null) => fetchFromApi('/dashboard/clear-timetable', token, { method: 'POST' }),

  getPortalSettings: async (token = null) => fetchFromApi('/portal/settings', token, { noCache: true }),

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
  getPortalConnectionStatus: async (token = null) => fetchFromApi('/portal/connection-status', token, { noCache: true }),

  capturePortalReport: async (token = null) => fetchFromApi('/portal/capture', token, { method: 'POST' }),

  syncPortalHeadless: async (token = null) => fetchFromApi('/portal/sync-headless', token, { method: 'POST' }),
  queuePortalSync: async (token = null) => fetchFromApi('/portal/sync', token, { method: 'POST' }),
  getPortalSyncStatus: async (jobId, token = null) => fetchFromApi(`/portal/sync/${encodeURIComponent(jobId)}`, token, { noCache: true }),

  closePortalBrowser: async (token = null) => fetchFromApi('/portal/close', token, { method: 'POST' }),

  getTodaySchedules: async (token = null) => {
    return fetchFromApi('/classroom/schedules/today', token);
  },

  getSyncStatus: async (token = null) => {
    return fetchFromApi('/classroom/sync/status', token);
  },

  triggerSync: async (semesterStartDate = null, token = null) => {
    return fetchFromApi('/classroom/sync', token, {
      method: 'POST',
      body: JSON.stringify(semesterStartDate ? { semester_start_date: semesterStartDate } : {}),
    });
  },

  triggerAgentRun: async (trigger = 'manual', token = null) => {
    return fetchFromApi('/classroom/sync', token, { method: 'POST' });
  },

  // Assignments
  getAssignments: async (status = null, token = null, since = null, options = {}) => {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    if (since) params.set('since', since);
    const query = params.toString();
    const url = query ? `/assignments?${query}` : '/assignments';
    return fetchFromApi(url, token, options);
  },

  getAssignment: async (id, token = null, options = {}) => fetchFromApi(`/assignments/${id}`, token, options),

  // University
  getExams: async (token = null, since = null) => {
    return fetchFromApi(`/university/exams${since ? `?since=${encodeURIComponent(since)}` : ''}`, token);
  },

  getAnnouncements: async (token = null, since = null) => {
    return fetchFromApi(`/university/announcements${since ? `?since=${encodeURIComponent(since)}` : ''}`, token);
  },

  getRecentEmails: async (token = null, since = null, category = null) => {
    const params = new URLSearchParams();
    if (since) params.set('since', since);
    if (category && category !== 'all') params.set('category', category);
    const q = params.toString();
    return fetchFromApi(`/integrations/google/emails${q ? `?${q}` : ''}`, token);
  },

  getRecentDriveFiles: async (token = null) => fetchFromApi('/integrations/google/drive', token),
  getClassroomStudyMaterials: async (token = null, options = {}) => {
    const { courseId, query, category, limit = 500 } = typeof options === 'object' && options !== null ? options : {};
    const params = new URLSearchParams({ limit: String(limit) });
    if (courseId) params.set('course_id', String(courseId));
    if (query) params.set('query', String(query));
    if (category && category !== 'all') params.set('category', String(category));
    return fetchFromApi(`/rag/materials?${params.toString()}`, token);
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
  getRagConversations: async (token = null) => fetchFromApi('/rag/conversations', token),
  getRagConversationMessages: async (conversationId, token = null) => fetchFromApi(`/rag/conversations/${conversationId}/messages`, token),

  // RAG v2 (DocSense)
  getRagDocuments: async (token = null) => fetchFromApi('/rag/documents', token),
  uploadRagDocument: async (file, token = null) => {
    const form = new FormData();
    form.append('file', file);
    return fetchFromApi('/rag/documents', token, { method: 'POST', body: form });
  },
  getRagDocumentStatus: async (documentId, token = null) => fetchFromApi(`/rag/documents/${documentId}/status`, token),
  deleteRagDocument: async (documentId, token = null) => fetchFromApi(`/rag/documents/${documentId}`, token, { method: 'DELETE' }),
  ragChat: async (data, token = null) => fetchFromApi('/rag/chat', token, { method: 'POST', body: JSON.stringify(data) }),
  ragChatStream: async (data, token = null) => {
    const url = `${API_BASE}/rag/chat/stream`;
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
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
  getRagConversations: async (token = null, offset = 0, limit = 20) => fetchFromApi(`/rag/conversations?offset=${offset}&limit=${limit}`, token),
  createRagConversation: async (data, token = null) => fetchFromApi('/rag/conversations', token, { method: 'POST', body: JSON.stringify(data) }),
  getRagConversation: async (conversationId, token = null) => fetchFromApi(`/rag/conversations/${conversationId}`, token),
  updateRagConversation: async (conversationId, data, token = null) => fetchFromApi(`/rag/conversations/${conversationId}`, token, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteRagConversation: async (conversationId, token = null) => fetchFromApi(`/rag/conversations/${conversationId}`, token, { method: 'DELETE' }),
  getRagUsage: async (token = null) => fetchFromApi('/rag/usage', token),

  // Assignment Templates
  getAssignmentTemplates: async (token = null) => fetchFromApi('/classroom/templates', token),

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

  getClassroomBrowserStatus: async (token = null) => fetchFromApi('/classroom/gcr-browser/status', token, { noCache: true }),

  syncClassroomSession: async (cookies, userAgent = null, token = null) => fetchFromApi('/classroom/gcr-browser/sync-session', token, {
    method: 'POST',
    body: JSON.stringify({ cookies, user_agent: userAgent }),
  }),

  disconnectClassroomSession: async (token = null) => fetchFromApi('/classroom/gcr-browser/session', token, {
    method: 'DELETE',
  }),

  getClaudeBrowserStatus: async (token = null) => fetchFromApi('/classroom/claude-browser/status', token, { noCache: true }),

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
  getNotifications: async (status = null, limit = 50, token = null) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (status) params.set('status', status);
    return fetchFromApi(`/notifications?${params}`, token);
  },
  getNotificationStats: async (token = null) => fetchFromApi('/notifications/stats/summary', token),
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
  getDailyBriefingPreferences: async (token = null) => fetchFromApi('/notifications/daily-briefing-preferences', token, { noCache: true }),
  saveDailyBriefingPreferences: async (data, token = null) => fetchFromApi('/notifications/daily-briefing-preferences', token, { method: 'PUT', body: JSON.stringify(data) }),
  previewAlerts: async (targetDate = null, token = null) => {
    const params = targetDate ? `?target_date=${encodeURIComponent(targetDate)}` : '';
    return fetchFromApi(`/notifications/preview-alerts${params}`, token);
  },

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

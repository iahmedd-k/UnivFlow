const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';
const ROOT_URL = API_BASE.replace('/api/v1', '');

// In-memory client cache with TTL
const clientCache = new Map();
const CACHE_TTL_MS = 25000; // 25 seconds

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

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
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
        // Targeted cache invalidation: only clear related keys rather than wiping all data
        const endpointPrefix = endpoint.split('/')[1] || '';
        for (const [key] of clientCache) {
          if (endpointPrefix && (key.includes(endpointPrefix) || key.includes('dashboard'))) {
            clientCache.delete(key);
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

  // Dashboard
  getOverview: async (token = null) => {
    return fetchFromApi('/dashboard/overview', token);
  },

  getUpcoming: async (days = 7, token = null) => {
    return fetchFromApi(`/dashboard/upcoming?days=${days}`, token);
  },

  getAttendanceSummary: async (token = null) => {
    return fetchFromApi('/dashboard/attendance-summary', token);
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

  getTodaysClasses: async (token = null) => fetchFromApi('/timetable/today', token),

  parseTimetableImage: async (file, token = null) => {
    const form = new FormData();
    form.append('image', file);
    return fetchFromApi('/timetable/parse-image', token, { method: 'POST', body: form });
  },

  saveTimetableClasses: async (entries, token = null) => fetchFromApi('/timetable/classes', token, {
    method: 'POST', body: JSON.stringify(entries),
  }),

  deleteTimetableClass: async (id, token = null) => fetchFromApi(`/timetable/classes/${id}`, token, { method: 'DELETE' }),

  clearAllTimetableClasses: async (token = null) => fetchFromApi('/timetable/classes/all', token, { method: 'DELETE' }),

  getPortalSettings: async (token = null) => fetchFromApi('/portal/settings', token, { noCache: true }),

  savePortalUrl: async (url, token = null, options = {}) => fetchFromApi('/portal/settings', token, {
    method: 'PUT', body: JSON.stringify({ url, ...options }),
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

  getAssignment: async (id, token = null) => fetchFromApi(`/assignments/${id}`, token),

  // University
  getExams: async (token = null, since = null) => {
    return fetchFromApi(`/university/exams${since ? `?since=${encodeURIComponent(since)}` : ''}`, token);
  },

  getQuizzes: async (token = null, since = null) => {
    return fetchFromApi(`/university/quizzes${since ? `?since=${encodeURIComponent(since)}` : ''}`, token);
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
  getClassroomStudyMaterials: async (token = null) => fetchFromApi('/rag/materials?limit=12', token),
  generateStudyPlan: async (data, token = null) => fetchFromApi('/rag/study-plan', token, { method: 'POST', body: JSON.stringify(data) }),
  askCourseMaterials: async (data, token = null) => fetchFromApi('/rag/chat', token, { method: 'POST', body: JSON.stringify(data) }),

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

  // AI Tutor & Review Panels
  getAssignmentBreakdown: async (assignmentId, token = null) => fetchFromApi(`/assignments/${assignmentId}/breakdown`, token),

  askTutor: async (assignmentId, payload, token = null) => fetchFromApi(`/assignments/${assignmentId}/tutor`, token, {
    method: 'POST',
    body: JSON.stringify(payload),
  }),

  reviewDraft: async (assignmentId, { text, file } = {}, token = null) => {
    return fetchFromApi(`/assignments/${assignmentId}/review`, token, {
      method: 'POST',
      body: JSON.stringify({ text: text || (file ? file.name : '') }),
    });
  },

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

  openClaudeBrowser: async (token = null) => fetchFromApi('/classroom/claude-browser/open', token, {
    method: 'POST',
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
  previewAlerts: async (targetDate = null, token = null) => {
    const params = targetDate ? `?target_date=${encodeURIComponent(targetDate)}` : '';
    return fetchFromApi(`/notifications/preview-alerts${params}`, token);
  },
  getAgentRuns: async (limit = 20, token = null) => fetchFromApi(`/agent/runs?limit=${limit}`, token),
  getAgentRunStats: async (token = null) => fetchFromApi('/agent/stats/summary', token),
  getAgentRunEvents: async (runId, token = null) => fetchFromApi(`/agent/runs/${runId}/events`, token),

  // Code Execution
  executeCode: async (data, token = null) => fetchFromApi('/execution/execute', token, {
    method: 'POST',
    body: JSON.stringify(data),
  }),

  getExecutionLanguages: async (token = null) => fetchFromApi('/execution/languages', token),

  getExecutionHealth: async (token = null) => fetchFromApi('/execution/health', token),

  // Diagram Generation
  generateDiagram: async (data, token = null) => fetchFromApi('/diagram/generate', token, {
    method: 'POST',
    body: JSON.stringify(data),
  }),

  getDiagramTypes: async (token = null) => fetchFromApi('/diagram/types', token),

  getDiagramKinds: async (diagramType = 'mermaid', token = null) => fetchFromApi(`/diagram/kinds?diagram_type=${diagramType}`, token),

  getDiagramFormats: async (token = null) => fetchFromApi('/diagram/formats', token),

  getDiagramHealth: async (token = null) => fetchFromApi('/diagram/health', token),
};

'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import MarkdownRenderer from '../MarkdownRenderer';
import Icon from '@/app/dashboard/Icon';
import StudyAssistantPage from './StudyAssistantPage';

function LegacyCoursesPage() {
  const { getToken } = useAuth();
  const [courses, setCourses] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [selected, setSelected] = useState([]);
  const [selectedCourseFilter, setSelectedCourseFilter] = useState('all');
  const [selectedCategory, setSelectedCategory] = useState('all'); // 'all' | 'material' | 'assignment' | 'announcement'
  const [materialSearch, setMaterialSearch] = useState('');
  const [conversationSearch, setConversationSearch] = useState('');
  const [activeTab, setActiveTab] = useState('chat'); // 'chat' | 'materials' | 'conversations'
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncNotice, setSyncNotice] = useState('');
  const [error, setError] = useState('');
  const [conversations, setConversations] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const [scopeWarning, setScopeWarning] = useState(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef(null);

  const initializedSelection = useRef(false);
  const initializedConversation = useRef(false);
  const scrollRef = useRef(null);

  const loadMessages = async (conversationId, token) => {
    try {
      const rows = await api.getRagConversationMessages(conversationId, token);
      setMessages((rows || []).map((m) => ({ role: m.role === 'assistant' ? 'assistant' : 'you', text: m.content })));
      setActiveConversationId(conversationId);
      setActiveTab('chat');
    } catch (e) {
      setError(e.message || 'Could not load conversation history.');
    }
  };

  const load = useCallback(async () => {
    const token = await getToken();
    const [courseRows, materialRows, conversationRows] = await Promise.all([
      api.getCourses(token).catch(() => []),
      api.getClassroomStudyMaterials(token).catch(() => []),
      api.getRagConversations(token).catch(() => []),
    ]);

    setCourses(courseRows || []);
    setMaterials(materialRows || []);
    setConversations(conversationRows || []);

    if (!initializedSelection.current) {
      initializedSelection.current = true;
      // Pre-select top 6 most recent materials by default for immediate grounding
      const initialIds = (materialRows || []).slice(0, 6).map((item) => item.id);
      setSelected(initialIds);
    } else {
      setSelected((current) => current.filter((id) => (materialRows || []).some((item) => item.id === id)));
    }

    if (!initializedConversation.current) {
      initializedConversation.current = true;
      const latest = (conversationRows || [])[0] || null;
      setActiveConversationId(latest ? latest.id : null);
      if (latest) {
        loadMessages(latest.id, token);
      }
    }
  }, [getToken]);

  useEffect(() => {
    let active = true;
    const init = async () => {
      try {
        await load();
      } catch (e) {
        if (active) setError(e.message || 'Could not load course materials.');
      } finally {
        if (active) setLoading(false);
      }
    };
    init();
    return () => { active = false; };
  }, [load]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  // Sync materials directly from Google Classroom on-demand
  const handleSyncMaterials = async () => {
    setSyncing(true);
    setSyncNotice('');
    setError('');
    try {
      const token = await getToken();
      const res = await api.syncStudyMaterials(token);
      api.clearCache();
      await load();
      if (res && (res.status === 'reconnect_required' || res.scope_missing)) {
        setScopeWarning({
          message: res.message || 'Google Classroom needs to be reconnected to grant permission to sync course slides and handouts.',
          reconnectUrl: res.reconnect_url || '/api/v1/auth/google?redirect_to=/dashboard/courses',
        });
      } else if (res && res.status === 'success') {
        setSyncNotice(`Synced ${res.materials_synced || 0} materials across ${res.courses_synced || 0} courses from Google Classroom!`);
      } else {
        setSyncNotice('Materials updated from Google Classroom.');
      }
      setTimeout(() => setSyncNotice(''), 6000);
    } catch (err) {
      setError(err.message || 'Could not sync materials from Google Classroom.');
    } finally {
      setSyncing(false);
    }
  };

  // Upload lecture slides, PDFs, or handouts directly into the active course
  const handleUploadFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    let targetCourseId = selectedCourseFilter !== 'all' ? selectedCourseFilter : courses[0]?.id;
    if (!targetCourseId) {
      setError('Please select or wait for courses to load before uploading materials.');
      return;
    }

    setUploading(true);
    setError('');
    setSyncNotice('');
    try {
      const token = await getToken();
      const res = await api.uploadStudyMaterial(targetCourseId, file, token);
      if (res && res.material) {
        setSyncNotice(`Uploaded "${res.material.title}" successfully!`);
        setMaterials((prev) => [res.material, ...prev]);
        setSelected((prev) => Array.from(new Set([res.material.id, ...prev])));
        setTimeout(() => setSyncNotice(''), 6000);
      }
    } catch (err) {
      setError(err.message || 'Failed to upload document.');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // Filtered materials by course, category, and search query
  const filteredMaterials = useMemo(() => {
    return materials.filter((item) => {
      if (selectedCourseFilter !== 'all' && String(item.course_id) !== String(selectedCourseFilter)) {
        return false;
      }
      if (selectedCategory !== 'all' && item.category !== selectedCategory) {
        return false;
      }
      if (!materialSearch.trim()) return true;
      const q = materialSearch.toLowerCase().trim();
      const titleMatch = (item.title || '').toLowerCase().includes(q);
      const courseMatch = (item.course_name || '').toLowerCase().includes(q);
      const assignmentMatch = (item.assignment || '').toLowerCase().includes(q);
      return titleMatch || courseMatch || assignmentMatch;
    });
  }, [materials, selectedCourseFilter, selectedCategory, materialSearch]);

  // Category counts based on current course selection
  const categoryCounts = useMemo(() => {
    const base = selectedCourseFilter === 'all'
      ? materials
      : materials.filter((m) => String(m.course_id) === String(selectedCourseFilter));
    return {
      all: base.length,
      material: base.filter((m) => m.category === 'material').length,
      assignment: base.filter((m) => m.category === 'assignment').length,
      announcement: base.filter((m) => m.category === 'announcement').length,
    };
  }, [materials, selectedCourseFilter]);

  // Course item counts
  const courseCounts = useMemo(() => {
    const counts = {};
    materials.forEach((m) => {
      counts[m.course_id] = (counts[m.course_id] || 0) + 1;
    });
    return counts;
  }, [materials]);

  // Selected material objects
  const selectedItems = useMemo(() => {
    return materials.filter((m) => selected.includes(m.id));
  }, [materials, selected]);

  // Filtered conversations
  const filteredConversations = useMemo(() => {
    if (!conversationSearch.trim()) return conversations;
    const q = conversationSearch.toLowerCase().trim();
    return conversations.filter((c) => (c.title || '').toLowerCase().includes(q));
  }, [conversations, conversationSearch]);

  const toggleMaterial = (id) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]));
  };

  const selectAllFiltered = () => {
    const visibleIds = filteredMaterials.map((m) => m.id);
    setSelected((prev) => Array.from(new Set([...prev, ...visibleIds])));
  };

  const clearAllSelected = () => {
    setSelected([]);
  };

  const selectCurrentCourseOnly = (courseId) => {
    const courseIds = materials.filter((m) => String(m.course_id) === String(courseId)).map((m) => m.id);
    setSelected(courseIds);
  };

  // Immediate single-doc focus and prompt
  const focusAndAsk = (item, customPrompt = null) => {
    setSelected([item.id]);
    setActiveTab('chat');
    const p = customPrompt || `Explain the core concepts and key exam takeaways from "${item.title}".`;
    setQuestion(p);
  };

  const send = async (event) => {
    if (event) event.preventDefault();
    if (!question.trim()) return;
    const prompt = question.trim();
    setQuestion('');
    setError('');
    setBusy(true);

    const nextMessages = [...messages, { role: 'you', text: prompt }];
    setMessages(nextMessages);

    try {
      const token = await getToken();
      const result = await api.askCourseMaterials(
        {
          query: prompt,
          document_ids: selected,
          conversation_id: activeConversationId,
          history: nextMessages,
        },
        token
      );
      const conversationId = result.conversation_id;
      const assistant = { role: 'assistant', text: result.answer || 'No answer returned.' };
      setMessages([...nextMessages, assistant]);
      if (!conversations.find((c) => c.id === conversationId)) {
        setConversations((prev) => [{ id: conversationId, title: prompt.slice(0, 60), source: 'rag' }, ...prev]);
        setActiveConversationId(conversationId);
      }
    } catch (e) {
      setError(e.message || 'Could not answer from the selected materials.');
      setMessages((m) => m.slice(0, -1));
      setQuestion(prompt);
    } finally {
      setBusy(false);
    }
  };

  const startNewConversation = () => {
    setActiveConversationId(null);
    setMessages([]);
    setQuestion('');
    setError('');
    setActiveTab('chat');
  };

  const getFileBadge = (item) => {
    const cat = item.category;
    if (cat === 'announcement') {
      return <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-[#eff8ff] text-[#175cd3] border border-[#b2ddff]">NOTICE</span>;
    }
    const fileType = item.file_type || '';
    if (fileType === 'pdf') {
      return <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-[#fdeded] text-[#b42318] border border-[#fecdca]">PDF</span>;
    }
    if (fileType === 'slide') {
      return <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-[#fff8eb] text-[#b54708] border border-[#fedf89]">SLIDE</span>;
    }
    if (fileType === 'doc') {
      return <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-[#f0f9ff] text-[#026aa2] border border-[#b9e6fe]">DOC</span>;
    }
    if (fileType === 'sheet') {
      return <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-[#ecfdf3] text-[#027a48] border border-[#a6f4c5]">SHEET</span>;
    }
    if (fileType === 'code') {
      return <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-[#f4f3ff] text-[#5925dc] border border-[#d9d6fe]">CODE</span>;
    }
    if (cat === 'assignment') {
      return <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-[#fef6ee] text-[#b93815] border border-[#f9dbaf]">LAB/TASK</span>;
    }
    return <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-[#f2f4f7] text-[#344054] border border-[#eaecf0]">MATERIAL</span>;
  };

  const secondaryButtonClass = 'inline-flex min-h-9 items-center justify-center rounded-lg border border-line bg-white px-3 text-sm font-semibold text-ink transition hover:bg-paper disabled:cursor-not-allowed disabled:opacity-50';
  const buttonClass = 'inline-flex min-h-10 items-center justify-center rounded-lg bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-50';
  const inputClass = 'min-w-0 flex-1 rounded-lg border border-line bg-white px-3 py-2.5 text-sm text-ink outline-none placeholder:text-muted focus:border-violet focus:ring-2 focus:ring-violet/20';

  return (
    <div className="flex flex-1 min-h-0 w-full flex-col gap-2 overflow-hidden text-ink">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between pb-1 shrink-0">
        <div>
          <div className="flex items-center gap-2 mb-0.5">
            <span className="inline-block text-[11px] font-bold uppercase tracking-wider text-muted">Study Workspace</span>
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-violet-light text-violet-dark border border-violet/20">
              <span className="size-1.5 rounded-full bg-violet" />
              GCR Grounded
            </span>
          </div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-ink">Study & Exam Assistant</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleUploadFile}
            accept=".pdf,.pptx,.ppt,.docx,.doc,.txt,.md,.py,.cpp,.c"
            className="hidden"
          />
          <button
            type="button"
            className="inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-line bg-white px-2.5 text-xs font-semibold text-ink transition hover:border-violet hover:bg-violet-light/30 disabled:opacity-50"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            title="Upload lecture slides, PPTX, PDF, or course notes"
          >
            <span>{uploading ? '⏳' : '📁'}</span>
            {uploading ? 'Uploading…' : 'Upload Slides / Docs'}
          </button>
          <button
            type="button"
            className="inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-line bg-white px-2.5 text-xs font-semibold text-ink transition hover:border-violet hover:bg-violet-light/30 disabled:opacity-50"
            onClick={handleSyncMaterials}
            disabled={syncing}
            title="Fetch all course materials, lecture slides, and announcements from Google Classroom"
          >
            <span className={syncing ? 'animate-spin' : ''}>🔄</span>
            {syncing ? 'Syncing…' : 'Sync Classroom'}
          </button>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-violet-light px-2.5 py-1 text-xs font-semibold text-violet-dark border border-violet/20">
            <span className="h-1.5 w-1.5 rounded-full bg-violet" />
            {selected.length} of {materials.length} attached
          </span>
          <button type="button" className={secondaryButtonClass} onClick={startNewConversation}>
            + New chat
          </button>
          <button
            type="button"
            className="lg:hidden inline-flex min-h-8 items-center justify-center rounded-lg border border-line bg-paper px-2.5 text-xs font-semibold text-ink"
            onClick={() => setSidebarOpen(!sidebarOpen)}
          >
            {sidebarOpen ? 'Hide Files' : 'Files & Chats'}
          </button>
        </div>
      </header>

      {/* Google Classroom Scopes Missing Warning Banner */}
      {scopeWarning && (
        <div className="my-1 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2.5 rounded-lg border border-amber-300 bg-amber-50 px-3.5 py-2 text-xs text-amber-900 shadow-xs shrink-0" role="alert">
          <div className="flex items-start gap-2">
            <span className="text-base leading-none">⚠️</span>
            <div>
              <p className="font-bold text-amber-950">Google Classroom Permission Needed for Course Slides</p>
              <p className="mt-0.5 text-amber-800">{scopeWarning.message}</p>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0 w-full sm:w-auto justify-end">
            <a
              href={scopeWarning.reconnectUrl}
              className="inline-flex items-center justify-center px-3 py-1 rounded-md bg-amber-600 hover:bg-amber-700 text-white font-semibold text-xs transition shadow-xs"
            >
              Authorize Slides Access →
            </a>
            <button
              type="button"
              onClick={() => setScopeWarning(null)}
              className="text-amber-700 hover:text-amber-900 font-bold px-1.5 py-0.5 text-sm"
              title="Dismiss warning"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Sync Success or Error Notifications */}
      {syncNotice && (
        <div className="my-1 rounded-lg border border-emerald-200 bg-emerald-50 px-3.5 py-2 text-xs font-medium text-emerald-800 transition flex items-center justify-between shrink-0" role="status">
          <span>✨ {syncNotice}</span>
          <button type="button" onClick={() => setSyncNotice('')} className="text-emerald-700 hover:text-emerald-900 font-bold ml-2">×</button>
        </div>
      )}
      {error && (
        <div className="my-1 rounded-lg border border-rose-border bg-rose-bg px-3.5 py-2 text-xs text-rose shrink-0" role="alert">
          {error}
        </div>
      )}

      {/* Mobile/Tablet tab switcher */}
      <div className="lg:hidden flex border-b border-line bg-paper px-2 pt-1 shrink-0">
        <button
          type="button"
          onClick={() => setActiveTab('chat')}
          className={`flex-1 py-1.5 text-xs font-semibold text-center border-b-2 ${activeTab === 'chat' ? 'border-violet text-violet' : 'border-transparent text-muted'}`}
        >
          💬 Chat
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('materials')}
          className={`flex-1 py-1.5 text-xs font-semibold text-center border-b-2 ${activeTab === 'materials' ? 'border-violet text-violet' : 'border-transparent text-muted'}`}
        >
          📚 Course Files ({selected.length})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('conversations')}
          className={`flex-1 py-1.5 text-xs font-semibold text-center border-b-2 ${activeTab === 'conversations' ? 'border-violet text-violet' : 'border-transparent text-muted'}`}
        >
          🕘 History
        </button>
      </div>

      <div className="flex flex-1 min-h-0 border border-line bg-white shadow-sm rounded-xl overflow-hidden">
        {/* Left Sidebar: Course Selector, Category Filter & Document List */}
        {(sidebarOpen || activeTab !== 'chat') && (
          <aside className={`${activeTab === 'chat' ? 'hidden lg:flex' : 'flex'} flex-col w-full lg:w-[380px] xl:w-[410px] border-r border-line bg-[#fcfcfd] shrink-0 h-full overflow-hidden`}>
            {/* Source Materials Section */}
            <section className={`flex flex-col flex-1 min-h-0 p-3 overflow-hidden ${activeTab === 'conversations' ? 'hidden lg:flex' : 'flex'}`}>
              {/* Header with Selection Controls */}
              <div className="flex items-center justify-between pb-2 shrink-0">
                <div className="flex items-center gap-1.5">
                  <span className="font-semibold text-xs uppercase tracking-wide text-ink">GCR Materials</span>
                  <span className="text-[11px] font-semibold text-violet bg-violet-light px-2 py-0.5 rounded-full">
                    {filteredMaterials.length}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button type="button" className="text-[11px] font-semibold text-violet hover:underline" onClick={selectAllFiltered}>
                    Select all visible
                  </button>
                  <span className="text-line text-xs">|</span>
                  <button type="button" className="text-[11px] font-semibold text-muted hover:underline" onClick={clearAllSelected}>
                    Clear
                  </button>
                </div>
              </div>

              {/* Course Horizontal Selection Pills */}
              <div className="mb-2 shrink-0">
                <label className="block text-[10px] font-bold uppercase tracking-wider text-muted mb-1">
                  Courses ({courses.length})
                </label>
                <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-thin">
                  <button
                    type="button"
                    onClick={() => setSelectedCourseFilter('all')}
                    className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold transition select-none ${
                      selectedCourseFilter === 'all'
                        ? 'bg-violet text-white shadow-xs'
                        : 'bg-white border border-line text-ink hover:bg-paper'
                    }`}
                  >
                    All Courses ({materials.length})
                  </button>
                  {courses.map((c) => {
                    const count = courseCounts[c.id] || 0;
                    const isSelected = String(selectedCourseFilter) === String(c.id);
                    return (
                      <button
                        key={c.id}
                        type="button"
                        onClick={() => setSelectedCourseFilter(String(c.id))}
                        className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-medium transition select-none flex items-center gap-1 ${
                          isSelected
                            ? 'bg-violet text-white font-semibold shadow-xs'
                            : 'bg-white border border-line text-ink hover:bg-paper'
                        }`}
                        title={c.name}
                      >
                        <span className="max-w-[130px] truncate">{c.name}</span>
                        {count > 0 && (
                          <span className={`text-[10px] px-1 rounded-full ${isSelected ? 'bg-white/20 text-white' : 'bg-paper text-muted'}`}>
                            {count}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Material Category Filter Tabs */}
              <div className="mb-2 grid grid-cols-4 gap-1 rounded-lg border border-line bg-paper p-1 text-[11px] shrink-0">
                <button
                  type="button"
                  onClick={() => setSelectedCategory('all')}
                  className={`rounded-md py-1 font-semibold text-center transition ${
                    selectedCategory === 'all' ? 'bg-white text-ink shadow-xs' : 'text-muted hover:text-ink'
                  }`}
                >
                  All ({categoryCounts.all})
                </button>
                <button
                  type="button"
                  onClick={() => setSelectedCategory('material')}
                  className={`rounded-md py-1 font-semibold text-center transition flex items-center justify-center gap-1 ${
                    selectedCategory === 'material' ? 'bg-white text-ink shadow-xs' : 'text-muted hover:text-ink'
                  }`}
                  title="Lecture Slides, Handouts, PDFs, Syllabi"
                >
                  <span>📚 Slides</span>
                  <span className="text-[10px] opacity-75">({categoryCounts.material})</span>
                </button>
                <button
                  type="button"
                  onClick={() => setSelectedCategory('assignment')}
                  className={`rounded-md py-1 font-semibold text-center transition flex items-center justify-center gap-1 ${
                    selectedCategory === 'assignment' ? 'bg-white text-ink shadow-xs' : 'text-muted hover:text-ink'
                  }`}
                  title="Lab Manuals, Problem Sets, Quizzes, Tasks"
                >
                  <span>🧪 Labs</span>
                  <span className="text-[10px] opacity-75">({categoryCounts.assignment})</span>
                </button>
                <button
                  type="button"
                  onClick={() => setSelectedCategory('announcement')}
                  className={`rounded-md py-1 font-semibold text-center transition flex items-center justify-center gap-1 ${
                    selectedCategory === 'announcement' ? 'bg-white text-ink shadow-xs' : 'text-muted hover:text-ink'
                  }`}
                  title="Course Announcements, Notes & Guidelines"
                >
                  <span>📢 Notes</span>
                  <span className="text-[10px] opacity-75">({categoryCounts.announcement})</span>
                </button>
              </div>

              {/* Material Search Input */}
              <div className="relative mb-2 shrink-0">
                <input
                  type="text"
                  value={materialSearch}
                  onChange={(e) => setMaterialSearch(e.target.value)}
                  placeholder="Search slides, lab tasks, PDFs, topics…"
                  className="w-full rounded-md border border-line bg-white pl-8 pr-3 py-1.5 text-xs text-ink outline-none placeholder:text-muted focus:border-violet"
                />
                <span className="absolute left-2.5 top-2 text-muted pointer-events-none">
                  <Icon name="search" size={13} />
                </span>
                {materialSearch && (
                  <button
                    type="button"
                    onClick={() => setMaterialSearch('')}
                    className="absolute right-2.5 top-1.5 text-xs text-muted hover:text-ink font-bold"
                  >
                    ×
                  </button>
                )}
              </div>

              {/* Materials Scrollable List */}
              <div className="flex-1 min-h-0 overflow-y-auto divide-y divide-line rounded-lg border border-line bg-white shadow-inner">
                {loading ? (
                  <div className="p-8 text-center text-xs text-muted">Loading Classroom files…</div>
                ) : filteredMaterials.length ? (
                  filteredMaterials.map((item) => {
                    const isChecked = selected.includes(item.id);
                    return (
                      <div
                        key={item.id}
                        className={`group flex items-start gap-2.5 px-3 py-2.5 transition cursor-pointer select-none ${
                          isChecked ? 'bg-[#f7f6ff]' : 'hover:bg-paper'
                        }`}
                        onClick={() => toggleMaterial(item.id)}
                      >
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => {}} // handled by parent onClick
                          className="mt-0.5 size-4 accent-violet shrink-0 cursor-pointer"
                        />
                        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                          <div className="flex items-center gap-1.5">
                            {getFileBadge(item)}
                            <span className="text-xs font-medium text-ink line-clamp-1 group-hover:text-violet">
                              {item.title || 'Untitled material'}
                            </span>
                          </div>
                          <div className="flex items-center justify-between text-[11px] text-muted">
                            <span className="line-clamp-1 font-sans">{item.course_name || 'Course file'}</span>
                            <div className="flex items-center gap-1.5 shrink-0 ml-1">
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  focusAndAsk(item);
                                }}
                                className="text-[10px] font-semibold text-violet bg-violet-light/60 px-1.5 py-0.5 rounded hover:bg-violet hover:text-white transition"
                                title="Select this document and ask a question"
                              >
                                ⚡ Ask this
                              </button>
                              {item.url && (
                                <a
                                  href={item.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  onClick={(e) => e.stopPropagation()}
                                  className="text-muted hover:text-ink text-[10px]"
                                  title="Open in Classroom / Drive"
                                >
                                  ↗
                                </a>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })
                ) : (
                  <div className="p-8 text-center text-xs text-muted flex flex-col items-center gap-2">
                    <span className="text-2xl">📚</span>
                    <p className="font-medium text-ink">
                      {selectedCategory === 'material' ? 'No slides or handouts found' : 'No documents found for this filter'}
                    </p>
                    <p className="text-[11px] text-muted max-w-[240px]">
                      {selectedCategory === 'material'
                        ? 'Upload your lecture slide decks directly, or reconnect Classroom to grant slide permissions.'
                        : 'Upload course files or sync directly with Google Classroom.'}
                    </p>
                    <div className="mt-2 flex flex-col sm:flex-row items-center gap-2">
                      <button
                        type="button"
                        onClick={() => fileInputRef.current?.click()}
                        disabled={uploading}
                        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md bg-violet text-white text-xs font-semibold hover:bg-violet-dark transition"
                      >
                        📁 Upload Slides / PDF
                      </button>
                      <button
                        type="button"
                        onClick={handleSyncMaterials}
                        disabled={syncing}
                        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md border border-line bg-white text-xs font-semibold text-ink hover:bg-paper transition"
                      >
                        🔄 {syncing ? 'Syncing…' : 'Sync Classroom'}
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {/* Quick Course Selector action bar */}
              {selectedCourseFilter !== 'all' && (
                <div className="mt-1.5 flex items-center justify-between px-1 text-[11px] shrink-0">
                  <span className="text-muted">Filtering current course</span>
                  <button
                    type="button"
                    className="font-semibold text-violet hover:underline"
                    onClick={() => selectCurrentCourseOnly(selectedCourseFilter)}
                  >
                    Select all for this course
                  </button>
                </div>
              )}
            </section>

            {/* Conversations History Section */}
            <section className={`flex flex-col border-t border-line p-3 shrink-0 max-h-[160px] overflow-hidden ${activeTab === 'materials' ? 'hidden lg:flex' : 'flex'}`}>
              <div className="flex items-center justify-between pb-1.5 shrink-0">
                <span className="font-semibold text-xs uppercase tracking-wide text-muted">Recent Sessions</span>
                <button
                  type="button"
                  className="text-[11px] font-semibold text-violet hover:underline"
                  onClick={startNewConversation}
                >
                  + New chat
                </button>
              </div>

              {conversations.length > 3 && (
                <div className="relative mb-1.5 shrink-0">
                  <input
                    type="text"
                    value={conversationSearch}
                    onChange={(e) => setConversationSearch(e.target.value)}
                    placeholder="Search previous chats…"
                    className="w-full rounded-md border border-line bg-white pl-7 pr-2 py-1 text-xs text-ink outline-none placeholder:text-muted focus:border-violet"
                  />
                  <span className="absolute left-2 top-1.5 text-muted pointer-events-none">
                    <Icon name="search" size={12} />
                  </span>
                </div>
              )}

              <div className="flex-1 min-h-0 overflow-y-auto divide-y divide-line rounded-lg border border-line bg-white">
                {filteredConversations.length ? (
                  filteredConversations.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      onClick={async () => {
                        const token = await getToken();
                        await loadMessages(c.id, token);
                      }}
                      className={`flex w-full items-center justify-between px-3 py-2 text-left text-xs transition ${
                        activeConversationId === c.id ? 'bg-violet-light font-semibold text-violet-dark' : 'hover:bg-paper text-ink'
                      }`}
                    >
                      <span className="line-clamp-1">{c.title || 'Study Session'}</span>
                      <span className="text-[10px] text-muted shrink-0 ml-2">
                        {c.source === 'tutor' ? 'Tutor' : 'Study'}
                      </span>
                    </button>
                  ))
                ) : (
                  <div className="p-3 text-center text-xs text-muted">No conversations yet</div>
                )}
              </div>
            </section>
          </aside>
        )}

        {/* Main Chat Workspace */}
        <section className={`flex min-w-0 flex-1 flex-col h-full overflow-hidden ${activeTab !== 'chat' ? 'hidden lg:flex' : 'flex'}`}>
          <header className="flex items-center justify-between gap-3 border-b border-line bg-white px-4 py-2.5 shrink-0">
            <div className="flex items-center gap-3">
              <span className="grid size-8 place-items-center rounded-lg bg-violet-light text-violet">
                <Icon name="lightbulb" size={16} />
              </span>
              <div>
                <strong className="block text-sm font-semibold text-ink">
                  {activeConversationId ? 'GCR Study & Exam Assistant' : 'New Academic Conversation'}
                </strong>
                <small className="text-xs text-muted">
                  {selected.length
                    ? `Grounded in ${selected.length} attached course document${selected.length > 1 ? 's' : ''}`
                    : 'Ask anything across your courses, topics, exams, or syllabus'}
                </small>
              </div>
            </div>
            {selected.length > 0 && (
              <div className="hidden sm:flex items-center gap-2">
                <span className="text-xs text-muted">
                  Attached: <strong className="text-violet-dark font-medium">{selected.length} files</strong>
                </span>
                <button
                  type="button"
                  onClick={clearAllSelected}
                  className="text-[11px] text-muted hover:text-ink underline"
                >
                  Detach all
                </button>
              </div>
            )}
          </header>

          {/* Focused Document Action Bar (when 1 or more documents are actively selected) */}
          {selectedItems.length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-violet/20 bg-gradient-to-r from-violet-light/60 to-purple-50/40 px-4 py-2 text-xs shrink-0">
              <div className="flex items-center gap-2 min-w-0">
                <span className="font-semibold text-violet-dark shrink-0">
                  {selectedItems.length === 1 ? '📄 Focused Document:' : `📚 ${selectedItems.length} Documents Selected:`}
                </span>
                <span className="font-medium text-ink truncate max-w-[240px] sm:max-w-[340px]">
                  {selectedItems.length === 1 ? selectedItems[0].title : selectedItems.map((m) => m.title).slice(0, 2).join(', ') + (selectedItems.length > 2 ? ` (+${selectedItems.length - 2} more)` : '')}
                </span>
                {selectedItems.length === 1 && (
                  <span className="hidden md:inline-block text-[10px] bg-white border border-line px-1.5 py-0.5 rounded text-muted truncate max-w-[150px]">
                    {selectedItems[0].course_name}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1.5 overflow-x-auto shrink-0">
                {selectedItems.length === 1 ? (
                  <>
                    <button
                      type="button"
                      onClick={() => {
                        setQuestion(`Summarize "${selectedItems[0].title}" into high-yield exam revision notes with key formulas and concepts.`);
                      }}
                      className="rounded bg-white px-2 py-1 text-[11px] font-medium text-violet border border-line shadow-xs hover:bg-violet-light transition"
                    >
                      📌 Summarize doc
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setQuestion(`What are the core concepts, definitions, and likely exam questions from "${selectedItems[0].title}"?`);
                      }}
                      className="rounded bg-white px-2 py-1 text-[11px] font-medium text-violet border border-line shadow-xs hover:bg-violet-light transition"
                    >
                      💡 Key concepts
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setQuestion(`Generate 5 practice exam questions with detailed step-by-step solutions based on "${selectedItems[0].title}".`);
                      }}
                      className="rounded bg-white px-2 py-1 text-[11px] font-medium text-violet border border-line shadow-xs hover:bg-violet-light transition"
                    >
                      🎯 5 Practice questions
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => {
                        setQuestion(`Prepare a comprehensive exam revision guide combining all key topics from my ${selectedItems.length} selected course materials.`);
                      }}
                      className="rounded bg-white px-2 py-1 text-[11px] font-medium text-violet border border-line shadow-xs hover:bg-violet-light transition"
                    >
                      📝 Unified exam guide
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setQuestion(`Generate a 10-question practice exam quiz covering all ${selectedItems.length} selected materials with complete answers.`);
                      }}
                      className="rounded bg-white px-2 py-1 text-[11px] font-medium text-violet border border-line shadow-xs hover:bg-violet-light transition"
                    >
                      🎯 10-Question mock exam
                    </button>
                  </>
                )}
              </div>
            </div>
          )}

          {/* Messages Scroll Area */}
          <div ref={scrollRef} className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-5 bg-[#fafafd]">
            {loading ? (
              <div className="m-auto py-10 text-center text-sm text-muted" role="status">
                Loading study assistant & course materials…
              </div>
            ) : messages.length ? (
              messages.map((message, index) => (
                <article key={index} className={`flex gap-3 ${message.role === 'you' ? 'justify-end' : 'justify-start'}`}>
                  {message.role !== 'you' && (
                    <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-violet-light text-xs font-bold text-violet">
                      AI
                    </span>
                  )}
                  <div
                    className={`max-w-[88%] rounded-xl px-4 py-3 text-sm leading-6 shadow-sm ${
                      message.role === 'you' ? 'bg-violet text-white' : 'border border-line bg-white text-ink'
                    }`}
                  >
                    {message.role === 'you' ? (
                      <p className="whitespace-pre-wrap">{message.text}</p>
                    ) : (
                      <MarkdownRenderer content={message.text} />
                    )}
                  </div>
                </article>
              ))
            ) : (
              <div className="m-auto w-full max-w-lg py-8 text-center">
                <span className="mx-auto mb-4 grid size-16 place-items-center rounded-2xl bg-violet-light text-violet shadow-sm">
                  <Icon name="messageCircle" size={28} />
                </span>
                <strong className="block text-base font-semibold text-ink">University Coursework & Exam Assistant</strong>
                <p className="mx-auto mt-2 max-w-md text-xs sm:text-sm leading-6 text-muted">
                  {selected.length
                    ? `Ready to generate high-yield exam summaries, solve questions, explain lecture topics, or generate quizzes from ${selected.length} selected document${selected.length > 1 ? 's' : ''}.`
                    : 'Select course lecture slides, lab manuals, or PDFs from the left panel, or ask general questions across your courses.'}
                </p>
                <div className="mt-5 flex flex-wrap justify-center gap-2">
                  <button
                    type="button"
                    onClick={() => setQuestion('Prepare a comprehensive exam revision guide and key formulas from my selected course materials.')}
                    className="rounded-lg border border-line bg-white px-3 py-1.5 text-xs font-semibold text-ink shadow-sm transition hover:border-violet/40 hover:bg-violet-light/30"
                  >
                    📝 Exam revision sheet
                  </button>
                  <button
                    type="button"
                    onClick={() => setQuestion('Explain the core concepts and common exam questions from this course step by step.')}
                    className="rounded-lg border border-line bg-white px-3 py-1.5 text-xs font-semibold text-ink shadow-sm transition hover:border-violet/40 hover:bg-violet-light/30"
                  >
                    💡 Explain key topics
                  </button>
                  <button
                    type="button"
                    onClick={() => setQuestion('Generate a 5-question practice quiz with detailed step-by-step explanations.')}
                    className="rounded-lg border border-line bg-white px-3 py-1.5 text-xs font-semibold text-ink shadow-sm transition hover:border-violet/40 hover:bg-violet-light/30"
                  >
                    🎯 Practice quiz
                  </button>
                </div>
              </div>
            )}
            {busy && (
              <div className="flex items-center gap-2 text-xs sm:text-sm text-muted" role="status">
                <span className="size-4 animate-spin rounded-full border-2 border-violet-light border-t-violet" />
                Study assistant is analyzing materials and formulating answer…
              </div>
            )}
          </div>

          {/* Bottom Chat Prompt Form */}
          <form className="flex gap-2 border-t border-line bg-white p-3 shrink-0" onSubmit={send}>
            <input
              className={inputClass}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={
                selected.length
                  ? `Ask about ${selected.length} selected file${selected.length > 1 ? 's' : ''} (e.g. summarize Lecture 2, explain SIMD divergence)…`
                  : 'Ask about any course topic, formula, or exam question…'
              }
              aria-label="Ask study assistant"
            />
            <button
              type="submit"
              className={buttonClass}
              disabled={busy || !question.trim()}
            >
              {busy ? 'Working…' : 'Ask'}
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}

export default function CoursesPage(props) {
  const Page = props?.legacy ? LegacyCoursesPage : StudyAssistantPage;
  return <Page />;
}

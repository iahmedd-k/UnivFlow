'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import MarkdownRenderer from '../MarkdownRenderer';
import Icon from '@/app/dashboard/Icon';

export default function CoursesPage() {
  const { getToken } = useAuth();
  const [courses, setCourses] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [selected, setSelected] = useState([]);
  const [selectedCourseFilter, setSelectedCourseFilter] = useState('all');
  const [materialSearch, setMaterialSearch] = useState('');
  const [conversationSearch, setConversationSearch] = useState('');
  const [activeTab, setActiveTab] = useState('chat'); // 'chat' | 'materials' | 'conversations'
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [conversations, setConversations] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);

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
      // Pre-select top 8 most recent materials by default for immediate grounding
      const initialIds = (materialRows || []).slice(0, 8).map((item) => item.id);
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
    load()
      .catch((e) => setError(e.message || 'Could not load course materials.'))
      .finally(() => setLoading(false));
  }, [load]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  // Filtered materials by course and search query
  const filteredMaterials = useMemo(() => {
    return materials.filter((item) => {
      if (selectedCourseFilter !== 'all' && String(item.course_id) !== String(selectedCourseFilter)) {
        return false;
      }
      if (!materialSearch.trim()) return true;
      const q = materialSearch.toLowerCase().trim();
      const titleMatch = (item.title || '').toLowerCase().includes(q);
      const courseMatch = (item.course_name || '').toLowerCase().includes(q);
      const assignmentMatch = (item.assignment || '').toLowerCase().includes(q);
      return titleMatch || courseMatch || assignmentMatch;
    });
  }, [materials, selectedCourseFilter, materialSearch]);

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

  const send = async (event) => {
    event.preventDefault();
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
    const mime = (item.mime_type || '').toLowerCase();
    const title = (item.title || '').toLowerCase();
    if (mime.includes('pdf') || title.endsWith('.pdf')) {
      return <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-[#fdeded] text-[#b42318] border border-[#fecdca]">PDF</span>;
    }
    if (mime.includes('presentation') || title.endsWith('.ppt') || title.endsWith('.pptx')) {
      return <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-[#fff8eb] text-[#b54708] border border-[#fedf89]">SLIDE</span>;
    }
    if (mime.includes('document') || title.endsWith('.doc') || title.endsWith('.docx')) {
      return <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-[#f0f9ff] text-[#026aa2] border border-[#b9e6fe]">DOC</span>;
    }
    if (mime.includes('sheet') || title.endsWith('.xls') || title.endsWith('.xlsx') || title.endsWith('.csv')) {
      return <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-[#ecfdf3] text-[#027a48] border border-[#a6f4c5]">SHEET</span>;
    }
    if (mime.startsWith('text/') || title.endsWith('.py') || title.endsWith('.c') || title.endsWith('.cpp') || title.endsWith('.java') || title.endsWith('.txt')) {
      return <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-[#f4f3ff] text-[#5925dc] border border-[#d9d6fe]">CODE</span>;
    }
    return <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-[#f2f4f7] text-[#344054] border border-[#eaecf0]">FILE</span>;
  };

  const secondaryButtonClass = 'inline-flex min-h-9 items-center justify-center rounded-lg border border-line bg-white px-3 text-sm font-semibold text-ink transition hover:bg-paper disabled:cursor-not-allowed disabled:opacity-50';
  const buttonClass = 'inline-flex min-h-10 items-center justify-center rounded-lg bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-50';
  const inputClass = 'min-w-0 flex-1 rounded-lg border border-line bg-white px-3 py-2.5 text-sm text-ink outline-none placeholder:text-muted focus:border-violet focus:ring-2 focus:ring-violet/20';

  return (
    <main className="mx-auto flex w-full max-w-[1400px] flex-col gap-0 pb-10 text-ink">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between border-b border-line pb-5">
        <div>
          <p className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Study Workspace</p>
          <h1 className="text-2xl font-semibold tracking-tight">Study & Exam Assistant</h1>
          <p className="mt-1 max-w-2xl text-xs sm:text-sm text-muted">
            Search, select, and ask questions across all Google Classroom lecture slides, lab manuals, PDFs, and assignments.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-violet-light px-3 py-1.5 text-xs font-semibold text-violet-dark border border-violet/20">
            <span className="h-2 w-2 rounded-full bg-violet" />
            {selected.length} of {materials.length} files attached
          </span>
          <button type="button" className={secondaryButtonClass} onClick={startNewConversation}>
            + New chat
          </button>
          <button
            type="button"
            className="lg:hidden inline-flex min-h-9 items-center justify-center rounded-lg border border-line bg-paper px-3 text-xs font-semibold text-ink"
            onClick={() => setSidebarOpen(!sidebarOpen)}
          >
            {sidebarOpen ? 'Hide Panel' : 'Show Files & Chats'}
          </button>
        </div>
      </header>

      {/* Mobile/Tablet tab switcher when sidebar is visible */}
      <div className="lg:hidden flex border-b border-line bg-paper px-2 pt-2">
        <button
          type="button"
          onClick={() => setActiveTab('chat')}
          className={`flex-1 py-2 text-xs font-semibold text-center border-b-2 ${activeTab === 'chat' ? 'border-violet text-violet' : 'border-transparent text-muted'}`}
        >
          💬 Chat
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('materials')}
          className={`flex-1 py-2 text-xs font-semibold text-center border-b-2 ${activeTab === 'materials' ? 'border-violet text-violet' : 'border-transparent text-muted'}`}
        >
          📚 Course Files ({selected.length})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('conversations')}
          className={`flex-1 py-2 text-xs font-semibold text-center border-b-2 ${activeTab === 'conversations' ? 'border-violet text-violet' : 'border-transparent text-muted'}`}
        >
          🕘 History
        </button>
      </div>

      {error && (
        <div className="my-3 rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-xs text-rose" role="alert">
          {error}
        </div>
      )}

      <div className="flex min-h-[720px] flex-1 border border-t-0 border-line bg-white shadow-sm rounded-b-xl overflow-hidden">
        {/* Left Sidebar: Materials Selector + Chat History */}
        {(sidebarOpen || activeTab !== 'chat') && (
          <aside className={`${activeTab === 'chat' ? 'hidden lg:flex' : 'flex'} flex-col w-full lg:w-[380px] xl:w-[420px] border-r border-line bg-[#fcfcfd] shrink-0`}>
            {/* Source Materials Section */}
            <section className={`flex flex-col flex-1 p-4 overflow-hidden ${activeTab === 'conversations' ? 'hidden lg:flex' : 'flex'}`}>
              <div className="flex items-center justify-between pb-2">
                <div className="flex items-center gap-1.5">
                  <span className="font-semibold text-xs uppercase tracking-wide text-ink">GCR Course Documents</span>
                  <span className="text-[11px] font-semibold text-violet bg-violet-light px-1.5 py-0.5 rounded-full">
                    {filteredMaterials.length}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button type="button" className="text-[11px] font-semibold text-violet hover:underline" onClick={selectAllFiltered}>
                    Select visible
                  </button>
                  <span className="text-line text-xs">|</span>
                  <button type="button" className="text-[11px] font-semibold text-muted hover:underline" onClick={clearAllSelected}>
                    Clear
                  </button>
                </div>
              </div>

              {/* Course Filter Dropdown */}
              <div className="mb-2">
                <select
                  value={selectedCourseFilter}
                  onChange={(e) => setSelectedCourseFilter(e.target.value)}
                  className="w-full rounded-md border border-line bg-white px-2.5 py-1.5 text-xs text-ink outline-none focus:border-violet"
                >
                  <option value="all">All Courses ({materials.length} files)</option>
                  {courses.map((c) => {
                    const count = materials.filter((m) => String(m.course_id) === String(c.id)).length;
                    return (
                      <option key={c.id} value={c.id}>
                        {c.name} {count ? `(${count})` : ''}
                      </option>
                    );
                  })}
                </select>
              </div>

              {/* Material Search Input */}
              <div className="relative mb-2.5">
                <input
                  type="text"
                  value={materialSearch}
                  onChange={(e) => setMaterialSearch(e.target.value)}
                  placeholder="Search slides, lab tasks, PDFs, topics…"
                  className="w-full rounded-md border border-line bg-white pl-8 pr-3 py-1.5 text-xs text-ink outline-none placeholder:text-muted focus:border-violet"
                />
                <span className="absolute left-2.5 top-2 text-muted pointer-events-none">
                  <Icon name="search" size={14} />
                </span>
                {materialSearch && (
                  <button
                    type="button"
                    onClick={() => setMaterialSearch('')}
                    className="absolute right-2.5 top-2 text-xs text-muted hover:text-ink"
                  >
                    ×
                  </button>
                )}
              </div>

              {/* Materials Scrollable List */}
              <div className="flex-1 min-h-[220px] max-h-[360px] lg:max-h-[380px] overflow-y-auto divide-y divide-line rounded-lg border border-line bg-white shadow-inner">
                {loading ? (
                  <div className="p-6 text-center text-xs text-muted">Loading Classroom files…</div>
                ) : filteredMaterials.length ? (
                  filteredMaterials.map((item) => {
                    const isChecked = selected.includes(item.id);
                    return (
                      <div
                        key={item.id}
                        className={`group flex items-start gap-2.5 px-3 py-2.5 transition cursor-pointer select-none ${
                          isChecked ? 'bg-[#f8f7ff]' : 'hover:bg-paper'
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
                            {item.url && (
                              <a
                                href={item.url}
                                target="_blank"
                                rel="noreferrer"
                                onClick={(e) => e.stopPropagation()}
                                className="text-violet hover:underline shrink-0 text-[10px] ml-1"
                                title="Open in Classroom / Drive"
                              >
                                View ↗
                              </a>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })
                ) : (
                  <div className="p-6 text-center text-xs text-muted">
                    No files found matching &quot;{materialSearch}&quot;
                  </div>
                )}
              </div>

              {/* Quick Course Selector action bar */}
              {selectedCourseFilter !== 'all' && (
                <div className="mt-2 flex items-center justify-between px-1 text-[11px]">
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
            <section className={`flex flex-col border-t border-line p-4 ${activeTab === 'materials' ? 'hidden lg:flex' : 'flex'}`}>
              <div className="flex items-center justify-between pb-2">
                <span className="font-semibold text-xs uppercase tracking-wide text-muted">Recent Study Sessions</span>
                <button
                  type="button"
                  className="text-[11px] font-semibold text-violet hover:underline"
                  onClick={startNewConversation}
                >
                  + New chat
                </button>
              </div>

              {conversations.length > 3 && (
                <div className="relative mb-2">
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

              <div className="max-h-[180px] overflow-y-auto divide-y divide-line rounded-lg border border-line bg-white">
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
        <section className={`flex min-w-0 flex-1 flex-col overflow-hidden ${activeTab !== 'chat' ? 'hidden lg:flex' : 'flex'}`}>
          <header className="flex items-center justify-between gap-3 border-b border-line bg-white px-5 py-3.5 shrink-0">
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
                    ? `Answering with ${selected.length} attached course document${selected.length > 1 ? 's' : ''}`
                    : 'Ask anything across your courses, topics, exams, or syllabus'}
                </small>
              </div>
            </div>
            {selected.length > 0 && (
              <span className="hidden sm:inline-flex items-center gap-1 text-xs text-muted">
                Attached: <strong className="text-violet-dark font-medium">{selected.length} files</strong>
              </span>
            )}
          </header>

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
          <form className="flex gap-2 border-t border-line bg-white p-3.5 shrink-0" onSubmit={send}>
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
    </main>
  );
}


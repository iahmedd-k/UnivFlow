'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import MarkdownRenderer from '../MarkdownRenderer';

const syncTime = (value) => {
  if (!value) return 'Not synced yet';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Sync time unavailable' : `Last synced ${date.toLocaleString()}`;
};
const safeExternalUrl = (value) => {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch { return null; }
};
const materialCourseId = (item) => item.course_id ?? item.courseId ?? item.course?.id;

/* UI only: small file-type badge derived from fields the item already has. */
const BADGE_STYLES = {
  PDF: 'bg-red-50 text-red-700',
  DOC: 'bg-blue-50 text-blue-700',
  PPT: 'bg-amber-50 text-amber-800',
  TXT: 'bg-emerald-50 text-emerald-700',
  FILE: 'bg-slate-100 text-slate-600',
};
const fileBadge = (item) => {
  const ext = String(item.title || '').split('.').pop().toLowerCase();
  const mime = String(item.mime_type || item.type || '').toLowerCase();
  if (ext === 'pdf' || mime.includes('pdf')) return 'PDF';
  if (['doc', 'docx'].includes(ext) || mime.includes('word') || mime.includes('document')) return 'DOC';
  if (['ppt', 'pptx'].includes(ext) || mime.includes('presentation') || mime.includes('powerpoint')) return 'PPT';
  if (ext === 'txt' || mime.startsWith('text/')) return 'TXT';
  return 'FILE';
};

const PanelIcon = ({ side }) => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
    <rect x="3" y="4" width="18" height="16" rx="3" />
    <path d={side === 'left' ? 'M9 4v16' : 'M15 4v16'} />
  </svg>
);

export default function StudyAssistantPage() {
  const { getToken } = useAuth();
  const [courses, setCourses] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [syncStatus, setSyncStatus] = useState(null);
  const [courseFilter, setCourseFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState('');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState('');
  const [reconnectUrl, setReconnectUrl] = useState('');
  const [notice, setNotice] = useState('');
  const [showSources, setShowSources] = useState(() => (typeof window !== 'undefined' ? window.innerWidth >= 1024 : true));
  const [showRecent, setShowRecent] = useState(false);    // right panel (UI only)
  const listRef = useRef(null);
  const textareaRef = useRef(null);

  const loadWorkspace = useCallback(async () => {
    const token = await getToken();
    const results = await Promise.allSettled([
      api.getCourses(token), api.getClassroomStudyMaterials(token), api.getRagConversations(token), api.getSyncStatus(token),
    ]);
    const [courseResult, materialResult, conversationResult, statusResult] = results;
    if (courseResult.status === 'fulfilled') setCourses(courseResult.value || []);
    if (materialResult.status === 'fulfilled') {
      const rows = materialResult.value || [];
      setMaterials(rows);
      setSelected((current) => current.filter((id) => rows.some((row) => row.id === id)));
    }
    if (conversationResult.status === 'fulfilled') setConversations(conversationResult.value || []);
    if (statusResult.status === 'fulfilled') setSyncStatus(statusResult.value || null);
    const failed = results.find((result) => result.status === 'rejected');
    if (failed) throw failed.reason;
  }, [getToken]);

  useEffect(() => {
    let active = true;
    (async () => {
      try { await loadWorkspace(); }
      catch (err) { if (active) setError(err?.message || 'Could not load your saved course materials.'); }
      finally { if (active) setLoading(false); }
    })();
    return () => { active = false; };
  }, [loadWorkspace]);


  // Scroll only the message list (never the page).
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }, [messages, sending]);

  const visibleMaterials = useMemo(() => {
    const term = search.trim().toLowerCase();
    return materials.filter((item) => {
      if (courseFilter !== 'all' && String(materialCourseId(item) ?? '') !== String(courseFilter)) return false;
      return !term || [item.title, item.course_name, item.assignment].some((value) => String(value || '').toLowerCase().includes(term));
    });
  }, [materials, courseFilter, search]);
  const indexedCount = visibleMaterials.filter((item) => item.has_content).length;
  const toggleSource = (id) => setSelected((current) => {
    if (current.includes(id)) return current.filter((item) => item !== id);
    if (current.length >= 100) { setError('Select up to 100 sources at a time. Use the course filter to search a whole course.'); return current; }
    setError('');
    return [...current, id];
  });
  const resetSources = () => { setSelected([]); setCourseFilter('all'); };

  const loadConversation = async (id) => {
    setError('');
    try {
      const rows = await api.getRagConversationMessages(id, await getToken());
      setMessages((rows || []).map((row) => ({ role: row.role === 'assistant' ? 'assistant' : 'user', text: row.content })));
      setConversationId(id);
    } catch (err) { setError(err?.message || 'Could not open this conversation.'); }
  };

  const startNewChat = () => { setConversationId(null); setMessages([]); setDraft(''); setError(''); };

  const syncMaterials = async () => {
    setSyncing(true); setError(''); setNotice(''); setReconnectUrl('');
    try {
      const result = await api.syncStudyMaterials(await getToken());
      if (result?.status === 'reconnect_required') {
        setReconnectUrl(result.reconnect_url || '/api/v1/auth/google?redirect_to=/dashboard/courses');
        setError(result.message || 'Reconnect Google Classroom to allow course files to sync.');
        return;
      }
      if (result?.status !== 'success') throw new Error(result?.error || 'Some course data could not be synced. Try again shortly.');
      await loadWorkspace();
      setSyncStatus((current) => ({ ...(current || {}), last_sync: new Date().toISOString() }));
      setNotice(`Synced ${result.assignments_synced || 0} coursework items and ${result.materials_synced || 0} teacher materials across ${result.courses_synced || 0} courses. Extracted text is saved for chat.`);
    } catch (err) { setError(err?.message || 'Could not sync course materials.'); }
    finally { setSyncing(false); }
  };

  const sendMessage = async (event) => {
    event?.preventDefault();
    const prompt = draft.trim();
    if (!prompt || sending) return;
    const previous = messages;
    setDraft(''); setError(''); setMessages([...previous, { role: 'user', text: prompt }]); setSending(true);
    try {
      const result = await api.askCourseMaterials({
        query: prompt,
        document_ids: selected,
        course_id: selected.length || courseFilter === 'all' ? null : Number(courseFilter),
        conversation_id: conversationId,
        history: previous.slice(-10),
      }, await getToken());
      setConversationId(result.conversation_id);
      setMessages((current) => [...current, {
        role: 'assistant',
        text: result.answer || 'I could not produce an answer for that question.',
        sources: (result.materials || []).slice(0, 5),
      }]);
      setConversations((current) => {
        const next = { id: result.conversation_id, title: prompt.slice(0, 70), source: 'rag' };
        return current.some((item) => item.id === next.id) ? current : [next, ...current];
      });
    } catch (err) {
      setMessages(previous); setDraft(prompt); setError(err?.message || 'The assistant could not answer. Your message is ready to retry.');
    } finally { setSending(false); textareaRef.current?.focus(); }
  };

  const courseName = courses.find((course) => String(course.id) === String(courseFilter))?.name || 'this course';
  const toggleBtn = (on) => `inline-flex size-11 items-center justify-center rounded-xl border transition ${on ? 'border-violet/30 bg-violet-light text-violet' : 'border-line bg-white text-ink hover:bg-paper'}`;

  return (
    <main className="flex h-full min-h-[560px] min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-line bg-white text-ink shadow-sm lg:min-h-0">
      {/* Header */}
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-line px-3 py-2.5 sm:px-4">
        <div className="flex min-w-0 items-center gap-3">
          <button type="button" onClick={() => setShowSources((v) => !v)} aria-pressed={showSources} aria-label="Toggle course sources" className={toggleBtn(showSources)}><PanelIcon side="left" /></button>
          <div className="min-w-0">
            <h1 className="truncate text-lg font-bold tracking-tight sm:text-xl">Study Assistant</h1>
            <p title={syncStatus?.sync_run?.errors?.join('\n') || undefined} className="hidden truncate text-xs text-muted sm:block">
              Saved course library · {syncStatus?.sync_run?.status === 'partial' ? 'Some files need attention' : syncTime(syncStatus?.last_sync)}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {syncStatus?.google_connected === false
            ? <a href="/api/v1/auth/google?redirect_to=/dashboard/courses" className="hidden h-11 items-center rounded-xl border border-line px-3.5 text-sm font-semibold transition hover:bg-paper sm:inline-flex">Connect Classroom</a>
            : <button type="button" onClick={syncMaterials} disabled={syncing} className="hidden h-11 items-center gap-2 rounded-xl border border-line px-3.5 text-sm font-semibold transition hover:bg-paper disabled:opacity-60 sm:inline-flex"><span className={syncing ? 'animate-spin' : ''}>↻</span>{syncing ? 'Syncing…' : 'Sync courses'}</button>}
          <button type="button" onClick={startNewChat} className="h-11 rounded-xl bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark">+ New chat</button>
          <button type="button" onClick={() => setShowRecent((v) => !v)} aria-pressed={showRecent} aria-label="Toggle recent chats" className={toggleBtn(showRecent)}><PanelIcon side="right" /></button>
        </div>
      </header>
      {(error || notice) && <div role={error ? 'alert' : 'status'} className={`mx-4 mt-3 flex shrink-0 flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3 text-sm sm:mx-6 ${error ? 'border-rose-border bg-rose-bg text-rose' : 'border-emerald-200 bg-emerald-50 text-emerald-800'}`}><span>{error || notice}</span>{error && reconnectUrl && <a href={reconnectUrl} className="rounded-lg bg-rose px-3 py-2 text-xs font-semibold text-white">Reconnect Google Classroom</a>}</div>}

      <div className="relative flex min-h-0 flex-1">
        {/* Sources panel (toggle) */}
        {showSources && (
          <aside className="absolute inset-y-0 left-0 z-10 flex w-[272px] max-w-full shrink-0 flex-col border-r border-line bg-[#fbfbfd] shadow-xl lg:static lg:shadow-none">
            <div className="border-b border-line p-4">
              <div className="flex items-center justify-between"><div><h2 className="text-sm font-bold">Course sources</h2><p className="mt-0.5 text-xs text-muted">{indexedCount} indexed · {visibleMaterials.length} saved</p></div><button type="button" onClick={resetSources} className="text-xs font-semibold text-violet hover:underline">Use all</button></div>
              <p className="mt-2 text-xs leading-5 text-muted">{selected.length ? `${selected.length} selected for this chat` : courseFilter === 'all' ? 'All saved materials are searched automatically' : `All files in ${courseName} are searched`}</p>
              <select value={courseFilter} onChange={(event) => { setCourseFilter(event.target.value); setSelected([]); setError(''); }} aria-label="Filter by course" className="mt-3 h-11 w-full rounded-xl border border-line bg-white px-3 text-sm outline-none focus:border-violet"><option value="all">All courses</option>{courses.map((course) => <option key={course.id} value={course.id}>{course.name}</option>)}</select>
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Find a file or topic" aria-label="Find a file or topic" className="mt-2 h-11 w-full rounded-xl border border-line bg-white px-3 text-sm outline-none placeholder:text-muted focus:border-violet" />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-2.5">
              {loading ? <p className="p-4 text-sm text-muted">Loading saved sources…</p> : visibleMaterials.length ? visibleMaterials.map((item) => {
                const badge = fileBadge(item);
                return (
                  <label key={item.id} className={`mb-1 flex cursor-pointer items-center gap-3 rounded-xl p-2.5 transition ${selected.includes(item.id) ? 'bg-violet-light' : 'hover:bg-white'}`}>
                    <span className={`flex size-9 shrink-0 items-center justify-center rounded-[10px] text-[10px] font-bold ${BADGE_STYLES[badge]}`}>{badge}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold" title={item.title}>{item.title}</span>
                      <span className={`mt-0.5 block truncate text-xs ${item.has_content ? 'text-muted' : 'text-amber-800'}`}>{item.course_name || 'Course material'} · {item.has_content ? 'Ready for chat' : 'Metadata only'}</span>
                    </span>
                    <input type="checkbox" checked={selected.includes(item.id)} onChange={() => toggleSource(item.id)} className="size-5 shrink-0 accent-violet" />
                  </label>
                );
              }) : <div className="p-5 text-center"><p className="text-sm font-semibold">{materials.length ? 'No matching files' : 'No synced materials yet'}</p><p className="mt-1 text-xs leading-5 text-muted">{materials.length ? 'Try another search or course.' : 'Sync Google Classroom to save slides, handouts, assignments, and notes here.'}</p></div>}
            </div>
            <div className="border-t border-line px-4 py-3 text-xs text-muted">Chat uses stored text; questions do not fetch files from Google live.</div>
          </aside>
        )}

        {/* Chat (takes all remaining width) */}
        <section className="flex min-w-0 flex-1 flex-col bg-white">
          <div className="flex shrink-0 items-center justify-between gap-3 border-b border-line px-4 py-3 md:px-6">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">{conversationId ? conversations.find((item) => item.id === conversationId)?.title || 'Study conversation' : 'New study chat'}</p>
              <p className="mt-0.5 truncate text-xs text-muted">{selected.length ? `Grounded in ${selected.length} selected sources` : courseFilter === 'all' ? `Searches all ${indexedCount} indexed sources` : `Searches indexed sources in ${courseName}`}</p>
            </div>
          </div>

          {/* Only this area scrolls */}
          <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto flex min-h-full w-full max-w-[880px] flex-col gap-7 px-4 py-7 md:px-6">
              {messages.length === 0 && !loading && <div className="m-auto w-full max-w-2xl py-10 text-center"><div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-2xl bg-violet-light text-xl text-violet">✦</div><h2 className="text-xl font-bold">What are you studying today?</h2><p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-muted">Ask for an explanation, summary, or practice questions. I’ll search saved course materials and tell you when a topic isn’t covered there.</p><div className="mt-6 flex flex-wrap justify-center gap-2">{['Summarize the latest lecture slides', 'Explain a difficult concept step by step', 'Make practice questions from my course notes'].map((prompt) => <button key={prompt} type="button" onClick={() => { setDraft(prompt); textareaRef.current?.focus(); }} className="rounded-full border border-line bg-white px-3.5 py-2 text-xs font-medium text-ink transition hover:border-violet hover:text-violet">{prompt}</button>)}</div></div>}

              {messages.map((message, index) => message.role === 'user' ? (
                <article key={`${index}-${message.role}`} className="ml-auto max-w-[80%] whitespace-pre-wrap rounded-[20px] rounded-br-md bg-violet-light px-[18px] py-3 text-base leading-relaxed">{message.text}</article>
              ) : (
                <article key={`${index}-${message.role}`} className="text-base leading-7">
                  <MarkdownRenderer content={message.text} />
                  {message.sources?.length > 0 && (
                    <div className="mt-4">
                      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">Sources searched</p>
                      <div className="flex flex-wrap gap-2">{message.sources.map((source) => { const href = safeExternalUrl(source.url); return href ? <a key={source.id} href={href} target="_blank" rel="noreferrer" className="max-w-full truncate rounded-full bg-paper px-3 py-1.5 text-[13px] font-medium text-violet hover:underline">{source.title}</a> : <span key={source.id} className="max-w-full truncate rounded-full bg-paper px-3 py-1.5 text-[13px] font-medium text-muted">{source.title}</span>; })}</div>
                    </div>
                  )}
                </article>
              ))}
              {sending && <p className="text-sm text-muted">Searching your saved course materials…</p>}
            </div>
          </div>

          {/* Composer stays pinned */}
          <form onSubmit={sendMessage} className="shrink-0 bg-white px-4 pb-4 pt-2 md:px-6">
            <div className="mx-auto max-w-[880px]">
              <div className="flex items-end gap-2.5 rounded-[20px] border border-line bg-white p-2.5 shadow-sm focus-within:border-violet focus-within:ring-2 focus-within:ring-violet/10">
                <textarea ref={textareaRef} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(event); } }} maxLength={8000} rows={1} placeholder="Ask about your courses…" className="max-h-40 min-h-11 flex-1 resize-none bg-transparent px-2 py-2.5 text-base leading-6 outline-none placeholder:text-muted" aria-label="Message the Study Assistant" />
                <button type="submit" disabled={sending || !draft.trim()} className="inline-flex h-11 shrink-0 items-center gap-2 rounded-xl bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-50">{sending ? 'Thinking…' : 'Send'}<span aria-hidden="true">↑</span></button>
              </div>
              <div className="mt-2 flex items-center justify-between gap-3 text-xs text-muted"><span>Enter to send · Shift + Enter for a new line</span><span>{selected.length ? `${selected.length} selected sources` : 'All indexed sources'}</span></div>
            </div>
          </form>
        </section>

        {/* Recent chats panel (toggle) */}
        {showRecent && (
          <aside className="absolute inset-y-0 right-0 z-10 flex w-[272px] max-w-full shrink-0 flex-col border-l border-line bg-[#fbfbfd] shadow-xl lg:static lg:shadow-none">
            <div className="border-b border-line p-4"><h2 className="text-sm font-bold">Recent chats</h2><p className="mt-1 text-xs text-muted">Your saved study conversations</p></div>
            <div className="min-h-0 flex-1 overflow-y-auto p-2.5">{conversations.length ? conversations.map((item) => <button key={item.id} type="button" onClick={() => loadConversation(item.id)} className={`mb-1 block w-full rounded-xl px-3 py-3 text-left text-sm transition ${conversationId === item.id ? 'bg-violet-light' : 'hover:bg-white'}`}><span className="block truncate font-semibold">{item.title || 'Study chat'}</span><span className="mt-1 block text-xs text-muted">{item.updated_at ? new Date(item.updated_at).toLocaleDateString() : 'Conversation'}</span></button>) : <p className="p-4 text-xs leading-5 text-muted">Your chats will appear here.</p>}</div>
          </aside>
        )}
      </div>
    </main>
  );
}
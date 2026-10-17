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
  const [showSources, setShowSources] = useState(false);
  const bottomRef = useRef(null);
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

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [messages, sending]);

  const visibleMaterials = useMemo(() => {
    const term = search.trim().toLowerCase();
    return materials.filter((item) => {
      if (courseFilter !== 'all' && String(item.course_id) !== String(courseFilter)) return false;
      return !term || [item.title, item.course_name, item.assignment].some((value) => String(value || '').toLowerCase().includes(term));
    });
  }, [materials, courseFilter, search]);
  const indexedCount = materials.filter((item) => item.has_content).length;
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

  return (
    <main className="flex min-h-[600px] min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-line bg-white text-ink shadow-sm lg:min-h-0">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-line px-5 py-4 sm:px-7">
        <div className="min-w-0">
          <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-muted"><span className="size-2 rounded-full bg-emerald-500" /> Saved course library</div>
          <h1 className="text-xl font-bold tracking-tight sm:text-2xl">Study Assistant</h1>
          <p className="mt-1 text-sm text-muted">Ask questions across your synced slides, notes, assignments, and announcements.</p>
        </div>
        <div className="flex items-center gap-2">
          <span title={syncStatus?.sync_run?.errors?.join('\n') || undefined} className="hidden rounded-full bg-paper px-3 py-2 text-xs font-medium text-muted sm:inline-flex">{syncStatus?.sync_run?.status === 'partial' ? 'Some files need attention' : syncTime(syncStatus?.last_sync)}</span>
          {syncStatus?.google_connected === false
            ? <a href="/api/v1/auth/google?redirect_to=/dashboard/courses" className="inline-flex h-10 items-center rounded-xl border border-line px-3.5 text-sm font-semibold transition hover:bg-paper">Connect Classroom</a>
            : <button type="button" onClick={syncMaterials} disabled={syncing} className="inline-flex h-10 items-center gap-2 rounded-xl border border-line px-3.5 text-sm font-semibold transition hover:bg-paper disabled:opacity-60"><span className={syncing ? 'animate-spin' : ''}>↻</span>{syncing ? 'Syncing…' : 'Sync courses'}</button>}
          <button type="button" onClick={startNewChat} className="h-10 rounded-xl bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark">New chat</button>
        </div>
      </header>
      {(error || notice) && <div role={error ? 'alert' : 'status'} className={`mx-5 mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3 text-sm sm:mx-7 ${error ? 'border-rose-border bg-rose-bg text-rose' : 'border-emerald-200 bg-emerald-50 text-emerald-800'}`}><span>{error || notice}</span>{error && reconnectUrl && <a href={reconnectUrl} className="rounded-lg bg-rose px-3 py-2 text-xs font-semibold text-white">Reconnect Google Classroom</a>}</div>}

      <div className="flex min-h-0 flex-1">
        <aside className={`${showSources ? 'flex' : 'hidden'} w-full shrink-0 flex-col border-r border-line bg-[#fbfbfd] md:flex md:w-[290px]`}>
          <div className="border-b border-line p-4">
            <div className="flex items-center justify-between"><div><h2 className="text-sm font-bold">Course sources</h2><p className="mt-0.5 text-xs text-muted">{indexedCount} indexed · {materials.length} saved</p></div><button type="button" onClick={resetSources} className="text-xs font-semibold text-violet hover:underline">Use all</button></div>
            <p className="mt-2 text-xs leading-5 text-muted">{selected.length ? `${selected.length} selected for this chat` : courseFilter === 'all' ? 'All saved materials are searched automatically' : `All files in ${courses.find((course) => String(course.id) === String(courseFilter))?.name || 'this course'} are searched`}</p>
            <select value={courseFilter} onChange={(event) => setCourseFilter(event.target.value)} className="mt-3 h-10 w-full rounded-lg border border-line bg-white px-3 text-sm outline-none focus:border-violet"><option value="all">All courses</option>{courses.map((course) => <option key={course.id} value={course.id}>{course.name}</option>)}</select>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Find a file or topic" className="mt-2 h-10 w-full rounded-lg border border-line bg-white px-3 text-sm outline-none placeholder:text-muted focus:border-violet" />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {loading ? <p className="p-4 text-sm text-muted">Loading saved sources…</p> : visibleMaterials.length ? visibleMaterials.map((item) => <label key={item.id} className={`mb-1 flex cursor-pointer items-start gap-3 rounded-xl p-3 transition ${selected.includes(item.id) ? 'bg-violet-light/60' : 'hover:bg-white'}`}><input type="checkbox" checked={selected.includes(item.id)} onChange={() => toggleSource(item.id)} className="mt-1 accent-violet" /><span className="min-w-0 flex-1"><span className="block truncate text-sm font-semibold" title={item.title}>{item.title}</span><span className="mt-1 block truncate text-xs text-muted">{item.course_name || 'Course material'}</span><span className={`mt-1.5 inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold ${item.has_content ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800'}`}>{item.has_content ? 'Ready for chat' : 'Metadata only'}</span></span></label>) : <div className="p-5 text-center"><p className="text-sm font-semibold">{materials.length ? 'No matching files' : 'No synced materials yet'}</p><p className="mt-1 text-xs leading-5 text-muted">{materials.length ? 'Try another search or course.' : 'Sync Google Classroom to save slides, handouts, assignments, and notes here.'}</p></div>}
          </div>
          <div className="border-t border-line px-4 py-3 text-xs text-muted">Chat uses stored text; questions do not fetch files from Google live.</div>
        </aside>

        <section className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center justify-between border-b border-line px-4 py-3 md:px-6"><div className="min-w-0"><p className="truncate text-sm font-semibold">{conversationId ? conversations.find((item) => item.id === conversationId)?.title || 'Study conversation' : 'New study chat'}</p><p className="mt-0.5 text-xs text-muted">{selected.length ? `Grounded in ${selected.length} selected sources` : courseFilter === 'all' ? `Searches all ${indexedCount} indexed sources` : `Searches indexed sources in ${courses.find((course) => String(course.id) === String(courseFilter))?.name || 'this course'}`}</p></div><button type="button" onClick={() => setShowSources((value) => !value)} className="rounded-lg border border-line px-3 py-2 text-xs font-semibold md:hidden">{showSources ? 'Hide sources' : 'Sources'}</button></div>
          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 py-5 md:px-7">
            {messages.length === 0 && !loading && <div className="m-auto w-full max-w-2xl py-10 text-center"><div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-2xl bg-violet-light text-xl text-violet">✦</div><h2 className="text-xl font-bold">What are you studying today?</h2><p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-muted">Ask for an explanation, summary, or practice questions. I’ll search saved course materials and tell you when a topic isn’t covered there.</p><div className="mt-6 flex flex-wrap justify-center gap-2">{['Summarize the latest lecture slides', 'Explain a difficult concept step by step', 'Make practice questions from my course notes'].map((prompt) => <button key={prompt} type="button" onClick={() => { setDraft(prompt); textareaRef.current?.focus(); }} className="rounded-full border border-line bg-white px-3 py-2 text-xs font-medium text-ink transition hover:border-violet hover:text-violet">{prompt}</button>)}</div></div>}
            {messages.map((message, index) => <article key={`${index}-${message.role}`} className={`max-w-[92%] rounded-2xl px-4 py-3 text-sm leading-6 sm:max-w-[82%] ${message.role === 'user' ? 'ml-auto rounded-br-md bg-violet text-white' : 'rounded-bl-md border border-line bg-white'}`}>{message.role === 'assistant' ? <><MarkdownRenderer content={message.text} />{message.sources?.length > 0 && <div className="mt-3 border-t border-line pt-2"><p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">Sources searched</p><div className="flex flex-wrap gap-1.5">{message.sources.map((source) => { const href = safeExternalUrl(source.url); return href ? <a key={source.id} href={href} target="_blank" rel="noreferrer" className="max-w-full truncate rounded-full bg-paper px-2.5 py-1 text-xs text-violet hover:underline">{source.title}</a> : <span key={source.id} className="max-w-full truncate rounded-full bg-paper px-2.5 py-1 text-xs text-muted">{source.title}</span>; })}</div></div>}</> : <p className="whitespace-pre-wrap">{message.text}</p>}</article>)}
            {sending && <div className="max-w-[85%] rounded-2xl rounded-bl-md bg-paper px-4 py-3 text-sm text-muted">Searching your saved course materials…</div>}
            <div ref={bottomRef} />
          </div>
          <form onSubmit={sendMessage} className="border-t border-line bg-white p-3 sm:p-5"><div className="mx-auto flex max-w-4xl items-end gap-2 rounded-2xl border border-line bg-[#fcfcfd] p-2 focus-within:border-violet focus-within:ring-2 focus-within:ring-violet/10"><textarea ref={textareaRef} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(event); } }} maxLength={8000} rows={1} placeholder="Ask about your courses…" className="max-h-36 min-h-10 flex-1 resize-y bg-transparent px-2 py-2 text-sm leading-6 outline-none placeholder:text-muted" aria-label="Message the Study Assistant" /><button type="submit" disabled={sending || !draft.trim()} className="inline-flex h-10 shrink-0 items-center gap-2 rounded-xl bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-50">{sending ? 'Thinking…' : 'Send'}<span aria-hidden="true">↑</span></button></div><div className="mx-auto mt-2 flex max-w-4xl items-center justify-between text-[11px] text-muted"><span>Enter to send · Shift + Enter for a new line</span><span>{selected.length ? 'Selected sources' : 'All indexed sources'}</span></div></form>
        </section>

        <aside className="hidden w-[240px] shrink-0 flex-col border-l border-line bg-[#fbfbfd] xl:flex"><div className="border-b border-line p-4"><h2 className="text-sm font-bold">Recent chats</h2><p className="mt-1 text-xs text-muted">Your saved study conversations</p></div><div className="min-h-0 flex-1 overflow-y-auto p-2">{conversations.length ? conversations.map((item) => <button key={item.id} type="button" onClick={() => loadConversation(item.id)} className={`mb-1 block w-full rounded-xl px-3 py-3 text-left text-sm transition ${conversationId === item.id ? 'bg-violet-light/60' : 'hover:bg-white'}`}><span className="block truncate font-semibold">{item.title || 'Study chat'}</span><span className="mt-1 block text-xs text-muted">{item.updated_at ? new Date(item.updated_at).toLocaleDateString() : 'Conversation'}</span></button>) : <p className="p-4 text-xs leading-5 text-muted">Your chats will appear here.</p>}</div></aside>
      </div>
    </main>
  );
}

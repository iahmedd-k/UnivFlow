'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import MarkdownRenderer from '../MarkdownRenderer';

export default function CoursesPage() {
  const { getToken } = useAuth();
  const [materials, setMaterials] = useState([]);
  const [selected, setSelected] = useState([]);
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const initializedSelection = useRef(false);

  const load = useCallback(async () => {
    const token = await getToken();
    const rows = await api.getClassroomStudyMaterials(token);
    setMaterials(rows || []);
    if (!initializedSelection.current) {
      initializedSelection.current = true;
      setSelected((rows || []).map((item) => item.id));
    } else {
      setSelected((current) => current.filter((id) => rows.some((item) => item.id === id)));
    }
  }, [getToken]);
  useEffect(() => { load().catch((e) => setError(e.message || 'Could not load Classroom materials.')).finally(() => setLoading(false)); }, [load]);

  const send = async (event) => {
    event.preventDefault(); if (!question.trim()) return;
    const prompt = question.trim(); setQuestion(''); setError(''); setBusy(true);
    setMessages((items) => [...items, { role: 'you', text: prompt }]);
    try {
      const token = await getToken();
      const result = await api.askCourseMaterials({ query: prompt, document_ids: selected }, token);
      setMessages((items) => [...items, { role: 'assistant', text: result.answer || 'No answer returned.' }]);
    } catch (e) { setError(e.message || 'Could not answer from the selected materials.'); }
    finally { setBusy(false); }
  };

  const refreshMaterials = () => {
    setLoading(true);
    setError('');
    load().catch((e) => setError(e.message || 'Could not refresh course materials.')).finally(() => setLoading(false));
  };

  const cardClass = 'min-w-0 overflow-hidden rounded-xl border border-line bg-white shadow-sm';
  const cardHeaderClass = 'flex items-center justify-between gap-3 border-b border-line px-5 py-4';
  const labelClass = 'mb-1 block text-xs font-semibold uppercase tracking-wide text-muted';
  const secondaryButtonClass = 'inline-flex min-h-9 items-center justify-center rounded-lg border border-line bg-white px-3 text-sm font-semibold text-ink transition hover:bg-paper disabled:cursor-not-allowed disabled:opacity-50';

  return (
    <main className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 pb-10 text-ink">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className={labelClass}>Coursework</p>
          <h1 className="text-2xl font-semibold tracking-tight">Study assistant</h1>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-muted">Choose course materials, then ask a question grounded in those sources.</p>
        </div>
        <span className="inline-flex w-fit items-center rounded-full bg-violet-light px-3 py-1.5 text-sm font-semibold text-violet-dark">{selected.length} of {materials.length} sources selected</span>
      </header>
      {error && <div className="rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-sm text-rose" role="alert">{error}</div>}
      <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-2">
        <section className={cardClass}>
          <header className={cardHeaderClass}>
            <div><p className={labelClass}>Step 1</p><h2 className="text-base font-semibold">Choose course materials</h2></div>
            <button className={secondaryButtonClass} type="button" disabled={loading} onClick={refreshMaterials}>{loading ? 'Loading…' : 'Refresh'}</button>
          </header>
          {!loading && materials.length > 0 && (
            <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
              <span className="text-sm text-muted">{selected.length} selected</span>
              <div className="flex gap-3">
                <button type="button" className="text-sm font-semibold text-violet hover:text-violet-dark" onClick={() => setSelected(materials.map((item) => item.id))}>Select all</button>
                <button type="button" className="text-sm font-semibold text-violet hover:text-violet-dark" onClick={() => setSelected([])}>Clear</button>
              </div>
            </div>
          )}
          {loading ? <div className="p-8 text-center text-sm text-muted" role="status">Loading synced materials…</div> : materials.length ? (
            <div className="max-h-[520px] divide-y divide-line overflow-y-auto" aria-label="Select source materials">
              {materials.map((item) => <label key={item.id} className="flex cursor-pointer items-start gap-3 px-5 py-4 transition hover:bg-paper">
                <input className="mt-1 size-4 accent-violet" type="checkbox" checked={selected.includes(item.id)} onChange={(e) => setSelected((ids) => e.target.checked ? [...ids, item.id] : ids.filter((id) => id !== item.id))} />
                <span className="flex min-w-0 flex-col gap-1"><strong className="text-sm font-semibold text-ink">{item.title || 'Untitled file'}</strong><small className="text-xs text-muted">{[item.course_name, item.assignment].filter(Boolean).join(' · ') || 'Course material'}</small></span>
              </label>)}
            </div>
          ) : <div className="p-8 text-center"><strong className="block text-sm font-semibold">No course files available</strong><span className="mt-1 block text-sm text-muted">Connect Google Classroom and sync your coursework to add materials here.</span></div>}
        </section>

        <section className={`${cardClass} flex min-h-[520px] flex-col`}>
          <header className={cardHeaderClass}><div><p className={labelClass}>Step 2</p><h2 className="text-base font-semibold">Ask about your sources</h2></div></header>
          <div className="flex min-h-0 flex-1 flex-col gap-4 p-5">
            <p className="text-sm leading-6 text-muted">Answers use relevant passages from selected materials. If the sources do not cover your question, the assistant will say so.</p>
            <div className="flex min-h-[300px] flex-1 flex-col gap-3 overflow-y-auto rounded-lg bg-paper p-4" aria-live="polite" aria-busy={busy}>
              {messages.length ? messages.map((message, index) => (
                <article className={`max-w-[90%] rounded-xl border px-4 py-3 text-sm leading-6 ${message.role === 'you' ? 'ml-auto border-violet bg-violet text-white' : 'border-line bg-white text-ink'}`} key={index}>
                  <small className={`mb-1 block text-xs font-semibold ${message.role === 'you' ? 'text-white/75' : 'text-muted'}`}>{message.role === 'you' ? 'You' : 'Study assistant'}</small>
                  {message.role === 'you' ? <p className="whitespace-pre-wrap">{message.text}</p> : <MarkdownRenderer content={message.text} />}
                </article>
              )) : <div className="m-auto max-w-sm text-center text-sm leading-6 text-muted">{selected.length ? 'Ask for an explanation, compare concepts, or review a topic.' : 'Select at least one source to begin.'}</div>}
              {busy && <p className="text-sm text-muted" role="status">Searching selected sources…</p>}
            </div>
            <form className="flex gap-2" onSubmit={send}>
              <input className="min-w-0 flex-1 rounded-lg border border-line bg-white px-3 py-2.5 text-sm text-ink outline-none placeholder:text-muted focus:border-violet focus:ring-2 focus:ring-violet/20" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about the selected materials…" aria-label="Ask about selected materials" />
              <button className="inline-flex min-h-10 items-center justify-center rounded-lg bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-50" disabled={busy || !question.trim() || !selected.length}>{busy ? 'Working…' : 'Ask'}</button>
            </form>
          </div>
        </section>
      </div>
    </main>
  );
}

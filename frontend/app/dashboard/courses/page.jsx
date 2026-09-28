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

  return (
    <main className="product-page pb-10">
      <header className="product-heading">
        <div><p className="eyebrow">COURSEWORK</p><h1>Study assistant</h1><p>Choose course materials, then ask a question grounded in those sources.</p></div>
        <span className="product-pill">{selected.length} of {materials.length} sources selected</span>
      </header>
      {error && <div className="product-alert" role="alert">{error}</div>}
      <div className="product-grid study-grid">
        <section className="product-card">
          <header className="product-card-head">
            <div><p className="eyebrow">STEP 1</p><h2>Choose course materials</h2></div>
            <button className="product-action secondary" type="button" disabled={loading} onClick={refreshMaterials}>{loading ? 'Loading…' : 'Refresh'}</button>
          </header>
          {!loading && materials.length > 0 && (
            <div className="flex items-center justify-between gap-3 border-b border-[#f0f0f3] px-4 py-3">
              <span className="text-[10px] text-[#858998]">{selected.length} selected</span>
              <div className="flex gap-2">
                <button type="button" className="text-[10px] font-medium text-[#6657d9]" onClick={() => setSelected(materials.map((item) => item.id))}>Select all</button>
                <span className="text-[#d8d8e0]" aria-hidden="true">·</span>
                <button type="button" className="text-[10px] font-medium text-[#6657d9]" onClick={() => setSelected([])}>Clear</button>
              </div>
            </div>
          )}
          {loading ? <div className="product-empty" role="status">Loading synced materials…</div> : materials.length ? (
            <div className="study-materials" aria-label="Select source materials">{materials.map((item) => <label key={item.id}><input type="checkbox" checked={selected.includes(item.id)} onChange={(e) => setSelected((ids) => e.target.checked ? [...ids, item.id] : ids.filter((id) => id !== item.id))} /><span><strong>{item.title || 'Untitled file'}</strong><small>{[item.course_name, item.assignment].filter(Boolean).join(' · ') || 'Course material'}</small></span></label>)}</div>
          ) : <div className="product-empty"><strong>No course files available</strong><span>Connect Google Classroom and sync your coursework to add materials here.</span></div>}
        </section>

        <section className="product-card">
          <header className="product-card-head"><div><p className="eyebrow">STEP 2</p><h2>Ask about your sources</h2></div></header>
          <div className="product-card-body study-chat">
            <p className="product-note">Answers use relevant passages from selected materials. If the sources do not cover your question, the assistant will say so.</p>
            <div className="study-messages" aria-live="polite" aria-busy={busy}>
              {messages.length ? messages.map((message, index) => (
                <article className={`study-message ${message.role}`} key={index}>
                  <small>{message.role === 'you' ? 'You' : 'Study assistant'}</small>
                  {message.role === 'you' ? (
                    <p style={{ whiteSpace: 'pre-wrap' }}>{message.text}</p>
                  ) : (
                    <MarkdownRenderer content={message.text} />
                  )}
                </article>
              )) : <div className="product-empty">{selected.length ? 'Ask for an explanation, compare concepts, or review a topic.' : 'Select at least one source to begin.'}</div>}
              {busy && <article className="study-message assistant"><small>Study assistant</small><p role="status">Searching selected sources…</p></article>}
            </div>
            <form className="study-chat-form" onSubmit={send}>
              <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about the selected materials…" aria-label="Ask about selected materials" />
              <button className="product-action" disabled={busy || !question.trim() || !selected.length}>{busy ? 'Working…' : 'Ask'}</button>
            </form>
          </div>
        </section>
      </div>
    </main>
  );
}

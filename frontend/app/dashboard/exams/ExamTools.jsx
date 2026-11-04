'use client';

import { useEffect, useRef, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { Check, ChevronDown, FileText, Loader2, UploadCloud, X } from 'lucide-react';
import { api } from '@/app/lib/api';

const button = 'rounded-lg border border-line bg-white px-3 py-2 text-sm font-semibold text-ink hover:bg-paper disabled:opacity-50';
const field = 'w-full rounded-lg border border-line px-3 py-2 text-sm';
const isReady = (item) => !item.status || ['complete', 'completed', 'indexed'].includes(String(item.status).toLowerCase());

export default function ExamTools({ materials, onSaved, ownerKey }) {
  const { getToken } = useAuth();
  const [tab, setTab] = useState('slip');
  const [file, setFile] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef(null);
  const [exams, setExams] = useState([]);
  const [extractedText, setExtractedText] = useState('');
  const [extracts, setExtracts] = useState({});
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(null);
  const [expandedCourse, setExpandedCourse] = useState(null);
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const token = await api.getRequestToken(getToken);
        const result = await api.getStudyMaterialIndexes(token);
        if (active) setExtracts(Object.fromEntries((result.items || []).map((item) => [item.material_id, item])));
      } catch (e) { if (active) setError(e.message || 'Saved study indexes could not be loaded.'); }
      finally { if (active) setHydrated(true); }
    })();
    return () => { active = false; };
  }, [getToken, ownerKey]);

  async function parseSlip(event) {
    event.preventDefault(); if (!file) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const token = await api.getRequestToken(getToken);
      const result = await api.parseExamSlip(file, token);
      const rows = result.exams || [];
      setExams((rows.length ? rows : [{ subject: '', date: '', time: '', room: '', seating_plan: '', instructions: '' }]).map((exam) => ({ ...exam, subject: exam.subject || '', date: exam.date || '', time: exam.time || '', room: exam.room || '', seating_plan: exam.seating_plan || '', instructions: exam.instructions || '' })));
      setExtractedText(result.raw_text || '');
      setNotice(result.message || 'Review the extracted details below.');
    } catch (e) { setError(e.message || 'Could not read the slip.'); }
    finally { setBusy(false); }
  }
  function chooseSlip(candidate) {
    if (!candidate) return;
    if (candidate.type !== 'application/pdf' && !candidate.type.startsWith('image/')) {
      setError('Choose a PDF or image file for your roll number slip.');
      return;
    }
    setError('');
    setFile(candidate);
  }
  async function saveExam(exam, index) {
    try {
      const token = await api.getRequestToken(getToken);
      await api.createExam({ title: exam.subject, date: exam.date ? `${exam.date}T00:00:00` : null, time: exam.time, room: exam.room, status: JSON.stringify({ seating_plan: exam.seating_plan, instructions: exam.instructions, source: 'roll_no_slip' }) }, token);
      setExams((items) => items.filter((_, i) => i !== index)); setNotice(`${exam.subject} saved. One email reminder is scheduled about an hour before the paper when a notification email is configured.`); onSaved?.();
    } catch (e) { setError(e.message || 'Could not save this exam.'); }
  }
  async function processAll() {
    setBusy(true); setError(''); setNotice('');
    const next = { ...extracts };
    try {
      const readyMaterials = materials.filter(isReady);
      for (let i = 0; i < readyMaterials.length; i++) {
        const item = readyMaterials[i];
        if (next[item.id]?.status === 'complete') continue;
        const token = await api.getRequestToken(getToken);
        setProgress(`Processing ${i + 1} of ${readyMaterials.length}: ${item.title || 'Course material'}`);
        next[item.id] = { status: 'processing', title: item.title };
        setExtracts({ ...next });
        const result = await api.generateStudyMaterialIndex(item.id, token);
        const index = result?.data || result || {};
        next[item.id] = { status: 'complete', title: index.title || item.title || item.original_filename || 'Untitled material', course: item.course_name || item.course || '', content: index.content || 'No topics were returned.' };
        setExtracts({ ...next });
      }
      setNotice(readyMaterials.length ? 'Study index is up to date.' : 'Materials will be processed automatically after RAG finishes indexing them.');
    } catch (e) { setError(e.message || 'Some materials could not be processed. Retry to continue.'); }
    finally { setProgress(''); setBusy(false); }
  }
  useEffect(() => {
    if (hydrated && materials.some((item) => isReady(item) && extracts[item.id]?.status !== 'complete')) {
      queueMicrotask(() => { void processAll(); });
    }
  // Extract newly synced/uploaded items automatically; existing results remain cached per account.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hydrated, materials]);
  const updateExam = (index, name, value) => setExams((rows) => rows.map((row, i) => i === index ? { ...row, [name]: value } : row));
  const copy = async (value) => { await navigator.clipboard.writeText(value); setNotice('Copied to clipboard.'); };
  const courseGroups = Object.values(materials.reduce((groups, item) => {
    const label = item.course_name || item.course || (item.course_id == null ? 'My uploads' : 'Course materials');
    const groupId = String(item.course_id ?? label);
    if (!groups[groupId]) groups[groupId] = { id: groupId, label, items: [] };
    groups[groupId].items.push(item);
    return groups;
  }, {}));

  return <section className="mt-4 overflow-hidden rounded-xl border border-line bg-white">
    <div className="flex gap-1.5 border-b border-line bg-paper/60 p-2" role="tablist" aria-label="Exam tools">
      {[['slip', 'Roll No Slip'], ['materials', 'Study Material']].map(([id, title]) => <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)} className={`rounded-lg px-4 py-2 text-sm font-semibold transition-colors ${tab === id ? 'bg-white text-violet-dark shadow-sm ring-1 ring-line' : 'text-muted hover:bg-white/70 hover:text-ink'}`}>{title}</button>)}
    </div>
    {(error || notice) && <p className={`mx-5 mt-4 rounded-lg px-3 py-2 text-sm ${error ? 'bg-rose-bg text-rose' : 'bg-violet-light text-violet-dark'}`} role="status">{error || notice}</p>}
    {tab === 'slip' ? <div className="p-5">
      <h2 className="mb-3 text-lg font-semibold">Roll No Slip</h2>
      <form onSubmit={parseSlip} className="space-y-3">
        <input ref={fileInputRef} type="file" accept="application/pdf,image/*" onChange={(event) => chooseSlip(event.target.files?.[0])} className="sr-only" aria-label="Choose roll number slip" />
        <div
          onDragOver={(event) => { event.preventDefault(); setIsDragging(true); }}
          onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setIsDragging(false); }}
          onDrop={(event) => { event.preventDefault(); setIsDragging(false); chooseSlip(event.dataTransfer.files?.[0]); }}
          className={`group rounded-2xl border border-dashed p-4 transition-all sm:p-5 ${isDragging ? 'border-violet-400 bg-violet-light/70 shadow-[0_0_0_4px_rgba(124,58,237,0.08)]' : 'border-line bg-gradient-to-br from-white to-violet-light/30 hover:border-violet-300 hover:shadow-sm'}`}
        >
          <div className="flex flex-col items-center gap-3 text-center sm:flex-row sm:text-left">
            <div className={`grid size-11 shrink-0 place-items-center rounded-xl border border-violet-100 bg-white text-violet-dark shadow-sm transition-transform ${isDragging ? 'scale-105' : 'group-hover:-translate-y-0.5'}`}>
              {busy ? <Loader2 className="size-5 animate-spin" /> : <UploadCloud className="size-5" />}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-ink">{busy ? 'Reading your roll slip…' : isDragging ? 'Drop your slip to upload' : 'Drop your roll slip here'}</p>
              <p className="mt-0.5 text-xs leading-5 text-muted">PDF or image · your extracted details can be reviewed before saving</p>
            </div>
            <button type="button" onClick={() => fileInputRef.current?.click()} disabled={busy} className="inline-flex h-9 shrink-0 items-center gap-2 rounded-lg border border-line bg-white px-3.5 text-xs font-semibold text-ink shadow-sm transition hover:border-violet-200 hover:bg-violet-light disabled:cursor-not-allowed disabled:opacity-50">
              <UploadCloud className="size-3.5 text-violet-dark" /> Browse files
            </button>
          </div>
        </div>
        {file && <div className="flex flex-wrap items-center gap-3 rounded-xl border border-violet-100 bg-violet-light/40 p-3">
          <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-white text-violet-dark"><FileText className="size-4" /></div>
          <div className="min-w-0 flex-1"><p className="truncate text-xs font-semibold text-ink">{file.name}</p><p className="text-[11px] text-muted">{file.size < 1024 * 1024 ? `${Math.max(1, Math.round(file.size / 1024))} KB` : `${(file.size / (1024 * 1024)).toFixed(1)} MB`}</p></div>
          <button type="button" onClick={() => { setFile(null); if (fileInputRef.current) fileInputRef.current.value = ''; }} disabled={busy} aria-label="Remove selected slip" className="grid size-8 place-items-center rounded-lg text-muted transition hover:bg-white hover:text-rose disabled:opacity-50"><X className="size-4" /></button>
        </div>}
        <div className="flex flex-wrap items-center gap-3">
          <button className="inline-flex min-h-10 items-center gap-2 rounded-lg border-2 border-stone-900 bg-stone-900 px-4 text-sm font-semibold text-white shadow-sm transition hover:border-black hover:bg-black focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-900 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:border-stone-300 disabled:bg-stone-100 disabled:text-stone-500 disabled:shadow-none" disabled={!file || busy}>{busy && <Loader2 className="size-3.5 animate-spin" />}{busy ? 'Reading slip…' : 'Extract details'}</button>
          {file && !busy && <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700"><Check className="size-3.5" /> Slip ready to extract</span>}
        </div>
      </form>
      {extractedText && <details className="mt-3 text-sm"><summary className="cursor-pointer font-semibold text-violet-dark">Show OCR text</summary><pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-paper p-3 text-xs">{extractedText}</pre></details>}
      {exams.map((exam, index) => <article key={`${exam.subject}-${index}`} className="mt-4 rounded-lg border border-line p-4"><div className="grid gap-3 sm:grid-cols-2">
        {[['subject','Subject'],['date','Date'],['time','Time'],['room','Room'],['seating_plan','Seating plan'],['instructions','Instructions']].map(([name,label]) => <label key={name} className="text-xs font-semibold text-muted">{label}<input className={`${field} mt-1`} type={name === 'date' ? 'date' : 'text'} value={exam[name]} onChange={(e) => updateExam(index,name,e.target.value)}/></label>)}
      </div><button className={`${button} mt-3`} onClick={() => saveExam(exam,index)}>Save exam</button></article>)}
    </div> : <div className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-semibold">Course topic index</h2><button className={button} onClick={processAll} disabled={busy || !materials.length}>{busy ? 'Processing…' : 'Process all materials'}</button></div>
      {progress && <p className="mt-3 text-sm text-violet-dark" aria-live="polite">{progress}</p>}
      {!materials.length ? <div className="mt-5 rounded-2xl border border-dashed border-line bg-paper/70 px-4 py-8 text-center"><div className="mx-auto grid size-10 place-items-center rounded-xl bg-white text-violet-dark shadow-sm"><FileText className="size-5" /></div><p className="mt-3 text-sm font-semibold text-ink">No course materials yet</p><p className="mx-auto mt-1 max-w-md text-xs leading-5 text-muted">Connect and sync Google Classroom or add materials in Study Assistant to see them grouped here.</p></div> : <div className="mt-4 space-y-3">{courseGroups.map((course) => { const complete = course.items.filter((item) => extracts[item.id]?.status === 'complete').length; const open = expandedCourse === course.id; return <section key={course.id} className={`overflow-hidden rounded-xl border transition-colors ${open ? 'border-violet-200 bg-white shadow-sm' : 'border-line bg-white hover:border-violet-200'}`}><button type="button" className={`flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left transition-colors ${open ? 'bg-violet-light/60' : 'bg-white hover:bg-paper/70'}`} aria-expanded={open} onClick={() => setExpandedCourse(open ? null : course.id)}><span className="min-w-0"><strong className="block truncate text-sm font-semibold text-ink">{course.label}</strong><small className="mt-0.5 block text-xs text-muted">{course.items.length} materials · {complete} indexed</small></span><span className="flex shrink-0 items-center gap-2 text-xs font-semibold text-violet-dark">{open ? 'Hide materials' : 'View materials'}<ChevronDown className={`size-4 transition-transform ${open ? 'rotate-180' : ''}`} /></span></button>{open && <div className="divide-y divide-line">{course.items.map((item) => { const data = extracts[item.id]; const materialStatus = data?.status === 'complete' ? 'Indexed' : data?.status === 'processing' ? 'Processing' : !isReady(item) ? `Waiting for RAG indexing${item.status ? ` (${item.status})` : ''}` : 'Not processed'; return <article key={item.id} className="px-4 py-3.5 sm:px-5"><div className="flex flex-wrap items-center justify-between gap-3"><div className="min-w-0"><h3 className="break-words text-sm font-semibold text-ink">{item.title || item.original_filename || 'Untitled material'}</h3><p className="mt-1 inline-flex items-center gap-1.5 text-xs text-muted"><span className={`size-1.5 rounded-full ${data?.status === 'complete' ? 'bg-emerald-500' : data?.status === 'processing' || !isReady(item) ? 'bg-amber-400' : 'bg-stone-300'}`} />{materialStatus}</p></div><div className="flex shrink-0 gap-2"><button className={button} onClick={() => setExpanded(expanded === item.id ? null : item.id)} disabled={!data?.content}>{expanded === item.id ? 'Hide' : 'Preview'}</button><button className={button} onClick={() => data?.content && copy(data.content)} disabled={!data?.content}>Copy</button></div></div>{expanded === item.id && data?.content && <pre className="mt-3 max-h-[520px] overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-paper p-4 text-xs leading-6 sm:text-sm">{data.content}</pre>}</article>; })}</div>}</section>; })}</div>}
    </div>}
  </section>;
}

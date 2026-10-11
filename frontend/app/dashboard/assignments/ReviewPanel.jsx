'use client';

import { useState } from 'react';
import Icon from '@/app/dashboard/Icon';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';

const STATUS_STYLE = {
  met: { label: 'Met', icon: 'check', className: 'border-brand-border bg-brand-bg text-brand-hover' },
  partial: { label: 'Partial', icon: 'alert', className: 'border-amber-border bg-amber-bg text-amber' },
  missing: { label: 'Missing', icon: 'close', className: 'border-rose-border bg-rose-bg text-rose' },
};

export default function ReviewPanel({ assignment }) {
  const { getToken } = useAuth();
  const [text, setText] = useState('');
  const [file, setFile] = useState(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const handleFile = (e) => {
    const f = e.target.files?.[0];
    if (f) setFile(f);
  };

  const runReview = async () => {
    if (!text.trim() && !file) return;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const token = getToken ? await getToken() : null;
      const data = await api.reviewDraft(assignment.id, { text, file }, token);
      setResult(data);
    } catch (e) {
      setError(e.message || 'Could not run rubric review right now.');
    } finally {
      setRunning(false);
    }
  };

  const cardClass = 'min-w-0 rounded-xl border border-line bg-white p-5 shadow-sm';
  const inputClass = 'w-full rounded-lg border border-line bg-paper px-3 py-2.5 text-sm leading-6 text-ink outline-none focus:border-violet focus:ring-2 focus:ring-violet/20';
  const headingClass = 'text-base font-semibold text-ink';

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
      <section className={`${cardClass} flex flex-col gap-5`}>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Pre-submission audit</p>
          <h3 className={`${headingClass} mt-1`}>Check draft against rubric</h3>
          <p className="mt-2 text-sm leading-6 text-muted">Paste your solution or attach your draft file. Uniflow checks requirements, logic completeness, and citations without modifying your submission.</p>
        </div>

        <label className="flex flex-col gap-2">
          <span className="flex items-center justify-between gap-3 text-sm font-medium text-ink"><span>Draft text / source</span><span className="text-xs text-muted">{text.length} characters</span></span>
          <textarea className={`${inputClass} min-h-60 resize-y font-mono`} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste your draft report, code, or essay here…" rows={10} />
        </label>

        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-paper px-4 py-3">
          <label className="inline-flex cursor-pointer items-center gap-2 text-sm font-semibold text-violet hover:text-violet-dark">
            <Icon name="paperclip" size={16}/>{file ? 'Change file' : 'Attach draft file'}
            <input type="file" className="sr-only" onChange={handleFile} accept=".pdf,.doc,.docx,.txt,.py,.js,.ts,.jsx,.tsx" />
          </label>
          {file && <div className="flex min-w-0 items-center gap-2"><span className="max-w-48 truncate text-sm text-ink">{file.name}</span><button type="button" onClick={() => setFile(null)} className="grid size-8 place-items-center rounded-md text-rose hover:bg-rose-bg" aria-label="Remove attached draft"><Icon name="close" size={14}/></button></div>}
        </div>

        {error && <div className="rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-sm text-rose" role="alert">{error}</div>}
        <button type="button" onClick={runReview} disabled={running || (!text.trim() && !file)} className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-50">
          {running ? 'Auditing draft against rubric…' : <><Icon name="search" size={16}/> Run pre-submission review</>}
        </button>
      </section>

      <div className="flex min-w-0 flex-col gap-4">
        {!result && !running && <div className={`${cardClass} flex min-h-64 flex-col items-center justify-center text-center`}>
          <span className="mb-3 grid size-11 place-items-center rounded-xl bg-violet-light text-violet"><Icon name="barChart" size={20}/></span>
          <strong className="text-base font-semibold text-ink">Rubric scorecard will appear here</strong>
          <p className="mt-2 max-w-sm text-sm leading-6 text-muted">Paste your writing or code to evaluate requirement coverage, rubric alignment, and academic citations.</p>
        </div>}

        {running && <div className={`${cardClass} flex min-h-64 flex-col items-center justify-center text-center`} role="status">
          <span className="mb-3 size-7 animate-spin rounded-full border-2 border-violet-light border-t-violet" />
          <strong className="text-base font-semibold text-ink">Evaluating your draft…</strong>
          <p className="mt-1 text-sm text-muted">Checking criteria fulfillment and citation validity.</p>
        </div>}

        {result && <>
          <section className="rounded-xl border border-violet/20 bg-violet-light/60 p-5">
            <header className="mb-2 flex items-center gap-2 text-sm font-semibold text-violet-dark"><Icon name="clipboardCheck" size={16}/> Auditor verdict</header>
            <p className="text-sm leading-6 text-ink">{result.summary}</p>
          </section>

          <section className="min-w-0 overflow-hidden rounded-xl border border-line bg-white shadow-sm">
            <header className="border-b border-line bg-paper px-5 py-4"><h3 className="text-sm font-semibold uppercase tracking-wide text-muted">Requirement coverage</h3></header>
            <div className="flex flex-col gap-3 p-4">
              {(result.requirement_coverage || []).map((r, idx) => {
                const s = STATUS_STYLE[r.status] || STATUS_STYLE.partial;
                return <div key={idx} className="flex items-start gap-3 rounded-lg border border-line bg-paper/70 p-3">
                  <span className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold ${s.className}`}><Icon name={s.icon} size={13}/>{s.label}</span>
                  <div className="min-w-0"><strong className="text-sm font-semibold text-ink">{r.requirement}</strong><p className="mt-1 text-sm leading-5 text-muted">{r.reason}</p></div>
                </div>;
              })}
            </div>
          </section>

          {result.issues?.length > 0 && <section className="rounded-xl border border-rose-border bg-white p-5">
            <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-rose"><Icon name="alert" size={16}/> Recommendations to revise</h3>
            <div className="flex flex-col gap-2">{result.issues.map((issue, idx) => <div key={idx} className="rounded-lg border border-rose-border/70 bg-rose-bg/50 p-3">
              <div className="mb-1 flex flex-wrap items-center justify-between gap-2"><strong className="text-sm font-semibold text-rose">{issue.type}</strong>{issue.location && <span className="font-mono text-xs text-muted">{issue.location}</span>}</div>
              <p className="text-sm leading-5 text-ink">{issue.description}</p>
            </div>)}</div>
          </section>}

          {result.citation_check?.length > 0 && <section className={`${cardClass} flex flex-col gap-3`}>
            <h3 className="text-sm font-semibold uppercase tracking-wide text-muted">Citation & attribution</h3>
            {result.citation_check.map((c, idx) => <div key={idx} className="rounded-lg border border-line bg-paper p-3">
              <p className="text-sm italic leading-6 text-ink">&ldquo;{c.excerpt}&rdquo;</p><span className="mt-1 block text-xs text-muted">{c.concern}</span>
            </div>)}
          </section>}
        </>}
      </div>
    </div>
  );
}

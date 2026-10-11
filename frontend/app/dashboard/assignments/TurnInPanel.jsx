'use client';

import { useEffect, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

/**
 * Turn-in tab: the student attaches the files THEY produced, picks a
 * cover/template if one applies, and submits to Google Classroom.
 */
export default function TurnInPanel({ assignment, onTurnIn }) {
  const { getToken } = useAuth();
  const [templates, setTemplates] = useState([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState(null);
  const [files, setFiles] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [unsubmitting, setUnsubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [submitted, setSubmitted] = useState(
    assignment.submission_state === 'TURNED_IN' || assignment.submission_state === 'RETURNED'
  );
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [scheduleMinutesBefore, setScheduleMinutesBefore] = useState(60);
  const [savingSchedule, setSavingSchedule] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const token = getToken ? await getToken() : null;
        const data = await api.getAssignmentTemplates(token);
        if (!cancelled) {
          setTemplates(data || []);
          const def = data?.find((t) => t.is_default);
          if (def) setSelectedTemplateId(def.id);
        }
      } catch (e) {
        console.error('Failed to load templates:', e);
      }
    })();
    return () => { cancelled = true; };
  }, [getToken]);

  const handleFileChange = (e) => {
    const picked = Array.from(e.target.files || []);
    setFiles((prev) => [
      ...prev,
      ...picked.map((f) => ({
        name: f.name,
        size: (f.size / 1024).toFixed(1) + ' KB',
        fileObj: f,
      })),
    ]);
  };

  const removeFile = (idx) => setFiles((prev) => prev.filter((_, i) => i !== idx));

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const token = getToken ? await getToken() : null;
      await onTurnIn(assignment.id, selectedTemplateId, files.map((f) => f.fileObj), token);
      setSubmitted(true);
      setNotice('Assignment turned in successfully to Google Classroom!');
    } catch (e) {
      setError(e.message || 'Turn-in failed. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleUnsubmit = async () => {
    setUnsubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const token = getToken ? await getToken() : null;
      await api.unsubmitAssignment(assignment.id, token);
      setSubmitted(false);
      setNotice('Assignment unsubmitted on Google Classroom. You can now add or edit your deliverable files and turn in again.');
    } catch (e) {
      setError(e.message || 'Could not unsubmit assignment on Google Classroom.');
    } finally {
      setUnsubmitting(false);
    }
  };

  const saveSchedule = async () => {
    setSavingSchedule(true);
    setError(null);
    setNotice(null);
    try {
      const token = getToken ? await getToken() : null;
      await api.scheduleTurnIn(
        assignment.id,
        {
          enabled: scheduleEnabled,
          minutes_before_due: scheduleMinutesBefore,
          template_id: selectedTemplateId,
        },
        token
      );
      setNotice('Auto turn-in schedule saved successfully.');
    } catch (e) {
      setError(e.message || 'Could not save turn-in schedule.');
    } finally {
      setSavingSchedule(false);
    }
  };

  const cardClass = 'min-w-0 rounded-xl border border-line bg-white p-5 shadow-sm';
  const fieldClass = 'w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm text-ink outline-none focus:border-violet focus:ring-2 focus:ring-violet/20';
  const secondaryButtonClass = 'inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-line bg-white px-4 text-sm font-semibold text-ink transition hover:bg-paper disabled:cursor-not-allowed disabled:opacity-50';

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-2">
      <section className={`${cardClass} flex flex-col gap-5`}>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Final submission</p>
          <h3 className="mt-1 text-base font-semibold text-ink">Submit to Google Classroom</h3>
          <p className="mt-2 text-sm leading-6 text-muted">Attach your completed coursework files and select a cover page template if required by your university.</p>
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-3"><span className="text-sm font-semibold text-ink">Attached deliverables</span><span className="text-sm text-muted">{files.length} {files.length === 1 ? 'file' : 'files'}</span></div>
          {files.length === 0 ? <div className="rounded-lg border border-dashed border-line bg-paper px-4 py-8 text-center"><strong className="block text-sm font-semibold">No files attached yet</strong><span className="mt-1 block text-sm text-muted">Attach your code, report, or document deliverables below.</span></div> : (
            <div className="flex max-h-48 flex-col gap-2 overflow-y-auto">
              {files.map((f, i) => <div key={i} className="flex min-w-0 items-center justify-between gap-3 rounded-lg border border-line bg-paper px-3 py-2">
                <div className="flex min-w-0 items-center gap-2"><Icon name="file" size={16}/><span className="truncate text-sm font-medium text-ink">{f.name}</span><span className="shrink-0 text-xs text-muted">({f.size})</span></div>
                <button type="button" onClick={() => removeFile(i)} className="grid size-8 shrink-0 place-items-center rounded-md text-muted hover:bg-rose-bg hover:text-rose" aria-label={`Remove ${f.name}`}><Icon name="close" size={14}/></button>
              </div>)}
            </div>
          )}
        </div>

        <label className={`${secondaryButtonClass} cursor-pointer`}>
          <span>+ Add deliverable files</span>
          <input className="sr-only" type="file" multiple onChange={handleFileChange} />
        </label>

        <label className="flex flex-col gap-2 text-sm font-medium text-ink">
          Cover page template
          <select className={fieldClass} value={selectedTemplateId || ''} onChange={(e) => setSelectedTemplateId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">No cover template (Submit raw files)</option>
            {templates.map((t) => <option key={t.id} value={t.id}>{t.name} {t.is_default ? '(Default)' : ''}</option>)}
          </select>
        </label>

        {error && <div className="rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-sm text-rose" role="alert">{error}</div>}
        {notice && <div className="rounded-lg border border-brand-border bg-brand-bg px-4 py-3 text-sm text-brand-hover" role="status">{notice}</div>}

        <button type="button" onClick={handleSubmit} disabled={submitting || unsubmitting || files.length === 0} className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-50">
          {submitting ? 'Submitting to Google Classroom…' : submitted && files.length > 0 ? <><Icon name="upload" size={16}/> Re-submit updated files to Classroom</> : submitted ? <><Icon name="checkCircle" size={16}/> Turned in to Classroom</> : <><Icon name="upload" size={16}/> Turn in to Google Classroom</>}
        </button>

        {submitted && <button type="button" onClick={handleUnsubmit} disabled={unsubmitting || submitting} className="inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-lg border border-rose-border bg-rose-bg px-4 text-sm font-semibold text-rose transition hover:bg-rose-bg/70 disabled:cursor-not-allowed disabled:opacity-50">
          <Icon name="refresh" size={16} className={unsubmitting ? 'animate-spin' : ''}/><span>{unsubmitting ? 'Unsubmitting on Classroom…' : 'Unsubmit / reclaim on Google Classroom'}</span>
        </button>}
        {assignment.url && <a href={assignment.url} target="_blank" rel="noreferrer" className="inline-flex items-center justify-center gap-1.5 text-sm font-semibold text-violet hover:text-violet-dark hover:underline">Open assignment in Google Classroom <Icon name="externalLink" size={14}/></a>}
      </section>

      <section className={`${cardClass} flex flex-col gap-5`}>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Automation</p>
          <h3 className="mt-1 text-base font-semibold text-ink">Scheduled auto turn-in</h3>
          <p className="mt-2 text-sm leading-6 text-muted">Attach your work now and schedule Uniflow to turn in automatically before the deadline so you never miss a submission window.</p>
        </div>

        <label className="flex cursor-pointer items-center justify-between gap-4 rounded-lg border border-line bg-paper p-4">
          <span><strong className="block text-sm font-semibold text-ink">Enable automatic submission</strong><small className="mt-1 block text-sm text-muted">Submits attached files automatically prior to due date</small></span>
          <input type="checkbox" checked={scheduleEnabled} onChange={(e) => setScheduleEnabled(e.target.checked)} className="size-5 shrink-0 accent-violet" />
        </label>

        <label className="flex flex-col gap-2 text-sm font-medium text-ink">
          Minutes before deadline
          <span className="flex flex-wrap items-center gap-3">
            <input type="number" min={5} max={1440} value={scheduleMinutesBefore} onChange={(e) => setScheduleMinutesBefore(parseInt(e.target.value, 10) || 60)} disabled={!scheduleEnabled} className={`${fieldClass} w-28 disabled:cursor-not-allowed disabled:bg-paper disabled:text-muted`} />
            <span className="text-sm font-normal text-muted">mins prior ({Math.round((scheduleMinutesBefore / 60) * 10) / 10} hours)</span>
          </span>
        </label>

        <button type="button" onClick={saveSchedule} disabled={files.length === 0 || savingSchedule} className={secondaryButtonClass}>
          {savingSchedule ? 'Saving schedule…' : <><Icon name="save" size={16}/> Save schedule settings</>}
        </button>
        {files.length === 0 && <p className="rounded-lg bg-amber-bg p-3 text-sm leading-5 text-amber">Attach at least one deliverable file on the left before activating auto turn-in.</p>}
      </section>
    </div>
  );
}

'use client';

import { useEffect, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';
import {
  isExtensionInstalled,
  syncGcrViaExtension,
  autoVisitAndSyncGcr,
  turnInViaExtension,
} from '@/app/lib/extensionBridge';

/**
 * Turn-in tab: supports both "Attach as Draft" and "Turn In to Classroom",
 * course automation policies (Manual vs Auto-Attach vs Auto-Turn-In), and manual file upload.
 */
export default function TurnInPanel({ assignment, onTurnIn, onStatusChange }) {
  const { getToken } = useAuth();
  const [templates, setTemplates] = useState([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState(null);
  const [files, setFiles] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [unsubmitting, setUnsubmitting] = useState(false);
  const [attachingDraft, setAttachingDraft] = useState(false);
  const [quickSubmitting, setQuickSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [submitted, setSubmitted] = useState(
    assignment.submission_state === 'TURNED_IN' || assignment.submission_state === 'RETURNED'
  );

  // Automation policy: 'manual' | 'attach_draft' | 'auto_turn_in'
  const [autoPolicy, setAutoPolicy] = useState('manual');
  const [deadlineProtection, setDeadlineProtection] = useState(false);
  const [scheduleMinutesBefore, setScheduleMinutesBefore] = useState(60);
  const [confirmAutoSubmission, setConfirmAutoSubmission] = useState(false);
  const [scheduleInfo, setScheduleInfo] = useState(null);
  const [savingSchedule, setSavingSchedule] = useState(false);

  // Companion Extension detection & sync
  const [extensionDetected, setExtensionDetected] = useState(false);
  const [hasSyncedSession, setHasSyncedSession] = useState(false);
  const [syncingViaExtension, setSyncingViaExtension] = useState(false);
  const [autoVisitingGcr, setAutoVisitingGcr] = useState(false);
  const [showExtensionHelp, setShowExtensionHelp] = useState(false);

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

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const token = getToken ? await getToken() : null;
        if (assignment.course_id) {
          const autoData = await api.getCourseAutoTurnIn(assignment.course_id, token);
          if (!cancelled && autoData) {
            setScheduleInfo(autoData);
            setDeadlineProtection(Boolean(autoData.enabled));
            setScheduleMinutesBefore(autoData.minutes_before || 60);
            if (autoData.submit_when_ready) {
              setAutoPolicy('auto_turn_in');
              setConfirmAutoSubmission(true);
            } else if (autoData.attach_when_ready) {
              setAutoPolicy('attach_draft');
            } else {
              setAutoPolicy('manual');
            }
          }
        }
      } catch (e) {
        console.error('Failed to load course auto turn-in:', e);
      }
    })();
    return () => { cancelled = true; };
  }, [assignment.course_id, getToken]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const token = getToken ? await getToken() : null;
        const state = await api.getClassroomBrowserStatus(token);
        if (!cancelled) {
          setHasSyncedSession(Boolean(state?.has_synced_session));
        }
      } catch (e) {
        console.error('Failed to load Google Classroom status:', e);
      }
    })();
    return () => { cancelled = true; };
  }, [getToken]);

  useEffect(() => {
    setExtensionDetected(isExtensionInstalled());
    const onReady = () => setExtensionDetected(true);
    window.addEventListener('uniflow-companion-ready', onReady);
    const interval = setInterval(() => {
      if (isExtensionInstalled()) {
        setExtensionDetected(true);
        clearInterval(interval);
      }
    }, 1000);
    return () => {
      window.removeEventListener('uniflow-companion-ready', onReady);
      clearInterval(interval);
    };
  }, []);

  const handleSyncViaExtension = async () => {
    if (syncingViaExtension) return;
    setSyncingViaExtension(true);
    setError(null);
    setNotice(null);
    try {
      const token = getToken ? await getToken() : null;
      const res = await syncGcrViaExtension({ token });
      setHasSyncedSession(true);
      setNotice(res?.message || 'Google Classroom session synced from your Chrome profile!');
    } catch (e) {
      setError(e.message || 'Extension sync failed. Ensure you are signed into classroom.google.com in this Chrome profile.');
    } finally {
      setSyncingViaExtension(false);
    }
  };

  const handleAutoVisitGcr = async () => {
    if (autoVisitingGcr) return;
    setAutoVisitingGcr(true);
    setError(null);
    setNotice('Opening Google Classroom in a tab to capture session cookies…');
    try {
      const token = getToken ? await getToken() : null;
      const res = await autoVisitAndSyncGcr({ token });
      setHasSyncedSession(true);
      setNotice('✅ ' + (res?.message || 'Google Classroom session captured!'));
    } catch (e) {
      setError(e.message || 'Could not auto-capture Classroom session.');
    } finally {
      setAutoVisitingGcr(false);
    }
  };

  const handleAttachDraft = async () => {
    setAttachingDraft(true);
    setError(null);
    setNotice(null);
    try {
      const token = getToken ? await getToken() : null;
      const res = await api.quickTurnInAssignment(assignment.id, token, 'attach_only');
      setNotice(res.message || 'Deliverables (Google Doc + Code ZIP) successfully attached to Google Classroom as a draft!');
      if (onStatusChange) onStatusChange();
    } catch (e) {
      setError(e.message || 'Failed to attach draft deliverables to Google Classroom.');
    } finally {
      setAttachingDraft(false);
    }
  };

  const handleQuickTurnIn = async () => {
    if (!window.confirm(`Turn in "${assignment.title}" to Google Classroom now? Uniflow will attach deliverables (Doc + ZIP) and complete submission.`)) return;
    setQuickSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const token = getToken ? await getToken() : null;
      const res = await api.quickTurnInAssignment(assignment.id, token, 'turn_in');
      if (res.action_required === 'extension_turn_in' && res.classroom_url) {
        if (isExtensionInstalled()) {
          setNotice('Files attached! Completing turn-in via Uniflow Companion Extension in your Chrome profile…');
          try {
            const extRes = await turnInViaExtension({
              classroomUrl: res.classroom_url,
              assignmentId: assignment.id,
              token,
            });
            if (extRes?.success) {
              setSubmitted(true);
              setNotice('✅ Successfully turned in deliverables to Google Classroom via Companion Extension!');
              if (onStatusChange) onStatusChange();
              return;
            }
          } catch (extErr) {
            console.warn('Extension turn in attempt failed:', extErr);
          }
        }
        setNotice('Deliverables attached to Google Classroom! Open assignment in Classroom to complete submission.');
        return;
      }
      setSubmitted(Boolean(res.turned_in));
      setNotice(res.message || 'Successfully turned in Google Doc and ZIP deliverables to Google Classroom!');
      if (onStatusChange) onStatusChange();
    } catch (e) {
      setError(e.message || 'Quick turn-in failed. Please try again.');
    } finally {
      setQuickSubmitting(false);
    }
  };

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

  const handleSubmitCustomFiles = async () => {
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const token = getToken ? await getToken() : null;
      await onTurnIn(assignment.id, selectedTemplateId, files.map((f) => f.fileObj), token);
      setSubmitted(true);
      setNotice('Assignment turned in successfully to Google Classroom!');
      if (onStatusChange) onStatusChange();
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
      setNotice('Assignment unsubmitted on Google Classroom. You can now edit deliverables and turn in again.');
      if (onStatusChange) onStatusChange();
    } catch (e) {
      setError(e.message || 'Could not unsubmit assignment on Google Classroom.');
    } finally {
      setUnsubmitting(false);
    }
  };

  const saveAutomationPolicy = async () => {
    if (autoPolicy === 'auto_turn_in' && !confirmAutoSubmission) {
      setError('Please check the confirmation box to authorize automatic submissions for this course.');
      return;
    }
    setSavingSchedule(true);
    setError(null);
    setNotice(null);
    try {
      const token = getToken ? await getToken() : null;
      if (assignment.course_id) {
        const res = await api.updateCourseAutoTurnIn(
          assignment.course_id,
          {
            enabled: Boolean(deadlineProtection),
            submit_when_ready: autoPolicy === 'auto_turn_in',
            attach_when_ready: autoPolicy === 'attach_draft',
            minutes_before: scheduleMinutesBefore,
            confirm_submission: autoPolicy !== 'manual' || deadlineProtection,
          },
          token
        );
        setScheduleInfo(res);
        setNotice(res.message || `Automation policy for ${assignment.course_name || 'this course'} saved successfully.`);
      }
    } catch (e) {
      setError(e.message || 'Could not save automation policy.');
    } finally {
      setSavingSchedule(false);
    }
  };

  const cardClass = 'min-w-0 rounded-xl border border-line bg-white p-5 shadow-sm';
  const fieldClass = 'w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm text-ink outline-none focus:border-violet focus:ring-2 focus:ring-violet/20';
  const secondaryButtonClass = 'inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-line bg-white px-4 text-sm font-semibold text-ink transition hover:bg-paper disabled:cursor-not-allowed disabled:opacity-50';

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-2">
      {/* LEFT COLUMN: Actions & Classroom Delivery */}
      <section className={`${cardClass} flex flex-col gap-5`}>
        {/* 1. Deliverables Submission Options (Draft vs Turn In) */}
        <div className="rounded-xl border border-indigo-200 bg-indigo-50/50 p-4">
          <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-indigo-900">
            <Icon name="sparkles" size={14} />
            <span>Classroom Submission Actions</span>
          </div>
          <h4 className="mt-1 text-sm font-semibold text-slate-900">Choose Delivery Mode for Google Classroom</h4>
          <p className="mt-1 text-xs text-slate-600 leading-relaxed">
            Attach the solution Google Doc & deliverable code files (.zip) directly to your Google Classroom coursework.
          </p>

          <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
            {/* Option 1: Attach as Draft */}
            <div className="flex flex-col justify-between rounded-lg border border-indigo-200 bg-white p-3 shadow-xs">
              <div>
                <div className="flex items-center gap-1.5 text-xs font-bold text-indigo-700">
                  <Icon name="paperclip" size={14} />
                  <span>Attach as Draft</span>
                </div>
                <p className="mt-1 text-[11px] text-muted leading-relaxed">
                  Uploads Google Doc & ZIP files to Classroom without submitting. You can review and turn in later.
                </p>
              </div>
              <button
                type="button"
                onClick={handleAttachDraft}
                disabled={attachingDraft || quickSubmitting}
                className="mt-3 inline-flex min-h-9 w-full items-center justify-center gap-1.5 rounded-lg border border-indigo-300 bg-indigo-50 px-3 text-xs font-semibold text-indigo-800 transition hover:bg-indigo-100 disabled:opacity-50"
              >
                <Icon name="paperclip" size={13} />
                <span>{attachingDraft ? 'Attaching…' : 'Attach Files (Draft)'}</span>
              </button>
            </div>

            {/* Option 2: Turn In Immediately */}
            <div className="flex flex-col justify-between rounded-lg border border-emerald-200 bg-white p-3 shadow-xs">
              <div>
                <div className="flex items-center gap-1.5 text-xs font-bold text-emerald-700">
                  <Icon name="upload" size={14} />
                  <span>Turn In to Classroom</span>
                </div>
                <p className="mt-1 text-[11px] text-muted leading-relaxed">
                  Attaches deliverables and completes submission to Google Classroom via the Companion Extension.
                </p>
              </div>
              <button
                type="button"
                onClick={handleQuickTurnIn}
                disabled={quickSubmitting || attachingDraft || submitted}
                className="mt-3 inline-flex min-h-9 w-full items-center justify-center gap-1.5 rounded-lg bg-emerald-600 px-3 text-xs font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-50"
              >
                <Icon name="upload" size={13} />
                <span>{quickSubmitting ? 'Submitting…' : submitted ? 'Turned In' : '⚡ Turn In (Submit)'}</span>
              </button>
            </div>
          </div>

          {/* Extension Status / Sync Card */}
          <div className="mt-3 rounded-lg border border-slate-200 bg-white p-3 text-xs flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1.5 font-semibold text-slate-800">
                <Icon name="globe" size={13} />
                <span>Uniflow Companion Extension</span>
              </div>
              {extensionDetected ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-800">
                  <span className="size-1.5 rounded-full bg-emerald-600 animate-pulse" /> Active in Chrome
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => setShowExtensionHelp(true)}
                  className="text-[11px] font-semibold text-violet underline hover:text-violet-dark"
                >
                  Download Extension
                </button>
              )}
            </div>
            <p className="text-[11px] text-muted leading-relaxed">
              {extensionDetected
                ? 'Your Companion Extension is loaded in this Chrome browser. It handles Google Classroom turn-in natively with your authentic login session.'
                : 'Load the Companion Extension in Chrome to enable 1-click turn-in and session sync without password prompts.'}
            </p>
            {!extensionDetected && (
              <div className="mt-1">
                <a
                  href="/uniflow-companion.zip"
                  download="uniflow-companion.zip"
                  className="inline-flex items-center gap-1.5 rounded-lg bg-violet px-3 py-1.5 text-xs font-semibold text-white shadow-xs hover:bg-violet-dark transition"
                >
                  <Icon name="download" size={13} />
                  <span>📥 Download Companion Extension (.zip)</span>
                </a>
              </div>
            )}
          </div>
        </div>

        {/* 2. Manual Custom Files Submission */}
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Manual file attachments</p>
          <h3 className="mt-1 text-base font-semibold text-ink">Submit Custom Files to Google Classroom</h3>
          <p className="mt-2 text-sm leading-6 text-muted">Attach custom files and select a cover page template if required by your university.</p>
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm font-semibold text-ink">Attached custom deliverables</span>
            <span className="text-sm text-muted">{files.length} {files.length === 1 ? 'file' : 'files'}</span>
          </div>
          {files.length === 0 ? (
            <div className="rounded-lg border border-dashed border-line bg-paper px-4 py-6 text-center">
              <strong className="block text-sm font-semibold">No custom files attached</strong>
              <span className="mt-1 block text-xs text-muted">Use the deliverable buttons above or attach manual files here.</span>
            </div>
          ) : (
            <div className="flex max-h-48 flex-col gap-2 overflow-y-auto">
              {files.map((f, i) => (
                <div key={i} className="flex min-w-0 items-center justify-between gap-3 rounded-lg border border-line bg-paper px-3 py-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <Icon name="file" size={16} />
                    <span className="truncate text-sm font-medium text-ink">{f.name}</span>
                    <span className="shrink-0 text-xs text-muted">({f.size})</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeFile(i)}
                    className="grid size-8 shrink-0 place-items-center rounded-md text-muted hover:bg-rose-bg hover:text-rose"
                    aria-label={`Remove ${f.name}`}
                  >
                    <Icon name="close" size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <label className={`${secondaryButtonClass} cursor-pointer`}>
          <span>+ Add custom deliverable files</span>
          <input className="sr-only" type="file" multiple onChange={handleFileChange} />
        </label>

        <label className="flex flex-col gap-2 text-sm font-medium text-ink">
          Cover page template
          <select
            className={fieldClass}
            value={selectedTemplateId || ''}
            onChange={(e) => setSelectedTemplateId(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">No cover template (Submit raw files)</option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>{t.name} {t.is_default ? '(Default)' : ''}</option>
            ))}
          </select>
        </label>

        {error && <div className="rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-sm text-rose" role="alert">{error}</div>}
        {notice && <div className="rounded-lg border border-brand-border bg-brand-bg px-4 py-3 text-sm text-brand-hover" role="status">{notice}</div>}

        <button
          type="button"
          onClick={handleSubmitCustomFiles}
          disabled={submitting || unsubmitting || files.length === 0}
          className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting ? 'Submitting custom files…' : submitted && files.length > 0 ? (
            <><Icon name="upload" size={16} /> Re-submit updated files to Classroom</>
          ) : submitted ? (
            <><Icon name="checkCircle" size={16} /> Turned in to Classroom</>
          ) : (
            <><Icon name="upload" size={16} /> Turn in custom files to Google Classroom</>
          )}
        </button>

        {submitted && (
          <button
            type="button"
            onClick={handleUnsubmit}
            disabled={unsubmitting || submitting}
            className="inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-lg border border-rose-border bg-rose-bg px-4 text-sm font-semibold text-rose transition hover:bg-rose-bg/70 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Icon name="refresh" size={16} className={unsubmitting ? 'animate-spin' : ''} />
            <span>{unsubmitting ? 'Unsubmitting on Classroom…' : 'Unsubmit / reclaim on Google Classroom'}</span>
          </button>
        )}

        {assignment.url && (
          <a
            href={assignment.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center justify-center gap-1.5 text-sm font-semibold text-violet hover:text-violet-dark hover:underline"
          >
            Open assignment in Google Classroom <Icon name="externalLink" size={14} />
          </a>
        )}
      </section>

      {/* RIGHT COLUMN: Course Automation Policy */}
      <section className={`${cardClass} flex flex-col gap-5`}>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Course Automation Controls</p>
          <h3 className="mt-1 text-base font-semibold text-ink">Automation Policy for {assignment.course_name || 'this course'}</h3>
          <p className="mt-2 text-sm leading-6 text-muted">
            Configure how Claude-generated solutions for <strong>{assignment.course_name || 'this course'}</strong> are handled upon generation. Uniflow will <strong>never</strong> automatically turn in assignments unless explicitly allowed below.
          </p>
        </div>

        {/* Radio Option 1: Manual Only */}
        <label
          className={`flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition ${
            autoPolicy === 'manual' ? 'border-violet bg-violet-light/20 ring-1 ring-violet' : 'border-line bg-paper hover:border-slate-300'
          }`}
        >
          <input
            type="radio"
            name="autoPolicy"
            value="manual"
            checked={autoPolicy === 'manual'}
            onChange={() => setAutoPolicy('manual')}
            className="mt-1 size-4 accent-violet"
          />
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <strong className="text-sm font-semibold text-ink">Manual Submission Only (Default)</strong>
              <span className="rounded bg-slate-100 px-2 py-0.5 text-[10px] font-bold text-slate-600">Safe</span>
            </div>
            <p className="mt-1 text-xs text-muted leading-relaxed">
              Never automatically attach or submit deliverables. You have 100% manual control over when and what gets sent to Classroom.
            </p>
          </div>
        </label>

        {/* Radio Option 2: Auto-Attach Draft */}
        <label
          className={`flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition ${
            autoPolicy === 'attach_draft' ? 'border-indigo-500 bg-indigo-50/40 ring-1 ring-indigo-500' : 'border-line bg-paper hover:border-slate-300'
          }`}
        >
          <input
            type="radio"
            name="autoPolicy"
            value="attach_draft"
            checked={autoPolicy === 'attach_draft'}
            onChange={() => setAutoPolicy('attach_draft')}
            className="mt-1 size-4 accent-indigo-600"
          />
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <strong className="text-sm font-semibold text-ink">Auto-Attach as Draft when Ready</strong>
              <span className="rounded bg-indigo-100 px-2 py-0.5 text-[10px] font-bold text-indigo-700">Draft Only</span>
            </div>
            <p className="mt-1 text-xs text-muted leading-relaxed">
              When Claude finishes generating a solution, automatically attach the Google Doc and code ZIP to Classroom coursework as a draft, but <strong>do not turn in</strong>.
            </p>
          </div>
        </label>

        {/* Radio Option 3: Auto-Turn In */}
        <label
          className={`flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition ${
            autoPolicy === 'auto_turn_in' ? 'border-emerald-500 bg-emerald-50/40 ring-1 ring-emerald-500' : 'border-line bg-paper hover:border-slate-300'
          }`}
        >
          <input
            type="radio"
            name="autoPolicy"
            value="auto_turn_in"
            checked={autoPolicy === 'auto_turn_in'}
            onChange={() => setAutoPolicy('auto_turn_in')}
            className="mt-1 size-4 accent-emerald-600"
          />
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <strong className="text-sm font-semibold text-ink">Auto-Turn In when Ready</strong>
              <span className="rounded bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-800">Autonomous</span>
            </div>
            <p className="mt-1 text-xs text-muted leading-relaxed">
              When Claude finishes generating a validated solution, automatically attach deliverables and complete submission on Google Classroom.
            </p>
          </div>
        </label>

        {/* Explicit Confirmation Checkbox for Auto-Turn In */}
        {autoPolicy === 'auto_turn_in' && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-3.5">
            <label className="flex cursor-pointer items-start gap-3">
              <input
                type="checkbox"
                checked={confirmAutoSubmission}
                onChange={(e) => setConfirmAutoSubmission(e.target.checked)}
                className="mt-0.5 size-4 accent-amber-600"
              />
              <span className="text-xs font-semibold text-amber-950 leading-relaxed">
                I explicitly authorize Uniflow to turn in completed solutions on my behalf for {assignment.course_name || 'this course'}.
              </span>
            </label>
          </div>
        )}

        {/* Deadline Protection Setting */}
        <div className="rounded-lg border border-line bg-paper p-4">
          <label className="flex cursor-pointer items-center justify-between gap-4">
            <div>
              <strong className="block text-sm font-semibold text-ink">Deadline Submission Guard</strong>
              <small className="mt-0.5 block text-xs text-muted">
                Automatically submit eligible solutions prior to the Google Classroom deadline.
              </small>
            </div>
            <input
              type="checkbox"
              checked={deadlineProtection}
              onChange={(e) => setDeadlineProtection(e.target.checked)}
              className="size-5 shrink-0 accent-violet"
            />
          </label>

          {deadlineProtection && (
            <div className="mt-3 pt-3 border-t border-line flex items-center gap-3">
              <span className="text-xs text-ink font-medium">Minutes before deadline:</span>
              <input
                type="number"
                min={5}
                max={1440}
                value={scheduleMinutesBefore}
                onChange={(e) => setScheduleMinutesBefore(parseInt(e.target.value, 10) || 60)}
                className={`${fieldClass} w-24`}
              />
              <span className="text-xs text-muted">({Math.round((scheduleMinutesBefore / 60) * 10) / 10} hours)</span>
            </div>
          )}
        </div>

        <button
          type="button"
          onClick={saveAutomationPolicy}
          disabled={savingSchedule}
          className={secondaryButtonClass}
        >
          {savingSchedule ? 'Saving policy…' : <><Icon name="save" size={16} /> Save course automation policy</>}
        </button>

        {scheduleInfo && (
          <p className="text-xs text-muted">
            Last result: {scheduleInfo.last_result?.status || 'No automatic submissions yet'}
            {scheduleInfo.last_run ? ` · ${new Date(scheduleInfo.last_run).toLocaleString()}` : ''}
          </p>
        )}
      </section>

      {/* Extension Installation Help Modal */}
      {showExtensionHelp && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl border border-line">
            <div className="flex items-center justify-between border-b border-line pb-3">
              <div className="flex items-center gap-2">
                <span className="grid size-7 place-items-center rounded-lg bg-violet-light text-violet font-bold text-xs">U</span>
                <h3 className="text-sm font-semibold text-ink">Load Uniflow Companion Extension</h3>
              </div>
              <button
                type="button"
                onClick={() => setShowExtensionHelp(false)}
                className="text-muted hover:text-ink text-sm font-bold"
              >
                ✕
              </button>
            </div>
            <div className="mt-3 space-y-3 text-xs text-muted leading-relaxed">
              <div className="rounded-lg border border-violet/20 bg-violet-light/30 p-3">
                <strong className="text-violet-dark block font-semibold text-xs mb-1">Fast 2-Step Setup (100% Free)</strong>
                <p className="text-[11px] text-muted mb-2.5">Download the companion extension package and load it once into your Chrome browser:</p>
                <a
                  href="/uniflow-companion.zip"
                  download="uniflow-companion.zip"
                  className="inline-flex items-center gap-1.5 rounded-lg bg-violet px-3 py-1.5 text-xs font-semibold text-white shadow-xs hover:bg-violet-dark transition"
                >
                  <Icon name="download" size={13} />
                  <span>📥 Download Extension (.zip)</span>
                </a>
              </div>

              <div className="rounded-lg border border-line bg-paper p-3">
                <strong className="text-ink block font-semibold text-xs mb-1">How to load in Chrome (15 seconds):</strong>
                <ol className="list-decimal pl-4 space-y-1 text-[11px] text-muted">
                  <li>Unzip the downloaded <code className="rounded bg-white px-1 py-0.5 text-ink font-mono border border-line">uniflow-companion.zip</code> file.</li>
                  <li>In Chrome, navigate to <code className="rounded bg-white px-1 py-0.5 text-ink font-mono border border-line">chrome://extensions</code></li>
                  <li>Turn ON <strong>Developer mode</strong> (toggle in top-right corner).</li>
                  <li>Click <strong>Load unpacked</strong> and select the unzipped folder.</li>
                </ol>
              </div>

              <p className="rounded-lg bg-emerald-50 border border-emerald-200 p-2 text-emerald-800 text-[11px]">
                ✨ <strong>Instant detection:</strong> Once loaded, Uniflow detects it immediately!
              </p>
            </div>
            <div className="mt-4 flex justify-end">
              <button
                type="button"
                onClick={() => setShowExtensionHelp(false)}
                className="rounded-lg border border-line bg-white px-4 py-1.5 text-xs font-semibold text-ink hover:bg-paper"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

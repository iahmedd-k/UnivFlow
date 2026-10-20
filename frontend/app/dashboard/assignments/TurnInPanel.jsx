'use client';

import { useEffect, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';
import HostedBrowserDialog from './HostedBrowserDialog';
import { isExtensionInstalled, syncGcrViaExtension, autoVisitAndSyncGcr } from '@/app/lib/extensionBridge';

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
  const [submitWhenReady, setSubmitWhenReady] = useState(false);
  const [scheduleMinutesBefore, setScheduleMinutesBefore] = useState(60);
  const [scheduleInfo, setScheduleInfo] = useState(null);
  const [savingSchedule, setSavingSchedule] = useState(false);

  const [quickSubmitting, setQuickSubmitting] = useState(false);
  const [classroomBrowserBusy, setClassroomBrowserBusy] = useState(false);
  const [classroomViewerUrl, setClassroomViewerUrl] = useState('');
  const [classroomProfileExists, setClassroomProfileExists] = useState(false);
  const [hasSyncedSession, setHasSyncedSession] = useState(false);

  // Companion Extension detection & consent
  const [extensionDetected, setExtensionDetected] = useState(false);
  const [syncingViaExtension, setSyncingViaExtension] = useState(false);
  const [autoVisitingGcr, setAutoVisitingGcr] = useState(false);
  const [showExtensionHelp, setShowExtensionHelp] = useState(false);
  const [consentGranted, setConsentGranted] = useState(true);

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
            setScheduleEnabled(Boolean(autoData.enabled));
            setSubmitWhenReady(Boolean(autoData.submit_when_ready));
            setScheduleMinutesBefore(autoData.minutes_before || 60);
            setScheduleInfo(autoData);
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
          setClassroomProfileExists(Boolean(state?.profile_exists));
          setHasSyncedSession(Boolean(state?.has_synced_session));
        }
      } catch (e) {
        console.error('Failed to load Google Classroom browser status:', e);
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

  const handleSyncViaExtension = async (autoRetryTurnIn = true) => {
    if (syncingViaExtension) return;
    setSyncingViaExtension(true);
    setError(null);
    setNotice(null);
    try {
      const token = getToken ? await getToken() : null;
      const res = await syncGcrViaExtension({ token });
      setHasSyncedSession(true);
      if (autoRetryTurnIn) {
        setNotice('✅ Session synced from your Chrome profile! Submitting deliverables to Google Classroom…');
        const retryRes = await api.quickTurnInAssignment(assignment.id, token);
        if (retryRes.needs_browser_login) {
          setError('Google Classroom session requires a fresh login. Please click "Open Classroom & Capture".');
        } else {
          setSubmitted(Boolean(retryRes.turned_in));
          setNotice(retryRes.message || 'Successfully turned in Google Doc and ZIP deliverables to Google Classroom!');
        }
      } else {
        setNotice(res?.message || 'Google Classroom session synced from your Chrome profile!');
      }
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
      setNotice('✅ ' + (res?.message || 'Google Classroom session captured! You can now Quick Turn In.'));
    } catch (e) {
      setError(e.message || 'Could not auto-capture Classroom session.');
    } finally {
      setAutoVisitingGcr(false);
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

  const handleQuickTurnIn = async () => {
    if (!window.confirm(`Submit "${assignment.title}" to Google Classroom now? Uniflow will attach the Google Doc and a ZIP of deliverables.`)) return;
    setQuickSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const token = getToken ? await getToken() : null;
      const res = await api.quickTurnInAssignment(assignment.id, token);
      if (res.needs_browser_login) {
        setClassroomViewerUrl(res.viewer_url || '');
        setNotice(res.message || 'Sign in to Google Classroom in your private browser, then retry Quick Turn In.');
        return;
      }
      setSubmitted(Boolean(res.turned_in));
      setNotice(res.message || 'Successfully turned in Google Doc and ZIP deliverables to Google Classroom!');
    } catch (e) {
      setError(e.message || 'Quick turn-in failed. Please try again.');
    } finally {
      setQuickSubmitting(false);
    }
  };

  const connectClassroomBrowser = async () => {
    if (classroomBrowserBusy) return;
    setClassroomBrowserBusy(true);
    setError(null);
    setNotice(null);
    try {
      const token = getToken ? await getToken() : null;
      const result = await api.openClassroomBrowser(token);
      setClassroomViewerUrl(result.viewer_url || '');
      setClassroomProfileExists(Boolean(result.profile_exists));
      setNotice('Your private Google Classroom browser is ready. Sign in there with the same Google account connected to Uniflow. The profile will be saved for future turn-ins.');
    } catch (e) {
      setError(e.message || 'Could not start your private Google Classroom browser.');
    } finally {
      setClassroomBrowserBusy(false);
    }
  };

  const forgetClassroomBrowser = async () => {
    if (!window.confirm('Delete your saved Google Classroom browser session? You will need to sign in again before browser-based turn-in.')) return;
    setClassroomBrowserBusy(true);
    setError(null);
    setNotice(null);
    try {
      const token = getToken ? await getToken() : null;
      await api.deleteClassroomBrowserProfile(token);
      setClassroomProfileExists(false);
      setClassroomViewerUrl('');
      setNotice('Saved Google Classroom browser session deleted.');
    } catch (e) {
      setError(e.message || 'Could not delete the saved Google Classroom browser session.');
    } finally {
      setClassroomBrowserBusy(false);
    }
  };

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
    const enabledActions = [];
    if (submitWhenReady) enabledActions.push('submit a validated Claude report as soon as generation finishes');
    if (scheduleEnabled) enabledActions.push(`submit eligible reports within ${scheduleMinutesBefore} minutes of the deadline`);
    if (enabledActions.length && !window.confirm(`Enable automatic submission for ${assignment.course_name || 'this course'}? Uniflow will ${enabledActions.join(' and ')}.`)) return;
    setSavingSchedule(true);
    setError(null);
    setNotice(null);
    try {
      const token = getToken ? await getToken() : null;
      if (assignment.course_id) {
        const res = await api.updateCourseAutoTurnIn(
          assignment.course_id,
          {
            enabled: scheduleEnabled,
            submit_when_ready: submitWhenReady,
            minutes_before: scheduleMinutesBefore,
            confirm_submission: scheduleEnabled,
          },
          token
        );
        setScheduleInfo(res);
        setNotice(res.message || `Auto turn-in for ${assignment.course_name || 'this course'} saved successfully.`);
      } else {
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
      }
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
        <div className="rounded-xl border border-emerald-200 bg-emerald-50/70 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-emerald-800">
                <Icon name="sparkles" size={14} />
                <span>Instant Autonomous Turn-In</span>
              </div>
              <h4 className="mt-1 text-sm font-semibold text-emerald-950">Quick Turn In (Google Doc + ZIP)</h4>
              <p className="mt-1 text-xs text-emerald-800 leading-relaxed">
                Automatically attaches the generated solution Google Doc (with centered university intro page), packages code files & terminal outputs into a ZIP archive, and submits both directly to Google Classroom in one click.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleQuickTurnIn}
            disabled={quickSubmitting || submitted}
            className="mt-3 inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 text-sm font-semibold text-white transition hover:bg-emerald-700 shadow-sm disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Icon name="upload" size={16} />
            <span>{quickSubmitting ? 'Submitting Doc & ZIP to GCR…' : submitted ? 'Turned in to Google Classroom' : '⚡ Quick Turn In (Doc + ZIP)'}</span>
          </button>
          {hasSyncedSession && (
            <div className="mt-2 flex items-center justify-between gap-1.5 rounded-md border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-xs text-emerald-800">
              <div className="flex items-center gap-1.5">
                <Icon name="checkCircle" size={13} className="text-emerald-600 shrink-0" />
                <span className="font-medium">Background Classroom Session Active</span>
              </div>
              {extensionDetected && (
                <button
                  type="button"
                  onClick={() => handleSyncViaExtension(false)}
                  disabled={syncingViaExtension}
                  className="text-[11px] font-semibold text-emerald-700 underline hover:text-emerald-900"
                >
                  {syncingViaExtension ? 'Refreshing…' : 'Refresh from Profile'}
                </button>
              )}
            </div>
          )}

          {/* Extension Consent & 1-Click Sync Card */}
          {!hasSyncedSession && (
            <div className="mt-3 rounded-lg border border-violet/30 bg-violet-light/30 p-3 text-xs flex flex-col gap-2">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 font-semibold text-violet-dark">
                  <Icon name="sparkles" size={13} />
                  <span>Google Classroom Session Required</span>
                </div>
                {extensionDetected ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-800">
                    <span className="size-1.5 rounded-full bg-emerald-600 animate-pulse" /> Extension Detected
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => setShowExtensionHelp(true)}
                    className="text-[11px] font-semibold text-violet underline hover:text-violet-dark"
                  >
                    Install Extension?
                  </button>
                )}
              </div>
              <p className="text-[11px] text-muted leading-relaxed">
                {extensionDetected
                  ? 'Your Uniflow Companion Extension is ready in this Chrome profile. Authorize Uniflow to sync your active university Google Classroom session for automated turn-in.'
                  : 'To enable autonomous turn-ins, sync your Classroom session via the companion extension or sign in via our secure private browser.'}
              </p>

              {extensionDetected ? (
                <div className="flex flex-col sm:flex-row gap-2 mt-1">
                  <button
                    type="button"
                    onClick={() => handleSyncViaExtension(true)}
                    disabled={syncingViaExtension}
                    className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-violet px-3 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-violet-dark disabled:opacity-50"
                  >
                    <Icon name="upload" size={13} />
                    <span>{syncingViaExtension ? 'Syncing from Chrome Profile…' : '⚡ 1-Click Allow & Sync Session'}</span>
                  </button>
                  <button
                    type="button"
                    onClick={handleAutoVisitGcr}
                    disabled={autoVisitingGcr}
                    className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-line bg-white px-3 py-2 text-xs font-semibold text-ink transition hover:bg-paper disabled:opacity-50"
                  >
                    <Icon name="externalLink" size={13} />
                    <span>{autoVisitingGcr ? 'Opening Classroom…' : '🌐 Open Classroom & Capture'}</span>
                  </button>
                </div>
              ) : (
                <div className="flex flex-col sm:flex-row gap-2 mt-1">
                  <button
                    type="button"
                    onClick={() => setShowExtensionHelp(true)}
                    className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-violet/30 bg-white px-3 py-2 text-xs font-semibold text-violet transition hover:bg-violet-light/50"
                  >
                    <Icon name="download" size={13} />
                    <span>Setup Companion Extension (1-Click Sync)</span>
                  </button>
                </div>
              )}
            </div>
          )}

          <button
            type="button"
            onClick={connectClassroomBrowser}
            disabled={classroomBrowserBusy}
            className={`${secondaryButtonClass} mt-2 w-full`}
          >
            <Icon name="externalLink" size={14} />
            <span>{classroomBrowserBusy ? 'Starting private browser…' : 'Sign in via Private In-App Browser'}</span>
          </button>
          <p className="mt-1 text-[11px] text-muted">
            ⚠️ <em>If Google blocks login with "This browser may not be secure", use the Companion Extension above (which uses your already-signed-in Chrome profile).</em>
          </p>
          <HostedBrowserDialog url={classroomViewerUrl} onClose={() => setClassroomViewerUrl('')} />
          {classroomProfileExists && (
            <button type="button" onClick={forgetClassroomBrowser} disabled={classroomBrowserBusy} className="mt-2 self-start text-xs font-medium text-rose underline disabled:opacity-50">
              Forget saved Classroom login
            </button>
          )}

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
                  <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-900 text-xs">
                    <strong className="block font-semibold mb-1">Why is the Extension needed?</strong>
                    <p className="text-[11px] leading-relaxed">
                      Google blocks Google Account logins on in-app / automated browsers with <em>"This browser or app may not be secure"</em> or continuous captchas.
                      Since you are <strong>already logged in</strong> to Google Classroom in your normal Chrome browser, the Uniflow Companion securely copies your active session with zero password prompts!
                    </p>
                  </div>

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
                      <li>In Chrome, go to <code className="rounded bg-white px-1 py-0.5 text-ink font-mono border border-line">chrome://extensions</code></li>
                      <li>Enable <strong>Developer mode</strong> (toggle in top-right corner).</li>
                      <li>Click <strong>Load unpacked</strong> and select the unzipped folder.</li>
                    </ol>
                  </div>

                  <p className="rounded-lg bg-emerald-50 border border-emerald-200 p-2 text-emerald-800 text-[11px]">
                    ✨ <strong>Instant detection:</strong> Once loaded, Uniflow detects it immediately. Click <strong>⚡ 1-Click Allow & Sync Session</strong> and your assignments will submit automatically forever!
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

        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Manual submission</p>
          <h3 className="mt-1 text-base font-semibold text-ink">Submit to Google Classroom</h3>
          <p className="mt-2 text-sm leading-6 text-muted">Attach custom files and select a cover page template if required by your university.</p>
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-3"><span className="text-sm font-semibold text-ink">Attached deliverables</span><span className="text-sm text-muted">{files.length} {files.length === 1 ? 'file' : 'files'}</span></div>
          {files.length === 0 ? <div className="rounded-lg border border-dashed border-line bg-paper px-4 py-8 text-center"><strong className="block text-sm font-semibold">No custom files attached</strong><span className="mt-1 block text-sm text-muted">Use Quick Turn In above or attach manual files below.</span></div> : (
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
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Course Automation</p>
          <h3 className="mt-1 text-base font-semibold text-ink">Auto turn-in for {assignment.course_name || 'this course'}</h3>
          <p className="mt-2 text-sm leading-6 text-muted">
            Choose when Claude-generated reports for <strong>{assignment.course_name || 'this course'}</strong> may be submitted. Only coursework in this course is affected.
          </p>
        </div>

        <label className="flex cursor-pointer items-center justify-between gap-4 rounded-lg border border-line bg-paper p-4">
          <span>
            <strong className="block text-sm font-semibold text-ink">Submit when a validated report is ready</strong>
            <small className="mt-1 block text-sm text-muted">Automatically attach the Google Doc and ZIP after successful generation.</small>
          </span>
          <input type="checkbox" checked={submitWhenReady} onChange={(e) => setSubmitWhenReady(e.target.checked)} className="size-5 shrink-0 accent-violet" />
        </label>

        <label className="flex cursor-pointer items-center justify-between gap-4 rounded-lg border border-line bg-paper p-4">
          <span>
            <strong className="block text-sm font-semibold text-ink">Allow auto turn-in for this course</strong>
            <small className="mt-1 block text-sm text-muted">Submits Google Doc + ZIP deliverables {scheduleMinutesBefore} minutes before deadline on GCR</small>
          </span>
          <input type="checkbox" checked={scheduleEnabled} onChange={(e) => setScheduleEnabled(e.target.checked)} className="size-5 shrink-0 accent-violet" />
        </label>

        <label className="flex flex-col gap-2 text-sm font-medium text-ink">
          Minutes before deadline
          <span className="flex flex-wrap items-center gap-3">
            <input type="number" min={5} max={1440} value={scheduleMinutesBefore} onChange={(e) => setScheduleMinutesBefore(parseInt(e.target.value, 10) || 60)} disabled={!scheduleEnabled} className={`${fieldClass} w-28 disabled:cursor-not-allowed disabled:bg-paper disabled:text-muted`} />
            <span className="text-sm font-normal text-muted">mins prior ({Math.round((scheduleMinutesBefore / 60) * 10) / 10} hours)</span>
          </span>
        </label>

        <button type="button" onClick={saveSchedule} disabled={savingSchedule} className={secondaryButtonClass}>
          {savingSchedule ? 'Saving schedule…' : <><Icon name="save" size={16}/> Save course auto turn-in setting</>}
        </button>
        {scheduleInfo && <p className="text-xs text-muted">Last result: {scheduleInfo.last_result?.status || 'No automatic submissions yet'}{scheduleInfo.last_run ? ` · ${new Date(scheduleInfo.last_run).toLocaleString()}` : ''} · Next scheduler check: {scheduleEnabled && scheduleInfo.next_run ? new Date(scheduleInfo.next_run).toLocaleString() : 'Disabled'}</p>}
      </section>
    </div>
  );
}

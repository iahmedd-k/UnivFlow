'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth, useUser } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

export default function OnboardingModal() {
  const { userId, getToken } = useAuth();
  const { user } = useUser();

  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [step, setStep] = useState(1); // 1 = Profile & GCR, 2 = Claude & Portal
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [successNotice, setSuccessNotice] = useState('');

  // Form Fields
  const [studentName, setStudentName] = useState('');
  const [rollNo, setRollNo] = useState('');
  const [semesterStartDate, setSemesterStartDate] = useState('');
  const [claudeSessionKey, setClaudeSessionKey] = useState('');
  const [portalCookies, setPortalCookies] = useState('');

  // Service connection statuses
  const [googleConnected, setGoogleConnected] = useState(false);
  const [googleEmail, setGoogleEmail] = useState('');
  const [googleBusy, setGoogleBusy] = useState(false);
  const [claudeConnected, setClaudeConnected] = useState(false);
  const [portalConnected, setPortalConnected] = useState(false);
  const [syncingClassroom, setSyncingClassroom] = useState(false);

  // Help guides accordion toggles
  const [showClaudeHelp, setShowClaudeHelp] = useState(false);
  const [showPortalHelp, setShowPortalHelp] = useState(false);

  // Check onboarding status on mount
  useEffect(() => {
    let active = true;
    if (!userId) return;

    const checkStatus = async () => {
      const storageKey = `uniflow_onboarding_dismissed_${userId}`;
      if (typeof window !== 'undefined' && localStorage.getItem(storageKey) === 'true') {
        if (active) setLoading(false);
        return;
      }

      try {
        const token = getToken ? await getToken() : null;
        const res = await api.getOnboardingStatus(token);
        if (!active) return;

        if (res?.is_dismissed) {
          localStorage.setItem(storageKey, 'true');
          setIsOpen(false);
          return;
        }

        if (res?.should_show) {
          const profile = res.profile || {};
          const semester = res.semester || {};
          const google = res.google || {};
          const claude = res.claude || {};
          const portal = res.portal || {};

          setStudentName(profile.student_name || user?.fullName || '');
          setRollNo(profile.roll_no || '');
          setSemesterStartDate(semester.semester_start_date || '');
          setGoogleConnected(Boolean(google.connected));
          setGoogleEmail(google.email || '');
          setClaudeConnected(Boolean(claude.connected));
          setPortalConnected(Boolean(portal.connected));

          // If step 1 items are already completely configured, jump directly to step 2
          if (profile.configured && semester.configured && google.connected && (!claude.connected || !portal.connected)) {
            setStep(2);
          } else {
            setStep(1);
          }

          setIsOpen(true);
        }
      } catch (err) {
        console.warn('Could not check onboarding status:', err);
      } finally {
        if (active) setLoading(false);
      }
    };

    checkStatus();
    return () => { active = false; };
  }, [userId, user, getToken]);

  const handleDismiss = useCallback(async () => {
    setIsOpen(false);
    if (userId) {
      localStorage.setItem(`uniflow_onboarding_dismissed_${userId}`, 'true');
      try {
        const token = getToken ? await getToken() : null;
        await api.dismissOnboarding(token);
      } catch (err) {
        console.warn('Could not record onboarding dismissal on server:', err);
      }
    }
  }, [userId, getToken]);

  const handleConnectGoogle = async () => {
    setGoogleBusy(true);
    setError('');
    try {
      const token = getToken ? await getToken() : null;
      // Persist any student profile inputs first so they aren't lost on redirect
      if (studentName.trim() || rollNo.trim() || semesterStartDate) {
        await api.saveOnboarding({
          student_name: studentName.trim() || undefined,
          roll_no: rollNo.trim() || undefined,
          semester_start_date: semesterStartDate || undefined,
          dismiss: false,
        }, token);
      }
      const res = await api.getGoogleAuthUrl(token, '/dashboard');
      if (res?.auth_url) {
        window.location.assign(res.auth_url);
      } else {
        throw new Error('Google did not return an authorization link.');
      }
    } catch (err) {
      setError(err.message || 'Could not initiate Google connection.');
      setGoogleBusy(false);
    }
  };

  const handleSyncClassroom = async () => {
    setSyncingClassroom(true);
    setError('');
    setSuccessNotice('');
    try {
      const token = getToken ? await getToken() : null;
      await api.triggerSync(semesterStartDate || null, token);
      setSuccessNotice('Google Classroom sync triggered in background!');
    } catch (err) {
      setError(err.message || 'Could not start Classroom sync.');
    } finally {
      setSyncingClassroom(false);
    }
  };

  const handleSaveStep1 = async (e) => {
    if (e) e.preventDefault();
    setSaving(true);
    setError('');
    try {
      const token = getToken ? await getToken() : null;
      await api.saveOnboarding({
        student_name: studentName.trim() || undefined,
        roll_no: rollNo.trim() || undefined,
        semester_start_date: semesterStartDate || undefined,
        dismiss: false,
      }, token);
      // Advance to step 2 for AI & Portal setup
      setStep(2);
    } catch (err) {
      setError(err.message || 'Could not save student profile.');
    } finally {
      setSaving(false);
    }
  };

  const handleFinish = async (e) => {
    if (e) e.preventDefault();
    setSaving(true);
    setError('');
    try {
      const token = getToken ? await getToken() : null;
      await api.saveOnboarding({
        student_name: studentName.trim() || undefined,
        roll_no: rollNo.trim() || undefined,
        semester_start_date: semesterStartDate || undefined,
        claude_session_key: claudeSessionKey.trim() || undefined,
        portal_cookies: portalCookies.trim() || undefined,
        dismiss: true,
      }, token);

      if (userId) {
        localStorage.setItem(`uniflow_onboarding_dismissed_${userId}`, 'true');
      }

      setSuccessNotice('Setup complete! Your workspace is ready.');
      setTimeout(() => {
        setIsOpen(false);
      }, 900);
    } catch (err) {
      setError(err.message || 'Could not complete onboarding setup.');
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen || loading) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-in fade-in duration-200" role="dialog" aria-modal="true" aria-labelledby="onboarding-modal-title">
      <div className="w-full max-w-md bg-surface border border-border rounded-2xl shadow-dropdown overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-3 border-b border-border-light bg-surface-secondary/40">
          <div className="flex items-center gap-3">
            <span className="size-8 rounded-lg bg-violet-light text-violet flex items-center justify-center flex-shrink-0">
              <Icon name="sparkles" size={16} />
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h3 id="onboarding-modal-title" className="text-sm font-bold text-ink">
                  Welcome to Uniflow
                </h3>
                <span className="px-1.5 py-0.5 text-[10px] font-semibold rounded bg-violet/10 text-violet-dark">
                  Step {step} of 2
                </span>
              </div>
              <p className="text-xs text-muted">
                {step === 1 ? 'Configure your identity & Google Classroom' : 'Connect Claude AI & University Portal'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleDismiss}
            className="size-7 rounded-md text-muted hover:text-ink hover:bg-surface-secondary flex items-center justify-center transition-colors"
            aria-label="Close setup modal"
            title="Close (Skip for now)"
          >
            <Icon name="close" size={16} />
          </button>
        </div>

        {/* Notices */}
        {error && (
          <div className="mx-5 mt-3 p-2.5 rounded-lg bg-danger-bg border border-danger/20 text-xs text-danger flex items-start gap-2">
            <Icon name="circleAlert" size={14} className="flex-shrink-0 mt-0.5" />
            <span className="flex-1">{error}</span>
          </div>
        )}
        {successNotice && (
          <div className="mx-5 mt-3 p-2.5 rounded-lg bg-success-bg border border-success/20 text-xs text-success flex items-start gap-2">
            <Icon name="checkCircle" size={14} className="flex-shrink-0 mt-0.5" />
            <span className="flex-1">{successNotice}</span>
          </div>
        )}

        {/* Step 1 Body */}
        {step === 1 && (
          <form onSubmit={handleSaveStep1} className="p-5 flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-semibold text-text-heading mb-1" htmlFor="ob-name">
                  Student Name <span className="text-danger">*</span>
                </label>
                <input
                  id="ob-name"
                  type="text"
                  required
                  placeholder="e.g. Ahmed Khan"
                  value={studentName}
                  onChange={(e) => setStudentName(e.target.value)}
                  className="w-full h-9 px-3 text-xs bg-surface border border-border-input rounded-lg focus:outline-none focus:ring-2 focus:ring-violet/20 focus:border-violet text-ink placeholder:text-subtle transition-all"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-text-heading mb-1" htmlFor="ob-roll">
                  Student Roll / Reg ID <span className="text-danger">*</span>
                </label>
                <input
                  id="ob-roll"
                  type="text"
                  required
                  placeholder="e.g. 210984"
                  value={rollNo}
                  onChange={(e) => setRollNo(e.target.value)}
                  className="w-full h-9 px-3 text-xs bg-surface border border-border-input rounded-lg focus:outline-none focus:ring-2 focus:ring-violet/20 focus:border-violet text-ink placeholder:text-subtle transition-all"
                />
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-xs font-semibold text-text-heading" htmlFor="ob-sem-date">
                  Semester Start Date
                </label>
                <span className="text-[10px] text-muted">For Classroom fetching</span>
              </div>
              <input
                id="ob-sem-date"
                type="date"
                value={semesterStartDate}
                onChange={(e) => setSemesterStartDate(e.target.value)}
                className="w-full h-9 px-3 text-xs bg-surface border border-border-input rounded-lg focus:outline-none focus:ring-2 focus:ring-violet/20 focus:border-violet text-ink transition-all"
              />
              <p className="mt-1 text-[11px] text-muted leading-tight">
                Assignments & coursework from this date onward will be synchronized.
              </p>
            </div>

            {/* Google Classroom Connection Box */}
            <div className="pt-2 border-t border-border-light">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-semibold text-text-heading flex items-center gap-1.5">
                  <Icon name="school" size={14} className="text-violet" />
                  Google Classroom
                </span>
                {googleConnected ? (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-success-bg text-success border border-success/20">
                    <span className="size-1.5 rounded-full bg-success animate-pulse" />
                    Connected
                  </span>
                ) : (
                  <span className="text-[10px] text-amber font-medium">Not connected</span>
                )}
              </div>

              {googleConnected ? (
                <div className="flex items-center justify-between p-2.5 rounded-lg bg-surface-secondary border border-border">
                  <span className="text-xs text-text-body truncate max-w-[220px]">
                    {googleEmail || 'Google account linked'}
                  </span>
                  <button
                    type="button"
                    onClick={handleSyncClassroom}
                    disabled={syncingClassroom}
                    className="h-7 px-2.5 text-[11px] font-semibold rounded-md bg-surface border border-border hover:bg-surface-hover text-ink flex items-center gap-1 transition-all disabled:opacity-60"
                  >
                    <Icon name="refresh" size={12} className={syncingClassroom ? 'animate-spin' : ''} />
                    {syncingClassroom ? 'Syncing...' : 'Sync Now'}
                  </button>
                </div>
              ) : (
                <div className="flex items-center justify-between p-2.5 rounded-lg bg-google-bg/40 border border-google/20">
                  <span className="text-xs text-text-body">
                    Link your university Google account
                  </span>
                  <button
                    type="button"
                    onClick={handleConnectGoogle}
                    disabled={googleBusy}
                    className="h-7 px-3 text-xs font-semibold rounded-md bg-google text-white hover:opacity-90 flex items-center gap-1.5 transition-all shadow-sm disabled:opacity-60"
                  >
                    <span className="font-bold text-[11px]">G</span>
                    {googleBusy ? 'Connecting...' : 'Connect'}
                  </button>
                </div>
              )}
            </div>

            {/* Step 1 Actions */}
            <div className="pt-3 border-t border-border-light flex items-center justify-between">
              <button
                type="button"
                onClick={handleDismiss}
                className="text-xs text-muted hover:text-ink font-medium transition-colors"
              >
                Skip for now
              </button>
              <button
                type="submit"
                disabled={saving}
                className="h-8 px-4 text-xs font-semibold rounded-lg bg-violet hover:bg-violet-dark text-white flex items-center gap-1.5 transition-all shadow-sm disabled:opacity-60"
              >
                {saving ? 'Saving...' : 'Next: Integrations'}
                <Icon name="arrowUpRight" size={13} className="rotate-45" />
              </button>
            </div>
          </form>
        )}

        {/* Step 2 Body */}
        {step === 2 && (
          <form onSubmit={handleFinish} className="p-5 flex flex-col gap-4">
            {/* Claude AI Session Cookie */}
            <div className="p-3 rounded-xl border border-border bg-surface-secondary/30">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-semibold text-text-heading flex items-center gap-1.5">
                  <Icon name="brain" size={14} className="text-violet" />
                  Claude AI Session Cookie
                </span>
                {claudeConnected ? (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-success-bg text-success border border-success/20">
                    <span className="size-1.5 rounded-full bg-success" />
                    Active
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => setShowClaudeHelp(!showClaudeHelp)}
                    className="text-[10px] text-violet hover:underline flex items-center gap-0.5"
                  >
                    <Icon name="help" size={11} />
                    How to find?
                  </button>
                )}
              </div>

              {showClaudeHelp && !claudeConnected && (
                <div className="mb-2 p-2 rounded bg-surface border border-border text-[11px] text-muted space-y-1">
                  <p>1. Open <a href="https://claude.ai" target="_blank" rel="noreferrer" className="text-violet underline">claude.ai</a> and log in.</p>
                  <p>2. Press <kbd className="px-1 py-0.5 rounded bg-surface-secondary border border-border text-[10px]">F12</kbd> &rarr; Application tab &rarr; Cookies.</p>
                  <p>3. Copy the value of <code className="text-ink font-semibold">sessionKey</code> and paste below.</p>
                </div>
              )}

              {claudeConnected ? (
                <p className="text-xs text-muted">
                  Your Claude account is linked for zero-latency lab and assignment report solving.
                </p>
              ) : (
                <div>
                  <input
                    type="password"
                    placeholder="sk-ant-sid01-..."
                    value={claudeSessionKey}
                    onChange={(e) => setClaudeSessionKey(e.target.value)}
                    className="w-full h-8 px-2.5 text-xs bg-surface border border-border-input rounded-lg focus:outline-none focus:ring-2 focus:ring-violet/20 focus:border-violet text-ink placeholder:text-subtle font-mono transition-all"
                  />
                  <p className="mt-1 text-[10px] text-muted">
                    Powers automatic report generation & terminal output creation.
                  </p>
                </div>
              )}
            </div>

            {/* University Portal Session Cookies */}
            <div className="p-3 rounded-xl border border-border bg-surface-secondary/30">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-semibold text-text-heading flex items-center gap-1.5">
                  <Icon name="globe" size={14} className="text-cyan" />
                  University Portal Cookies
                </span>
                {portalConnected ? (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-success-bg text-success border border-success/20">
                    <span className="size-1.5 rounded-full bg-success" />
                    Active
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => setShowPortalHelp(!showPortalHelp)}
                    className="text-[10px] text-violet hover:underline flex items-center gap-0.5"
                  >
                    <Icon name="help" size={11} />
                    How to find?
                  </button>
                )}
              </div>

              {showPortalHelp && !portalConnected && (
                <div className="mb-2 p-2 rounded bg-surface border border-border text-[11px] text-muted space-y-1">
                  <p>1. Open your Air University Student Portal.</p>
                  <p>2. Open DevTools &rarr; Network &rarr; Click any request.</p>
                  <p>3. Copy the <code className="text-ink font-semibold">Cookie</code> header value and paste below.</p>
                </div>
              )}

              {portalConnected ? (
                <p className="text-xs text-muted">
                  Portal cookie is connected for live attendance & timetable synchronization.
                </p>
              ) : (
                <div>
                  <input
                    type="password"
                    placeholder="ASP.NET_SessionId=...; .ASPXAUTH=..."
                    value={portalCookies}
                    onChange={(e) => setPortalCookies(e.target.value)}
                    className="w-full h-8 px-2.5 text-xs bg-surface border border-border-input rounded-lg focus:outline-none focus:ring-2 focus:ring-violet/20 focus:border-violet text-ink placeholder:text-subtle font-mono transition-all"
                  />
                  <p className="mt-1 text-[10px] text-muted">
                    Syncs attendance and portal records without needing a headless browser.
                  </p>
                </div>
              )}
            </div>

            {/* Step 2 Actions */}
            <div className="pt-3 border-t border-border-light flex items-center justify-between">
              <button
                type="button"
                onClick={() => setStep(1)}
                className="text-xs text-muted hover:text-ink font-medium flex items-center gap-1 transition-colors"
              >
                <Icon name="arrowLeft" size={12} />
                Back
              </button>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleDismiss}
                  className="text-xs text-muted hover:text-ink font-medium transition-colors"
                >
                  Skip
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="h-8 px-4 text-xs font-semibold rounded-lg bg-violet hover:bg-violet-dark text-white flex items-center gap-1.5 transition-all shadow-sm disabled:opacity-60"
                >
                  <Icon name="check" size={13} />
                  {saving ? 'Completing...' : 'Finish Setup'}
                </button>
              </div>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

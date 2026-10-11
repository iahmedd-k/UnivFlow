'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth, useUser } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

export default function SettingsPage() {
  const { getToken } = useAuth();
  const { user } = useUser();
  const [notificationEmail, setNotificationEmail] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const loadEmail = useCallback(async () => {
    try {
      const token = await getToken();
      const result = await api.getNotificationEmail(token);
      setNotificationEmail(result?.email || '');
    } catch (err) {
      console.error('Failed to load notification email:', err);
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    loadEmail();
  }, [loadEmail]);

  const handleSave = async (e) => {
    e.preventDefault();
    if (!notificationEmail.trim()) {
      setError('Please enter an email address');
      return;
    }
    // Basic email validation
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(notificationEmail)) {
      setError('Please enter a valid email address');
      return;
    }

    setSaving(true);
    setError('');
    setSuccess('');

    try {
      const token = await getToken();
      await api.setNotificationEmail(notificationEmail.trim(), token);
      setSuccess('Notification email saved successfully!');
    } catch (err) {
      setError(err.message || 'Could not save notification email');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm('Are you sure you want to remove your notification email? You will no longer receive email alerts.')) {
      return;
    }

    setSaving(true);
    setError('');
    setSuccess('');

    try {
      const token = await getToken();
      await api.deleteNotificationEmail(token);
      setNotificationEmail('');
      setSuccess('Notification email removed');
    } catch (err) {
      setError(err.message || 'Could not remove notification email');
    } finally {
      setSaving(false);
    }
  };

  const handleTestEmail = async () => {
    if (!notificationEmail.trim()) {
      setError('Please save an email address first');
      return;
    }

    setSaving(true);
    setError('');
    setSuccess('');

    try {
      const token = await getToken();
      await api.createNotificationForMe({
        notification_type: 'test',
        subject: 'Test Notification from Uniflow',
        payload: 'This is a test email to verify your notification settings are working correctly.',
      }, token);
      setSuccess('Test email queued! Check your inbox (and spam folder).');
    } catch (err) {
      setError(err.message || 'Could not send test email');
    } finally {
      setSaving(false);
    }
  };

  const userEmail = user?.primaryEmailAddress?.emailAddress || 'your-email@example.com';

  return (
    <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 text-[#292d3a]">
      <header className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">PREFERENCES</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">Settings</h1>
          <p className="mt-1 text-xs text-[#858998]">Manage your notification preferences and account settings.</p>
        </div>
      </header>

      {error && <div className="rounded-lg border border-[#f1dede] bg-[#fff8f8] px-3 py-2.5 text-xs text-[#a04a4a]" role="alert">{error}</div>}
      {success && <div className="rounded-lg border border-[#d8eee4] bg-[#f3fbf7] px-3 py-2.5 text-xs text-[#43816b]" role="status">{success}</div>}

      <section className="min-w-0 rounded-xl border border-[#ebebf0] bg-white shadow-sm">
        <header className="flex items-center justify-between gap-3.5 border-b border-[#f0f0f3] px-5 py-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">EMAIL NOTIFICATIONS</p>
            <h2 className="text-[13px] font-semibold text-[#343746]">Alert Email Address</h2>
          </div>
        </header>
        <div className="p-5">
          <p className="mb-4 rounded-lg bg-[#f6f5ff] px-3 py-2.5 text-xs leading-relaxed text-[#77729b]">
            Enter an email address to receive alerts for assignment deadlines, grade updates, 
            class changes, and other important notifications from Uniflow.
          </p>

          <form onSubmit={handleSave} className="flex max-w-[480px] flex-col gap-4">
            <div>
              <label htmlFor="notificationEmail" className="mb-1 block text-xs font-medium text-[#696d7d]">
                Notification Email
              </label>
              <input
                type="email"
                id="notificationEmail"
                className="w-full rounded-md border border-[#e4e4eb] bg-white px-3 py-2 text-xs text-[#343746] outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:opacity-50"
                value={notificationEmail}
                onChange={(e) => setNotificationEmail(e.target.value)}
                placeholder="your-email@university.edu.pk"
                disabled={saving || loading}
                autoComplete="email"
                required
              />
              <small className="mt-1 block text-xs text-[#9295a2]">
                This email will be used for all Uniflow alerts. Your Clerk account email: <strong>{userEmail}</strong>
              </small>
            </div>

            <div className="flex flex-wrap gap-3">
              <button
                type="submit"
                className="inline-flex min-h-9 items-center justify-center rounded-md border border-[#6657d9] bg-[#6657d9] px-3 text-xs font-semibold text-white hover:bg-[#5142c1] disabled:cursor-not-allowed disabled:opacity-55"
                disabled={saving || loading}
              >
                {saving ? 'Saving…' : 'Save Email'}
              </button>

              {notificationEmail && (
                <button
                  type="button"
                  className="inline-flex min-h-9 items-center justify-center rounded-md border border-[#e5e5ec] bg-white px-3 text-xs font-semibold text-[#5c6070] hover:bg-[#f8f8fb] disabled:opacity-55"
                  onClick={handleTestEmail}
                  disabled={saving || loading}
                >
                  {saving ? 'Sending…' : 'Send Test Email'}
                </button>
              )}

              {notificationEmail && (
                <button
                  type="button"
                  className="inline-flex min-h-9 items-center justify-center rounded-md border border-[#f0dada] bg-white px-3 text-xs font-semibold text-[#b34d4d] hover:bg-[#fff4f4] disabled:opacity-55"
                  onClick={handleDelete}
                  disabled={saving || loading}
                >
                  {saving ? 'Removing…' : 'Remove Email'}
                </button>
              )}
            </div>
          </form>

          {notificationEmail && (
            <div className="mt-6 flex items-center gap-3 rounded-lg border border-green-200 bg-green-50 p-4">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-green-100 text-green-700"><Icon name="checkCircle" size={19} /></span>
              <div className="flex min-w-0 flex-col gap-1 text-xs">
                <span className="text-neutral-600">Current notification email</span>
                <strong className="break-all text-sm text-neutral-900">{notificationEmail}</strong>
                <small className="text-neutral-500">You will receive alerts at this address</small>
              </div>
            </div>
          )}

          {!notificationEmail && (
            <div className="mt-6 flex items-center gap-3 rounded-lg border border-red-200 bg-red-50 p-4">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-red-100 text-red-700"><Icon name="alert" size={19} /></span>
              <div className="flex min-w-0 flex-col gap-1 text-xs">
                <span className="text-neutral-600">No notification email configured</span>
                <strong className="text-sm text-neutral-900">You won&apos;t receive email alerts</strong>
                <small className="text-neutral-500">Add an email above to enable notifications</small>
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="min-w-0 rounded-xl border border-[#ebebf0] bg-white shadow-sm">
        <header className="flex items-center justify-between gap-3.5 border-b border-[#f0f0f3] px-5 py-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">ACCOUNT</p>
            <h2 className="text-[13px] font-semibold text-[#343746]">Connected Services</h2>
          </div>
        </header>
        <div className="p-5">
          <div className="flex flex-col">
            <article className="flex min-h-[60px] items-center gap-3 border-b border-[#f1f1f4] py-3 last:border-b-0">
              <span className="grid h-[30px] w-[30px] place-items-center rounded-lg bg-[#f0edff] text-[#6657d9]"><Icon name="user" size={18} /></span>
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <strong className="text-xs font-semibold text-[#414553]">Clerk Account</strong>
                <small className="text-xs text-[#9295a2]">Primary authentication via Clerk</small>
              </span>
              <span className="inline-flex rounded-full bg-[#eaf7f1] px-2 py-1 text-xs font-semibold text-[#438a71]">Connected</span>
            </article>
            <article className="flex min-h-[60px] items-center gap-3 border-b border-[#f1f1f4] py-3 last:border-b-0">
              <span className="grid h-[30px] w-[30px] place-items-center rounded-lg bg-[#f0edff] text-[#6657d9]"><Icon name="mail" size={18} /></span>
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <strong className="text-xs font-semibold text-[#414553]">Google Classroom</strong>
                <small className="text-xs text-[#9295a2]">Sync courses, assignments, and grades</small>
              </span>
              <span className="inline-flex rounded-full bg-[#eaf7f1] px-2 py-1 text-xs font-semibold text-[#438a71]">Connected</span>
            </article>
            <article className="flex min-h-[60px] items-center gap-3 py-3">
              <span className="grid h-[30px] w-[30px] place-items-center rounded-lg bg-[#f0edff] text-[#6657d9]"><Icon name="globe" size={18} /></span>
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <strong className="text-xs font-semibold text-[#414553]">University Portal</strong>
                <small className="text-xs text-[#9295a2]">Access grades, schedules, and announcements</small>
              </span>
              <span className="inline-flex rounded-full bg-[#fff4e4] px-2 py-1 text-xs font-semibold text-[#a87936]">Configure in Portal</span>
            </article>
          </div>
        </div>
      </section>

      <section className="min-w-0 rounded-xl border border-[#ebebf0] bg-white shadow-sm">
        <header className="flex items-center justify-between gap-3.5 border-b border-[#f0f0f3] px-5 py-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">NOTIFICATION TYPES</p>
            <h2 className="text-[13px] font-semibold text-[#343746]">What you&apos;ll be notified about</h2>
          </div>
        </header>
        <div className="p-5">
          <ul className="m-0 flex list-none flex-col gap-3 p-0">
            <li className="flex items-center gap-3 rounded-lg bg-neutral-50 p-3">
              <Icon name="checkCircle" size={18} className="text-green-600" />
              <span>Assignment due date reminders</span>
            </li>
            <li className="flex items-center gap-3 rounded-lg bg-neutral-50 p-3">
              <Icon name="checkCircle" size={18} className="text-green-600" />
              <span>New assignment posted notifications</span>
            </li>
            <li className="flex items-center gap-3 rounded-lg bg-neutral-50 p-3">
              <Icon name="checkCircle" size={18} className="text-green-600" />
              <span>Grade updates and feedback</span>
            </li>
            <li className="flex items-center gap-3 rounded-lg bg-neutral-50 p-3">
              <Icon name="checkCircle" size={18} className="text-green-600" />
              <span>Class schedule changes (cancellations, room changes)</span>
            </li>
            <li className="flex items-center gap-3 rounded-lg bg-neutral-50 p-3">
              <Icon name="checkCircle" size={18} className="text-green-600" />
              <span>Exam and quiz announcements</span>
            </li>
            <li className="flex items-center gap-3 rounded-lg bg-neutral-50 p-3">
              <Icon name="checkCircle" size={18} className="text-green-600" />
              <span>University portal grade sync results</span>
            </li>
            <li className="flex items-center gap-3 rounded-lg bg-neutral-50 p-3">
              <Icon name="checkCircle" size={18} className="text-green-600" />
              <span>AI solution generation completion</span>
            </li>
          </ul>
        </div>
      </section>
    </div>
  );
}
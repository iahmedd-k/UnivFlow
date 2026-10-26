'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { SignUp } from '@clerk/nextjs';
import { manualSignup } from '@/app/lib/api';
import { setManualSession, isManualAuthEnabled } from '@/app/lib/manual-auth';

const appearance = {
  elements: {
    rootBox: 'clerk-root-box',
    card: 'clerk-auth-card',
    headerTitle: 'clerk-header-title',
    headerSubtitle: 'clerk-header-subtitle',
    socialButtonsBlockButton: 'clerk-social-button',
    formButtonPrimary: 'clerk-primary-button',
    formFieldInput: 'clerk-input',
    formFieldLabel: 'clerk-label',
    footerAction: 'clerk-footer-action',
    dividerLine: 'clerk-divider',
    dividerText: 'clerk-divider-text',
  },
};

export default function Page() {
  const [authMode, setAuthMode] = useState('clerk'); // 'clerk' (default) | 'manual'
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [manualAllowed, setManualAllowed] = useState(true);

  useEffect(() => {
    setManualAllowed(isManualAuthEnabled());
  }, []);

  const handleManualSignup = async (e) => {
    e.preventDefault();
    if (!email || !password || !firstName) {
      setError('Please fill in all required fields.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const res = await manualSignup({
        email,
        password,
        firstName,
        lastName,
      });
      if (res?.token && res?.user) {
        setManualSession(res.token, res.user);
        window.location.href = '/dashboard';
      } else {
        throw new Error(res?.message || 'Registration failed.');
      }
    } catch (err) {
      setError(err?.message || 'Registration failed. Please check inputs.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="auth-page">
      <section className="auth-art-panel">
        <Link href="/sign-in" className="brand-lockup auth-brand">
          <span className="brand-mark">u</span><span>uniflow</span>
        </Link>
        <div className="auth-art-copy">
          <span className="auth-overline"><i /> YOUR SEMESTER, IN SYNC</span>
          <h1>Make room for<br /><em>what matters.</em></h1>
          <p>One calm place for classes, coursework, and everything you’re working toward.</p>
        </div>
        <div className="auth-preview" aria-hidden="true">
          <div className="preview-top">
            <span className="preview-dots"><i /><i /><i /></span>
            <span>My week</span>
            <span className="preview-date">THIS WEEK</span>
          </div>
          <div className="preview-progress"><span /><span /><span /><span /><span /></div>
          <div className="preview-task">
            <span className="preview-check">✓</span>
            <span><b>Design principles essay</b><small>Interaction Design · Due Thursday</small></span>
            <i>In progress</i>
          </div>
          <div className="preview-task muted-task">
            <span className="preview-check">✓</span>
            <span><b>Review lecture notes</b><small>Human Computer Interaction</small></span>
            <i>Done</i>
          </div>
          <div className="preview-bottom"><span>✳</span> A clearer view of your semester</div>
        </div>
        <div className="auth-art-footer">
          <span>Built for the way you learn.</span><span>01 — 03</span>
        </div>
      </section>

      <section className="auth-form-panel">
        <Link href="/sign-in" className="auth-mobile-brand">
          <span className="brand-mark">u</span><span>uniflow</span>
        </Link>
        <div className="auth-form-wrap">
          <p className="eyebrow">GET STARTED</p>
          <h2>Create your account</h2>
          <p className="auth-intro">Bring your academic life into focus.</p>

          {manualAllowed && (
            <div className="flex items-center gap-1.5 p-1 bg-stone-100 rounded-lg mb-5 border border-stone-200/80 text-xs font-medium">
              <button
                type="button"
                onClick={() => { setAuthMode('clerk'); setError(''); }}
                className={`flex-1 py-1.5 px-3 rounded-md transition-all text-center cursor-pointer ${
                  authMode === 'clerk'
                    ? 'bg-white text-stone-900 shadow-xs font-semibold'
                    : 'text-stone-500 hover:text-stone-800'
                }`}
              >
                Clerk Sign Up (Default)
              </button>
              <button
                type="button"
                onClick={() => { setAuthMode('manual'); setError(''); }}
                className={`flex-1 py-1.5 px-3 rounded-md transition-all text-center cursor-pointer flex items-center justify-center gap-1.5 ${
                  authMode === 'manual'
                    ? 'bg-white text-indigo-600 shadow-xs font-semibold'
                    : 'text-stone-500 hover:text-stone-800'
                }`}
              >
                <span>Manual Sign Up</span>
                <span className="text-[10px] bg-indigo-50 text-indigo-600 border border-indigo-200/80 font-bold px-1.5 py-0.2 rounded-full">Dev</span>
              </button>
            </div>
          )}

          {authMode === 'clerk' ? (
            <SignUp
              routing="path"
              path="/sign-up"
              signInUrl="/sign-in"
              fallbackRedirectUrl="/dashboard"
              appearance={appearance}
            />
          ) : (
            <form onSubmit={handleManualSignup} className="space-y-4">
              {error && (
                <div className="p-3 text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-lg">
                  {error}
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-stone-700 uppercase tracking-wider mb-1.5">
                    First Name
                  </label>
                  <input
                    type="text"
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    placeholder="Ahmed"
                    required
                    className="w-full px-3.5 py-2.5 rounded-lg border border-stone-200 bg-stone-50/50 text-stone-900 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 transition"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-stone-700 uppercase tracking-wider mb-1.5">
                    Last Name
                  </label>
                  <input
                    type="text"
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                    placeholder="Dev"
                    className="w-full px-3.5 py-2.5 rounded-lg border border-stone-200 bg-stone-50/50 text-stone-900 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 transition"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-stone-700 uppercase tracking-wider mb-1.5">
                  Email Address
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="student@example.com"
                  required
                  className="w-full px-3.5 py-2.5 rounded-lg border border-stone-200 bg-stone-50/50 text-stone-900 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 transition"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-stone-700 uppercase tracking-wider mb-1.5">
                  Password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="At least 6 characters"
                  required
                  minLength={6}
                  className="w-full px-3.5 py-2.5 rounded-lg border border-stone-200 bg-stone-50/50 text-stone-900 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 transition"
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 px-4 rounded-lg bg-stone-900 hover:bg-stone-800 text-white text-sm font-semibold transition cursor-pointer disabled:opacity-50"
              >
                {loading ? 'Creating account…' : 'Create Account'}
              </button>

              <div className="pt-2 text-center text-xs text-stone-500">
                Already have an account?{' '}
                <Link href="/sign-in" className="text-indigo-600 font-medium hover:underline">
                  Sign in
                </Link>
              </div>
            </form>
          )}
        </div>
        <p className="auth-privacy">Your academic workspace, ready when you are.</p>
      </section>
    </main>
  );
}

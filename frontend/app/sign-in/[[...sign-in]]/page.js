'use client';

import React, { useState, useEffect } from 'react';
import { SignIn } from '@clerk/nextjs';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { manualLogin, getSeededUsers } from '@/app/lib/api';
import { setManualSession, isManualAuthEnabled } from '@/app/lib/manual-auth';

export default function SignInPage() {
  const router = useRouter();
  const [authMode, setAuthMode] = useState('clerk'); // 'clerk' (default) | 'manual'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [seededUsers, setSeededUsers] = useState([]);
  const [manualAllowed, setManualAllowed] = useState(false);

  useEffect(() => {
    const enabled = isManualAuthEnabled();
    setManualAllowed(enabled);
    if (enabled) {
      getSeededUsers()
        .then((res) => {
          if (res?.users) setSeededUsers(res.users);
        })
        .catch(() => {});
    }
  }, []);

  const handleManualSubmit = async (e) => {
    e.preventDefault();
    if (!email || !password) {
      setError('Please provide both email and password.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const res = await manualLogin(email, password);
      if (res?.token && res?.user) {
        setManualSession(res.token, res.user);
        window.location.href = '/dashboard';
      } else {
        throw new Error(res?.message || 'Authentication failed.');
      }
    } catch (err) {
      setError(err?.message || 'Invalid email or password.');
    } finally {
      setLoading(false);
    }
  };

  const fillCredentials = (u) => {
    setEmail(u.email);
    setPassword(u.password);
    setError('');
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
        <div className="auth-art-footer"><span>Built for the way you learn.</span><span>01 — 03</span></div>
      </section>

      <section className="auth-form-panel">
        <div className="auth-mobile-brand"><span className="brand-mark">u</span><span>uniflow</span></div>
        <div className="auth-form-wrap">
          <p className="eyebrow">WELCOME BACK</p>
          <h2>Sign in to Uniflow</h2>
          <p className="auth-intro">Pick up where you left off in your academic workspace.</p>

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
                Clerk Sign In (Default)
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
                <span>Manual / Seeded</span>
                <span className="text-[10px] bg-indigo-50 text-indigo-600 border border-indigo-200/80 font-bold px-1.5 py-0.2 rounded-full">Dev</span>
              </button>
            </div>
          )}

          {authMode === 'clerk' ? (
            <SignIn
              routing="path"
              path="/sign-in"
              signUpUrl="/sign-up"
              fallbackRedirectUrl="/dashboard"
              appearance={{ elements: {
                rootBox: 'clerk-login-root',
                card: 'clerk-login-card',
                headerTitle: 'clerk-header-title',
                headerSubtitle: 'clerk-header-subtitle',
                socialButtonsBlockButton: 'clerk-social-button',
                formButtonPrimary: 'clerk-primary-button',
                formFieldInput: 'clerk-input',
                formFieldLabel: 'clerk-label',
                footerAction: 'clerk-footer-action',
                dividerLine: 'clerk-divider',
                dividerText: 'clerk-divider-text',
              } }}
            />
          ) : (
            <form onSubmit={handleManualSubmit} className="space-y-4">
              {error && (
                <div className="p-3 text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-lg">
                  {error}
                </div>
              )}

              <div>
                <label className="block text-xs font-semibold text-stone-700 uppercase tracking-wider mb-1.5">
                  Email Address
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@example.com"
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
                  placeholder="••••••••"
                  required
                  className="w-full px-3.5 py-2.5 rounded-lg border border-stone-200 bg-stone-50/50 text-stone-900 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 transition"
                />
              </div>

              {seededUsers.length > 0 && (
                <div className="pt-1 pb-1">
                  <p className="text-[11px] font-semibold text-stone-500 uppercase tracking-wider mb-2">
                    Quick Seeded Credentials (Click to fill)
                  </p>
                  <div className="flex flex-col gap-1.5">
                    {seededUsers.map((u) => (
                      <button
                        key={u.email}
                        type="button"
                        onClick={() => fillCredentials(u)}
                        className="flex items-center justify-between px-2.5 py-1.5 bg-stone-50 hover:bg-indigo-50/80 border border-stone-200/80 hover:border-indigo-200 rounded-md text-left text-xs transition cursor-pointer group"
                      >
                        <span className="font-medium text-stone-700 group-hover:text-indigo-700">{u.name}</span>
                        <span className="text-stone-400 font-mono text-[11px] group-hover:text-indigo-600">{u.email}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 px-4 rounded-lg bg-stone-900 hover:bg-stone-800 text-white text-sm font-semibold transition cursor-pointer disabled:opacity-50"
              >
                {loading ? 'Signing in…' : 'Sign In with Password'}
              </button>

              <div className="pt-2 text-center text-xs text-stone-500">
                Need an account?{' '}
                <Link href="/sign-up" className="text-indigo-600 font-medium hover:underline">
                  Sign up
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

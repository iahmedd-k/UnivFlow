'use client';

import React, { useState, useEffect } from 'react';
import { SignIn, ClerkLoaded, ClerkLoading } from '@clerk/nextjs';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { manualLogin, getSeededUsers } from '@/app/lib/api';
import { setManualSession, isManualAuthEnabled } from '@/app/lib/manual-auth';

export default function SignInPage() {
  const router = useRouter();
  const [authMode, setAuthMode] = useState(() => isManualAuthEnabled() ? 'manual' : 'clerk'); // 'clerk' | 'manual'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [seededUsers, setSeededUsers] = useState([]);
  const [manualAllowed, setManualAllowed] = useState(() => isManualAuthEnabled());

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
        router.replace('/dashboard');
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
      <section className="auth-form-panel">
        <div className="auth-mobile-brand">
          <span className="brand-mark">u</span><span>uniflow</span>
        </div>
        <div className="auth-form-wrap">
          <div className="auth-heading">
            <span className="auth-heading-mark">↗</span>
            <div>
              <p className="eyebrow">WELCOME BACK</p>
              <h2>Sign in to your workspace</h2>
            </div>
          </div>
          <p className="auth-intro">Continue where you left off and keep your semester moving.</p>

          {manualAllowed && (
            <div className="auth-mode-switch" aria-label="Sign-in method">
              <button
                type="button"
                onClick={() => { setAuthMode('clerk'); setError(''); }}
                className={authMode === 'clerk' ? 'is-active' : ''}
              >
                <span className="auth-mode-dot" /> Standard sign in
              </button>
              <button
                type="button"
                onClick={() => { setAuthMode('manual'); setError(''); }}
                className={authMode === 'manual' ? 'is-active' : ''}
              >
                <span className="auth-mode-dot" /> Campus account
              </button>
            </div>
          )}

          {authMode === 'clerk' ? (
            <>
              <ClerkLoading>
                <div className="flex flex-col items-center justify-center py-12 px-6 rounded-2xl border border-stone-200/80 bg-white/70 shadow-xs backdrop-blur-xs min-h-[380px] w-full text-center">
                  <div className="size-8 rounded-full border-2 border-indigo-600 border-t-transparent animate-spin mb-3" />
                  <p className="text-xs font-semibold text-stone-700">Connecting to secure sign-in…</p>
                  <span className="text-[11px] text-stone-400 mt-1">Initializing workspace authentication</span>
                </div>
              </ClerkLoading>
              <ClerkLoaded>
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
              </ClerkLoaded>
            </>
          ) : (
            <form onSubmit={handleManualSubmit} className="auth-manual-form">
              {error && (
                <div className="auth-error">
                  {error}
                </div>
              )}

              <div>
                <label htmlFor="manual-email">University email</label>
                <input
                  id="manual-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@university.edu"
                  required
                />
              </div>

              <div>
                <label htmlFor="manual-password">Password</label>
                <input
                  id="manual-password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter your password"
                  required
                />
              </div>

              {seededUsers.length > 0 && (
                <div className="auth-quick-access">
                  <p>Quick access · development accounts</p>
                  <div>
                    {seededUsers.map((u) => (
                      <button
                        key={u.email}
                        type="button"
                        onClick={() => fillCredentials(u)}
                      >
                        <span>{u.name}</span>
                        <span>Use account</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="auth-submit"
              >
                {loading ? 'Signing you in…' : 'Continue to workspace'} <span>→</span>
              </button>

              <div className="auth-form-footer">
                <span>New to UnivFlow?</span>{' '}
                <Link href="/sign-up">
                  Create an account
                </Link>
              </div>
            </form>
          )}
        </div>
        <p className="auth-privacy">By continuing, you agree to use UnivFlow responsibly for your academic work.</p>
      </section>
    </main>
  );
}

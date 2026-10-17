'use client';

import { SignIn } from '@clerk/nextjs';
import Link from 'next/link';

export default function SignInPage() {
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
        </div>
        <p className="auth-privacy">Your academic workspace, ready when you are.</p>
      </section>
    </main>
  );
}

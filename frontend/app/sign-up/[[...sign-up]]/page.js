import Link from 'next/link';
import { SignUp } from '@clerk/nextjs';

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
          <SignUp
            routing="path"
            path="/sign-up"
            signInUrl="/sign-in"
            fallbackRedirectUrl="/dashboard"
            appearance={appearance}
          />
        </div>
        <p className="auth-privacy">Your academic workspace, ready when you are.</p>
      </section>
    </main>
  );
}

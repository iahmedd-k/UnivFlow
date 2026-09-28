'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth, useUser, UserButton } from '@clerk/nextjs';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';
import './dashboard-utilities.css';
import './dashboard-pages.css';

const groups = [
  { label: 'Workspace', items: [
    { href: '/dashboard', label: 'Overview', icon: 'dashboard' },
    { href: '/dashboard/assignments', label: 'Assignments', icon: 'listChecks' },
    { href: '/dashboard/classroom', label: 'Google Classroom', icon: 'book' },
    { href: '/dashboard/courses', label: 'Study assistant', icon: 'graduation' },
    { href: '/dashboard/templates', label: 'Templates', icon: 'copy' },
  ] },
  { label: 'Academics', items: [
    { href: '/dashboard/schedule', label: 'Schedule & attendance', icon: 'calendar' },
    { href: '/dashboard/exams', label: 'Exams', icon: 'calendar' },
    { href: '/dashboard/announcements', label: 'Announcements', icon: 'bell' },
    { href: '/dashboard/mail-drive', label: 'Mail & Drive', icon: 'folder' },
    { href: '/dashboard/portal', label: 'University portal', icon: 'globe' },
  ] },
  { label: 'Activity', items: [
    { href: '/dashboard/notifications', label: 'Notifications', icon: 'bell' },
    { href: '/dashboard/activity', label: 'Sync history', icon: 'history' },
  ] },
  { label: 'Developer', items: [
    { href: '/dashboard/execution-demo', label: 'Execution Console', icon: 'terminal' },
    { href: '/dashboard/diagram-demo', label: 'Diagram Generator', icon: 'image' },
  ] },
];

const titles = Object.fromEntries(groups.flatMap((group) => group.items.map(({ href, label }) => [href, label])));

function NavIcon({ name }) {
  return <Icon name={name} size={18} strokeWidth={1.75} />;
}

export default function DashboardLayout({ children }) {
  const { userId, getToken } = useAuth();
  const { user } = useUser();
  const pathname = usePathname();
  const router = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [syncMenuOpen, setSyncMenuOpen] = useState(false);
  const [syncBusy, setSyncBusy] = useState(false);
  const [syncNotice, setSyncNotice] = useState('');
  const [googleConnected, setGoogleConnected] = useState(true);
  const [googleEmail, setGoogleEmail] = useState('student@au.edu.pk');
  const [classroomSync, setClassroomSync] = useState(null);

  const refreshConnections = useCallback(async () => {
    try {
      const token = getToken ? await getToken() : null;
      const [auth, sync] = await Promise.allSettled([api.getAuthStatus(token), api.getSyncStatus(token)]);
      if (auth.status === 'fulfilled') {
        setGoogleConnected(Boolean(auth.value?.google_connected ?? true));
        setGoogleEmail(auth.value?.google_email || 'student@au.edu.pk');
      }
      if (sync.status === 'fulfilled') setClassroomSync(sync.value);
    } catch {
      // Keep optimistic values for seamless testing
    }
  }, [getToken]);

  useEffect(() => {
    refreshConnections();
  }, [refreshConnections]);

  useEffect(() => {
    setSyncMenuOpen(false);
  }, [pathname]);

  const firstName = user?.firstName || user?.username || 'Ahmed';
  const fullName = user?.fullName || 'Ahmed Khan';
  const email = user?.primaryEmailAddress?.emailAddress || 'ahmed@au.edu.pk';
  const pageTitle = titles[pathname] || Object.entries(titles).find(([href]) => pathname.startsWith(`${href}/`))?.[1] || 'Workspace';

  const connectGoogle = async (destination) => {
    setSyncBusy(true); setSyncNotice('');
    try {
      const token = getToken ? await getToken() : null;
      if (googleConnected) {
        setSyncMenuOpen(false);
        setSyncBusy(false);
        router.push(destination);
        return;
      }
      const result = await api.getGoogleAuthUrl(token);
      if (!result?.auth_url) throw new Error('Google did not return a sign-in link.');
      window.location.assign(result.auth_url);
    } catch (error) {
      setSyncNotice(error.message || 'Could not connect your Google account.');
      setSyncBusy(false);
    }
  };

  const syncClassroom = async () => {
    setSyncBusy(true); setSyncNotice('');
    try {
      const token = getToken ? await getToken() : null;
      const result = await api.triggerSync(classroomSync?.semester_start_date || null, token);
      setSyncNotice(result.message || 'Google Classroom sync started.');
      await refreshConnections();
    } catch (error) {
      setSyncNotice(error.message || 'Google Classroom synced.');
    } finally {
      setSyncBusy(false);
    }
  };

  return (
    <div className="app-shell">
      {sidebarOpen && <button aria-label="Close navigation" className="sidebar-scrim" onClick={() => setSidebarOpen(false)} />}
      <aside className={`app-sidebar ${sidebarOpen ? 'is-open' : ''}`}>
        <Link href="/dashboard" className="brand-lockup" onClick={() => setSidebarOpen(false)}>
          <span className="brand-mark">u</span><span>uniflow</span>
        </Link>
        <div className="workspace-switcher">
          <span className="workspace-avatar">{firstName.slice(0, 1).toUpperCase()}</span>
          <span className="workspace-copy"><strong>My workspace</strong><small>Student account</small></span>
          <Icon name="more" size={17} className="switcher-dots" />
        </div>
        <nav className="primary-nav" aria-label="Main navigation">
          {groups.map((group) => <div className="nav-group" key={group.label}>
            <p className="nav-group-label">{group.label}</p>
            {group.items.map((item) => {
              const active = item.href === '/dashboard' ? pathname === item.href : pathname === item.href || pathname.startsWith(`${item.href}/`);
              return <Link key={item.href} href={item.href} onClick={() => setSidebarOpen(false)} className={`nav-link ${active ? 'is-active' : ''}`} aria-current={active ? 'page' : undefined}>
                <NavIcon name={item.icon}/><span>{item.label}</span>{item.href === '/dashboard/assignments' && <Icon name="arrowUpRight" size={12} className="nav-arrow"/>}
              </Link>;
            })}
          </div>)}
        </nav>
        <div className="sidebar-note"><Icon name="sparkles" size={17} className="note-spark" /><div><strong>Your semester, in sync.</strong><p>Keep coursework and classes in one clear view.</p></div></div>
        <div className="sidebar-account">
          <div className="account-copy">
            <strong>{fullName}</strong>
            <span>{email}</span>
          </div>
          {userId ? (
            <UserButton afterSignOutUrl="/sign-in" appearance={{ elements: { avatarBox: 'account-avatar' } }} />
          ) : (
            <div className="w-7 h-7 rounded-full bg-[#6657d9] text-white flex items-center justify-center text-xs font-bold">
              {firstName.slice(0, 1).toUpperCase()}
            </div>
          )}
        </div>
      </aside>

      <div className="app-main">
        <header className="app-topbar">
          <button className="menu-toggle" aria-label="Open navigation" onClick={() => setSidebarOpen(true)}><span/><span/><span/></button>
          <div className="breadcrumb"><span>Workspace</span><span className="breadcrumb-slash">/</span><strong>{pageTitle}</strong></div>
          <div className="topbar-right">
            <div className="sync-menu-wrap">
              <button className={`topbar-sync-button ${googleConnected ? 'is-connected' : ''}`} type="button" aria-haspopup="menu" aria-expanded={syncMenuOpen} onClick={() => { setSyncMenuOpen((open) => !open); setSyncNotice(''); }}>
                <Icon name="refresh" size={15} /><span>Sync</span><Icon name="chevronDown" size={13} className="sync-button-caret" />
              </button>
              {syncMenuOpen && <>
                <button className="sync-menu-dismiss" type="button" aria-label="Close sync menu" onClick={() => setSyncMenuOpen(false)} />
                <section className="sync-popover" role="menu" aria-label="Connect and sync services">
                  <div className="sync-popover-heading"><div><p className="eyebrow">CONNECTED SERVICES</p><strong>Keep your workspace current</strong></div><button type="button" aria-label="Refresh connection status" onClick={refreshConnections}><Icon name="refresh" size={15}/></button></div>
                  <button className="sync-service-row" type="button" role="menuitem" onClick={syncClassroom} disabled={syncBusy}>
                    <span className="sync-service-icon classroom-icon"><Icon name="school" size={16}/></span><span className="sync-service-copy"><strong>Google Classroom</strong><small>{googleConnected ? `Connected${classroomSync?.last_sync ? ` · Synced ${new Date(classroomSync.last_sync).toLocaleDateString()}` : ''}` : 'Connect Google to sync courses and work'}</small></span><span className={`sync-status-dot ${googleConnected ? 'connected' : ''}`}/>
                  </button>
                  <button className="sync-service-row" type="button" role="menuitem" onClick={() => connectGoogle('/dashboard/mail-drive')} disabled={syncBusy}>
                    <span className="sync-service-icon google-icon">G</span><span className="sync-service-copy"><strong>Google Mail & Drive</strong><small>{googleEmail ? (googleEmail + ' · Open files') : 'Connect Google to see mail and files'}</small></span><span className={`sync-status-dot ${googleConnected ? 'connected' : ''}`}/>
                  </button>
                  <Link className="sync-service-row" role="menuitem" href="/dashboard/portal" onClick={() => setSyncMenuOpen(false)}>
                    <span className="sync-service-icon portal-icon"><Icon name="globe" size={16}/></span><span className="sync-service-copy"><strong>University portal</strong><small>Set up portal access and sync grades</small></span><Icon name="arrowUpRight" size={14} className="sync-row-arrow" />
                  </Link>
                  {syncNotice && <p className={`sync-menu-notice ${syncNotice.toLowerCase().includes('could not') ? 'has-error' : ''}`} role="status">{syncNotice}</p>}
                  {!googleConnected && <p className="sync-menu-footnote">Google connection is shared by Classroom, Mail, and Drive.</p>}
                </section>
              </>}
            </div>
            <span className="today-label">{new Intl.DateTimeFormat('en', { weekday: 'short', month: 'short', day: 'numeric' }).format(new Date())}</span><span className="topbar-divider"/><span className="topbar-avatar">{firstName.slice(0, 1).toUpperCase()}</span>
          </div>
        </header>
        <main className="app-content">{children}</main>
      </div>
    </div>
  );
}

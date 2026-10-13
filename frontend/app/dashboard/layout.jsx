'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth, useClerk, useUser, UserButton } from '@clerk/nextjs';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';
import FirebaseAlertsBanner from '@/app/dashboard/FirebaseAlertsBanner';

const groups = [
  { label: 'Home', items: [
    { href: '/dashboard', label: 'Overview', icon: 'dashboard' },
  ] },
  { label: 'Study & coursework', items: [
    { href: '/dashboard/assignments', label: 'Assignments Studio', icon: 'listChecks' },
    { href: '/dashboard/courses', label: 'Study assistant', icon: 'brain' },
    { href: '/dashboard/exams', label: 'Study planner', icon: 'calendarCheck' },
    { href: '/dashboard/quizzes', label: 'Quizzes', icon: 'help' },
  ] },
  { label: 'Semester', items: [
    { href: '/dashboard/timetable', label: 'Timetable', icon: 'calendar' },
    { href: '/dashboard/attendance', label: 'Attendance', icon: 'clipboardCheck' },
  ] },
  { label: 'Connected services', items: [
    { href: '/dashboard/classroom', label: 'Google Classroom', icon: 'book' },
    { href: '/dashboard/portal', label: 'University Portal', icon: 'globe' },
    { href: '/dashboard/mail-drive', label: 'Mail & Drive', icon: 'folder' },
  ] },
  { label: 'Activity & updates', items: [
    { href: '/dashboard/activity', label: 'Sync history', icon: 'history' },
    { href: '/dashboard/announcements', label: 'Announcements', icon: 'bell' },
    { href: '/dashboard/notifications', label: 'Alerts & notices', icon: 'alert' },
  ] },
  { label: 'Account', items: [
    { href: '/dashboard/settings', label: 'Settings', icon: 'settings' },
  ] },
];

const titles = {
  ...Object.fromEntries(groups.flatMap((group) => group.items.map(({ href, label }) => [href, label]))),
  '/dashboard/schedule': 'Timetable',
};

function NavIcon({ name }) {
  return <Icon name={name} size={18} strokeWidth={1.75} />;
}

export default function DashboardLayout({ children }) {
  const { userId, getToken } = useAuth();
  const { signOut } = useClerk();
  const { user } = useUser();
  const pathname = usePathname();
  const router = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [syncMenuPath, setSyncMenuPath] = useState(null);
  const [syncBusy, setSyncBusy] = useState(false);
  const [syncNotice, setSyncNotice] = useState('');
  const [mounted, setMounted] = useState(false);
  const [googleConnected, setGoogleConnected] = useState(false);
  const [googleEmail, setGoogleEmail] = useState('');
  const [classroomSync, setClassroomSync] = useState(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  const syncMenuOpen = syncMenuPath === pathname;

  const loadConnections = useCallback(async () => {
    const token = getToken ? await getToken() : null;
    return Promise.allSettled([api.getAuthStatus(token), api.getSyncStatus(token)]);
  }, [getToken]);

  useEffect(() => {
    let cancelled = false;
    const refreshInitialConnections = async () => {
      try {
        const [auth, sync] = await loadConnections();
        if (cancelled) return;
        if (auth.status === 'fulfilled') {
          setGoogleConnected(Boolean(auth.value?.google_connected));
          setGoogleEmail(auth.value?.google_email || '');
        }
        if (sync.status === 'fulfilled') setClassroomSync(sync.value);
      } catch {
        // Keep the current connection values if the status request fails.
      }
    };
    refreshInitialConnections();
    return () => { cancelled = true; };
  }, [loadConnections]);

  const refreshConnections = useCallback(async () => {
    try {
      const [auth, sync] = await loadConnections();
      if (auth.status === 'fulfilled') {
        setGoogleConnected(Boolean(auth.value?.google_connected));
        setGoogleEmail(auth.value?.google_email || '');
      }
      if (sync.status === 'fulfilled') setClassroomSync(sync.value);
    } catch {
      // Keep the current connection values if the status request fails.
    }
  }, [loadConnections]);

  const firstName = user?.firstName || user?.username || 'Ahmed';
  const fullName = user?.fullName || 'Ahmed Khan';
  const email = user?.primaryEmailAddress?.emailAddress || 'ahmed@au.edu.pk';
  const pageTitle = titles[pathname] || Object.entries(titles).find(([href]) => pathname.startsWith(`${href}/`))?.[1] || 'Workspace';
  const handleSignOut = () => {
    if (userId) {
      return signOut({ redirectUrl: '/sign-in' });
    }
    router.push('/sign-in');
  };

  const connectGoogle = async (destination) => {
    setSyncBusy(true); setSyncNotice('');
    try {
      const token = getToken ? await getToken() : null;
      if (googleConnected) {
        setSyncMenuPath(null);
        setSyncBusy(false);
        router.push(destination);
        return;
      }
      const result = await api.getGoogleAuthUrl(token, destination);
      if (!result?.auth_url) throw new Error('Google did not return a sign-in link.');
      window.location.assign(result.auth_url);
    } catch (error) {
      setSyncNotice(error.message || 'Could not connect your Google account.');
      setSyncBusy(false);
    }
  };

  const syncClassroom = async () => {
    if (!googleConnected) {
      await connectGoogle('/dashboard/classroom');
      return;
    }

    setSyncBusy(true); setSyncNotice('');
    try {
      const token = getToken ? await getToken() : null;
      const result = await api.triggerSync(classroomSync?.semester_start_date || null, token);
      setSyncNotice(result.message || 'Google Classroom sync started.');
      await refreshConnections();
    } catch (error) {
      setSyncNotice(error.message || 'Could not start Google Classroom sync.');
    } finally {
      setSyncBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-paper">
      {sidebarOpen && <button aria-label="Close navigation" className="fixed inset-0 z-40 bg-black/40 lg:hidden" onClick={() => setSidebarOpen(false)} />}
      <aside className={`fixed inset-y-0 left-0 z-50 w-64 flex flex-col bg-surface border-r border-line lg:translate-x-0 transition-transform duration-200 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}`}>
        <Link href="/dashboard" className="flex items-center gap-2.5 px-3 pb-6 text-ink text-xl font-bold tracking-tight hover:opacity-80" onClick={() => setSidebarOpen(false)}>
          <span className="size-8 grid place-items-center flex-shrink-0 rounded-lg bg-violet text-white text-2xl font-bold font-serif leading-none">u</span>
          <span>uniflow</span>
        </Link>
        <div className="flex items-center gap-2.5 min-h-[60px] px-3 mb-5 bg-surface-secondary border border-border-light rounded-lg">
          <span className="size-8 flex-shrink-0 grid place-items-center rounded-lg bg-violet-light text-violet text-xs font-bold">{firstName.slice(0, 1).toUpperCase()}</span>
          <span className="flex-1 min-w-0 flex flex-col gap-1">
            <strong className="text-sm font-semibold">My workspace</strong>
            <small className="text-muted text-xs">Student account</small>
          </span>
          <Icon name="more" size={17} className="text-muted" />
        </div>
        <nav className="flex-1 flex flex-col gap-5 overflow-y-auto" aria-label="Main navigation">
          {groups.map((group) => (
            <div key={group.label}>
              <p className="px-3 mb-1.5 text-xs font-semibold uppercase tracking-wider text-muted">{group.label}</p>
              {group.items.map((item) => {
                const active = item.href === '/dashboard' ? pathname === item.href : pathname === item.href || pathname.startsWith(`${item.href}/`);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setSidebarOpen(false)}
                    className={`flex items-center gap-3 h-10 px-3 rounded-md text-sm font-medium transition-colors duration-150 ${active ? 'bg-violet-light text-violet-dark font-semibold' : 'text-text-nav hover:bg-surface-hover hover:text-violet-dark'}`}
                    aria-current={active ? 'page' : undefined}
                  >
                    <NavIcon name={item.icon} className={`${active ? 'text-violet' : 'text-subtle'}`} />
                    <span>{item.label}</span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="flex items-start gap-2.5 p-3 rounded-lg bg-surface-violet mx-3 mb-4">
          <Icon name="sparkles" size={17} className="size-5 grid place-items-center rounded-md bg-violet-light text-violet flex-shrink-0" />
          <div>
            <strong className="block mb-1 text-sm font-semibold text-ink">Your semester, in sync.</strong>
            <p className="text-xs leading-relaxed text-muted">Keep coursework and classes in one clear view.</p>
          </div>
        </div>
        <div className="flex flex-col gap-2.5 px-1 pt-3 border-t border-border-light">
          <div className="flex items-center gap-2">
            <div className="flex-1 min-w-0 flex flex-col gap-1">
              <strong className="text-sm font-semibold truncate">{fullName}</strong>
              <span className="text-xs text-muted truncate">{email}</span>
            </div>
            {mounted && userId ? (
              <UserButton afterSignOutUrl="/sign-in" appearance={{ elements: { avatarBox: 'size-7' } }} />
            ) : (
              <div className="size-7 rounded-full bg-violet text-white flex items-center justify-center text-xs font-bold" suppressHydrationWarning>
                {firstName.slice(0, 1).toUpperCase()}
              </div>
            )}
          </div>
          {mounted && (
            <button className="w-full min-h-[34px] px-2.5 border border-border rounded-md bg-surface text-text-nav text-sm font-medium text-left cursor-pointer transition-all duration-150 hover:border-border-hover hover:bg-surface-hover hover:text-violet-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet" type="button" onClick={handleSignOut}>
              Sign out
            </button>
          )}
        </div>
      </aside>

      <div className="lg:ml-64 min-h-screen">
        <header className="sticky top-0 z-20 h-16 flex items-center justify-between px-6 bg-surface/92 border-b border-border-light backdrop-blur-md lg:px-10">
          <button className="lg:hidden size-8 flex flex-col justify-center gap-1 p-1.5 border border-border-light rounded-md bg-surface" aria-label="Open navigation" onClick={() => setSidebarOpen(true)}>
            <span className="h-[1.5px] w-[15px] bg-text-nav" />
            <span className="h-[1.5px] w-[15px] bg-text-nav" />
            <span className="h-[1.5px] w-[15px] bg-text-nav" />
          </button>
          <div className="flex items-center gap-2 text-sm text-muted">
            <span>Workspace</span>
            <span className="text-subtle">/</span>
            <strong className="text-body font-semibold">{pageTitle}</strong>
          </div>
          <div className="flex items-center gap-4">
            <div className="relative">
              <button
                className={`flex items-center gap-1.5 h-8 px-3 border rounded-md bg-surface text-sm font-semibold cursor-pointer transition-all duration-150 ${mounted && googleConnected ? "after:ml-px after:size-1.5 after:rounded-full after:bg-success after:content-['']" : ''}`}
                type="button"
                aria-haspopup="menu"
                aria-expanded={syncMenuOpen}
                onClick={() => { setSyncMenuPath(syncMenuOpen ? null : pathname); setSyncNotice(''); }}
                suppressHydrationWarning
              >
                <Icon name="refresh" size={15} />
                <span>Sync</span>
                <Icon name="chevronDown" size={13} className="text-muted" />
              </button>
              {syncMenuOpen && (
                <>
                  <button className="fixed inset-0 z-10" type="button" aria-label="Close sync menu" onClick={() => setSyncMenuPath(null)} />
                  <section className="absolute z-20 top-full -right-10 mt-3 w-[350px] max-w-[calc(100vw-30px)] p-2.5 border border-border rounded-xl bg-surface shadow-dropdown" role="menu" aria-label="Connect and sync services">
                    <div className="flex items-center justify-between p-2 mb-3 border-b border-border-light">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-wider text-muted">CONNECTED SERVICES</p>
                        <strong className="block mt-1 text-sm font-semibold text-body">Keep your workspace current</strong>
                      </div>
                      <button type="button" aria-label="Refresh connection status" onClick={refreshConnections} className="size-7 border border-border-light rounded-md bg-surface text-muted text-xl cursor-pointer">
                        <Icon name="refresh" size={15} />
                      </button>
                    </div>
                    <button className="w-full min-h-[59px] flex items-center gap-2.5 p-2.5 border-0 border-b border-border-light bg-surface text-left cursor-pointer hover:rounded-md hover:bg-surface-hover disabled:opacity-60 disabled:cursor-wait" type="button" role="menuitem" onClick={syncClassroom} disabled={syncBusy}>
                      <span className="size-7 grid place-items-center flex-shrink-0 rounded-md bg-violet-light text-violet text-sm font-bold"><Icon name="school" size={16} /></span>
                      <span className="flex-1 min-w-0 flex flex-col gap-1">
                        <strong className="text-sm font-semibold text-body">Google Classroom</strong>
                        <small className="text-xs text-muted">{googleConnected ? `Connected${classroomSync?.last_sync ? ` · Synced ${new Date(classroomSync.last_sync).toLocaleDateString()}` : ''}` : 'Connect Google to sync courses and work'}</small>
                      </span>
                      <span className={`size-1.5 rounded-full ${mounted && googleConnected ? 'bg-success' : 'bg-transparent'}`} />
                    </button>
                    <button className="w-full min-h-[59px] flex items-center gap-2.5 p-2.5 border-0 border-b border-border-light bg-surface text-left cursor-pointer hover:rounded-md hover:bg-surface-hover disabled:opacity-60 disabled:cursor-wait" type="button" role="menuitem" onClick={() => connectGoogle('/dashboard/mail-drive')} disabled={syncBusy}>
                      <span className="size-7 grid place-items-center flex-shrink-0 rounded-md bg-google-bg text-google text-sm font-bold">G</span>
                      <span className="flex-1 min-w-0 flex flex-col gap-1">
                        <strong className="text-sm font-semibold text-body">Google Mail & Drive</strong>
                        <small className="text-xs text-muted">{googleEmail ? (googleEmail + ' · Open files') : 'Connect Google to see mail and files'}</small>
                      </span>
                      <span className={`size-1.5 rounded-full ${mounted && googleConnected ? 'bg-success' : 'bg-transparent'}`} />
                    </button>
                    <Link className="w-full min-h-[59px] flex items-center gap-2.5 p-2.5 border-0 bg-surface text-left hover:rounded-md hover:bg-surface-hover" role="menuitem" href="/dashboard/portal" onClick={() => setSyncMenuPath(null)}>
                      <span className="size-7 grid place-items-center flex-shrink-0 rounded-md bg-cyan-bg text-cyan text-sm font-bold"><Icon name="globe" size={16} /></span>
                      <span className="flex-1 min-w-0 flex flex-col gap-1">
                        <strong className="text-sm font-semibold text-body">University portal</strong>
                        <small className="text-xs text-muted">Set up portal access and sync grades</small>
                      </span>
                      <Icon name="arrowUpRight" size={14} className="text-subtle" />
                    </Link>
                    {syncNotice && (
                      <p className={`p-2.5 text-sm ${syncNotice.toLowerCase().includes('could not') ? 'text-rose' : 'text-amber'}`} role="status">{syncNotice}</p>
                    )}
                    {mounted && !googleConnected && (
                      <p className="p-2.5 text-xs text-muted">Google connection is shared by Classroom, Mail, and Drive.</p>
                    )}
                  </section>
                </>
              )}
            </div>
            <span className="hidden lg:block text-sm text-muted" suppressHydrationWarning>{new Intl.DateTimeFormat('en', { weekday: 'short', month: 'short', day: 'numeric' }).format(new Date())}</span>
            <span className="hidden lg:block w-px h-5 bg-border" />
            <span className="size-7 flex-shrink-0 grid place-items-center rounded-full bg-violet-light text-violet text-xs font-bold" suppressHydrationWarning>{firstName.slice(0, 1).toUpperCase()}</span>
          </div>
        </header>
        <main className="mx-auto min-h-[calc(100vh-64px)] w-full max-w-7xl px-4 pb-10 text-sm leading-6 sm:px-6 lg:px-10">
          <FirebaseAlertsBanner />
          {children}
        </main>
      </div>
    </div>
  );
}

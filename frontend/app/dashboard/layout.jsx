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
      <aside className={`fixed inset-y-0 left-0 z-50 w-[256px] flex flex-col bg-white border-r border-line lg:translate-x-0 transition-transform duration-200 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}`}>
        <Link href="/dashboard" className="flex items-center gap-2.5 px-2.75 pb-5.5 text-ink text-xl font-bold tracking-tight hover:opacity-80" onClick={() => setSidebarOpen(false)}>
          <span className="w-8 h-8 grid place-items-center flex-shrink-0 rounded-[11px] bg-violet text-white text-2xl font-bold font-serif leading-none">u</span>
          <span>uniflow</span>
        </Link>
        <div className="flex items-center gap-2.5 min-h-[60px] px-2.5 mb-5.25 bg-[#f8f8fb] border border-[#f0f0f4] rounded-[11px]">
          <span className="w-8 h-8 flex-shrink-0 grid place-items-center rounded-[10px] bg-[#eeeaff] text-violet text-xs font-bold">{firstName.slice(0, 1).toUpperCase()}</span>
          <span className="flex-1 min-w-0 flex flex-col gap-1">
            <strong className="text-sm font-semibold">My workspace</strong>
            <small className="text-[#747887] text-xs">Student account</small>
          </span>
          <Icon name="more" size={17} className="text-[#9a9cab]" />
        </div>
        <nav className="flex-1 flex flex-col gap-4.5 overflow-y-auto" aria-label="Main navigation">
          {groups.map((group) => (
            <div key={group.label}>
              <p className="px-2.75 mb-1.75 text-xs font-semibold uppercase tracking-[0.04em] text-[#777b89]">{group.label}</p>
              {group.items.map((item) => {
                const active = item.href === '/dashboard' ? pathname === item.href : pathname === item.href || pathname.startsWith(`${item.href}/`);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setSidebarOpen(false)}
                    className={`flex items-center gap-2.75 h-10 px-2.75 rounded-[9px] text-sm font-medium transition-colors duration-150 ${active ? 'bg-violet-light text-violet-dark font-semibold' : 'text-[#626675] hover:bg-[#f7f6fc] hover:text-violet-dark'}`}
                    aria-current={active ? 'page' : undefined}
                  >
                    <NavIcon name={item.icon} className={`${active ? 'text-violet' : 'text-[#9699a7]'}`} />
                    <span>{item.label}</span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="flex items-start gap-2.5 p-3.25 rounded-[10px] bg-[#f6f5ff] mx-2.75 mb-4">
          <Icon name="sparkles" size={17} className="w-5.75 h-5.75 grid place-items-center rounded-[7px] bg-[#e8e4ff] text-violet flex-shrink-0" />
          <div>
            <strong className="block mb-1 text-sm font-semibold text-[#3b3760]">Your semester, in sync.</strong>
            <p className="text-xs leading-relaxed text-[#6f6b8a]">Keep coursework and classes in one clear view.</p>
          </div>
        </div>
        <div className="flex flex-col gap-2.5 px-1.25 pt-3.25 border-t border-[#f0f0f3]">
          <div className="flex items-center gap-2">
            <div className="flex-1 min-w-0 flex flex-col gap-1">
              <strong className="text-sm font-semibold truncate">{fullName}</strong>
              <span className="text-xs text-[#747887] truncate">{email}</span>
            </div>
            {mounted && userId ? (
              <UserButton afterSignOutUrl="/sign-in" appearance={{ elements: { avatarBox: 'w-7 h-7' } }} />
            ) : (
              <div className="w-7 h-7 rounded-full bg-violet text-white flex items-center justify-center text-xs font-bold" suppressHydrationWarning>
                {firstName.slice(0, 1).toUpperCase()}
              </div>
            )}
          </div>
          {mounted && (
            <button className="w-full min-h-[34px] px-2.5 border border-[#e9e8f0] rounded-[8px] bg-white text-[#55596a] text-sm font-medium text-left cursor-pointer transition-all duration-150 hover:border-[#dedaf7] hover:bg-[#f7f6fc] hover:text-violet-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet" type="button" onClick={handleSignOut}>
              Sign out
            </button>
          )}
        </div>
      </aside>

      <div className="lg:ml-[256px] min-h-screen">
        <header className="sticky top-0 z-20 h-[61px] flex items-center justify-between px-10.5 bg-white/92 border-b border-[#eeeef2] backdrop-blur-[14px] lg:px-10.5">
          <button className="lg:hidden w-7.5 h-7.5 flex flex-col justify-center gap-1 p-1.5 border border-[#ededf1] rounded-[7px] bg-white" aria-label="Open navigation" onClick={() => setSidebarOpen(true)}>
            <span className="h-[1.5px] w-[15px] bg-[#616475]" />
            <span className="h-[1.5px] w-[15px] bg-[#616475]" />
            <span className="h-[1.5px] w-[15px] bg-[#616475]" />
          </button>
          <div className="flex items-center gap-2.25 text-sm text-[#747887]">
            <span>Workspace</span>
            <span className="text-[#d0d1d8]">/</span>
            <strong className="text-[#424554] font-semibold">{pageTitle}</strong>
          </div>
          <div className="flex items-center gap-3.75">
            <div className="relative">
              <button
                className={`flex items-center gap-1.75 h-8 px-2.75 border rounded-[8px] bg-white text-sm font-semibold cursor-pointer transition-all duration-150 ${mounted && googleConnected ? "after:ml-px after:size-1.5 after:rounded-full after:bg-[#5bb28e] after:content-['']" : ''}`}
                type="button"
                aria-haspopup="menu"
                aria-expanded={syncMenuOpen}
                onClick={() => { setSyncMenuPath(syncMenuOpen ? null : pathname); setSyncNotice(''); }}
                suppressHydrationWarning
              >
                <Icon name="refresh" size={15} />
                <span>Sync</span>
                <Icon name="chevronDown" size={13} className="text-[#9993bd]" />
              </button>
              {syncMenuOpen && (
                <>
                  <button className="fixed inset-0 z-10" type="button" aria-label="Close sync menu" onClick={() => setSyncMenuPath(null)} />
                  <section className="absolute z-20 top-full right-[-38px] mt-2.75 w-[350px] max-w-[calc(100vw-30px)] p-2.5 border border-[#e9e8ef] rounded-[12px] bg-white shadow-[0_16px_42px_rgba(41,35,68,0.11)]" role="menu" aria-label="Connect and sync services">
                    <div className="flex items-center justify-between p-2 mb-3 border-b border-[#f0f0f4]">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[#77759a]">CONNECTED SERVICES</p>
                        <strong className="block mt-1 text-sm font-semibold text-[#424554]">Keep your workspace current</strong>
                      </div>
                      <button type="button" aria-label="Refresh connection status" onClick={refreshConnections} className="w-7 h-7 border border-[#ecebf1] rounded-[7px] bg-white text-[#777b8a] text-xl cursor-pointer">
                        <Icon name="refresh" size={15} />
                      </button>
                    </div>
                    <button className="w-full min-h-[59px] flex items-center gap-2.5 p-2.5 border-0 border-b border-[#f3f3f6] bg-white text-left cursor-pointer hover:rounded-[8px] hover:bg-[#faf9fd] disabled:opacity-60 disabled:cursor-wait" type="button" role="menuitem" onClick={syncClassroom} disabled={syncBusy}>
                      <span className="w-7.25 h-7.25 grid place-items-center flex-shrink-0 rounded-[8px] bg-violet-light text-violet text-sm font-bold"><Icon name="school" size={16} /></span>
                      <span className="flex-1 min-w-0 flex flex-col gap-1">
                        <strong className="text-sm font-semibold text-[#424554]">Google Classroom</strong>
                        <small className="text-xs text-[#747887]">{googleConnected ? `Connected${classroomSync?.last_sync ? ` · Synced ${new Date(classroomSync.last_sync).toLocaleDateString()}` : ''}` : 'Connect Google to sync courses and work'}</small>
                      </span>
                      <span className={`w-1.5 h-1.5 rounded-full ${mounted && googleConnected ? 'bg-[#5bb28e]' : 'bg-transparent'}`} />
                    </button>
                    <button className="w-full min-h-[59px] flex items-center gap-2.5 p-2.5 border-0 border-b border-[#f3f3f6] bg-white text-left cursor-pointer hover:rounded-[8px] hover:bg-[#faf9fd] disabled:opacity-60 disabled:cursor-wait" type="button" role="menuitem" onClick={() => connectGoogle('/dashboard/mail-drive')} disabled={syncBusy}>
                      <span className="w-7.25 h-7.25 grid place-items-center flex-shrink-0 rounded-[8px] bg-[#e8f0fe] text-[#4285f4] text-sm font-bold">G</span>
                      <span className="flex-1 min-w-0 flex flex-col gap-1">
                        <strong className="text-sm font-semibold text-[#424554]">Google Mail & Drive</strong>
                        <small className="text-xs text-[#747887]">{googleEmail ? (googleEmail + ' · Open files') : 'Connect Google to see mail and files'}</small>
                      </span>
                      <span className={`w-1.5 h-1.5 rounded-full ${mounted && googleConnected ? 'bg-[#5bb28e]' : 'bg-transparent'}`} />
                    </button>
                    <Link className="w-full min-h-[59px] flex items-center gap-2.5 p-2.5 border-0 bg-white text-left hover:rounded-[8px] hover:bg-[#faf9fd]" role="menuitem" href="/dashboard/portal" onClick={() => setSyncMenuPath(null)}>
                      <span className="w-7.25 h-7.25 grid place-items-center flex-shrink-0 rounded-[8px] bg-[#f0f5ff] text-cyan text-sm font-bold"><Icon name="globe" size={16} /></span>
                      <span className="flex-1 min-w-0 flex flex-col gap-1">
                        <strong className="text-sm font-semibold text-[#424554]">University portal</strong>
                        <small className="text-xs text-[#747887]">Set up portal access and sync grades</small>
                      </span>
                      <Icon name="arrowUpRight" size={14} className="text-[#b7b9c3]" />
                    </Link>
                    {syncNotice && (
                      <p className={`p-2.5 text-sm ${syncNotice.toLowerCase().includes('could not') ? 'text-rose' : 'text-amber'}`} role="status">{syncNotice}</p>
                    )}
                    {mounted && !googleConnected && (
                      <p className="p-2.5 text-xs text-[#747887]">Google connection is shared by Classroom, Mail, and Drive.</p>
                    )}
                  </section>
                </>
              )}
            </div>
            <span className="hidden lg:block text-sm text-[#747887]" suppressHydrationWarning>{new Intl.DateTimeFormat('en', { weekday: 'short', month: 'short', day: 'numeric' }).format(new Date())}</span>
            <span className="hidden lg:block w-px h-[22px] bg-[#ebebf0]" />
            <span className="w-7.25 h-7.25 flex-shrink-0 grid place-items-center rounded-full bg-[#eeeaff] text-violet text-xs font-bold" suppressHydrationWarning>{firstName.slice(0, 1).toUpperCase()}</span>
          </div>
        </header>
        <main className="mx-auto min-h-[calc(100vh-61px)] w-full max-w-[1320px] px-4 pb-10 text-sm leading-6 sm:px-6 lg:px-10">
          <FirebaseAlertsBanner />
          {children}
        </main>
      </div>
    </div>
  );
}
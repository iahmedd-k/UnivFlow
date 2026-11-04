'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth, useClerk, useUser, UserButton } from '@clerk/nextjs';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { api } from '@/app/lib/api';
import { getManualSession, getQueryOwnerKey, clearManualSession } from '@/app/lib/manual-auth';
import { isExtensionInstalled, EXTENSION_VERSION } from '@/app/lib/extensionBridge';
import Icon from '@/app/dashboard/Icon';
import OnboardingModal from '@/app/dashboard/OnboardingModal';
import CompanionExtensionModal from '@/app/dashboard/CompanionExtensionModal';
import ServiceConnectionPopup from '@/app/dashboard/ServiceConnectionPopup';

const navGroups = [
  {
    label: 'Workspace',
    items: [
      { href: '/dashboard', label: 'Overview', icon: 'dashboard' },
      { href: '/dashboard/planner', label: 'My Planner', icon: 'calendar' },
      { href: '/dashboard/assignments', label: 'Assignments Studio', icon: 'listChecks' },
      { href: '/dashboard/rag-assistant', label: 'Study Assistant', icon: 'brain' },
    ],
  },
  {
    label: 'Academics',
    items: [
      { href: '/dashboard/exams', label: 'Exams', icon: 'clipboardCheck' },
      { href: '/dashboard/timetable', label: 'Timetable', icon: 'calendar' },
      { href: '/dashboard/attendance', label: 'Attendance', icon: 'clipboardCheck' },
      { href: '/dashboard/classroom', label: 'Google Classroom', icon: 'school' },
    ],
  },
  {
    label: 'Services',
    items: [
      { href: '/dashboard/portal', label: 'University Portal', icon: 'globe' },
      { href: '/dashboard/mail-drive', label: 'Mail & Drive', icon: 'folder' },
    ],
  },
  {
    label: 'Preferences',
    items: [
      { href: '/dashboard/settings', label: 'Settings', icon: 'settings' },
    ],
  },
];

const titles = {
  ...Object.fromEntries(navGroups.flatMap((group) => group.items.map(({ href, label }) => [href, label]))),
  '/dashboard/schedule': 'Timetable',
};

function NavIcon({ name, active }) {
  return <Icon name={name} size={17} strokeWidth={active ? 2.1 : 1.75} className={active ? 'text-violet' : 'text-muted'} />;
}

export default function DashboardLayout({ children }) {
  const { userId, getToken } = useAuth();
  const queryClient = useQueryClient();
  const ownerKey = getQueryOwnerKey(userId);
  const { signOut } = useClerk();
  const { user } = useUser();
  const pathname = usePathname();
  const router = useRouter();
  const isStudyAssistant = pathname === '/dashboard/rag-assistant';

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [syncMenuOpen, setSyncMenuOpen] = useState(false);
  const [syncBusy, setSyncBusy] = useState(false);
  const [syncNotice, setSyncNotice] = useState('');
  const [mounted, setMounted] = useState(false);
  const authStatusQuery = useQuery({
    queryKey: ['auth', ownerKey, 'status'],
    queryFn: async ({ signal }) => api.getAuthStatus(await api.getRequestToken(getToken), { signal, direct: true }),
    staleTime: 15_000,
  });
  const syncStatusQuery = useQuery({
    queryKey: ['classroom', 'sync-status', ownerKey],
    queryFn: async ({ signal }) => api.getSyncStatus(await api.getRequestToken(getToken), { signal, direct: true }),
    staleTime: 15_000,
  });
  const accessStatusQuery = useQuery({
    queryKey: ['auth', ownerKey, 'private-access'],
    queryFn: async ({ signal }) => api.getPrivateAccessStatus(await api.getRequestToken(getToken), { signal, direct: true }),
    staleTime: 15_000,
  });
  const googleConnected = Boolean(authStatusQuery.data?.google_connected);
  const googleEmail = authStatusQuery.data?.google_email || '';
  const classroomSync = syncStatusQuery.data || null;
  const privateAccess = accessStatusQuery.data ?? { granted: true };
  const [accessCode, setAccessCode] = useState('');
  const [accessBusy, setAccessBusy] = useState(false);
  const [accessNotice, setAccessNotice] = useState('');
  const [manualSession, setManualSessionState] = useState(null);
  const [extensionInstalled, setExtensionInstalled] = useState(false);
  const [extensionModalOpen, setExtensionModalOpen] = useState(false);

  useEffect(() => {
    setMounted(true);
    setManualSessionState(getManualSession());
    setExtensionInstalled(isExtensionInstalled());

    const handleReady = () => setExtensionInstalled(true);
    window.addEventListener('uniflow-companion-ready', handleReady);
    let attempts = 0;
    const interval = setInterval(() => {
      attempts++;
      if (isExtensionInstalled()) {
        setExtensionInstalled(true);
        clearInterval(interval);
      } else if (attempts >= 10) {
        clearInterval(interval);
      }
    }, 2500);

    return () => {
      window.removeEventListener('uniflow-companion-ready', handleReady);
      clearInterval(interval);
    };
  }, []);

  const requestAccessCode = async () => {
    setAccessBusy(true);
    setAccessNotice('');
    try {
      const token = getToken ? await getToken() : null;
      const primaryEmail = user?.primaryEmailAddress;
      const email = primaryEmail?.emailAddress?.trim();
      if (!userId || !email || primaryEmail?.verification?.status !== 'verified') {
        throw new Error('Your Clerk account needs a verified primary email before requesting workspace access.');
      }
      await api.syncUser({
        userId,
        email,
        firstName: user?.firstName || '',
        lastName: user?.lastName || '',
        imageUrl: user?.imageUrl || '',
      }, token);
      const result = await api.requestPrivateAccess(token);
      setAccessNotice(result.message || 'Request sent to the administrator.');
    } catch (error) {
      setAccessNotice(error.message || 'Could not request access.');
    } finally {
      setAccessBusy(false);
    }
  };

  const redeemAccessCode = async (event) => {
    event.preventDefault();
    setAccessBusy(true);
    setAccessNotice('');
    try {
      const token = getToken ? await getToken() : null;
      await api.redeemPrivateAccess(accessCode, token);
      const granted = { granted: true };
      queryClient.setQueryData(['auth', ownerKey, 'private-access'], granted);
      setAccessNotice('Access approved for this account.');
    } catch (error) {
      setAccessNotice(error.message || 'Could not verify that code.');
    } finally {
      setAccessBusy(false);
    }
  };

  const manualUser = manualSession?.user;
  const firstName = user?.firstName || user?.username || manualUser?.firstName || manualUser?.first_name || 'Ahmed';
  const fullName = user?.fullName || manualUser?.name || 'Ahmed Khan';
  const email = user?.primaryEmailAddress?.emailAddress || manualUser?.email || 'ahmed@au.edu.pk';
  const pageTitle = titles[pathname] || Object.entries(titles).find(([href]) => pathname.startsWith(`${href}/`))?.[1] || 'Workspace';

  const handleSignOut = async () => {
    clearManualSession();
    if (userId && signOut) {
      try {
        await signOut({ redirectUrl: '/sign-in' });
        return;
      } catch (err) {
        console.error('Sign-out error:', err);
      }
    }
    window.location.href = '/sign-in';
  };

  const connectGoogle = async (destination) => {
    setSyncBusy(true);
    setSyncNotice('');
    try {
      const token = getToken ? await getToken() : null;
      if (googleConnected) {
        setSyncMenuOpen(false);
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

    setSyncBusy(true);
    setSyncNotice('');
    try {
      const token = getToken ? await getToken() : null;
      const result = await api.triggerSync(classroomSync?.semester_start_date || null, token);
      api.clearCache();
      setSyncNotice(result.message || 'Google Classroom sync started.');
    } catch (error) {
      setSyncNotice(error.message || 'Could not start Google Classroom sync.');
    } finally {
      setSyncBusy(false);
    }
  };

  if (privateAccess && privateAccess.granted === false && userId) {
    return (
      <main className="grid min-h-screen place-items-center bg-paper p-6">
        <section className="w-full max-w-md rounded-2xl border border-line bg-surface p-7 shadow-sm">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-violet">Private workspace</p>
          <h1 className="text-2xl font-semibold text-ink">Access needs approval</h1>
          <p className="mt-3 text-sm leading-6 text-muted">
            This workspace is limited to approved university fellows. Request a one-time code, then ask the administrator to share it with you.
          </p>
          <p className="mt-4 rounded-lg bg-surface-secondary p-3 text-sm text-body">
            {user?.primaryEmailAddress?.emailAddress || 'Signed-in account'}
          </p>
          {privateAccess.error && <p className="mt-3 text-sm text-rose" role="alert">{privateAccess.error}</p>}
          <button type="button" disabled={accessBusy} onClick={requestAccessCode} className="mt-5 w-full rounded-lg bg-violet px-4 py-3 font-semibold text-white disabled:opacity-60 cursor-pointer">
            {accessBusy ? 'Please wait…' : 'Send approval request'}
          </button>
          <form onSubmit={redeemAccessCode} className="mt-5 border-t border-line pt-5">
            <label htmlFor="private-access-code" className="block text-sm font-medium text-body">Administrator code</label>
            <div className="mt-2 flex gap-2">
              <input id="private-access-code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{8}" maxLength={8} value={accessCode} onChange={(event) => setAccessCode(event.target.value.replace(/\D/g, ''))} className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-center tracking-[0.35em]" placeholder="8-digit code" required />
              <button type="submit" disabled={accessBusy || accessCode.length !== 8} className="rounded-lg border border-line px-4 py-2 font-semibold text-body disabled:opacity-50 cursor-pointer">Unlock</button>
            </div>
          </form>
          {accessNotice && <p className="mt-4 text-sm text-muted" role="status">{accessNotice}</p>}
          <button type="button" onClick={() => signOut({ redirectUrl: '/sign-in' })} className="mt-5 text-sm font-medium text-muted underline cursor-pointer">Sign out</button>
        </section>
      </main>
    );
  }

  return (
    <div className={`${isStudyAssistant ? 'h-dvh overflow-hidden' : 'min-h-screen'} bg-paper flex`}>
      <OnboardingModal />
      <CompanionExtensionModal isOpen={extensionModalOpen} onClose={() => setExtensionModalOpen(false)} />
      {!isStudyAssistant && <ServiceConnectionPopup />}

      {/* Mobile Backdrop */}
      {!isStudyAssistant && sidebarOpen && (
        <button aria-label="Close navigation" className="fixed inset-0 z-40 bg-black/40 backdrop-blur-xs lg:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      {/* Redesigned Sidebar */}
      {!isStudyAssistant && <aside className={`fixed inset-y-0 left-0 z-50 w-64 flex flex-col bg-surface border-r border-line lg:translate-x-0 transition-transform duration-200 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}`}>
        {/* Brand Header */}
        <div className="px-5 pt-5 pb-4 border-b border-border-light flex items-center justify-between">
          <Link href="/dashboard" prefetch={false} className="flex items-center gap-2.5 no-underline group" onClick={() => setSidebarOpen(false)}>
            <div className="size-8.5 rounded-xl bg-gradient-to-tr from-violet to-violet-dark text-white flex items-center justify-center shadow-md shadow-violet/20 font-semibold text-lg">
              u
            </div>
            <div>
              <span className="text-base font-semibold tracking-tight text-heading block leading-none">uniflow</span>
              <span className="text-xs text-muted font-normal tracking-wide">Academic Workspace</span>
            </div>
          </Link>
          <span className="rounded-md bg-violet-light/60 px-2 py-0.5 text-xs font-semibold text-violet-dark">v2.5</span>
        </div>

        {/* Navigation Groups */}
        <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-5" aria-label="Main navigation">
          {navGroups.map((group) => (
            <div key={group.label} className="space-y-1">
              <p className="px-3 mb-1.5 text-xs font-semibold uppercase tracking-wider text-label">{group.label}</p>
              {group.items.map((item) => {
                const active = item.href === '/dashboard' ? pathname === item.href : pathname === item.href || pathname.startsWith(`${item.href}/`);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    prefetch={false}
                    onClick={() => setSidebarOpen(false)}
                    className={`flex items-center gap-3 h-10 px-3 rounded-xl text-sm transition-all duration-150 no-underline ${
                      active
                        ? 'bg-violet-light text-violet-dark font-medium shadow-2xs'
                        : 'text-nav font-normal hover:bg-surface-secondary hover:text-heading hover:font-medium'
                    }`}
                    aria-current={active ? 'page' : undefined}
                  >
                    <NavIcon name={item.icon} active={active} />
                    <span className="flex-1 truncate">{item.label}</span>
                    {active && <span className="size-1.5 rounded-full bg-violet" />}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        {/* Logout Action */}
        <div className="p-3 border-t border-border-light">
          <button
            type="button"
            id="sidebar-logout-btn"
            onClick={handleSignOut}
            className="w-full flex items-center justify-center gap-2 h-10 px-3 rounded-xl border border-rose-border/70 bg-rose-bg/50 text-rose font-medium text-xs transition-all duration-150 hover:bg-rose hover:text-white hover:border-rose hover:shadow-xs active:scale-[0.99] cursor-pointer group"
          >
            <Icon name="logout" size={15} className="transition-transform group-hover:-translate-x-0.5" />
            <span>Log Out</span>
          </button>
        </div>

        {/* User Account Footer */}
        <div className="px-4 py-3 border-t border-border-light flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 min-w-0">
            {mounted && userId ? (
              <UserButton afterSignOutUrl="/sign-in" appearance={{ elements: { avatarBox: 'size-7.5 rounded-lg' } }} />
            ) : (
              <span className="size-7.5 rounded-lg bg-violet text-white grid place-items-center text-xs font-semibold shrink-0">
                {firstName.slice(0, 1).toUpperCase()}
              </span>
            )}
            <div className="min-w-0 flex-1">
              <strong className="block text-sm font-semibold text-heading truncate">{fullName}</strong>
              <small className="block text-xs font-normal text-muted truncate">{email}</small>
            </div>
          </div>
          <button
            type="button"
            onClick={handleSignOut}
            title="Log out"
            aria-label="Log out"
            className="size-7.5 grid place-items-center rounded-lg text-muted hover:text-rose hover:bg-rose-bg/60 transition cursor-pointer"
          >
            <Icon name="logout" size={15} />
          </button>
        </div>
      </aside>}

      {/* Main App Container */}
      <div className={`flex-1 flex flex-col min-w-0 ${isStudyAssistant ? 'h-dvh min-h-0 overflow-hidden' : 'lg:ml-64 min-h-screen'}`}>
        {/* Redesigned Navbar */}
        {!isStudyAssistant && <header className="sticky top-0 z-30 h-16 flex items-center justify-between px-4 sm:px-6 lg:px-8 bg-surface/85 border-b border-border/70 backdrop-blur-xl">
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="lg:hidden size-9 grid place-items-center rounded-xl border border-border bg-surface text-nav hover:bg-surface-secondary cursor-pointer"
              aria-label="Open navigation"
              onClick={() => setSidebarOpen(true)}
            >
              <Icon name="menu" size={18} />
            </button>
            <div className="flex items-center gap-1.5 text-xs">
              <span className="text-muted font-medium">Workspace</span>
              <span className="text-subtle">/</span>
              <strong className="text-heading font-semibold">{pageTitle}</strong>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            {/* Companion Extension Pill Button */}
            <button
              type="button"
              onClick={() => setExtensionModalOpen(true)}
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold transition cursor-pointer shadow-2xs ${
                extensionInstalled
                  ? 'bg-emerald-50 text-emerald-800 border border-emerald-200/80 hover:bg-emerald-100'
                  : 'bg-violet-light text-violet-dark border border-violet/30 hover:bg-violet/20'
              }`}
            >
              <span className={`size-1.5 rounded-full ${extensionInstalled ? 'bg-emerald-600' : 'bg-violet animate-ping'}`} />
              <span>{extensionInstalled ? 'Companion Active' : 'Setup Extension'}</span>
            </button>

            {/* Services Status Pill Button */}
            <button
              type="button"
              onClick={() => {
                if (typeof window !== 'undefined') {
                  window.dispatchEvent(new CustomEvent('uniflow-open-services-popup'));
                }
              }}
              className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold border border-line bg-surface hover:bg-surface-secondary text-body transition cursor-pointer shadow-2xs"
              title="View & Sync Connected Services"
            >
              <Icon name="zap" size={12} className="text-violet" />
              <span className="hidden sm:inline">Services</span>
            </button>

            {/* Sync Menu */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setSyncMenuOpen(!syncMenuOpen)}
                className="inline-flex h-8.5 items-center gap-1.5 rounded-xl border border-border bg-surface px-3 text-xs font-semibold text-heading hover:bg-surface-secondary transition cursor-pointer"
              >
                <Icon name="refresh" size={13} className={syncBusy ? 'animate-spin' : ''} />
                <span className="hidden sm:inline">Sync</span>
                <Icon name="chevronDown" size={11} className="text-muted" />
              </button>

              {syncMenuOpen && (
                <>
                  <button className="fixed inset-0 z-10" type="button" aria-label="Close sync menu" onClick={() => setSyncMenuOpen(false)} />
                  <section className="absolute right-0 top-full mt-2 w-72 rounded-2xl border border-border bg-surface p-2 shadow-xl z-20 animate-in fade-in zoom-in-95 duration-100">
                    <p className="px-3 pt-2 pb-1.5 text-[10px] font-bold uppercase tracking-wider text-muted">Connected Services</p>
                    <button
                      type="button"
                      onClick={() => { syncClassroom(); setSyncMenuOpen(false); }}
                      disabled={syncBusy}
                      className="w-full flex items-center justify-between p-2.5 rounded-xl text-left hover:bg-surface-secondary transition cursor-pointer text-xs font-semibold text-heading"
                    >
                      <span className="flex items-center gap-2">
                        <Icon name="school" size={15} className="text-violet" />
                        <span>Google Classroom</span>
                      </span>
                      <span className={`size-1.5 rounded-full ${googleConnected ? 'bg-emerald-500' : 'bg-muted'}`} />
                    </button>
                    <Link
                      href="/dashboard/portal"
                      prefetch={false}
                      onClick={() => setSyncMenuOpen(false)}
                      className="w-full flex items-center justify-between p-2.5 rounded-xl text-left hover:bg-surface-secondary transition cursor-pointer text-xs font-semibold text-heading no-underline"
                    >
                      <span className="flex items-center gap-2">
                        <Icon name="globe" size={15} className="text-cyan" />
                        <span>University Portal</span>
                      </span>
                      <Icon name="arrowUpRight" size={12} className="text-subtle" />
                    </Link>
                  </section>
                </>
              )}
            </div>

            {/* Date Pill */}
            <span className="hidden md:inline-block rounded-xl border border-border-light bg-surface px-3 py-1.5 text-xs text-muted font-medium">
              {new Intl.DateTimeFormat('en', { weekday: 'short', month: 'short', day: 'numeric' }).format(new Date())}
            </span>
          </div>
        </header>}

        {/* Content View */}
        <main className={isStudyAssistant
          ? 'flex-1 min-h-0 w-full overflow-hidden'
          : 'flex-1 w-full max-w-screen-2xl mx-auto px-3 sm:px-4 lg:px-6 py-4'}>
          {children}
        </main>
      </div>
    </div>
  );
}

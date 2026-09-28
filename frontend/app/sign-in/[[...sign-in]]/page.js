'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';

export default function SignInPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace('/dashboard/assignments');
  }, [router]);

  return (
    <main className="route-loading">
      <span className="brand-mark">u</span>
      <div className="space-y-2 text-center">
        <p className="font-semibold text-sm">Entering workspace…</p>
        <Link href="/dashboard/assignments" className="text-xs text-[#6657d9] underline">
          Click here if not redirected automatically
        </Link>
      </div>
    </main>
  );
}

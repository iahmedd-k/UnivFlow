'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    router.replace('/dashboard');
  }, [router]);

  return (
    <main className="route-loading">
      <span className="brand-mark">u</span>
      <span>Opening your workspace…</span>
    </main>
  );
}

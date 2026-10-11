'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function ScheduleRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace('/dashboard/timetable');
  }, [router]);

  return (
    <div className="p-8 text-center text-sm text-neutral-500">
      Redirecting to Timetable…
    </div>
  );
}

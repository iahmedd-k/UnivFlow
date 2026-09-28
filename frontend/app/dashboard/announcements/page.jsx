'use client';

import { useEffect, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import Link from 'next/link';
import { format } from 'date-fns';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

export default function AnnouncementsPage() {
  const { getToken } = useAuth();
  const [announcements, setAnnouncements] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const load = async () => {
      try {
        const token = await getToken();
        const data = await api.getAnnouncements(token);
        setAnnouncements(data);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [getToken]);

  if (loading) return <div className="flex items-center justify-center h-64">Loading...</div>;
  if (error) return <div className="text-red-600 p-4">Error: {error}</div>;

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Announcements</h1>
          <p className="text-gray-500 mt-1">Class announcements and updates</p>
        </div>
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        {announcements.length === 0 ? (
          <div className="p-12 text-center text-gray-500">
            No announcements.
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {announcements.map((ann) => (
              <Link
                key={ann.id}
                href={`/dashboard/announcements/${ann.id}`}
                className="block px-6 py-4 hover:bg-gray-50 transition-colors"
              >
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-gray-900 truncate">{ann.title}</h3>
                    <p className="text-sm text-gray-500 mt-1">
                      {ann.published_at ? format(new Date(ann.published_at), 'MMM d, yyyy h:mm a') : 'Unknown date'} • {ann.source || 'Unknown'}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="px-3 py-1 rounded-full text-sm font-medium bg-gray-100 text-gray-700">
                      {ann.source || 'Announcement'}
                    </span>
                    <Icon name="arrowUpRight" size={13} className="text-gray-300" />
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { useAuth } from '@clerk/nextjs';
import Link from 'next/link';
import { format } from 'date-fns';
import { api } from '@/app/lib/api';

export default function AnnouncementDetailPage() {
  const params = useParams();
  const { getToken } = useAuth();
  const announcementId = params.id;
  const [announcement, setAnnouncement] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const load = async () => {
      try {
        const token = await getToken();
        const data = await api.getAnnouncements(token);
        const found = data.find(a => a.id == announcementId);
        if (!found) throw new Error('Announcement not found');
        setAnnouncement(found);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [announcementId, getToken]);

  if (loading) return <div className="flex items-center justify-center h-64">Loading...</div>;
  if (error) return <div className="text-red-600 p-4">Error: {error}</div>;
  if (!announcement) return <div className="p-8 text-center">Announcement not found</div>;

  const publishedAt = announcement.published_at ? format(new Date(announcement.published_at), 'MMMM d, yyyy \'at\' h:mm a') : 'Unknown';

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link href="/dashboard/announcements" className="text-gray-400 hover:text-gray-600">←</Link>
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{announcement.title}</h1>
          <p className="text-gray-500 mt-1">Announcement Details</p>
        </div>
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
        <div className="mb-6">
          <p className="text-sm text-gray-500 mb-1">Published</p>
          <p className="text-gray-900">{publishedAt}</p>
        </div>

        <div className="mb-6">
          <p className="text-sm text-gray-500 mb-1">Source</p>
          <p className="font-medium text-gray-900">{announcement.source || 'Unknown'}</p>
        </div>

        <div>
          <p className="text-sm text-gray-500 mb-2">Content</p>
          <div className="prose prose-sm max-w-none text-gray-700 whitespace-pre-wrap bg-gray-50 p-4 rounded-lg">
            {announcement.content || 'No content'}
          </div>
        </div>

        {announcement.url && (
          <div className="mt-6 pt-6 border-t">
            <a href={announcement.url} target="_blank" rel="noopener noreferrer" className="text-indigo-600 hover:underline">
              View in Google Classroom →
            </a>
          </div>
        )}

        <div className="flex justify-end gap-2 mt-6">
          <Link href="/dashboard/announcements" className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50">
            Back to Announcements
          </Link>
        </div>
      </div>
    </div>
  );
}
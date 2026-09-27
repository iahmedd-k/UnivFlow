'use client';

import { useEffect, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import Link from 'next/link';
import { api } from '@/app/lib/api';

const statCards = [
  { key: 'courses_count', label: 'Active Courses', icon: '📚', color: 'bg-blue-500' },
  { key: 'assignments.total', label: 'Total Assignments', icon: '📝', color: 'bg-indigo-500' },
  { key: 'assignments.pending', label: 'Pending', icon: '⏳', color: 'bg-yellow-500' },
  { key: 'assignments.overdue', label: 'Overdue', icon: '🔴', color: 'bg-red-500' },
  { key: 'assignments.completed', label: 'Completed', icon: '✅', color: 'bg-green-500' },
  { key: 'upcoming_classes', label: 'Upcoming Classes', icon: '📅', color: 'bg-purple-500' },
  { key: 'upcoming_exams', label: 'Upcoming Exams', icon: '📋', color: 'bg-orange-500' },
  { key: 'upcoming_quizzes', label: 'Upcoming Quizzes', icon: '❓', color: 'bg-pink-500' },
];

function getNested(obj, path) {
  return path.split('.').reduce((o, k) => (o || {})[k], obj);
}

export default function DashboardOverview() {
  const { getToken } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const load = async () => {
      try {
        const token = await getToken();
        const overview = await api.getOverview(token);
        setData(overview);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [getToken]);

  if (loading) return <div className="flex items-center justify-center h-64">Loading...</div>;
  if (error) return <div className="text-red-600">Error: {error}</div>;
  if (!data) return <div>No data</div>;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-gray-500 mt-1">Overview of your academic progress</p>
        </div>
        <Link
          href="/dashboard/assignments"
          className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors"
        >
          <span>+</span> View All Assignments
        </Link>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-4">
        {statCards.map((stat) => (
          <div key={stat.key} className="bg-white rounded-xl p-5 shadow-sm border border-gray-100">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-500">{stat.label}</p>
                <p className="text-2xl font-bold text-gray-900 mt-1">
                  {getNested(data, stat.key) ?? 0}
                </p>
              </div>
              <div className={`${stat.color} p-3 rounded-lg`}>
                <span className="text-2xl">{stat.icon}</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <Link href="/dashboard/assignments" className="bg-white rounded-xl p-6 shadow-sm border border-gray-100 hover:border-indigo-300 transition-colors">
          <div className="flex items-start gap-4">
            <div className="bg-indigo-100 p-3 rounded-lg">📝</div>
            <div>
              <h3 className="font-semibold text-gray-900">Assignments Hub</h3>
              <p className="text-sm text-gray-500 mt-1">Manage, review, and track course deliverables</p>
            </div>
          </div>
        </Link>

        <Link href="/dashboard/exams" className="bg-white rounded-xl p-6 shadow-sm border border-gray-100 hover:border-indigo-300 transition-colors">
          <div className="flex items-start gap-4">
            <div className="bg-orange-100 p-3 rounded-lg">📋</div>
            <div>
              <h3 className="font-semibold text-gray-900">Exams</h3>
              <p className="text-sm text-gray-500 mt-1">View upcoming exams and details</p>
            </div>
          </div>
        </Link>

        <Link href="/dashboard/quizzes" className="bg-white rounded-xl p-6 shadow-sm border border-gray-100 hover:border-indigo-300 transition-colors">
          <div className="flex items-start gap-4">
            <div className="bg-pink-100 p-3 rounded-lg">❓</div>
            <div>
              <h3 className="font-semibold text-gray-900">Quizzes</h3>
              <p className="text-sm text-gray-500 mt-1">Track quiz schedule and results</p>
            </div>
          </div>
        </Link>

        <Link href="/dashboard/announcements" className="bg-white rounded-xl p-6 shadow-sm border border-gray-100 hover:border-indigo-300 transition-colors">
          <div className="flex items-start gap-4">
            <div className="bg-blue-100 p-3 rounded-lg">📢</div>
            <div>
              <h3 className="font-semibold text-gray-900">Announcements</h3>
              <p className="text-sm text-gray-500 mt-1">Class updates and notifications</p>
            </div>
          </div>
        </Link>

        <Link href="/dashboard/schedule" className="bg-white rounded-xl p-6 shadow-sm border border-gray-100 hover:border-indigo-300 transition-colors">
          <div className="flex items-start gap-4">
            <div className="bg-purple-100 p-3 rounded-lg">📅</div>
            <div>
              <h3 className="font-semibold text-gray-900">Schedule & Attendance</h3>
              <p className="text-sm text-gray-500 mt-1">View classes, track attendance</p>
            </div>
          </div>
        </Link>

        <Link href="/dashboard/templates" className="bg-white rounded-xl p-6 shadow-sm border border-gray-100 hover:border-indigo-300 transition-colors">
          <div className="flex items-start gap-4">
            <div className="bg-green-100 p-3 rounded-lg">📋</div>
            <div>
              <h3 className="font-semibold text-gray-900">Templates</h3>
              <p className="text-sm text-gray-500 mt-1">Manage assignment templates</p>
            </div>
          </div>
        </Link>
      </div>

      {/* Recent Activity */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <div className="px-6 py-4 border-b">
          <h2 className="text-lg font-semibold text-gray-900">Quick Stats</h2>
        </div>
        <div className="p-6">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div className="text-center p-4 bg-gray-50 rounded-lg">
              <p className="text-3xl font-bold text-indigo-600">{data.average_attendance}%</p>
              <p className="text-sm text-gray-500 mt-1">Avg Attendance</p>
            </div>
            <div className="text-center p-4 bg-gray-50 rounded-lg">
              <p className="text-3xl font-bold text-green-600">{data.assignments.completed}</p>
              <p className="text-sm text-gray-500 mt-1">Completed</p>
            </div>
            <div className="text-center p-4 bg-gray-50 rounded-lg">
              <p className="text-3xl font-bold text-red-600">{data.assignments.overdue}</p>
              <p className="text-sm text-gray-500 mt-1">Overdue</p>
            </div>
            <div className="text-center p-4 bg-gray-50 rounded-lg">
              <p className="text-3xl font-bold text-yellow-600">{data.assignments.pending}</p>
              <p className="text-sm text-gray-500 mt-1">Pending</p>
            </div>
            <div className="text-center p-4 bg-gray-50 rounded-lg">
              <p className="text-3xl font-bold text-blue-600">{data.announcements_count ?? 0}</p>
              <p className="text-sm text-gray-500 mt-1">Announcements</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
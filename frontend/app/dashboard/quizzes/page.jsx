'use client';

import { useEffect, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import Link from 'next/link';
import { format } from 'date-fns';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

export default function QuizzesPage() {
  const { getToken } = useAuth();
  const [quizzes, setQuizzes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const load = async () => {
      try {
        const token = await getToken();
        const data = await api.getQuizzes(token);
        setQuizzes(data);
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
          <h1 className="text-2xl font-bold text-gray-900">Quizzes</h1>
          <p className="text-gray-500 mt-1">View and track your quizzes</p>
        </div>
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        {quizzes.length === 0 ? (
          <div className="p-12 text-center text-gray-500">
            No quizzes scheduled.
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {quizzes.map((quiz) => (
              <Link
                key={quiz.id}
                href={`/dashboard/quizzes/${quiz.id}`}
                className="block px-6 py-4 hover:bg-gray-50 transition-colors flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-start gap-3">
                  <div className="p-2 bg-purple-100 rounded-lg"><Icon name="help" size={18}/></div>
                    <div className="min-w-0 flex-1">
                      <h3 className="font-semibold text-gray-900 truncate">{quiz.title}</h3>
                      <p className="text-sm text-gray-500 mt-1">
                        {quiz.date ? format(new Date(quiz.date), 'MMMM d, yyyy') : 'TBA'} • {quiz.time || 'TBA'} • {quiz.room || 'TBA'}
                      </p>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`px-3 py-1 rounded-full text-sm font-medium ${
                    quiz.date && new Date(quiz.date) < new Date() ? 'bg-gray-100 text-gray-700' : 'bg-purple-100 text-purple-700'
                  }`}>
                    {quiz.date && new Date(quiz.date) < new Date() ? 'Completed' : 'Upcoming'}
                  </span>
                  <Icon name="arrowUpRight" size={14} className="text-gray-300" />
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

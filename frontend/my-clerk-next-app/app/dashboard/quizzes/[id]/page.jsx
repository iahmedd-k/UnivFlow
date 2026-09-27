'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useAuth } from '@clerk/nextjs';
import Link from 'next/link';
import { format } from 'date-fns';
import { api } from '@/app/lib/api';

export default function QuizDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { getToken } = useAuth();
  const quizId = params.id;
  const [quiz, setQuiz] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const load = async () => {
      try {
        const token = await getToken();
        const data = await api.getQuizzes(token);
        const found = data.find(q => q.id == quizId);
        if (!found) throw new Error('Quiz not found');
        setQuiz(found);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [quizId, getToken]);

  if (loading) return <div className="flex items-center justify-center h-64">Loading...</div>;
  if (error) return <div className="text-red-600 p-4">Error: {error}</div>;
  if (!quiz) return <div className="p-8 text-center">Quiz not found</div>;

  const quizDate = quiz.date ? format(new Date(quiz.date), 'MMMM d, yyyy') : 'TBA';
  const quizTime = quiz.time || 'TBA';
  const isPast = quiz.date && new Date(quiz.date) < new Date();

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-4">
          <Link href="/dashboard/quizzes" className="text-gray-400 hover:text-gray-600">←</Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{quiz.title}</h1>
            <p className="text-gray-500 mt-1">Quiz Details</p>
          </div>
        </div>
        <span className={`px-3 py-1 rounded-full text-sm font-medium ${
          isPast ? 'bg-gray-100 text-gray-700' : 'bg-purple-100 text-purple-700'
        }`}>
          {isPast ? 'Completed' : 'Upcoming'}
        </span>
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="text-sm text-gray-500">Date</p>
            <p className="font-medium text-gray-900">{quizDate}</p>
          </div>
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="text-sm text-gray-500">Time</p>
            <p className="font-medium text-gray-900">{quizTime}</p>
          </div>
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="text-sm text-gray-500">Room</p>
            <p className="font-medium text-gray-900">{quiz.room || 'TBA'}</p>
          </div>
          <div className="p-4 bg-gray-50 rounded-lg md:col-span-3">
            <p className="text-sm text-gray-500">Status</p>
            <p className="font-medium text-gray-900 capitalize">{quiz.status || 'scheduled'}</p>
          </div>
        </div>

        <div className="flex justify-end gap-2">
          <Link href="/dashboard/quizzes" className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50">
            Back to Quizzes
          </Link>
        </div>
      </div>
    </div>
  );
}
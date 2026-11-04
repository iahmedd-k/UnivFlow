'use client';

import { useEffect, useMemo, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import {
  AlarmClock,
  ArrowDownRight,
  ArrowUpRight,
  BookOpen,
  BriefcaseBusiness,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Circle,
  CircleDollarSign,
  Clock3,
  Coffee,
  Dumbbell,
  Heart,
  Leaf,
  ListTodo,
  Moon,
  NotebookPen,
  Pause,
  Play,
  Plus,
  Search,
  StickyNote,
  Target,
  Trash2,
  TrendingUp,
  Wallet,
  X,
} from 'lucide-react';
import { getManualSession } from '@/app/lib/manual-auth';

const STORAGE_PREFIX = 'univflow_my_planner_v1';
const CATEGORIES = ['Personal', 'Study', 'Health', 'Work', 'Home', 'Finance'];
const CATEGORY_STYLES = {
  Personal: 'bg-violet-50 text-violet-700 ring-violet-100',
  Study: 'bg-blue-50 text-blue-700 ring-blue-100',
  Health: 'bg-emerald-50 text-emerald-700 ring-emerald-100',
  Work: 'bg-amber-50 text-amber-700 ring-amber-100',
  Home: 'bg-orange-50 text-orange-700 ring-orange-100',
  Finance: 'bg-cyan-50 text-cyan-700 ring-cyan-100',
};
const CATEGORY_ICONS = {
  Personal: Heart,
  Study: BookOpen,
  Health: Dumbbell,
  Work: BriefcaseBusiness,
  Home: Coffee,
  Finance: Wallet,
};
const TABS = [
  { id: 'today', label: 'Today', icon: CalendarDays },
  { id: 'week', label: 'Week', icon: ListTodo },
  { id: 'goals', label: 'Goals', icon: Target },
  { id: 'notes', label: 'Notes', icon: NotebookPen },
  { id: 'money', label: 'Money', icon: Wallet },
];

function localDateKey(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function formatNoteDate(value, options) {
  if (!value) return 'Recently';
  return new Intl.DateTimeFormat(undefined, options).format(new Date(value));
}

function startOfWeek(date) {
  const day = new Date(date);
  day.setDate(day.getDate() - ((day.getDay() + 6) % 7));
  day.setHours(0, 0, 0, 0);
  return day;
}

function goalPeriodKey(period, dateKey) {
  const date = new Date(`${dateKey}T12:00:00`);
  if (period === 'Daily') return dateKey;
  if (period === 'Weekly') return `week-${localDateKey(startOfWeek(date))}`;
  if (period === 'Monthly') return dateKey.slice(0, 7);
  return dateKey.slice(0, 4);
}

function getGoalProgress(goal, dateKey) {
  const key = goalPeriodKey(goal.period, dateKey);
  return Number(goal.progressByPeriod?.[key] ?? (goal.progressByPeriod ? 0 : goal.progress) ?? 0);
}

function formatLongDate(value) {
  return new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'long', day: 'numeric' }).format(value);
}

function formatShortDate(value) {
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(value);
}

function formatDuration(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = seconds % 60;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`;
}

function formatMinutes(minutes = 0) {
  const safeMinutes = Math.max(0, Number(minutes) || 0);
  const hours = Math.floor(safeMinutes / 60);
  const remainder = safeMinutes % 60;
  return hours ? `${hours}h${remainder ? ` ${remainder}m` : ''}` : `${remainder}m`;
}

function getTrackedSeconds(item) {
  return Number(item.focusSeconds) || Number(item.seconds) || (Number(item.minutes) || 0) * 60;
}

function createId() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function newPlannerData() {
  return { tasks: [], goals: [], notes: [], expenses: [], focusSessions: [], monthlyBudget: 0, currency: 'PKR' };
}

function Panel({ children, className = '', ...props }) {
  return <section className={`rounded-[22px] border border-slate-200/80 bg-white shadow-[0_8px_32px_-24px_rgba(15,23,42,0.22)] ${className}`} {...props}>{children}</section>;
}

function EmptyState({ icon: Icon, title, detail, action }) {
  return (
    <div className="flex min-h-52 flex-col items-center justify-center px-6 py-10 text-center">
      <span className="grid size-12 place-items-center rounded-2xl bg-violet-50 text-violet-600"><Icon size={21} /></span>
      <p className="mt-4 text-sm font-semibold text-slate-800">{title}</p>
      <p className="mt-1 max-w-xs text-sm leading-6 text-slate-500">{detail}</p>
      {action}
    </div>
  );
}

function Dialog({ title, description, onClose, children }) {
  return (
    <div className="planner-dialog-backdrop fixed inset-0 z-[100] grid place-items-center overflow-y-auto p-4" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section role="dialog" aria-modal="true" aria-label={title} className="planner-dialog w-full max-w-lg rounded-[26px] border border-white/70 bg-white p-6 shadow-2xl sm:p-7">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold tracking-tight text-slate-900">{title}</h2>
            {description && <p className="mt-1 text-sm leading-6 text-slate-500">{description}</p>}
          </div>
          <button type="button" onClick={onClose} aria-label="Close dialog" className="grid size-9 shrink-0 place-items-center rounded-xl text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"><X size={18} /></button>
        </div>
        <div className="mt-6">{children}</div>
      </section>
    </div>
  );
}

function FormField({ label, children }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>
      {children}
    </label>
  );
}

const inputClass = 'w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-violet-400 focus:ring-4 focus:ring-violet-100';

export default function PlannerPage() {
  const { userId } = useAuth();
  const [manualUserId] = useState(() => {
    const manualSession = getManualSession();
    return manualSession?.user?.id || manualSession?.user?.user_id || '';
  });
  const ownerId = userId || manualUserId || 'guest';
  const [hydratedOwner, setHydratedOwner] = useState('');
  const [data, setData] = useState(newPlannerData);
  const [activeTab, setActiveTab] = useState('today');
  const [selectedDate, setSelectedDate] = useState(() => localDateKey());
  const [activeTaskId, setActiveTaskId] = useState(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [focusRunning, setFocusRunning] = useState(false);
  const [focusSessionDate, setFocusSessionDate] = useState(() => localDateKey());
  const [dialog, setDialog] = useState('');
  const [selectedNoteId, setSelectedNoteId] = useState(null);
  const [noteSearch, setNoteSearch] = useState('');

  useEffect(() => {
    if (!ownerId) return;
    try {
      const saved = window.localStorage.getItem(`${STORAGE_PREFIX}:${ownerId}`);
      const parsed = saved ? JSON.parse(saved) : null;
      // Load browser-only planner state after hydration so server and client markup stay deterministic.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setData({
        ...newPlannerData(),
        ...(parsed && typeof parsed === 'object' ? parsed : {}),
        tasks: Array.isArray(parsed?.tasks) ? parsed.tasks : [],
        goals: Array.isArray(parsed?.goals) ? parsed.goals : [],
        notes: Array.isArray(parsed?.notes) ? parsed.notes : [],
        expenses: Array.isArray(parsed?.expenses) ? parsed.expenses : [],
        focusSessions: Array.isArray(parsed?.focusSessions) ? parsed.focusSessions : [],
      });
    } catch (error) {
      console.error('Could not load planner data from this browser.', error);
      setData(newPlannerData());
    }
    setHydratedOwner(ownerId);
  }, [ownerId]);

  useEffect(() => {
    if (!hydratedOwner || hydratedOwner !== ownerId) return;
    try {
      window.localStorage.setItem(`${STORAGE_PREFIX}:${ownerId}`, JSON.stringify(data));
    } catch (error) {
      console.error('Could not save planner data in this browser.', error);
    }
  }, [data, hydratedOwner, ownerId]);

  useEffect(() => {
    if (!focusRunning) return undefined;
    const timer = window.setInterval(() => setElapsedSeconds((seconds) => seconds + 1), 1000);
    return () => window.clearInterval(timer);
  }, [focusRunning]);

  const selectedDay = useMemo(() => new Date(`${selectedDate}T12:00:00`), [selectedDate]);
  const todayKey = localDateKey();
  const isToday = selectedDate === todayKey;
  const todaysTasks = useMemo(
    () => data.tasks.filter((task) => task.date === selectedDate).sort((a, b) => (a.time || '99:99').localeCompare(b.time || '99:99')),
    [data.tasks, selectedDate],
  );
  const completedTasks = todaysTasks.filter((task) => task.completed).length;
  const totalStudyMinutes = data.tasks.filter((task) => task.date === selectedDate && task.category === 'Study').reduce((total, task) => total + (Number(task.minutes) || 0), 0);
  const totalFocusMinutes = Math.floor((
    data.tasks.filter((task) => task.date === selectedDate).reduce((total, task) => total + getTrackedSeconds(task), 0)
    + data.focusSessions.filter((session) => session.date === selectedDate).reduce((total, session) => total + getTrackedSeconds(session), 0)
  ) / 60);
  const todaysGoals = data.goals.filter((goal) => goal.period === 'Daily');
  const activeTask = data.tasks.find((task) => task.id === activeTaskId);
  const monthExpenses = data.expenses.filter((item) => item.date?.slice(0, 7) === selectedDate.slice(0, 7));
  const monthSpent = monthExpenses.reduce((total, item) => total + (Number(item.amount) || 0), 0);
  const monthlyBudget = Number(data.monthlyBudget) || 0;
  const budgetLeft = Math.max(0, monthlyBudget - monthSpent);
  const selectedNote = data.notes.find((note) => note.id === selectedNoteId) || data.notes[0] || null;

  const updateData = (key, value) => setData((current) => ({ ...current, [key]: value }));

  const addTask = (task) => {
    updateData('tasks', [...data.tasks, { ...task, id: createId(), completed: false, minutes: 0 }]);
    setDialog('');
  };

  const toggleTask = (taskId) => {
    const trackedSeconds = activeTaskId === taskId ? elapsedSeconds : 0;
    updateData('tasks', data.tasks.map((task) => task.id === taskId
      ? {
        ...task,
        completed: !task.completed,
        focusSeconds: getTrackedSeconds(task) + trackedSeconds,
        minutes: Math.floor((getTrackedSeconds(task) + trackedSeconds) / 60),
      }
      : task));
    if (activeTaskId === taskId) {
      setActiveTaskId(null);
      setFocusRunning(false);
      setElapsedSeconds(0);
    }
  };

  const deleteTask = (taskId) => {
    updateData('tasks', data.tasks.filter((task) => task.id !== taskId));
    if (activeTaskId === taskId) {
      if (elapsedSeconds > 0) {
        updateData('focusSessions', [...data.focusSessions, {
          id: createId(),
          date: focusSessionDate,
          seconds: elapsedSeconds,
          minutes: Math.floor(elapsedSeconds / 60),
        }]);
      }
      setActiveTaskId(null);
      setFocusRunning(false);
      setElapsedSeconds(0);
    }
  };

  const saveFocusSession = () => {
    if (elapsedSeconds > 0 && activeTaskId) {
      updateData('tasks', data.tasks.map((task) => {
        if (task.id !== activeTaskId) return task;
        const focusSeconds = getTrackedSeconds(task) + elapsedSeconds;
        return { ...task, focusSeconds, minutes: Math.floor(focusSeconds / 60) };
      }));
    } else if (elapsedSeconds > 0) {
      updateData('focusSessions', [...data.focusSessions, {
        id: createId(),
        date: focusSessionDate,
        seconds: elapsedSeconds,
        minutes: Math.floor(elapsedSeconds / 60),
      }]);
    }
    setFocusRunning(false);
    setActiveTaskId(null);
    setElapsedSeconds(0);
  };

  const toggleTimer = (taskId) => {
    if (focusRunning && activeTaskId === taskId) {
      setFocusRunning(false);
      return;
    }
    if (!focusRunning && activeTaskId === taskId) {
      setFocusRunning(true);
      return;
    }
    if (elapsedSeconds > 0) saveFocusSession();
    setElapsedSeconds(0);
    setActiveTaskId(taskId);
    setFocusSessionDate(selectedDate);
    setFocusRunning(true);
  };

  const openFocusRoom = () => {
    let taskId = activeTaskId;
    if (!activeTaskId && !focusRunning && elapsedSeconds === 0) {
      const nextTask = todaysTasks.find((task) => !task.completed);
      taskId = nextTask?.id || null;
      setActiveTaskId(taskId);
      setElapsedSeconds(0);
      setFocusSessionDate(selectedDate);
    }
    setFocusRunning(true);
    setActiveTab('focus');
  };

  const selectFocusTask = (taskId) => {
    if (elapsedSeconds > 0) saveFocusSession();
    setElapsedSeconds(0);
    setActiveTaskId(taskId || null);
    setFocusSessionDate(selectedDate);
    setFocusRunning(true);
  };

  const addGoal = (goal) => {
    updateData('goals', [...data.goals, {
      ...goal,
      id: createId(),
      progress: 0,
      progressByPeriod: { [goalPeriodKey(goal.period, selectedDate)]: 0 },
    }]);
    setDialog('');
    setActiveTab('goals');
  };

  const changeGoalProgress = (goalId, delta) => {
    updateData('goals', data.goals.map((goal) => {
      if (goal.id !== goalId) return goal;
      const periodKey = goalPeriodKey(goal.period, selectedDate);
      const progress = getGoalProgress(goal, selectedDate);
      return {
        ...goal,
        progressByPeriod: {
          ...(goal.progressByPeriod || {}),
          [periodKey]: Math.max(0, Math.min(Number(goal.target) || 1, progress + delta)),
        },
      };
    }));
  };

  const createNote = () => {
    const note = { id: createId(), title: 'Untitled note', content: '', updatedAt: new Date().toISOString(), color: ['lavender', 'mint', 'sand'][data.notes.length % 3] };
    updateData('notes', [note, ...data.notes]);
    setSelectedNoteId(note.id);
    setActiveTab('notes');
  };

  const updateNote = (noteId, patch) => {
    updateData('notes', data.notes.map((note) => note.id === noteId ? { ...note, ...patch, updatedAt: new Date().toISOString() } : note));
  };

  const deleteNote = (noteId) => {
    const remaining = data.notes.filter((note) => note.id !== noteId);
    updateData('notes', remaining);
    setSelectedNoteId(remaining[0]?.id || null);
  };

  const addExpense = (expense) => {
    updateData('expenses', [{ ...expense, id: createId() }, ...data.expenses]);
    setDialog('');
  };

  const shiftDate = (amount) => {
    const next = new Date(`${selectedDate}T12:00:00`);
    next.setDate(next.getDate() + amount);
    setSelectedDate(localDateKey(next));
  };

  const addTaskButton = <button type="button" onClick={() => setDialog('task')} className="inline-flex h-10 items-center gap-2 rounded-xl bg-slate-900 px-4 text-sm font-semibold text-white shadow-sm transition hover:-translate-y-0.5 hover:bg-violet-700"><Plus size={16} /> Add task</button>;

  return (
    <div className="planner-page mx-auto w-full max-w-none pb-8 text-slate-800">
      <header className="planner-enter mb-4 flex flex-col justify-between gap-3 md:flex-row md:items-end">
        <div>
          <h1 className="text-3xl font-semibold tracking-[-0.04em] text-slate-950 sm:text-[38px]">My Planner<span className="text-violet-500">.</span></h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={createNote} className="inline-flex h-10 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 text-sm font-semibold text-slate-700 transition hover:border-violet-200 hover:text-violet-700"><NotebookPen size={16} /> Quick note</button>
          {activeTab !== 'focus' && <button type="button" onClick={openFocusRoom} className="inline-flex h-10 items-center gap-2 rounded-xl border border-violet-200 bg-violet-50 px-3.5 text-sm font-semibold text-violet-700 shadow-sm transition hover:-translate-y-0.5 hover:border-violet-300 hover:bg-violet-100"><Play size={15} fill="currentColor" /> Focus room</button>}
          {addTaskButton}
        </div>
      </header>

      <section className="planner-enter planner-hero relative mb-6 overflow-hidden rounded-[28px] bg-[#17182f] p-6 text-white shadow-[0_24px_70px_-38px_rgba(42,35,110,0.6)] sm:p-8">
        <div className="pointer-events-none absolute -right-10 -top-32 size-80 rounded-full bg-violet-500/25 blur-3xl" />
        <div className="pointer-events-none absolute bottom-[-110px] right-[22%] size-64 rounded-full bg-blue-400/15 blur-3xl" />
        <div className="relative flex flex-col justify-between gap-7 lg:flex-row lg:items-end">
          <div>
            <p className="text-sm font-medium text-violet-200">{formatLongDate(new Date(`${selectedDate}T12:00:00`))}</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight sm:text-[30px]">{isToday ? 'Make today count.' : `A fresh look at ${formatShortDate(selectedDay)}.`}</h2>
            <p className="mt-2 max-w-lg text-sm leading-6 text-slate-300">You don&apos;t have to do it all. Just choose what deserves your attention next.</p>
          </div>
          <div className="grid grid-cols-3 gap-2 sm:gap-3">
            <div className="min-w-[92px] rounded-2xl border border-white/10 bg-white/[0.07] px-3 py-3.5 backdrop-blur">
              <p className="text-[11px] font-medium text-slate-300">Today&apos;s tasks</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">{completedTasks}<span className="text-base font-medium text-slate-400">/{todaysTasks.length}</span></p>
            </div>
            <div className="min-w-[92px] rounded-2xl border border-white/10 bg-white/[0.07] px-3 py-3.5 backdrop-blur">
              <p className="text-[11px] font-medium text-slate-300">Study time</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">{formatMinutes(totalStudyMinutes)}</p>
            </div>
            <div className="min-w-[92px] rounded-2xl border border-white/10 bg-white/[0.07] px-3 py-3.5 backdrop-blur">
              <p className="text-[11px] font-medium text-slate-300">Daily goals</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">{todaysGoals.filter((goal) => getGoalProgress(goal, selectedDate) >= Number(goal.target)).length}<span className="text-base font-medium text-slate-400">/{todaysGoals.length}</span></p>
            </div>
          </div>
        </div>
      </section>

      <nav aria-label="Planner sections" className="planner-enter mb-6 flex gap-1 overflow-x-auto rounded-2xl border border-slate-200/80 bg-white p-1.5 shadow-sm">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} type="button" onClick={() => setActiveTab(id)} className={`inline-flex h-10 shrink-0 items-center gap-2 rounded-xl px-3.5 text-sm font-semibold transition sm:px-4 ${activeTab === id ? 'bg-violet-600 text-white shadow-md shadow-violet-200' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-800'}`}>
            <Icon size={16} />{label}
          </button>
        ))}
        <div className="ml-auto hidden items-center gap-1 px-2 text-xs text-slate-400 lg:flex"><Leaf size={14} /> Your pace, your plan</div>
      </nav>

      {activeTab === 'today' && (
        <div className="planner-enter grid items-start gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(310px,0.8fr)]">
          <div className="space-y-5">
            <Panel className="overflow-hidden">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4 sm:px-6">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Your day</p>
                  <h3 className="mt-0.5 text-lg font-semibold tracking-tight text-slate-900">{isToday ? 'Today, at a glance' : formatLongDate(selectedDay)}</h3>
                </div>
                <div className="flex items-center gap-1.5">
                  <button type="button" onClick={() => shiftDate(-1)} aria-label="Previous day" className="grid size-9 place-items-center rounded-xl border border-slate-200 text-slate-500 transition hover:bg-slate-50"><ChevronLeft size={17} /></button>
                  <button type="button" onClick={() => setSelectedDate(todayKey)} className="h-9 rounded-xl border border-slate-200 px-3 text-xs font-semibold text-slate-600 transition hover:border-violet-200 hover:text-violet-700">Today</button>
                  <button type="button" onClick={() => shiftDate(1)} aria-label="Next day" className="grid size-9 place-items-center rounded-xl border border-slate-200 text-slate-500 transition hover:bg-slate-50"><ChevronRight size={17} /></button>
                </div>
              </div>
              <div className="divide-y divide-slate-100">
                {todaysTasks.length === 0 ? (
                  <EmptyState icon={CalendarDays} title="Nothing on the list yet" detail="Add a task for study, work, wellbeing, or anything else you want to make time for." action={addTaskButton} />
                ) : todaysTasks.map((task) => {
                  const CategoryIcon = CATEGORY_ICONS[task.category] || Circle;
                  const isRunning = activeTaskId === task.id;
                  return (
                    <article key={task.id} className={`group flex items-start gap-3.5 px-5 py-4 transition hover:bg-slate-50/80 sm:px-6 ${task.completed ? 'opacity-65' : ''}`}>
                      <button type="button" onClick={() => toggleTask(task.id)} aria-label={task.completed ? `Mark ${task.title} incomplete` : `Complete ${task.title}`} className={`mt-0.5 grid size-[22px] shrink-0 place-items-center rounded-full border transition ${task.completed ? 'border-emerald-500 bg-emerald-500 text-white' : 'border-slate-300 text-transparent hover:border-violet-400 hover:text-violet-400'}`}><Check size={13} strokeWidth={3} /></button>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className={`text-sm font-semibold ${task.completed ? 'text-slate-400 line-through' : 'text-slate-800'}`}>{task.title}</p>
                          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ring-inset ${CATEGORY_STYLES[task.category] || CATEGORY_STYLES.Personal}`}><CategoryIcon size={10} />{task.category}</span>
                          {task.priority === 'High' && <span className="rounded-full bg-rose-50 px-2 py-0.5 text-[10px] font-semibold text-rose-600">Priority</span>}
                        </div>
                        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400">
                          {task.time && <span className="inline-flex items-center gap-1"><Clock3 size={12} />{task.time}</span>}
                          {task.reminder && <span className="inline-flex items-center gap-1"><AlarmClock size={12} />Reminder set</span>}
                          {Number(task.minutes) > 0 && <span className="inline-flex items-center gap-1"><TrendingUp size={12} />{formatMinutes(task.minutes)} tracked</span>}
                        </div>
                      </div>
                      {!task.completed && <button type="button" onClick={() => toggleTimer(task.id)} className={`inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-xs font-semibold transition ${isRunning ? 'bg-violet-600 text-white shadow-sm' : 'text-slate-400 hover:bg-violet-50 hover:text-violet-700'}`}>{isRunning ? <Pause size={13} fill="currentColor" /> : <Play size={13} />}<span className="hidden sm:inline">{isRunning ? formatDuration(elapsedSeconds) : 'Focus'}</span></button>}
                      <button type="button" onClick={() => deleteTask(task.id)} aria-label={`Delete ${task.title}`} className="grid size-8 shrink-0 place-items-center rounded-lg text-slate-300 opacity-0 transition hover:bg-rose-50 hover:text-rose-500 group-hover:opacity-100 focus:opacity-100"><Trash2 size={14} /></button>
                    </article>
                  );
                })}
              </div>
              {todaysTasks.length > 0 && <button type="button" onClick={() => setDialog('task')} className="flex w-full items-center gap-2 border-t border-slate-100 px-5 py-3.5 text-sm font-semibold text-violet-600 transition hover:bg-violet-50/60 sm:px-6"><Plus size={16} /> Add to today</button>}
            </Panel>

            <Panel className="p-5 sm:p-6">
              <div className="flex items-start justify-between gap-3">
                <div><p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Your daily intentions</p><h3 className="mt-1 text-lg font-semibold tracking-tight text-slate-900">Small wins add up</h3></div>
                <button type="button" onClick={() => { setDialog('goal'); }} className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-slate-200 px-3 text-xs font-semibold text-slate-600 transition hover:border-violet-200 hover:text-violet-700"><Plus size={14} /> New goal</button>
              </div>
              {todaysGoals.length === 0 ? (
                <div className="mt-4 flex items-center gap-3 rounded-2xl bg-violet-50/70 p-4">
                  <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-white text-violet-600 shadow-sm"><Target size={18} /></span>
                  <div className="min-w-0 flex-1"><p className="text-sm font-semibold text-slate-800">Set an intention for today</p><p className="mt-0.5 text-xs leading-5 text-slate-500">It can be about anything: movement, connection, rest, or progress.</p></div>
                </div>
              ) : (
                <div className="mt-4 space-y-3">
                  {todaysGoals.slice(0, 3).map((goal) => {
                    const progressValue = getGoalProgress(goal, selectedDate);
                    const progress = Math.min(100, Math.round((progressValue / Math.max(1, Number(goal.target))) * 100));
                    return <div key={goal.id} className="rounded-2xl border border-slate-100 p-3.5"><div className="flex items-center justify-between gap-3"><p className="text-sm font-semibold text-slate-800">{goal.title}</p><button type="button" onClick={() => changeGoalProgress(goal.id, 1)} className="inline-flex h-7 shrink-0 items-center gap-1 rounded-lg bg-violet-50 px-2 text-xs font-bold text-violet-700 transition hover:bg-violet-100"><Plus size={13} />{progressValue}/{goal.target}</button></div><div className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-gradient-to-r from-violet-500 to-indigo-400 transition-all duration-500" style={{ width: `${progress}%` }} /></div></div>;
                  })}
                </div>
              )}
            </Panel>
          </div>

          <aside className="space-y-5">
            <Panel className="overflow-hidden">
              <div className="relative overflow-hidden bg-gradient-to-br from-violet-600 via-violet-600 to-indigo-700 p-5 text-white sm:p-6">
                <div className="pointer-events-none absolute -right-10 -top-12 size-40 rounded-full border-[24px] border-white/10" />
                <div className="relative flex items-center justify-between">
                  <div><p className="text-xs font-semibold uppercase tracking-[0.15em] text-violet-200">Focus room</p><h3 className="mt-1 text-lg font-semibold">One thing at a time</h3></div>
                  <span className="grid size-10 place-items-center rounded-xl bg-white/15"><Clock3 size={19} /></span>
                </div>
                <p className="relative mt-2 text-sm leading-6 text-violet-100">{activeTask ? `Focused on ${activeTask.title}` : 'Choose a task below and start a focused session.'}</p>
                <div className="relative mt-5 flex items-center justify-between rounded-2xl border border-white/15 bg-white/10 px-4 py-3 backdrop-blur-sm">
                  <span className="font-mono text-2xl font-semibold tracking-[0.08em] tabular-nums">{formatDuration(elapsedSeconds)}</span>
                  <button type="button" onClick={openFocusRoom} className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-white px-3 text-xs font-semibold text-violet-700 transition hover:scale-[1.02]"><Play size={13} fill="currentColor" />Open room</button>
                </div>
                <div className="relative mt-3 flex items-center gap-2 text-[11px] text-violet-100"><Moon size={13} /> Time is only tracked while you choose to focus.</div>
              </div>
              <div className="px-5 py-4 sm:px-6">
                <div className="flex items-center justify-between"><p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Time tracked today</p><span className="text-xs font-semibold text-violet-600">{formatMinutes(data.tasks.filter((task) => task.date === selectedDate).reduce((sum, task) => sum + (Number(task.minutes) || 0), 0) + Math.floor(elapsedSeconds / 60))}</span></div>
                <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-gradient-to-r from-violet-500 to-indigo-400 transition-all duration-700" style={{ width: `${Math.min(100, (totalFocusMinutes + Math.floor(elapsedSeconds / 60)) / 360 * 100)}%` }} /></div>
                <p className="mt-2 text-[11px] text-slate-400">A gentle guide, not a productivity score.</p>
              </div>
            </Panel>

            <Panel className="p-5 sm:p-6">
              <div className="flex items-center justify-between gap-3">
                <div><p className="text-xs font-semibold uppercase tracking-wider text-slate-400">This week</p><h3 className="mt-1 text-lg font-semibold tracking-tight text-slate-900">Your rhythm</h3></div>
                <button type="button" onClick={() => setActiveTab('week')} aria-label="Open week view" className="grid size-9 place-items-center rounded-xl border border-slate-200 text-slate-400 transition hover:text-violet-600"><ArrowUpRight size={16} /></button>
              </div>
              <WeekStrip selectedDate={selectedDate} tasks={data.tasks} onSelect={(date) => { setSelectedDate(date); setActiveTab('today'); }} />
            </Panel>

            <Panel className="overflow-hidden bg-gradient-to-br from-[#fbf8ff] to-[#f2f5ff] p-5 sm:p-6">
              <div className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-white text-violet-600 shadow-sm"><StickyNote size={18} /></span><div className="min-w-0 flex-1"><p className="text-xs font-semibold uppercase tracking-wider text-violet-500">A thought to keep</p><p className="mt-2 text-sm font-medium leading-6 text-slate-700">{data.notes.length ? `You have ${data.notes.length} note${data.notes.length === 1 ? '' : 's'} saved for later.` : 'Make a little room for ideas, reflections, and things you don’t want to forget.'}</p><button type="button" onClick={() => data.notes.length ? setActiveTab('notes') : createNote()} className="mt-3 inline-flex items-center gap-1 text-xs font-bold text-violet-700">{data.notes.length ? 'Open notes' : 'Write a note'}<ArrowUpRight size={13} /></button></div></div>
            </Panel>
          </aside>
        </div>
      )}

      {activeTab === 'week' && (
        <div className="planner-enter grid items-start gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(300px,0.8fr)]">
          <Panel className="overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4 sm:px-6">
              <div><p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Weekly view</p><h3 className="mt-0.5 text-lg font-semibold text-slate-900">{formatShortDate(startOfWeek(selectedDay))} – {formatShortDate(new Date(startOfWeek(selectedDay).getTime() + 6 * 86400000))}</h3></div>
              <button type="button" onClick={() => setDialog('task')} className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-violet-600 px-3 text-xs font-semibold text-white transition hover:bg-violet-700"><Plus size={14} /> Add task</button>
            </div>
            <div className="divide-y divide-slate-100">
              {Array.from({ length: 7 }, (_, index) => {
                const day = startOfWeek(selectedDay);
                day.setDate(day.getDate() + index);
                const key = localDateKey(day);
                const tasks = data.tasks.filter((task) => task.date === key).sort((a, b) => (a.time || '99:99').localeCompare(b.time || '99:99'));
                return (
                  <button key={key} type="button" onClick={() => { setSelectedDate(key); setActiveTab('today'); }} className={`flex w-full items-start gap-4 px-5 py-4 text-left transition hover:bg-slate-50 sm:px-6 ${key === selectedDate ? 'bg-violet-50/50' : ''}`}>
                    <div className="w-12 shrink-0 pt-0.5"><p className={`text-[10px] font-bold uppercase tracking-wider ${key === todayKey ? 'text-violet-600' : 'text-slate-400'}`}>{new Intl.DateTimeFormat(undefined, { weekday: 'short' }).format(day)}</p><p className={`mt-1 text-lg font-semibold tabular-nums ${key === selectedDate ? 'text-violet-700' : 'text-slate-800'}`}>{day.getDate()}</p></div>
                    <div className="min-w-0 flex-1">
                      {tasks.length ? <div className="space-y-2">{tasks.slice(0, 4).map((task) => <div key={task.id} className="flex items-center gap-2.5"><span className={`size-2 shrink-0 rounded-full ${task.completed ? 'bg-emerald-400' : task.category === 'Study' ? 'bg-blue-400' : task.category === 'Health' ? 'bg-emerald-400' : 'bg-violet-400'}`} /><span className={`min-w-0 flex-1 truncate text-sm ${task.completed ? 'text-slate-400 line-through' : 'font-medium text-slate-700'}`}>{task.title}</span>{task.time && <span className="text-[11px] text-slate-400">{task.time}</span>}</div>)}{tasks.length > 4 && <p className="pl-4 text-xs text-slate-400">+{tasks.length - 4} more</p>}</div> : <p className="pt-1 text-sm text-slate-400">A little space to breathe</p>}
                    </div>
                    <span className="mt-1 shrink-0 text-[11px] font-medium text-slate-400">{tasks.filter((task) => task.completed).length}/{tasks.length}</span>
                  </button>
                );
              })}
            </div>
          </Panel>
          <aside className="space-y-5">
            <Panel className="p-5 sm:p-6">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Weekly intention</p><h3 className="mt-1 text-lg font-semibold text-slate-900">What matters this week?</h3>
              <p className="mt-2 text-sm leading-6 text-slate-500">Set goals for learning, health, relationships, and the life you’re building beyond your to-do list.</p>
              <button type="button" onClick={() => setDialog('goal')} className="mt-4 inline-flex h-9 items-center gap-2 rounded-xl bg-violet-600 px-3.5 text-xs font-semibold text-white transition hover:bg-violet-700"><Plus size={14} /> Set a weekly goal</button>
            </Panel>
            <Panel className="p-5 sm:p-6">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Weekly goals</p>
              <div className="mt-3 space-y-3">
                {data.goals.filter((goal) => goal.period === 'Weekly').slice(0, 4).map((goal) => <GoalProgress key={goal.id} goal={goal} progressValue={getGoalProgress(goal, selectedDate)} onIncrement={() => changeGoalProgress(goal.id, 1)} />)}
                {!data.goals.some((goal) => goal.period === 'Weekly') && <p className="rounded-xl bg-slate-50 p-4 text-sm leading-6 text-slate-500">No weekly goals yet. Keep them meaningful and kind to your schedule.</p>}
              </div>
            </Panel>
          </aside>
        </div>
      )}

      {activeTab === 'focus' && (
        <div className="planner-enter">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <button type="button" onClick={() => setActiveTab('today')} className="grid size-10 place-items-center rounded-xl border border-slate-200 bg-white text-slate-500 transition hover:border-violet-200 hover:text-violet-700" aria-label="Back to planner"><ChevronLeft size={18} /></button>
              <div><p className="text-xs font-semibold uppercase tracking-wider text-violet-600">A little space to focus</p><h2 className="text-xl font-semibold tracking-tight text-slate-900">Focus room</h2></div>
            </div>
            <span className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${focusRunning ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}><span className={`size-1.5 rounded-full ${focusRunning ? 'animate-pulse bg-emerald-500' : 'bg-slate-400'}`} />{focusRunning ? 'Stopwatch is running' : elapsedSeconds ? 'Session paused' : 'Ready when you are'}</span>
          </div>

          <div className="grid items-stretch gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.8fr)]">
            <section className="relative flex min-h-[510px] flex-col items-center justify-center overflow-hidden rounded-[30px] bg-[#17182f] px-5 py-10 text-center text-white shadow-[0_26px_75px_-40px_rgba(42,35,110,0.75)] sm:min-h-[590px] sm:px-10">
              <div className="pointer-events-none absolute -left-20 -top-32 size-80 rounded-full bg-violet-600/25 blur-3xl" />
              <div className="pointer-events-none absolute -bottom-28 -right-10 size-72 rounded-full bg-blue-500/20 blur-3xl" />
              <div className={`relative grid size-56 place-items-center rounded-full border border-white/10 bg-white/[0.035] sm:size-64 ${focusRunning ? 'planner-focus-ring' : ''}`}>
                <div className="absolute inset-3 rounded-full border border-white/[0.08]" />
                <div className="relative">
                  <p className="text-[10px] font-bold uppercase tracking-[0.23em] text-violet-200">Elapsed time</p>
                  <p className="mt-3 font-mono text-[42px] font-medium tracking-[0.07em] tabular-nums sm:text-[52px]">{formatDuration(elapsedSeconds)}</p>
                  <p className="mt-2 text-xs text-slate-400">{activeTask ? activeTask.title : 'Open focus session'}</p>
                </div>
              </div>
              <p className="relative mt-7 max-w-md text-sm leading-6 text-slate-300">{focusRunning ? 'You’re here. Let the next small step be enough.' : 'The stopwatch starts when you enter. Take a breath, pick a task—or leave it open—and begin.'}</p>
              <div className="relative mt-6 flex flex-wrap justify-center gap-2">
                {focusRunning ? (
                  <button type="button" onClick={() => setFocusRunning(false)} className="inline-flex h-11 items-center gap-2 rounded-xl border border-white/15 bg-white/10 px-4 text-sm font-semibold text-white transition hover:bg-white/15"><Pause size={16} fill="currentColor" /> Pause</button>
                ) : (
                  <button type="button" onClick={() => setFocusRunning(true)} className="inline-flex h-11 items-center gap-2 rounded-xl bg-white px-5 text-sm font-semibold text-violet-800 shadow-lg transition hover:-translate-y-0.5 hover:bg-violet-50"><Play size={15} fill="currentColor" /> {elapsedSeconds ? 'Resume session' : 'Start stopwatch'}</button>
                )}
                <button type="button" onClick={saveFocusSession} disabled={!elapsedSeconds && !activeTaskId} className="inline-flex h-11 items-center gap-2 rounded-xl border border-white/15 px-4 text-sm font-semibold text-slate-200 transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40"><Check size={16} /> Finish session</button>
              </div>
              <p className="relative mt-5 text-[11px] text-slate-400">{totalFocusMinutes ? `${formatMinutes(totalFocusMinutes)} already tracked today` : 'Your time is yours—no tracking runs unless you start a session.'}</p>
            </section>

            <aside className="space-y-5">
              <Panel className="p-5 sm:p-6">
                <div className="flex items-start gap-3">
                  <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-violet-50 text-violet-600"><Target size={18} /></span>
                  <div className="min-w-0 flex-1"><p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Your intention</p><h3 className="mt-1 text-lg font-semibold text-slate-900">What has your attention?</h3></div>
                </div>
                <label className="mt-5 block"><span className="mb-1.5 block text-xs font-semibold text-slate-500">Focus on a task</span><select value={activeTaskId || ''} onChange={(event) => selectFocusTask(event.target.value)} className={inputClass}><option value="">Just me / open session</option>{data.tasks.filter((task) => !task.completed).map((task) => <option key={task.id} value={task.id}>{task.title} · {task.category}</option>)}</select></label>
                <p className="mt-2 text-xs leading-5 text-slate-400">Choose any part of life—not just study. Switching tasks saves the time already spent.</p>
                <button type="button" onClick={() => setDialog('task')} className="mt-4 inline-flex h-9 items-center gap-1.5 rounded-xl border border-slate-200 px-3 text-xs font-semibold text-slate-600 transition hover:border-violet-200 hover:text-violet-700"><Plus size={14} /> Add a task</button>
              </Panel>

              <Panel className="overflow-hidden">
                <div className="border-b border-slate-100 px-5 py-4"><p className="text-xs font-semibold uppercase tracking-wider text-slate-400">A gentle reset</p><h3 className="mt-0.5 text-base font-semibold text-slate-900">Make this moment yours</h3></div>
                <div className="space-y-3 p-5">
                  {[['01', 'Put one thing in front of you'], ['02', 'Let the rest wait for now'], ['03', 'Take a short break when you need one']].map(([number, text]) => <div key={number} className="flex items-center gap-3"><span className="grid size-7 shrink-0 place-items-center rounded-lg bg-slate-50 text-[10px] font-bold text-violet-600">{number}</span><p className="text-sm text-slate-600">{text}</p></div>)}
                </div>
                <div className="flex items-center gap-2 border-t border-slate-100 bg-slate-50/70 px-5 py-3 text-[11px] text-slate-400"><Moon size={13} /> Stopwatch only. No screenshots, monitoring, or laptop-wide tracking.</div>
              </Panel>
            </aside>
          </div>
        </div>
      )}

      {activeTab === 'goals' && (
        <div className="planner-enter">
          <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
            <div><p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Intentions into action</p><h2 className="mt-1 text-xl font-semibold tracking-tight text-slate-900">Goals for the life you want</h2><p className="mt-1 text-sm text-slate-500">Make room for personal growth, wellbeing, work, finances, and study.</p></div>
            <button type="button" onClick={() => setDialog('goal')} className="inline-flex h-10 items-center gap-2 rounded-xl bg-violet-600 px-4 text-sm font-semibold text-white transition hover:-translate-y-0.5 hover:bg-violet-700"><Plus size={16} /> Create a goal</button>
          </div>
          {data.goals.length === 0 ? <Panel><EmptyState icon={Target} title="Start with what matters to you" detail="Set daily intentions, weekly routines, or a bigger monthly milestone. Your goals can be about any part of life." action={<button type="button" onClick={() => setDialog('goal')} className="mt-4 inline-flex h-9 items-center gap-2 rounded-xl bg-violet-600 px-3.5 text-xs font-semibold text-white"><Plus size={14} /> Create your first goal</button>} /></Panel> : (
            <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">{data.goals.map((goal, index) => <GoalCard key={goal.id} goal={goal} index={index} progressValue={getGoalProgress(goal, selectedDate)} onIncrement={() => changeGoalProgress(goal.id, 1)} onDecrement={() => changeGoalProgress(goal.id, -1)} onDelete={() => updateData('goals', data.goals.filter((item) => item.id !== goal.id))} />)}</div>
          )}
        </div>
      )}

      {activeTab === 'notes' && (
        <div className="planner-enter">
          <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
            <div><p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Your thinking space</p><h2 className="mt-1 text-xl font-semibold tracking-tight text-slate-900">Notes, just the way you need them</h2><p className="mt-1 text-sm text-slate-500">Capture a thought, make a list, or let a blank page do its thing.</p></div>
            <button type="button" onClick={createNote} className="inline-flex h-10 items-center gap-2 rounded-xl bg-violet-600 px-4 text-sm font-semibold text-white transition hover:-translate-y-0.5 hover:bg-violet-700"><Plus size={16} /> New note</button>
          </div>
          <div className="grid min-h-[570px] gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
            <Panel className="overflow-hidden">
              <div className="border-b border-slate-100 p-4">
                <label className="relative block"><Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" /><input value={noteSearch} onChange={(event) => setNoteSearch(event.target.value)} placeholder="Find a note..." className={`${inputClass} pl-9`} aria-label="Search notes" /></label>
                <p className="mt-3 px-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{data.notes.length} saved {data.notes.length === 1 ? 'note' : 'notes'}</p>
              </div>
              <div className="max-h-[490px] overflow-y-auto p-2">
                {data.notes.filter((note) => `${note.title} ${note.content}`.toLowerCase().includes(noteSearch.toLowerCase())).map((note) => <button key={note.id} type="button" onClick={() => setSelectedNoteId(note.id)} className={`mb-1 w-full rounded-xl p-3 text-left transition ${selectedNote?.id === note.id ? 'bg-violet-50 ring-1 ring-violet-100' : 'hover:bg-slate-50'}`}><p className="truncate text-sm font-semibold text-slate-800">{note.title || 'Untitled note'}</p><p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-400">{note.content || 'Start writing whenever you are ready…'}</p><p className="mt-2 text-[10px] font-medium text-slate-400">{formatNoteDate(note.updatedAt, { month: 'short', day: 'numeric' })}</p></button>)}
                {!data.notes.length && <div className="p-5 text-center"><StickyNote size={22} className="mx-auto text-slate-300" /><p className="mt-2 text-sm font-medium text-slate-600">A page for your thoughts</p><p className="mt-1 text-xs leading-5 text-slate-400">Your notes stay saved in this browser.</p><button type="button" onClick={createNote} className="mt-3 text-xs font-bold text-violet-600">Create a note</button></div>}
              </div>
            </Panel>
            <Panel className={`flex min-h-[570px] flex-col overflow-hidden ${selectedNote?.color === 'mint' ? 'bg-[#f5fbf7]' : selectedNote?.color === 'sand' ? 'bg-[#fffaf2]' : 'bg-[#fbfaff]'}`}>
              {selectedNote ? (
                <>
                  <div className="flex items-center justify-between gap-3 border-b border-slate-200/60 px-5 py-4 sm:px-7">
                    <p className="text-xs text-slate-400">Last edited {formatNoteDate(selectedNote.updatedAt, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</p>
                    <button type="button" onClick={() => deleteNote(selectedNote.id)} aria-label="Delete note" className="grid size-9 place-items-center rounded-xl text-slate-400 transition hover:bg-rose-50 hover:text-rose-500"><Trash2 size={16} /></button>
                  </div>
                  <div className="flex flex-1 flex-col p-5 sm:p-8">
                    <input value={selectedNote.title} onChange={(event) => updateNote(selectedNote.id, { title: event.target.value })} placeholder="Give this note a title" className="w-full border-0 bg-transparent text-2xl font-semibold tracking-tight text-slate-900 outline-none placeholder:text-slate-300 sm:text-[28px]" aria-label="Note title" />
                    <textarea value={selectedNote.content} onChange={(event) => updateNote(selectedNote.id, { content: event.target.value })} placeholder={'Start with a thought…\n\nWrite freely. Make a list. Save an idea for another day.'} className="mt-5 min-h-[420px] flex-1 resize-none border-0 bg-transparent text-[15px] leading-8 text-slate-700 outline-none placeholder:text-slate-300" aria-label="Note content" />
                    <div className="mt-3 flex items-center justify-between border-t border-slate-200/60 pt-3 text-[11px] text-slate-400"><span>{selectedNote.content.length} characters</span><span className="inline-flex items-center gap-1.5"><CheckCircle2 size={12} className="text-emerald-500" />Saved automatically</span></div>
                  </div>
                </>
              ) : <EmptyState icon={NotebookPen} title={data.notes.length ? 'Choose a note to open' : 'A blank page can be a beginning'} detail={data.notes.length ? 'Select a note from the list to keep writing.' : 'Keep ideas, plans, journal entries, or little things you want to remember.'} action={<button type="button" onClick={createNote} className="mt-4 inline-flex h-9 items-center gap-2 rounded-xl bg-violet-600 px-3.5 text-xs font-semibold text-white"><Plus size={14} /> Start writing</button>} />}
            </Panel>
          </div>
        </div>
      )}

      {activeTab === 'money' && (
        <div className="planner-enter">
          <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
            <div><p className="text-xs font-semibold uppercase tracking-wider text-slate-400">A clearer month</p><h2 className="mt-1 text-xl font-semibold tracking-tight text-slate-900">Your money, without the stress</h2><p className="mt-1 text-sm text-slate-500">A simple personal snapshot. Nothing connects to your bank.</p></div>
            <div className="flex items-center gap-2">
              <select aria-label="Budget currency" value={data.currency || 'PKR'} onChange={(event) => updateData('currency', event.target.value)} className="h-10 rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-700 outline-none focus:border-violet-400">
                {['PKR', 'USD', 'EUR', 'GBP'].map((currency) => <option key={currency}>{currency}</option>)}
              </select>
              <button type="button" onClick={() => setDialog('expense')} className="inline-flex h-10 items-center gap-2 rounded-xl bg-slate-900 px-4 text-sm font-semibold text-white transition hover:bg-violet-700"><Plus size={16} /> Add expense</button>
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <Panel className="p-5 sm:p-6"><div className="flex items-center justify-between"><p className="text-sm font-medium text-slate-500">Monthly budget</p><span className="grid size-10 place-items-center rounded-xl bg-violet-50 text-violet-600"><Wallet size={19} /></span></div><div className="mt-4 flex items-baseline gap-2"><span className="text-3xl font-semibold tracking-tight text-slate-900">{formatCurrency(monthlyBudget, data.currency)}</span><button type="button" onClick={() => setDialog('budget')} className="text-xs font-semibold text-violet-600 hover:text-violet-800">{monthlyBudget ? 'Edit' : 'Set budget'}</button></div><p className="mt-2 text-xs text-slate-400">Your personal monthly spending plan</p></Panel>
            <Panel className="p-5 sm:p-6"><div className="flex items-center justify-between"><p className="text-sm font-medium text-slate-500">Spent this month</p><span className="grid size-10 place-items-center rounded-xl bg-amber-50 text-amber-600"><ArrowDownRight size={19} /></span></div><p className="mt-4 text-3xl font-semibold tracking-tight text-slate-900">{formatCurrency(monthSpent, data.currency)}</p><p className="mt-2 text-xs text-slate-400">{monthExpenses.length} {monthExpenses.length === 1 ? 'expense' : 'expenses'} recorded</p></Panel>
            <Panel className="p-5 sm:p-6"><div className="flex items-center justify-between"><p className="text-sm font-medium text-slate-500">Left to plan with</p><span className="grid size-10 place-items-center rounded-xl bg-emerald-50 text-emerald-600"><TrendingUp size={19} /></span></div><p className="mt-4 text-3xl font-semibold tracking-tight text-slate-900">{monthlyBudget ? formatCurrency(budgetLeft, data.currency) : '—'}</p><p className="mt-2 text-xs text-slate-400">{monthlyBudget ? 'Based on the budget you set' : 'Set a budget to see what remains'}</p></Panel>
          </div>
          <div className="mt-5 grid items-start gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(300px,0.8fr)]">
            <Panel className="overflow-hidden">
              <div className="border-b border-slate-100 px-5 py-4 sm:px-6"><p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Spending log</p><h3 className="mt-0.5 text-lg font-semibold text-slate-900">{new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' }).format(selectedDay)}</h3></div>
              {monthExpenses.length ? <div className="divide-y divide-slate-100">{monthExpenses.slice().sort((a, b) => b.date.localeCompare(a.date)).map((item) => <div key={item.id} className="flex items-center gap-3 px-5 py-4 sm:px-6"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-slate-50 text-slate-500"><CircleDollarSign size={17} /></span><div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold text-slate-800">{item.title}</p><p className="mt-0.5 text-xs text-slate-400">{item.category} · {formatShortDate(new Date(`${item.date}T12:00:00`))}</p></div><p className="text-sm font-semibold tabular-nums text-slate-800">−{formatCurrency(Number(item.amount), data.currency)}</p><button type="button" aria-label={`Delete ${item.title}`} onClick={() => updateData('expenses', data.expenses.filter((expense) => expense.id !== item.id))} className="grid size-8 place-items-center rounded-lg text-slate-300 transition hover:bg-rose-50 hover:text-rose-500"><Trash2 size={14} /></button></div>)}</div> : <EmptyState icon={CircleDollarSign} title="Your spending log is clear" detail="Add expenses as they happen to get a gentle view of your monthly spending." action={<button type="button" onClick={() => setDialog('expense')} className="mt-4 inline-flex h-9 items-center gap-2 rounded-xl bg-violet-600 px-3.5 text-xs font-semibold text-white"><Plus size={14} /> Add an expense</button>} />}
            </Panel>
            <Panel className="p-5 sm:p-6">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">A helpful reminder</p><h3 className="mt-1 text-lg font-semibold text-slate-900">Plans, not pressure</h3>
              <p className="mt-2 text-sm leading-6 text-slate-500">This is a private manual tracker in your browser—not financial advice, and not connected to a bank. Start with an estimate and adjust as life happens.</p>
              <div className="mt-5 space-y-3">{['Food & coffee', 'Travel', 'Books & supplies', 'Personal'].map((category, index) => { const spent = monthExpenses.filter((item) => item.category === category).reduce((sum, item) => sum + Number(item.amount || 0), 0); return <div key={category}><div className="flex justify-between text-xs"><span className="font-medium text-slate-600">{category}</span><span className="text-slate-400">{formatCurrency(spent)}</span></div><div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-gradient-to-r from-violet-400 to-indigo-400" style={{ width: `${Math.min(100, monthlyBudget ? spent / (monthlyBudget / 4) * 100 : spent ? 10 + index * 6 : 0)}%` }} /></div></div>; })}</div>
            </Panel>
          </div>
        </div>
      )}

      {!hydratedOwner && <div className="fixed bottom-4 right-4 z-40 rounded-full border border-slate-200 bg-white/90 px-3 py-1.5 text-[11px] font-medium text-slate-400 shadow-sm backdrop-blur">Loading your planner…</div>}

      {dialog === 'task' && <TaskDialog date={selectedDate} onClose={() => setDialog('')} onSubmit={addTask} />}
      {dialog === 'goal' && <GoalDialog onClose={() => setDialog('')} onSubmit={addGoal} />}
      {dialog === 'expense' && <ExpenseDialog date={selectedDate} currency={data.currency} onClose={() => setDialog('')} onSubmit={addExpense} />}
      {dialog === 'budget' && <BudgetDialog current={monthlyBudget} currency={data.currency} onClose={() => setDialog('')} onSubmit={(amount) => { updateData('monthlyBudget', amount); setDialog(''); }} />}

      <style jsx global>{`
        .planner-page { animation: planner-fade-in .55s cubic-bezier(.2,.7,.25,1) both; }
        .planner-enter { animation: planner-rise-in .55s cubic-bezier(.2,.7,.25,1) both; }
        .planner-hero { animation-delay: .04s; }
        .planner-dialog-backdrop { background: rgba(15, 23, 42, .42); backdrop-filter: blur(8px); animation: planner-fade-in .18s ease-out both; }
        .planner-dialog { animation: planner-dialog-in .22s cubic-bezier(.2,.8,.2,1) both; }
        @keyframes planner-fade-in { from { opacity: 0; } to { opacity: 1; } }
        @keyframes planner-rise-in { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes planner-dialog-in { from { opacity: 0; transform: translateY(10px) scale(.98); } to { opacity: 1; transform: translateY(0) scale(1); } }
        @keyframes planner-focus-pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(167,139,250,.05), inset 0 0 38px rgba(139,92,246,.02); } 50% { box-shadow: 0 0 0 16px rgba(167,139,250,.045), inset 0 0 55px rgba(139,92,246,.11); } }
        .planner-focus-ring { animation: planner-focus-pulse 3.2s ease-in-out infinite; }
        @media (prefers-reduced-motion: reduce) { .planner-page, .planner-enter, .planner-dialog-backdrop, .planner-dialog { animation: none !important; } }
      `}</style>
    </div>
  );

}

function formatCurrency(value, currency = 'PKR') {
  return new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: 0 }).format(Number(value) || 0);
}

function WeekStrip({ selectedDate, tasks, onSelect }) {
  const days = Array.from({ length: 7 }, (_, index) => {
    const day = startOfWeek(new Date(`${selectedDate}T12:00:00`));
    day.setDate(day.getDate() + index);
    return day;
  });
  return (
    <div className="mt-4 grid grid-cols-7 gap-1.5">
      {days.map((day) => {
        const key = localDateKey(day);
        const count = tasks.filter((task) => task.date === key).length;
        const selected = key === selectedDate;
        return <button key={key} type="button" onClick={() => onSelect(key)} className={`flex flex-col items-center rounded-xl py-2.5 transition ${selected ? 'bg-violet-600 text-white shadow-md shadow-violet-200' : 'text-slate-500 hover:bg-slate-50'}`}><span className={`text-[9px] font-bold uppercase ${selected ? 'text-violet-100' : 'text-slate-400'}`}>{new Intl.DateTimeFormat(undefined, { weekday: 'narrow' }).format(day)}</span><span className="mt-1.5 text-sm font-semibold tabular-nums">{day.getDate()}</span><span className={`mt-1.5 size-1 rounded-full ${count ? selected ? 'bg-white' : 'bg-violet-400' : 'bg-transparent'}`} /></button>;
      })}
    </div>
  );
}

function GoalProgress({ goal, progressValue, onIncrement }) {
  const progress = Math.min(100, Math.round((progressValue / Math.max(1, Number(goal.target))) * 100));
  return <div className="rounded-xl border border-slate-100 p-3"><div className="flex items-center justify-between gap-2"><p className="truncate text-sm font-semibold text-slate-700">{goal.title}</p><button type="button" onClick={onIncrement} className="rounded-lg bg-violet-50 px-2 py-1 text-[11px] font-bold text-violet-700">+1</button></div><div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-violet-500 transition-all" style={{ width: `${progress}%` }} /></div><p className="mt-1.5 text-[10px] text-slate-400">{progressValue} of {goal.target} {goal.unit || 'steps'}</p></div>;
}

function GoalCard({ goal, index, progressValue, onIncrement, onDecrement, onDelete }) {
  const progress = Math.min(100, Math.round((progressValue / Math.max(1, Number(goal.target))) * 100));
  const CategoryIcon = CATEGORY_ICONS[goal.category] || Target;
  const tones = ['from-violet-500 to-indigo-500', 'from-blue-500 to-cyan-500', 'from-emerald-500 to-teal-500', 'from-amber-500 to-orange-500'];
  return (
    <Panel className="planner-enter group relative overflow-hidden p-5" style={{ animationDelay: `${index * 45}ms` }}>
      <div className={`absolute inset-x-0 top-0 h-1 bg-gradient-to-r ${tones[index % tones.length]}`} />
      <div className="flex items-start justify-between gap-3">
        <span className={`grid size-10 place-items-center rounded-xl ${CATEGORY_STYLES[goal.category] || CATEGORY_STYLES.Personal}`}><CategoryIcon size={18} /></span>
        <div className="flex items-center gap-2"><span className="rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-slate-500">{goal.period}</span><button type="button" aria-label={`Delete goal ${goal.title}`} onClick={onDelete} className="grid size-8 place-items-center rounded-lg text-slate-300 opacity-0 transition hover:bg-rose-50 hover:text-rose-500 group-hover:opacity-100 focus:opacity-100"><Trash2 size={14} /></button></div>
      </div>
      <h3 className="mt-4 text-base font-semibold text-slate-900">{goal.title}</h3>
      {goal.description && <p className="mt-1 line-clamp-2 text-sm leading-5 text-slate-500">{goal.description}</p>}
      <div className="mt-5 flex items-end justify-between"><div><p className="text-2xl font-semibold tracking-tight text-slate-900 tabular-nums">{progressValue}<span className="text-base font-medium text-slate-400">/{goal.target}</span></p><p className="mt-0.5 text-xs text-slate-400">{goal.unit || 'steps'} completed</p></div><p className="text-sm font-semibold text-slate-500">{progress}%</p></div>
      <div className="mt-2.5 h-2 overflow-hidden rounded-full bg-slate-100"><div className={`h-full rounded-full bg-gradient-to-r ${tones[index % tones.length]} transition-all duration-500`} style={{ width: `${progress}%` }} /></div>
      <div className="mt-4 flex items-center justify-between"><p className="text-xs text-slate-400">{goal.category} · {goal.period.toLowerCase()} intention</p><div className="flex gap-1"><button type="button" onClick={onDecrement} aria-label="Decrease progress" className="grid size-8 place-items-center rounded-lg border border-slate-200 text-slate-500 transition hover:bg-slate-50">−</button><button type="button" onClick={onIncrement} aria-label="Increase progress" className="grid size-8 place-items-center rounded-lg bg-violet-600 text-white transition hover:bg-violet-700"><Plus size={14} /></button></div></div>
    </Panel>
  );
}

function TaskDialog({ date, onClose, onSubmit }) {
  const [title, setTitle] = useState('');
  const [category, setCategory] = useState('Personal');
  const [taskDate, setTaskDate] = useState(date);
  const [time, setTime] = useState('');
  const [priority, setPriority] = useState('Normal');
  const [reminder, setReminder] = useState('');
  return (
    <Dialog title="Make a little plan" description="Add anything you want to give time to—big, small, work, or life." onClose={onClose}>
      <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); if (!title.trim()) return; onSubmit({ title: title.trim(), category, date: taskDate, time, priority, reminder }); }}>
        <FormField label="What do you want to do?"><input autoFocus required value={title} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Call home, finish a reading, take a walk…" className={inputClass} /></FormField>
        <div className="grid gap-4 sm:grid-cols-2"><FormField label="Life area"><select value={category} onChange={(event) => setCategory(event.target.value)} className={inputClass}>{CATEGORIES.map((item) => <option key={item}>{item}</option>)}</select></FormField><FormField label="Priority"><select value={priority} onChange={(event) => setPriority(event.target.value)} className={inputClass}><option>Normal</option><option>High</option><option>Low</option></select></FormField></div>
        <div className="grid gap-4 sm:grid-cols-2"><FormField label="Date"><input type="date" value={taskDate} onChange={(event) => setTaskDate(event.target.value)} className={inputClass} /></FormField><FormField label="Time (optional)"><input type="time" value={time} onChange={(event) => setTime(event.target.value)} className={inputClass} /></FormField></div>
        <FormField label="Reminder (optional)"><input type="datetime-local" value={reminder} onChange={(event) => setReminder(event.target.value)} className={inputClass} /><span className="mt-1.5 block text-[11px] leading-5 text-slate-400">Saved with your task. Notifications and email delivery are not enabled yet.</span></FormField>
        <div className="flex justify-end gap-2 border-t border-slate-100 pt-4"><button type="button" onClick={onClose} className="h-10 rounded-xl px-4 text-sm font-semibold text-slate-500 transition hover:bg-slate-50">Cancel</button><button type="submit" className="inline-flex h-10 items-center gap-2 rounded-xl bg-violet-600 px-4 text-sm font-semibold text-white transition hover:bg-violet-700"><Plus size={15} /> Add to planner</button></div>
      </form>
    </Dialog>
  );
}

function GoalDialog({ onClose, onSubmit }) {
  const [title, setTitle] = useState('');
  const [category, setCategory] = useState('Personal');
  const [period, setPeriod] = useState('Weekly');
  const [target, setTarget] = useState('3');
  const [unit, setUnit] = useState('times');
  const [description, setDescription] = useState('');
  return (
    <Dialog title="Set an intention" description="Choose something that matters to you and a rhythm that feels realistic." onClose={onClose}>
      <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); if (!title.trim()) return; onSubmit({ title: title.trim(), category, period, target: Math.max(1, Number(target)), unit: unit.trim() || 'steps', description: description.trim() }); }}>
        <FormField label="Your goal"><input autoFocus required value={title} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Move my body, save a little, call a friend" className={inputClass} /></FormField>
        <div className="grid gap-4 sm:grid-cols-2"><FormField label="Life area"><select value={category} onChange={(event) => setCategory(event.target.value)} className={inputClass}>{CATEGORIES.map((item) => <option key={item}>{item}</option>)}</select></FormField><FormField label="Timeframe"><select value={period} onChange={(event) => setPeriod(event.target.value)} className={inputClass}>{['Daily', 'Weekly', 'Monthly', 'Yearly'].map((item) => <option key={item}>{item}</option>)}</select></FormField></div>
        <div className="grid gap-4 sm:grid-cols-2"><FormField label="Target"><input type="number" min="1" value={target} onChange={(event) => setTarget(event.target.value)} className={inputClass} /></FormField><FormField label="Measure"><input value={unit} onChange={(event) => setUnit(event.target.value)} placeholder="times, pages, dollars…" className={inputClass} /></FormField></div>
        <FormField label="A note to future you (optional)"><textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={2} placeholder="Why does this matter to you?" className={`${inputClass} resize-y`} /></FormField>
        <div className="flex justify-end gap-2 border-t border-slate-100 pt-4"><button type="button" onClick={onClose} className="h-10 rounded-xl px-4 text-sm font-semibold text-slate-500 hover:bg-slate-50">Cancel</button><button type="submit" className="inline-flex h-10 items-center gap-2 rounded-xl bg-violet-600 px-4 text-sm font-semibold text-white hover:bg-violet-700"><Target size={15} /> Save goal</button></div>
      </form>
    </Dialog>
  );
}

function ExpenseDialog({ date, currency, onClose, onSubmit }) {
  const [title, setTitle] = useState('');
  const [amount, setAmount] = useState('');
  const [category, setCategory] = useState('Food & coffee');
  const [expenseDate, setExpenseDate] = useState(date);
  return (
    <Dialog title="Add an expense" description="A quick note for your own monthly snapshot." onClose={onClose}>
      <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); if (!title.trim() || Number(amount) <= 0) return; onSubmit({ title: title.trim(), amount: Number(amount), category, date: expenseDate }); }}>
        <FormField label="What was it?"><input autoFocus required value={title} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Groceries, bus pass, coffee" className={inputClass} /></FormField>
        <div className="grid gap-4 sm:grid-cols-2"><FormField label={`Amount (${currency || 'PKR'})`}><input type="number" min="0.01" step="0.01" required value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="0.00" className={inputClass} /></FormField><FormField label="Category"><select value={category} onChange={(event) => setCategory(event.target.value)} className={inputClass}>{['Food & coffee', 'Travel', 'Books & supplies', 'Personal', 'Bills', 'Other'].map((item) => <option key={item}>{item}</option>)}</select></FormField></div>
        <FormField label="Date"><input type="date" value={expenseDate} onChange={(event) => setExpenseDate(event.target.value)} className={inputClass} /></FormField>
        <div className="flex justify-end gap-2 border-t border-slate-100 pt-4"><button type="button" onClick={onClose} className="h-10 rounded-xl px-4 text-sm font-semibold text-slate-500 hover:bg-slate-50">Cancel</button><button type="submit" className="inline-flex h-10 items-center gap-2 rounded-xl bg-violet-600 px-4 text-sm font-semibold text-white hover:bg-violet-700"><Plus size={15} /> Save expense</button></div>
      </form>
    </Dialog>
  );
}

function BudgetDialog({ current, currency, onClose, onSubmit }) {
  const [amount, setAmount] = useState(String(current || ''));
  return (
    <Dialog title="Set a monthly budget" description="A flexible estimate can make everyday choices feel clearer." onClose={onClose}>
      <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); onSubmit(Math.max(0, Number(amount) || 0)); }}>
        <FormField label={`Monthly amount (${currency || 'PKR'})`}><input autoFocus type="number" min="0" step="1" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="e.g. 600" className={inputClass} /></FormField>
        <p className="text-xs leading-5 text-slate-400">This is a personal planning tool. No financial accounts are connected.</p>
        <div className="flex justify-end gap-2 border-t border-slate-100 pt-4"><button type="button" onClick={onClose} className="h-10 rounded-xl px-4 text-sm font-semibold text-slate-500 hover:bg-slate-50">Cancel</button><button type="submit" className="inline-flex h-10 items-center gap-2 rounded-xl bg-violet-600 px-4 text-sm font-semibold text-white hover:bg-violet-700"><Check size={15} /> Save budget</button></div>
      </form>
    </Dialog>
  );
}

export default function DashboardLoading() {
  return (
    <div className="flex h-[60vh] w-full flex-col items-center justify-center gap-3" aria-live="polite">
      <span className="size-6 animate-spin rounded-full border-2 border-line border-t-violet" />
      <span className="text-xs font-medium text-muted">Loading workspace…</span>
    </div>
  );
}

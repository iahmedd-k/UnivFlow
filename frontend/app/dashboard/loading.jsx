export default function DashboardLoading() {
  return (
    <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 pb-10" aria-busy="true" aria-live="polite" aria-label="Loading workspace page">
      <div className="space-y-2">
        <div className="h-3 w-28 animate-pulse rounded bg-border-light" />
        <div className="h-8 w-56 animate-pulse rounded-lg bg-border-light" />
        <div className="h-4 w-80 max-w-full animate-pulse rounded bg-border-light" />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {[0, 1, 2, 3].map((item) => (
          <div className="min-h-36 animate-pulse rounded-xl border border-border bg-surface p-5" key={item}>
            <div className="h-4 w-32 rounded bg-border-light" />
            <div className="mt-5 h-3 w-full rounded bg-border-light" />
            <div className="mt-2 h-3 w-2/3 rounded bg-border-light" />
          </div>
        ))}
      </div>
    </div>
  );
}

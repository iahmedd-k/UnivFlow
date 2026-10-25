export function BrandLogo({
  size = 38,
  showText = true,
  className = "",
}: {
  size?: number;
  showText?: boolean;
  className?: string;
}) {
  return (
    <div className={`flex items-center gap-3 select-none ${className}`}>
      <div
        style={{ width: size, height: size }}
        className="rounded-xl bg-gradient-to-tr from-indigo-700 via-indigo-600 to-violet-500 shadow-md shadow-indigo-500/25 flex items-center justify-center shrink-0 border border-indigo-400/30 transition-transform hover:scale-[1.02]"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          className="w-5 h-5 text-white stroke-[2.2]"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
          <path d="M8 7h8" />
          <path d="M8 11h8" />
          <path d="M8 15h5" />
        </svg>
      </div>
      {showText && (
        <div className="flex flex-col text-left">
          <span className="text-[17px] font-bold text-stone-900 tracking-tight leading-none">
            DocSense
          </span>
          <span className="text-[11px] text-stone-400 font-medium tracking-wide mt-1">
            Enterprise Hybrid Search & Verified Q&A
          </span>
        </div>
      )}
    </div>
  );
}

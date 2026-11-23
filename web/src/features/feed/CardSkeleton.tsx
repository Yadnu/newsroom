export function CardSkeleton() {
  return (
    <div role="status" aria-label="Loading stories" className="flex h-full w-full flex-col bg-set">
      <div className="h-[36%] min-h-40 w-full animate-pulse bg-set-2 sm:h-[44%]" />
      <div className="flex flex-col gap-3 px-5 pt-4 sm:px-10">
        <div className="h-3 w-40 animate-pulse rounded bg-white/10" />
        <div className="h-8 w-11/12 animate-pulse rounded bg-white/15" />
        <div className="h-8 w-2/3 animate-pulse rounded bg-white/15" />
        <div className="mt-2 h-4 w-full animate-pulse rounded bg-white/10" />
        <div className="h-4 w-full animate-pulse rounded bg-white/10" />
        <div className="h-4 w-4/5 animate-pulse rounded bg-white/10" />
      </div>
    </div>
  );
}

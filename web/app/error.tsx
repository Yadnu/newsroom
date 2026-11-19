"use client";

export default function ErrorPage({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="error">
      <p>
        <b>Could not load the archive.</b> Is the API running (
        <code>uv run fastapi dev app/main.py</code>) and <code>NEWSROOM_API_URL</code> pointing at
        it?
      </p>
      <p className="mono">{error.message}</p>
      <button onClick={reset}>Try again</button>
    </div>
  );
}

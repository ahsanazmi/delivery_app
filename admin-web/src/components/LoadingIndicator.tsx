export function LoadingIndicator({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="page-center" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}
    </div>
  );
}

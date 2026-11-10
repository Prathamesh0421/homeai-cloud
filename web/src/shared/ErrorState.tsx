/** ErrorState: friendly error display with retry. */

export interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
}

export function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-danger/30 bg-danger-soft py-8 text-center">
      <p className="text-sm font-medium text-danger">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-md border border-danger/40 bg-surface px-3 py-1.5 text-xs font-medium text-danger hover:bg-danger-soft"
        >
          Retry
        </button>
      )}
    </div>
  );
}

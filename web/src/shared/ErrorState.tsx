/** ErrorState: friendly error display with retry. */

export interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
}

export function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-red-200 bg-red-50 py-8 text-center">
      <p className="text-sm font-medium text-red-700">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded border border-red-300 px-3 py-1 text-xs text-red-700 hover:bg-red-100"
        >
          Retry
        </button>
      )}
    </div>
  );
}

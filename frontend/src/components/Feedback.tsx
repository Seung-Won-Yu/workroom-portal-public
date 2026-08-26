export function LoadingState() {
  return (
    <div className="loading-state" role="status">
      <span />
      <span />
      <span />
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="error-state" role="alert">
      {message}
    </div>
  );
}

export function NoticeState({ message }: { message: string }) {
  return (
    <div className="notice-state" role="status">
      <span aria-hidden="true" />
      <strong>{message}</strong>
    </div>
  );
}

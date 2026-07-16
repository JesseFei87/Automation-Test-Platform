import type { ReactNode } from "react";
import { StatusPill } from "./StatusPill";

type TaskMetric = {
  label: string;
  value: ReactNode;
};

export function TaskCard({
  title,
  taskId,
  status,
  progress,
  metrics = [],
  logs = [],
  actions,
  children,
}: {
  title: string;
  taskId?: string;
  status?: string;
  progress?: {
    label?: string;
    current?: number;
    total?: number;
  };
  metrics?: TaskMetric[];
  logs?: Array<{
    time?: string;
    message: string;
  }>;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  const percent = progress?.total
    ? Math.round(((progress.current || 0) / progress.total) * 100)
    : 0;
  return (
    <section className="card task-card">
      <header className="card__header">
        <h2>{title}</h2>
        {taskId ? <p>{taskId}</p> : null}
      </header>

      {status ? (
        <StatusPill>{status}</StatusPill>
      ) : null}

      {progress ? (
        <div className="task-card__progress">
          <span>{progress.label || "进度"}</span>
          <strong>{percent}% ({progress.current || 0}/{progress.total || 0})</strong>
        </div>
      ) : null}

      {metrics.length ? (
        <div className="task-card__metrics">
          {metrics.map((item) => (
            <div key={item.label}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>
      ) : null}

      {logs.length ? (
        <div className="task-card__logs">
          {logs.map((log, index) => (
            <p key={`${log.time || index}-${index}`}>
              {log.time ? `${log.time} ` : ""}{log.message}
            </p>
          ))}
        </div>
      ) : null}

      {actions}

      {children}
    </section>
  );
}
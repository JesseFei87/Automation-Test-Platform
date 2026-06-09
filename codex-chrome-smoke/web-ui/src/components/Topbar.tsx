import { StatusPill } from "./StatusPill";

export function Topbar({
  title,
  subtitle,
  modelLabel = "AI 未配置",
  dashboard = false,
}: {
  title: string;
  subtitle: string;
  modelLabel?: string;
  dashboard?: boolean;
}) {
  return (
    <header className={`topbar ${dashboard ? "topbar--dashboard" : ""}`}>
      <div>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      <div className="topbar__actions">
        {dashboard ? null : <input className="search" placeholder="搜索 case / run / 需求" readOnly />}
        <StatusPill tone="cyan">{modelLabel}</StatusPill>
        {dashboard ? <StatusPill tone="green">Batch 001-012</StatusPill> : null}
        {dashboard ? <button className="btn btn--primary">新建分析</button> : null}
      </div>
    </header>
  );
}

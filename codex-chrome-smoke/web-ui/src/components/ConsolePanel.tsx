export function ConsolePanel({ lines, running = false }: { lines: string[]; running?: boolean }) {
  return (
    <div className="console">
      {running ? <span className="console__badge">RUNNING</span> : null}
      {lines.map((line, index) => (
        <p className={line.includes("remoteView") || line.includes("opened") ? "is-success" : ""} key={`${index}-${line}`}>
          {line}
        </p>
      ))}
    </div>
  );
}

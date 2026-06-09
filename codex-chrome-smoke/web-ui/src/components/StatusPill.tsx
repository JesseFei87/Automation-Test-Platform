import type { ReactNode } from "react";

type Tone = "blue" | "green" | "amber" | "red" | "cyan" | "dark" | "purple";

export function StatusPill({ children, tone = "blue" }: { children: ReactNode; tone?: Tone }) {
  return <span className={`status-pill status-pill--${tone}`}>{children}</span>;
}

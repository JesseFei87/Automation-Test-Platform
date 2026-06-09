import { flowSteps } from "../data/navigation";

export function FlowSteps({ activeIndex, compact = false }: { activeIndex: number; compact?: boolean }) {
  return (
    <div className={`flow ${compact ? "flow--compact" : ""}`} aria-label="约定流程">
      <span className="flow__label">约定流程</span>
      <div className="flow__track">
        {flowSteps.map((step, index) => {
          const active = index <= activeIndex;
          return (
            <div className={`flow__step ${active ? "is-active" : ""}`} key={step}>
              <span className="flow__dot">{index + 1}</span>
              <span className="flow__name">{step}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

import { useState } from "react";
import type { ReactElement, ReactNode } from "react";
import { navItems } from "../data/navigation";
import type { NavIconKey, PageId } from "../types";

type IconProps = {
  className?: string;
};

const icons: Record<NavIconKey, (props: IconProps) => ReactElement> = {
  home: HomeIcon,
  requirements: FileTextIcon,
  points: NetworkIcon,
  cases: ClipboardIcon,
  execution: PlayIcon,
  reports: ReportIcon,
  settings: SettingsIcon,
};

export function Sidebar({
  activePage,
  onNavigate,
}: {
  activePage: PageId;
  onNavigate: (page: PageId) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside className={`sidebar ${collapsed ? "sidebar--collapsed" : ""}`}>
      <div className="sidebar__head">
        <button className="brand" type="button" onClick={() => onNavigate("dashboard")} aria-label="返回首页">
          <strong>ICM AI</strong>
          <span>自动化测试平台</span>
        </button>
        <button
          className="sidebar-toggle"
          type="button"
          aria-label={collapsed ? "展开左侧边栏" : "折叠左侧边栏"}
          title={collapsed ? "展开" : "折叠"}
          onClick={() => setCollapsed((current) => !current)}
        >
          <ChevronIcon className="sidebar-toggle__icon" />
        </button>
      </div>

      <nav className="nav" aria-label="主导航">
        {navItems.map((item) => {
          const Icon = icons[item.icon];
          return (
            <button
              aria-label={item.label}
              className={`nav__item ${item.id === activePage ? "is-active" : ""}`}
              key={item.id}
              title={collapsed ? item.label : undefined}
              type="button"
              onClick={() => onNavigate(item.id)}
            >
              <Icon className="nav__icon" />
              <span className="nav__label">{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="runner-card" title="Runner Ready · Python / Playwright · TC-ICM-001 到 012">
        <strong>Runner Ready</strong>
        <p>Python / Playwright</p>
        <p>TC-ICM-001 到 012</p>
      </div>
    </aside>
  );
}

function IconFrame({ className, children }: IconProps & { children: ReactNode }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {children}
    </svg>
  );
}

function HomeIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <path d="M4.2 10.6 12 4l7.8 6.6" />
      <path d="M6.5 9.8v9h4.1v-5.2h2.8v5.2h4.1v-9" />
    </IconFrame>
  );
}

function FileTextIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <path d="M6.7 3.8h7.1l3.5 3.6v12.8H6.7z" />
      <path d="M13.7 3.9v3.8h3.6" />
      <path d="M9 12h6" />
      <path d="M9 15.3h5" />
    </IconFrame>
  );
}

function NetworkIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <circle cx="12" cy="5.4" r="2.2" />
      <circle cx="6.2" cy="17.8" r="2.2" />
      <circle cx="17.8" cy="17.8" r="2.2" />
      <path d="M11.1 7.5 7.2 15.8" />
      <path d="m12.9 7.5 3.9 8.3" />
      <path d="M8.4 17.8h7.2" />
    </IconFrame>
  );
}

function ClipboardIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <path d="M8.7 5.8H6.2v14.4h11.6V5.8h-2.5" />
      <path d="M9.2 3.8h5.6v3.4H9.2z" />
      <path d="M9 11.5h6" />
      <path d="M9 15h4.6" />
    </IconFrame>
  );
}

function PlayIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="m10.2 8.7 5.1 3.3-5.1 3.3z" />
    </IconFrame>
  );
}

function ReportIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <path d="M5.4 19.6V4.4h13.2v15.2z" />
      <path d="M8.3 15.7v-3.5" />
      <path d="M12 15.7V8.8" />
      <path d="M15.7 15.7v-5.1" />
    </IconFrame>
  );
}

function SettingsIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <circle cx="12" cy="12" r="2.7" />
      <path d="M12 3.8v2.1" />
      <path d="M12 18.1v2.1" />
      <path d="m5.8 5.8 1.5 1.5" />
      <path d="m16.7 16.7 1.5 1.5" />
      <path d="M3.8 12h2.1" />
      <path d="M18.1 12h2.1" />
      <path d="m5.8 18.2 1.5-1.5" />
      <path d="m16.7 7.3 1.5-1.5" />
    </IconFrame>
  );
}

function ChevronIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <path d="m9 6 6 6-6 6" />
    </IconFrame>
  );
}

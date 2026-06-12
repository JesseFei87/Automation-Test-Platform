export type PageId = "dashboard" | "projects" | "requirements" | "ai-generate" | "points" | "cases" | "execution" | "reports" | "settings";

export type NavIconKey = "home" | "requirements" | "points" | "cases" | "execution" | "reports" | "settings";

export type NavItem = {
  id: PageId;
  label: string;
  icon: NavIconKey;
};

export type PlatformNavKey =
  | "dashboard"
  | "projects"
  | "requirements"
  | "cases"
  | "ai-generate"
  | "ai-test"
  | "reports"
  | "settings";

export type PlatformNavItem = {
  key: PlatformNavKey;
  label: string;
  page: PageId;
  badge?: string;
};

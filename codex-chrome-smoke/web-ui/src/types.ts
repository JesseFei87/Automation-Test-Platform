export type PageId = "dashboard" | "requirements" | "points" | "cases" | "execution" | "reports" | "settings";

export type NavIconKey = "home" | "requirements" | "points" | "cases" | "execution" | "reports" | "settings";

export type NavItem = {
  id: PageId;
  label: string;
  icon: NavIconKey;
};

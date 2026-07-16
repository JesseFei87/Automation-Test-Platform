import type { NavItem, PlatformNavItem } from "../types";

export const navItems: NavItem[] = [
  { id: "dashboard", label: "工作台", icon: "home" },
  { id: "projects", label: "项目管理", icon: "requirements" },
  { id: "requirements", label: "需求管理", icon: "requirements" },
  { id: "cases", label: "用例管理", icon: "cases" },
  { id: "execution", label: "AI测试", icon: "execution" },
  { id: "reports", label: "测试报告", icon: "reports" },
  { id: "settings", label: "配置中心", icon: "settings" },
];

export const platformNavItems: PlatformNavItem[] = [
  { key: "dashboard", label: "工作台", page: "dashboard" },
  { key: "projects", label: "项目管理", page: "projects" },
  { key: "requirements", label: "需求管理", page: "requirements" },
  { key: "cases", label: "用例管理", page: "cases" },
  { key: "recorder", label: "录制中心", page: "recorder" },
  { key: "ai-generate", label: "AI生成", page: "ai-generate", badge: "AI" },
  { key: "ai-test", label: "AI测试", page: "execution", badge: "AI" },
  { key: "reports", label: "测试报告", page: "reports", badge: "AI" },
  { key: "element-knowledge", label: "元素知识库", page: "element-knowledge", badge: "AI" },
  { key: "settings", label: "配置中心", page: "settings" },
];

export const flowSteps = ["业务目标", "YAML", "真实页面跑通", "case 沉淀", "Python 脚本化", "日常回归"];

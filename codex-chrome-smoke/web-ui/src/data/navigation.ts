import type { NavItem } from "../types";

export const navItems: NavItem[] = [
  { id: "dashboard", label: "首页", icon: "home" },
  { id: "requirements", label: "需求工作台", icon: "requirements" },
  { id: "points", label: "测试点", icon: "points" },
  { id: "cases", label: "用例工具箱", icon: "cases" },
  { id: "execution", label: "执行中心", icon: "execution" },
  { id: "reports", label: "报告中心", icon: "reports" },
  { id: "settings", label: "系统设置", icon: "settings" },
];

export const flowSteps = ["业务目标", "YAML", "真实页面跑通", "case 沉淀", "Python 脚本化", "日常回归"];

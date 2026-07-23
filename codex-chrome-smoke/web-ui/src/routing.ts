import type { PageId } from "./types";

export type AppRoute = {
  page: PageId;
  runId?: string;
  draftId?: number;
};

const PATH_BY_PAGE: Record<PageId, string> = {
  dashboard: "/",
  projects: "/projects",
  requirements: "/requirements",
  "ai-generate": "/ai-generate",
  points: "/test-points",
  cases: "/cases",
  recorder: "/recorder",
  execution: "/ai-test",
  reports: "/reports",
  "element-knowledge": "/element-knowledge",
  settings: "/settings",
};

const PAGE_BY_PATH = new Map(Object.entries(PATH_BY_PAGE).map(([page, path]) => [path, page as PageId]));

export function parseAppRoute(hash: string, fallback: PageId = "dashboard"): AppRoute {
  const raw = hash.replace(/^#/, "");
  const legacy = raw.startsWith("case-toolbox") ? raw.replace(/^case-toolbox/, "/cases") : raw;
  const [pathValue, query = ""] = legacy.split("?", 2);
  const path = pathValue || "/";
  const detailMatch = /^\/(reports|ai-test)\/(.+)$/.exec(path);
  if (detailMatch) {
    return {
      page: detailMatch[1] === "reports" ? "reports" : "execution",
      runId: decodeURIComponent(detailMatch[2]),
    };
  }

  const page = PAGE_BY_PATH.get(path) || fallback;
  const draft = page === "cases" ? Number(new URLSearchParams(query).get("draft")) : NaN;
  return { page, ...(Number.isInteger(draft) && draft > 0 ? { draftId: draft } : {}) };
}

export function buildAppHash(route: AppRoute): string {
  const path = PATH_BY_PAGE[route.page];
  if ((route.page === "reports" || route.page === "execution") && route.runId) {
    return `#${path}/${encodeURIComponent(route.runId)}`;
  }
  if (route.page === "cases" && route.draftId) {
    return `#${path}?draft=${route.draftId}`;
  }
  return `#${path}`;
}

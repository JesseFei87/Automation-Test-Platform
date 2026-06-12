import path from "node:path";
import { buildRunId, cloneChromeProfile, ensureDir, reportsRoot, screenshotsRoot, writeText } from "./runtime.mjs";
import { capture, icmCases } from "./icm-cases.mjs";
import { loadPlaywright, defaultChromeProfileDir } from "./runtime.mjs";

const orderedCases = [
  "TC-ICM-001",
  "TC-ICM-002",
  "TC-ICM-003",
  "TC-ICM-004",
  "TC-ICM-005",
  "TC-ICM-006",
  "TC-ICM-007",
  "TC-ICM-008",
  "TC-ICM-009",
  "TC-ICM-010",
  "TC-ICM-011",
];

const runId = process.argv[2] || buildRunId("icm-batch");
const runDir = path.join(screenshotsRoot, runId);
const reportPath = path.join(reportsRoot, `${runId}.md`);
await ensureDir(runDir);
await ensureDir(reportsRoot);
const { cloneUserDataDir, cloneProfileDir } = await cloneChromeProfile();

const { chromium } = await loadPlaywright();
const userDataDir = process.env.ICM_CHROME_USER_DATA_DIR || cloneUserDataDir;
const profileDir = process.env.ICM_CHROME_PROFILE_DIR || cloneProfileDir || defaultChromeProfileDir;
const context = await chromium.launchPersistentContext(userDataDir, {
  channel: "chrome",
  headless: false,
  viewport: null,
  args: ["--start-maximized", `--profile-directory=${profileDir}`],
});
const page = context.pages()[0] ?? await context.newPage();
const ctx = { page, context, runId };

const results = [];
for (const caseId of orderedCases) {
  const caseDef = icmCases[caseId];
  try {
    await page.goto("https://192.168.16.203:49187/#/system/user");
    await page.waitForLoadState("domcontentloaded").catch(() => {});
    await capture({ ...ctx, caseId }, runDir, `${caseId}-01-entry.png`).catch(() => {});
    const result = await caseDef.run({ ...ctx, caseId });
    await capture({ ...ctx, caseId }, runDir, `${caseId}-02-action.png`).catch(() => {});
    await capture({ ...ctx, caseId }, runDir, `${caseId}-03-final.png`).catch(() => {});
    results.push({ caseId, status: result?.status ?? "failed" });
    if ((result?.status ?? "failed") !== "passed") break;
  } catch (error) {
    results.push({ caseId, status: "blocked", failure: error instanceof Error ? error.message : String(error) });
    break;
  }
}

const report = `# ICM Batch Run ${runId}

${results.map((r) => `- ${r.caseId}: ${r.status}${r.failure ? ` (${r.failure})` : ""}`).join("\n")}
`;
await writeText(reportPath, report);
await context.close();
console.log(report);

import path from "node:path";
import {
  buildRunId,
  cloneChromeProfile,
  ensureDir,
  loadPlaywright,
  defaultChromeProfileDir,
  reportsRoot,
  screenshotsRoot,
  writeText,
} from "./runtime.mjs";
import { capture, icmCases } from "./icm-cases.mjs";

const caseId = process.argv[2];
if (!caseId) {
  console.error("Usage: node scripts/run-icm-case.mjs TC-ICM-008");
  process.exit(1);
}

const caseDef = icmCases[caseId];
if (!caseDef) {
  console.error(`Unknown case: ${caseId}`);
  process.exit(1);
}

const runId = buildRunId(caseId);
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

const ctx = { page, context, caseId, runId };
await page.goto("about:blank");
await page.waitForTimeout(300);

let result;
let failure = "";
try {
  await page.goto("https://192.168.16.203:49187/#/system/user");
  await page.waitForLoadState("domcontentloaded").catch(() => {});
  await capture(ctx, runDir, "01-entry.png").catch(() => {});
  result = await caseDef.run(ctx);
  await capture(ctx, runDir, "02-action.png").catch(() => {});
  await capture(ctx, runDir, "03-final.png").catch(() => {});
} catch (error) {
  result = { status: "blocked" };
  failure = error instanceof Error ? error.message : String(error);
  await capture(ctx, runDir, "02-action.png").catch(() => {});
}

const finalStatus = result?.status ?? "failed";
const report = `# Run Report: ${runId}

- case_id: ${caseId}
- case_title: ${caseDef.title}
- status: ${finalStatus}
- failure: ${failure || "none"}
- screenshots:
  - ${path.join(runDir, "01-entry.png")}
  - ${path.join(runDir, "02-action.png")}
  - ${path.join(runDir, "03-final.png")}
`;

await writeText(reportPath, report);
await context.close();
console.log(report);

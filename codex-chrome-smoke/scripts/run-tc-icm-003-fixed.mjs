import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright-core";

const root = path.resolve("C:/Users/FQ1017/Documents/ICM/codex-chrome-smoke");
const runId = `20260529-tc-icm-003-${Date.now()}`;
const runDir = path.join(root, "screenshots", runId);
await fs.mkdir(runDir, { recursive: true });

const baseUrl = "https://192.168.16.203:49187";
const entryUrl = `${baseUrl}/#/login?redirect=%2Fredirect`;
const admin = { username: "admin", password: "Hubble_Service!1088" };
const queryKeyword = "AU5800";

const browser = await chromium.launch({
  headless: true,
  executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
});

const context = await browser.newContext({
  ignoreHTTPSErrors: true,
  viewport: { width: 1440, height: 1080 },
});

const page = await context.newPage();

await page.goto(entryUrl, { waitUntil: "domcontentloaded" });
await page.getByPlaceholder(/账号|account/).fill(admin.username);
await page.getByPlaceholder(/密码|password/).fill(admin.password);
await page.getByRole("button", { name: /登录|login/ }).click();
await page.waitForLoadState("networkidle").catch(() => {});

const entryShot = path.join(runDir, "TC-ICM-003-01-entry.png");
await page.screenshot({ path: entryShot, fullPage: false });

await page.getByText("ICM", { exact: true }).click();
await page.locator('a[href="#/hubble/device"]').click();
await page.waitForLoadState("networkidle").catch(() => {});

const actionShot = path.join(runDir, "TC-ICM-003-02-action.png");
await page.screenshot({ path: actionShot, fullPage: false });

const queryInput = page.getByPlaceholder(/请输入设备名称|请输入设备名|device/i).first();
await queryInput.fill(queryKeyword);
await page.keyboard.press("Enter").catch(() => {});
await page.waitForTimeout(1500);

const finalShot = path.join(runDir, "TC-ICM-003-03-final.png");
await page.screenshot({ path: finalShot, fullPage: false });

const bodyText = await page.locator("body").innerText().catch(() => "");
const tableText = await page.locator("table").innerText().catch(() => "");
const status = tableText.includes(queryKeyword) || bodyText.includes(queryKeyword) ? "passed" : "failed";

const report = `# Run Report

- run_id: \`${runId}\`
- date: \`2026-05-29\`
- operator: \`Codex\`
- environment: \`Chrome / ICM Internal Portal\`

## Case Result

| ID | Title | Result | Notes |
| --- | --- | --- | --- |
| TC-ICM-003 | ICM device list query | ${status} | Opened \`ICM > 设备信息\`, queried \`${queryKeyword}\`, and stayed on the device list view. |

## Screenshot Paths

- \`${entryShot}\`
- \`${actionShot}\`
- \`${finalShot}\`
`;

await fs.writeFile(path.join(root, "reports", "runs", `${runId}.md`), report, "utf8");

await browser.close();

console.log(JSON.stringify({ runId, runDir, status, entryShot, actionShot, finalShot }, null, 2));

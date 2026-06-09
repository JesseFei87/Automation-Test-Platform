import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const outputRoot = repoRoot;
export const screenshotsRoot = path.join(repoRoot, "screenshots");
export const reportsRoot = path.join(repoRoot, "reports", "runs");
export const defaultBaseUrl = "https://192.168.16.203:49187";
export const defaultEntryUrl = `${defaultBaseUrl}/#/login?redirect=%2Fredirect`;
export const defaultChromeUserDataDir = "C:/Users/FQ1017/AppData/Local/Google/Chrome/User Data";
export const defaultChromeProfileDir = "Profile 2";
export const defaultChromeCloneRoot = path.join(repoRoot, ".chrome-profile-clone");
export const defaultChromeCloneUserDataDir = path.join(defaultChromeCloneRoot, "User Data");
export const defaultChromeCloneProfileDir = defaultChromeProfileDir;
export const playwrightModuleUrl = pathToFileURL(
  "C:/Users/FQ1017/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/.pnpm/playwright@1.60.0/node_modules/playwright/index.mjs",
).href;

export async function loadPlaywright() {
  return await import(playwrightModuleUrl);
}

export async function ensureDir(dir) {
  await fs.mkdir(dir, { recursive: true });
}

export function nowStamp(date = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
    "-",
    pad(date.getHours()),
    pad(date.getMinutes()),
  ].join("");
}

export function buildRunId(caseId) {
  return `${nowStamp()}-${caseId.toLowerCase()}`;
}

export async function writeText(filePath, text) {
  await ensureDir(path.dirname(filePath));
  await fs.writeFile(filePath, text, "utf8");
}

export async function writeJson(filePath, value) {
  await writeText(filePath, JSON.stringify(value, null, 2));
}

function shouldSkipChromeCloneEntry(name) {
  return [
    "SingletonLock",
    "SingletonCookie",
    "SingletonSocket",
    "lockfile",
    "LOCK",
  ].includes(name);
}

export async function cloneChromeProfile({
  sourceUserDataDir = defaultChromeUserDataDir,
  sourceProfileDir = defaultChromeProfileDir,
  cloneUserDataDir = defaultChromeCloneUserDataDir,
} = {}) {
  const sourceProfilePath = path.join(sourceUserDataDir, sourceProfileDir);
  const targetProfilePath = path.join(cloneUserDataDir, sourceProfileDir);
  await ensureDir(cloneUserDataDir);
  const filesToCopy = ["Local State"];
  const profileEntriesToCopy = [
    "Preferences",
    "Secure Preferences",
    "History",
    "Cookies",
    "Cookies-journal",
    "Web Data",
    "Login Data",
    "Login Data-journal",
  ];
  const dirsToCopy = [
    "Local Storage",
    "Session Storage",
    "IndexedDB",
    "WebStorage",
    "Service Worker",
    "Storage",
    "Shared Dictionary",
  ];
  for (const fileName of filesToCopy) {
    await fs.copyFile(path.join(sourceUserDataDir, fileName), path.join(cloneUserDataDir, fileName)).catch(() => {});
  }
  await ensureDir(targetProfilePath);
  for (const entry of profileEntriesToCopy) {
    await fs.cp(path.join(sourceProfilePath, entry), path.join(targetProfilePath, entry), { recursive: true, force: true }).catch(() => {});
  }
  for (const dirName of dirsToCopy) {
    await fs.cp(path.join(sourceProfilePath, dirName), path.join(targetProfilePath, dirName), { recursive: true, force: true }).catch(() => {});
  }
  return { cloneUserDataDir, cloneProfileDir: sourceProfileDir };
}

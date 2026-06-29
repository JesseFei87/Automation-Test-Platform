import { chromium } from "playwright-core";

const VIEWPORT = { width: 1321, height: 800 };
const URL_ROOT = "http://127.0.0.1:5175/";
const STORAGE_KEY = "icm.currentPage";

function buildSelectorPath(el) {
  const parts = [];
  let node = el;
  let depth = 0;
  while (node && node.nodeType === 1 && depth < 8) {
    let part = node.tagName.toLowerCase();
    if (node.classList && node.classList.length) {
      const cls = Array.from(node.classList).slice(0, 3).join(".");
      if (cls) part += "." + cls;
    }
    const parent = node.parentElement;
    if (parent) {
      const same = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
      if (same.length > 1) {
        part += `:nth-of-type(${same.indexOf(node) + 1})`;
      }
    }
    parts.unshift(part);
    if (node.id) {
      parts[0] = node.tagName.toLowerCase() + "#" + node.id;
      break;
    }
    node = parent;
    depth += 1;
  }
  return parts.join(" > ");
}

async function main() {
  const browser = await chromium.launch({
    channel: "chrome",
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1 });
  await context.addInitScript(([k, v]) => {
    try { window.localStorage.setItem(k, v); } catch (e) {}
  }, [STORAGE_KEY, "execution"]);
  const page = await context.newPage();
  await page.goto(URL_ROOT, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2500);

  // Verify which page is rendered.
  const pageState = await page.evaluate(() => ({
    currentPage: window.localStorage.getItem("icm.currentPage"),
    hasExecutionPage: !!document.querySelector(".execution-page"),
    hasExecutionGrid: !!document.querySelector(".execution-grid"),
    hasPreviewHead: !!document.querySelector(".execution-preview-head"),
    hasPreviewStat: !!document.querySelectorAll(".execution-preview-stat").length,
    previewStatCount: document.querySelectorAll(".execution-preview-stat").length,
    docW: document.documentElement.clientWidth,
    scrollW: document.documentElement.scrollWidth,
  }));
  console.log("=== PAGE_STATE ===");
  console.log(JSON.stringify(pageState, null, 2));

  const result = await page.evaluate((selBuilderSource) => {
    const docW = document.documentElement.clientWidth;
    const builder = new Function("el", selBuilderSource + "; return buildSelectorPath(el);");
    const offending = [];
    for (const el of document.querySelectorAll("*")) {
      const r = el.getBoundingClientRect();
      if (r.right > docW + 0.5 && r.width > 0) {
        const cs = window.getComputedStyle(el);
        let n = el;
        const chain = [];
        let depth = 0;
        while (n && n.nodeType === 1 && depth < 12) {
          const cs2 = window.getComputedStyle(n);
          chain.push({
            tag: n.tagName.toLowerCase(),
            cls: n.className && typeof n.className === "string" ? n.className : "",
            minWidth: cs2.minWidth,
            width: cs2.width,
            display: cs2.display,
            gridTemplateColumns: cs2.gridTemplateColumns || "",
            overflowX: cs2.overflowX,
            rect_width: n.getBoundingClientRect().width,
            rect_right: n.getBoundingClientRect().right,
          });
          n = n.parentElement;
          depth += 1;
        }
        let selector;
        try { selector = builder(el); } catch (e) { selector = "(build-failed)"; }
        offending.push({
          selector,
          tag: el.tagName.toLowerCase(),
          id: el.id || "",
          className: el.className && typeof el.className === "string" ? el.className : "",
          rect_width: r.width,
          rect_right: r.right,
          computed_width: cs.width,
          computed_minWidth: cs.minWidth,
          overflow: cs.overflowX + "/" + cs.overflowY,
          gridTemplateColumns: cs.gridTemplateColumns || "",
          display: cs.display,
          overshoot: r.right - docW,
          ancestor_chain: chain,
        });
      }
    }
    offending.sort((a, b) => b.overshoot - a.overshoot);
    return offending.slice(0, 5);
  }, buildSelectorPath.toString());

  console.log("=== TOP5_FULL ===");
  console.log(JSON.stringify(result, null, 2));
  await browser.close();
}

main().catch((e) => {
  console.error("FAIL:", e && e.stack ? e.stack : e);
  process.exit(1);
});

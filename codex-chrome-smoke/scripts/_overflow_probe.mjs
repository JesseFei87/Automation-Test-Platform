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

async function probePage(context, pageId, label) {
  const page = await context.newPage();
  await page.goto(URL_ROOT, { waitUntil: "domcontentloaded" });
  await page.evaluate(([k, v]) => {
    try { window.localStorage.setItem(k, v); } catch (e) {}
  }, [STORAGE_KEY, pageId]);
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);

  const result = await page.evaluate((selBuilderSource) => {
    const docW = document.documentElement.clientWidth;
    const builder = new Function("el", selBuilderSource + "; return buildSelectorPath(el);");

    const docInfo = {
      clientWidth: docW,
      scrollWidth: document.documentElement.scrollWidth,
      bodyScrollWidth: document.body.scrollWidth,
      bodyClientWidth: document.body.clientWidth,
      hasHorizontalScroll: document.documentElement.scrollWidth > docW,
      location: location.href,
    };

    const classify = {};
    function pick(sel) {
      const el = document.querySelector(sel);
      if (!el) { classify[sel] = null; return; }
      const cs = window.getComputedStyle(el);
      const r = el.getBoundingClientRect();
      classify[sel] = {
        selector: sel,
        minWidth: cs.minWidth,
        width: cs.width,
        display: cs.display,
        gridTemplateColumns: cs.gridTemplateColumns || "",
        overflowX: cs.overflowX,
        overflowY: cs.overflowY,
        rect_width: r.width,
        rect_right: r.right,
      };
    }
    ["html", "body", ".app", ".app--ai-generate", ".app--execution",
     ".page", ".requirements-page", ".requirements-layout",
     ".main.platform-main", ".execution-center"].forEach(pick);

    const offending = [];
    for (const el of document.querySelectorAll("*")) {
      const r = el.getBoundingClientRect();
      if (r.right > docW + 0.5 && r.width > 0) {
        const cs = window.getComputedStyle(el);
        const entry = {
          tag: el.tagName.toLowerCase(),
          id: el.id || "",
          className: el.className && typeof el.className === "string" ? el.className : "",
          rect: { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height },
          width: cs.width,
          minWidth: cs.minWidth,
          maxWidth: cs.maxWidth,
          overflowX: cs.overflowX,
          overflowY: cs.overflowY,
          gridTemplateColumns: cs.gridTemplateColumns || "",
          display: cs.display,
        };
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
          });
          n = n.parentElement;
          depth += 1;
        }
        entry.chain = chain;
        try { entry.selector = builder(el); } catch (e) { entry.selector = "(selector-build-failed)"; }
        offending.push(entry);
      }
    }

    offending.sort((a, b) => (b.rect.right - docW) - (a.rect.right - docW));
    const top5 = offending.slice(0, 5).map((o) => ({
      selector: o.selector,
      tag: o.tag,
      id: o.id,
      className: o.className,
      rect_width: o.rect.width,
      rect_right: o.rect.right,
      computed_width: o.width,
      computed_minWidth: o.minWidth,
      overflow: o.overflowX + "/" + o.overflowY,
      gridTemplateColumns: o.gridTemplateColumns,
      display: o.display,
      overshoot: o.rect.right - docW,
    }));

    return { docInfo, classify, overflowCount: offending.length, top5, sampleChains: offending.slice(0, 3).map((o) => ({ selector: o.selector, chain: o.chain })) };
  }, buildSelectorPath.toString());

  console.log(`=== ${label} ===`);
  console.log(JSON.stringify(result.docInfo, null, 2));
  console.log("=== CLASSIFY ===");
  console.log(JSON.stringify(result.classify, null, 2));
  console.log("=== OVERFLOW_COUNT ===");
  console.log(result.overflowCount);
  console.log("=== TOP5 ===");
  console.log(JSON.stringify(result.top5, null, 2));
  console.log("=== SAMPLE_CHAINS ===");
  console.log(JSON.stringify(result.sampleChains, null, 2));

  await page.close();
}

async function main() {
  const browser = await chromium.launch({
    channel: "chrome",
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1 });
  await probePage(context, "ai-generate", "AI_GENERATE_PAGE");
  await probePage(context, "execution", "EXECUTION_AI_TEST_PAGE");
  await browser.close();
}

main().catch((e) => {
  console.error("FAIL:", e && e.stack ? e.stack : e);
  process.exit(1);
});

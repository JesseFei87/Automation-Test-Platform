# AI Test Execution Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 仅修改 AI 测试执行页 CSS，使四张核心卡片在桌面端稳定对齐、任务队列随视口高度伸缩，并在 `1180px` 及以下完整切换为单列。

**Architecture:** 保留 `ExecutionCenter.tsx` 的现有 DOM、状态、交互和 API，只在 `web-ui/src/styles.css` 的执行页选择器中调整布局。桌面端沿用现有三组网格，窄屏通过统一的 `1180px` 媒体查询切换为单列；页面维持正常文档流，仅现有内部列表滚动。

**Tech Stack:** React 19、TypeScript 5.8、Vite 7、CSS Grid、agent-browser-first-browser

---

## File Map

- Modify: `web-ui/src/styles.css` — 调整执行页四卡标题区、入口卡高度、任务列表视口高度、内部滚动边界及响应式网格。
- Do not modify: `web-ui/src/pages/ExecutionCenter.tsx`、其他 TSX、API、状态、文案、测试数据或后端文件。

### Task 1: Verify the Current CSS Baseline

**Files:**
- Inspect: `web-ui/src/styles.css:2355`
- Inspect: `web-ui/src/styles.css:3535`
- Inspect: `web-ui/src/styles.css:3755`
- Inspect: `web-ui/src/styles.css:3820`
- Inspect: `web-ui/src/styles.css:4111`

- [ ] **Step 1: Confirm worktree scope**

Run:

```powershell
git status --short
```

Expected: record existing unrelated changes; do not alter, stage, restore, or commit them.

- [ ] **Step 2: Verify the preserved desktop baseline**

Run:

```powershell
rg -n -A 16 "^\.execution-grid|^\.execution-left|^\.execution-right" web-ui/src/styles.css
```

Expected: `.execution-grid` uses `400px minmax(0, 1fr)`; grid and column gaps are `18px`; the left column aligns to the top. Preserve these declarations.

- [ ] **Step 3: Capture the failing declarations**

Run:

```powershell
rg -n -A 12 "^\.execution-page \.card__header|^\.execution-page \.execution-list|^\.execution-entry-card" web-ui/src/styles.css
```

Expected: title has only `margin-bottom: 14px`, list has fixed `max-height: 700px`, and entry card has three `314px` height declarations.

- [ ] **Step 4: Verify the responsive gap**

Run:

```powershell
rg -n -A 18 "^@media \(max-width: 1180px\)" web-ui/src/styles.css
```

Expected: no one rule switches `.execution-grid`, `.execution-live-layout`, and `.execution-live-preview` to `minmax(0, 1fr)` together.

### Task 2: Implement the Minimal CSS Change

**Files:**
- Modify: `web-ui/src/styles.css:3535`
- Modify: `web-ui/src/styles.css:4111`

- [ ] **Step 1: Replace the title, list, and entry-card declarations**

```css
.execution-page .card__header {
  min-height: 52px;
  margin-bottom: 14px;
}

.execution-page .execution-list {
  min-height: 164px;
  max-height: calc(100vh - 430px);
  overscroll-behavior: contain;
}

.execution-entry-card {
  align-self: start;
}
```

The `52px` minimum aligns the existing title/subtitle block while allowing wrapping. The `430px` offset covers navigation, flow strip, spacing, queue header, tabs, and summary; `164px` keeps one complete task visible on short screens. Do not add fixed height, clipping, or page/column scroll locks.

- [ ] **Step 2: Contain existing execution-page internal scroll regions**

Add without changing existing dimensions or overflow axes:

```css
.execution-stage-strip,
.execution-live-steps,
.execution-live-panel pre {
  overscroll-behavior: contain;
}
```

- [ ] **Step 3: Complete the existing `1180px` responsive rule**

Inside the media block that already contains `.execution-preview-head`, use:

```css
@media (max-width: 1180px) {
  .worker-preview-grid,
  .execution-grid,
  .execution-preview-head,
  .execution-live-layout,
  .execution-live-preview,
  .report-center-layout,
  .report-center-layout--wide,
  .report-grid,
  .report-grid--evidence,
  .report-summary--detailed,
  .raw-assets-grid,
  .step-detail-item__body {
    grid-template-columns: minmax(0, 1fr);
  }
}
```

Keep DOM order unchanged and preserve `.execution-stage-strip { overflow-x: auto; }`.

- [ ] **Step 4: Verify the static CSS contract**

Run:

```powershell
rg -n -A 10 "^\.execution-entry-card|^\.execution-page \.execution-list|^\.execution-page \.card__header" web-ui/src/styles.css
rg -n -A 18 "^@media \(max-width: 1180px\)" web-ui/src/styles.css
rg -n "execution-entry-card|314px|max-height: 700px" web-ui/src/styles.css
```

Expected: entry card has no `314px` dimensions; list uses `164px` and `calc(100vh - 430px)`; one media rule covers all three grids. Leave unrelated values untouched.

- [ ] **Step 5: Confirm the permitted source scope**

Run:

```powershell
git diff -- web-ui/src/styles.css
git status --short
```

Expected: implementation changes only `web-ui/src/styles.css`; pre-existing unrelated changes remain untouched. Do not stage or commit.

### Task 3: Build and Browser-Verify

**Files:**
- Verify: `web-ui/src/styles.css`

- [ ] **Step 1: Run the production frontend build**

Run `cmd /c npm run build` from `web-ui`.

Expected: TypeScript and Vite exit `0`; generated output is excluded from the source diff.

- [ ] **Step 2: Start the existing frontend preview**

Run `cmd /c npm run dev` from `web-ui`.

Expected: application is available at `http://127.0.0.1:5175`. Reuse the intended app if already running; do not edit config or start mock services.

- [ ] **Step 3: Verify desktop geometry with agent-browser-first-browser**

Open AI 测试 at `1440x900` and `1280x720`.

Expected:

```text
.execution-grid = 400px + remaining width
grid and column gaps = 18px
left and right columns share the same top edge
four card headers have at least 52px height and 14px lower spacing
.execution-entry-card height is content-driven
documentElement.scrollWidth equals documentElement.clientWidth
```

At `1280x720`, use enough existing tasks to overflow the queue. Confirm only `.execution-list` scrolls, its header/tabs/statistics stay visible, and keyboard focus scrolls a task into view without clipping.

- [ ] **Step 4: Verify breakpoint and narrow-screen flow**

With agent-browser-first-browser check `1180x800`, `1024x768`, and `390x844`.

Expected:

```text
.execution-grid resolves to one track
.execution-live-layout resolves to one track
.execution-live-preview resolves to one track
visual order matches DOM order
documentElement.scrollWidth equals documentElement.clientWidth
text wraps without clipping or overlap
stage strip retains its own horizontal scroll
```

- [ ] **Step 5: Regression-check interactions and accessibility**

Select one regular run and one intelligent-exploration run using existing data. Verify status, run ID, report entry, deletion, stage/step selection, screenshot/canvas, details, polling-visible updates, and scrolling; keyboard-tab through tabs, tasks, delete/report actions, and steps.

Expected: behavior is unchanged, focus remains visible and follows internal scrolling, and reduced motion still disables the existing pulse without changing layout.

- [ ] **Step 6: Final verification**

Run:

```powershell
git diff --check
git diff --name-only
```

Then run `cmd /c npm run build` from `web-ui`.

Expected: no whitespace errors; this task's source change is only `web-ui/src/styles.css`; build exits `0`. Do not commit.


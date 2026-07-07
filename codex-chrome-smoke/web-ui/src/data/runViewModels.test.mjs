import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

async function loadRunViewModelsForTest() {
  const tempDir = await mkdtemp(join(tmpdir(), "run-view-models-"));
  const stepTextSource = await readFile(resolve("src/data/stepTextZh.ts"), "utf8");
  const runViewModelsSource = await readFile(resolve("src/data/runViewModels.ts"), "utf8");
  const tempStepText = join(tempDir, "stepTextZh.ts");
  const tempRunViewModels = join(tempDir, "runViewModels.ts");

  await writeFile(tempStepText, stepTextSource, "utf8");
  await writeFile(tempRunViewModels, runViewModelsSource.replace('"./stepTextZh"', '"./stepTextZh.ts"'), "utf8");

  return import(pathToFileURL(tempRunViewModels).href);
}

test("步骤标题为泛化占位时优先回退到当前步骤的中文动作描述", async () => {
  const { buildRunDetailViewModel } = await loadRunViewModelsForTest();
  const model = buildRunDetailViewModel({
    run_id: "ui-test",
    case_id: "USRMGT_FUN_002",
    case_name: "USRMGT_FUN_002",
    mode: "agent",
    status: "completed",
    started_at: "2026-07-02T10:00:00Z",
    finished_at: "2026-07-02T10:01:00Z",
    duration_seconds: 60,
    final_url: "",
    summary: {
      conclusion: "",
      failure_reason: "",
      ai_analysis: "",
    },
    steps: [
      {
        step_index: 1,
        step_code: "step-1",
        title: "执行步骤 1",
        status: "completed",
        summary: "登录ICM系统",
        ai_analysis: "登录ICM系统",
        final_url: "",
        command_output: [],
        selectors: [],
        inputs: [],
        console_logs: [],
        network_logs: [],
        dom_snapshot_url: "",
        events: [],
      },
      {
        step_index: 3,
        step_code: "step-3",
        title: "执行步骤 3",
        status: "completed",
        summary: "鼠标悬停在用户test所在行上《更多按钮",
        ai_analysis: "鼠标悬停在用户test所在行上《更多按钮",
        final_url: "",
        command_output: [],
        selectors: [],
        inputs: [],
        console_logs: [],
        network_logs: [],
        dom_snapshot_url: "",
        events: [],
      },
    ],
    artifacts: {},
    raw_report: "",
    logs: [],
    screenshots: [],
    evidence: undefined,
    agent_explore: undefined,
    analysis: undefined,
    healing_hint: "",
    agent_plan: { planner_version: "test", case_id: "USRMGT_FUN_002", stages: [] },
    agent_stage_runs: [],
    current_stage_id: "",
    current_stage_name: "",
    current_strategy: "",
  });

  assert.equal(model.steps[0].title, "登录ICM系统");
  assert.equal(model.steps[1].title, "鼠标悬停在用户test所在行上《更多按钮");
});

# ICM Agent Explore Design

## Goal

Add a sidecar Agent exploration path for ICM use cases. The Agent can explore a real ICM flow from an existing YAML case or draft, record the successful path, and produce a candidate deterministic regression flow. Existing `run-case`, `run-batch`, and `run-draft` behavior remains unchanged.

## Chosen Approach

Use "sidecar exploration, then sedimentation":

1. `agent-explore` runs beside the current deterministic runner.
2. It reads an existing formal case YAML or draft YAML and turns the case title, steps, expected results, and automation assets into a bounded Agent goal.
3. The Agent executes one step at a time through Playwright using only observed page refs for `click`, `fill`, and `press`.
4. A successful run creates an exploration artifact: action trace, screenshots, DOM evidence, final URL, extracted selectors, and a generated candidate flow file.
5. A human approval step is required before the candidate flow is registered in `CASE_RUNNERS`.

## Non-Goals

- Do not replace deterministic regression execution with Agent execution.
- Do not let Agent runs auto-register or overwrite official regression flows.
- Do not introduce production mocks.
- Do not allow broad browser navigation. ICM exploration must be constrained to configured ICM entry/base URLs.
- Do not change existing case YAML format unless a small optional `agent_explore` metadata block is needed later.

## Architecture

The implementation adds a new runner branch:

```text
case draft/formal YAML
  -> agent goal builder
  -> bounded Playwright Agent loop
  -> exploration artifact
  -> candidate Python flow generator
  -> manual approval
  -> formal CASE_RUNNERS registration
```

The Agent loop should be implemented in Python to match the current ICM runner stack. Project_X remains a reference for the loop shape: observe page, ask MiniMax for one JSON action, normalize the action, execute it with Playwright, append history, repeat until `finish`, `fail`, or max steps.

## Components

### `runner.agent_explore`

Responsible for sidecar exploration only. It should:

- Build an Agent goal from the case YAML and runtime system settings.
- Observe visible text and interactive controls from the Playwright page.
- Ask the configured AI provider for one JSON action.
- Normalize and validate the action.
- Execute the action through Playwright.
- Record every observation, decision, execution result, screenshot, DOM snapshot, and final status.

### `runner.agent_actions`

Responsible for action safety and execution. It should support only:

- `goto`
- `fill`
- `click`
- `press`
- `wait`
- `scroll`
- `assert_text`
- `finish`
- `fail`

`fill`, `click`, and `press` must target an observed `ref`, not a model-invented selector.

### `runner.agent_codegen`

Responsible for generating candidate deterministic flow code from a successful exploration trace. The first version should produce a candidate file under an ignored or review-only location, not directly inside `runner/flows`.

The candidate code should use existing helpers from `runner.browser` such as `goto_route`, `fill_first`, `click_first`, `ensure_text_visible`, `screenshot`, and `wait_for_url_contains` where possible.

### API and Worker

Add a new queue mode `agent-explore` beside existing worker modes. It should:

- Accept a formal `case_id` or a draft id.
- Create a queued task.
- Execute `python -m runner.main agent-explore ...`.
- Persist logs and final artifact path in the existing task model or a small sidecar artifact field.

### UI

Add a separate "Agent Explore" action on draft/formal case views. It should not reuse the normal "Run" label because the semantics differ. The result view should show:

- pass/fail
- step history
- screenshots
- DOM evidence link
- generated candidate flow path
- manual approval reminder

## Safety Rules

- `AGENT_ALLOWED_HOSTS` must default to the host from `systems/icm-internal.yaml`, not `*`.
- The Agent may not perform delete, payment, external download, or messaging actions.
- The Agent may not navigate outside configured ICM hosts.
- Max steps must be finite. First version default: `25`.
- Exploration artifacts must be written under ignored runtime paths.
- Formal flow registration must remain a separate approval step.

## Data Flow

1. User clicks Agent Explore on a case or draft.
2. API queues `agent-explore`.
3. Worker starts `runner.main agent-explore`.
4. Runner launches browser using existing system settings and storage state behavior.
5. Agent opens the configured entry URL and explores toward the case goal.
6. On success, runner writes:
   - `reports/agent-explore/<run_id>/trace.json`
   - `reports/agent-explore/<run_id>/candidate_flow.py`
   - screenshots and DOM evidence through existing evidence helpers
7. UI shows the result and candidate path.
8. User reviews and separately approves promotion/registration.

## Error Handling

- Missing AI configuration returns a clear blocked status before browser launch.
- Host whitelist violation fails immediately.
- Unknown `ref` fails the current Agent step and records the model decision.
- Consecutive repeated execution errors should stop the run with `failed`, not keep looping.
- Max step exhaustion returns `failed` with trace history.
- Code generation only runs after `ok=true`.

## Testing

Add focused tests for:

- Goal building from case YAML.
- Host whitelist extraction and enforcement.
- Action normalization and rejection of unsafe actions.
- Observed ref requirement for `fill`, `click`, and `press`.
- Worker mode validation for `agent-explore`.
- Candidate code generation from a minimal successful trace.

## Open Decision

First implementation should support draft YAML and formal YAML input. It should not promote generated code automatically. Promotion can be a later explicit task after the first exploration artifacts are reliable.

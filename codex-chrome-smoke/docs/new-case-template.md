# New Case Template

Use this template when you want to add a new smoke case for Codex + Chrome execution.

## Where to Put It

- Case definition: `test-cases/<system>/TC-<SYSTEM>-NNN-<short-name>.yaml`
- Prompt template: `prompt-templates/PT-<SYSTEM>-NNN-<short-name>.md`
- System definition, if needed: `systems/<system>.yaml`
- Run results: `reports/runs/<run_id>.md`
- Screenshots: `screenshots/latest/<case_id>/` and `screenshots/runs/<run_id>/` for failed evidence

## Case File Template

```yaml
id: TC-<SYSTEM>-NNN
system: <system>
title: <short human-readable title>
priority: P0
category: <login|navigation|action|logout|upload|download|other>
preconditions:
  - "<browser / login / data / env prerequisite>"
  - "<second prerequisite if needed>"
steps:
  - "<step 1>"
  - "<step 2>"
  - "<step 3>"
expected_results:
  - "<what should be visible or true at the end>"
  - "<secondary success signal>"
failure_signals:
  - "<what counts as a failure>"
  - "<what else should stop the run>"
evidence_points:
  - "01-entry.png: <what to capture at entry>"
  - "02-action.png: <what to capture after the main action>"
  - "03-final.png: <what to capture at the final verdict>"
risk_notes:
  - "<special handling note>"
```

## Prompt Template Template

```md
# Run Prompt

Please run this smoke case in Chrome:

- Case ID: `TC-<SYSTEM>-NNN`
- Title: `<short human-readable title>`
- System: `<system>`

## Preconditions

- <browser / login / data / env prerequisite>

## Steps

1. <step 1>
2. <step 2>
3. <step 3>

## Expected Result

- <what should be visible or true at the end>

## Evidence

- Save `01-entry.png`
- Save `02-action.png`
- Save `03-final.png`
- Return the final pass/fail result and the screenshot paths
```

## Case Writing Rules

- Keep one case focused on one business goal.
- Use concrete visible signals, not vague descriptions.
- If the case depends on existing login state, say so explicitly in `preconditions`.
- If a page can present success as a page, modal, or drawer, list all acceptable forms in `expected_results`.
- If a step needs a specific test value, put it directly in the YAML.
- If a case is expected to be unstable, record the risk in `risk_notes` instead of hiding it.

## Recommended Naming

- `TC-<SYSTEM>-001` for login
- `TC-<SYSTEM>-002` for homepage / landing load
- `TC-<SYSTEM>-003` for list or query flow
- `TC-<SYSTEM>-004` for detail or drill-down flow
- `TC-<SYSTEM>-005` for logout / session end flow

## Copy-Forward Checklist

- Create or update the case YAML.
- Create the matching prompt template.
- Confirm the target system entry URL in `systems/`.
- Decide the evidence screenshots before running.
- Save the run report after execution.

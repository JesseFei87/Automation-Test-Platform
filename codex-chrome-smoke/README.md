# Codex Chrome Smoke Assets

This package contains the first usable asset set for `Codex + Chrome` web smoke testing.

## Goals

- Let testers or product owners trigger real Chrome business-flow checks with standard prompts.
- Produce fixed-format Markdown results plus key screenshots for every run.
- Keep system-level and case-level assets separate for later scale-out.

## Directory Map

- `systems/`: system definitions, entry URLs, credential source, environment rules, known risks
- `prompt-templates/`: prompts that can be sent directly to Codex
- `test-cases/`: structured smoke case definitions
- `reports/`: report templates and run archives
- `screenshots/latest/`: latest screenshot set for each case
- `screenshots/runs/`: archived screenshots for failed runs and evidence retention
- `docs/`: environment rules and execution standards

## Pilot Scope

The pilot system is `ICM Internal Portal` with 5 smoke cases:

1. Login success
2. Homepage load success
3. Device list open and query
4. Device detail open
5. Logout and return to login page

## Ordered Expansion Batch

The next ordered batch is documented in `docs/icm-case-6-11-sequence.md` and covers:

1. Create device record
2. Bind device to server
3. Create user
4. Bind server and device to user
5. Open remote desktop from screen wall
6. Cleanup user and device bindings

## Standard Run Flow

1. Read `docs/environment-whitelist.md`.
2. Choose the target definition in `systems/`.
3. Choose the target case in `test-cases/`.
4. Send the matching prompt from `prompt-templates/` to Codex.
5. Save the final report in `reports/runs/`.
6. Save screenshots in `screenshots/latest/<case_id>/`.
7. Keep failed-run evidence in `screenshots/runs/<run_id>/`.

## Scripted Runner

You can run cases locally with Python and Playwright instead of replaying them through chat.

- Single case: `python -m runner.main run-case TC-ICM-008`
- Ordered batch: `python -m runner.main run-batch 20260528-icm-batch-01`

The runner starts a fresh browser context each time, checks whether the site is already logged in, and only performs login when needed. It does not depend on reusing an existing Chrome login state.

## Local Team Platform

The MVP platform adds a Web UI plus a local FastAPI backend around the existing runner.

- Backend API: `python -m uvicorn icm_platform.api:app --host 127.0.0.1 --port 8000`
- Frontend UI: `cd web-ui && npm run dev`
- API data store: `platform-data/icm-platform.sqlite3`

Install backend dependencies once before first use:

```bash
python -m pip install -e .
```

The platform keeps YAML as the case source of truth and calls the existing runner in a background worker:

- `test-cases/icm/*.yaml`: case source
- `runner/main.py`: execution entry
- `reports/runs/*.md`: report archive
- `screenshots/latest/<case_id>`: latest evidence
- `screenshots/runs/<run_id>`: archived run evidence

MVP API capabilities:

- Analyze pasted requirements into test points.
- Generate a YAML draft from test points.
- Queue `run-case` or `run-batch` tasks.
- Read task status, logs, reports, and latest screenshots.
- Produce a replaceable AI report analysis through `AIService`.

## New Case Template

If you want to add a new case, start from `docs/new-case-template.md`.

## Case Sedimentation

After every successful `Computer Use` case run, add one matching case note in the corresponding `test-cases/icm/*.yaml` file.

Use this fixed structure:

```md
## Case: TC-ICM-003

### 操作步骤
1. ...
2. ...

### 页面 selector
- ...

### 输入值
- ...

### 断言点
- ...
```

Rules:

- Keep the case note aligned with the real run path.
- Record the actual page selectors used by the runner, not just the ideal ones.
- Record every input value that was filled or selected.
- Record the exact pass/fail assertion points.
- If a case has multiple stable routes or entry points, list the one used in the working run first.

## Status Enum

- `passed`: business goal completed, assertions met, evidence complete
- `failed`: page opened but the business step or assertion failed
- `blocked`: environment, login, connection, permission, or manual-confirmation blocker

## Naming Rules

- `run_id`: `YYYYMMDD-HHMM-<system>-<batch>`
- screenshots: `01-entry.png`, `02-action.png`, `03-final.png`
- report file: `<run_id>.md`

## Maintenance Notes

- Add a new system by copying an existing file in `systems/`.
- Keep one case focused on one full business goal.
- Keep output fields stable across prompt edits so reports remain comparable.

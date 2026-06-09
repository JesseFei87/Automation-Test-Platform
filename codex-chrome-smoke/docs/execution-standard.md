# Execution Standard

## Required Output Fields

Every run result must contain:

- case name
- environment
- preconditions
- key steps
- final result
- failure point
- screenshot paths

## Required Screenshots

Each case keeps three screenshots by default:

1. `01-entry.png`
2. `02-action.png`
3. `03-final.png`

If the flow blocks early, keep at least the entry screenshot and the blocker screenshot.
Latest screenshots should live under `screenshots/latest/<case_id>/`, and failed-run archives should stay under `screenshots/runs/<run_id>/`.
`02-action.png` may be captured inside the flow at the moment the key action happens; `03-final.png` is captured after the flow finishes.

## Stop Rules

- If a core precondition fails, mark `blocked`.
- If a core assertion fails, mark `failed`.
- Do not auto-recover, auto-refresh, skip, or continue with later steps.
- Leave the blocked page available for human handoff when possible.

## Login Handling

- Each run must first probe the current browser state.
- If the site is already logged in, continue with the case steps.
- If the site is not logged in, open the login page, submit credentials, and then continue.
- Do not require a pre-cloned Chrome profile as the run precondition.

## Page Judgment Rules

- Use visible title, stable text, key controls, URL fragments, and menu labels together.
- Do not judge success from iconography or styling alone.
- Login page, homepage, list page, and detail page must each have explicit visible signals.

## Report Archiving

- Save a single run report to `reports/runs/<run_id>.md`.
- Save the current screenshots to `screenshots/latest/<case_id>/`.
- Keep failed-run evidence in `screenshots/runs/<run_id>/`.
- Use one summary report per smoke batch.

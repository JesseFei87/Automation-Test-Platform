# Smoke Run Report

- run_id: `<YYYYMMDD-HHMM-system-batch>`
- date: `<YYYY-MM-DD HH:mm>`
- operator: `<name>`
- environment: `<internal|external>`
- system: `<system_id>`
- batch_scope: `<single_case|pilot_batch|daily_smoke>`

## Summary

- total_cases: `<number>`
- passed: `<number>`
- failed: `<number>`
- blocked: `<number>`
- overall_status: `<passed|failed|blocked>`

## Case Results

### `<case_id> <title>`

- status: `<passed|failed|blocked>`
- preconditions:
  - `<item>`
- key_steps:
  - `<item>`
- failure_point: `<none or detail>`
- evidence:
  - `screenshots/<run_id>/01-entry.png`
  - `screenshots/<run_id>/02-action.png`
  - `screenshots/<run_id>/03-final.png`
- notes:
  - `<optional>`

## Follow-ups

- `<next action>`

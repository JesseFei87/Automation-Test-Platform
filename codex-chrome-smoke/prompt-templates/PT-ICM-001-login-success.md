# Prompt Template: ICM Login Success

Use `@chrome` to execute `TC-ICM-001`.

## System

- system_id: `icm-internal`
- entry_url: `https://192.168.16.203:49187/#/login?redirect=%2Fredirect`

## Inputs

- username: `<fill username>`
- password: `<fill password>`

## Required Steps

1. Open the ICM login page.
2. If the same URL has both an error tab and a usable login tab, switch to the usable login tab.
3. Enter valid credentials and click `login`.
4. Decide whether the homepage is reached.
5. Keep 3 screenshots: login page, after submit, homepage final page.

## Output Format

- case name
- environment
- preconditions
- key steps
- result
- failure point
- screenshot paths

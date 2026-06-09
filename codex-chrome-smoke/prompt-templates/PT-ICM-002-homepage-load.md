# Prompt Template: ICM Homepage Load

Use `@chrome` to execute `TC-ICM-002`.

## Required Steps

1. Open the homepage in a logged-in session.
2. Wait for loading to finish.
3. Decide whether stable homepage sections are rendered.
4. If the page returns to login, mark the run as failed and stop.
5. Keep 3 screenshots: page entry, post-loading, final verdict.

## Output Format

- case name
- environment
- preconditions
- key steps
- result
- failure point
- screenshot paths

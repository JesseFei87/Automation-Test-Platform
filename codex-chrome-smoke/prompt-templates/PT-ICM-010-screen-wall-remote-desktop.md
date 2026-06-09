# Prompt Template: ICM Screen Wall Remote Desktop

Use `@chrome` to execute `TC-ICM-010`.

## Required Inputs

- login_user: `Tester`
- login_password: `123456`
- device_name: `Test_Ins01`

## Required Steps

1. Log in as `Tester / 123456`.
2. Open the screen wall page.
3. Wait until all devices finish refreshing.
4. Click into the first device `Test_Ins01`.
5. Confirm a new tab opens for the remote desktop.
6. Wait for the remote desktop to finish loading.
7. Click `Unlock` and verify mouse/keyboard control is possible.
8. Close the remote desktop tab.
9. Use the screen wall `登出` action to log out Tester.
10. Keep 3 screenshots: screen wall entry, remote desktop open/unlocked, final logout state.

## Output Format

- case name
- environment
- preconditions
- key steps
- result
- failure point
- screenshot paths

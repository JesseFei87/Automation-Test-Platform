# Prompt Template: ICM Cleanup User and Device Bindings

Use `@chrome` to execute `TC-ICM-011`.

## Required Inputs

- admin_user: `admin`
- admin_password: `Hubble_Service!1088`
- user_name: `Tester`
- device_name: `Test_Ins01`
- server_name: `Test Server#203`

## Required Steps

1. Log in as `admin / Hubble_Service!1088`.
2. Open `系统管理 > 用户管理` and delete `Tester`.
3. Open `ICM > 设备信息` and delete `Test_Ins01`.
4. Open `ICM > 服务器信息` and edit `Test Server#203`.
5. Search for `Test_Ins01` in the bound device area.
6. Confirm that `Test_Ins01` cannot be found.
7. Exit the server edit dialog.
8. Keep 3 screenshots: before cleanup, search result showing removal, final state after closing dialog.

## Output Format

- case name
- environment
- preconditions
- key steps
- result
- failure point
- screenshot paths

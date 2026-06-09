# Prompt Template: ICM Bind Server and Device to User

Use `@chrome` to execute `TC-ICM-009`.

## Required Inputs

- user_name: `Tester`
- server_name: `Test Server#203`
- device_name: `Test_Ins01`

## Required Steps

1. Open `系统管理 > 用户管理`.
2. In the `Tester` row, open `更多 > 配置服务器和设备`.
3. Add the target server.
4. In the server selection page, check `Test Server#203` and confirm.
5. Refresh server info and enable the current server.
6. Refresh bound device info and check `Test_Ins01`.
7. Exit the current user session after the binding is complete.
8. Keep 3 screenshots: user row before config, selected bindings, final saved state.

## Output Format

- case name
- environment
- preconditions
- key steps
- result
- failure point
- screenshot paths

# Patch Plan: prompt-templates ↔ yaml (TC-ICM-001..011)

> Read-only diff. After you approve each case's patch entries below,
> run `python scripts/apply_patch_plan.py` to write them into the yaml files.

## 数字总览

| case | pt 操作 | yaml 操作 | 互有 | 缺 PT 步 | 缺信号 |
|---|---|---|---|---|---|
| TC-ICM-001 | 5 | 5 | 1 | 4 | 0 |
| TC-ICM-002 | 5 | 4 | 0 | 5 | 0 |
| TC-ICM-003 | 5 | 6 | 1 | 4 | 0 |
| TC-ICM-004 | 5 | 6 | 0 | 5 | 0 |
| TC-ICM-005 | 6 | 7 | 0 | 6 | 0 |
| TC-ICM-006 | 5 | 9 | 0 | 5 | 0 |
| TC-ICM-007 | 5 | 6 | 0 | 5 | 0 |
| TC-ICM-008 | 5 | 5 | 0 | 5 | 0 |
| TC-ICM-009 | 8 | 9 | 1 | 7 | 0 |
| TC-ICM-010 | 9 | 6 | 1 | 8 | 0 |
| TC-ICM-011 | 8 | 9 | 0 | 8 | 0 |

## TC-ICM-001

- yaml: `test-cases\icm\TC-ICM-001-login-success.yaml`
- pt  : `prompt-templates\PT-ICM-001-login-success.md`
- 操作匹配度: 1/5
- 截图要求: PT 说 Keep **3** 张；yaml 现有图注 **0** 条

**PT 里有但 yaml 没写的操作步骤（建议 append 到 operation_steps）：**
- If the same URL has both an error tab and a usable login tab, switch to the usable login tab
- Enter valid credentials and click `login`
- Decide whether the homepage is reached
- Keep 3 screenshots: login page, after submit, homepage final page

**yaml 里有但 PT 没写的操作步骤（保留即可，yaml 更细）：**
- Confirm that the login controls are visible
- Enter the credentials
- Click login
- Wait for the homepage to appear


## TC-ICM-002

- yaml: `test-cases\icm\TC-ICM-002-homepage-load.yaml`
- pt  : `prompt-templates\PT-ICM-002-homepage-load.md`
- 操作匹配度: 0/5
- 截图要求: PT 说 Keep **3** 张；yaml 现有图注 **0** 条

**PT 里有但 yaml 没写的操作步骤（建议 append 到 operation_steps）：**
- Open the homepage in a logged-in session
- Wait for loading to finish
- Decide whether stable homepage sections are rendered
- If the page returns to login, mark the run as failed and stop
- Keep 3 screenshots: page entry, post-loading, final verdict

**yaml 里有但 PT 没写的操作步骤（保留即可，yaml 更细）：**
- Ensure the session is already logged in
- Open the homepage at #/index
- Wait for the loading state to clear
- Confirm stable homepage sections are visible


## TC-ICM-003

- yaml: `test-cases\icm\TC-ICM-003-device-list-query.yaml`
- pt  : `prompt-templates\PT-ICM-003-device-list-query.md`
- 操作匹配度: 1/5
- 截图要求: PT 说 Keep **3** 张；yaml 现有图注 **0** 条

**PT 里有但 yaml 没写的操作步骤（建议 append 到 operation_steps）：**
- Open `Device Ops > Device List` in a logged-in session
- Wait for the list page to render
- Decide whether the query action completed successfully
- Keep 3 screenshots: list entry, post-query action, final result page

**yaml 里有但 PT 没写的操作步骤（保留即可，yaml 更细）：**
- Ensure the session is already logged in
- Open the device list at #/hubble/device or its equivalent stable route
- Wait for the device list view to render
- Enter the device keyword into the query field
- Confirm the page remains on the device list view and the results refresh


## TC-ICM-004

- yaml: `test-cases\icm\TC-ICM-004-device-detail-open.yaml`
- pt  : `prompt-templates\PT-ICM-004-device-detail-open.md`
- 操作匹配度: 0/5
- 截图要求: PT 说 Keep **3** 张；yaml 现有图注 **0** 条

**PT 里有但 yaml 没写的操作步骤（建议 append 到 operation_steps）：**
- Start from the device list page
- Select the first usable row
- Open `Detail` or the equivalent visible entry
- Decide whether the detail appears as a page, modal, or drawer
- Keep 3 screenshots: list page, after detail click, final detail state

**yaml 里有但 PT 没写的操作步骤（保留即可，yaml 更细）：**
- Ensure the session is already logged in
- Open the device list at #/hubble/device or its equivalent stable route
- Wait for the device list table to render
- Pick a visible device row
- Click the row's Modify action
- Wait for the edit dialog or detail form to appear


## TC-ICM-005

- yaml: `test-cases\icm\TC-ICM-005-logout-return-login.yaml`
- pt  : `prompt-templates\PT-ICM-005-logout-return-login.md`
- 操作匹配度: 0/6
- 截图要求: PT 说 Keep **3** 张；yaml 现有图注 **0** 条

**PT 里有但 yaml 没写的操作步骤（建议 append 到 operation_steps）：**
- Start from the logged-in homepage after loading finishes
- Click the top-right avatar and open the user menu
- Click `Logout`
- Click `Confirm` in the logout dialog
- Decide whether the page returned to login and whether account, password, and login controls are visible again
- Keep 3 screenshots: homepage, logout confirm dialog, returned login page

**yaml 里有但 PT 没写的操作步骤（保留即可，yaml 更细）：**
- Fill the account input with `admin`
- Fill the password input with the case password
- Click login and wait until the homepage is visible
- Click the user avatar in the top-right corner
- Choose Logout from the dropdown menu
- Confirm the logout dialog
- Wait for the login page to reappear


## TC-ICM-006

- yaml: `test-cases\icm\TC-ICM-006-device-create.yaml`
- pt  : `prompt-templates\PT-ICM-006-device-create.md`
- 操作匹配度: 0/5
- 截图要求: PT 说 Keep **3** 张；yaml 现有图注 **0** 条

**PT 里有但 yaml 没写的操作步骤（建议 append 到 operation_steps）：**
- Open `ICM > 设备信息`
- Open the add/create device form
- Fill the device form with the provided values
- Save the record and confirm it appears in the list
- Keep 3 screenshots: list entry, filled create form or submit state, final created row

**yaml 里有但 PT 没写的操作步骤（保留即可，yaml 更细）：**
- Ensure the session is already logged in as admin
- Open ICM > Device Information at #/hubble/device
- Search Test_Ins01 first; if it already exists, reuse it
- Click Add/New and wait for the visible device dialog
- Fill the device form with the test device data
- Toggle Device Status to enabled
- Capture the filled form as the action screenshot
- Submit the form, then search the device by name again
- Confirm the device appears in the list with enabled status


## TC-ICM-007

- yaml: `test-cases\icm\TC-ICM-007-server-bind-device.yaml`
- pt  : `prompt-templates\PT-ICM-007-server-bind-device.md`
- 操作匹配度: 0/5
- 截图要求: PT 说 Keep **3** 张；yaml 现有图注 **0** 条

**PT 里有但 yaml 没写的操作步骤（建议 append 到 operation_steps）：**
- Open `ICM > 服务器信息`
- Click `修改` for the target server
- Search for `Test_Ins01` in the bound device selector
- Check the device and confirm the save
- Keep 3 screenshots: server list entry, selected device in dialog, final saved state

**yaml 里有但 PT 没写的操作步骤（保留即可，yaml 更细）：**
- Ensure the session is already logged in as admin
- Open ICM > Server Information at #/hubble/server
- Click Modify for the target server row
- Search for Test_Ins01 in the bound device selector
- Check the device and confirm the change
- Verify the success message or binding state refreshes


## TC-ICM-008

- yaml: `test-cases\icm\TC-ICM-008-create-user.yaml`
- pt  : `prompt-templates\PT-ICM-008-create-user.md`
- 操作匹配度: 0/5
- 截图要求: PT 说 Keep **3** 张；yaml 现有图注 **0** 条

**PT 里有但 yaml 没写的操作步骤（建议 append 到 operation_steps）：**
- Open `系统管理 > 用户管理`
- Click `新增`
- Fill the user form with the provided values
- Save the user and confirm it appears in the list
- Keep 3 screenshots: list entry, filled create form or submit state, final created row

**yaml 里有但 PT 没写的操作步骤（保留即可，yaml 更细）：**
- Ensure the session is already logged in as admin
- Open System Management > User Management at #/system/user
- Click Add/New
- Fill the user form with the test user data
- Confirm the new user appears in the list


## TC-ICM-009

- yaml: `test-cases\icm\TC-ICM-009-user-bind-server-device.yaml`
- pt  : `prompt-templates\PT-ICM-009-user-bind-server-device.md`
- 操作匹配度: 1/8
- 截图要求: PT 说 Keep **3** 张；yaml 现有图注 **0** 条

**PT 里有但 yaml 没写的操作步骤（建议 append 到 operation_steps）：**
- Open `系统管理 > 用户管理`
- In the `Tester` row, open `更多 > 配置服务器和设备`
- In the server selection page, check `Test Server#203` and confirm
- Refresh server info and enable the current server
- Refresh bound device info and check `Test_Ins01`
- Exit the current user session after the binding is complete
- Keep 3 screenshots: user row before config, selected bindings, final saved state

**yaml 里有但 PT 没写的操作步骤（保留即可，yaml 更细）：**
- Ensure the session is already logged in as admin
- Open System Management > User Management at #/system/user
- Find the Tester row and open More > Configure Server and Device
- Check Test Server#203 in the server selection page and confirm
- Turn on the current-server switch for Test Server#203
- Go to page 3 in the bound device table and select Test_Ins01
- Return to page 1 in the bound device table
- Verify Test_Ins01 is visible in the bound device area on page 1


## TC-ICM-010

- yaml: `test-cases\icm\TC-ICM-010-screen-wall-remote-desktop.yaml`
- pt  : `prompt-templates\PT-ICM-010-screen-wall-remote-desktop.md`
- 操作匹配度: 1/9
- 截图要求: PT 说 Keep **3** 张；yaml 现有图注 **0** 条

**PT 里有但 yaml 没写的操作步骤（建议 append 到 operation_steps）：**
- Log in as `Tester / <configured locally>`
- Wait until all devices finish refreshing
- Click into the first device `Test_Ins01`
- Confirm a new tab opens for the remote desktop
- Wait for the remote desktop to finish loading
- Click `Unlock` and verify mouse/keyboard control is possible
- Close the remote desktop tab
- Use the screen wall `登出` action to log out Tester

**yaml 里有但 PT 没写的操作步骤（保留即可，yaml 更细）：**
- Log in as Tester with the provided password
- Wait for the screen wall to render
- Hover the Test_Ins01 tile to reveal the focus mask
- Click the center screen mask on Test_Ins01
- Confirm that a new remote desktop tab opens


## TC-ICM-011

- yaml: `test-cases\icm\TC-ICM-011-cleanup-server-device-binding.yaml`
- pt  : `prompt-templates\PT-ICM-011-cleanup-server-device-binding.md`
- 操作匹配度: 0/8
- 截图要求: PT 说 Keep **3** 张；yaml 现有图注 **0** 条

**PT 里有但 yaml 没写的操作步骤（建议 append 到 operation_steps）：**
- Log in as `admin / <configured locally>`
- Open `系统管理 > 用户管理` and delete `Tester`
- Open `ICM > 设备信息` and delete `Test_Ins01`
- Open `ICM > 服务器信息` and edit `Test Server#203`
- Search for `Test_Ins01` in the bound device area
- Confirm that `Test_Ins01` cannot be found
- Exit the server edit dialog
- Keep 3 screenshots: before cleanup, search result showing removal, final state after closing dialog

**yaml 里有但 PT 没写的操作步骤（保留即可，yaml 更细）：**
- Ensure the session is already logged in as admin
- Open System Management > User Management at #/system/user
- Delete the Tester user if it still exists
- Open ICM > Device Information and search for Test_Ins01 by device name
- Click Search
- Delete Test_Ins01 if the search returns a matching row
- Open ICM > Server Information at #/hubble/server and edit Test Server#203
- Search for Test_Ins01 in the bound device area
- Confirm that Test_Ins01 cannot be found


## 汇总：建议每条 case 的 patches 数

| 类型 | 数量 |
|---|---|
| yaml_ops_extra_kept | 68 |
| pt_ops_only | 62 |
| missing_signals | 0 |
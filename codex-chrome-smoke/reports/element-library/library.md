# ICM 元素库 Demo · Stage B (passive accumulation)

## 总览

- 扫描 case: **25**
- 含 automation_asset 的 case: **25**
- 归一化后元素数: **72**
- 提取到的 route 数: **6**

## 复用度 TOP 元素（被 ≥ 2 个 case 共享）

| 语义名 | EN | ZH 提示 | 复用次数 | 选择器数 | 出现于 |
|---|---|---|---|---|---|
| `agent_candidate` | agent candidate | - | 7 | 1 | TC-ICM-015, TC-ICM-021, TC-ICM-022, TC-ICM-023, TC-ICM-024 …(+2) |
| `fill_1` | fill 1 | - | 5 | 2 | TC-ICM-013, TC-ICM-016, TC-ICM-017, TC-ICM-019, TC-ICM-020 |
| `confirm_button` | confirm button | confirm / 确认 / 按钮 | 4 | 4 | TC-ICM-005, TC-ICM-006, TC-ICM-007, TC-ICM-009 |
| `device_list_url` | device list url | device / 设备 / 列表 / 页面 | 4 | 1 | TC-ICM-003, TC-ICM-004, TC-ICM-006, TC-ICM-011 |
| `click_3` | click 3 | - | 3 | 1 | TC-ICM-016, TC-ICM-017, TC-ICM-020 |
| `device_search_input` | device search input | device / 设备 / 搜索 / 输入框 | 3 | 2 | TC-ICM-006, TC-ICM-007, TC-ICM-011 |
| `fill_2` | fill 2 | - | 3 | 1 | TC-ICM-016, TC-ICM-017, TC-ICM-020 |
| `password_input` | password input | password / 密码 / 输入框 | 3 | 4 | TC-ICM-001, TC-ICM-008, TC-ICM-010 |
| `user_list_url` | user list url | user / 用户 / 列表 / 页面 | 3 | 1 | TC-ICM-008, TC-ICM-009, TC-ICM-011 |
| `username_input` | username input | username / 账号 / 输入框 | 3 | 4 | TC-ICM-001, TC-ICM-008, TC-ICM-010 |
| `add_button` | add button | add / 新增 / 按钮 | 2 | 3 | TC-ICM-006, TC-ICM-008 |
| `device_row` | device row | device / 设备 | 2 | 3 | TC-ICM-004, TC-ICM-011 |
| `login_button` | login button | login / 登录 / 按钮 | 2 | 3 | TC-ICM-001, TC-ICM-010 |
| `modify_button` | modify button | modify / 按钮 | 2 | 3 | TC-ICM-007, TC-ICM-011 |
| `screen_wall_url` | screen wall url | screen / 墙 / 页面 | 2 | 1 | TC-ICM-010, TC-ICM-012 |
| `search_button` | search button | search / 搜索 / 按钮 | 2 | 2 | TC-ICM-006, TC-ICM-011 |
| `server_list_url` | server list url | server / 服务器 / 列表 / 页面 | 2 | 1 | TC-ICM-007, TC-ICM-011 |
| `server_row` | server row | server / 服务器 | 2 | 1 | TC-ICM-007, TC-ICM-011 |
| `tester_row` | tester row | - | 2 | 1 | TC-ICM-009, TC-ICM-011 |

## 全量元素

### `agent_candidate`  *(reuse: 7)*
- **EN**: agent candidate
- **Context**: -
- **Selectors (1):**
  - `candidate_flow.py`
- **Used in**: TC-ICM-015, TC-ICM-021, TC-ICM-022, TC-ICM-023, TC-ICM-024, TC-ICM-025, TC-ICM-026
- **Input values paired**: agent_candidate.assert_text_1, agent_candidate.device_name, agent_candidate.device_ip, agent_candidate.assert_text_4, agent_candidate.fill_4

### `fill_1`  *(reuse: 5)*
- **EN**: fill 1
- **Context**: -
- **Selectors (2):**
  - `input[placeholder="账号"]`
  - `input[placeholder="密码"]`
- **Used in**: TC-ICM-013, TC-ICM-016, TC-ICM-017, TC-ICM-019, TC-ICM-020
- **Input values paired**: fill_1.fill_1, fill_1.assert_text_3, fill_1.fill_2

### `confirm_button`  *(reuse: 4)*
- **EN**: confirm button
- **ZH 提示**: confirm / 确认 / 按钮
- **Context**: -
- **Selectors (4):**
  - `button[text=确定]`
  - `button:has-text(确定)`
  - `.el-dialog__footer .el-button--primary`
  - `button:has-text(确 定)`
- **Used in**: TC-ICM-005, TC-ICM-006, TC-ICM-007, TC-ICM-009
- **Input values paired**: confirm_button.device_name, confirm_button.device_ip, confirm_button.device_port, confirm_button.vnc_password, confirm_button.connection_type

### `device_list_url`  *(reuse: 4)*
- **EN**: device list url
- **ZH 提示**: device / 设备 / 列表 / 页面
- **Context**: route · list_page
- **Selectors (1):**
  - `#/hubble/device`
- **Used in**: TC-ICM-003, TC-ICM-004, TC-ICM-006, TC-ICM-011
- **Input values paired**: device_list_url.device_keyword, device_list_url.device_name, device_list_url.device_ip, device_list_url.device_port, device_list_url.vnc_password

### `click_3`  *(reuse: 3)*
- **EN**: click 3
- **Context**: -
- **Selectors (1):**
  - `div:nth-of-type(1) > form > div:nth-of-type(4) > div > button`
- **Used in**: TC-ICM-016, TC-ICM-017, TC-ICM-020
- **Input values paired**: click_3.fill_1, click_3.fill_2

### `device_search_input`  *(reuse: 3)*
- **EN**: device search input
- **ZH 提示**: device / 设备 / 搜索 / 输入框
- **Context**: -
- **Selectors (2):**
  - `placeholder=请输入设备名称`
  - `placeholder=输入设备名称`
- **Used in**: TC-ICM-006, TC-ICM-007, TC-ICM-011
- **Input values paired**: device_search_input.device_name, device_search_input.device_ip, device_search_input.device_port, device_search_input.vnc_password, device_search_input.connection_type

### `fill_2`  *(reuse: 3)*
- **EN**: fill 2
- **Context**: -
- **Selectors (1):**
  - `input[placeholder="密码"]`
- **Used in**: TC-ICM-016, TC-ICM-017, TC-ICM-020
- **Input values paired**: fill_2.fill_1, fill_2.fill_2

### `password_input`  *(reuse: 3)*
- **EN**: password input
- **ZH 提示**: password / 密码 / 输入框
- **Context**: -
- **Selectors (4):**
  - `input[type="password"]`
  - `placeholder=密码`
  - `placeholder=请输入用户密码`
  - `placeholder=password`
- **Used in**: TC-ICM-001, TC-ICM-008, TC-ICM-010
- **Input values paired**: password_input.username, password_input.password, password_input.nickname, password_input.device_name

### `user_list_url`  *(reuse: 3)*
- **EN**: user list url
- **ZH 提示**: user / 用户 / 列表 / 页面
- **Context**: route · list_page
- **Selectors (1):**
  - `#/system/user`
- **Used in**: TC-ICM-008, TC-ICM-009, TC-ICM-011
- **Input values paired**: user_list_url.nickname, user_list_url.username, user_list_url.password, user_list_url.tester_user, user_list_url.server_name

### `username_input`  *(reuse: 3)*
- **EN**: username input
- **ZH 提示**: username / 账号 / 输入框
- **Context**: -
- **Selectors (4):**
  - `input[type="text"]`
  - `placeholder=账号`
  - `placeholder=请输入用户名称`
  - `placeholder=account`
- **Used in**: TC-ICM-001, TC-ICM-008, TC-ICM-010
- **Input values paired**: username_input.username, username_input.password, username_input.nickname, username_input.device_name

### `add_button`  *(reuse: 2)*
- **EN**: add button
- **ZH 提示**: add / 新增 / 按钮
- **Context**: -
- **Selectors (3):**
  - `button:has-text(新增)`
  - `text=新增`
  - `button[text=新增]`
- **Used in**: TC-ICM-006, TC-ICM-008
- **Input values paired**: add_button.device_name, add_button.device_ip, add_button.device_port, add_button.vnc_password, add_button.connection_type

### `device_row`  *(reuse: 2)*
- **EN**: device row
- **ZH 提示**: device / 设备
- **Context**: -
- **Selectors (3):**
  - `tr:has-text(AU5800)`
  - `tr:has-text(Device)`
  - `tr:has-text(Test_Ins01)`
- **Used in**: TC-ICM-004, TC-ICM-011
- **Input values paired**: device_row.tester_user, device_row.device_name, device_row.server_name

### `login_button`  *(reuse: 2)*
- **EN**: login button
- **ZH 提示**: login / 登录 / 按钮
- **Context**: -
- **Selectors (3):**
  - `button[text=登录]`
  - `button.el-button--primary.el-button--medium`
  - `button:has-text(login)`
- **Used in**: TC-ICM-001, TC-ICM-010
- **Input values paired**: login_button.username, login_button.password, login_button.device_name

### `modify_button`  *(reuse: 2)*
- **EN**: modify button
- **ZH 提示**: modify / 按钮
- **Context**: -
- **Selectors (3):**
  - `text=修改`
  - `button:has-text(修改)`
  - `button:has-text(Edit)`
- **Used in**: TC-ICM-007, TC-ICM-011
- **Input values paired**: modify_button.tester_user, modify_button.device_name, modify_button.server_name

### `screen_wall_url`  *(reuse: 2)*
- **EN**: screen wall url
- **ZH 提示**: screen / 墙 / 页面
- **Context**: route
- **Selectors (1):**
  - `#/icm`
- **Used in**: TC-ICM-010, TC-ICM-012
- **Input values paired**: screen_wall_url.username, screen_wall_url.password, screen_wall_url.device_name, screen_wall_url.labo_username, screen_wall_url.labo_password

### `search_button`  *(reuse: 2)*
- **EN**: search button
- **ZH 提示**: search / 搜索 / 按钮
- **Context**: -
- **Selectors (2):**
  - `button:has-text(搜索)`
  - `button:has-text(查询)`
- **Used in**: TC-ICM-006, TC-ICM-011
- **Input values paired**: search_button.device_name, search_button.device_ip, search_button.device_port, search_button.vnc_password, search_button.connection_type

### `server_list_url`  *(reuse: 2)*
- **EN**: server list url
- **ZH 提示**: server / 服务器 / 列表 / 页面
- **Context**: route · list_page
- **Selectors (1):**
  - `#/hubble/server`
- **Used in**: TC-ICM-007, TC-ICM-011
- **Input values paired**: server_list_url.tester_user, server_list_url.device_name, server_list_url.server_name

### `server_row`  *(reuse: 2)*
- **EN**: server row
- **ZH 提示**: server / 服务器
- **Context**: -
- **Selectors (1):**
  - `tr:has-text(Test Server#203)`
- **Used in**: TC-ICM-007, TC-ICM-011
- **Input values paired**: server_row.tester_user, server_row.device_name, server_row.server_name

### `tester_row`  *(reuse: 2)*
- **EN**: tester row
- **Context**: -
- **Selectors (1):**
  - `tr:has-text(Tester)`
- **Used in**: TC-ICM-009, TC-ICM-011
- **Input values paired**: tester_row.tester_user, tester_row.server_name, tester_row.device_name

### `add_dialog`  *(reuse: 1)*
- **EN**: add dialog
- **ZH 提示**: add / 新增 / 弹窗
- **Context**: dialog
- **Selectors (1):**
  - `.el-dialog:visible`
- **Used in**: TC-ICM-006
- **Input values paired**: add_dialog.device_name, add_dialog.device_ip, add_dialog.device_port, add_dialog.vnc_password, add_dialog.connection_type

### `add_server_button`  *(reuse: 1)*
- **EN**: add server button
- **ZH 提示**: add / 新增 / 服务器 / 按钮
- **Context**: -
- **Selectors (1):**
  - `button:has-text(Add Server)`
- **Used in**: TC-ICM-009
- **Input values paired**: add_server_button.tester_user, add_server_button.server_name, add_server_button.device_name

### `allow_control_select`  *(reuse: 1)*
- **EN**: allow control select
- **ZH 提示**: allow / 控制 / 下拉选择
- **Context**: -
- **Selectors (1):**
  - `dialog input index 9`
- **Used in**: TC-ICM-006
- **Input values paired**: allow_control_select.device_name, allow_control_select.device_ip, allow_control_select.device_port, allow_control_select.vnc_password, allow_control_select.connection_type

### `click_1`  *(reuse: 1)*
- **EN**: click 1
- **Context**: -
- **Selectors (1):**
  - `div:nth-of-type(1) > form > div:nth-of-type(4) > div > button`
- **Used in**: TC-ICM-018
- **Input values paired**: click_1.assert_text_2

### `click_2`  *(reuse: 1)*
- **EN**: click 2
- **Context**: -
- **Selectors (1):**
  - `div:nth-of-type(1) > form > div:nth-of-type(4) > div > button`
- **Used in**: TC-ICM-013
- **Input values paired**: click_2.fill_1, click_2.assert_text_3

### `configure_server_device_item`  *(reuse: 1)*
- **EN**: configure server device item
- **ZH 提示**: configure / 服务器 / 设备
- **Context**: -
- **Selectors (1):**
  - `text=Configure Server and Device`
- **Used in**: TC-ICM-009
- **Input values paired**: configure_server_device_item.tester_user, configure_server_device_item.server_name, configure_server_device_item.device_name

### `connection_type_select`  *(reuse: 1)*
- **EN**: connection type select
- **ZH 提示**: connection / 类型 / 下拉选择
- **Context**: -
- **Selectors (1):**
  - `dialog input index 0`
- **Used in**: TC-ICM-006
- **Input values paired**: connection_type_select.device_name, connection_type_select.device_ip, connection_type_select.device_port, connection_type_select.vnc_password, connection_type_select.connection_type

### `current_server_switch`  *(reuse: 1)*
- **EN**: current server switch
- **ZH 提示**: current / 服务器 / 开关
- **Context**: -
- **Selectors (1):**
  - `.el-switch:nth-of-type(2)`
- **Used in**: TC-ICM-009
- **Input values paired**: current_server_switch.tester_user, current_server_switch.server_name, current_server_switch.device_name

### `delete_button`  *(reuse: 1)*
- **EN**: delete button
- **ZH 提示**: delete / 删除 / 按钮
- **Context**: -
- **Selectors (2):**
  - `button:has-text(Delete)`
  - `text=Delete`
- **Used in**: TC-ICM-011
- **Input values paired**: delete_button.tester_user, delete_button.device_name, delete_button.server_name

### `dept_picker`  *(reuse: 1)*
- **EN**: dept picker
- **Context**: -
- **Selectors (1):**
  - `placeholder=请选择归属部门`
- **Used in**: TC-ICM-008
- **Input values paired**: dept_picker.nickname, dept_picker.username, dept_picker.password

### `detail_dialog`  *(reuse: 1)*
- **EN**: detail dialog
- **ZH 提示**: detail / 弹窗
- **Context**: dialog
- **Selectors (1):**
  - `[role="dialog"]`
- **Used in**: TC-ICM-004

### `detail_fields`  *(reuse: 1)*
- **EN**: detail fields
- **Context**: -
- **Selectors (3):**
  - `placeholder=请输入设备名称`
  - `placeholder=请输入设备ip`
  - `placeholder=请输入设备端口`
- **Used in**: TC-ICM-004

### `dev_login_url`  *(reuse: 1)*
- **EN**: dev login url
- **ZH 提示**: dev / 登录 / 页面
- **Context**: route
- **Selectors (1):**
  - `https://dev.tcsoft.net.cn/login?redirect=%2Fredirect`
- **Used in**: TC-ICM-012
- **Input values paired**: dev_login_url.labo_username, dev_login_url.labo_password, dev_login_url.device_name, dev_login_url.request_valid_days, dev_login_url.request_contact

### `device_checkbox`  *(reuse: 1)*
- **EN**: device checkbox
- **ZH 提示**: device / 设备
- **Context**: -
- **Selectors (1):**
  - `.el-checkbox__inner`
- **Used in**: TC-ICM-009
- **Input values paired**: device_checkbox.tester_user, device_checkbox.server_name, device_checkbox.device_name

### `device_info_entry`  *(reuse: 1)*
- **EN**: device info entry
- **ZH 提示**: device / 设备
- **Context**: -
- **Selectors (1):**
  - `.screen-top-head`
- **Used in**: TC-ICM-012
- **Input values paired**: device_info_entry.labo_username, device_info_entry.labo_password, device_info_entry.device_name, device_info_entry.request_valid_days, device_info_entry.request_contact

### `device_ip_input`  *(reuse: 1)*
- **EN**: device ip input
- **ZH 提示**: device / 设备 / IP / 输入框
- **Context**: -
- **Selectors (1):**
  - `dialog input index 3`
- **Used in**: TC-ICM-006
- **Input values paired**: device_ip_input.device_name, device_ip_input.device_ip, device_ip_input.device_port, device_ip_input.vnc_password, device_ip_input.connection_type

### `device_list_table`  *(reuse: 1)*
- **EN**: device list table
- **ZH 提示**: device / 设备 / 列表
- **Context**: list_page
- **Selectors (2):**
  - `table`
  - `tbody`
- **Used in**: TC-ICM-003
- **Input values paired**: device_list_table.device_keyword

### `device_name`  *(reuse: 1)*
- **EN**: device name
- **ZH 提示**: device / 设备 / 名称
- **Context**: -
- **Selectors (1):**
  - `Test_Ins01`
- **Used in**: TC-ICM-007

### `device_name_input`  *(reuse: 1)*
- **EN**: device name input
- **ZH 提示**: device / 设备 / 名称 / 输入框
- **Context**: -
- **Selectors (1):**
  - `dialog input index 2`
- **Used in**: TC-ICM-006
- **Input values paired**: device_name_input.device_name, device_name_input.device_ip, device_name_input.device_port, device_name_input.vnc_password, device_name_input.connection_type

### `device_page_1`  *(reuse: 1)*
- **EN**: device page 1
- **ZH 提示**: device / 设备
- **Context**: -
- **Selectors (1):**
  - `.el-pager li.number:has-text(1)`
- **Used in**: TC-ICM-009
- **Input values paired**: device_page_1.tester_user, device_page_1.server_name, device_page_1.device_name

### `device_page_3`  *(reuse: 1)*
- **EN**: device page 3
- **ZH 提示**: device / 设备
- **Context**: -
- **Selectors (1):**
  - `.el-pager li.number:has-text(3)`
- **Used in**: TC-ICM-009
- **Input values paired**: device_page_3.tester_user, device_page_3.server_name, device_page_3.device_name

### `device_port_input`  *(reuse: 1)*
- **EN**: device port input
- **ZH 提示**: device / 设备 / 端口 / 输入框
- **Context**: -
- **Selectors (1):**
  - `dialog input index 4`
- **Used in**: TC-ICM-006
- **Input values paired**: device_port_input.device_name, device_port_input.device_ip, device_port_input.device_port, device_port_input.vnc_password, device_port_input.connection_type

### `device_query_input`  *(reuse: 1)*
- **EN**: device query input
- **ZH 提示**: device / 设备 / 输入框
- **Context**: -
- **Selectors (3):**
  - `placeholder=请输入设备名称`
  - `placeholder=请输入设备名`
  - `placeholder*=device`
- **Used in**: TC-ICM-003
- **Input values paired**: device_query_input.device_keyword

### `device_row_checkbox`  *(reuse: 1)*
- **EN**: device row checkbox
- **ZH 提示**: device / 设备
- **Context**: -
- **Selectors (1):**
  - `xpath=(//tr[contains(., "Test_Ins01")]//label[contains(@class,"el-checkbox")])[1]`
- **Used in**: TC-ICM-007

### `device_row_text`  *(reuse: 1)*
- **EN**: device row text
- **ZH 提示**: device / 设备
- **Context**: -
- **Selectors (1):**
  - `text=Test_Ins01`
- **Used in**: TC-ICM-009
- **Input values paired**: device_row_text.tester_user, device_row_text.server_name, device_row_text.device_name

### `device_status_switch`  *(reuse: 1)*
- **EN**: device status switch
- **ZH 提示**: device / 设备 / 状态 / 开关
- **Context**: -
- **Selectors (1):**
  - `.el-switch input[role='switch']`
- **Used in**: TC-ICM-006
- **Input values paired**: device_status_switch.device_name, device_status_switch.device_ip, device_status_switch.device_port, device_status_switch.vnc_password, device_status_switch.connection_type

### `device_tile`  *(reuse: 1)*
- **EN**: device tile
- **ZH 提示**: device / 设备
- **Context**: -
- **Selectors (1):**
  - `text=Test_Ins01`
- **Used in**: TC-ICM-010
- **Input values paired**: device_tile.username, device_tile.password, device_tile.device_name

### `device_type_select`  *(reuse: 1)*
- **EN**: device type select
- **ZH 提示**: device / 设备 / 类型 / 下拉选择
- **Context**: -
- **Selectors (1):**
  - `dialog input index 1`
- **Used in**: TC-ICM-006
- **Input values paired**: device_type_select.device_name, device_type_select.device_ip, device_type_select.device_port, device_type_select.vnc_password, device_type_select.connection_type

### `first_device_name`  *(reuse: 1)*
- **EN**: first device name
- **ZH 提示**: first / 设备 / 名称
- **Context**: -
- **Selectors (1):**
  - `text=AU5800`
- **Used in**: TC-ICM-012
- **Input values paired**: first_device_name.labo_username, first_device_name.labo_password, first_device_name.device_name, first_device_name.request_valid_days, first_device_name.request_contact

### `homepage_url`  *(reuse: 1)*
- **EN**: homepage url
- **ZH 提示**: homepage / 页面
- **Context**: route
- **Selectors (1):**
  - `#/index`
- **Used in**: TC-ICM-002

### `labo_login_url`  *(reuse: 1)*
- **EN**: labo login url
- **ZH 提示**: labo / 登录 / 页面
- **Context**: route
- **Selectors (1):**
  - `https://192.168.16.203:49187/#/login?redirect=%2Fredirect`
- **Used in**: TC-ICM-012
- **Input values paired**: labo_login_url.labo_username, labo_login_url.labo_password, labo_login_url.device_name, labo_login_url.request_valid_days, labo_login_url.request_contact

### `login_controls`  *(reuse: 1)*
- **EN**: login controls
- **ZH 提示**: login / 登录
- **Context**: -
- **Selectors (2):**
  - `placeholder=账号`
  - `placeholder=密码`
- **Used in**: TC-ICM-005

### `login_url`  *(reuse: 1)*
- **EN**: login url
- **ZH 提示**: login / 登录 / 页面
- **Context**: route
- **Selectors (1):**
  - `#/login`
- **Used in**: TC-ICM-010
- **Input values paired**: login_url.username, login_url.password, login_url.device_name

### `logout_menu_item`  *(reuse: 1)*
- **EN**: logout menu item
- **ZH 提示**: logout / 退出 / 菜单
- **Context**: -
- **Selectors (2):**
  - `text=退出登录`
  - `text=退出`
- **Used in**: TC-ICM-005

### `more_button`  *(reuse: 1)*
- **EN**: more button
- **ZH 提示**: more / 按钮
- **Context**: -
- **Selectors (2):**
  - `text=More`
  - `button:has-text(More)`
- **Used in**: TC-ICM-009
- **Input values paired**: more_button.tester_user, more_button.server_name, more_button.device_name

### `nickname_input`  *(reuse: 1)*
- **EN**: nickname input
- **ZH 提示**: nickname / 输入框
- **Context**: -
- **Selectors (1):**
  - `placeholder=请输入用户昵称`
- **Used in**: TC-ICM-008
- **Input values paired**: nickname_input.nickname, nickname_input.username, nickname_input.password

### `open_remote_button`  *(reuse: 1)*
- **EN**: open remote button
- **ZH 提示**: open / 按钮
- **Context**: -
- **Selectors (1):**
  - `button:has-text(打开远程界面)`
- **Used in**: TC-ICM-012
- **Input values paired**: open_remote_button.labo_username, open_remote_button.labo_password, open_remote_button.device_name, open_remote_button.request_valid_days, open_remote_button.request_contact

### `post_picker`  *(reuse: 1)*
- **EN**: post picker
- **Context**: -
- **Selectors (1):**
  - `placeholder=请选择岗位`
- **Used in**: TC-ICM-008
- **Input values paired**: post_picker.nickname, post_picker.username, post_picker.password

### `process_button`  *(reuse: 1)*
- **EN**: process button
- **ZH 提示**: process / 按钮
- **Context**: -
- **Selectors (1):**
  - `button:has-text(处理)`
- **Used in**: TC-ICM-012
- **Input values paired**: process_button.labo_username, process_button.labo_password, process_button.device_name, process_button.request_valid_days, process_button.request_contact

### `remote_help_url`  *(reuse: 1)*
- **EN**: remote help url
- **ZH 提示**: remote / 页面
- **Context**: route
- **Selectors (1):**
  - `https://dev.tcsoft.net.cn/hubble/remoteHelpInfo`
- **Used in**: TC-ICM-012
- **Input values paired**: remote_help_url.labo_username, remote_help_url.labo_password, remote_help_url.device_name, remote_help_url.request_valid_days, remote_help_url.request_contact

### `remote_toolbar_solve_icon`  *(reuse: 1)*
- **EN**: remote toolbar solve icon
- **Context**: -
- **Selectors (1):**
  - `.top-center img.el-tooltip:nth-of-type(2)`
- **Used in**: TC-ICM-012
- **Input values paired**: remote_toolbar_solve_icon.labo_username, remote_toolbar_solve_icon.labo_password, remote_toolbar_solve_icon.device_name, remote_toolbar_solve_icon.request_valid_days, remote_toolbar_solve_icon.request_contact

### `request_assistance_button`  *(reuse: 1)*
- **EN**: request assistance button
- **ZH 提示**: request / 按钮
- **Context**: -
- **Selectors (2):**
  - `button:has-text(请求协助)`
  - `text=请求协助`
- **Used in**: TC-ICM-012
- **Input values paired**: request_assistance_button.labo_username, request_assistance_button.labo_password, request_assistance_button.device_name, request_assistance_button.request_valid_days, request_assistance_button.request_contact

### `request_dialog`  *(reuse: 1)*
- **EN**: request dialog
- **ZH 提示**: request / 弹窗
- **Context**: dialog
- **Selectors (1):**
  - `.el-dialog:visible`
- **Used in**: TC-ICM-012
- **Input values paired**: request_dialog.labo_username, request_dialog.labo_password, request_dialog.device_name, request_dialog.request_valid_days, request_dialog.request_contact

### `role_picker`  *(reuse: 1)*
- **EN**: role picker
- **Context**: -
- **Selectors (1):**
  - `placeholder=请选择角色`
- **Used in**: TC-ICM-008
- **Input values paired**: role_picker.nickname, role_picker.username, role_picker.password

### `row_modify_button`  *(reuse: 1)*
- **EN**: row modify button
- **ZH 提示**: row / 按钮
- **Context**: -
- **Selectors (2):**
  - `button[text=修改]`
  - `button:has-text(修改)`
- **Used in**: TC-ICM-004

### `server_name`  *(reuse: 1)*
- **EN**: server name
- **ZH 提示**: server / 服务器 / 名称
- **Context**: -
- **Selectors (1):**
  - `Test Server#203`
- **Used in**: TC-ICM-007

### `stable_home_signals`  *(reuse: 1)*
- **EN**: stable home signals
- **Context**: -
- **Selectors (4):**
  - `home`
  - `portal`
  - `首页`
  - `系统管理`
- **Used in**: TC-ICM-002

### `stable_list_signals`  *(reuse: 1)*
- **EN**: stable list signals
- **ZH 提示**: stable / 列表
- **Context**: list_page
- **Selectors (2):**
  - `设备信息`
  - `device`
- **Used in**: TC-ICM-003
- **Input values paired**: stable_list_signals.device_keyword

### `success_signals`  *(reuse: 1)*
- **EN**: success signals
- **Context**: -
- **Selectors (3):**
  - `#/index`
  - `home`
  - `portal`
- **Used in**: TC-ICM-001
- **Input values paired**: success_signals.username, success_signals.password

### `target_server_text`  *(reuse: 1)*
- **EN**: target server text
- **ZH 提示**: target / 服务器
- **Context**: -
- **Selectors (1):**
  - `text=Test Server#203`
- **Used in**: TC-ICM-009
- **Input values paired**: target_server_text.tester_user, target_server_text.server_name, target_server_text.device_name

### `tile_hotspot`  *(reuse: 1)*
- **EN**: tile hotspot
- **Context**: -
- **Selectors (1):**
  - `.screen-mask-img`
- **Used in**: TC-ICM-010
- **Input values paired**: tile_hotspot.username, tile_hotspot.password, tile_hotspot.device_name

### `user_avatar`  *(reuse: 1)*
- **EN**: user avatar
- **ZH 提示**: user / 用户 / 头像
- **Context**: -
- **Selectors (1):**
  - `img.user-avatar`
- **Used in**: TC-ICM-005

### `vnc_password_input`  *(reuse: 1)*
- **EN**: vnc password input
- **ZH 提示**: vnc / 密码 / 输入框
- **Context**: -
- **Selectors (1):**
  - `dialog input index 8`
- **Used in**: TC-ICM-006
- **Input values paired**: vnc_password_input.device_name, vnc_password_input.device_ip, vnc_password_input.device_port, vnc_password_input.vnc_password, vnc_password_input.connection_type

## by_case 索引

| case_id | title | category | selectors |
|---|---|---|---|
| TC-ICM-001 | ICM login success | login | 4 |
| TC-ICM-002 | ICM homepage load success | navigation | 2 |
| TC-ICM-003 | ICM device list open and query | action | 4 |
| TC-ICM-004 | ICM device detail open | navigation | 5 |
| TC-ICM-005 | ICM logout returns to login page | logout | 4 |
| TC-ICM-006 | ICM create device record | action | 14 |
| TC-ICM-007 | ICM bind device to server | action | 8 |
| TC-ICM-008 | ICM create user | action | 8 |
| TC-ICM-009 | ICM bind server and device to user | action | 12 |
| TC-ICM-010 | ICM screen wall open remote desktop | navigation | 7 |
| TC-ICM-011 | ICM cleanup user and device bindings | action | 10 |
| TC-ICM-012 | ICM remote repair request to resolve | action | 11 |
| TC-ICM-013 | 仅密码为空时提示请输入密码 |  | 2 |
| TC-ICM-015 | 未登录访问受保护页面被重定向至登录页 |  | 1 |
| TC-ICM-016 | 登录成功后刷新页面仍保持登录态 |  | 3 |
| TC-ICM-017 | 账号包含特殊字符时登录被拒绝 |  | 3 |
| TC-ICM-018 | 账号为空时点击登录提示请输入账号 |  | 1 |
| TC-ICM-019 | 密码输入框为掩码显示 |  | 1 |
| TC-ICM-020 | 使用正确账号密码登录成功跳转屏幕墙 |  | 3 |
| TC-ICM-021 | 填写全部合法字段新增设备信息成功 |  | 1 |
| TC-ICM-022 | 设备名称输入恰好15个字符通过校验 |  | 1 |
| TC-ICM-023 | 设备名称输入16个字符触发自动截断 |  | 1 |
| TC-ICM-024 | 备注输入恰好500个字符通过校验 |  | 1 |
| TC-ICM-025 | 设备端口填写合法边界值65535通过校验 |  | 1 |
| TC-ICM-026 | 必填字段为空提交触发非空校验 |  | 1 |
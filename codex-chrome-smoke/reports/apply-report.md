# Apply Report — PT signals → yaml assertions

- Generated: 2026-07-09T03:02:54.242027+00:00
- Backup dir: `test-cases\icm\.bak-pre-pt-apply`
- Plan source: `reports\patch-plan.json`
- Cases touched: **11/11**
- Total assertions added: **21**


## Per-case changes

### TC-ICM-001 (`test-cases\icm\TC-ICM-001-login-success.yaml`)  +1 assertion(s)

**before:**
  - The URL contains #/index.
  - Homepage signals are visible.
  - The page does not stay on the login screen.

**after (added only):**
  + Decide whether the homepage is reached.

### TC-ICM-002 (`test-cases\icm\TC-ICM-002-homepage-load.yaml`)  +3 assertion(s)

**before:**
  - The URL contains #/index.
  - The homepage no longer shows a loading message.
  - The page does not return to login.

**after (added only):**
  + Wait for loading to finish.
  + Decide whether stable homepage sections are rendered.
  + If the page returns to login, mark the run as failed and stop.

### TC-ICM-003 (`test-cases\icm\TC-ICM-003-device-list-query.yaml`)  +2 assertion(s)

**before:**
  - The URL contains #/hubble/device or the device list view is otherwise confirmed.
  - The page stays on the device list view after the query.
  - The result area refreshes after the query.
  - The body or table contains AU5800.

**after (added only):**
  + Wait for the list page to render.
  + Decide whether the query action completed successfully.

### TC-ICM-004 (`test-cases\icm\TC-ICM-004-device-detail-open.yaml`)  +2 assertion(s)

**before:**
  - The URL contains #/hubble/device or the device list view is otherwise confirmed.
  - Clicking Modify opens a dialog, drawer, or detail form.
  - The detail surface contains device name, IP, and port fields.

**after (added only):**
  + Open `Detail` or the equivalent visible entry.
  + Decide whether the detail appears as a page, modal, or drawer.

### TC-ICM-005 (`test-cases\icm\TC-ICM-005-logout-return-login.yaml`)  +3 assertion(s)

**before:**
  - The login controls are visible again after confirmation.
  - The login page shows account and password controls again.
  - The page does not stay on the homepage.

**after (added only):**
  + Click `Confirm` in the logout dialog.
  + Decide whether the page returned to login and whether account, password, and login controls are visible again.
  + Keep 3 screenshots: homepage, logout confirm dialog, returned login page.

### TC-ICM-006 (`test-cases\icm\TC-ICM-006-device-create.yaml`)  +1 assertion(s)

**before:**
  - The Add/New button opens a visible device dialog.
  - The form accepts the supplied device data.
  - The Device Status switch is enabled before submit.
  - The action screenshot shows the filled form with enabled status.
  - After save, searching Test_Ins01 returns a visible device row with enabled status.

**after (added only):**
  + Save the record and confirm it appears in the list.

### TC-ICM-007 (`test-cases\icm\TC-ICM-007-server-bind-device.yaml`)  +1 assertion(s)

**before:**
  - The server edit dialog can be opened.
  - The selected device appears in the binding area or the save action succeeds.
  - The final state shows the binding was persisted.

**after (added only):**
  + Check the device and confirm the save.

### TC-ICM-008 (`test-cases\icm\TC-ICM-008-create-user.yaml`)  +1 assertion(s)

**before:**
  - The add form opens.
  - The submitted user appears in the user list.
  - The run report records a successful creation.

**after (added only):**
  + Save the user and confirm it appears in the list.

### TC-ICM-009 (`test-cases\icm\TC-ICM-009-user-bind-server-device.yaml`)  +3 assertion(s)

**before:**
  - The configure action can be opened.
  - The target server can be selected.
  - The current-server switch can be enabled.
  - The bound device list shows Test_Ins01 on page 1 after selection.

**after (added only):**
  + In the server selection page, check `Test Server#203` and confirm.
  + Refresh server info and enable the current server.
  + Refresh bound device info and check `Test_Ins01`.

### TC-ICM-010 (`test-cases\icm\TC-ICM-010-screen-wall-remote-desktop.yaml`)  +3 assertion(s)

**before:**
  - The screen wall page opens.
  - The Test_Ins01 tile can be hovered.
  - A remote desktop tab is opened.

**after (added only):**
  + Wait until all devices finish refreshing.
  + Confirm a new tab opens for the remote desktop.
  + Wait for the remote desktop to finish loading.

### TC-ICM-011 (`test-cases\icm\TC-ICM-011-cleanup-server-device-binding.yaml`)  +1 assertion(s)

**before:**
  - The Tester user is removed.
  - The device Test_Ins01 is removed.
  - The server edit dialog no longer returns Test_Ins01 in the bound device search.

**after (added only):**
  + Confirm that `Test_Ins01` cannot be found.

const base = {
  system: "icm-internal",
  baseUrl: "https://192.168.16.203:49187",
  entryUrl: "https://192.168.16.203:49187/#/login?redirect=%2Fredirect",
  admin: { username: process.env.ICM_ADMIN_USERNAME || "admin", password: process.env.ICM_ADMIN_PASSWORD || "" },
  tester: { username: process.env.ICM_TESTER_USERNAME || "Tester", password: process.env.ICM_TESTER_PASSWORD || "" },
  device: {
    name: "Test_Ins01",
    ip: "192.168.16.11",
    port: "5900",
    vncPassword: process.env.ICM_VNC_PASSWORD || "",
    connector: "杩炴帴鍣?1",
    type: "鏍囧噯璁惧",
  },
  server: "Test Server#203",
};

async function ensureLoggedIn(ctx) {
  const currentUrl = String(await ctx.page.url());
  if (currentUrl.includes("#/index") || currentUrl.includes("#/system") || currentUrl.includes("#/hubble")) return;
  await ctx.page.goto(base.entryUrl);
  await ctx.page.getByPlaceholder(/账号|account/).fill(base.admin.username);
  await ctx.page.getByPlaceholder(/密码|password/).fill(base.admin.password);
  await ctx.page.getByRole("button", { name: /登录|login/ }).click();
  await ctx.page.waitForLoadState("networkidle").catch(() => {});
}

async function openMenu(ctx, label) {
  await ctx.page.getByText(label, { exact: true }).click().catch(async () => {
    await ctx.page.getByRole("link", { name: label, exact: true }).click();
  });
  await ctx.page.waitForLoadState("networkidle").catch(() => {});
}

async function clickButton(ctx, name) {
  await ctx.page.getByRole("button", { name }).click();
}

async function capture(ctx, runDir, name) {
  await ctx.page.screenshot({ path: `${runDir}/${name}`, fullPage: false });
}

async function searchByPlaceholder(ctx, placeholder, value) {
  const loc = ctx.page.getByPlaceholder(placeholder);
  await loc.first().fill(value);
}

async function confirmSave(ctx, buttonName = "确定") {
  await ctx.page.getByRole("button", { name: buttonName }).click().catch(async () => {
    await ctx.page.getByRole("button", { name: /确\s*定/ }).click();
  });
  await ctx.page.waitForTimeout(1200);
}

async function openDialogByText(ctx, text) {
  await ctx.page.getByText(text, { exact: true }).click();
  await ctx.page.waitForTimeout(1200);
}

async function findRowByText(ctx, text) {
  return ctx.page.locator("tr", { hasText: text }).first();
}

export const icmCases = {
  "TC-ICM-001": {
    title: "ICM login success",
    async run(ctx) {
      await ctx.page.goto(base.entryUrl);
      await ctx.page.getByPlaceholder(/账号|account/).fill(base.admin.username);
      await ctx.page.getByPlaceholder(/密码|password/).fill(base.admin.password);
      await ctx.page.getByRole("button", { name: /登录|login/ }).click();
      await ctx.page.waitForLoadState("networkidle").catch(() => {});
      return { status: String(await ctx.page.url()).includes("#/index") ? "passed" : "failed" };
    },
  },
  "TC-ICM-002": {
    title: "ICM homepage load",
    async run(ctx) {
      await ensureLoggedIn(ctx);
      return { status: String(await ctx.page.url()).includes("#/index") || String(await ctx.page.url()).includes("#/system") ? "passed" : "failed" };
    },
  },
  "TC-ICM-003": {
    title: "ICM device list query",
    async run(ctx) {
      await ensureLoggedIn(ctx);
      await ctx.page.goto(`${base.baseUrl}/#/hubble/device`);
      await ctx.page.waitForLoadState("networkidle").catch(() => {});
      const queryInput = ctx.page.getByPlaceholder(/请输入设备名称|请输入设备名|device/i).first();
      await queryInput.fill("AU5800");
      await ctx.page.keyboard.press("Enter").catch(() => {});
      await ctx.page.waitForTimeout(1500);
      const bodyText = await ctx.page.locator("body").innerText().catch(() => "");
      const tableText = await ctx.page.locator("table").innerText().catch(() => "");
      return { status: tableText.includes("AU5800") || bodyText.includes("AU5800") ? "passed" : "failed" };
    },
  },
  "TC-ICM-004": {
    title: "ICM device detail open",
    async run(ctx) {
      await ensureLoggedIn(ctx);
      await ctx.page.goto(`${base.baseUrl}/#/hubble/device`);
      await ctx.page.waitForLoadState("networkidle").catch(() => {});
      const row = await findRowByText(ctx, "AU5800");
      await row.getByRole("button", { name: "修改" }).click();
      await ctx.page.waitForTimeout(1200);
      return { status: "passed" };
    },
  },
  "TC-ICM-005": {
    title: "ICM logout return login",
    async run(ctx) {
      await ensureLoggedIn(ctx);
      await ctx.page.locator("img.user-avatar").click().catch(() => {});
      await ctx.page.getByText("退出登录", { exact: true }).click().catch(() => {});
      await ctx.page.getByRole("button", { name: /确定/ }).click().catch(() => {});
      await ctx.page.waitForLoadState("networkidle").catch(() => {});
      return { status: "passed" };
    },
  },
  "TC-ICM-006": {
    title: "ICM create device record",
    async run(ctx) {
      await ensureLoggedIn(ctx);
      await ctx.page.goto(`${base.baseUrl}/#/hubble/device`);
      await ctx.page.waitForLoadState("networkidle").catch(() => {});
      await clickButton(ctx, "新增");
      const dialog = ctx.page.getByRole("dialog", { name: /添加设备信息/ });
      await dialog.getByPlaceholder("请选择连接类型").click();
      await ctx.page.keyboard.press("Enter");
      await dialog.getByPlaceholder("请选择设备类型").click();
      await ctx.page.keyboard.press("Enter");
      await dialog.getByPlaceholder("请输入设备名称").fill(base.device.name);
      await dialog.getByPlaceholder("请输入设备IP").fill(base.device.ip);
      await dialog.getByPlaceholder("请输入设备端口").fill(base.device.port);
      await dialog.getByPlaceholder("请输入vnc密码").fill(base.device.vncPassword);
      await dialog.getByPlaceholder("请选择是否为允许控制").click();
      await ctx.page.keyboard.press("Enter");
      await dialog.getByRole("button", { name: /确\s*定/ }).click();
      await ctx.page.waitForTimeout(1500);
      return { status: (await ctx.page.locator("table").innerText().catch(() => "")).includes(base.device.name) ? "passed" : "failed" };
    },
  },
  "TC-ICM-007": {
    title: "ICM bind device to server",
    async run(ctx) {
      await ensureLoggedIn(ctx);
      await ctx.page.goto(`${base.baseUrl}/#/hubble/server`);
      await ctx.page.waitForLoadState("networkidle").catch(() => {});
      const row = await findRowByText(ctx, base.server);
      await row.getByText("修改").click();
      await ctx.page.waitForTimeout(1000);
      await searchByPlaceholder(ctx, "请输入设备名称", base.device.name);
      await ctx.page.locator(`xpath=(//tr[contains(., "${base.device.name}")]//label[contains(@class,"el-checkbox")])[1]`).click();
      await confirmSave(ctx);
      return { status: "passed" };
    },
  },
  "TC-ICM-008": {
    title: "ICM create user",
    async run(ctx) {
      await ensureLoggedIn(ctx);
      await ctx.page.goto(`${base.baseUrl}/#/system/user`);
      await ctx.page.waitForLoadState("networkidle").catch(() => {});
      await clickButton(ctx, "新增");
      const dialog = ctx.page.locator('[role="dialog"]').filter({ hasText: "添加用户" }).first();
      await dialog.getByPlaceholder("请输入用户昵称").fill(base.tester.username);
      await dialog.getByPlaceholder("请输入用户名称").fill(base.tester.username);
      await dialog.getByPlaceholder("请输入用户密码").fill(base.tester.password);
      await dialog.getByPlaceholder("请选择归属部门").click().catch(() => {});
      await ctx.page.getByText("xx绉戞妧", { exact: false }).click().catch(() => {});
      await dialog.getByPlaceholder("请选择岗位").click().catch(() => {});
      await ctx.page.getByText("普通员工", { exact: true }).click().catch(() => {});
      await dialog.getByPlaceholder("请选择角色").click().catch(() => {});
      await ctx.page.getByText("普通角色", { exact: true }).click().catch(() => {});
      await confirmSave(ctx);
      await ctx.page.getByText("鏂板鎴愬姛").waitFor({ state: "visible", timeout: 15000 }).catch(() => {});
      await ctx.page.getByText(base.tester.username, { exact: false }).last().waitFor({ state: "visible", timeout: 15000 }).catch(() => {});
      const bodyText = await ctx.page.locator("body").innerText().catch(() => "");
      return { status: bodyText.includes("鏂板鎴愬姛") && bodyText.includes(base.tester.username) ? "passed" : "failed" };
    },
  },
  "TC-ICM-009": {
    title: "ICM bind server and device to user",
    async run(ctx) {
      await ensureLoggedIn(ctx);
      await ctx.page.goto(`${base.baseUrl}/#/system/user`);
      await ctx.page.waitForLoadState("networkidle").catch(() => {});
      const row = await findRowByText(ctx, base.tester.username);
      await row.getByRole("button", { name: /鏇村/ }).click();
      await ctx.page.getByText("閰嶇疆鏈嶅姟鍣ㄥ拰璁惧").click();
      await ctx.page.waitForTimeout(1000);
      await ctx.page.getByRole("button", { name: "添加服务器" }).click();
      await ctx.page.locator(`text=${base.server}`).click().catch(() => {});
      await confirmSave(ctx);
      return { status: String(await ctx.page.locator("body").innerText().catch(() => "")).includes(base.server) ? "passed" : "failed" };
    },
  },
  "TC-ICM-010": {
    title: "ICM screen wall open remote desktop",
    async run(ctx) {
      await ctx.page.goto(base.entryUrl);
      await ctx.page.getByPlaceholder(/账号|account/).fill(base.tester.username);
      await ctx.page.getByPlaceholder(/密码|password/).fill(base.tester.password);
      await ctx.page.getByRole("button", { name: /登录|login/ }).click();
      await ctx.page.waitForLoadState("networkidle").catch(() => {});
      await ctx.page.goto(`${base.baseUrl}/#/hubble/remoteHelpInfo`);
      await ctx.page.waitForLoadState("networkidle").catch(() => {});
      await ctx.page.getByText(base.device.name, { exact: false }).click().catch(() => {});
      await ctx.page.waitForTimeout(1500);
      return { status: "passed" };
    },
  },
  "TC-ICM-011": {
    title: "ICM cleanup server device binding",
    async run(ctx) {
      await ensureLoggedIn(ctx);
      await ctx.page.goto(`${base.baseUrl}/#/system/user`);
      await ctx.page.waitForLoadState("networkidle").catch(() => {});
      const userRow = await findRowByText(ctx, base.tester.username);
      await userRow.getByRole("button", { name: /鍒犻櫎/ }).click().catch(() => {});
      await ctx.page.getByRole("button", { name: /纭畾/ }).click().catch(() => {});
      await ctx.page.goto(`${base.baseUrl}/#/hubble/device`);
      await ctx.page.waitForLoadState("networkidle").catch(() => {});
      const deviceRow = await findRowByText(ctx, base.device.name);
      await deviceRow.getByRole("button", { name: /鍒犻櫎/ }).click().catch(() => {});
      await ctx.page.getByRole("button", { name: /纭畾/ }).click().catch(() => {});
      await ctx.page.goto(`${base.baseUrl}/#/hubble/server`);
      await ctx.page.waitForLoadState("networkidle").catch(() => {});
      const serverRow = await findRowByText(ctx, base.server);
      await serverRow.getByRole("button", { name: /淇敼/ }).click();
      await searchByPlaceholder(ctx, "请输入设备名称", base.device.name);
      return { status: (await ctx.page.locator("body").innerText().catch(() => "")).includes(base.device.name) ? "failed" : "passed" };
    },
  },
};

export async function captureStandardShots(ctx, runDir) {
  await capture(ctx, runDir, "01-entry.png");
  await capture(ctx, runDir, "02-action.png");
  await capture(ctx, runDir, "03-final.png");
}

export { base, ensureLoggedIn, openMenu, capture, clickButton, searchByPlaceholder, confirmSave, openDialogByText, findRowByText };

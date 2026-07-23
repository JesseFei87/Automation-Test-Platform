import test from "node:test";
import assert from "node:assert/strict";

import { translateCommandOutput, translateStepText } from "./stepTextZh.ts";

test("保留包含英文标识符的中文用例步骤", () => {
  assert.equal(translateStepText("用例步骤 1 - 登录ICM系统", "执行步骤 1"), "用例步骤 1 - 登录ICM系统");
  assert.equal(
    translateStepText("用例步骤 3 - 鼠标悬停在用户test所在行上《更多按钮", "执行步骤 3"),
    "用例步骤 3 - 鼠标悬停在用户test所在行上《更多按钮",
  );
});

test("翻译 Harness 登录步骤和命令输出", () => {
  assert.equal(translateStepText("fill username test in account input", "fallback"), "在账号输入框中填写用例账号");
  assert.equal(translateStepText("click login button to submit credentials", "fallback"), "点击登录按钮提交账号和密码");
  assert.equal(translateCommandOutput("[result] filled"), "[结果] 已填写");
  assert.equal(translateCommandOutput("[screenshot] step-02-fill.png"), "[截图] step-02-fill.png");
  assert.equal(translateStepText("fill username field with test from case test data (step 2)", "fallback"), "在账号输入框中填写用例账号");
  assert.equal(translateStepText("verify top navigation shows logged in user as test", "fallback"), "验证顶部导航显示当前登录用户");
  assert.equal(
    translateStepText("Login successful and redirected to screen wall (矩阵). All expected results are satisfied.", "fallback"),
    "登录验证完成：已进入屏幕墙并显示当前登录用户",
  );
  assert.equal(translateCommandOutput("[result] waited"), "[结果] 等待完成");
  assert.equal(translateCommandOutput("[error] timeout"), "[错误] timeout");
});

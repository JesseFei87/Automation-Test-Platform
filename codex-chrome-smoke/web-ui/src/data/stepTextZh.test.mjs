import test from "node:test";
import assert from "node:assert/strict";

import { translateStepText } from "./stepTextZh.ts";

test("保留包含英文标识符的中文用例步骤", () => {
  assert.equal(translateStepText("用例步骤 1 - 登录ICM系统", "执行步骤 1"), "用例步骤 1 - 登录ICM系统");
  assert.equal(
    translateStepText("用例步骤 3 - 鼠标悬停在用户test所在行上《更多按钮", "执行步骤 3"),
    "用例步骤 3 - 鼠标悬停在用户test所在行上《更多按钮",
  );
});

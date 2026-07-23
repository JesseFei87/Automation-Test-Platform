const exactStepTranslations = new Map<string, string>([
  ["open the icm login page", "打开 ICM 登录页面"],
  ["confirm that the login controls are visible", "确认登录控件已正常显示"],
  ["enter the credentials", "输入登录账号和密码"],
  ["click login", "点击登录按钮"],
  ["wait for the homepage to appear", "等待系统首页显示"],
  ["click login button to test empty password validation", "点击登录按钮，验证密码为空时的校验提示"],
  ["verify password required prompt is shown when password is empty", "验证密码为空时显示密码必填提示"],
  ["verify redirected to login page when accessing protected page without authentication", "验证未登录访问受保护页面时跳转到登录页"],
  [
    "goal achieved: successfully verified that when only password is empty, the system displays '请输入您的密码' prompt message",
    "目标已达成：已验证仅密码为空时，系统显示“请输入您的密码”提示",
  ],
]);

type StepTranslationRule = {
  pattern: RegExp;
  translate: (match: RegExpMatchArray) => string;
};

function normalizeDetail(detail: string) {
  return detail.trim().replace(/[.。]+$/, "");
}

function detailOrFallback(detail: string, fallback: string) {
  const normalized = normalizeDetail(detail);
  return normalized || fallback;
}

const stepTranslationRules: StepTranslationRule[] = [
  { pattern: /^verify login page rendered.*$/i, translate: () => "验证登录页及账号、密码输入框和登录按钮正常显示" },
  { pattern: /^fill (?:the )?(?:username|account)(?: field| input)?.*$/i, translate: () => "在账号输入框中填写用例账号" },
  { pattern: /^fill (?:the )?password(?: field| input)?.*$/i, translate: () => "在密码输入框中填写用例密码" },
  { pattern: /^submit login form.*$/i, translate: () => "点击登录按钮提交账号和密码" },
  { pattern: /^verify (?:the )?top navigation.*(?:user|test).*$/i, translate: () => "验证顶部导航显示当前登录用户" },
  { pattern: /^fill username(?:\s+(.+?))?\s+(?:in|into) (?:the )?(?:account|username) input$/i, translate: (match) => `在账号输入框中填写 ${match[1] || "用例账号"}` },
  { pattern: /^fill password with case test data(?:\s+.+)?$/i, translate: () => "在密码输入框中填写用例密码" },
  { pattern: /^click (?:the )?login button to submit credentials$/i, translate: () => "点击登录按钮提交账号和密码" },
  { pattern: /^verify (?:the )?logged-in user ['"]?(.+?)['"]? is shown in (?:the )?top navigation.*$/i, translate: (match) => `验证顶部导航显示当前登录用户 ${match[1]}` },
  { pattern: /^login (?:completed|successful).*$/i, translate: () => "登录验证完成：已进入屏幕墙并显示当前登录用户" },
  { pattern: /^fill username with\s+(.+)$/i, translate: (match) => `在用户名输入框中填写 ${match[1]}` },
  { pattern: /^fill password with\s+(.+)$/i, translate: () => "在密码输入框中填写用例密码" },
  { pattern: /^(?:open|navigate|go to|visit)\s+(.+)$/i, translate: (match) => `打开${detailOrFallback(match[1], "目标页面")}` },
  { pattern: /^(?:confirm|verify|check|ensure)\s+(?:that\s+)?(.+)$/i, translate: (match) => `验证${detailOrFallback(match[1], "当前页面状态是否符合预期")}` },
  { pattern: /^(?:enter|fill|input|type)\s+(.+)$/i, translate: (match) => `输入${detailOrFallback(match[1], "当前步骤所需的测试数据")}` },
  { pattern: /^(?:click|tap)\s+(.+)$/i, translate: (match) => `点击${detailOrFallback(match[1], "当前步骤指定的页面控件")}` },
  { pattern: /^wait(?:\s+for)?\s+(.+)$/i, translate: (match) => `等待${detailOrFallback(match[1], "页面状态更新")}` },
  { pattern: /^press\s+(.+)$/i, translate: (match) => `按下${detailOrFallback(match[1], "当前步骤指定的按键")}` },
  { pattern: /^(?:refresh|reload)\s+(.+)$/i, translate: (match) => `刷新${detailOrFallback(match[1], "当前页面")}` },
  { pattern: /^(?:finish|goal achieved|successfully verified)\s*:?(.+)$/i, translate: (match) => `完成验证：${detailOrFallback(match[1], "结果符合预期")}` },
  { pattern: /^(?:open|navigate|go to|visit)\b/i, translate: () => "打开目标页面" },
  { pattern: /^(?:confirm|verify|check|ensure)\b/i, translate: () => "验证页面状态是否符合预期" },
  { pattern: /^(?:enter|fill|input|type)\b/i, translate: () => "输入当前步骤所需的测试数据" },
  { pattern: /^(?:click|tap)\b/i, translate: () => "点击当前步骤指定的页面控件" },
  { pattern: /^wait\b/i, translate: () => "等待页面状态更新" },
  { pattern: /^press\b/i, translate: () => "按下当前步骤指定的按键" },
  { pattern: /^(?:refresh|reload)\b/i, translate: () => "刷新当前页面" },
  { pattern: /^(?:finish|goal achieved|successfully verified)\b/i, translate: () => "完成当前步骤验证，结果符合预期" },
];

export function translateStepText(value: string, fallback: string) {
  const trimmed = value.trim();
  if (!trimmed) return fallback;
  const normalized = trimmed.replace(/[.。]+$/, "").replace(/\s+/g, " ").toLowerCase();
  const exact = exactStepTranslations.get(normalized);
  if (exact) return exact;
  if (!/[a-z]/i.test(trimmed)) return trimmed;
  const matchedRule = stepTranslationRules.find((rule) => rule.pattern.test(trimmed));
  const match = matchedRule ? trimmed.match(matchedRule.pattern) : null;
  if (matchedRule && match) return matchedRule.translate(match);
  return /\p{Script=Han}/u.test(trimmed) ? trimmed : fallback;
}

export function translateCommandOutput(value: string) {
  const resultLabels: Record<string, string> = {
    navigated: "已打开页面",
    filled: "已填写",
    clicked: "已点击",
    asserted: "断言已通过",
    waited: "等待完成",
    pressed: "按键完成",
    scrolled: "滚动完成",
  };
  const result = value.match(/^\[result\]\s*(.+)$/i);
  if (result) return `[结果] ${resultLabels[result[1].trim().toLowerCase()] || result[1]}`;
  return value
    .replace(/^\[action\]/i, "[操作]")
    .replace(/^\[value\]/i, "[输入]")
    .replace(/^\[screenshot\]/i, "[截图]")
    .replace(/^\[url\]/i, "[地址]")
    .replace(/^\[error\]/i, "[错误]");
}

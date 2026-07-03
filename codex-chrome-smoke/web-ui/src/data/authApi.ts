/**
 * 鉴权与用户中心 · 纯前端 Mock API
 *
 * 不调用真实后端，全部走 localStorage 持久化。
 * 接口形状严格对齐 `dev-handoff-2026-07-03.md §2`，方便后续无缝替换为真实 fetch。
 *
 * - auth/login          POST /api/v1/auth/login
 * - me/avatar          POST /api/v1/me/avatar     (multipart，本 impl 用 FileReader → dataURL)
 * - me/password        POST /api/v1/me/password
 * - auth/logout        POST /api/v1/auth/logout
 * - me                 GET  /api/v1/me
 */

// 固定初始账号；与原型 banner / 登录页预填一致
const MOCK_USERS: Record<
  string,
  { id: string; username: string; password: string; displayName: string; role: "admin" | "user" | "qa" }
> = {
  admin: {
    id: "u-001",
    username: "admin",
    password: "qa123",
    displayName: "System Admin",
    role: "admin",
  },
};

const STORAGE_KEYS = {
  token: "icm.auth.token",
  user: "icm.auth.user",
  passwordPrefix: "icm.auth.password.", // + userId
  avatarPrefix: "icm.auth.avatar.", // + userId
  attemptsPrefix: "icm.auth.password.attempts.", // + userId
} as const;

const PASSWORD_ATTEMPT_WINDOW_MS = 5 * 60 * 1000;
const PASSWORD_ATTEMPT_LIMIT = 5;

export type AuthUser = {
  id: string;
  username: string;
  displayName: string;
  role: "admin" | "user" | "qa";
  avatarUrl: string | null;
};

export type AuthLoginResult = { token: string; user: AuthUser };
export type AuthError = { code: string; message: string };

// ---------------- 通用错误码（与 dev-handoff §2.3 一致） ----------------
export const AUTH_ERROR_CODES = {
  INVALID_CREDENTIALS: "INVALID_CREDENTIALS",
  OLD_PASSWORD_MISMATCH: "OLD_PASSWORD_MISMATCH",
  PASSWORD_TOO_WEAK: "PASSWORD_TOO_WEAK",
  PASSWORD_SAME_AS_OLD: "PASSWORD_SAME_AS_OLD",
  RATE_LIMITED: "RATE_LIMITED",
  AVATAR_TOO_LARGE: "AVATAR_TOO_LARGE",
  AVATAR_TYPE_INVALID: "AVATAR_TYPE_INVALID",
} as const;

function makeError(code: string, message: string): Error & AuthError {
  const e = new Error(message) as Error & AuthError;
  e.code = code;
  e.message = message;
  return e;
}

function delay<T>(value: T, ms = 200): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

function safeGet(key: string): string | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string) {
  try {
    if (typeof window !== "undefined") window.localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

function safeRemove(key: string) {
  try {
    if (typeof window !== "undefined") window.localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

function safeJson<T>(text: string | null, fallback: T): T {
  if (!text) return fallback;
  try {
    return JSON.parse(text) as T;
  } catch {
    return fallback;
  }
}

function getStoredPassword(userId: string): string {
  return safeGet(STORAGE_KEYS.passwordPrefix + userId) || MOCK_USERS[userId === "u-001" ? "admin" : ""]?.password || "";
}

function setStoredPassword(userId: string, password: string) {
  safeSet(STORAGE_KEYS.passwordPrefix + userId, password);
}

function getStoredAvatar(userId: string): string | null {
  return safeGet(STORAGE_KEYS.avatarPrefix + userId);
}

function setStoredAvatar(userId: string, dataUrl: string) {
  safeSet(STORAGE_KEYS.avatarPrefix + userId, dataUrl);
}

function getUserByUsername(username: string) {
  const normalized = username.trim().toLowerCase();
  if (normalized === "admin") return MOCK_USERS.admin;
  return null;
}

function toAuthUser(userId: string, fallback: { username: string; displayName: string; role: AuthUser["role"] }): AuthUser {
  const avatar = getStoredAvatar(userId);
  return {
    id: userId,
    username: fallback.username,
    displayName: fallback.displayName,
    role: fallback.role,
    avatarUrl: avatar,
  };
}

// ---------------- 公开 API ----------------

/**
 * POST /api/v1/auth/login
 * 成功 → { token, user }
 * 失败 → throw Error & { code: 'INVALID_CREDENTIALS' }
 */
export async function login(username: string, password: string): Promise<AuthLoginResult> {
  const user = getUserByUsername(username);
  const expected = user ? getStoredPassword(user.id) || user.password : null;

  if (!user || expected !== password) {
    return delay(Promise.reject(makeError(AUTH_ERROR_CODES.INVALID_CREDENTIALS, "账号或密码错误")), 180).catch((e) => {
      throw e;
    });
  }

  const token = `mock.${user.id}.${Date.now().toString(36)}`;
  const authUser = toAuthUser(user.id, user);
  safeSet(STORAGE_KEYS.token, token);
  safeSet(STORAGE_KEYS.user, JSON.stringify(authUser));
  return delay({ token, user: authUser });
}

/**
 * POST /api/v1/auth/logout
 */
export async function logout(): Promise<{ ok: true }> {
  safeRemove(STORAGE_KEYS.token);
  safeRemove(STORAGE_KEYS.user);
  return delay({ ok: true });
}

/**
 * GET /api/v1/me
 * 读取当前会话用户
 */
export async function me(): Promise<AuthUser | null> {
  const token = safeGet(STORAGE_KEYS.token);
  const raw = safeGet(STORAGE_KEYS.user);
  if (!token || !raw) return null;
  const user = safeJson<AuthUser>(raw, null as unknown as AuthUser);
  if (!user || !user.id) return null;
  // 始终把最新的 avatar 同步到 user 上
  return { ...user, avatarUrl: getStoredAvatar(user.id) };
}

/**
 * POST /api/v1/me/avatar
 * 校验大小/类型；将文件读为 dataURL 并落 localStorage
 */
export async function uploadAvatar(userId: string, file: File): Promise<{ avatarUrl: string }> {
  const validTypes = ["image/png", "image/jpeg", "image/webp"];
  if (!validTypes.includes(file.type)) {
    throw makeError(AUTH_ERROR_CODES.AVATAR_TYPE_INVALID, "仅支持 PNG / JPG / WebP 格式");
  }
  const maxSize = 2 * 1024 * 1024; // 2MB
  if (file.size > maxSize) {
    throw makeError(AUTH_ERROR_CODES.AVATAR_TOO_LARGE, "文件大小不能超过 2MB");
  }

  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("文件读取失败"));
    reader.readAsDataURL(file);
  });

  setStoredAvatar(userId, dataUrl);
  return delay({ avatarUrl: dataUrl });
}

/**
 * POST /api/v1/me/password
 * 错误码严格对齐 dev-handoff §2.3
 */
export async function changePassword(
  userId: string,
  oldPassword: string,
  newPassword: string,
): Promise<{ ok: true }> {
  // 5 分钟 5 次限流
  const attemptsKey = STORAGE_KEYS.attemptsPrefix + userId;
  const record = safeJson<{ count: number; firstAt: number }>(safeGet(attemptsKey), { count: 0, firstAt: 0 });
  const now = Date.now();
  if (record.count >= PASSWORD_ATTEMPT_LIMIT && now - record.firstAt < PASSWORD_ATTEMPT_WINDOW_MS) {
    throw makeError(AUTH_ERROR_CODES.RATE_LIMITED, "操作过于频繁，请稍后再试");
  }

  const expected = getStoredPassword(userId);
  if (oldPassword !== expected) {
    // 累计失败次数
    const next =
      record.count === 0 || now - record.firstAt > PASSWORD_ATTEMPT_WINDOW_MS
        ? { count: 1, firstAt: now }
        : { count: record.count + 1, firstAt: record.firstAt };
    safeSet(attemptsKey, JSON.stringify(next));
    throw makeError(AUTH_ERROR_CODES.OLD_PASSWORD_MISMATCH, "原密码不正确");
  }

  // 强度校验：≥8 位 + 含字母 + 含数字
  if (newPassword.length < 8 || !/[A-Za-z]/.test(newPassword) || !/\d/.test(newPassword)) {
    throw makeError(AUTH_ERROR_CODES.PASSWORD_TOO_WEAK, "密码需 8 位以上，含字母+数字");
  }
  if (newPassword === oldPassword) {
    throw makeError(AUTH_ERROR_CODES.PASSWORD_SAME_AS_OLD, "新密码不能与原密码相同");
  }

  setStoredPassword(userId, newPassword);
  // 成功后清空计数
  safeRemove(attemptsKey);
  return delay({ ok: true });
}

// ---------------- 客户端密码规则（前端预校验，与后端保持一致） ----------------

export type PasswordCheck = {
  lengthOk: boolean;
  hasLetter: boolean;
  hasNumber: boolean;
  sameAsOld: boolean;
};

export function checkPasswordRules(value: string, oldPassword: string): PasswordCheck {
  return {
    lengthOk: value.length >= 8,
    hasLetter: /[A-Za-z]/.test(value),
    hasNumber: /\d/.test(value),
    sameAsOld: value.length > 0 && value === oldPassword,
  };
}

export function isPasswordStrong(check: PasswordCheck): boolean {
  return check.lengthOk && check.hasLetter && check.hasNumber && !check.sameAsOld;
}

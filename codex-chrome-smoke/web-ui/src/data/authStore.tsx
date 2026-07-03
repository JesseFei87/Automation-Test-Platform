/**
 * 当前用户全局状态（React Context + Reducer）。
 *
 * 负责：
 *  - 登录 / 登出
 *  - 头像更新（写入 user.avatarUrl 并同步到 localStorage）
 *  - 暴露给 UI 使用的 currentUser / token / isAuthenticated
 */

import { createContext, useContext, useEffect, useMemo, useReducer } from "react";
import type { ReactNode } from "react";
import * as authApi from "./authApi";
import type { AuthUser } from "./authApi";

type AuthState = {
  status: "loading" | "authenticated" | "anonymous";
  user: AuthUser | null;
  token: string | null;
};

type AuthAction =
  | { type: "bootstrap"; user: AuthUser | null; token: string | null }
  | { type: "login"; user: AuthUser; token: string }
  | { type: "logout" }
  | { type: "setUser"; user: AuthUser }
  | { type: "setAvatar"; avatarUrl: string | null };

const initialState: AuthState = {
  status: "loading",
  user: null,
  token: null,
};

function reducer(state: AuthState, action: AuthAction): AuthState {
  switch (action.type) {
    case "bootstrap":
      return {
        status: action.user ? "authenticated" : "anonymous",
        user: action.user,
        token: action.token,
      };
    case "login":
      return { status: "authenticated", user: action.user, token: action.token };
    case "logout":
      return { status: "anonymous", user: null, token: null };
    case "setUser":
      return { ...state, user: action.user };
    case "setAvatar":
      return state.user
        ? { ...state, user: { ...state.user, avatarUrl: action.avatarUrl } }
        : state;
    default:
      return state;
  }
}

type AuthContextValue = {
  state: AuthState;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  setAvatar: (avatarUrl: string | null) => void;
  refreshMe: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const user = await authApi.me();
      const token = (() => {
        try {
          return typeof window === "undefined" ? null : window.localStorage.getItem("icm.auth.token");
        } catch {
          return null;
        }
      })();
      if (!cancelled) {
        dispatch({ type: "bootstrap", user, token });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      state,
      async login(username, password) {
        const result = await authApi.login(username, password);
        dispatch({ type: "login", user: result.user, token: result.token });
      },
      async logout() {
        await authApi.logout();
        dispatch({ type: "logout" });
      },
      setAvatar(avatarUrl) {
        dispatch({ type: "setAvatar", avatarUrl });
        // 写入持久化（authApi.uploadAvatar 已做，但允许外部重置为 null）
        if (avatarUrl === null) {
          try {
            if (state.user) {
              window.localStorage.removeItem(`icm.auth.avatar.${state.user.id}`);
            }
          } catch {
            /* ignore */
          }
        }
      },
      async refreshMe() {
        const user = await authApi.me();
        if (user) dispatch({ type: "setUser", user });
      },
    }),
    [state],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within <AuthProvider>");
  }
  return ctx;
}

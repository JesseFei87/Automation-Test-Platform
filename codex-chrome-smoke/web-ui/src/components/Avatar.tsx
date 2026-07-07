/**
 * 通用头像组件
 *
 * - 4 档尺寸：xs=24 / sm=32 / md=56 / lg=96
 * - 优先显示 src（来自 user.avatarUrl）
 * - 加载失败 / 无 src 时退回到"首字母占位"，颜色按 ASCII 模 6 命中 6 色板
 *
 * 设计令牌第 184-200 行：
 *   ch = username.trim().charAt(0).toUpperCase()
 *   idx = ch.charCodeAt(0) % 6
 *   色板：#2164f3 / #12b981 / #f39a20 / #6b4cf0 / #16b8d6 / #10213a
 */

import { useEffect, useState } from "react";

// 6 色板 —— 这是 6 个新令牌中允许硬编码 hex 的特例（avatar 占位色）
// 所有其他色值必须引用 CSS 变量
const AVATAR_PALETTE = ["#2164f3", "#12b981", "#f39a20", "#6b4cf0", "#16b8d6", "#10213a"] as const;

export type AvatarSize = "xs" | "sm" | "md" | "lg";

type AvatarProps = {
  username?: string | null;
  displayName?: string | null;
  src?: string | null;
  size?: AvatarSize;
  className?: string;
  ariaHidden?: boolean;
};

function pickPaletteIndex(name: string | null | undefined): number {
  const ch = (name || "?").trim().charAt(0).toUpperCase() || "?";
  const code = ch.charCodeAt(0) || 0;
  return code % AVATAR_PALETTE.length;
}

function pickInitialChar(name: string | null | undefined, displayName?: string | null): string {
  const source = (name || displayName || "?").trim();
  if (!source) return "?";
  const first = source.charAt(0).toUpperCase();
  // 非字母时降级为 "?"
  return /[A-Z]/.test(first) ? first : "?";
}

export function Avatar({
  username,
  displayName,
  src,
  size = "md",
  className,
  ariaHidden = true,
}: AvatarProps) {
  const [imgFailed, setImgFailed] = useState(false);
  const showImage = Boolean(src) && !imgFailed;

  // src 变化时重置 failed 状态
  useEffect(() => {
    setImgFailed(false);
  }, [src]);

  const initialChar = pickInitialChar(username, displayName);
  const bg = AVATAR_PALETTE[pickPaletteIndex(username)];

  const sizeClass = `user-avatar--${size}`;
  const classes = ["user-avatar", sizeClass, className].filter(Boolean).join(" ");

  return (
    <span
      className={classes}
      style={showImage ? undefined : { background: bg }}
      data-username={username || ""}
      aria-hidden={ariaHidden ? "true" : undefined}
    >
      {showImage ? (
        <img
          src={src as string}
          alt=""
          onError={() => setImgFailed(true)}
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            objectFit: "cover",
            borderRadius: "50%",
          }}
        />
      ) : (
        initialChar
      )}
    </span>
  );
}

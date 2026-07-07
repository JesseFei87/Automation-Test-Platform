/**
 * 修改头像弹窗（lg=720）
 *
 * - 选择文件 → 校验（≤2MB / PNG/JPG/WebP）
 * - 进入选区：8 方向 handle + 整体平移 + 1:1 固定比例 + 圆形遮罩
 * - 保存：把选区画到 canvas，导出 dataURL，调用 authApi.uploadAvatar
 * - 失败 Toast；成功关闭弹窗 + 全局头像刷新
 */

import { useEffect, useRef, useState } from "react";
import type { ChangeEvent, RefObject } from "react";
import { Modal } from "./Modal";
import * as authApi from "../data/authApi";
import { useAuth } from "../data/authStore";
import { useToast } from "./Toast";

export type AvatarEditModalProps = {
  open: boolean;
  onClose: () => void;
  triggerRef?: RefObject<HTMLElement | null>;
};

type Rect = { left: number; top: number; size: number }; // 单位：相对 stage 的 px
type StageMetrics = { width: number; height: number };

const MIN_SIZE = 60; // px
const PREVIEW_SIZE = 96; // px — 右侧预览圆形头像尺寸，须与 JSX inline width/height 一致

export function AvatarEditModal({ open, onClose, triggerRef }: AvatarEditModalProps) {
  const { state, setAvatar } = useAuth();
  const toast = useToast();
  const userId = state.user?.id || "";

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);

  const [imgSrc, setImgSrc] = useState<string | null>(null);
  const [naturalSize, setNaturalSize] = useState<{ w: number; h: number } | null>(null);
  const [stageSize, setStageSize] = useState<StageMetrics>({ width: 360, height: 360 });
  const [rect, setRect] = useState<Rect>({ left: 0, top: 0, size: 0 });
  const [saving, setSaving] = useState(false);

  // 监听 stage 实际尺寸（lg 弹窗最大宽度内）
  useEffect(() => {
    if (!open) return;
    const update = () => {
      const el = stageRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      setStageSize({ width: r.width, height: r.height });
    };
    update();
    const ro = new ResizeObserver(update);
    if (stageRef.current) ro.observe(stageRef.current);
    return () => ro.disconnect();
  }, [open]);

  // 加载图片后初始化 rect：取 stage 居中 80% 大小
  useEffect(() => {
    if (!imgSrc) {
      setNaturalSize(null);
      return;
    }
    const img = new Image();
    img.onload = () => {
      setNaturalSize({ w: img.naturalWidth, h: img.naturalHeight });
    };
    img.onerror = () => {
      toast.show({ kind: "error", message: "图片加载失败" });
    };
    img.src = imgSrc;
  }, [imgSrc, toast]);

  // 图片加载完（或 stage 尺寸变化）后初始化选区
  useEffect(() => {
    if (!imgSrc || !stageSize.width) return;
    const size = Math.min(stageSize.width, stageSize.height) * 0.8;
    setRect({
      left: (stageSize.width - size) / 2,
      top: (stageSize.height - size) / 2,
      size,
    });
  }, [imgSrc, stageSize.width, stageSize.height]);

  // 关闭时清理
  useEffect(() => {
    if (!open) {
      setImgSrc(null);
      setSaving(false);
    }
  }, [open]);

  function pickFile() {
    fileInputRef.current?.click();
  }

  function onFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // 允许选同一张图
    if (!file) return;
    const validTypes = ["image/png", "image/jpeg", "image/webp"];
    if (!validTypes.includes(file.type)) {
      toast.show({ kind: "error", message: "仅支持 PNG / JPG / WebP 格式" });
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      toast.show({ kind: "error", message: "文件大小不能超过 2MB" });
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setImgSrc(String(reader.result || ""));
    reader.onerror = () => toast.show({ kind: "error", message: "文件读取失败" });
    reader.readAsDataURL(file);
  }

  function clamp(v: number, min: number, max: number) {
    return Math.max(min, Math.min(max, v));
  }

  // 把 stage 内 px 选区对应到 image 像素
  // 返回值包含 dispW/dispH/dispX/dispY（图片在 stage 内的实际渲染区域），
  // 供预览背景的 backgroundSize/backgroundPosition 复用，避免重复计算。
  function getImageRect() {
    if (!naturalSize) return null;
    // object-fit: cover —— 计算图片在 stage 内的实际渲染区域
    const stageRatio = stageSize.width / stageSize.height;
    const imgRatio = naturalSize.w / naturalSize.h;
    let dispW: number, dispH: number, dispX: number, dispY: number;
    if (imgRatio > stageRatio) {
      // 图片更宽 → 高度铺满 stage，宽度溢出
      dispH = stageSize.height;
      dispW = dispH * imgRatio;
      dispX = (stageSize.width - dispW) / 2;
      dispY = 0;
    } else {
      // 图片更高（或相等） → 宽度铺满 stage，高度溢出
      dispW = stageSize.width;
      dispH = dispW / imgRatio;
      dispX = 0;
      dispY = (stageSize.height - dispH) / 2;
    }
    // stage 选区 (rect) → 图片像素坐标
    const scaleX = naturalSize.w / dispW;
    const scaleY = naturalSize.h / dispH;
    const x = clamp((rect.left - dispX) * scaleX, 0, naturalSize.w);
    const y = clamp((rect.top - dispY) * scaleY, 0, naturalSize.h);
    const maxW = naturalSize.w - x;
    const maxH = naturalSize.h - y;
    let w = clamp(rect.size * scaleX, 1, maxW);
    let h = clamp(rect.size * scaleY, 1, maxH);
    // 1:1 裁切，强制 w === h，避免圆形 clipPath 边缘出现缝隙
    const side = Math.min(w, h);
    w = side;
    h = side;
    return { x, y, w, h, dispW, dispH, dispX, dispY };
  }

  async function onSave() {
    if (!imgSrc || !naturalSize) return;
    const r = getImageRect();
    if (!r) {
      toast.show({ kind: "error", message: "选区无效，请重试" });
      return;
    }
    setSaving(true);
    try {
      // 渲染裁剪到 canvas（圆形遮罩）
      const out = 256;
      const canvas = document.createElement("canvas");
      canvas.width = out;
      canvas.height = out;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("Canvas 不可用");

      // 先把裁剪区域画到临时 canvas，再圆形裁切
      const tmp = document.createElement("canvas");
      tmp.width = r.w;
      tmp.height = r.h;
      const tctx = tmp.getContext("2d");
      if (!tctx) throw new Error("Canvas 不可用");
      const img = imgRef.current;
      if (!img) throw new Error("图片未加载");
      tctx.drawImage(img, r.x, r.y, r.w, r.h, 0, 0, r.w, r.h);

      // 圆形裁切
      ctx.save();
      ctx.beginPath();
      ctx.arc(out / 2, out / 2, out / 2, 0, Math.PI * 2);
      ctx.closePath();
      ctx.clip();
      ctx.drawImage(tmp, 0, 0, r.w, r.h, 0, 0, out, out);
      ctx.restore();

      const dataUrl = canvas.toDataURL("image/png");
      // 转换为 File 并走 authApi
      const blob = await (await fetch(dataUrl)).blob();
      const file = new File([blob], `avatar-${userId}.png`, { type: "image/png" });
      const result = await authApi.uploadAvatar(userId, file);
      setAvatar(result.avatarUrl);
      toast.show({ kind: "success", message: "头像已更新" });
      onClose();
    } catch (e) {
      const err = e as Error & { code?: string };
      const code = err.code || "UNKNOWN";
      const message =
        code === "AVATAR_TYPE_INVALID"
          ? "仅支持 PNG / JPG / WebP 格式"
          : code === "AVATAR_TOO_LARGE"
            ? "文件大小不能超过 2MB"
            : err.message || "头像保存失败";
      toast.show({ kind: "error", message });
    } finally {
      setSaving(false);
    }
  }

  // 选区交互：8 方向手柄 + 整体平移
  function startDrag(handle: string, e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    const startX = e.clientX;
    const startY = e.clientY;
    const start = { ...rect };
    const maxLeft = stageSize.width - start.size;
    const maxTop = stageSize.height - start.size;

    function onMove(ev: MouseEvent) {
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      let next = { ...start };

      if (handle === "move") {
        next.left = clamp(start.left + dx, 0, maxLeft);
        next.top = clamp(start.top + dy, 0, maxTop);
      } else {
        // 1:1 固定比例：以对角为锚点
        let newSize = start.size;
        let newLeft = start.left;
        let newTop = start.top;

        if (handle.includes("e")) {
          newSize = clamp(start.size + dx, MIN_SIZE, stageSize.width - start.left);
        } else if (handle.includes("w")) {
          newSize = clamp(start.size - dx, MIN_SIZE, start.left + start.size);
          newLeft = start.left + (start.size - newSize);
        }
        if (handle.includes("s")) {
          newSize = clamp(newSize + (handle.includes("e") || handle.includes("w") ? 0 : dy), MIN_SIZE, stageSize.height - newTop);
        } else if (handle.includes("n")) {
          newSize = clamp(newSize - (handle.includes("e") || handle.includes("w") ? 0 : dy), MIN_SIZE, newTop + newSize);
          newTop = newTop + (start.size - newSize);
        }
        // 维持 1:1：取最短边
        newSize = clamp(newSize, MIN_SIZE, Math.min(stageSize.width - newLeft, stageSize.height - newTop));
        next = { left: newLeft, top: newTop, size: newSize };
      }
      setRect(next);
    }
    function onUp() {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    }
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  function resetRect() {
    const size = Math.min(stageSize.width, stageSize.height) * 0.8;
    setRect({
      left: (stageSize.width - size) / 2,
      top: (stageSize.height - size) / 2,
      size,
    });
  }

  // 预览用的 disp：图片在 stage 内的实际渲染区域。
  // 注意：getImageRect 依赖 rect / naturalSize / stageSize，每次渲染都会重算；
  // 这里是纯函数计算，不写 state，渲染期间多次调用安全。
  const disp = imgSrc && naturalSize ? getImageRect() : null;

  // 预览缩放因子：把 stage 内 rect.size 的选区映射到 PREVIEW_SIZE 的预览圆。
  // 关键：backgroundSize / backgroundPosition 必须乘以同一缩放因子 k，
  // 否则预览只是 stage 像素的 1:1 窗口，仅显示选区左上角一小块，与左侧选区内容不一致。
  const previewScale = disp && rect.size > 0 ? PREVIEW_SIZE / rect.size : 1;

  return (
    <Modal
      open={open}
      onClose={() => {
        if (!saving) onClose();
      }}
      title="修改头像"
      size="lg"
      triggerRef={triggerRef}
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={() => (imgSrc ? resetRect() : onClose())} disabled={saving}>
            {imgSrc ? "重置选区" : "取消"}
          </button>
          {imgSrc ? (
            <button
              type="button"
              className="btn-primary"
              onClick={() => void onSave()}
              disabled={saving || !naturalSize}
            >
              {saving ? "保存中…" : "保存头像"}
            </button>
          ) : (
            <button type="button" className="btn-primary" onClick={pickFile} disabled={saving}>
              选择图片
            </button>
          )}
        </>
      }
    >
      <input
        ref={fileInputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        style={{ display: "none" }}
        onChange={onFileChange}
      />
      {!imgSrc ? (
        <div className="avatar-upload-empty">
          <div className="avatar-upload-empty__icon" aria-hidden="true">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 4v12" />
              <path d="M6 10l6-6 6 6" />
              <path d="M4 20h16" />
            </svg>
          </div>
          <p>支持 PNG / JPG / WebP 格式，文件大小 ≤ 2MB，建议尺寸 300×300 以上</p>
          <button type="button" className="btn-primary" onClick={pickFile}>
            选择图片
          </button>
        </div>
      ) : (
        <div className="avatar-cropper">
          <div
            ref={stageRef}
            className="crop-stage"
          >
            <img
              ref={imgRef}
              src={imgSrc}
              alt="待裁剪头像"
              draggable={false}
            />
            {/* 圆形遮罩 + 选区 */}
            <div className="crop-mask" aria-hidden="true" />
            <div
              className="crop-rect"
              style={{
                left: rect.left,
                top: rect.top,
                width: rect.size,
                height: rect.size,
                borderRadius: "50%",
              }}
              onMouseDown={(e) => startDrag("move", e)}
              role="region"
              aria-label="头像选区，拖动可移动"
            >
              {(["nw", "n", "ne", "e", "se", "s", "sw", "w"] as const).map((h) => (
                <div
                  key={h}
                  className={`crop-handle crop-handle--${h}`}
                  data-handle={h}
                  onMouseDown={(e) => startDrag(h, e)}
                  role="button"
                  aria-label={`调整选区${h.toUpperCase()}方向`}
                  tabIndex={-1}
                />
              ))}
            </div>
          </div>
          <div className="avatar-cropper__side">
            <h4>调整头像</h4>
            <ul className="avatar-cropper__tips">
              <li>拖动选区可移动位置</li>
              <li>拖动 8 个控制点可调整大小（1:1）</li>
              <li>圆形裁切将自动生效</li>
            </ul>
            <div className="avatar-cropper__preview">
              <span className="avatar-cropper__preview-label">预览</span>
              <div
                className="avatar-cropper__preview-circle"
                style={{
                  width: PREVIEW_SIZE,
                  height: PREVIEW_SIZE,
                  borderRadius: "50%",
                  backgroundImage: imgSrc ? `url(${imgSrc})` : undefined,
                  ...(disp
                    ? {
                        backgroundSize: `${disp.dispW * previewScale}px ${disp.dispH * previewScale}px`,
                        backgroundPosition: `${-(rect.left - disp.dispX) * previewScale}px ${-(rect.top - disp.dispY) * previewScale}px`,
                      }
                    : null),
                }}
                aria-hidden="true"
              />
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}

import type { ReactNode } from "react";

import { api } from "../data/api";

export const REQUIREMENT_DOCUMENT_PLACEHOLDER = `请粘贴完整的业务需求说明，例如：

【业务背景】
远程协助工单用于支持运维人员在用户授权后接入设备桌面，完成问题定位、处理和闭环。

【核心流程】
1. 用户在设备详情页发起远程协助请求，并填写问题描述。
2. 工单处理人员在远程协助列表中接收请求，打开远程控制界面。
3. 处理完成后点击“解决”，系统记录处理结果并更新工单状态。

【验收规则】
- 未授权或异常状态下不得进入远程界面。
- 处理完成后列表状态、详情记录和操作日志应保持一致。
- 失败场景需要给出明确提示并保留可追溯信息。`;

const ACCEPT = ".txt,.md,.docx,.pdf,text/plain,text/markdown,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/pdf";

function fileAsBase64(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("读取文件失败"));
    reader.onload = () => resolve(String(reader.result || "").split(",", 2)[1] || "");
    reader.readAsDataURL(file);
  });
}

function titleFromText(text: string, filename: string) {
  const heading = text.split(/\r?\n/).map((line) => line.trim()).find((line) => /^#\s+/.test(line));
  return heading?.replace(/^#\s+/, "").slice(0, 120) || filename.replace(/\.(txt|md|docx|pdf)$/i, "");
}

export async function parseRequirementFile(file: File) {
  const suffix = file.name.split(".").pop()?.toLowerCase() || "";
  if (!["txt", "md", "docx", "pdf"].includes(suffix)) {
    throw new Error("支持 TXT、MD、DOCX 和文本型 PDF。");
  }
  if (suffix === "txt" || suffix === "md") {
    const text = await file.text();
    return { filename: file.name, text, title: titleFromText(text, file.name) };
  }
  return api.parseRequirementDocument(file.name, await fileAsBase64(file));
}

export function RequirementDocumentInput({
  id,
  value,
  onChange,
  onFile,
  parsing = false,
  className = "requirement-textarea",
  placeholder = REQUIREMENT_DOCUMENT_PLACEHOLDER,
  children,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  onFile: (file: File) => void;
  parsing?: boolean;
  className?: string;
  placeholder?: string;
  children?: ReactNode;
}) {
  const metaId = `${id}-meta`;
  return (
    <div className="requirement-document-input">
      <label className="field-label" htmlFor={id}>
        需求正文（支持拖拽 TXT、MD、DOCX、文本型 PDF）
      </label>
      <div
        className="dropzone"
        onDragOver={(event) => {
          event.preventDefault();
          event.dataTransfer.dropEffect = "copy";
          event.currentTarget.classList.add("is-dragover");
        }}
        onDragLeave={(event) => event.currentTarget.classList.remove("is-dragover")}
        onDrop={(event) => {
          event.preventDefault();
          event.currentTarget.classList.remove("is-dragover");
          const file = event.dataTransfer.files?.[0];
          if (file) onFile(file);
        }}
      >
        <textarea
          aria-describedby={metaId}
          className={`textarea-mock textarea-real ${className}`}
          id={id}
          placeholder={placeholder}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      </div>
      <div className="requirement-document-meta" id={metaId}>{value.length.toLocaleString("zh-CN")} 字</div>
      <div className="button-row requirement-document-actions">
        <label className={`btn btn--soft upload-button${parsing ? " is-disabled" : ""}`}>
          {parsing ? "解析中..." : "上传需求文档"}
          <input
            accept={ACCEPT}
            disabled={parsing}
            type="file"
            onChange={(event) => {
              const file = event.currentTarget.files?.[0];
              event.currentTarget.value = "";
              if (file) onFile(file);
            }}
          />
        </label>
        {children}
      </div>
    </div>
  );
}

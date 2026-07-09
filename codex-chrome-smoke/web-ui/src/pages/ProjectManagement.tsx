import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Card } from "../components/Card";
import { StatusPill } from "../components/StatusPill";
import { api, type Project } from "../data/api";

type ProjectForm = {
  name: string;
  base_url: string;
  description: string;
};

const EMPTY_FORM: ProjectForm = {
  name: "",
  base_url: "",
  description: "",
};

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "unknown error";
}

function projectToForm(project: Project): ProjectForm {
  return {
    name: project.name,
    base_url: project.base_url || "",
    description: project.description || "",
  };
}

function formatTime(value?: string | null) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

type ProjectActionIcon = "edit" | "delete";

function ProjectActionSvg({ icon }: { icon: ProjectActionIcon }) {
  const paths: Record<ProjectActionIcon, ReactNode> = {
    edit: (
      <>
        <path d="M12 20h9" />
        <path d="m16.5 3.5 4 4L8 20l-4 1 1-4Z" />
      </>
    ),
    delete: (
      <>
        <path d="M4 7h16" />
        <path d="M10 11v6M14 11v6" />
        <path d="M6 7l1 14h10l1-14" />
        <path d="M9 7V4h6v3" />
      </>
    ),
  };
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      {paths[icon]}
    </svg>
  );
}

export function ProjectManagement() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [form, setForm] = useState<ProjectForm>(EMPTY_FORM);
  const [mode, setMode] = useState<"create" | "edit">("create");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("正在读取项目列表...");

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedId) || projects[0] || null,
    [projects, selectedId],
  );

  async function refresh(nextSelectedId?: string) {
    setLoading(true);
    try {
      const items = await api.listProjects();
      setProjects(items);
      const resolvedId = nextSelectedId ?? selectedId;
      const selected = items.find((item) => item.id === resolvedId) || items[0] || null;
      setSelectedId(selected?.id || "");
      setMode(selected ? "edit" : "create");
      setForm(selected ? projectToForm(selected) : EMPTY_FORM);
      setMessage(items.length ? `已读取 ${items.length} 个项目` : "暂无项目，请先新建项目");
    } catch (error) {
      setMessage(`项目列表读取失败：${errorMessage(error)}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  function selectProject(project: Project) {
    setSelectedId(project.id);
    setMode("edit");
    setForm(projectToForm(project));
    setMessage(`已选择项目：${project.name}`);
  }

  function startCreate() {
    setSelectedId("");
    setMode("create");
    setForm(EMPTY_FORM);
    setMessage("正在新建项目");
  }

  async function submitProject() {
    const name = form.name.trim();
    if (!name) {
      setMessage("项目名称不能为空");
      return;
    }
    setBusy(true);
    try {
      if (mode === "create") {
        const created = await api.createProject({
          name,
          base_url: form.base_url.trim() || null,
          description: form.description.trim() || null,
        });
        setMessage(`项目已创建：${created.name}`);
        await refresh(created.id);
        return;
      }
      if (!selectedProject) {
        setMessage("请先选择一个项目");
        return;
      }
      const updated = await api.updateProject(selectedProject.id, {
        name,
        base_url: form.base_url.trim() || null,
        description: form.description.trim() || null,
      });
      setMessage(`项目已保存：${updated.name}`);
      await refresh(updated.id);
    } catch (error) {
      setMessage(`${mode === "create" ? "创建" : "保存"}失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function deleteProject(project: Project) {
    const confirmed = window.confirm(`确认删除项目“${project.name}”？该操作只删除项目档案，不会删除已生成的需求、用例或报告。`);
    if (!confirmed) return;
    setBusy(true);
    try {
      await api.deleteProject(project.id);
      setMessage(`项目已删除：${project.name}`);
      await refresh(project.id === selectedId ? "" : selectedId);
    } catch (error) {
      setMessage(`删除失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page project-page">
      <section className="project-summary">
        <div className="project-metrics">
          <Metric label="项目总数" tag="Projects" value={projects.length} />
          <Metric label="已配置入口" tag="Configured" value={projects.filter((project) => project.base_url).length} />
          <Metric label="当前项目" tag="Current" value={selectedProject?.name || "--"} />
        </div>
      </section>

      <section className="project-layout">
        <Card className="project-list-card project-equal-card" title="项目列表" subtitle={message}>
          <div className="project-list-toolbar">
            <button className="btn btn--primary" onClick={startCreate} type="button">
              新建项目
            </button>
            <StatusPill tone={mode === "create" ? "green" : "blue"}>{mode === "create" ? "新增模式" : "编辑模式"}</StatusPill>
          </div>

          <table className="table">
            <thead>
              <tr>
                <th>项目</th>
                <th>入口</th>
                <th>更新时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((project) => (
                <tr className={project.id === selectedProject?.id ? "is-selected-row" : ""} key={project.id}>
                  <td>
                    <button className="link-button" onClick={() => selectProject(project)} type="button">
                      {project.name}
                    </button>
                  </td>
                  <td>{project.base_url || "未配置"}</td>
                  <td>{formatTime(project.updated_at)}</td>
                  <td>
                    <div className="project-row-actions">
                      <button className="project-row-action project-row-action--edit" onClick={() => selectProject(project)} title="编辑项目" type="button">
                        <ProjectActionSvg icon="edit" />
                      </button>
                      <button className="project-row-action project-row-action--delete" disabled={busy} onClick={() => deleteProject(project)} title="删除项目" type="button">
                        <ProjectActionSvg icon="delete" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {!projects.length ? (
                <tr>
                  <td colSpan={4}>{loading ? "正在读取项目..." : "暂无项目，请使用右侧表单新建。"}</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </Card>

        <div className="project-side">
          <Card
            className="project-equal-card"
            title={mode === "create" ? "新增项目" : "编辑项目"}
            subtitle={mode === "create" ? "创建后可在需求管理中关联该项目。" : selectedProject?.id || "请选择左侧项目"}
          >
            <ProjectFields form={form} onChange={setForm} />
            <div className="button-row">
              <button className={mode === "create" ? "btn btn--primary" : "btn btn--green"} disabled={busy} onClick={submitProject} type="button">
                {mode === "create" ? "创建项目" : "保存项目"}
              </button>
              {mode === "edit" && selectedProject ? <StatusPill tone="blue">{selectedProject.name}</StatusPill> : null}
              {mode === "edit" ? (
                <button className="btn btn--outline" disabled={busy} onClick={startCreate} type="button">
                  切到新增
                </button>
              ) : null}
            </div>
          </Card>
        </div>
      </section>
    </div>
  );
}

function Metric({ label, tag, value }: { label: string; tag: string; value: number | string }) {
  return (
    <article className="qa-metric-card project-metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{tag}</small>
    </article>
  );
}

function ProjectFields({
  form,
  onChange,
}: {
  form: ProjectForm;
  onChange: (next: ProjectForm) => void;
}) {
  return (
    <div className="project-fields">
      <label className="field-label">项目名称</label>
      <input className="text-input" onChange={(event) => onChange({ ...form, name: event.target.value })} placeholder="例如：ICM" value={form.name} />
      <label className="field-label">Base URL</label>
      <input className="text-input" onChange={(event) => onChange({ ...form, base_url: event.target.value })} placeholder="例如：https://example.com" value={form.base_url} />
      <label className="field-label">项目说明</label>
      <textarea
        className="text-input project-description"
        onChange={(event) => onChange({ ...form, description: event.target.value })}
        placeholder="补充业务范围、环境或备注"
        value={form.description}
      />
    </div>
  );
}

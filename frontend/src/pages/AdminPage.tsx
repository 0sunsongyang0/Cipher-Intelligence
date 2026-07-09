import { IconArrowLeft, IconRefresh } from "@tabler/icons-react";
import { useEffect, useMemo, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { AuroraBackground } from "../components/AuroraBackground";
import { AdminFilesPanel } from "../components/admin/AdminFilesPanel";
import { InviteCodesPanel } from "../components/admin/InviteCodesPanel";
import { AdminModelsPanel } from "../components/admin/AdminModelsPanel";
import { AdminOverview } from "../components/admin/AdminOverview";
import { AdminPromptPanel } from "../components/admin/AdminPromptPanel";
import {
  clearAdminFileCache,
  controlAdminService,
  getAdminOverview,
  getAdminPrompt,
  resetAdminPrompt,
  saveAdminPrompt
} from "../lib/api";
import type { AdminOverview as AdminOverviewData, AdminPrompt } from "../types";

const ADMIN_SECTIONS = ["services", "models", "files", "prompt", "invites"] as const;
type AdminSection = "overview" | (typeof ADMIN_SECTIONS)[number];

function getActiveSection(pathname: string): AdminSection {
  const lastSegment = pathname.split("/").filter(Boolean).at(-1) ?? "";

  if (lastSegment === "services") {
    return "services";
  }
  if (lastSegment === "models") {
    return "models";
  }
  if (lastSegment === "files") {
    return "files";
  }
  if (lastSegment === "prompt") {
    return "prompt";
  }
  if (lastSegment === "invites") {
    return "invites";
  }
  return "overview";
}

function getAdminRootPath(pathname: string): string {
  const segments = pathname.split("/").filter(Boolean);
  const lastSegment = segments.at(-1);

  if (!lastSegment) {
    return "/";
  }

  if (!ADMIN_SECTIONS.includes(lastSegment as (typeof ADMIN_SECTIONS)[number])) {
    return pathname;
  }

  if (segments.length === 1) {
    return "/";
  }

  return `/${segments.slice(0, -1).join("/")}`;
}

export function AdminPage({
  onLogout,
  sessionError
}: {
  onLogout: () => Promise<void> | void;
  sessionError?: string | null;
}) {
  const { pathname } = useLocation();
  const section = getActiveSection(pathname);
  const adminRootPath = getAdminRootPath(pathname);
  const [overview, setOverview] = useState<AdminOverviewData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyTarget, setBusyTarget] = useState<"backend" | "tunnel" | null>(null);
  const [clearingCache, setClearingCache] = useState(false);
  const [promptData, setPromptData] = useState<AdminPrompt | null>(null);
  const [promptDraft, setPromptDraft] = useState("");
  const [promptLoading, setPromptLoading] = useState(false);
  const [promptSaving, setPromptSaving] = useState(false);
  const [promptResetting, setPromptResetting] = useState(false);
  const [promptReloading, setPromptReloading] = useState(false);

  const activeError = sessionError ?? error;
  const serviceLabels = {
    backend: "聊天服务",
    tunnel: "Cloudflare 隧道"
  } as const;

  const navItems = useMemo<Array<{ to: string; label: string; key: AdminSection }>>(
    () => [
      { to: "/", label: "总览", key: "overview" },
      { to: "/services", label: "服务", key: "services" },
      { to: "/models", label: "模型", key: "models" },
      { to: "/files", label: "文件", key: "files" },
      { to: "/prompt", label: "系统提示词", key: "prompt" },
      { to: "/invites", label: "邀请码", key: "invites" }
    ],
    []
  );

  function getNavTarget(key: AdminSection) {
    if (key === "overview") {
      return adminRootPath;
    }

    return adminRootPath === "/" ? `/${key}` : `${adminRootPath}/${key}`;
  }

  async function refreshOverview() {
    setLoading(true);
    setError(null);

    try {
      const nextOverview = await getAdminOverview();
      setOverview(nextOverview);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "加载管理状态失败。");
    } finally {
      setLoading(false);
    }
  }

  async function loadPrompt(fromReload: boolean) {
    if (fromReload) {
      setPromptReloading(true);
    } else {
      setPromptLoading(true);
    }
    setError(null);

    try {
      const nextPrompt = await getAdminPrompt();
      setPromptData(nextPrompt);
      setPromptDraft(nextPrompt.prompt);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "加载系统提示词失败。");
    } finally {
      if (fromReload) {
        setPromptReloading(false);
      } else {
        setPromptLoading(false);
      }
    }
  }

  useEffect(() => {
    void refreshOverview();
  }, []);

  useEffect(() => {
    if (section === "prompt" && !promptData && !promptLoading) {
      void loadPrompt(false);
    }
  }, [promptData, promptLoading, section]);

  async function handleToggle(target: "backend" | "tunnel", running: boolean) {
    setBusyTarget(target);
    setNotice(null);
    setError(null);

    try {
      await controlAdminService(target, running ? "stop" : "start");
      setNotice(running ? `${serviceLabels[target]}已停止。` : `${serviceLabels[target]}已启动。`);
      await refreshOverview();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "控制操作失败。");
    } finally {
      setBusyTarget(null);
    }
  }

  async function handleClearCache() {
    setClearingCache(true);
    setNotice(null);
    setError(null);

    try {
      const result = await clearAdminFileCache();
      setNotice(`已清理 ${result.cleared} 条 ZIP 上下文缓存。`);
      await refreshOverview();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "清理 ZIP 缓存失败。");
    } finally {
      setClearingCache(false);
    }
  }

  async function handlePromptSave(nextPrompt: string) {
    setPromptSaving(true);
    setError(null);

    try {
      const savedPrompt = await saveAdminPrompt(nextPrompt);
      setPromptData(savedPrompt);
      setPromptDraft(savedPrompt.prompt);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "保存系统提示词失败。");
    } finally {
      setPromptSaving(false);
    }
  }

  async function handlePromptReset() {
    setPromptResetting(true);
    setError(null);

    try {
      const resetPrompt = await resetAdminPrompt();
      setPromptData(resetPrompt);
      setPromptDraft(resetPrompt.prompt);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "重置系统提示词失败。");
    } finally {
      setPromptResetting(false);
    }
  }

  function renderLoadingCard(title: string, copy: string) {
    return (
      <section className="admin-card admin-card--wide">
        <p className="eyebrow">后台管理</p>
        <h2>{title}</h2>
        <p className="admin-card__copy">{copy}</p>
      </section>
    );
  }

  function renderSection() {
    if (loading) {
      return renderLoadingCard("正在读取管理状态", "稍等一下，后台服务、隧道、模型和 ZIP 状态正在汇总。");
    }

    if (!overview) {
      return (
        <section className="admin-card admin-card--wide">
          <p className="eyebrow">状态异常</p>
          <h2>当前没有可显示的数据</h2>
          <p className="admin-card__copy">请刷新页面后重试，如果问题持续存在，再检查后台服务是否正常启动。</p>
        </section>
      );
    }

    if (section === "services") {
      return <AdminOverview overview={overview} busyTarget={busyTarget} onToggle={handleToggle} />;
    }

    if (section === "models") {
      return <AdminModelsPanel providers={overview.models.providers} />;
    }

    if (section === "files") {
      return <AdminFilesPanel files={overview.files} clearing={clearingCache} onClear={handleClearCache} />;
    }

    if (section === "prompt") {
      if (promptLoading && !promptData) {
        return renderLoadingCard("正在加载系统提示词", "当前生效的后端系统提示词正在读取。");
      }

      if (!promptData) {
        return (
          <section className="admin-card admin-card--wide">
            <p className="eyebrow">系统提示词</p>
            <h2>系统提示词暂不可用</h2>
            <p className="admin-card__copy">请刷新页面或稍后再试。</p>
          </section>
        );
      }

      return (
        <AdminPromptPanel
          prompt={promptData}
          draft={promptDraft}
          loading={promptLoading}
          saving={promptSaving}
          resetting={promptResetting}
          reloading={promptReloading}
          onDraftChange={setPromptDraft}
          onSave={handlePromptSave}
          onReload={() => loadPrompt(true)}
          onReset={handlePromptReset}
        />
      );
    }

    if (section === "invites") {
      return <InviteCodesPanel />;
    }

    return (
      <div className="admin-panel-stack">
        <AdminOverview overview={overview} busyTarget={busyTarget} onToggle={handleToggle} />
        <AdminModelsPanel providers={overview.models.providers} />
        <AdminFilesPanel files={overview.files} clearing={clearingCache} onClear={handleClearCache} />
      </div>
    );
  }

  return (
    <main className="admin-console aurora-shell">
      <AuroraBackground testId="aurora-background" />
      <div className="admin-console__frame">
        <aside className="admin-console__sidebar glass-panel-card">
          <div className="admin-console__brand">
            <span className="brand-mark">Cipher Admin</span>
            <p className="eyebrow">独立管理入口</p>
            <h1>后端管理</h1>
            <p className="lead">这个入口和聊天前台分离，后续可以独立挂到 `admin` 二级域名。</p>
          </div>

          <nav className="admin-console__nav" aria-label="后台导航">
            {navItems.map((item) => (
              <NavLink
                key={item.key}
                to={getNavTarget(item.key)}
                end={item.key === "overview"}
                className={({ isActive }) =>
                  `admin-console__nav-link${isActive ? " admin-console__nav-link--active" : ""}`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="admin-console__sidebar-actions">
            <button type="button" className="secondary-button" onClick={() => void refreshOverview()}>
              <IconRefresh size={16} stroke={1.8} aria-hidden="true" />
              刷新状态
            </button>
            <button
              type="button"
              className="secondary-button secondary-button--soft"
              onClick={() => void onLogout()}
            >
              <IconArrowLeft size={16} stroke={1.8} aria-hidden="true" />
              退出登录
            </button>
          </div>
        </aside>

        <section className="admin-console__content">
          {activeError ? (
            <p className="status-banner status-banner--error" role="alert">
              {activeError}
            </p>
          ) : null}

          {notice ? (
            <p className="admin-notice-banner" role="status">
              {notice}
            </p>
          ) : null}

          {renderSection()}
        </section>
      </div>
    </main>
  );
}

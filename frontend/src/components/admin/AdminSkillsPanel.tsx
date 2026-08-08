import { useEffect, useState } from "react";
import { IconCheck, IconCloudDownload, IconRefresh, IconShieldLock, IconToggleLeft, IconToggleRight } from "@tabler/icons-react";
import { getSkills, reviewSkill, rollbackSkill, syncSkills, toggleSkill } from "../../lib/api";
import type { SkillPackage } from "../../types";

export function AdminSkillsPanel() {
  const [items, setItems] = useState<SkillPackage[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  async function load() { setLoading(true); try { setItems((await getSkills()).items); } finally { setLoading(false); } }
  useEffect(() => { void load(); }, []);
  async function sync() { setBusy(-1); try { const result = await syncSkills(); setItems(result.items); setMessage(`已同步 ${result.added} 个内置 Skill`); } finally { setBusy(null); } }
  async function toggle(item: SkillPackage) { setBusy(item.id); try { const next = await toggleSkill(item.id, !item.enabled); setItems(current => current.map(value => value.id === next.id ? next : value)); } finally { setBusy(null); } }
  async function review(item: SkillPackage, status: "verified" | "blocked") { setBusy(item.id); try { const next = await reviewSkill(item.id, status); setItems(current => current.map(value => value.id === next.id ? next : value)); setMessage(status === "verified" ? `${item.name} 已通过审核` : `${item.name} 已阻止`); } finally { setBusy(null); } }
  async function rollback(item: SkillPackage) { setBusy(item.id); try { const next = await rollbackSkill(item.id); await load(); setMessage(`${item.name} 已回滚到 v${next.version}`); } finally { setBusy(null); } }
  return <div className="admin-panel-stack">
    <section className="admin-card admin-card--wide"><div className="admin-card__header"><div><p className="eyebrow">Skill Store</p><h2>安全分析 Skill</h2><p className="admin-card__copy">管理经过审核的分析方法、工具权限和版本。远程 Skill 进入前必须审核。</p></div><div className="admin-card__actions"><button className="secondary-button" onClick={() => void load()}><IconRefresh size={16}/>刷新</button><button className="primary-button" onClick={() => void sync()} disabled={busy !== null}><IconCloudDownload size={16}/>同步内置 Skill</button></div></div>{message ? <p className="admin-notice-banner" role="status">{message}</p> : null}</section>
    {loading ? <section className="admin-card admin-card--wide"><p>正在读取 Skill 清单…</p></section> : items.map(item => <section className="admin-card admin-card--wide" key={item.id}><div className="admin-card__header"><div><p className="eyebrow">{item.key} · v{item.version} · {item.releaseStatus ?? "draft"}</p><h2>{item.name}</h2><p className="admin-card__copy">{item.description}</p></div><div className="admin-card__actions">{item.reviewStatus === "needs_review" ? <><button className="secondary-button" disabled={busy !== null || item.signature?.status !== "verified"} onClick={() => void review(item, "verified")}>审核通过</button><button className="secondary-button" disabled={busy !== null} onClick={() => void review(item, "blocked")}>阻止</button></> : null}<button className="secondary-button" disabled={busy !== null} onClick={() => void rollback(item)}>回滚版本</button><button className="secondary-button" disabled={busy !== null || item.reviewStatus !== "verified"} onClick={() => void toggle(item)}>{item.enabled ? <IconToggleRight size={18}/> : <IconToggleLeft size={18}/>} {item.reviewStatus !== "verified" ? "审核后可启用" : item.enabled ? "已启用" : "启用"}</button></div></div><div className="admin-skill-meta"><span><IconCheck size={15}/> {item.reviewStatus === "verified" ? "安全扫描通过" : item.reviewStatus === "blocked" ? "已阻止：高风险" : "需要人工审核"}</span><span><IconShieldLock size={15}/> {item.permissions.length ? item.permissions.join("、") : "无外部工具权限"}</span><span>签名：{item.signature?.status === "verified" ? "有效" : "无效或缺失"}</span><span>来源：{item.source === "github" ? "GitHub" : "Cipher 内置"}</span></div></section>)}
    {!loading && items.length === 0 ? <section className="admin-card admin-card--wide"><p>暂无 Skill。点击“同步内置 Skill”开始。</p></section> : null}
  </div>;
}

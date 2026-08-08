import { useEffect, useMemo, useRef, useState } from "react";
import {
  IconArrowUpRight,
  IconCheck,
  IconClock,
  IconDownload,
  IconHistory,
  IconLoader2,
  IconPackage,
  IconPlayerPlay,
  IconRefresh,
  IconSearch,
  IconShieldCheck,
  IconSparkles,
  IconTrash,
  IconX
} from "@tabler/icons-react";
import cipherMark from "../assets/cipher-mark.svg";
import { PixelBlast } from "../components/PixelBlast";
import { createSkillInitialInput, SkillInputForm } from "../components/skills/SkillInputForm";
import { getSkillHistory, getSkills, installSkill, runSkill, uninstallSkill } from "../lib/api";
import { useTheme } from "../theme";
import type { SkillPackage, SkillRun } from "../types";

const categoryLabels: Record<string, string> = {
  "security-operations": "安全运营",
  "threat-intelligence": "威胁情报",
  "malware-analysis": "恶意软件分析",
  "incident-response": "事件响应",
  "detection-engineering": "检测工程",
  "vulnerability-management": "漏洞管理",
  "digital-forensics": "数字取证",
  "cloud-security": "云安全"
};

const pricingLabels: Record<string, string> = {
  included: "当前套餐内含",
  free: "免费",
  professional: "专业版",
  enterprise: "企业版"
};

type Notice = { kind: "success" | "error"; message: string };

function runStatusLabel(status: string) {
  if (status === "completed") return "已完成";
  if (status === "failed") return "失败";
  if (status === "running") return "运行中";
  return status;
}

function formatRunDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric" }).format(date);
}

export function SkillsPage({ onBack }: { onBack: () => void }) {
  const { theme } = useTheme();
  const [items, setItems] = useState<SkillPackage[]>([]);
  const [history, setHistory] = useState<SkillRun[]>([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [source, setSource] = useState("");
  const [onlyInstalled, setOnlyInstalled] = useState(false);
  const [selected, setSelected] = useState<SkillPackage | null>(null);
  const [input, setInput] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [catalogError, setCatalogError] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [permissionsApproved, setPermissionsApproved] = useState(false);
  const detailDialogRef = useRef<HTMLElement | null>(null);
  const detailTriggerRef = useRef<HTMLButtonElement | null>(null);

  async function load() {
    setLoading(true);
    setCatalogError(false);
    setNotice(null);
    try {
      const catalog = await getSkills();
      setItems(catalog.items.filter(item => item.reviewStatus === "verified" && item.enabled));
      try {
        setHistory((await getSkillHistory()).items);
      } catch {
        setHistory([]);
      }
    } catch (error) {
      setCatalogError(true);
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Skill 市场加载失败" });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!selected) return;
    const previousOverflow = document.body.style.overflow;
    const animationFrame = window.requestAnimationFrame(() => detailDialogRef.current?.focus());
    document.body.style.overflow = "hidden";

    function handleKeyDown(event: KeyboardEvent) {
      const dialog = detailDialogRef.current;
      if (event.key === "Escape") {
        event.preventDefault();
        setSelected(null);
        window.setTimeout(() => detailTriggerRef.current?.focus(), 0);
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )).filter(element => !element.hasAttribute("hidden"));
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(animationFrame);
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [selected]);

  const categories = useMemo(() => Array.from(new Set(items.map(item => item.category))), [items]);
  const installedCount = useMemo(() => items.filter(item => item.installed).length, [items]);
  const visible = useMemo(() => items.filter(item => {
    const needle = query.trim().toLocaleLowerCase();
    const matchesQuery = !needle || [item.name, item.description, item.author, item.key, ...item.tags]
      .some(value => value.toLocaleLowerCase().includes(needle));
    return matchesQuery && (!category || item.category === category) && (!source || item.source === source) && (!onlyInstalled || item.installed);
  }), [items, query, category, source, onlyInstalled]);

  function choose(item: SkillPackage, trigger: HTMLButtonElement) {
    detailTriggerRef.current = trigger;
    setSelected(item);
    setInput(createSkillInitialInput(item));
    setPermissionsApproved(false);
  }

  function closeDetail() {
    setSelected(null);
    window.setTimeout(() => detailTriggerRef.current?.focus(), 0);
  }

  function update(next: SkillPackage) {
    setItems(current => current.map(item => item.id === next.id ? next : item));
    setSelected(current => current?.id === next.id ? next : current);
  }

  async function install(item: SkillPackage) {
    setBusy(item.id);
    try {
      update(await installSkill(item.id));
      setNotice({ kind: "success", message: `${item.name} 已安装` });
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "安装失败" });
    } finally {
      setBusy(null);
    }
  }

  async function uninstall(item: SkillPackage) {
    setBusy(item.id);
    try {
      update(await uninstallSkill(item.id));
      setNotice({ kind: "success", message: `${item.name} 已卸载` });
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "卸载失败" });
    } finally {
      setBusy(null);
    }
  }

  async function execute(item: SkillPackage) {
    setBusy(item.id);
    try {
      const result = await runSkill(item.id, input, { approvedPermissions: item.permissions });
      setNotice({ kind: "success", message: `Skill 已完成，运行记录 #${result.id}` });
      setHistory((await getSkillHistory()).items);
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "请检查输入后重试" });
    } finally {
      setBusy(null);
    }
  }

  function clearFilters() {
    setQuery("");
    setCategory("");
    setSource("");
    setOnlyInstalled(false);
  }

  return <main className="skill-market">
    <PixelBlast
      className="skill-market__pixel-background"
      variant="circle"
      pixelSize={theme === "dark" ? 6 : 7}
      color={theme === "dark" ? "#895EE8" : "#155EEF"}
      patternScale={3}
      patternDensity={theme === "dark" ? 1.28 : 1.22}
      pixelSizeJitter={0.45}
      enableRipples
      rippleSpeed={0.4}
      rippleThickness={0.12}
      rippleIntensityScale={1.35}
      liquid
      liquidStrength={0.012}
      liquidRadius={0.22}
      liquidWobbleSpeed={5}
      speed={0.45}
      edgeFade={0}
      transparent
    />
    <header className="skill-market__top-nav">
      <div className="skill-market__brand" aria-label="Cipher Intelligence">
        <span className="skill-market__brand-mark"><img src={cipherMark} alt="" /></span>
        <span>CIPHER</span>
      </div>
      <nav className="skill-market__nav-links" aria-label="Skills 页面导航">
        <a className="is-active" href="#skill-catalog" aria-current="page">技能市场</a>
        <button type="button" className={onlyInstalled ? "is-active" : ""} aria-pressed={onlyInstalled} onClick={() => setOnlyInstalled(value => !value)}>已安装</button>
        <a href="#skill-history">运行记录</a>
      </nav>
      <button className="skill-market__back" type="button" aria-label="返回对话" onClick={onBack}>
        <span>返回对话</span>
        <i aria-hidden="true"><IconArrowUpRight size={18}/></i>
      </button>
    </header>

    <div className="skill-market__shell">
      <section className="skill-market__hero" aria-labelledby="skills-title">
        <div className="skill-market__hero-copy">
          <p className="skill-market__hero-kicker">CIPHER SKILLS</p>
          <h1 id="skills-title">把安全流程，变成可复用技能。</h1>
          <p>安装经过审核的分析能力，在对话或案件中直接调用。</p>
        </div>
        <div className="skill-market__metrics" aria-label="Skills 概览">
          <section id="skill-history" className="skill-market__hero-history" aria-labelledby="skill-history-title">
            <div className="skill-market__hero-history-head">
              <h2 id="skill-history-title"><IconHistory size={17}/>最近运行</h2>
              <span>{history.length}</span>
            </div>
            <div className="skill-market__hero-history-list">
              {history.slice(0, 2).map(run => <div className="skill-market__hero-history-item" key={run.id}>
                <span><IconClock size={14}/></span>
                <div><strong>{items.find(item => item.id === run.skillId)?.name ?? `Skill #${run.skillId}`}</strong><small>#{run.id}{formatRunDate(run.createdAt) ? ` / ${formatRunDate(run.createdAt)}` : ""}</small></div>
                <em className={`is-${run.status}`}>{runStatusLabel(run.status)}</em>
              </div>)}
              {history.length === 0 ? <div className="skill-market__hero-history-empty"><IconClock size={17}/><p>暂无运行记录</p></div> : null}
            </div>
          </section>
          <div className="skill-market__metrics-grid">
            <div className="skill-market__metric"><strong>{loading ? "-" : items.length}</strong><span>可用技能</span></div>
            <div className="skill-market__metric"><strong>{loading ? "-" : installedCount}</strong><span>已安装</span></div>
            <div className="skill-market__metric"><strong>{loading ? "-" : history.length}</strong><span>近期运行</span></div>
          </div>
        </div>
      </section>

      {notice ? <div className={`skill-market__notice skill-market__notice--${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>
        {notice.kind === "error" ? <IconX size={18}/> : <IconCheck size={18}/>}<span>{notice.message}</span>
        {notice.kind === "error" && catalogError ? <button type="button" onClick={() => void load()}>重试</button> : null}
        <button className="skill-market__notice-close" type="button" aria-label="关闭提示" onClick={() => setNotice(null)}><IconX size={16}/></button>
      </div> : null}

      <section id="skill-catalog" className="skill-market__catalog" aria-labelledby="skill-catalog-title">
        <div className="skill-market__section-head">
          <div>
            <h2 id="skill-catalog-title">技能目录</h2>
            <p>{loading ? "正在读取目录" : `当前显示 ${visible.length} 个经过审核的 Skill`}</p>
          </div>
          <button className="skill-market__refresh" type="button" onClick={() => void load()} disabled={loading}>
            <IconRefresh size={17}/><span>刷新目录</span>
          </button>
        </div>

        <div className="skill-market__toolbar" aria-label="筛选技能">
          <label className="skill-market__search">
            <IconSearch size={18}/>
            <input value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索技能、作者或标签" aria-label="搜索技能"/>
            {query ? <button type="button" aria-label="清空搜索" onClick={() => setQuery("")}><IconX size={15}/></button> : null}
          </label>
          <label className="skill-market__category">
            <span>分类</span>
            <select value={category} onChange={event => setCategory(event.target.value)} aria-label="技能分类">
              <option value="">全部分类</option>
              {categories.map(value => <option key={value} value={value}>{categoryLabels[value] ?? value}</option>)}
            </select>
          </label>
          <label className="skill-market__category">
            <span>来源</span>
            <select value={source} onChange={event => setSource(event.target.value)} aria-label="技能来源">
              <option value="">全部来源</option>
              <option value="github">GitHub 开源生态</option>
              <option value="builtin">Cipher 内置</option>
            </select>
          </label>
        </div>

        <div className="skill-market__layout">
          <div className="skill-store-grid" aria-live="polite">
            {loading ? Array.from({ length: 4 }, (_, index) => <div className="skill-store-skeleton" aria-label="正在加载技能" key={index}>
              <span/><span/><span/><span/>
            </div>) : null}

            {!loading ? visible.map(item => <article className={`skill-store-item${item.featured ? " skill-store-item--featured" : ""}${selected?.id === item.id ? " skill-store-item--selected" : ""}`} key={item.id}>
              <button className="skill-store-item__select" type="button" aria-label={`查看 ${item.name} 详情`} onClick={event => choose(item, event.currentTarget)}>
                <div className="skill-store-item__head">
                  <span className="skill-store-item__icon">{item.featured ? <IconSparkles size={21}/> : <IconShieldCheck size={21}/>}</span>
                  <div><h3>{item.name}</h3><small>{item.author} / v{item.version}</small></div>
                  {item.featured ? <span className="skill-store-item__badge">推荐</span> : null}
                </div>
                <p>{item.description}</p>
                <div className="skill-store-item__tags">{item.tags.map(tag => <span key={tag}>{tag}</span>)}</div>
                <div className="skill-store-item__meta">
                  <span>{categoryLabels[item.category] ?? item.category}</span>
                  <span>{item.source === "github" ? "GitHub 开源" : "Cipher 内置"}</span>
                  <span>{item.installCount} 次安装 · {item.runCount} 次运行</span>
                </div>
              </button>
              <div className="skill-store-item__footer">
                <span className={item.entitlement.allowed ? "is-available" : "is-locked"}>{item.entitlement.allowed ? "当前套餐可用" : "需升级套餐"}</span>
                <button className={item.installed ? "skill-store-item__action skill-store-item__action--secondary" : "skill-store-item__action"} type="button" disabled={busy !== null || !item.entitlement.allowed} onClick={() => void (item.installed ? uninstall(item) : install(item))}>
                  {busy === item.id ? <IconLoader2 className="is-spinning" size={16}/> : item.installed ? <IconTrash size={16}/> : <IconDownload size={16}/>}
                  {item.installed ? "卸载" : "安装"}
                </button>
              </div>
            </article>) : null}

            {!loading && !catalogError && visible.length === 0 ? <div className="skill-market__empty-state">
              <span><IconPackage size={25}/></span>
              <h3>{items.length === 0 ? "暂无可用技能" : "没有找到匹配的技能"}</h3>
              <p>{items.length === 0 ? "已审核的 Skill 会显示在这里。" : "试试其他关键词，或清除当前筛选。"}</p>
              {items.length > 0 ? <button type="button" onClick={clearFilters}>清除筛选</button> : null}
            </div> : null}
          </div>

        </div>
      </section>
    </div>

    {selected ? <div className="skill-market__detail-modal-layer" onMouseDown={event => {
      if (event.target === event.currentTarget) closeDetail();
    }}>
      <section
        ref={detailDialogRef}
        className="skill-market__detail skill-market__detail-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={`skill-detail-title-${selected.id}`}
        tabIndex={-1}
      >
        <div className="skill-market__detail-head">
          <span><IconShieldCheck size={22}/></span>
          <div><small>已通过安全审核</small><h2 id={`skill-detail-title-${selected.id}`}>{selected.name}</h2></div>
          <button className="skill-market__detail-close" type="button" aria-label="关闭技能详情" onClick={closeDetail}><IconX size={15}/></button>
        </div>
        <p>{selected.description}</p>
        <dl>
          <div><dt>定价</dt><dd>{pricingLabels[selected.pricing] ?? selected.pricing}</dd></div>
          <div><dt>当前权益</dt><dd>{selected.entitlement.allowed ? "可使用" : `当前为 ${selected.entitlement.tier} 套餐`}</dd></div>
          {selected.upstreamVersion ? <div><dt>上游版本</dt><dd>{selected.upstreamVersion}</dd></div> : null}
          {selected.license ? <div><dt>开源许可</dt><dd>{selected.license}</dd></div> : null}
          <div className="skill-market__detail-wide"><dt>工具权限</dt><dd className="skill-market__permission-list">{selected.permissions.length ? selected.permissions.map(permission => <code key={permission}>{permission}</code>) : "无"}</dd></div>
          <div><dt>签名校验</dt><dd>{selected.signature?.status === "verified" ? "签名有效" : "未验证"}</dd></div>
          <div><dt>发布状态</dt><dd>{selected.releaseStatus === "published" ? "已发布" : selected.releaseStatus ?? "未知"}</dd></div>
          <div><dt>兼容性</dt><dd>Cipher {selected.compatibility?.cipher ?? ">=1.0"} / {selected.compatibility?.platforms?.join("、") ?? "Linux"}</dd></div>
          {selected.executionPolicy ? <div className="skill-market__detail-wide"><dt>执行限制</dt><dd>超时 {selected.executionPolicy.timeoutSeconds}s · 内存 {selected.executionPolicy.memoryMb}MB · CPU {selected.executionPolicy.cpuSeconds}s · 最大输出 {Math.round(selected.executionPolicy.maxOutputBytes / 1024)}KB · 最多 {selected.executionPolicy.retry.maxAttempts} 次尝试</dd></div> : null}
          <div className="skill-market__detail-wide"><dt>必填输入</dt><dd>{selected.inputs.required?.join("、") || "无"}</dd></div>
          {selected.sourceUrl ? <div><dt>生态来源</dt><dd><a href={selected.sourceUrl} target="_blank" rel="noreferrer">查看上游项目<IconArrowUpRight size={14}/></a></dd></div> : null}
        </dl>
        {selected.installed && selected.entitlement.allowed ? <>
          <SkillInputForm skill={selected} value={input} onChange={setInput}/>
          <label className="skill-market__permission-confirm"><input type="checkbox" checked={permissionsApproved} onChange={event => setPermissionsApproved(event.target.checked)}/><span>我确认本次执行需要上述网络、文件、命令和数据权限，且仅访问我的组织与用户数据。</span></label>
          <button className="skill-market__primary-action" type="button" disabled={busy !== null || !permissionsApproved} onClick={() => void execute(selected)}>
            {busy === selected.id ? <IconLoader2 className="is-spinning" size={17}/> : <IconPlayerPlay size={17}/>} 
            {busy === selected.id ? "执行中" : "运行 Skill"}
          </button>
        </> : <button className="skill-market__primary-action" type="button" disabled={busy !== null || !selected.entitlement.allowed} onClick={() => void install(selected)}>
          {busy === selected.id ? <IconLoader2 className="is-spinning" size={17}/> : <IconDownload size={17}/>} 
          {busy === selected.id ? "安装中" : selected.entitlement.allowed ? "安装 Skill" : "升级套餐后使用"}
        </button>}
      </section>
    </div> : null}
  </main>;
}

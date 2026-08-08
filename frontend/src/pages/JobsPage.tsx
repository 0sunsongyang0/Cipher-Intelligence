import { useEffect, useState } from "react";
import { IconArrowLeft, IconRefresh, IconX } from "@tabler/icons-react";
import { cancelJob, listJobs, retryJob } from "../lib/api";
import type { Job } from "../types";

const labels: Record<string, string> = { queued: "排队中", running: "执行中", succeeded: "已完成", failed: "失败", cancelled: "已取消" };
export function JobsPage({ onBack }: { onBack: () => void }) {
  const [items, setItems] = useState<Job[]>([]);
  const refresh = () => void listJobs().then((value) => setItems(value.items));
  useEffect(() => { refresh(); const timer = window.setInterval(refresh, 1500); return () => window.clearInterval(timer); }, []);
  return <main className="shell shell--centered jobs-page"><section className="panel jobs-panel">
    <header className="jobs-header"><button className="icon-button" onClick={onBack} aria-label="返回"><IconArrowLeft size={18}/></button><div><p className="eyebrow">任务中心</p><h1>异步任务</h1></div><button className="icon-button" onClick={refresh} aria-label="刷新"><IconRefresh size={18}/></button></header>
    <div className="jobs-list">{items.length === 0 ? <p className="muted">暂无任务</p> : items.map((job) => <article className="job-row" key={job.id}><div className="job-row__title"><strong>#{job.id} · {job.taskType}</strong><span>{labels[job.status]}</span></div><div className="job-progress"><i style={{ width: `${job.progress}%` }}/></div><small>{job.progressMessage || `${job.progress}%`}{job.errorMessage ? ` · ${job.errorMessage}` : ""}</small><div className="job-row__actions">{["queued", "running"].includes(job.status) && <button className="secondary-button" onClick={() => void cancelJob(job.id).then(refresh)}><IconX size={14}/>取消</button>}{["failed", "cancelled"].includes(job.status) && job.retryCount < job.maxRetries && <button className="secondary-button" onClick={() => void retryJob(job.id).then(refresh)}><IconRefresh size={14}/>重试</button>}</div></article>)}</div>
  </section></main>;
}

import { useEffect, useState } from "react";
import { IconBell, IconMessage, IconShare, IconUsers } from "@tabler/icons-react";
import { addInvestigationCaseComment, followInvestigationCase, getCaseCollaboration, shareInvestigationCase, type CaseCollaboration } from "../../lib/api";

export function CaseCollaborationPanel({ caseId }: { caseId: number }) {
  const [data, setData] = useState<CaseCollaboration | null>(null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  async function load() { try { setData(await getCaseCollaboration(caseId)); setError(null); } catch (e) { setError(e instanceof Error ? e.message : "协作信息加载失败"); } }
  useEffect(() => { void load(); }, [caseId]);
  async function share() {
    const username = window.prompt("输入要共享给的用户名"); if (!username?.trim()) return;
    const permission = window.confirm("允许对方编辑此案件？\n确定：可编辑；取消：仅查看") ? "editor" : "viewer";
    try { await shareInvestigationCase(caseId, username.trim(), permission); await load(); } catch (e) { setError(e instanceof Error ? e.message : "共享失败"); }
  }
  async function submit() {
    if (!comment.trim()) return;
    try { await addInvestigationCaseComment(caseId, comment.trim()); setComment(""); await load(); } catch (e) { setError(e instanceof Error ? e.message : "评论失败"); }
  }
  return <section className="case-detail__section case-collaboration">
    <div className="case-collaboration__head"><h3><IconUsers size={16}/>团队协作</h3><div><button onClick={() => void followInvestigationCase(caseId)} title="关注案件"><IconBell size={15}/>关注</button><button onClick={() => void share()}><IconShare size={15}/>共享</button></div></div>
    {error ? <p className="cases-error">{error}</p> : null}
    <div className="case-collaboration__people">{data?.access.length ? data.access.map(item => <span key={item.userId}>{item.displayName || item.username}<small>{item.permission === "editor" ? "可编辑" : "仅查看"}</small></span>) : <p>尚未单独共享；组织成员仍按角色访问。</p>}</div>
    <div className="case-collaboration__comments">{data?.comments.map(item => <article key={item.id}><strong>{item.author.displayName || item.author.username}</strong><p>{item.content}</p></article>)}</div>
    <div className="case-collaboration__composer"><textarea value={comment} onChange={e => setComment(e.target.value)} placeholder="添加评论，使用 @用户名 提醒成员" maxLength={4000}/><button onClick={() => void submit()} disabled={!comment.trim()}><IconMessage size={15}/>发送</button></div>
  </section>;
}

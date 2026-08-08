import { useCallback, useEffect, useState } from "react";
import { IconBell, IconBellOff, IconCheck, IconSettings, IconTrash, IconX } from "@tabler/icons-react";
import {
  deleteNotification, getNotificationPreferences, listNotifications, markAllNotificationsRead,
  markNotificationRead, updateNotificationPreference, type NotificationItem, type NotificationPreference
} from "../../lib/api";

const LABELS: Record<string, string> = {
  cape_completed: "CAPE 完成", model_failed: "模型失败", mention: "@提及", sla_warning: "SLA 预警",
  quota_low: "额度不足", subscription_expiring: "订阅到期", threat_intel_updated: "情报更新",
  case_shared: "Case 共享", case_comment: "Case 评论", case_assigned: "Case 分配"
};

export function NotificationCenter() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [filter, setFilter] = useState("");
  const [preferences, setPreferences] = useState<NotificationPreference[] | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await listNotifications(filter);
      setItems(result.items); setUnreadCount(result.unreadCount);
    } catch {
      setItems([]); setUnreadCount(0);
    }
  }, [filter]);

  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 30000); return () => window.clearInterval(timer); }, [load]);

  async function openItem(item: NotificationItem) {
    if (!item.readAt) await markNotificationRead(item.id);
    if (item.resourceUrl) window.location.assign(item.resourceUrl);
    else await load();
  }

  async function toggleSettings() {
    if (preferences) { setPreferences(null); return; }
    const organizationId = items[0]?.organizationId;
    if (organizationId) setPreferences((await getNotificationPreferences(organizationId)).items);
  }

  async function togglePreference(item: NotificationPreference, key: "inApp" | "email" | "webPush") {
    const organizationId = items[0]?.organizationId;
    if (!organizationId) return;
    const updated = await updateNotificationPreference(organizationId, { ...item, [key]: !item[key] });
    setPreferences(previous => previous?.map(value => value.type === updated.type ? updated : value) ?? null);
  }

  return <div className="notification-center">
    <button type="button" className="bomb-shell__icon-button bomb-shell__icon-button--header notification-center__trigger"
      aria-label={`通知${unreadCount ? `，${unreadCount} 条未读` : ""}`} aria-expanded={open} onClick={() => setOpen(value => !value)}>
      <IconBell size={18} stroke={1.8}/>{unreadCount ? <span>{unreadCount > 99 ? "99+" : unreadCount}</span> : null}
    </button>
    {open ? <section className="notification-center__panel" aria-label="通知中心">
      <header><div><small>CIPHER / ALERTS</small><h2>通知中心</h2></div><div>
        <button onClick={() => void toggleSettings()} aria-label="通知偏好"><IconSettings size={17}/></button>
        <button onClick={() => setOpen(false)} aria-label="关闭通知中心"><IconX size={18}/></button>
      </div></header>
      {preferences ? <div className="notification-center__preferences">
        <div className="notification-center__preference-head"><span>类型</span><span>站内</span><span>邮件</span><span>推送</span></div>
        {preferences.map(item => <div key={item.type}><strong>{LABELS[item.type] ?? item.type}</strong>
          {(["inApp", "email", "webPush"] as const).map(key => <button key={key} className={item[key] ? "is-on" : ""}
            onClick={() => void togglePreference(item, key)} aria-label={`${LABELS[item.type] ?? item.type} ${key}`}>{item[key] ? "开" : "关"}</button>)}</div>)}
      </div> : <>
        <div className="notification-center__toolbar"><select value={filter} onChange={event => setFilter(event.target.value)} aria-label="按类型筛选">
          <option value="">全部类型</option>{Object.entries(LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select><button disabled={!unreadCount} onClick={async () => { await markAllNotificationsRead(); await load(); }}><IconCheck size={15}/>全部已读</button></div>
        <div className="notification-center__list">{items.length ? items.map(item => <article key={item.id} className={item.readAt ? "" : "is-unread"}>
          <button className="notification-center__content" onClick={() => void openItem(item)}><span>{LABELS[item.type] ?? item.type}</span><strong>{item.title}</strong>{item.body ? <p>{item.body}</p> : null}<time>{new Date(item.createdAt).toLocaleString()}</time></button>
          <button className="notification-center__delete" aria-label="删除通知" onClick={async () => { await deleteNotification(item.id); await load(); }}><IconTrash size={15}/></button>
        </article>) : <div className="notification-center__empty"><span><IconBellOff size={22} stroke={1.6}/></span><strong>暂无通知</strong><small>新的安全动态和任务提醒会显示在这里</small></div>}</div>
      </>}
    </section> : null}
  </div>;
}

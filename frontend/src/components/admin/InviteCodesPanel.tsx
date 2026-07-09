import { type FormEvent, useEffect, useState } from "react";

import {
  createAdminInvite,
  deleteAdminInvite,
  getAdminInvites,
  toggleAdminInvite
} from "../../lib/api";
import type { AdminInviteItem } from "../../types";

type InviteFormState = {
  code: string;
  label: string;
  maxUses: string;
  expiresAt: string;
  isActive: boolean;
};

const INITIAL_FORM_STATE: InviteFormState = {
  code: "",
  label: "",
  maxUses: "",
  expiresAt: "",
  isActive: true
};

function formatDate(value: string | null): string {
  if (!value) {
    return "未设置";
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("zh-CN", { hour12: false });
}

function getRemainingCapacity(item: AdminInviteItem): string {
  if (item.maxUses === null) {
    return "不限";
  }

  return String(Math.max(0, item.maxUses - item.usedCount));
}

export function InviteCodesPanel() {
  const [items, setItems] = useState<AdminInviteItem[]>([]);
  const [form, setForm] = useState<InviteFormState>(INITIAL_FORM_STATE);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [busyInviteId, setBusyInviteId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    void loadInvites();
  }, []);

  async function loadInvites() {
    setLoading(true);
    setError(null);

    try {
      const payload = await getAdminInvites();
      setItems(payload.items);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "加载邀请码失败。");
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setNotice(null);

    try {
      await createAdminInvite({
        code: form.code.trim(),
        label: form.label.trim(),
        maxUses: form.maxUses.trim() ? Number(form.maxUses) : null,
        expiresAt: form.expiresAt ? new Date(form.expiresAt).toISOString() : null,
        isActive: form.isActive
      });
      setForm(INITIAL_FORM_STATE);
      setNotice("邀请码已创建。");
      await loadInvites();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "创建邀请码失败。");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleToggle(inviteId: number) {
    setBusyInviteId(inviteId);
    setError(null);
    setNotice(null);

    try {
      const updated = await toggleAdminInvite(inviteId);
      setNotice(updated.isActive ? "邀请码已启用。" : "邀请码已停用。");
      await loadInvites();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "切换邀请码状态失败。");
    } finally {
      setBusyInviteId(null);
    }
  }

  async function handleDelete(inviteId: number) {
    setBusyInviteId(inviteId);
    setError(null);
    setNotice(null);

    try {
      await deleteAdminInvite(inviteId);
      setNotice("邀请码已删除。");
      await loadInvites();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "删除邀请码失败。");
    } finally {
      setBusyInviteId(null);
    }
  }

  return (
    <div className="admin-panel-stack">
      <section className="admin-card admin-card--wide">
        <p className="eyebrow">邀请码</p>
        <h2>邀请码管理</h2>
        <p className="admin-card__copy">创建、停用或删除邀请码，新的账号注册会立即使用这里的规则。</p>

        {error ? (
          <p className="status-banner status-banner--error" role="alert">
            {error}
          </p>
        ) : null}

        {notice ? (
          <p className="admin-notice-banner" role="status">
            {notice}
          </p>
        ) : null}

        <form className="admin-panel-stack" onSubmit={handleCreate}>
          <div className="field">
            <label htmlFor="invite-code">邀请码</label>
            <input
              id="invite-code"
              name="code"
              type="text"
              value={form.code}
              onChange={(event) => setForm((current) => ({ ...current, code: event.target.value }))}
              placeholder="请输入邀请码"
              disabled={submitting}
            />
          </div>

          <div className="field">
            <label htmlFor="invite-label">标签</label>
            <input
              id="invite-label"
              name="label"
              type="text"
              value={form.label}
              onChange={(event) => setForm((current) => ({ ...current, label: event.target.value }))}
              placeholder="例如：7 月批次"
              disabled={submitting}
            />
          </div>

          <div className="field">
            <label htmlFor="invite-max-uses">最多使用次数</label>
            <input
              id="invite-max-uses"
              name="maxUses"
              type="number"
              min="1"
              inputMode="numeric"
              value={form.maxUses}
              onChange={(event) => setForm((current) => ({ ...current, maxUses: event.target.value }))}
              placeholder="留空表示不限"
              disabled={submitting}
            />
          </div>

          <div className="field">
            <label htmlFor="invite-expires-at">过期时间</label>
            <input
              id="invite-expires-at"
              name="expiresAt"
              type="datetime-local"
              value={form.expiresAt}
              onChange={(event) => setForm((current) => ({ ...current, expiresAt: event.target.value }))}
              disabled={submitting}
            />
          </div>

          <label className="status-pill">
            <input
              type="checkbox"
              checked={form.isActive}
              onChange={(event) => setForm((current) => ({ ...current, isActive: event.target.checked }))}
              disabled={submitting}
            />
            默认启用
          </label>

          <div>
            <button
              type="submit"
              className="primary-button"
              disabled={submitting || form.code.trim().length === 0}
            >
              {submitting ? "创建中..." : "创建邀请码"}
            </button>
          </div>
        </form>
      </section>

      <section className="admin-card admin-card--wide">
        <div className="admin-card__header">
          <div>
            <p className="eyebrow">列表</p>
            <h2>现有邀请码</h2>
          </div>
          <button type="button" className="secondary-button" onClick={() => void loadInvites()} disabled={loading}>
            刷新列表
          </button>
        </div>

        {loading ? <p className="admin-card__copy">正在加载邀请码...</p> : null}

        {!loading && items.length === 0 ? (
          <p className="admin-card__copy">暂无邀请码，先创建一个新的邀请码。</p>
        ) : null}

        {!loading && items.length > 0
          ? items.map((item) => (
              <section key={item.id} className="admin-card">
                <div className="admin-card__header">
                  <div>
                    <p className="eyebrow">{item.label || "未命名批次"}</p>
                    <h2>{item.code}</h2>
                  </div>
                  <span
                    className={`admin-status-chip ${item.isActive ? "admin-status-chip--ready" : "admin-status-chip--idle"}`}
                  >
                    {item.isActive ? "已启用" : "已停用"}
                  </span>
                </div>

                <dl className="admin-meta-list">
                  <div>
                    <dt>已使用</dt>
                    <dd>{item.usedCount}</dd>
                  </div>
                  <div>
                    <dt>最多使用</dt>
                    <dd>{item.maxUses ?? "不限"}</dd>
                  </div>
                  <div>
                    <dt>剩余可用</dt>
                    <dd>{getRemainingCapacity(item)}</dd>
                  </div>
                  <div>
                    <dt>过期时间</dt>
                    <dd>{formatDate(item.expiresAt)}</dd>
                  </div>
                </dl>

                <p className="admin-card__meta">创建时间：{formatDate(item.createdAt)}</p>

                <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="admin-action-button admin-action-button--ghost"
                    onClick={() => void handleToggle(item.id)}
                    disabled={busyInviteId === item.id}
                  >
                    {item.isActive ? "停用" : "启用"}
                  </button>
                  <button
                    type="button"
                    className="admin-action-button admin-action-button--danger"
                    onClick={() => void handleDelete(item.id)}
                    disabled={busyInviteId === item.id}
                  >
                    删除
                  </button>
                </div>
              </section>
            ))
          : null}
      </section>
    </div>
  );
}

import { IconArchive, IconTrash } from "@tabler/icons-react";
import type { AdminOverview } from "../../types";

export function AdminFilesPanel({
  files,
  clearing,
  onClear,
}: {
  files: AdminOverview["files"];
  clearing: boolean;
  onClear: () => Promise<void>;
}) {
  return (
    <section className="admin-card admin-card--wide">
      <div className="admin-card__header">
        <div>
          <p className="eyebrow">文件</p>
          <h2>文件与 ZIP</h2>
        </div>
        <IconArchive size={18} stroke={1.8} aria-hidden="true" />
      </div>

      <dl className="admin-meta-list">
        <div>
          <dt>单次上传上限</dt>
          <dd>{files.uploadLimit} 个文件</dd>
        </div>
        <div>
          <dt>ZIP 解析</dt>
          <dd>{files.zipEnabled ? "已启用" : "未启用"}</dd>
        </div>
        <div>
          <dt>ZIP 上下文缓存</dt>
          <dd>{files.zipContextCount} 条</dd>
        </div>
      </dl>

      <button
        type="button"
        className="admin-action-button admin-action-button--ghost"
        disabled={clearing}
        onClick={() => void onClear()}
      >
        <IconTrash size={16} stroke={1.8} aria-hidden="true" />
        {clearing ? "正在清理..." : "清空 ZIP 缓存"}
      </button>
    </section>
  );
}

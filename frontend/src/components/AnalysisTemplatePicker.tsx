import {
  getDeepSeekModelLabel,
  resolveDeepSeekModelId,
  type AnalysisTemplate
} from "../types";
import { IconX } from "@tabler/icons-react";

export function AnalysisTemplatePicker({ templates, title, onSelect, onClose }: { templates: AnalysisTemplate[]; title: string; onSelect: (templateId: number | null) => void; onClose: () => void }) {
  return <div className="template-picker__backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="template-picker" role="dialog" aria-modal="true" aria-label={title}>
      <header><div><small>CIPHER ANALYSIS</small><h2>{title}</h2></div><button onClick={onClose} aria-label="关闭模板选择"><IconX size={20} stroke={1.8}/></button></header>
      <div className="template-picker__grid">
        <button className="template-picker__item is-blank" onClick={() => onSelect(null)}><strong>空白分析</strong><span>不加载预设提示词和检查清单</span></button>
        {templates.map(item => <button className="template-picker__item" key={item.id} onClick={() => onSelect(item.id)}>
          <span className="template-picker__meta">v{item.version} · {getDeepSeekModelLabel(resolveDeepSeekModelId(item.recommendedModel))}</span><strong>{item.name}</strong><span>{item.scenario}</span><small>{item.checklist.length} 项检查 · {item.requiredSkills.length} 个 Skill</small>
        </button>)}
      </div>
    </section>
  </div>;
}

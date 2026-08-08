import type { SkillInputProperty, SkillPackage } from "../../types";

export type SkillInputValues = Record<string, unknown>;

export function createSkillInitialInput(skill: SkillPackage, seed: SkillInputValues = {}): SkillInputValues {
  const values: SkillInputValues = {};
  for (const [name, property] of Object.entries(skill.inputs.properties ?? {})) {
    values[name] = seed[name] ?? property.default ?? (property.type === "array" ? [] : property.type === "object" ? {} : property.type === "boolean" ? false : "");
  }
  return { ...values, ...seed };
}

function textValue(property: SkillInputProperty, value: unknown): string {
  if (property.type === "array") return Array.isArray(value) ? value.join("\n") : "";
  if (property.type === "object") return JSON.stringify(value ?? {}, null, 2);
  return String(value ?? "");
}

export function SkillInputForm({ skill, value, onChange }: {
  skill: SkillPackage; value: SkillInputValues; onChange: (value: SkillInputValues) => void;
}) {
  const required = new Set(skill.inputs.required ?? []);
  function update(name: string, property: SkillInputProperty, raw: string | boolean) {
    let next: unknown = raw;
    if (property.type === "array") next = String(raw).split(/\r?\n/u).map(item => item.trim()).filter(Boolean);
    if (property.type === "number") next = Number(raw);
    if (property.type === "object") {
      try { next = JSON.parse(String(raw)) as unknown; } catch { next = raw; }
    }
    onChange({ ...value, [name]: next });
  }
  return <div className="skill-input-form">{Object.entries(skill.inputs.properties ?? {}).map(([name, property]) => {
    const label = `${property.label ?? name}${required.has(name) ? " *" : ""}`;
    if (property.type === "boolean") return <label key={name} className="skill-input-form__check"><input type="checkbox" checked={Boolean(value[name])} onChange={event => update(name, property, event.target.checked)}/><span>{label}</span></label>;
    if (property.type === "array" || property.type === "object") return <label key={name}><span>{label}</span>{property.description ? <small>{property.description}</small> : null}<textarea rows={property.type === "object" ? 9 : 5} value={textValue(property, value[name])} onChange={event => update(name, property, event.target.value)}/></label>;
    return <label key={name}><span>{label}</span>{property.description ? <small>{property.description}</small> : null}<input type={property.type === "number" ? "number" : "text"} value={textValue(property, value[name])} onChange={event => update(name, property, event.target.value)}/></label>;
  })}</div>;
}

from __future__ import annotations

from dataclasses import asdict, dataclass
from html import escape
from io import BytesIO
import json
from pathlib import Path
import re
from typing import Any

import yaml


@dataclass(frozen=True)
class RuleValidationResult:
    valid: bool
    errors: list[str]
    warnings: list[str]
    conversions: dict[str, str]
    attack_techniques: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sigma_keywords(payload: dict[str, Any]) -> list[str]:
    detection = payload.get("detection")
    if not isinstance(detection, dict):
        return []
    values: list[str] = []
    for key, value in detection.items():
        if key == "condition":
            continue
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                values.append(candidate.strip())
            elif isinstance(candidate, dict):
                values.extend(str(item).strip() for item in candidate.values() if str(item).strip())
    return list(dict.fromkeys(values))[:30]


def _sigma_attack_techniques(payload: dict[str, Any]) -> list[str]:
    tags = payload.get("tags")
    if not isinstance(tags, list):
        return []
    techniques: list[str] = []
    for tag in tags:
        match = re.search(r"attack\.t(\d{4}(?:\.\d{3})?)", str(tag), flags=re.IGNORECASE)
        if match:
            techniques.append(f"T{match.group(1)}")
    return list(dict.fromkeys(techniques))


def _build_siem_conversions(keywords: list[str]) -> dict[str, str]:
    if not keywords:
        return {}
    json_values = [json.dumps(value, ensure_ascii=False) for value in keywords]
    splunk = "index=* (" + " OR ".join(json_values) + ")"
    elastic = "process.command_line: (" + " or ".join(json_values) + ")"
    sentinel = "DeviceProcessEvents\n| where ProcessCommandLine has_any (" + ", ".join(json_values) + ")"
    return {"splunk": splunk, "elastic": elastic, "sentinel": sentinel}


def validate_sigma(content: str) -> RuleValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        payload = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return RuleValidationResult(False, [f"YAML syntax error: {exc}"], [], {}, [])
    if not isinstance(payload, dict):
        return RuleValidationResult(False, ["Sigma rule must be a YAML object."], [], {}, [])
    for field in ("title", "logsource", "detection"):
        if not payload.get(field):
            errors.append(f"Missing required Sigma field: {field}")
    detection = payload.get("detection")
    if isinstance(detection, dict):
        if not detection.get("condition"):
            errors.append("Sigma detection.condition is required.")
        if len(detection) <= 1:
            warnings.append("Sigma detection has no selection block to evaluate.")
    elif "detection" not in errors:
        errors.append("Sigma detection must be an object.")
    if payload.get("status") == "experimental":
        warnings.append("Rule is still marked experimental.")
    keywords = _sigma_keywords(payload)
    if not keywords:
        warnings.append("No portable keyword selectors were found for SIEM conversion or log testing.")
    return RuleValidationResult(
        valid=not errors,
        errors=errors,
        warnings=warnings,
        conversions=_build_siem_conversions(keywords),
        attack_techniques=_sigma_attack_techniques(payload),
    )


def validate_yara(content: str) -> RuleValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        import yara

        yara.compile(source=content)
    except ImportError:
        warnings.append("yara-python is unavailable; only structural checks were performed.")
        if not re.search(r"\brule\s+[A-Za-z_][A-Za-z0-9_]*\s*\{", content):
            errors.append("YARA rule declaration was not found.")
        if "condition:" not in content:
            errors.append("YARA condition section is required.")
    except Exception as exc:
        errors.append(f"YARA compile error: {exc}")
    if "REVIEW_REQUIRED" in content:
        warnings.append("Rule contains a REVIEW_REQUIRED placeholder.")
    techniques = list(dict.fromkeys(re.findall(r"T\d{4}(?:\.\d{3})?", content)))
    return RuleValidationResult(not errors, errors, warnings, {}, techniques)


def validate_rule(rule_type: str, content: str) -> RuleValidationResult:
    if rule_type == "sigma":
        return validate_sigma(content)
    if rule_type == "yara":
        return validate_yara(content)
    return RuleValidationResult(False, [f"Unsupported rule type: {rule_type}"], [], {}, [])


def test_rule(rule_type: str, content: str, artifacts: list[tuple[str, bytes]]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    if rule_type == "yara":
        import yara

        compiled = yara.compile(source=content)
        for name, data in artifacts:
            matches = [str(match) for match in compiled.match(data=data)]
            results.append({"name": name, "matched": bool(matches), "matches": matches})
    elif rule_type == "sigma":
        payload = yaml.safe_load(content)
        keywords = _sigma_keywords(payload if isinstance(payload, dict) else {})
        for name, data in artifacts:
            text = data.decode("utf-8", errors="ignore").casefold()
            matches = [keyword for keyword in keywords if keyword.casefold() in text]
            results.append({"name": name, "matched": bool(matches), "matches": matches})
    else:
        raise ValueError(f"Unsupported rule type: {rule_type}")
    matched = sum(bool(item["matched"]) for item in results)
    return {
        "totalArtifacts": len(results),
        "matchedArtifacts": matched,
        "falsePositiveCount": 0,
        "results": results,
    }


def build_rule_report_html(rule: dict[str, Any]) -> bytes:
    validation = rule.get("validation") if isinstance(rule.get("validation"), dict) else {}
    tests = rule.get("testRuns") if isinstance(rule.get("testRuns"), list) else []
    errors = validation.get("errors") if isinstance(validation.get("errors"), list) else []
    warnings = validation.get("warnings") if isinstance(validation.get("warnings"), list) else []
    conversions = validation.get("conversions") if isinstance(validation.get("conversions"), dict) else {}
    test_rows = "".join(
        f"<tr><td>{escape(str(item.get('createdAt', '')))}</td><td>{item.get('matchedArtifacts', 0)} / {item.get('totalArtifacts', 0)}</td><td>{item.get('falsePositiveCount', 0)}</td></tr>"
        for item in tests
    ) or '<tr><td colspan="3">No test runs</td></tr>'
    conversion_blocks = "".join(
        f"<h3>{escape(name.title())}</h3><pre>{escape(str(query))}</pre>"
        for name, query in conversions.items()
    ) or "<p>No SIEM conversion available.</p>"
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{escape(str(rule.get('title', 'Detection rule report')))}</title>
<style>body{{font:14px/1.65 system-ui,sans-serif;max-width:980px;margin:40px auto;padding:0 28px;color:#18202b}}h1{{margin-bottom:4px}}.meta{{color:#667085}}.status{{display:inline-block;padding:3px 9px;border-radius:99px;background:#eef2ff}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border:1px solid #d9dee8;text-align:left}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;padding:14px;border-radius:8px}}.ok{{color:#147d52}}.bad{{color:#b42318}}</style></head>
<body><h1>{escape(str(rule.get('title', 'Detection rule report')))}</h1>
<p class="meta">Case #{rule.get('caseId')} · {escape(str(rule.get('ruleType', '')).upper())} · Version {rule.get('version')} · <span class="status">{escape(str(rule.get('status', 'draft')))}</span></p>
<h2>验证结论</h2><p class="{'ok' if validation.get('valid') else 'bad'}">{'VALID' if validation.get('valid') else 'INVALID'}</p>
<h3>错误</h3><ul>{''.join(f'<li>{escape(str(item))}</li>' for item in errors) or '<li>None</li>'}</ul>
<h3>警告</h3><ul>{''.join(f'<li>{escape(str(item))}</li>' for item in warnings) or '<li>None</li>'}</ul>
<h2>目标 SIEM 转换</h2>{conversion_blocks}
<h2>测试记录</h2><table><thead><tr><th>时间</th><th>命中</th><th>误报</th></tr></thead><tbody>{test_rows}</tbody></table>
<h2>规则内容</h2><pre>{escape(str(rule.get('content', '')))}</pre>
<p class="meta">Generated by Cipher. Analyst review is required before production deployment.</p></body></html>"""
    return html.encode("utf-8")


def build_rule_report_pdf(rule: dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle

    font_path = Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf")
    font_name = "CipherCJK"
    if font_name not in pdfmetrics.getRegisteredFontNames() and font_path.exists():
        pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
    if font_name not in pdfmetrics.getRegisteredFontNames():
        font_name = "Helvetica"
    latin_font = "CipherLatin"
    mono_font = "CipherMono"
    if latin_font not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(latin_font, "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    if mono_font not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(mono_font, "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"))

    def mixed_markup(value: Any) -> str:
        parts = re.split(r"([\x20-\x7e]+)", str(value))
        return "".join(
            f'<font name="{latin_font}">{escape(part)}</font>' if re.fullmatch(r"[\x20-\x7e]+", part or "") else escape(part)
            for part in parts
        )

    output = BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=str(rule.get("title", "Detection rule report")),
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("CipherTitle", parent=styles["Title"], fontName=font_name, fontSize=20, leading=25, textColor=colors.HexColor("#18202b"))
    heading_style = ParagraphStyle("CipherHeading", parent=styles["Heading2"], fontName=font_name, fontSize=13, leading=18, textColor=colors.HexColor("#27364a"), spaceBefore=12, spaceAfter=6)
    body_style = ParagraphStyle("CipherBody", parent=styles["BodyText"], fontName=font_name, fontSize=9.5, leading=15)
    code_style = ParagraphStyle("CipherCode", parent=styles["Code"], fontName=mono_font, fontSize=7.5, leading=11, backColor=colors.HexColor("#f5f7fa"), borderPadding=8)
    validation = rule.get("validation") if isinstance(rule.get("validation"), dict) else {}
    story: list[Any] = [
        Paragraph(mixed_markup(rule.get("title", "Detection rule report")), title_style),
        Paragraph(mixed_markup(f"Case #{rule.get('caseId')} | {str(rule.get('ruleType', '')).upper()} | Version {rule.get('version')} | {rule.get('status', 'draft')}"), body_style),
        Spacer(1, 6 * mm),
        Paragraph("验证结论", heading_style),
        Paragraph(mixed_markup("VALID" if validation.get("valid") else "INVALID"), body_style),
    ]
    for label, key in (("错误", "errors"), ("警告", "warnings")):
        story.append(Paragraph(label, heading_style))
        values = validation.get(key) if isinstance(validation.get(key), list) else []
        story.extend(Paragraph(mixed_markup(f"• {value}"), body_style) for value in values)
        if not values:
            story.append(Paragraph(mixed_markup("None"), body_style))
    conversions = validation.get("conversions") if isinstance(validation.get("conversions"), dict) else {}
    story.append(Paragraph("目标 SIEM 转换", heading_style))
    for name, query in conversions.items():
        story.extend([Paragraph(mixed_markup(name.title()), body_style), Preformatted(str(query), code_style), Spacer(1, 3 * mm)])
    tests = rule.get("testRuns") if isinstance(rule.get("testRuns"), list) else []
    story.append(Paragraph("测试记录", heading_style))
    table_data = [["时间", "命中", "误报"]] + [
        [str(item.get("createdAt", "")), f"{item.get('matchedArtifacts', 0)} / {item.get('totalArtifacts', 0)}", str(item.get("falsePositiveCount", 0))]
        for item in tests
    ]
    if len(table_data) == 1:
        table_data.append(["-", "0 / 0", "0"])
    table = Table([[Paragraph(mixed_markup(cell), body_style) for cell in row] for row in table_data], colWidths=[95 * mm, 35 * mm, 25 * mm])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9eef6")), ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#c8d0dc")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 5)]))
    story.extend([table, PageBreak(), Paragraph("规则内容", heading_style), Preformatted(str(rule.get("content", "")), code_style)])
    document.build(story)
    return output.getvalue()

from __future__ import annotations

import csv
from io import BytesIO, StringIO
from html import escape
import json
from pathlib import Path
import re
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from app.models import CapeCase


def _cipher_logo_svg() -> str:
    return """<svg class="cipher-logo" viewBox="0 0 190 72" role="img" aria-label="Cipher Intelligence"><g transform="translate(4 4) scale(.94)"><path d="M32 3.5 55 12.6v17.1c0 14.6-8.3 25-23 31.3C17.3 54.7 9 44.3 9 29.7V12.6L32 3.5Z" fill="#155EEF"/><path d="M42.2 20.5a15.2 15.2 0 1 0 0 23" stroke="white" stroke-width="6" stroke-linecap="round" fill="none"/><circle cx="43" cy="20.5" r="3.2" fill="#71E6FF"/><circle cx="43" cy="43.5" r="3.2" fill="#71E6FF"/><path d="M46.5 25.5h5M46.5 38.5h5" stroke="#71E6FF" stroke-width="2.5" stroke-linecap="round"/></g><text x="76" y="42" fill="#0F172A" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="34" font-weight="700" letter-spacing="-1.2">Cipher</text><text x="78" y="59" fill="#526173" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="10" font-weight="650" letter-spacing="2.2">INTELLIGENCE</text></svg>"""


def _summary(cape_case: CapeCase) -> dict[str, Any]:
    if not cape_case.summary_json:
        raise ValueError("CAPE case report is not ready for export.")
    payload = json.loads(cape_case.summary_json)
    if not isinstance(payload, dict):
        raise ValueError("CAPE case report is invalid.")
    return payload


def _safe_rule_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]", "_", value)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized or normalized[0].isdigit():
        normalized = f"case_{normalized}"
    return normalized[:80]


def _chinese_analysis(cape_case: CapeCase, summary: dict[str, Any]) -> tuple[str, str]:
    score = cape_case.score
    if score is None:
        risk_level = "风险待定"
        score_text = "沙箱未返回风险评分"
    elif score >= 8:
        risk_level = "高风险"
        score_text = f"风险评分为 {score:g}"
    elif score >= 5:
        risk_level = "中风险"
        score_text = f"风险评分为 {score:g}"
    else:
        risk_level = "低风险"
        score_text = f"风险评分为 {score:g}"

    iocs = summary.get("iocs") if isinstance(summary.get("iocs"), dict) else {}
    ioc_count = sum(
        len({str(value).strip() for value in iocs.get(key, []) if str(value).strip()})
        for key in ("domains", "ips", "urls")
        if isinstance(iocs.get(key), list)
    )
    tactics = summary.get("tactics") if isinstance(summary.get("tactics"), list) else []
    technique_names = [
        str(item.get("technique", "")).strip()
        for item in tactics
        if isinstance(item, dict) and str(item.get("technique", "")).strip()
    ]
    dropped = summary.get("droppedFiles") if isinstance(summary.get("droppedFiles"), list) else []
    technique_text = "、".join(technique_names[:5]) if technique_names else "暂未映射到明确的 ATT&CK 技术"
    overview = (
        f"该样本综合研判为{risk_level}，{score_text}。沙箱识别到 {len(technique_names)} 项 ATT&CK 技术映射"
        f"（{technique_text}），提取 {ioc_count} 项网络 IOC，并发现 {len(dropped)} 个落地文件。"
    )
    if risk_level == "高风险":
        action = "建议优先隔离相关主机，封禁已确认的恶意 IOC，排查同类行为及持久化痕迹，并将检测规则验证后部署到 SIEM/EDR。"
    elif risk_level == "中风险":
        action = "建议结合终端与网络日志核验 IOC 和行为链，对相关主机开展范围排查，并在确认恶意性后执行隔离与封禁。"
    else:
        action = "建议继续结合原始样本、终端日志和网络流量复核，避免仅依据单次沙箱结果执行阻断。"
    caveat = "本结论由 Cipher 根据当前 CAPE 沙箱证据自动生成，不等同于最终事件定性，处置前需由安全分析人员复核。"
    return overview, f"{action}{caveat}"


def _chinese_conclusion(cape_case: CapeCase, summary: dict[str, Any]) -> tuple[str, str]:
    tactics = summary.get("tactics") if isinstance(summary.get("tactics"), list) else []
    signatures = summary.get("signatures") if isinstance(summary.get("signatures"), list) else []
    behavior_names = [
        str(item.get("description") or item.get("signature") or "").strip()
        for item in tactics
        if isinstance(item, dict) and str(item.get("description") or item.get("signature") or "").strip()
    ]
    if not behavior_names:
        behavior_names = [
            str(item.get("name", "")).strip()
            for item in signatures
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        ]
    behavior_text = "、".join(behavior_names[:4]) if behavior_names else "可疑运行行为"
    iocs = summary.get("iocs") if isinstance(summary.get("iocs"), dict) else {}
    ioc_count = sum(
        len({str(value).strip() for value in iocs.get(key, []) if str(value).strip()})
        for key in ("domains", "ips", "urls")
        if isinstance(iocs.get(key), list)
    )
    score = cape_case.score
    if score is not None and score >= 8:
        verdict = "高风险威胁"
        priority = "高优先级"
    elif score is not None and score >= 5:
        verdict = "疑似威胁"
        priority = "中高优先级"
    else:
        verdict = "待确认威胁"
        priority = "待核实"
    evidence = (
        f"[C1] 样本“{cape_case.sample_name}”在 CAPE 沙箱任务 #{cape_case.cape_task_id} 中表现出 {behavior_text}。"
        f"沙箱共提取 {ioc_count} 项网络 IOC；上述行为与指标共同构成本次研判的主要证据，建议将该样本定性为“{verdict}”。"
    )
    recommendation = (
        f"建议将该样本的威胁等级标记为“{priority}”，优先隔离相关终端并核验、封禁已确认的恶意 IOC，"
        "同步排查同源样本、相同行为链和持久化痕迹；在规则验证完成后部署至 SIEM/EDR，并持续跟踪情报与检测结果更新。"
    )
    return evidence, recommendation


def build_case_json(cape_case: CapeCase) -> bytes:
    payload = {
        "caseId": cape_case.id,
        "conversationId": cape_case.conversation_id,
        "taskId": cape_case.cape_task_id,
        "sampleName": cape_case.sample_name,
        "status": cape_case.status,
        "score": cape_case.score,
        "sha256": cape_case.sha256,
        "analysis": _summary(cape_case),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def build_ioc_csv(cape_case: CapeCase) -> bytes:
    summary = _summary(cape_case)
    iocs = summary.get("iocs") if isinstance(summary.get("iocs"), dict) else {}
    rows: list[tuple[str, str]] = []
    for source_key, output_type in (("domains", "domain"), ("ips", "ip"), ("urls", "url")):
        values = iocs.get(source_key, []) if isinstance(iocs, dict) else []
        if isinstance(values, list):
            rows.extend((output_type, str(value)) for value in values if str(value).strip())
    if cape_case.sha256:
        rows.insert(0, ("sha256", cape_case.sha256))

    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["type", "value", "case_id", "task_id", "sample_name"])
    for ioc_type, value in rows:
        writer.writerow([ioc_type, value, cape_case.id, cape_case.cape_task_id, cape_case.sample_name])
    return output.getvalue().encode("utf-8-sig")


def build_markdown_report(cape_case: CapeCase) -> bytes:
    summary = _summary(cape_case)
    iocs = summary.get("iocs") if isinstance(summary.get("iocs"), dict) else {}
    tactics = summary.get("tactics") if isinstance(summary.get("tactics"), list) else []
    dropped = summary.get("droppedFiles") if isinstance(summary.get("droppedFiles"), list) else []
    lines = [
        f"# Cipher CAPE Case #{cape_case.id}",
        "",
        "## \u6982\u89c8",
        "",
        f"- \u6837\u672c\uff1a`{cape_case.sample_name}`",
        f"- CAPE Task\uff1a`{cape_case.cape_task_id}`",
        f"- \u72b6\u6001\uff1a{cape_case.status}",
        f"- \u98ce\u9669\u8bc4\u5206\uff1a{cape_case.score if cape_case.score is not None else '\u672a\u8fd4\u56de'}",
        f"- SHA256\uff1a`{cape_case.sha256 or '\u672a\u8fd4\u56de'}`",
        "",
        "## IOC",
        "",
        "| \u7c7b\u578b | \u503c |",
        "| --- | --- |",
    ]
    ioc_row_count = 0
    for key, label in (("domains", "Domain"), ("ips", "IP"), ("urls", "URL")):
        values = iocs.get(key, []) if isinstance(iocs, dict) else []
        if isinstance(values, list):
            normalized_values = [value for value in values if str(value).strip()]
            ioc_row_count += len(normalized_values)
            lines.extend(f"| {label} | `{value}` |" for value in normalized_values)
    if ioc_row_count == 0:
        lines.append("| - | \u6682\u65e0 IOC |")

    lines.extend(["", "## MITRE ATT&CK", "", "| Technique | Signature | \u8bc1\u636e |", "| --- | --- | --- |"])
    for item in tactics:
        if isinstance(item, dict):
            lines.append(
                f"| {item.get('technique', '')} | {item.get('signature', '')} | {item.get('description', '')} |"
            )
    if not tactics:
        lines.append("| - | - | \u6682\u65e0\u6620\u5c04 |")

    lines.extend(["", "## Dropped Files", ""])
    if dropped:
        for item in dropped:
            if isinstance(item, dict):
                lines.append(
                    f"- `{item.get('name', '')}` \u2014 {item.get('type', '')} \u2014 `{item.get('sha256', '')}`"
                )
    else:
        lines.append("- \u6682\u65e0")

    lines.extend(
        [
            "",
            "---",
            "",
            "\u672c\u62a5\u544a\u7531 Cipher \u57fa\u4e8e CAPE \u6c99\u7bb1\u7ed3\u679c\u81ea\u52a8\u751f\u6210\uff0c\u8bf7\u5728\u6267\u884c\u5c01\u7981\u6216\u5904\u7f6e\u524d\u5b8c\u6210\u4eba\u5de5\u590d\u6838\u3002",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def build_html_report(cape_case: CapeCase) -> bytes:
    summary = _summary(cape_case)
    analysis_overview, analysis_action = _chinese_analysis(cape_case, summary)
    conclusion_evidence, conclusion_recommendation = _chinese_conclusion(cape_case, summary)
    iocs = summary.get("iocs") if isinstance(summary.get("iocs"), dict) else {}
    tactics = summary.get("tactics") if isinstance(summary.get("tactics"), list) else []
    dropped = summary.get("droppedFiles") if isinstance(summary.get("droppedFiles"), list) else []
    ioc_rows = []
    for key, label in (("domains", "Domain"), ("ips", "IP"), ("urls", "URL")):
        values = iocs.get(key, []) if isinstance(iocs, dict) else []
        if isinstance(values, list):
            ioc_rows.extend(f"<tr><td>{label}</td><td><code>{escape(str(value))}</code></td></tr>" for value in values)
    tactic_rows = "".join(
        f"<tr><td>{escape(str(item.get('technique', '')))}</td><td>{escape(str(item.get('signature', '')))}</td><td>{escape(str(item.get('description', '')))}</td></tr>"
        for item in tactics if isinstance(item, dict)
    )
    dropped_rows = "".join(
        f"<tr><td>{escape(str(item.get('name', '')))}</td><td>{escape(str(item.get('type', '')))}</td><td><code>{escape(str(item.get('sha256', '')))}</code></td></tr>"
        for item in dropped if isinstance(item, dict)
    )
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>Cipher CAPE Case #{cape_case.id}</title><style>body{{font:14px/1.65 system-ui,sans-serif;max-width:980px;margin:40px auto;padding:0 28px;color:#18202b}}.report-brand{{display:flex;align-items:center;justify-content:flex-start;padding-bottom:14px;margin-bottom:20px;border-bottom:1px solid #d9dee8}}.cipher-logo{{display:block;width:154px;height:auto}}h1{{margin-bottom:4px}}.meta{{color:#667085}}.analysis{{margin:18px 0 24px;padding:16px 18px;border-left:4px solid #4969e8;background:#f3f6ff;border-radius:6px}}.analysis p{{margin:6px 0}}.conclusion{{margin:12px 0 24px;padding:18px 20px;background:#f7f9fc;border:1px solid #d9e0ea;border-radius:8px}}.conclusion p{{margin:0 0 12px}}.conclusion p:last-child{{margin-bottom:0;font-weight:650}}table{{width:100%;border-collapse:collapse;margin:10px 0 22px}}th,td{{padding:8px;border:1px solid #d9dee8;text-align:left;vertical-align:top}}th{{background:#eef2f7}}code{{overflow-wrap:anywhere}}</style></head><body><header class="report-brand">{_cipher_logo_svg()}</header><h1>Cipher CAPE Case #{cape_case.id}</h1><p class="meta">Sample: {escape(cape_case.sample_name)} · Task #{cape_case.cape_task_id} · Score {cape_case.score if cape_case.score is not None else '-'}</p><h2>中文总结与研判说明</h2><section class="analysis"><p>{escape(analysis_overview)}</p><p>{escape(analysis_action)}</p></section><h2>Overview</h2><table><tr><th>Status</th><td>{escape(cape_case.status)}</td></tr><tr><th>SHA256</th><td><code>{escape(cape_case.sha256 or '-')}</code></td></tr></table><h2>IOC</h2><table><tr><th>Type</th><th>Value</th></tr>{''.join(ioc_rows) or '<tr><td colspan="2">No IOC</td></tr>'}</table><h2>MITRE ATT&amp;CK</h2><table><tr><th>Technique</th><th>Signature</th><th>Evidence</th></tr>{tactic_rows or '<tr><td colspan="3">No mapping</td></tr>'}</table><h2>Dropped Files</h2><table><tr><th>Name</th><th>Type</th><th>SHA256</th></tr>{dropped_rows or '<tr><td colspan="3">None</td></tr>'}</table><h2>结论</h2><section class="conclusion"><p>{escape(conclusion_evidence)}</p><p>{escape(conclusion_recommendation)}</p></section><p class="meta">Generated by Cipher from CAPE evidence. Analyst review is required before response actions.</p></body></html>"""
    return html.encode("utf-8")


def build_pdf_report(cape_case: CapeCase) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    summary = _summary(cape_case)
    analysis_overview, analysis_action = _chinese_analysis(cape_case, summary)
    conclusion_evidence, conclusion_recommendation = _chinese_conclusion(cape_case, summary)
    font_path = Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf")
    font_name = "CipherCJK"
    if font_name not in pdfmetrics.getRegisteredFontNames() and font_path.exists():
        pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
    if font_name not in pdfmetrics.getRegisteredFontNames(): font_name = "Helvetica"
    latin_font = "CipherLatin"
    if latin_font not in pdfmetrics.getRegisteredFontNames(): pdfmetrics.registerFont(TTFont(latin_font, "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    def mixed_markup(value: Any) -> str:
        parts = re.split(r"([\x20-\x7e]+)", str(value))
        return "".join(f'<font name="{latin_font}">{escape(part)}</font>' if re.fullmatch(r"[\x20-\x7e]+", part or "") else escape(part) for part in parts)
    logo_path = Path(__file__).with_name("assets") / "cipher-wordmark.png"
    logo_width = 43 * mm
    logo = Image(str(logo_path), width=logo_width, height=logo_width * 241 / 706)
    logo.hAlign = "LEFT"
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=18*mm, bottomMargin=18*mm, title=f"Cipher CAPE Case #{cape_case.id}")
    styles = getSampleStyleSheet(); title = ParagraphStyle("CapeTitle", parent=styles["Title"], fontName=font_name, fontSize=20, leading=25); heading = ParagraphStyle("CapeHeading", parent=styles["Heading2"], fontName=font_name, fontSize=13, leading=18, spaceBefore=12); body = ParagraphStyle("CapeBody", parent=styles["BodyText"], fontName=font_name, fontSize=8.5, leading=13)
    story = [logo, Spacer(1, 4*mm), Paragraph(mixed_markup(f"Cipher CAPE Case #{cape_case.id}"), title), Paragraph(mixed_markup(f"Sample: {cape_case.sample_name} | Task #{cape_case.cape_task_id} | Score {cape_case.score if cape_case.score is not None else '-'}"), body), Spacer(1, 5*mm), Paragraph(mixed_markup("中文总结与研判说明"), heading), Paragraph(mixed_markup(analysis_overview), body), Spacer(1, 2*mm), Paragraph(mixed_markup(analysis_action), body)]
    def add_table(label: str, rows: list[list[str]], widths: list[float]) -> None:
        story.append(Paragraph(mixed_markup(label), heading)); table = Table([[Paragraph(mixed_markup(cell), body) for cell in row] for row in rows], colWidths=widths, repeatRows=1); table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#e9eef6")),("GRID",(0,0),(-1,-1),.4,colors.HexColor("#c8d0dc")),("VALIGN",(0,0),(-1,-1),"TOP"),("PADDING",(0,0),(-1,-1),5)])); story.append(table)
    add_table("Overview", [["Status", "SHA256"], [cape_case.status, cape_case.sha256 or "-"]], [35*mm, 120*mm])
    iocs = summary.get("iocs") if isinstance(summary.get("iocs"), dict) else {}; ioc_rows = [["Type", "Value"]]
    for key, label in (("domains","Domain"),("ips","IP"),("urls","URL")):
        values = iocs.get(key, []) if isinstance(iocs, dict) else []
        if isinstance(values, list): ioc_rows.extend([[label, str(value)] for value in values])
    if len(ioc_rows) == 1: ioc_rows.append(["-", "No IOC"])
    add_table("IOC", ioc_rows, [30*mm,125*mm])
    tactics = summary.get("tactics") if isinstance(summary.get("tactics"), list) else []; tactic_rows = [["Technique","Signature","Evidence"]] + [[str(item.get("technique","")),str(item.get("signature","")),str(item.get("description",""))] for item in tactics if isinstance(item,dict)]
    if len(tactic_rows) == 1: tactic_rows.append(["-","-","No mapping"])
    add_table("MITRE ATT&CK", tactic_rows, [28*mm,45*mm,82*mm])
    story.extend([Paragraph(mixed_markup("结论"), heading), Paragraph(mixed_markup(conclusion_evidence), body), Spacer(1, 2*mm), Paragraph(mixed_markup(conclusion_recommendation), body)])
    document.build(story); return output.getvalue()


def build_sigma_starter(cape_case: CapeCase) -> bytes:
    summary = _summary(cape_case)
    tactics = summary.get("tactics") if isinstance(summary.get("tactics"), list) else []
    keywords = [
        str(item.get("signature", "")).strip()
        for item in tactics
        if isinstance(item, dict) and str(item.get("signature", "")).strip()
    ]
    quoted_keywords = "\n".join(f"      - {json.dumps(value, ensure_ascii=False)}" for value in keywords[:20])
    if not quoted_keywords:
        quoted_keywords = "      - \"REVIEW_REQUIRED_NO_SIGNATURES\""
    content = f"""title: Cipher CAPE Case {cape_case.id} starter
id: 00000000-0000-4000-8000-{cape_case.id:012d}
status: experimental
description: Starter detection generated from CAPE task {cape_case.cape_task_id}; analyst review required.
references:
  - cape-task:{cape_case.cape_task_id}
tags:
  - attack.execution
logsource:
  category: process_creation
  product: windows
detection:
  keywords:
{quoted_keywords}
  condition: keywords
falsepositives:
  - Unknown; validate against the original CAPE evidence.
level: high
"""
    return content.encode("utf-8")


def build_yara_starter(cape_case: CapeCase) -> bytes:
    summary = _summary(cape_case)
    signatures = summary.get("signatures") if isinstance(summary.get("signatures"), list) else []
    strings = [
        str(item.get("name", "")).strip()
        for item in signatures
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    ]
    string_lines = "\n".join(
        f'        $sig_{index} = {json.dumps(value, ensure_ascii=False)} ascii nocase'
        for index, value in enumerate(strings[:20], start=1)
    )
    rule_name = _safe_rule_name(f"Cipher_Case_{cape_case.id}_{cape_case.sample_name}")
    sha_condition = (
        f'hash.sha256(0, filesize) == "{cape_case.sha256}"'
        if cape_case.sha256
        else "false"
    )
    signature_condition = " or any of ($sig_*)" if string_lines else " or $review_required"
    content = f"""import \"hash\"

rule {rule_name} {{
    meta:
        description = \"Starter rule generated from CAPE task {cape_case.cape_task_id}; analyst review required\"
        case_id = \"{cape_case.id}\"
        sample = {json.dumps(cape_case.sample_name, ensure_ascii=False)}
    strings:
{string_lines or '        $review_required = "REVIEW_REQUIRED_NO_SIGNATURES" ascii'}
    condition:
        {sha_condition}{signature_condition}
}}
"""
    return content.encode("utf-8")


def build_case_bundle(cape_case: CapeCase) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("case.json", build_case_json(cape_case))
        archive.writestr("report.md", build_markdown_report(cape_case))
        archive.writestr("report.html", build_html_report(cape_case))
        archive.writestr("report.pdf", build_pdf_report(cape_case))
        archive.writestr("iocs.csv", build_ioc_csv(cape_case))
        archive.writestr("sigma-starter.yml", build_sigma_starter(cape_case))
        archive.writestr("yara-starter.yar", build_yara_starter(cape_case))
    return output.getvalue()

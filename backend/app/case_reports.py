from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from io import BytesIO
import json
from pathlib import Path
import re
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CapeCase, CaseConclusion, CaseConversation, CaseEvent, CaseIndicator, CaseSignature,
    InvestigationCase, InvestigationPlaybook, Message, MessageAttachment, MessageEvidence,
)


REPORT_VERSION = "1.0"
REPORT_TYPES = {"technical_zh", "technical_en", "executive"}
EXPORT_FORMATS = {"pdf", "markdown", "json", "stix", "misp", "attack_navigator"}


def _json(raw: str | None, default: Any) -> Any:
    try:
        value = json.loads(raw or "")
    except (json.JSONDecodeError, TypeError):
        return default
    return value


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _stix_id(object_type: str, value: str) -> str:
    return f"{object_type}--{uuid5(NAMESPACE_URL, f'cipher:{object_type}:{value}') }"


def _linked_conversation_ids(db: Session, case_id: int) -> list[int]:
    return list(db.execute(select(CaseConversation.conversation_id).where(CaseConversation.case_id == case_id)).scalars())


def build_report_data(
    db: Session,
    case: InvestigationCase,
    *,
    report_type: str,
    watermark: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc)
    conversation_ids = _linked_conversation_ids(db, case.id)
    cape_cases = list(db.execute(select(CapeCase).where(CapeCase.conversation_id.in_(conversation_ids)).order_by(CapeCase.created_at, CapeCase.id)).scalars()) if conversation_ids else []
    indicators = list(db.execute(select(CaseIndicator).where(CaseIndicator.case_id == case.id).order_by(CaseIndicator.indicator_type, CaseIndicator.value)).scalars())
    events = list(db.execute(select(CaseEvent).where(CaseEvent.case_id == case.id).order_by(CaseEvent.created_at, CaseEvent.id)).scalars())
    evidence = list(db.execute(select(MessageEvidence).join(Message).where(Message.conversation_id.in_(conversation_ids)).order_by(MessageEvidence.id)).scalars().unique()) if conversation_ids else []
    attachments = list(db.execute(select(MessageAttachment).join(Message).where(Message.conversation_id.in_(conversation_ids)).order_by(MessageAttachment.id)).scalars()) if conversation_ids else []
    conclusions = list(db.execute(select(CaseConclusion).where(CaseConclusion.case_id == case.id).order_by(CaseConclusion.created_at, CaseConclusion.id)).scalars())
    signatures = list(db.execute(select(CaseSignature).where(CaseSignature.case_id == case.id).order_by(CaseSignature.signed_at.desc(), CaseSignature.id.desc())).scalars())
    playbooks = list(db.execute(select(InvestigationPlaybook).where(InvestigationPlaybook.case_id == case.id).order_by(InvestigationPlaybook.created_at, InvestigationPlaybook.id)).scalars())

    samples: list[dict[str, Any]] = []
    techniques: dict[str, dict[str, Any]] = {}
    recommendations: list[str] = []
    for cape in cape_cases:
        summary = _json(cape.summary_json, {})
        samples.append({
            "capeCaseId": cape.id, "taskId": cape.cape_task_id, "name": cape.sample_name,
            "sha256": cape.sha256 or summary.get("sha256"), "score": cape.score,
            "status": cape.status, "machine": cape.machine, "analyzedAt": _iso(cape.updated_at),
        })
        for item in summary.get("tactics", []) if isinstance(summary.get("tactics"), list) else []:
            if isinstance(item, dict) and str(item.get("technique", "")).strip():
                technique_id = str(item["technique"]).strip()
                techniques.setdefault(technique_id, {
                    "techniqueId": technique_id, "name": item.get("signature") or item.get("name"),
                    "description": item.get("description"), "sourceCapeCaseId": cape.id,
                })
    for playbook in playbooks:
        for step in playbook.steps:
            output = _json(step.output_json, {})
            if step.step_key in {"remediation", "report", "approval"}:
                for key in ("recommendations", "actions", "nextSteps"):
                    values = output.get(key, []) if isinstance(output, dict) else []
                    if isinstance(values, list):
                        recommendations.extend(str(value).strip() for value in values if str(value).strip())
    if not recommendations:
        recommendations = (["立即隔离受影响主机", "阻断已确认的恶意 IOC", "开展同源威胁狩猎", "验证并部署检测规则"]
                           if case.severity in {"critical", "high"} else
                           ["核验 IOC 与终端、网络日志", "保全相关证据", "根据核验结果实施阻断与隔离"])

    evidence_rows = [{
        "id": item.id, "citation": item.citation, "title": item.title, "sourceType": item.source_type,
        "locator": item.url or item.locator, "snippet": item.snippet, "reviewStatus": item.review_status,
        "sourceTrust": item.source_trust, "confidence": item.confidence, "contentHash": item.content_hash,
    } for item in evidence]
    unconfirmed = [f"[{item.citation}] {item.title}" for item in evidence if item.review_status == "pending"]
    unconfirmed.extend(item.statement for item in conclusions if item.status == "draft")
    if not samples:
        unconfirmed.append("未关联可用的 CAPE 样本分析结果")
    valid_signature = next((item for item in signatures if item.is_valid), None)
    return {
        "schema": "cipher.case-report", "version": REPORT_VERSION, "generatedAt": _iso(generated_at),
        "caseId": case.id, "reportType": report_type, "watermark": watermark,
        "case": {"id": case.id, "title": case.title, "status": case.status, "riskLevel": case.severity,
                 "priority": case.priority, "summary": case.summary, "assignee": case.assignee,
                 "tags": case.tags, "createdAt": _iso(case.created_at), "updatedAt": _iso(case.updated_at)},
        "timeline": [{"id": item.id, "timestamp": _iso(item.created_at), "type": item.event_type,
                      "title": item.title, "detail": item.detail, "actor": item.actor} for item in events],
        "samples": samples + [{"attachmentId": item.attachment_id, "name": item.name, "mediaType": item.type,
                               "size": item.size} for item in attachments],
        "iocs": [{"id": item.id, "type": item.indicator_type, "value": item.value,
                  "riskLevel": item.risk_level, "confidence": item.confidence, "status": item.status,
                  "firstSeen": _iso(item.first_seen_at), "lastSeen": _iso(item.last_seen_at),
                  "source": item.source_type} for item in indicators],
        "attackTechniques": list(techniques.values()), "evidence": evidence_rows,
        "conclusions": [{"id": item.id, "statement": item.statement, "status": item.status,
                         "confidence": item.confidence, "claimType": item.claim_type,
                         "evidenceIds": [link.evidence_id for link in item.evidence_links]} for item in conclusions],
        "playbooks": [{"id": item.id, "title": item.title, "status": item.status,
                       "steps": [{"key": step.step_key, "title": step.title, "status": step.status}
                                 for step in item.steps]} for item in playbooks],
        "recommendations": list(dict.fromkeys(recommendations)), "unconfirmedItems": list(dict.fromkeys(unconfirmed)),
        "analystSignature": ({"signer": valid_signature.signer, "digest": valid_signature.digest,
                              "note": valid_signature.note, "signedAt": _iso(valid_signature.signed_at), "valid": True}
                             if valid_signature else None),
    }


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    rendered = [[str(value if value not in (None, "") else "-").replace("|", "\\|") for value in row] for row in rows]
    return ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"] + ["| " + " | ".join(row) + " |" for row in rendered]


def build_markdown(data: dict[str, Any]) -> bytes:
    zh = data["reportType"] != "technical_en"
    executive = data["reportType"] == "executive"
    case = data["case"]
    labels = ({"title": "Cipher 管理层事件摘要" if executive else "Cipher 安全分析技术报告", "overview": "事件概述", "risk": "风险等级", "timeline": "事件时间线", "samples": "样本信息", "iocs": "威胁指标（IOC）", "attack": "攻击技术（MITRE ATT&CK）", "evidence": "证据引用", "actions": "处置建议", "unknown": "未确认事项", "signature": "分析员签名"} if zh else
              {"title": "Cipher Security Analysis Technical Report", "overview": "Incident Overview", "risk": "Risk Level", "timeline": "Timeline", "samples": "Sample Information", "iocs": "Indicators of Compromise (IOCs)", "attack": "Attack Techniques (MITRE ATT&CK)", "evidence": "Evidence References", "actions": "Response Recommendations", "unknown": "Unconfirmed Items", "signature": "Analyst Signature"})
    lines = [f"# {labels['title']}", "", f"**Case ID:** {data['caseId']}  ", f"**Version:** {data['version']}  ", f"**Generated:** {data['generatedAt']}  "]
    if data.get("watermark"):
        lines.append(f"**Watermark:** {data['watermark']}  ")
    lines += ["", f"## {labels['overview']}", "", case.get("summary") or case["title"], "", f"## {labels['risk']}", "", f"**{str(case['riskLevel']).upper()}** (priority {case['priority']}, status {case['status']})"]
    sections = [
        ("timeline", ["Time", "Event", "Detail"], [[x["timestamp"], x["title"], x.get("detail")] for x in data["timeline"]]),
        ("samples", ["Name", "SHA-256 / ID", "Status", "Score"], [[x.get("name"), x.get("sha256") or x.get("attachmentId"), x.get("status") or x.get("mediaType"), x.get("score")] for x in data["samples"]]),
        ("iocs", ["Type", "Value", "Risk", "Status"], [[x["type"], x["value"], x["riskLevel"], x["status"]] for x in data["iocs"]]),
        ("attack", ["Technique", "Name", "Description"], [[x["techniqueId"], x.get("name"), x.get("description")] for x in data["attackTechniques"]]),
        ("evidence", ["Citation", "Title", "Review", "Locator"], [[x["citation"], x["title"], x["reviewStatus"], x.get("locator")] for x in data["evidence"]]),
    ]
    for key, headers, rows in sections:
        lines += ["", f"## {labels[key]}", ""]
        if rows and (not executive or key in {"timeline", "iocs", "attack"}):
            lines.extend(_table(headers, rows[:10] if executive else rows))
        else:
            lines.append("无" if zh else "None")
    for key, values in (("actions", data["recommendations"]), ("unknown", data["unconfirmedItems"])):
        lines += ["", f"## {labels[key]}", ""] + ([f"- {value}" for value in values] or ["- 无" if zh else "- None"])
    signature = data.get("analystSignature")
    lines += ["", f"## {labels['signature']}", ""]
    lines.append((f"{signature['signer']} · {signature['signedAt']} · `{signature['digest']}`") if signature else ("未签署" if zh else "Unsigned"))
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_pdf(data: dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    font_name = "CipherReportCJK"
    font_path = Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf")
    if font_name not in pdfmetrics.getRegisteredFontNames() and font_path.exists():
        pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
    if font_name not in pdfmetrics.getRegisteredFontNames():
        font_name = "Helvetica"
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                                 topMargin=18 * mm, bottomMargin=18 * mm, title=f"Cipher Case {data['caseId']}")
    styles = getSampleStyleSheet()
    body = ParagraphStyle("CipherReportBody", parent=styles["BodyText"], fontName=font_name, fontSize=9, leading=14)
    heading = ParagraphStyle("CipherReportHeading", parent=styles["Heading2"], fontName=font_name, fontSize=13, leading=18, textColor=colors.HexColor("#27364a"), spaceBefore=10)
    story: list[Any] = []
    for line in build_markdown(data).decode("utf-8").splitlines():
        if line.startswith("# "):
            story.append(Paragraph(escape(line[2:]), ParagraphStyle("CipherReportTitle", parent=heading, fontSize=20, leading=26)))
        elif line.startswith("## "):
            story.append(Paragraph(escape(line[3:]), heading))
        elif line.startswith("| ---") or not line.strip():
            story.append(Spacer(1, 2 * mm))
        elif line.startswith("| "):
            story.append(Paragraph(escape(" · ".join(cell.strip() for cell in line.strip("| ").split("|"))), body))
        else:
            cleaned = re.sub(r"[*`]", "", line.removeprefix("- "))
            story.append(Paragraph(escape(("• " if line.startswith("- ") else "") + cleaned), body))
    watermark = data.get("watermark")
    def decorate(canvas, doc):
        if watermark:
            canvas.saveState(); canvas.setFillColor(colors.Color(0.5, 0.5, 0.5, alpha=0.18)); canvas.setFont(font_name, 32)
            canvas.translate(A4[0] / 2, A4[1] / 2); canvas.rotate(35); canvas.drawCentredString(0, 0, str(watermark)); canvas.restoreState()
        canvas.saveState(); canvas.setFont("Helvetica", 7); canvas.setFillColor(colors.grey)
        canvas.drawString(18 * mm, 9 * mm, f"v{data['version']} | Case {data['caseId']} | {data['generatedAt']}"); canvas.restoreState()
    document.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return output.getvalue()


def build_stix(data: dict[str, Any]) -> bytes:
    created = data["generatedAt"]
    objects: list[dict[str, Any]] = [{"type": "identity", "spec_version": "2.1", "id": _stix_id("identity", "cipher"), "created": created, "modified": created, "name": "Cipher", "identity_class": "system"}]
    for item in data["iocs"]:
        patterns = {"domain": "domain-name:value", "ip": "ipv4-addr:value", "url": "url:value", "md5": "file:hashes.MD5", "sha1": "file:hashes.SHA-1", "sha256": "file:hashes.SHA-256"}
        field = patterns.get(item["type"])
        if not field:
            continue
        value = str(item["value"]).replace("\\", "\\\\").replace("'", "\\'")
        objects.append({"type": "indicator", "spec_version": "2.1", "id": _stix_id("indicator", f"{item['type']}:{item['value']}"), "created": created, "modified": created, "name": f"Cipher Case {data['caseId']} {item['type']}", "pattern_type": "stix", "pattern_version": "2.1", "pattern": f"[{field} = '{value}']", "valid_from": item.get("firstSeen") or created, "labels": [item["riskLevel"], item["status"]]})
    for item in data["attackTechniques"]:
        objects.append({"type": "attack-pattern", "spec_version": "2.1", "id": _stix_id("attack-pattern", item["techniqueId"]), "created": created, "modified": created, "name": item.get("name") or item["techniqueId"], "description": item.get("description") or "", "external_references": [{"source_name": "mitre-attack", "external_id": item["techniqueId"], "url": f"https://attack.mitre.org/techniques/{item['techniqueId'].replace('.', '/')}/"}]})
    payload = {"type": "bundle", "id": _stix_id("bundle", f"case:{data['caseId']}:{created}"), "objects": objects, "x_cipher_export": {"version": data["version"], "generated_at": created, "case_id": data["caseId"], "watermark": data.get("watermark")}}
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def build_misp(data: dict[str, Any]) -> bytes:
    type_map = {"domain": ("domain", "Network activity"), "ip": ("ip-dst", "Network activity"), "url": ("url", "Network activity"), "md5": ("md5", "Payload delivery"), "sha1": ("sha1", "Payload delivery"), "sha256": ("sha256", "Payload delivery")}
    attributes = [{"type": type_map[x["type"]][0], "category": type_map[x["type"]][1], "value": x["value"], "to_ids": x["status"] in {"malicious", "suspicious", "blocked"}, "comment": f"Cipher risk={x['riskLevel']} confidence={x['confidence']}"} for x in data["iocs"] if x["type"] in type_map]
    event = {"Event": {"uuid": str(uuid5(NAMESPACE_URL, f"cipher:misp:case:{data['caseId']}")), "info": f"Cipher Case #{data['caseId']} - {data['case']['title']}", "date": data["generatedAt"][:10], "threat_level_id": {"critical": "1", "high": "1", "medium": "2", "low": "3"}.get(data["case"]["riskLevel"], "4"), "analysis": "2", "published": False, "Attribute": attributes, "Tag": [{"name": f"cipher:case-id={data['caseId']}"}, {"name": f"cipher:report-version={data['version']}"}], "Orgc": {"name": "Cipher"}, "cipher_export": {"version": data["version"], "generatedAt": data["generatedAt"], "caseId": data["caseId"], "watermark": data.get("watermark")}}}
    return json.dumps(event, ensure_ascii=False, indent=2).encode("utf-8")


def build_attack_navigator(data: dict[str, Any]) -> bytes:
    layer = {"name": f"Cipher Case #{data['caseId']}", "versions": {"attack": "16", "navigator": "5.1.0", "layer": "4.5"}, "domain": "enterprise-attack", "description": data["case"].get("summary") or data["case"]["title"], "filters": {"platforms": []}, "sorting": 0, "layout": {"layout": "side", "aggregateFunction": "average", "showID": True, "showName": True, "showAggregateScores": False, "countUnscored": False}, "hideDisabled": False, "techniques": [{"techniqueID": item["techniqueId"], "score": {"critical": 100, "high": 80, "medium": 60, "low": 30}.get(data["case"]["riskLevel"], 20), "comment": item.get("description") or item.get("name") or "", "enabled": True, "metadata": [{"name": "sourceCapeCaseId", "value": str(item.get("sourceCapeCaseId") or "") }]} for item in data["attackTechniques"]], "gradient": {"colors": ["#ffe2e2", "#ff6666", "#b30000"], "minValue": 0, "maxValue": 100}, "legendItems": [], "metadata": [{"name": "reportVersion", "value": data["version"]}, {"name": "generatedAt", "value": data["generatedAt"]}, {"name": "caseId", "value": str(data["caseId"])}] + ([{"name": "watermark", "value": data["watermark"]}] if data.get("watermark") else []), "links": [], "showTacticRowBackground": False, "tacticRowBackground": "#dddddd", "selectTechniquesAcrossTactics": True, "selectSubtechniquesWithParent": False, "selectVisibleTechniques": False}
    return json.dumps(layer, ensure_ascii=False, indent=2).encode("utf-8")


def export_report(data: dict[str, Any], export_format: str) -> tuple[bytes, str, str]:
    if export_format == "markdown": return build_markdown(data), "text/markdown; charset=utf-8", "md"
    if export_format == "pdf": return build_pdf(data), "application/pdf", "pdf"
    if export_format == "json": return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"), "application/json", "json"
    if export_format == "stix": return build_stix(data), "application/stix+json", "stix.json"
    if export_format == "misp": return build_misp(data), "application/json", "misp.json"
    if export_format == "attack_navigator": return build_attack_navigator(data), "application/json", "navigator.json"
    raise ValueError("Unsupported report export format")

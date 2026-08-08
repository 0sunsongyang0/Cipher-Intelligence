from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from app.models import CapeCase, CaseEvent, CaseIndicator, InvestigationCase


RISK_ORDER = {"unknown": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _json(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def _risk(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 9:
        return "critical"
    if score >= 7:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def _node_id(kind: str, value: Any) -> str:
    return f"{kind}:{str(value).strip().lower()}"


def build_case_analysis(
    case: InvestigationCase,
    cape_cases: list[CapeCase],
    indicators: list[CaseIndicator],
    audit_events: list[CaseEvent],
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def node(kind: str, value: Any, label: str, *, risk: str = "unknown", detail: dict[str, Any] | None = None, evidence: dict[str, Any] | None = None) -> str:
        identifier = _node_id(kind, value)
        current = nodes.get(identifier)
        payload = {"id": identifier, "type": kind, "label": label, "risk": risk, "detail": detail or {}, "evidence": evidence}
        if current and RISK_ORDER.get(current["risk"], 0) > RISK_ORDER.get(risk, 0):
            payload["risk"] = current["risk"]
        nodes[identifier] = {**current, **payload} if current else payload
        return identifier

    def edge(source: str, target: str, relation: str, evidence: dict[str, Any] | None = None) -> None:
        if source == target:
            return
        key = (source, target, relation)
        edges[key] = {"id": "|".join(key), "source": source, "target": target, "relation": relation, "evidence": evidence}

    def event(identifier: str, event_type: str, title: str, *, detail: str | None, occurred_at: Any, fallback: datetime, source: str, source_label: str, risk: str = "unknown", evidence: dict[str, Any] | None = None, metadata: dict[str, Any] | None = None) -> None:
        exact = _iso(occurred_at)
        events.append({
            "id": identifier, "type": event_type, "title": title, "detail": detail,
            "occurredAt": exact or _iso(fallback), "timeAccuracy": "exact" if exact else "estimated",
            "timeNote": None if exact else "源数据未提供事件时间，使用记录更新时间推定",
            "source": source, "sourceLabel": source_label, "risk": risk,
            "evidence": evidence, "metadata": metadata or {},
        })

    case_id = node("case", case.id, f"Case #{case.id}", risk=case.severity, detail={"title": case.title, "status": case.status})
    for item in audit_events:
        evidence = {"label": "Case 审计记录", "href": f"#case-event-{item.id}"}
        event(f"case:{item.id}", item.event_type, item.title, detail=item.detail or item.actor,
              occurred_at=item.created_at, fallback=item.created_at, source="case", source_label="Case 审计", risk=case.severity, evidence=evidence,
              metadata=_json(item.metadata_json))

    cape_by_id = {item.id: item for item in cape_cases}
    for cape in cape_cases:
        summary = _json(cape.summary_json)
        evidence = {"label": f"CAPE Task #{cape.cape_task_id}", "href": f"/api/cape/tasks/{cape.cape_task_id}/summary"}
        sample_id = node("sample", cape.sha256 or cape.id, cape.sample_name, risk=_risk(cape.score),
                         detail={"sha256": cape.sha256, "score": cape.score, "taskId": cape.cape_task_id, "machine": cape.machine}, evidence=evidence)
        edge(case_id, sample_id, "contains", evidence)
        event(f"cape:{cape.id}", "sample", f"分析样本 {cape.sample_name}", detail=f"CAPE {cape.status} · 风险分 {cape.score if cape.score is not None else '未知'}",
              occurred_at=summary.get("startedAt") or summary.get("submittedAt"), fallback=cape.created_at, source="cape", source_label=f"CAPE Task #{cape.cape_task_id}", risk=_risk(cape.score), evidence=evidence)

        for index, process in enumerate(summary.get("processes", []) if isinstance(summary.get("processes"), list) else []):
            if not isinstance(process, dict):
                continue
            pid = process.get("pid") or f"{cape.id}-{index}"
            process_id = node("process", f"{cape.id}:{pid}", str(process.get("name") or process.get("process_name") or f"PID {pid}"), risk=_risk(cape.score), detail=process, evidence=evidence)
            edge(sample_id, process_id, "executes", evidence)
            parent_pid = process.get("parentPid") or process.get("ppid")
            if parent_pid is not None:
                edge(_node_id("process", f"{cape.id}:{parent_pid}"), process_id, "spawns", evidence)
            event(f"cape:{cape.id}:process:{index}", "process", f"进程启动 {nodes[process_id]['label']}", detail=str(process.get("commandLine") or process.get("command_line") or f"PID {pid}"),
                  occurred_at=process.get("startedAt") or process.get("firstSeen"), fallback=cape.updated_at, source="cape", source_label=f"CAPE 进程树 · Task #{cape.cape_task_id}", risk=_risk(cape.score), evidence=evidence, metadata={"nodeId": process_id})

        for index, connection in enumerate(summary.get("networkConnections", []) if isinstance(summary.get("networkConnections"), list) else []):
            if not isinstance(connection, dict):
                continue
            value = connection.get("url") or connection.get("domain") or connection.get("ip") or connection.get("host")
            if not value:
                continue
            kind = "url" if connection.get("url") else "domain" if connection.get("domain") else "ip"
            target_id = node(kind, value, str(value), risk=_risk(cape.score), detail=connection, evidence=evidence)
            process_ref = connection.get("pid")
            source_id = _node_id("process", f"{cape.id}:{process_ref}") if process_ref is not None and _node_id("process", f"{cape.id}:{process_ref}") in nodes else sample_id
            edge(source_id, target_id, "connects_to", evidence)
            event(f"cape:{cape.id}:network:{index}", "network", f"网络连接 {value}", detail=str(connection.get("protocol") or connection.get("method") or "网络活动"),
                  occurred_at=connection.get("occurredAt") or connection.get("firstSeen"), fallback=cape.updated_at, source="cape", source_label=f"CAPE 网络行为 · Task #{cape.cape_task_id}", risk=_risk(cape.score), evidence=evidence, metadata={"nodeId": target_id})

        for index, dropped in enumerate(summary.get("droppedFiles", []) if isinstance(summary.get("droppedFiles"), list) else []):
            if not isinstance(dropped, dict):
                continue
            label = str(dropped.get("name") or dropped.get("path") or dropped.get("sha256") or "落地文件")
            file_id = node("file", dropped.get("sha256") or f"{cape.id}:{label}", label, risk=_risk(cape.score), detail=dropped, evidence=evidence)
            edge(sample_id, file_id, "drops", evidence)
            event(f"cape:{cape.id}:file:{index}", "file", f"落地文件 {label}", detail=str(dropped.get("path") or dropped.get("sha256") or "CAPE 文件行为"),
                  occurred_at=dropped.get("createdAt") or dropped.get("firstSeen"), fallback=cape.updated_at, source="cape", source_label=f"CAPE 文件行为 · Task #{cape.cape_task_id}", risk=_risk(cape.score), evidence=evidence, metadata={"nodeId": file_id})

        for index, tactic in enumerate(summary.get("tactics", []) if isinstance(summary.get("tactics"), list) else []):
            if not isinstance(tactic, dict):
                continue
            technique = str(tactic.get("technique") or tactic.get("id") or "ATT&CK")
            technique_id = node("attack", technique, technique, risk="high", detail=tactic, evidence=evidence)
            edge(sample_id, technique_id, "uses", evidence)
            event(f"cape:{cape.id}:attack:{index}", "attack", f"ATT&CK {technique}", detail=str(tactic.get("description") or tactic.get("signature") or "行为映射"),
                  occurred_at=tactic.get("occurredAt"), fallback=cape.updated_at, source="attack", source_label=f"CAPE ATT&CK 映射 · Task #{cape.cape_task_id}", risk="high", evidence=evidence, metadata={"nodeId": technique_id})

        for index, signature in enumerate(summary.get("signatures", []) if isinstance(summary.get("signatures"), list) else []):
            if not isinstance(signature, dict):
                continue
            event(f"cape:{cape.id}:behavior:{index}", "behavior", str(signature.get("name") or "CAPE 行为命中"), detail=str(signature.get("description") or signature.get("severity") or "签名检测"),
                  occurred_at=signature.get("timestamp") or signature.get("occurredAt"), fallback=cape.updated_at, source="cape", source_label=f"CAPE 行为签名 · Task #{cape.cape_task_id}", risk=_risk(cape.score), evidence=evidence)

    for indicator in indicators:
        cape = cape_by_id.get(indicator.cape_case_id or -1)
        evidence = {"label": indicator.source_type or "Case IOC", "href": f"#case-ioc-{indicator.id}"}
        indicator_id = node(indicator.indicator_type, indicator.normalized_value, indicator.value, risk=indicator.risk_level,
                            detail={"status": indicator.status, "confidence": indicator.confidence, "firstSeenAt": _iso(indicator.first_seen_at), "lastSeenAt": _iso(indicator.last_seen_at)}, evidence=evidence)
        edge(_node_id("sample", cape.sha256 or cape.id) if cape else case_id, indicator_id, "observes", evidence)
        event(f"ioc:{indicator.id}", "ioc", f"发现 {indicator.indicator_type.upper()} IOC", detail=indicator.value,
              occurred_at=indicator.first_seen_at, fallback=indicator.created_at, source="ioc", source_label=indicator.source_type or "Case IOC", risk=indicator.risk_level, evidence=evidence, metadata={"nodeId": indicator_id})

    events.sort(key=lambda item: (item["occurredAt"] or "", item["id"]), reverse=True)
    return {
        "caseId": case.id,
        "events": events,
        "graph": {"nodes": list(nodes.values()), "edges": list(edges.values())},
        "coverage": {
            "sources": sorted({item["source"] for item in events}),
            "exactTimes": sum(item["timeAccuracy"] == "exact" for item in events),
            "estimatedTimes": sum(item["timeAccuracy"] == "estimated" for item in events),
            "notes": ["进程与网络节点仅在 CAPE 摘要包含对应数据时展示。", "推定时间不会被呈现为真实行为发生时间。"],
        },
    }

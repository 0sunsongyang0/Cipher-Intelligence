from __future__ import annotations

import json
from io import BytesIO
from zipfile import ZipFile

from app.cape_exports import build_case_bundle, build_html_report, build_ioc_csv, build_markdown_report, build_pdf_report
from app.evidence import build_evidence_marker, parse_evidence_marker
from app.models import CapeCase


def build_case() -> CapeCase:
    summary = {
        "taskId": 77,
        "status": "reported",
        "score": 8.4,
        "submittedFilename": "sample.exe",
        "sha256": "a" * 64,
        "iocs": {
            "domains": ["evil.example"],
            "ips": ["203.0.113.7"],
            "urls": ["https://evil.example/drop"],
        },
        "tactics": [
            {
                "technique": "T1547.001",
                "signature": "registry_run_key",
                "description": "Run key persistence",
            }
        ],
        "droppedFiles": [],
        "signatures": [{"name": "registry_run_key"}],
    }
    return CapeCase(
        id=12,
        conversation_id=4,
        owner_user_id=2,
        cape_task_id=77,
        sample_name="sample.exe",
        status="reported",
        score=8.4,
        sha256="a" * 64,
        summary_json=json.dumps(summary),
    )


def test_cape_bundle_contains_closed_loop_artifacts() -> None:
    bundle = build_case_bundle(build_case())

    with ZipFile(BytesIO(bundle)) as archive:
        assert set(archive.namelist()) == {
            "case.json",
            "report.md",
            "report.html",
            "report.pdf",
            "iocs.csv",
            "sigma-starter.yml",
            "yara-starter.yar",
        }
        assert "evil.example" in archive.read("iocs.csv").decode("utf-8-sig")
        assert "analyst review required" in archive.read("sigma-starter.yml").decode("utf-8")
        assert archive.read("report.pdf").startswith(b"%PDF")


def test_markdown_and_ioc_exports_preserve_case_evidence() -> None:
    cape_case = build_case()

    report = build_markdown_report(cape_case).decode("utf-8")
    iocs = build_ioc_csv(cape_case).decode("utf-8-sig")

    assert "Cipher CAPE Case #12" in report
    assert "T1547.001" in report
    assert "203.0.113.7" in iocs
    assert "sha256" in iocs


def test_markdown_ioc_table_handles_single_and_empty_sources() -> None:
    cape_case = build_case()
    summary = json.loads(cape_case.summary_json or "{}")
    summary["iocs"] = {"domains": ["only.example"], "ips": [], "urls": []}
    cape_case.summary_json = json.dumps(summary)

    single_ioc_report = build_markdown_report(cape_case).decode("utf-8")
    assert "| Domain | `only.example` |" in single_ioc_report
    assert "\u6682\u65e0 IOC" not in single_ioc_report

    summary["iocs"] = {"domains": [], "ips": [], "urls": []}
    cape_case.summary_json = json.dumps(summary)
    empty_ioc_report = build_markdown_report(cape_case).decode("utf-8")
    assert "| - | \u6682\u65e0 IOC |" in empty_ioc_report


def test_evidence_marker_round_trips_structured_sources() -> None:
    evidence = [
        {
            "sourceType": "web",
            "citation": "W1",
            "title": "Threat advisory",
            "url": "https://example.test/advisory",
        }
    ]

    assert parse_evidence_marker(build_evidence_marker(evidence)) == evidence


def test_html_and_pdf_reports_are_exportable() -> None:
    cape_case = build_case()

    html = build_html_report(cape_case).decode("utf-8")
    pdf = build_pdf_report(cape_case)

    assert "evil.example" in html
    assert "T1547.001" in html
    assert 'aria-label="Cipher Intelligence"' in html
    assert 'class="report-brand"' in html
    assert "中文总结与研判说明" in html
    assert "综合研判为高风险" in html
    assert "提取 3 项网络 IOC" in html
    assert "<h2>结论</h2>" in html
    assert "[C1]" in html
    assert "高优先级" in html
    assert pdf.startswith(b"%PDF")

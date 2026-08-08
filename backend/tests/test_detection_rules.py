from app.detection_rules import build_rule_report_html, build_rule_report_pdf, test_rule as run_rule_test, validate_rule


SIGMA_RULE = """title: Suspicious PowerShell
status: experimental
logsource:
  category: process_creation
  product: windows
detection:
  keywords:
    - powershell -enc
  condition: keywords
tags:
  - attack.t1059.001
"""

YARA_RULE = """rule Cipher_Test {
  strings:
    $marker = "cipher-malware-marker" ascii
  condition:
    $marker
}
"""


def test_sigma_validation_builds_siem_conversions() -> None:
    result = validate_rule("sigma", SIGMA_RULE)

    assert result.valid is True
    assert set(result.conversions) == {"splunk", "elastic", "sentinel"}
    assert result.attack_techniques == ["T1059.001"]


def test_yara_validation_and_uploaded_artifact_test() -> None:
    result = validate_rule("yara", YARA_RULE)
    test_result = run_rule_test(
        "yara",
        YARA_RULE,
        [("positive.bin", b"cipher-malware-marker"), ("negative.bin", b"clean")],
    )

    assert result.valid is True
    assert test_result["matchedArtifacts"] == 1
    assert test_result["results"][0]["matched"] is True


def test_rule_validation_reports_render_html_and_pdf() -> None:
    validation = validate_rule("sigma", SIGMA_RULE).as_dict()
    payload = {
        "id": 2,
        "caseId": 7,
        "ruleType": "sigma",
        "title": "Suspicious PowerShell",
        "content": SIGMA_RULE,
        "status": "validated",
        "version": 3,
        "validation": validation,
        "testRuns": [{"createdAt": "2026-08-06T10:00:00Z", "matchedArtifacts": 1, "totalArtifacts": 2, "falsePositiveCount": 0}],
    }

    assert "Splunk" in build_rule_report_html(payload).decode("utf-8")
    assert build_rule_report_pdf(payload).startswith(b"%PDF")

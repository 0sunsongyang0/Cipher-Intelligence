from __future__ import annotations

import json
import re

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import AnalysisTemplate, AnalysisTemplateVersion, OrganizationMember


BUILTIN_TEMPLATES = [
    ("malicious-office", "恶意 Office 文档", "分析可疑 Word、Excel、PowerPoint、RTF 与宏文档", "识别文档利用链、宏行为、外联与落地载荷；区分事实和推断，禁止执行样本。", ["确认文件类型、哈希与来源", "检查 OLE/OOXML 结构、宏与嵌入对象", "提取 URL、域名、IP、命令与落地文件", "映射 ATT&CK 并给出处置建议"], ["office-parser", "ioc-extractor"], "执行摘要；证据表；行为链；IOC；ATT&CK；结论与处置建议", ["sha256", "file_type", "source", "macro_or_exploit_evidence"], "chatgpt-5.4-az"),
    ("powershell", "PowerShell 样本", "分析脚本、命令行、编码载荷与日志片段", "安全地静态分析 PowerShell，逐层还原混淆和编码，说明能力与置信度，不运行未知代码。", ["记录原始命令与哈希", "还原 Base64、字符串拼接和混淆", "识别下载、持久化、凭据与防御规避", "提取 IOC 并映射 ATT&CK"], ["powershell-deobfuscator", "ioc-extractor"], "摘要；解混淆结果；行为与 ATT&CK；IOC；检测和响应建议", ["source_text", "sha256", "deobfuscation_steps"], "chatgpt-5.4-az"),
    ("phishing-email", "钓鱼邮件", "分析 EML、MSG、邮件头、正文、链接与附件", "以邮件取证流程分析欺诈与恶意投递，保留头部证据和 URL 原文，不访问未知链接。", ["验证 Received、From、Reply-To 与认证结果", "检查诱导话术、品牌仿冒和异常链接", "分析附件与跳转链", "形成封禁、检索与用户处置建议"], ["email-parser", "ioc-extractor"], "研判结论；邮件头证据；社工特征；链接/附件；IOC；处置范围", ["message_id", "sender", "received_chain", "authentication_results", "urls"], "claude-sonnet-4-6-az"),
    ("webshell", "WebShell", "分析 PHP、JSP、ASP.NET、Python 等可疑服务端脚本", "静态分析 WebShell 能力、入口、命令执行和持久化特征；不要补全可直接滥用的攻击代码。", ["确认语言、路径、哈希和时间戳", "识别输入入口、认证门槛与危险函数", "分析混淆、文件操作、命令和网络能力", "生成 IOC、狩猎与修复建议"], ["code-analysis", "ioc-extractor"], "摘要；入口与能力；调用链证据；IOC；影响范围；清除与加固", ["sha256", "server_path", "language", "dangerous_call_evidence"], "chatgpt-5.4-az"),
    ("ransomware-triage", "勒索软件初筛", "对勒索样本、赎金信、告警和主机迹象进行快速分诊", "执行防御性勒索软件初筛，优先识别家族线索、加密范围、横向移动与立即遏制事项；不得运行样本。", ["记录样本哈希、文件名与发现时间", "检查赎金信、扩展名、互斥体和服务", "识别加密、备份破坏、横向移动和 C2", "给出按优先级排序的遏制步骤"], ["malware-static", "ioc-extractor"], "严重度；关键证据；家族线索；影响面；IOC；立即/后续处置", ["sha256", "discovery_time", "host", "ransom_note_or_encryption_evidence"], "chatgpt-5.4-az"),
    ("linux-elf", "Linux ELF 分析", "分析 Linux ELF 可执行文件、共享库与内核模块", "静态分析 ELF 元数据、依赖、符号、段、持久化和网络行为；明确架构与动态链接上下文，不执行样本。", ["确认哈希、架构、位数与链接方式", "检查 ELF 头、段、符号、导入和字符串", "识别打包、反调试、提权、持久化与网络行为", "输出 IOC、ATT&CK 与主机狩猎建议"], ["elf-parser", "ioc-extractor"], "摘要；ELF 元数据；能力证据；IOC；ATT&CK；检测和响应建议", ["sha256", "architecture", "elf_type", "section_or_symbol_evidence"], "chatgpt-5.4-az"),
]


def snapshot(template: AnalysisTemplate) -> dict:
    return {"id": template.id, "slug": template.slug, "name": template.name, "scenario": template.scenario,
            "systemPrompt": template.system_prompt, "checklist": json.loads(template.checklist_json),
            "requiredSkills": json.loads(template.required_skills_json), "outputFormat": template.output_format,
            "requiredEvidenceFields": json.loads(template.required_evidence_json),
            "recommendedModel": template.recommended_model, "organizationId": template.organization_id,
            "status": template.status, "version": template.current_version}


def save_version(db: Session, template: AnalysisTemplate, user_id: int) -> None:
    db.add(AnalysisTemplateVersion(template_id=template.id, version=template.current_version,
                                   snapshot_json=json.dumps(snapshot(template), ensure_ascii=False), created_by_user_id=user_id))


def seed_builtins(db: Session, user_id: int) -> None:
    if db.execute(select(AnalysisTemplate.id).limit(1)).first():
        return
    for slug, name, scenario, prompt, checklist, skills, output, evidence, model in BUILTIN_TEMPLATES:
        item = AnalysisTemplate(slug=slug, name=name, scenario=scenario, system_prompt=prompt,
            checklist_json=json.dumps(checklist, ensure_ascii=False), required_skills_json=json.dumps(skills, ensure_ascii=False),
            output_format=output, required_evidence_json=json.dumps(evidence, ensure_ascii=False), recommended_model=model,
            status="published", created_by_user_id=user_id, updated_by_user_id=user_id)
        db.add(item); db.flush(); save_version(db, item, user_id)
    db.commit()


def visible_query(user_id: int):
    org_ids = select(OrganizationMember.organization_id).where(OrganizationMember.user_id == user_id)
    return select(AnalysisTemplate).where(or_(AnalysisTemplate.organization_id.is_(None), AnalysisTemplate.organization_id.in_(org_ids)))


def resolve_template(db: Session, template_id: int | None, user_id: int) -> tuple[AnalysisTemplate | None, dict | None]:
    if template_id is None:
        return None, None
    template = db.execute(visible_query(user_id).where(AnalysisTemplate.id == template_id, AnalysisTemplate.status == "published")).scalar_one_or_none()
    if template is None:
        raise HTTPException(400, "Template is unavailable or not visible")
    return template, snapshot(template)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "analysis-template"

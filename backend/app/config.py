from decimal import Decimal, ROUND_HALF_UP
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
DEFAULT_DATABASE_URL = f"sqlite:///{(BACKEND_DIR / 'data' / 'app.db').as_posix()}"
DEFAULT_PROMPT_CONFIG_PATH = BACKEND_DIR / "data" / "prompt-config.json"
DEFAULT_AVATAR_STORAGE_PATH = BACKEND_DIR / "data" / "avatars"
DEFAULT_CHAT_SYSTEM_PROMPT = """# Dual-Mode Autonomous AI Agent: General Daily Assistant + CAPE Sandbox Cybersecurity Analyst
You are a dual-mode autonomous AI Agent with two fully independent operating modes: General Daily Assistant Mode and CAPE Sandbox Threat Analysis Mode. You will automatically detect user intent and switch between modes based on input content - no manual mode-switch commands are required from the user. Security analysis mode takes precedence whenever a valid CAPE artifact or cybersecurity analysis request is detected. You must execute all analysis workflows strictly per the rules below, with no skipped steps or speculative conclusions.

### Global Language Rule (Highest Priority)
You must respond to all user inputs in Simplified Chinese by default. This rule applies to all output forms: daily conversations, analysis reports, summary tables, technical explanations, code comments, error prompts and compliance statements. You may only output content in other languages when the user explicitly requests so, or when the task is a dedicated translation assignment requiring target-language output. All section titles, table headers and report content in the CAPE analysis template must be rendered in Chinese during actual output.

---

## 1. Permanent General Daily Assistant Capabilities
Active by default for all non-security requests. Handle all general user requests with clear, concise, and accurate output:
- Productivity: schedule planning, document summarization, copywriting, data sorting, spreadsheet analysis, meeting minutes, email drafting
- Academic & technical support: knowledge Q&A, multi-language translation, mathematical computation, code writing/debugging across Python/C++/Go/Shell/JS, algorithm explanation, technical documentation drafting
- Daily life: travel planning, lifestyle advice, creative brainstorming, hobby discussion, casual conversation
- General file processing: read and interpret plain text, logs, JSON, CSV, Markdown, code files, and standard documents

---

## 2. CAPE Sandbox Auto-Analysis Mode
### 2.1 Automatic Trigger Logic
You will automatically pause general conversation and launch the full standardized analysis pipeline immediately if any of the following conditions are detected:
- User uploads compressed archives (.zip, .rar, .7z, .tar.gz) containing CAPE sandbox output artifacts
- User pastes raw CAPE report.json / static_analysis.json / dynamic_analysis.json content
- User requests malware analysis, sandbox forensics, threat research, pcap inspection, or any cybersecurity artifact analysis
- Auto-validation: verify the presence of canonical CAPE file structures first. If the uploaded file is not a valid CAPE output, perform general file parsing and inform the user clearly that the package is not a recognized CAPE sandbox output.

When the user returns to general topics (daily questions, productivity, lifestyle, general knowledge), you will automatically switch back to General Daily Assistant Mode seamlessly.

### 2.2 Mandatory Full Analysis Pipeline (Non-skippable)
Execute all steps sequentially, log evidence for every conclusion, and generate corresponding summary tables for core modules.

#### Step 1: Archive Inventory & Forensic Triage
- If you need to show the archive directory tree, render it only inside a fenced code block using plain text. Never place an ASCII tree in a normal paragraph.
- Categorize all artifacts by type: metadata reports, static logs, behavior logs, network captures, memory dumps, dropped files, screenshots, system logs
- Validate file integrity, flag corrupted, encrypted or empty artifacts
- Mark and prioritize high-value forensic files for deep analysis
- Always output a Markdown file inventory summary table with explicit columns

#### Step 2: Static Analysis Deep Dive
- File core metadata: MD5, SHA1, SHA256, SHA512 hashes, file type, size, architecture (x86/x64/ARM), compile timestamp, linker version, entry point address
- Executable structure analysis: import/export tables, section names & entropy values, resource section inspection, digital signature status (valid / invalid / missing)
- Packer & obfuscation detection: identify packers (UPX, ASProtect, Themida, etc.), crypters, code virtualization, high-entropy sections, and anti-disassembly techniques
- String extraction & classification: C2 endpoints (IP/domain/URL), hardcoded credentials, registry keys, file paths, command-line arguments, encryption keys, anti-debug and anti-sandbox strings
- Antivirus detection summary: aggregate AV detection results, threat naming consensus, and overall detection rate
- Output a static risk finding summary table

#### Step 3: Dynamic Behavior Analysis & TTP Mapping
- Process lifecycle: full process tree, process injection techniques (process hollowing, DLL injection, reflective loading, process doppelganging), parent-child process anomalies
- Persistence mechanisms: registry run keys, scheduled tasks, system services, startup folders, WMI event consumers, browser extension injection
- Privilege escalation: UAC bypass, token manipulation, exploit execution, unsigned driver loading
- System modification: file creation/deletion/overwrite, registry tampering, system configuration alteration, hosts file modification
- Information theft: keylogging, screen capture, clipboard access, browser credential stealing, document enumeration, webcam/microphone access
- Anti-analysis behavior: sandbox detection, anti-debug checks, anti-VM tricks, sleep skipping, conditional execution based on environment
- Map all observed behaviors to corresponding MITRE ATT&CK tactics and techniques
- Output a ranked malicious behavior summary table and a dedicated MITRE ATT&CK mapping table

#### Step 4: Network Traffic Forensics (pcap / network logs)
- Full connection inventory: source/destination IP, port, protocol (TCP/UDP/ICMP/DNS/HTTP/HTTPS)
- C2 communication analysis: beaconing pattern, heartbeat interval, user-agent strings, request methods, payload encoding scheme, data exfiltration volume
- Malicious network artifacts: malicious domains/URLs, DNS tunneling indicators, DGA-generated domains, proxy connections, Tor exit node traffic, peer-to-peer communication
- Download/upload activity: payload download URLs, hashes of downloaded files where available, data exfiltration endpoints
- Output a complete IOC summary table with risk ratings

#### Step 5: Dropped & Written Files Assessment
- Full inventory of all files written to disk during sample execution
- For each dropped file: record full file path, file name, hash value, file type, and classified functional purpose
- Flag secondary payloads, configuration files, decoy files, self-deletion scripts, and lateral movement tools
- Output a dropped payload detail table

#### Step 6: Memory Forensic Summary
- Injected modules and reflective DLLs identified in memory
- Unbacked memory regions and shellcode fragments
- Hardcoded configuration strings, C2 addresses, and decryption keys extracted from memory
- Evidence of process hollowing and process replacement
- Indicators of fileless malware and in-memory-only attacks

#### Step 7: Threat Classification & Risk Rating
- Malware family categorization: Ransomware, Remote Access Trojan (RAT), Info Stealer, Cryptominer, Botnet, Downloader/Dropper, Macro Malware, Worm, Backdoor, Rootkit
- Overall risk rating: Very Low / Low / Medium / High / Critical
  - Critical: enables full remote control, data encryption (ransomware), large-scale data exfiltration, or lateral movement capability
  - High: establishes persistence, steals sensitive information, or modifies system core configuration
  - Medium: performs unauthorized system changes or network communication without explicit user consent
  - Low: suspicious behavior but no direct destructive or theft action
  - Very Low: benign file with no malicious indicators
- Impact assessment: evaluate impact on data confidentiality, system integrity, service availability, and internal network security
- False positive elimination: explicitly rule out benign system behavior, legitimate software actions, and sandbox environment artifacts

---

## 3. Standardized Output Template (Mandatory for CAPE Reports)
All CAPE analysis reports must strictly follow the structure below. Every risk conclusion must include a short evidence snippet extracted directly from the CAPE raw logs. Core modules must use Markdown tables for summary presentation. Do not collapse tables into prose. Do not render archive trees or file inventories as wrapped inline text.

(示例如下)

===== CAPE 沙箱恶意样本安全分析报告 =====

1. 样本基础元数据
   [哈希、文件类型、架构、编译时间、签名状态的简要汇总]

2. 静态分析结果
   [概述 + 静态风险汇总表]
   | 风险项 | 类别 | 详情 | 严重程度 | 证据来源 |
   |--------|------|------|----------|----------|
   | [项] | [加壳/字符串/PE结构] | [描述] | [高/中/低] | [CAPE日志片段] |

3. 动态行为汇总
   [概述 + 恶意行为分级统计表]
   | 行为类别 | 具体动作 | 风险等级 | MITRE技术编号 | 证据 |
   |----------|----------|----------|---------------|------|
   | [持久化] | [创建注册表启动项] | [高] | [T1547.001] | [CAPE日志片段] |

4. MITRE ATT&CK 战术与技术映射
   [专属映射表]
   | 战术 | 技术编号 | 技术名称 | 观测到的行为 |
   |------|----------|----------|--------------|
   | 执行 | T1059.003 | 命令与脚本解释器：Windows命令行 | [观测行为] |
   | 持久化 | T1547.001 | 启动或登录自动执行：注册表运行键/启动文件夹 | [观测行为] |

5. 网络威胁指标(IOC)清单
   [完整结构化IOC表]
   | IOC类型 | 数值 | 端口/协议 | 风险评级 | 描述 |
   |---------|------|-----------|----------|------|
   | IP地址 | 192.168.x.x | 443 / TCP | 高危 | C2命令控制服务器 |
   | 域名 | malicious.example.com | 80 / HTTP | 高危 | 载荷下载主机 |
   | URL | http://example.com/payload.exe | 80 / HTTP | 高危 | 第二阶段下载链接 |

6. 释放恶意载荷列表
   [释放文件详情表]
   | 文件路径 | 文件名 | SHA256哈希 | 文件类型 | 功能用途 | 风险等级 |
   |----------|--------|------------|----------|----------|----------|
   | C:\\Users\\x\\AppData\\ | payload.exe | [哈希值] | PE32可执行文件 | 第二阶段后门 | 高危 |

7. 内存取证关键信息
   [注入模块、硬编码配置、Shellcode发现项的要点汇总]

8. 威胁分类与整体风险等级
   [明确最终判定 + 风险判定依据]

9. 完整攻击链路还原
   [分步叙述：执行 -> 持久化 -> 权限提升 -> 防御规避 -> 命令控制 -> 数据窃取]

10. 应急响应处置手册
    - 单主机修复步骤
    - 内网隔离与处置建议

11. 检测与防御加固建议
    - EDR检测规则、防火墙策略、系统加固方案

12. 可导出纯文本IOC汇总
    [可直接复制粘贴，按类型分组，每行一条]

===== 报告结束 =====

---

## 4. Available Analysis Commands
Users may invoke the following commands at any time during security analysis:
- Report variants
  - `Executive Summary`: 1-page high-level summary with key tables for non-technical stakeholders
  - `Brief Report`: Condensed output with only core risk tables and IOC list
  - `Full Technical Report`: Complete report with full raw log snippets and granular details
  - `Export IOC List`: Standalone plain-text block of all indicators for SIEM / threat platform import
- Special analysis functions
  - `Generate Detection Rules`: Output Yara rules, Sigma rules, Suricata IDS signatures, and EDR detection queries
  - `Show Attack Chain`: Step-by-step reconstruction of the full malware lifecycle
  - `Show MITRE Matrix`: Complete ATT&CK technique mapping table
  - `Extract [target]`: Custom extraction for specific data (e.g. all persistence mechanisms, all network connections, all strings)

---

## 5. Error Handling & Edge Cases
- Corrupted / password-protected archives: Notify the user explicitly and request a valid, unencrypted file
- Non-CAPE compressed files: Perform general file content analysis, and clearly inform the user that the file is not a recognized CAPE sandbox output
- Missing critical artifacts: Explicitly list all missing forensic files (e.g. pcap, report.json), state the impact on analysis depth, and perform limited analysis based on available data; leave corresponding table rows blank with a "Data unavailable" note
- Unsupported file formats: Notify the user and list compatible input formats
- Overly large datasets: Summarize top high-risk entries in tables first, and offer to expand to full lists upon request
- Ambiguous or inconclusive evidence: Clearly mark conclusions as "Suspected" in tables and explain the uncertainty

---

## 6. Compliance & Safety Guardrails
1. All analysis outputs are strictly for legitimate cybersecurity research, incident response, threat hunting, and educational purposes only.
2. Never generate, modify, or assist with the creation of malware, exploits, evasion tools, or any unauthorized offensive cybersecurity tools.
3. Do not assist with any activity that violates applicable local, national, or international laws or regulations.
4. Disclaimer: All analysis conclusions are automated auxiliary judgments. They do not replace professional cybersecurity tools and expert verification.
5. Do not process or analyze samples containing illegal content, personal privacy data, or classified information."""


class Settings(BaseSettings):
    app_name: str = "\u5154\u5154\u70b8\u5f39\u7684\u5927\u6a21\u578b\u52a9\u624b"
    app_env: str = "production"
    app_access_password: str = "change-me"
    session_secret: str = "change-me-too"
    session_cookie_secure: bool | None = None
    deepseek_api_key: str = "unset"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    smart_model_routing_enabled: bool = True
    smart_model_routing_economy_model: str = "deepseek-v4-flash"
    smart_model_routing_strong_model: str = "deepseek-v4-pro"
    smart_model_routing_long_context_tokens: int = 32_000
    smart_model_routing_daily_budget_microusd: int = 0
    smart_model_routing_timeout_seconds: float = 60.0
    smart_model_routing_failure_threshold: int = 2
    smart_model_routing_cooldown_seconds: float = 30.0
    cape_base_url: str = "http://127.0.0.1:8080"
    cape_api_token: str = ""
    cape_poll_interval_seconds: float = 5.0
    cape_submit_timeout_seconds: float = 30.0
    cape_query_timeout_seconds: float = 20.0
    cape_task_cost_microusd: int = 0
    cape_task_cost_cny: Decimal = Decimal("1")
    billing_cny_per_usd: Decimal = Decimal("7.2")
    openai_proxy_base_url: str = "http://[private-ip]:3887/v1"
    openai_official_api_key: str = "unset"
    retention_cleanup_interval_seconds: int = 86400
    retention_upload_days: int = 30
    openai_aws_api_key: str = "unset"
    openai_az_api_key: str = "unset"
    openai_backup_api_key: str = "unset"
    claude_official_api_key: str = "unset"
    claude_az_api_key: str = "unset"
    claude_backup_api_key: str = "unset"
    search_provider: str = "tavily"
    search_result_limit: int = 5
    search_timeout_seconds: float = 12.0
    tavily_api_key: str = "unset"
    tavily_search_depth: str = "advanced"
    tavily_news_time_range: str = "day"
    virustotal_api_key: str = ""
    urlhaus_api_key: str = ""
    misp_url: str = ""
    misp_api_key: str = ""
    ioc_provider_config_json: str = "{}"
    prompt_config_path: str = str(DEFAULT_PROMPT_CONFIG_PATH)
    chat_system_prompt: str = DEFAULT_CHAT_SYSTEM_PROMPT
    database_url: str = DEFAULT_DATABASE_URL
    avatar_storage_path: str = str(DEFAULT_AVATAR_STORAGE_PATH)
    casdoor_enabled: bool = False
    casdoor_endpoint: str = ""
    casdoor_internal_endpoint: str = ""
    casdoor_client_id: str = ""
    casdoor_client_secret: str = ""
    casdoor_organization_name: str = ""
    casdoor_application_name: str = ""
    casdoor_application_owner: str = "admin"
    casdoor_display_name: str = "Casdoor"
    casdoor_scope: str = "openid profile email"
    casdoor_redirect_uri: str = ""
    casdoor_admin_redirect_uri: str = ""
    casdoor_auto_create_users: bool = True
    casdoor_auto_link_users: bool = False
    casdoor_admin_users: str = ""
    casdoor_admin_roles: str = ""
    casdoor_role_mapping: str = ""
    casdoor_sync_groups_as_workspaces: bool = True
    casdoor_commerce_enabled: bool = False
    casdoor_plan_tier_mapping: str = ""
    casdoor_timeout_seconds: float = 15.0

    model_config = SettingsConfigDict(
        # Tests must be hermetic: production credentials in a developer's .env
        # must never change the test application configuration.
        env_file=() if os.environ.get("APP_ENV", "").casefold() == "test" else (
            str(BACKEND_DIR / ".env"), str(REPO_ROOT / ".env")
        ),
        extra="ignore",
    )

    def __init__(self, **values):
        super().__init__(**values)
        if self.app_env not in {"development", "test"} and (
            self.app_access_password == "change-me"
            or self.session_secret == "change-me-too"
        ):
            raise ValueError(
                "default auth secrets are not allowed outside explicit test/development mode"
            )
        if self.casdoor_enabled and not self.casdoor_configured:
            raise ValueError(
                "CASDOOR_ENABLED requires CASDOOR_ENDPOINT, CASDOOR_CLIENT_ID, "
                "CASDOOR_CLIENT_SECRET, CASDOOR_ORGANIZATION_NAME and "
                "CASDOOR_APPLICATION_NAME"
            )
        if self.billing_cny_per_usd <= 0:
            raise ValueError("BILLING_CNY_PER_USD must be greater than zero")

    @property
    def session_cookie_secure_enabled(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.app_env == "production"

    @property
    def effective_cape_task_cost_microusd(self) -> int:
        if self.cape_task_cost_microusd > 0:
            return self.cape_task_cost_microusd
        cape_cost_cny = Decimal(str(self.cape_task_cost_cny))
        cny_per_usd = Decimal(str(self.billing_cny_per_usd))
        if cape_cost_cny <= 0:
            return 0
        microusd = cape_cost_cny * Decimal(1_000_000) / cny_per_usd
        return int(microusd.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @property
    def casdoor_configured(self) -> bool:
        return all(
            value.strip()
            for value in (
                self.casdoor_endpoint,
                self.casdoor_client_id,
                self.casdoor_client_secret,
                self.casdoor_organization_name,
                self.casdoor_application_name,
            )
        )

    @property
    def casdoor_auth_enabled(self) -> bool:
        # Settings validation rejects incomplete production configuration. Keep
        # the runtime flag authoritative so test and embedded configurations can
        # explicitly enable the provider without duplicating all deployment data.
        return self.casdoor_enabled

    @staticmethod
    def _comma_separated_values(value: str) -> set[str]:
        return {item.strip().casefold() for item in value.split(",") if item.strip()}

    @property
    def casdoor_admin_user_set(self) -> set[str]:
        return self._comma_separated_values(self.casdoor_admin_users)

    @property
    def casdoor_admin_role_set(self) -> set[str]:
        return self._comma_separated_values(self.casdoor_admin_roles)

    @property
    def casdoor_cipher_role_mapping(self) -> dict[str, str]:
        defaults = {
            "cipher-owner": "owner", "owner": "owner",
            "cipher-admin": "admin", "admin": "admin",
            "soc-analyst": "analyst", "analyst": "analyst",
            "soc-reviewer": "reviewer", "reviewer": "reviewer",
            "cipher-viewer": "viewer", "viewer": "viewer",
        }
        if not self.casdoor_role_mapping.strip():
            return defaults
        try:
            parsed = __import__("json").loads(self.casdoor_role_mapping)
        except (ValueError, TypeError):
            return defaults
        if not isinstance(parsed, dict):
            return defaults
        allowed = {"owner", "admin", "analyst", "reviewer", "viewer"}
        defaults.update({str(key).strip().casefold(): str(value).strip().casefold() for key, value in parsed.items() if str(value).strip().casefold() in allowed})
        return defaults

    @property
    def casdoor_subscription_tier_mapping(self) -> dict[str, str]:
        defaults = {
            "cipher-free": "free", "free": "free",
            "cipher-standard": "standard", "standard": "standard",
            "cipher-pro": "pro", "pro": "pro",
            "cipher-enterprise": "enterprise", "enterprise": "enterprise",
        }
        if not self.casdoor_plan_tier_mapping.strip():
            return defaults
        try:
            parsed = __import__("json").loads(self.casdoor_plan_tier_mapping)
        except (ValueError, TypeError):
            return defaults
        if not isinstance(parsed, dict):
            return defaults
        allowed = {"free", "standard", "pro", "enterprise"}
        defaults.update({str(key).strip().casefold(): str(value).strip().casefold()
            for key, value in parsed.items() if str(value).strip().casefold() in allowed})
        return defaults


settings = Settings()

import json
from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator


ChatModelId = Literal[
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "chatgpt-5.5-official",
    "chatgpt-5.4-az",
    "chatgpt-5.5-backup",
    "chatgpt-5.4-backup",
    "claude-opus-4-7-official",
    "claude-opus-4-6-aws",
    "claude-sonnet-4-6-az",
    "claude-opus-4-7-backup",
    "claude-opus-4-6-backup",
    "claude-sonnet-4-6-backup",
]


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str
    inviteCode: str
    displayName: str | None = None
    avatarDataUrl: str | None = None

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip()
        if not 3 <= len(normalized) <= 64:
            raise ValueError("Username must be between 3 and 64 characters")
        return normalized

    @field_validator("displayName")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) > 80:
            raise ValueError("Display name must be 80 characters or fewer")
        return normalized


class LoginRequest(BaseModel):
    username: str | None = None
    password: str
    passcode: str | None = Field(default=None, pattern=r"^\d{6}$")
    recoveryCode: str | None = Field(default=None, max_length=64)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class UserPayload(BaseModel):
    id: int
    username: str
    displayName: str
    avatarUrl: str | None
    isAdmin: bool


class ConnectedAccountPayload(BaseModel):
    provider: str
    label: str


class AccountProviderPayload(BaseModel):
    provider: str
    label: str
    connected: bool
    authorizationUrl: str | None = None


class AccountProviderListPayload(BaseModel):
    items: list[AccountProviderPayload]


class AccountIdentityPayload(BaseModel):
    source: Literal["local", "casdoor"]
    providerName: str
    email: str | None = None
    emailVerified: bool = False
    connectedAccounts: list[ConnectedAccountPayload] = Field(default_factory=list)
    mfaEnabled: bool = False
    passwordEnabled: bool = False
    lastSignInAt: str | None = None
    lastSyncedAt: datetime | None = None
    syncStatus: Literal["local", "current", "stale"] = "local"
    syncAvailable: bool = False
    managementUrl: str = ""


class AccountOverview(BaseModel):
    user: UserPayload
    workspaceAvatarUrl: str | None = None
    identityAvatarUrl: str | None = None
    identity: AccountIdentityPayload


class AccountSecurityOverview(BaseModel):
    authSource: Literal["local", "casdoor", "hybrid"]
    localPasswordEnabled: bool
    totpEnabled: bool
    recoveryCodesRemaining: int
    suspiciousLoginAlerts: bool


class ReauthenticationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str | None = Field(default=None, max_length=1024)
    passcode: str | None = Field(default=None, pattern=r"^\d{6}$")


class PasswordChangeRequest(ReauthenticationRequest):
    newPassword: str = Field(min_length=8, max_length=1024)


class TotpSetupRequest(ReauthenticationRequest):
    pass


class LocalTotpConfirmRequest(ReauthenticationRequest):
    secret: str = Field(min_length=16, max_length=128)
    confirmationCode: str = Field(pattern=r"^\d{6}$")


class RecoveryCodePayload(BaseModel):
    codes: list[str]


class SessionItemPayload(BaseModel):
    id: int
    current: bool
    ipAddress: str | None
    userAgent: str | None
    createdAt: datetime
    lastSeenAt: datetime


class LoginEventPayload(BaseModel):
    id: int
    method: str
    outcome: str
    suspicious: bool
    ipAddress: str | None
    userAgent: str | None
    createdAt: datetime


class SecurityAlertUpdate(BaseModel):
    enabled: bool


class AccountEmailVerificationResponse(BaseModel):
    email: str
    sent: bool = True
    message: str = "Verification email sent"


class AccountEmailCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 12 or not normalized.isdigit():
            raise ValueError("Verification code must contain 1 to 12 digits")
        return normalized


class AccountMfaSetupPayload(BaseModel):
    secret: str
    recoveryCode: str
    otpauthUri: str


class AccountMfaConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: str
    recoveryCode: str
    passcode: str

    @field_validator("secret", "recoveryCode")
    @classmethod
    def validate_mfa_secret(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 256:
            raise ValueError("Invalid MFA setup value")
        return normalized

    @field_validator("passcode")
    @classmethod
    def validate_passcode(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) != 6 or not normalized.isdigit():
            raise ValueError("Authenticator code must contain 6 digits")
        return normalized


class AccountUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    displayName: str | None = None
    email: str | None = None
    avatarDataUrl: str | None = None
    removeAvatar: bool = False

    @field_validator("displayName")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Display name cannot be blank")
        if len(normalized) > 80:
            raise ValueError("Display name must be 80 characters or fewer")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Email cannot be blank")
        if len(normalized) > 254:
            raise ValueError("Email must be 254 characters or fewer")
        local, separator, domain = normalized.rpartition("@")
        if (
            separator != "@"
            or normalized.count("@") != 1
            or not local
            or not domain
            or "." not in domain
            or any(character.isspace() for character in normalized)
        ):
            raise ValueError("Enter a valid email address")
        return normalized


class SessionStatus(BaseModel):
    authenticated: bool
    user: UserPayload | None = None


class CasdoorAuthConfig(BaseModel):
    enabled: bool
    provider: Literal["casdoor"] = "casdoor"
    displayName: str = "Casdoor"
    managementUrl: str = ""


class AuthSuccess(SessionStatus):
    pass


class AdminInviteItem(BaseModel):
    id: int
    code: str
    label: str
    isActive: bool
    maxUses: int | None
    usedCount: int
    expiresAt: datetime | None
    createdAt: datetime


class AdminInviteListResponse(BaseModel):
    items: list[AdminInviteItem]


class AdminInviteCreateRequest(BaseModel):
    code: str
    label: str = ""
    maxUses: int | None = None
    expiresAt: datetime | None = None
    isActive: bool = True

    @field_validator("maxUses")
    @classmethod
    def validate_max_uses(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("maxUses must be greater than 0")
        return value


class ConversationCreate(BaseModel):
    title: str
    templateId: int | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Conversation title cannot be blank")
        if len(normalized) > 255:
            raise ValueError("Conversation title must be 255 characters or fewer")
        return normalized


class ConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    isPinned: bool | None = None
    isArchived: bool | None = None
    caseStatus: Literal["open", "investigating", "contained", "closed"] | None = None
    severity: Literal["unknown", "low", "medium", "high", "critical"] | None = None
    assignee: str | None = None
    tags: list[str] | None = None
    caseSummary: str | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Conversation title cannot be blank")
        if len(normalized) > 255:
            raise ValueError("Conversation title must be 255 characters or fewer")
        return normalized

    @field_validator("assignee")
    @classmethod
    def normalize_assignee(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) > 80:
            raise ValueError("Assignee must be 80 characters or fewer")
        return normalized or ""

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            tag = item.strip()
            if not tag or tag in normalized:
                continue
            if len(tag) > 32:
                raise ValueError("Each tag must be 32 characters or fewer")
            normalized.append(tag)
        if len(normalized) > 12:
            raise ValueError("A case can have at most 12 tags")
        return normalized

    @field_validator("caseSummary")
    @classmethod
    def normalize_case_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) > 4000:
            raise ValueError("Case summary must be 4000 characters or fewer")
        return normalized or ""


class ConversationImportMessage(BaseModel):
    role: str
    content: str
    attachments: list["MessageAttachmentItem"] = []


class ConversationImportRequest(BaseModel):
    title: str
    messages: list[ConversationImportMessage]


class ConversationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    is_pinned: bool
    is_archived: bool
    case_status: str
    severity: str
    assignee: str | None
    tags: list[str]
    case_summary: str | None
    analysis_template_id: int | None = None
    analysis_template_version: int | None = None
    analysis_config: dict | None = None
    created_at: datetime
    updated_at: datetime


class ConversationList(BaseModel):
    items: list[ConversationItem]


class ConversationImportResult(ConversationItem):
    importedMessages: int


class ChatMessageInput(BaseModel):
    role: str
    content: str
    attachments: list["MessageAttachmentItem"] = []


class MessageAttachmentItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(validation_alias=AliasChoices("attachment_id", "id"))
    name: str
    type: str
    size: int
    meta: str | None = None


class MessageEvidenceItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | str
    sourceType: str = Field(validation_alias=AliasChoices("source_type", "sourceType"))
    citation: str
    title: str
    url: str | None = None
    locator: str | None = None
    snippet: str | None = None
    reviewStatus: str = Field(default="pending", validation_alias=AliasChoices("review_status", "reviewStatus"))
    sourceTrust: int = Field(default=50, validation_alias=AliasChoices("source_trust", "sourceTrust"))
    confidence: int = 50
    acquiredAt: datetime | None = Field(default=None, validation_alias=AliasChoices("acquired_at", "acquiredAt"))
    contentHash: str | None = Field(default=None, validation_alias=AliasChoices("content_hash", "contentHash"))
    snapshotUrl: str | None = Field(default=None, validation_alias=AliasChoices("snapshot_url", "snapshotUrl"))
    reviewNote: str | None = Field(default=None, validation_alias=AliasChoices("review_note", "reviewNote"))
    reviewedBy: str | None = Field(default=None, validation_alias=AliasChoices("reviewed_by", "reviewedBy"))
    reviewedAt: datetime | None = Field(default=None, validation_alias=AliasChoices("reviewed_at", "reviewedAt"))


class ChatRequest(BaseModel):
    messages: list[ChatMessageInput]
    model: ChatModelId = "deepseek-v4-flash"
    conversationId: str | None = None
    zipContextId: str | None = None
    webSearch: bool = False
    responseLanguage: Literal["zh-CN", "en"] | None = None
    responseLength: Literal["concise", "balanced", "detailed"] | None = None
    uploadedFileIds: list[str] = []
    forceModel: bool = False
    taskType: str | None = Field(default=None, max_length=64)
    riskLevel: Literal["low", "normal", "high", "critical"] = "normal"


class UploadZipResponse(BaseModel):
    zipContextId: str
    archiveName: str
    entryCount: int
    extractedEntryCount: int
    inventoryOnlyCount: int
    skippedEntryCount: int
    supportedByCurrentModel: bool
    unsupportedReason: str | None = None
    uploading: bool = False
    errorMessage: str | None = None


class UploadZipRequest(BaseModel):
    conversationId: str
    model: ChatModelId


class CapeSubmitResponse(BaseModel):
    taskId: int
    status: str
    reusedExistingTask: bool = False


class CapeTaskStatusResponse(BaseModel):
    taskId: int
    status: str
    completed: bool
    score: float | None = None
    targetFilename: str | None = None
    machine: str | None = None


class CapeIocSummary(BaseModel):
    domains: list[str]
    ips: list[str]
    urls: list[str]


class CapeTacticItem(BaseModel):
    technique: str
    signature: str
    description: str


class CapeDroppedFileItem(BaseModel):
    name: str
    path: str
    type: str
    sha256: str


class CapeAnalysisSummaryResponse(BaseModel):
    taskId: int
    status: str
    score: float | None = None
    submittedFilename: str | None = None
    sha256: str | None = None
    iocs: CapeIocSummary
    tactics: list[CapeTacticItem]
    droppedFiles: list[CapeDroppedFileItem]
    processes: list[dict] = Field(default_factory=list)
    networkConnections: list[dict] = Field(default_factory=list)
    signatures: list[dict]


class CapeCaseResponse(BaseModel):
    id: int
    conversationId: int
    taskId: int
    sampleName: str
    status: str
    completed: bool
    score: float | None = None
    targetFilename: str | None = None
    machine: str | None = None
    sha256: str | None = None
    reusedExistingTask: bool = False
    summary: CapeAnalysisSummaryResponse | None = None
    createdAt: datetime
    updatedAt: datetime


class CapeCaseListResponse(BaseModel):
    items: list[CapeCaseResponse]


CaseStatus = Literal["open", "triage", "investigating", "review", "confirmed", "contained", "remediating", "closed"]
CaseSeverity = Literal["unknown", "low", "medium", "high", "critical"]


class InvestigationCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    status: CaseStatus = "open"
    severity: CaseSeverity = "unknown"
    assignee: str | None = None
    tags: list[str] = Field(default_factory=list)
    summary: str | None = None
    priority: int = Field(default=3, ge=1, le=5)
    slaDueAt: datetime | None = None
    parentCaseId: int | None = None
    conversationIds: list[int] = Field(default_factory=list)
    workspaceId: int | None = None
    assigneeUserId: int | None = None
    templateId: int | None = None

    @field_validator("title")
    @classmethod
    def normalize_case_title(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 255:
            raise ValueError("Case title must contain 1 to 255 characters")
        return value

    @field_validator("tags")
    @classmethod
    def normalize_case_tags(cls, value: list[str]) -> list[str]:
        tags = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if len(tags) > 12 or any(len(item) > 32 for item in tags):
            raise ValueError("Cases support up to 12 tags of 32 characters each")
        return tags


class InvestigationCaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    status: CaseStatus | None = None
    statusReason: str | None = Field(default=None, max_length=2000)
    severity: CaseSeverity | None = None
    assignee: str | None = None
    tags: list[str] | None = None
    summary: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    slaDueAt: datetime | None = None
    parentCaseId: int | None = None
    assigneeUserId: int | None = None


OrganizationRole = Literal["owner", "admin", "analyst", "reviewer", "viewer"]


class OrganizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")


class MemberUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    role: OrganizationRole


class CaseAccessUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    permission: Literal["viewer", "editor"] = "viewer"


class CaseCommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=4000)


EvidenceReviewStatus = Literal["pending", "verified", "rejected"]
ConclusionStatus = Literal["draft", "verified", "rejected"]
ConclusionClaimType = Literal["fact", "inference"]
CrossCheckVerdict = Literal["supports", "contradicts", "inconclusive"]


class ConclusionCrossCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    modelId: str = Field(min_length=1, max_length=96)
    verdict: CrossCheckVerdict
    confidence: int = Field(ge=0, le=100)
    rationale: str = Field(min_length=1, max_length=2000)
    checkedAt: datetime | None = None


class ConclusionCrossCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    modelId: ChatModelId


class CaseEvidenceReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewStatus: EvidenceReviewStatus
    sourceTrust: int = Field(ge=0, le=100)
    confidence: int = Field(ge=0, le=100)
    acquiredAt: datetime | None = None
    contentHash: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    snapshotUrl: str | None = None
    reviewNote: str | None = Field(default=None, max_length=2000)


class CaseConclusionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str = Field(min_length=1, max_length=4000)
    status: ConclusionStatus = "draft"
    confidence: int = Field(default=50, ge=0, le=100)
    claimType: ConclusionClaimType = "inference"
    confidenceRationale: str | None = Field(default=None, max_length=2000)
    evidenceIds: list[int] = Field(default_factory=list)
    conflictEvidenceIds: list[int] = Field(default_factory=list)
    crossChecks: list[ConclusionCrossCheck] = Field(default_factory=list, max_length=12)


class CaseConclusionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str | None = Field(default=None, min_length=1, max_length=4000)
    status: ConclusionStatus | None = None
    confidence: int | None = Field(default=None, ge=0, le=100)
    claimType: ConclusionClaimType | None = None
    confidenceRationale: str | None = Field(default=None, max_length=2000)
    evidenceIds: list[int] | None = None
    conflictEvidenceIds: list[int] | None = None
    crossChecks: list[ConclusionCrossCheck] | None = Field(default=None, max_length=12)


class CaseSignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signer: str = Field(min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=2000)


class CaseConversationAdd(BaseModel):
    conversationIds: list[int]


class CaseMergeRequest(BaseModel):
    targetCaseId: int


IndicatorType = Literal["domain", "ip", "url", "md5", "sha1", "sha256"]
IndicatorRisk = Literal["unknown", "low", "medium", "high", "critical"]
IndicatorStatus = Literal["pending", "malicious", "suspicious", "false_positive", "blocked"]


class CaseIndicatorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    riskLevel: IndicatorRisk | None = None
    confidence: int | None = Field(default=None, ge=0, le=100)
    status: IndicatorStatus | None = None
    expiresAt: datetime | None = None


class CaseIndicatorBulkUpdate(BaseModel):
    ids: list[int] = Field(min_length=1)
    status: IndicatorStatus


class CaseIndicatorEnrichRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    providers: list[str] | None = None
    force: bool = False


class CaseIndicatorItem(BaseModel):
    id: int
    type: IndicatorType
    value: str
    riskLevel: IndicatorRisk
    confidence: int
    status: IndicatorStatus
    sourceType: str
    capeCaseId: int | None
    sampleName: str | None
    firstSeenAt: datetime
    lastSeenAt: datetime
    expiresAt: datetime | None
    enrichment: dict


class CaseIndicatorList(BaseModel):
    items: list[CaseIndicatorItem]
    total: int
    counts: dict[str, dict[str, int]]


DetectionRuleType = Literal["sigma", "yara"]
DetectionRuleStatus = Literal["draft", "validated", "approved", "deployed"]


class DetectionRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ruleType: DetectionRuleType
    title: str
    content: str
    sourceCapeCaseId: int | None = None

    @field_validator("title", "content")
    @classmethod
    def require_rule_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Detection rule fields cannot be blank")
        return value


class DetectionRuleGenerateRequest(BaseModel):
    capeCaseIds: list[int] = Field(default_factory=list)
    ruleTypes: list[DetectionRuleType] = Field(default_factory=lambda: ["sigma", "yara"])


class DetectionRuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    content: str | None = None
    status: DetectionRuleStatus | None = None


class DetectionRuleVersionItem(BaseModel):
    id: int
    version: int
    validationStatus: str
    actor: str | None
    createdAt: datetime


class DetectionRuleTestRunItem(BaseModel):
    id: int
    totalArtifacts: int
    matchedArtifacts: int
    falsePositiveCount: int
    results: list[dict]
    createdAt: datetime


class DetectionRuleItem(BaseModel):
    id: int
    caseId: int
    sourceCapeCaseId: int | None
    ruleType: DetectionRuleType
    title: str
    content: str
    status: DetectionRuleStatus
    version: int
    validationStatus: str
    validation: dict
    lastValidatedAt: datetime | None
    approvedAt: datetime | None
    deployedAt: datetime | None
    versions: list[DetectionRuleVersionItem] = Field(default_factory=list)
    testRuns: list[DetectionRuleTestRunItem] = Field(default_factory=list)
    createdAt: datetime
    updatedAt: datetime


class DetectionRuleList(BaseModel):
    items: list[DetectionRuleItem]
    counts: dict[str, int]


PlaybookStepStatus = Literal["pending", "running", "waiting_approval", "completed", "failed"]


class PlaybookTemplateItem(BaseModel):
    id: str
    title: str
    description: str
    steps: list[str]


class PlaybookCreate(BaseModel):
    templateId: str


class PlaybookStepAction(BaseModel):
    input: dict = Field(default_factory=dict)
    output: dict = Field(default_factory=dict)
    error: str | None = None


class PlaybookStepItem(BaseModel):
    id: int
    key: str
    position: int
    title: str
    status: PlaybookStepStatus
    input: dict
    output: dict
    error: str | None
    attemptCount: int
    requiresApproval: bool
    approvedAt: datetime | None
    approvedBy: str | None
    startedAt: datetime | None
    completedAt: datetime | None


class PlaybookItem(BaseModel):
    id: int
    caseId: int
    templateId: str
    title: str
    status: str
    progress: int
    steps: list[PlaybookStepItem]
    createdAt: datetime
    updatedAt: datetime
    completedAt: datetime | None


class PlaybookList(BaseModel):
    items: list[PlaybookItem]


class InvestigationCaseEventItem(BaseModel):
    id: int
    eventType: str
    title: str
    detail: str | None
    metadata: dict
    actor: str | None
    createdAt: datetime


class InvestigationCaseConversationItem(BaseModel):
    id: int
    title: str
    updatedAt: datetime
    messageCount: int
    sampleCount: int


class InvestigationCaseItem(BaseModel):
    id: int
    title: str
    status: str
    severity: str
    assignee: str | None
    organizationId: int | None = None
    workspaceId: int | None = None
    assigneeUserId: int | None = None
    tags: list[str]
    summary: str | None
    analysisTemplateId: int | None = None
    analysisTemplateVersion: int | None = None
    analysisConfig: dict | None = None
    priority: int
    slaDueAt: datetime | None
    overdue: bool
    parentCaseId: int | None
    mergedIntoCaseId: int | None
    childCaseIds: list[int]
    conversationCount: int
    sampleCount: int
    capeTaskCount: int
    iocCount: int
    createdAt: datetime
    updatedAt: datetime
    closedAt: datetime | None
    conversations: list[InvestigationCaseConversationItem] = Field(default_factory=list)
    capeCases: list[CapeCaseResponse] = Field(default_factory=list)
    timeline: list[InvestigationCaseEventItem] = Field(default_factory=list)


class InvestigationCaseList(BaseModel):
    items: list[InvestigationCaseItem]
    counts: dict[str, int]


def parse_chat_request_json(raw: str) -> ChatRequest:
    parsed = json.loads(raw)
    if isinstance(parsed, list):
        messages = TypeAdapter(list[ChatMessageInput]).validate_python(parsed)
        return ChatRequest(messages=messages)
    return ChatRequest.model_validate(parsed)


class MessageItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str
    content: str
    created_at: datetime
    attachments: list[MessageAttachmentItem] = []
    evidence: list[MessageEvidenceItem] = []


class MessageList(BaseModel):
    items: list[MessageItem]
    nextCursor: int | None = None
    total: int | None = None


class MessageFeedbackRequest(BaseModel):
    rating: Literal["up", "down"] | None = None
    reason: Literal["factual_error", "citation_error", "formatting", "not_helpful", "other"] | None = None
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_reason(self) -> "MessageFeedbackRequest":
        if self.rating == "down" and self.reason is None:
            raise ValueError("A reason is required for negative feedback")
        return self


class MessageFeedbackResponse(BaseModel):
    messageId: int
    rating: str | None
    reason: str | None = None

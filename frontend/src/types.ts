export type ChatRole = "system" | "user" | "assistant";

export type AuthUser = {
  id: number;
  username: string;
  displayName?: string;
  avatarUrl?: string | null;
  isAdmin: boolean;
};

export type SessionStatus = {
  authenticated: boolean;
  user: AuthUser | null;
};

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type Job = {
  id: number;
  taskType: string;
  status: JobStatus;
  progress: number;
  progressMessage: string | null;
  result: Record<string, unknown> | null;
  errorMessage: string | null;
  retryCount: number;
  maxRetries: number;
  timeoutSeconds: number;
  startedAt: string | null;
  completedAt: string | null;
  createdAt: string;
  updatedAt: string;
};

export type AnalysisTemplate = {
  id: number; slug: string; name: string; scenario: string; systemPrompt: string;
  checklist: string[]; requiredSkills: string[]; outputFormat: string;
  requiredEvidenceFields: string[]; recommendedModel: string; organizationId: number | null;
  status: "draft" | "published" | "disabled"; version: number;
};

export type CasdoorAuthConfig = {
  enabled: boolean;
  provider: "casdoor";
  displayName: string;
  managementUrl: string;
};

export type ConnectedAccount = {
  provider: string;
  label: string;
};

export type AccountProvider = ConnectedAccount & {
  connected: boolean;
  authorizationUrl: string | null;
};

export type AccountIdentity = {
  source: "local" | "casdoor";
  providerName: string;
  email: string | null;
  emailVerified: boolean;
  connectedAccounts: ConnectedAccount[];
  mfaEnabled: boolean;
  passwordEnabled: boolean;
  lastSignInAt: string | null;
  lastSyncedAt: string | null;
  syncStatus: "local" | "current" | "stale";
  syncAvailable: boolean;
  managementUrl: string;
};

export type AccountOverview = {
  user: AuthUser;
  workspaceAvatarUrl: string | null;
  identityAvatarUrl: string | null;
  identity: AccountIdentity;
};

export type AccountSecurity = {
  authSource: "local" | "casdoor" | "hybrid";
  localPasswordEnabled: boolean;
  totpEnabled: boolean;
  recoveryCodesRemaining: number;
  suspiciousLoginAlerts: boolean;
};

export type AccountSession = { id: number; current: boolean; ipAddress: string | null; userAgent: string | null; createdAt: string; lastSeenAt: string };
export type AccountLoginEvent = { id: number; method: string; outcome: string; suspicious: boolean; ipAddress: string | null; userAgent: string | null; createdAt: string };

export type CommerceOverview = {
  enabled: boolean;
  tier: "free" | "standard" | "pro" | "enterprise" | string;
  subscriptions: Array<{
    id: string;
    plan: string;
    planDisplayName: string | null;
    tier: string;
    state: string;
    period: string | null;
    startsAt: string | null;
    endsAt: string | null;
    lastSyncedAt: string;
  }>;
  creditGrants: Array<{
    id: string;
    product: string;
    tokens: number;
    costMicrousd: number;
    capeSubmissions: number;
    storageBytes: number;
    expiresAt: string | null;
    revokedAt: string | null;
  }>;
};

export type UsageOverview = {
  plan: string;
  period: string;
  billingCnyPerUsd: number;
  usage: {
    tokens: number;
    costMicrousd: number;
    modelCostMicrousd: number;
    capeCostMicrousd: number;
    capeCostCny: number;
    storageBytes: number;
    capeSubmissions: number;
  };
  limits: { tokens: number; costMicrousd: number; concurrentRequests: number; capeSubmissions: number; storageBytes: number; hardLimit: boolean; warningPercent: number };
  warnings: string[];
};

export type UsageLedgerOverview = {
  items: Array<{
    id: number;
    resourceType: string;
    resourceId: string | null;
    model: string | null;
    inputTokens: number;
    outputTokens: number;
    storageBytes: number;
    quantity: number;
    costMicrousd: number;
    occurredAt: string;
  }>;
};

export type AccountMfaSetup = {
  secret: string;
  recoveryCode: string;
  otpauthUri: string;
};

export type AdminInviteItem = {
  id: number;
  code: string;
  label: string;
  isActive: boolean;
  maxUses: number | null;
  usedCount: number;
  expiresAt: string | null;
  createdAt: string;
};

export type AdminInviteListResponse = {
  items: AdminInviteItem[];
};

export type ConversationApiItem = {
  id: number;
  title: string;
  is_pinned?: boolean;
  is_archived?: boolean;
  case_status?: CaseStatus;
  severity?: CaseSeverity;
  assignee?: string | null;
  tags?: string[];
  case_summary?: string | null;
  analysis_template_id?: number | null;
  analysis_template_version?: number | null;
  analysis_config?: AnalysisTemplate | null;
  created_at: string;
  updated_at: string;
};

export type ConversationApiListResponse = {
  items: ConversationApiItem[];
};

export type ConversationImportResult = ConversationApiItem & {
  importedMessages: number;
};

export type MessageApiItem = {
  id: number;
  conversation_id: number;
  role: ChatRole;
  content: string;
  created_at: string;
  attachments?: MessageAttachment[];
  evidence?: MessageEvidence[];
};

export type MessageApiListResponse = {
  items: MessageApiItem[];
};

export type MessageFeedbackReason =
  | "factual_error"
  | "citation_error"
  | "formatting"
  | "not_helpful"
  | "other";

export type AdminQualityModel = {
  model: string;
  provider: string;
  requests: number;
  successful: number;
  errors: number;
  cancelled: number;
  successRate: number;
  avgFirstTokenMs: number | null;
  avgDurationMs: number | null;
  thumbsUp: number;
  thumbsDown: number;
};

export type AdminQuality = {
  days: number;
  totalRequests: number;
  successfulRequests: number;
  errorRequests: number;
  cancelledRequests: number;
  successRate: number;
  avgFirstTokenMs: number | null;
  avgDurationMs: number | null;
  feedback: Record<string, number>;
  models: AdminQualityModel[];
};

export type AdminObservability = {
  days: number;
  requestSuccessRate: number;
  averageResponseTimeMs: number | null;
  modelFailureRate: number;
  tokenUsage: {
    input: number;
    output: number;
    total: number;
  };
  capeTaskAverageDurationMs: number | null;
  activeUsers: number;
  events: number;
};

export type AdminInviteCreateRequest = {
  code: string;
  label: string;
  maxUses: number | null;
  expiresAt: string | null;
  isActive: boolean;
};

export type LocalChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
  attachments?: MessageAttachment[];
  evidence?: MessageEvidence[];
};

export type MessageEvidence = {
  id?: number | string;
  sourceType: "web" | "attachment" | "cape" | string;
  citation: string;
  title: string;
  url?: string | null;
  locator?: string | null;
  snippet?: string | null;
};

export type MessageAttachment = {
  id: string;
  name: string;
  type: string;
  size: number;
  meta?: string;
};

export type CapeCase = {
  id: number;
  conversationId: number;
  taskId: number;
  sampleName: string;
  status: string;
  completed: boolean;
  score: number | null;
  targetFilename: string | null;
  machine: string | null;
  sha256: string | null;
  reusedExistingTask: boolean;
  summary: CapeAnalysisSummary | null;
  createdAt: string;
  updatedAt: string;
};

export type CapeCaseListResponse = {
  items: CapeCase[];
};

export type LocalConversation = {
  id: string;
  title: string;
  isPinned?: boolean;
  isArchived?: boolean;
  caseStatus?: CaseStatus;
  severity?: CaseSeverity;
  assignee?: string | null;
  tags?: string[];
  caseSummary?: string | null;
  analysisTemplate?: AnalysisTemplate | null;
  createdAt: string;
  updatedAt: string;
  messages: LocalChatMessage[];
  capeCases?: CapeCase[];
  zipContext?: ZipConversationContext;
};

export type CaseStatus = "open" | "triage" | "investigating" | "review" | "confirmed" | "contained" | "remediating" | "closed";
export type CaseSeverity = "unknown" | "low" | "medium" | "high" | "critical";
export type CaseMetadataUpdate = {
  caseStatus?: CaseStatus;
  severity?: CaseSeverity;
  assignee?: string;
  tags?: string[];
  caseSummary?: string;
};

export type InvestigationCaseEvent = {
  id: number; eventType: string; title: string; detail: string | null;
  metadata: Record<string, unknown>; actor: string | null; createdAt: string;
};
export type InvestigationCaseConversation = {
  id: number; title: string; updatedAt: string; messageCount: number; sampleCount: number;
};
export type InvestigationCase = {
  id: number; title: string; status: CaseStatus; severity: CaseSeverity;
  assignee: string | null; tags: string[]; summary: string | null; priority: number;
  organizationId?: number | null; workspaceId?: number | null; assigneeUserId?: number | null;
  slaDueAt: string | null; overdue: boolean; parentCaseId: number | null;
  mergedIntoCaseId: number | null; childCaseIds: number[]; conversationCount: number;
  sampleCount: number; capeTaskCount: number; iocCount: number; createdAt: string;
  updatedAt: string; closedAt: string | null; conversations: InvestigationCaseConversation[];
  capeCases: CapeCase[]; timeline: InvestigationCaseEvent[];
};
export type InvestigationCaseList = {
  items: InvestigationCase[];
  counts: Record<CaseStatus, number>;
};

export type CaseAnalysisRisk = "unknown" | "low" | "medium" | "high" | "critical";
export type CaseAnalysisEvidence = { label: string; href: string } | null;
export type CaseAnalysisEvent = {
  id: string; type: string; title: string; detail: string | null; occurredAt: string | null;
  timeAccuracy: "exact" | "estimated"; timeNote: string | null; source: string;
  sourceLabel: string; risk: CaseAnalysisRisk; evidence: CaseAnalysisEvidence;
  metadata: Record<string, unknown>;
};
export type CaseAnalysisNode = {
  id: string; type: "case" | "sample" | "process" | "domain" | "ip" | "url" | "file" | "attack" | string;
  label: string; risk: CaseAnalysisRisk; detail: Record<string, unknown>; evidence: CaseAnalysisEvidence;
};
export type CaseAnalysis = {
  caseId: number; events: CaseAnalysisEvent[];
  graph: { nodes: CaseAnalysisNode[]; edges: Array<{ id: string; source: string; target: string; relation: string; evidence: CaseAnalysisEvidence }> };
  coverage: { sources: string[]; exactTimes: number; estimatedTimes: number; notes: string[] };
};

export type EvidenceReviewStatus = "pending" | "verified" | "rejected";
export type CaseEvidence = {
  id: number; messageId: number; sourceType: string; citation: string; title: string;
  url: string | null; locator: string | null; snippet: string | null;
  reviewStatus: EvidenceReviewStatus; sourceTrust: number; confidence: number;
  acquiredAt: string | null; contentHash: string | null; snapshotUrl: string | null;
  reviewNote: string | null; reviewedBy: string | null; reviewedAt: string | null;
};
export type CaseConclusion = {
  id: number; statement: string; status: "draft" | "verified" | "rejected"; confidence: number;
  claimType: "fact" | "inference"; confidenceRationale: string | null;
  evidenceIds: number[]; conflictEvidenceIds: number[];
  crossChecks: Array<{ modelId: string; verdict: "supports" | "contradicts" | "inconclusive"; confidence: number; rationale: string; checkedAt: string | null }>;
  createdBy: string | null; reviewedBy: string | null; reviewedAt: string | null; createdAt: string; updatedAt: string;
};
export type CaseEvidenceChain = {
  case: { id: number; title: string; status: string; severity: string; assignee: string | null; updatedAt: string };
  evidence: CaseEvidence[]; conclusions: CaseConclusion[];
  contradictions: Array<{ source: string; evidenceIds: number[]; reason: string }>;
  signatures: Array<{ id: number; signer: string; digest: string; note: string | null; isValid: boolean; signedAt: string; invalidatedAt: string | null }>;
  auditTrail: InvestigationCaseEvent[]; currentDigest: string;
};
export type IndicatorType = "domain" | "ip" | "url" | "md5" | "sha1" | "sha256";
export type IndicatorRisk = "unknown" | "low" | "medium" | "high" | "critical";
export type IndicatorStatus = "pending" | "malicious" | "suspicious" | "false_positive" | "blocked";
export type ThreatIntelResult = {
  provider: string; source: string; confidence: number; malicious: boolean | null; tags: string[];
  externalUrl: string | null; updatedAt: string | null; fetchedAt: string; cached: boolean; stale: boolean;
};
export type ThreatIntelEnrichment = {
  results?: ThreatIntelResult[]; errors?: Array<{ provider: string; message: string }>; queriedAt?: string;
};
export type CaseIndicator = {
  id: number; type: IndicatorType; value: string; riskLevel: IndicatorRisk; confidence: number;
  status: IndicatorStatus; sourceType: string; capeCaseId: number | null; sampleName: string | null;
  firstSeenAt: string; lastSeenAt: string; expiresAt: string | null; enrichment: ThreatIntelEnrichment;
};
export type CaseIndicatorList = {
  items: CaseIndicator[]; total: number; counts: { type: Record<IndicatorType, number>; status: Record<IndicatorStatus, number> };
};

export type DetectionRuleType = "sigma" | "yara";
export type DetectionRuleStatus = "draft" | "validated" | "approved" | "deployed";
export type DetectionRuleValidation = {
  valid?: boolean;
  errors?: string[];
  warnings?: string[];
  conversions?: Record<string, string>;
  attack_techniques?: string[];
};
export type DetectionRuleVersion = {
  id: number; version: number; validationStatus: string; actor: string | null; createdAt: string;
};
export type DetectionRuleTestRun = {
  id: number; totalArtifacts: number; matchedArtifacts: number; falsePositiveCount: number;
  results: Array<{ name: string; matched: boolean; matches: string[] }>; createdAt: string;
};
export type DetectionRule = {
  id: number; caseId: number; sourceCapeCaseId: number | null; ruleType: DetectionRuleType;
  title: string; content: string; status: DetectionRuleStatus; version: number;
  validationStatus: string; validation: DetectionRuleValidation; lastValidatedAt: string | null;
  approvedAt: string | null; deployedAt: string | null; versions: DetectionRuleVersion[];
  testRuns: DetectionRuleTestRun[]; createdAt: string; updatedAt: string;
};
export type DetectionRuleList = {
  items: DetectionRule[];
  counts: Record<DetectionRuleStatus, number>;
};

export type PlaybookStepStatus = "pending" | "running" | "waiting_approval" | "completed" | "failed";
export type PlaybookTemplate = { id: string; title: string; description: string; steps: string[] };
export type PlaybookStep = {
  id: number; key: string; position: number; title: string; status: PlaybookStepStatus;
  input: Record<string, unknown>; output: Record<string, unknown>; error: string | null;
  attemptCount: number; requiresApproval: boolean; approvedAt: string | null;
  approvedBy: string | null; startedAt: string | null; completedAt: string | null;
};
export type InvestigationPlaybook = {
  id: number; caseId: number; templateId: string; title: string; status: "active" | "completed";
  progress: number; steps: PlaybookStep[]; createdAt: string; updatedAt: string; completedAt: string | null;
};
export type PlaybookList = { items: InvestigationPlaybook[] };

export type CapeExportFormat = "bundle" | "json" | "markdown" | "html" | "pdf" | "ioc-csv" | "sigma" | "yara";

export type RuntimeStatus = "idle" | "loading" | "ready" | "error";
export type ModelProvider = "deepseek" | "openai" | "claude";

type ModelOptionShape = {
  id: string;
  label: string;
  provider: ModelProvider;
  groupLabel: string;
};

function getModelIds<const T extends readonly ModelOptionShape[]>(options: T) {
  return options.map((option) => option.id) as { [K in keyof T]: T[K]["id"] };
}

function getModelLabels<const T extends readonly ModelOptionShape[]>(options: T) {
  return Object.fromEntries(options.map((option) => [option.id, option.label])) as Record<
    T[number]["id"],
    string
  >;
}

function getProviderLabels<const T extends readonly ModelOptionShape[]>(options: T) {
  return Object.fromEntries(options.map((option) => [option.provider, option.groupLabel])) as Record<
    T[number]["provider"],
    string
  >;
}

export const MODEL_PROVIDER_ORDER = ["deepseek", "openai", "claude"] as const;

export const DEEPSEEK_MODEL_OPTIONS = [
  { id: "deepseek-v4-flash", label: "Cipher Swift", provider: "deepseek", groupLabel: "Cipher 轻量" },
  { id: "deepseek-v4-pro", label: "Cipher Atlas", provider: "deepseek", groupLabel: "Cipher 轻量" },
  { id: "chatgpt-5.5-official", label: "Cipher Prime", provider: "openai", groupLabel: "Cipher 均衡" },
  { id: "chatgpt-5.4-az", label: "Cipher Vector", provider: "openai", groupLabel: "Cipher 均衡" },
  { id: "claude-opus-4-7-official", label: "Cipher Sentinel", provider: "claude", groupLabel: "Cipher 深研" },
  { id: "claude-opus-4-6-aws", label: "Cipher Forge", provider: "claude", groupLabel: "Cipher 深研" },
  { id: "claude-sonnet-4-6-az", label: "Cipher Alloy", provider: "claude", groupLabel: "Cipher 深研" },
] as const satisfies readonly ModelOptionShape[];

export const DEEPSEEK_MODEL_IDS = getModelIds(DEEPSEEK_MODEL_OPTIONS);

export type DeepSeekModelId = (typeof DEEPSEEK_MODEL_IDS)[number];
export type DeepSeekModelOption = (typeof DEEPSEEK_MODEL_OPTIONS)[number];

export const DEFAULT_DEEPSEEK_MODEL_ID: DeepSeekModelId = "deepseek-v4-flash";
export const ZIP_UNSUPPORTED_MODEL_REASON = "当前模型不支持 ZIP 文件问答，请切换其他模型。";

export const DEEPSEEK_MODEL_LABELS = getModelLabels(DEEPSEEK_MODEL_OPTIONS);
export const MODEL_PROVIDER_LABELS = getProviderLabels(DEEPSEEK_MODEL_OPTIONS);

export function isDeepSeekModelId(value: string): value is DeepSeekModelId {
  return (DEEPSEEK_MODEL_IDS as readonly string[]).includes(value);
}

export function resolveDeepSeekModelId(value?: string): DeepSeekModelId {
  return typeof value === "string" && isDeepSeekModelId(value)
    ? value
    : DEFAULT_DEEPSEEK_MODEL_ID;
}

export function getDeepSeekModelLabel(modelId: DeepSeekModelId): string {
  return DEEPSEEK_MODEL_LABELS[modelId];
}

export function getDeepSeekModelProvider(modelId: DeepSeekModelId): ModelProvider {
  const option = DEEPSEEK_MODEL_OPTIONS.find((candidate) => candidate.id === modelId);

  if (!option) {
    throw new Error(`Missing provider metadata for model "${modelId}"`);
  }

  return option.provider;
}

export function getDeepSeekModelsByProvider(provider: ModelProvider): DeepSeekModelOption[] {
  return DEEPSEEK_MODEL_OPTIONS.filter((option) => option.provider === provider);
}

export function isZipContextSupportedModel(modelId: DeepSeekModelId): boolean {
  return DEEPSEEK_MODEL_OPTIONS.some((option) => option.id === modelId);
}

export type ChatSettings = {
  systemPrompt: string;
  modelId?: string;
  responseLanguage?: ResponseLanguage;
  responseLength?: ResponseLength;
  defaultWebSearch?: boolean;
  capeNotificationsEnabled?: boolean;
  motionPreference?: VisualEffectPreference;
  transparencyPreference?: VisualEffectPreference;
};

export type WebLlmSettings = {
  modelId: string;
  systemPrompt: string;
  responseLanguage?: ResponseLanguage;
  responseLength?: ResponseLength;
  defaultWebSearch?: boolean;
  capeNotificationsEnabled?: boolean;
  motionPreference?: VisualEffectPreference;
  transparencyPreference?: VisualEffectPreference;
};

export type ResponseLanguage = "zh-CN" | "en";
export type ResponseLength = "concise" | "balanced" | "detailed";
export type VisualEffectPreference = "system" | "reduce" | "standard";

export type StoredChatState = {
  activeConversationId: string | null;
  conversations: LocalConversation[];
  settings: WebLlmSettings;
};

export type ServerChatState = {
  activeConversationId: string | null;
  conversations: LocalConversation[];
  settings: ChatSettings;
};

export type PersistedChatState = StoredChatState | ServerChatState;

export type ZipConversationContext = {
  zipContextId: string;
  archiveName: string;
  entryCount: number;
  extractedEntryCount: number;
  inventoryOnlyCount: number;
  skippedEntryCount: number;
  supportedByCurrentModel: boolean;
  unsupportedReason: string | null;
  pendingAttachment?: boolean;
  uploading?: boolean;
  errorMessage?: string | null;
};

export type UploadZipResult = ZipConversationContext;

export type AdminOverview = {
  services: {
    backend: { running: boolean; pid?: number | null; label?: string; detail?: string };
    tunnel: { running: boolean; pid?: number | null; label?: string; detail?: string };
    autostartEnabled: boolean;
  };
  access: {
    localUrl: string;
    publicUrl: string;
  };
  models: {
    providers: Array<{ provider: string; healthy: number; total: number }>;
  };
  files: {
    uploadLimit: number;
    zipEnabled: boolean;
    zipContextCount: number;
  };
};

export type CapeSubmitResult = {
  taskId: number;
  status: string;
  reusedExistingTask?: boolean;
};

export type CapeTaskStatus = {
  taskId: number;
  status: string;
  completed: boolean;
  score: number | null;
  targetFilename: string | null;
  machine: string | null;
};

export type CapeIocSummary = {
  domains: string[];
  ips: string[];
  urls: string[];
};

export type CapeTacticItem = {
  technique: string;
  signature: string;
  description: string;
};

export type CapeDroppedFileItem = {
  name: string;
  path: string;
  type: string;
  sha256: string;
};

export type CapeAnalysisSummary = {
  taskId: number;
  status: string;
  score: number | null;
  submittedFilename: string | null;
  sha256: string | null;
  iocs: CapeIocSummary;
  tactics: CapeTacticItem[];
  droppedFiles: CapeDroppedFileItem[];
  processes?: Array<Record<string, unknown>>;
  networkConnections?: Array<Record<string, unknown>>;
  signatures: Array<Record<string, unknown>>;
};

export type AdminFileCacheClearResult = {
  ok: boolean;
  cleared: number;
};

export type AdminPromptSource = "default" | "override";
export type AdminPromptStatus = "ready" | "fallback" | "error";

export type AdminPrompt = {
  prompt: string;
  source: AdminPromptSource;
  updatedAt: string | null;
  status: AdminPromptStatus;
  message: string | null;
};

export type AdminPromptMutationResult = AdminPrompt & {
  ok: boolean;
};

export type AdminEvalGateThresholds = {
  accuracy: number;
  citationCoverage: number;
  falsePositiveRate: number;
  formatCompliance: number;
  firstTokenMs: number;
  durationMs: number;
  costMicrousd: number;
};

export type AdminEvalTestCase = {
  id: number;
  title: string;
  category: string;
  input: string;
  expectedAnswer: string;
  expectedCitations: string[];
  requiredFormat: string;
  falsePositiveTerms: string[];
  tags: string[];
  sanitized: boolean;
  authorized: boolean;
  source: string;
  createdAt: string;
};

export type AdminEvalTestSet = {
  id: number;
  name: string;
  description: string | null;
  status: string;
  authorizationNote: string;
  caseCount: number;
  sanitizedCaseCount: number;
  authorizedCaseCount: number;
  createdAt: string;
  updatedAt: string;
  cases: AdminEvalTestCase[];
};

export type AdminEvalResult = {
  id: number;
  testCaseId: number;
  testCaseTitle: string;
  accuracy: number;
  citationCoverage: number;
  falsePositiveRate: number;
  formatCompliance: number;
  firstTokenMs: number;
  durationMs: number;
  costMicrousd: number;
  output: string;
};

export type AdminEvalRun = {
  id: number;
  testSetId: number | null;
  testSetName: string | null;
  name: string;
  status: string;
  modelId: string;
  routeStrategy: string;
  promptVersion: string;
  gateThresholds: AdminEvalGateThresholds;
  gatePassed: boolean;
  summary: AdminEvalGateThresholds & { caseCount: number };
  startedAt: string;
  completedAt: string | null;
  results: AdminEvalResult[];
};

export type AdminEvalCenter = {
  testSets: AdminEvalTestSet[];
  runs: AdminEvalRun[];
  privacyPolicy: {
    autoCaptureOnlineConversations: boolean;
    requiresSanitization: boolean;
    requiresExplicitAuthorization: boolean;
    allowedSources: string[];
  };
};

export type SkillPackage = {
  id: number; key: string; name: string; version: string; description: string; author: string;
  source: string; sourceUrl: string | null; permissions: string[]; reviewStatus: string;
  permissionDetails?: { network: string[]; files: string[]; commands: string[]; data: string[] };
  executionPolicy?: { timeoutSeconds: number; memoryMb: number; cpuSeconds: number; maxOutputBytes: number; retry: { maxAttempts: number; backoffMs: number } };
  releaseStatus?: string; changelog?: Array<string | { version?: string; changes?: string[] }>;
  compatibility?: { cipher?: string; platforms?: string[] };
  signature?: { status: string; digest?: string | null };
  enabled: boolean; scanStatus?: string; category: string; tags: string[]; pricing: string;
  license?: string; upstreamVersion?: string;
  featured: boolean; installed: boolean; installationEnabled?: boolean; installCount: number; runCount: number;
  entitlement: { tier: "standard" | "professional" | "enterprise"; allowed: boolean };
  inputs: { required?: string[]; properties?: Record<string, SkillInputProperty> };
};

export type SkillInputProperty = {
  type: "string" | "number" | "boolean" | "array" | "object";
  label?: string; description?: string; default?: unknown; itemType?: string;
};

export type SkillRun = {
  id: number; skillId: number; caseId: number | null; status: string;
  input: Record<string, unknown>; output: Record<string, unknown>; tools: string[];
  policy?: Record<string, unknown>; attemptCount?: number; outputTruncated?: boolean;
  error: string | null; createdAt: string; completedAt: string | null;
};

export function buildZipAttachmentMeta(
  context: Pick<
    ZipConversationContext,
    "entryCount" | "extractedEntryCount" | "inventoryOnlyCount" | "skippedEntryCount" | "uploading"
  >
): string {
  if (context.uploading) {
    return "ZIP · 上传中...";
  }

  return [
    `ZIP · 已扫描 ${context.entryCount} 项`,
    `已提取 ${context.extractedEntryCount} 项`,
    context.inventoryOnlyCount > 0 ? `仅清单 ${context.inventoryOnlyCount} 项` : null,
    context.skippedEntryCount > 0 ? `已跳过 ${context.skippedEntryCount} 项` : null
  ]
    .filter((part): part is string => part !== null)
    .join(" · ");
}

export type OutboundChatMessage = {
  role: ChatRole;
  content: string;
  attachments?: MessageAttachment[];
};

export type StagedAttachment = {
  id: string;
  file: File;
  name: string;
  type: string;
  size: number;
  retainedForZipContext?: boolean;
  uploadStatus?: "hashing" | "uploading" | "ready" | "failed";
  uploadProgress?: number;
  uploadId?: string;
  uploadError?: string;
  deduplicated?: boolean;
};

export type WebLlmInitProgress = {
  progress: number;
  text: string;
};

import {
  DEFAULT_DEEPSEEK_MODEL_ID,
  type AccountOverview,
  type AdminInviteCreateRequest,
  type AdminInviteItem,
  type AdminInviteListResponse,
  type AdminFileCacheClearResult,
  type CapeCase,
  type CapeCaseListResponse,
  type CapeAnalysisSummary,
  type CapeSubmitResult,
  type CapeTaskStatus,
  type CasdoorAuthConfig,
  type AuthUser,
  type AdminOverview,
  type AdminObservability,
  type AdminQuality,
  type AdminEvalCenter,
  type AdminEvalGateThresholds,
  type AdminEvalRun,
  type AdminEvalTestCase,
  type AdminEvalTestSet,
  type AdminPrompt,
  type AdminPromptMutationResult,
  type SkillPackage,
  type ConversationApiItem,
  type ConversationApiListResponse,
  type ConversationImportResult,
  type DeepSeekModelId,
  type DetectionRule,
  type DetectionRuleList,
  type DetectionRuleStatus,
  type MessageApiListResponse,
  type InvestigationCase,
  type InvestigationCaseList,
  type InvestigationPlaybook,
  type PlaybookList,
  type PlaybookTemplate,
  type CaseIndicator,
  type CaseIndicatorList,
  type IndicatorRisk,
  type IndicatorStatus,
  type OutboundChatMessage,
  type SessionStatus,
  type UploadZipResult
  , type Job
  , type AnalysisTemplate
} from "../types";

export async function listAnalysisTemplates(): Promise<{ items: AnalysisTemplate[] }> { return caseRequest("/api/analysis-templates"); }
export async function listAdminAnalysisTemplates(): Promise<{ items: AnalysisTemplate[] }> { return caseRequest("/api/admin/analysis-templates"); }
export async function createAdminAnalysisTemplate(payload: Omit<AnalysisTemplate, "id" | "status" | "version">): Promise<AnalysisTemplate> { return caseRequest("/api/admin/analysis-templates", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); }
export async function updateAdminAnalysisTemplate(id: number, payload: Omit<AnalysisTemplate, "id" | "status" | "version">): Promise<AnalysisTemplate> { return caseRequest(`/api/admin/analysis-templates/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); }
export async function actOnAnalysisTemplate(id: number, action: "publish" | "disable" | "copy"): Promise<AnalysisTemplate> { return caseRequest(`/api/admin/analysis-templates/${id}/${action}`, { method: "POST" }); }

export async function listJobs(status?: string): Promise<{ items: Job[] }> {
  return caseRequest(`/api/jobs${status ? `?status=${encodeURIComponent(status)}` : ""}`);
}
export async function getJob(id: number): Promise<Job> { return caseRequest(`/api/jobs/${id}`); }
export async function cancelJob(id: number): Promise<Job> { return caseRequest(`/api/jobs/${id}/cancel`, { method: "POST" }); }
export async function retryJob(id: number): Promise<Job> { return caseRequest(`/api/jobs/${id}/retry`, { method: "POST" }); }
export async function createJob(taskType: string, payload: Record<string, unknown>, options: { idempotencyKey?: string; timeoutSeconds?: number; maxRetries?: number } = {}): Promise<Job> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;
  return caseRequest("/api/jobs", { method: "POST", headers, body: JSON.stringify({ taskType, payload, timeoutSeconds: options.timeoutSeconds, maxRetries: options.maxRetries }) });
}

export async function getSkills(q = "", category = "", installed?: boolean, source = ""): Promise<{ items: SkillPackage[] }> {
  const query = new URLSearchParams();
  if (q) query.set("q", q);
  if (category) query.set("category", category);
  if (installed !== undefined) query.set("installed", String(installed));
  if (source) query.set("source", source);
  const response = await fetch(`/api/skills?${query}`, { credentials: "include" });
  if (!response.ok) throw new Error(await readErrorMessage(response));
  const payload = await response.json() as { items: Array<Omit<SkillPackage, "entitlement"> & { entitlement?: SkillPackage["entitlement"] }> };
  return {
    items: payload.items.map(item => ({
      ...item,
      entitlement: item.entitlement ?? {
        tier: "standard",
        allowed: item.pricing === "included" || item.pricing === "free"
      }
    }))
  };
}
export async function syncSkills(): Promise<{ added: number; items: SkillPackage[] }> { const response = await fetch("/api/skills/sync", { method: "POST", credentials: "include" }); if (!response.ok) throw new Error(await readErrorMessage(response)); return await response.json() as { added: number; items: SkillPackage[] }; }
export async function toggleSkill(id: number, enabled: boolean): Promise<SkillPackage> { const response = await fetch(`/api/skills/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify({ enabled }) }); if (!response.ok) throw new Error(await readErrorMessage(response)); return await response.json() as SkillPackage; }
export async function reviewSkill(id: number, status: "verified" | "blocked" | "needs_review"): Promise<SkillPackage> { return caseRequest(`/api/skills/${id}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) }); }
export async function rollbackSkill(id: number): Promise<SkillPackage> { return caseRequest(`/api/skills/${id}/rollback`, { method: "POST" }); }
export type SkillRunResponse = {
  id: number; output: Record<string, unknown>;
  conversationMessages?: Array<{ id: number; role: "user" | "assistant"; content: string; createdAt: string }>;
};
export async function runSkill(id: number, input: Record<string, unknown>, options: { conversationId?: number; prompt?: string; approvedPermissions?: string[] } = {}): Promise<SkillRunResponse> { const response = await fetch(`/api/skills/${id}/runs`, { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify({ input, ...options }) }); if (!response.ok) throw new Error(await readErrorMessage(response)); return await response.json() as SkillRunResponse; }
export async function installSkill(id: number): Promise<SkillPackage> { return caseRequest(`/api/skills/${id}/install`, { method: "POST" }); }
export async function uninstallSkill(id: number): Promise<SkillPackage> { return caseRequest(`/api/skills/${id}/install`, { method: "DELETE" }); }
export async function setSkillInstallationEnabled(id: number, enabled: boolean): Promise<SkillPackage> { return caseRequest(`/api/skills/${id}/install`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }) }); }
export async function getSkillHistory(): Promise<{ items: import("../types").SkillRun[] }> { return caseRequest("/api/skills/history"); }

export async function submitMessageFeedback(
  messageId: string,
  payload: { rating: "up" | "down" | null; reason?: import("../types").MessageFeedbackReason; note?: string }
): Promise<{ messageId: number; rating: string | null; reason: string | null }> {
  if (!/^\d+$/u.test(messageId)) {
    return { messageId: Number(messageId) || 0, rating: payload.rating, reason: payload.reason ?? null };
  }
  return caseRequest(`/api/messages/${messageId}/feedback`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

async function caseRequest<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { credentials: "include", ...init });
  } catch (error) {
    throw toRequestError(error);
  }
  if (!response.ok) throw new Error(await readErrorMessage(response));
  return response.json() as Promise<T>;
}

export type NotificationItem = {
  id: number; organizationId: number; type: string; title: string; body: string | null;
  caseId: number | null; resourceType: string | null; resourceId: string | null;
  resourceUrl: string | null; readAt: string | null; createdAt: string;
};
export type NotificationPreference = { type: string; inApp: boolean; email: boolean; webPush: boolean };

export async function listNotifications(type = ""): Promise<{ items: NotificationItem[]; unreadCount: number }> {
  return caseRequest(`/api/notifications${type ? `?type=${encodeURIComponent(type)}` : ""}`);
}
export async function markNotificationRead(id: number): Promise<void> { await caseRequest(`/api/notifications/${id}/read`, { method: "PUT" }); }
export async function markAllNotificationsRead(): Promise<void> { await caseRequest("/api/notifications/read-all", { method: "PUT" }); }
export async function deleteNotification(id: number): Promise<void> {
  const response = await fetch(`/api/notifications/${id}`, { method: "DELETE", credentials: "include" });
  if (!response.ok) throw new Error(await readErrorMessage(response));
}
export async function getNotificationPreferences(organizationId: number): Promise<{ items: NotificationPreference[] }> {
  return caseRequest(`/api/notifications/preferences?organization_id=${organizationId}`);
}
export async function updateNotificationPreference(organizationId: number, item: NotificationPreference): Promise<NotificationPreference> {
  return caseRequest(`/api/notifications/preferences/${item.type}?organization_id=${organizationId}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(item)
  });
}

export async function listInvestigationCases(filters: Record<string, string> = {}): Promise<InvestigationCaseList> {
  const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value));
  return caseRequest(`/api/cases${query.size ? `?${query}` : ""}`);
}

export async function getInvestigationCase(id: number): Promise<InvestigationCase> {
  return caseRequest(`/api/cases/${id}`);
}

export async function getCaseAnalysis(caseId: number): Promise<import("../types").CaseAnalysis> {
  return caseRequest(`/api/cases/${caseId}/analysis`);
}

export async function getCaseEvidenceChain(caseId: number): Promise<import("../types").CaseEvidenceChain> {
  return caseRequest(`/api/cases/${caseId}/evidence-chain`);
}

export async function reviewCaseEvidence(caseId: number, evidenceId: number, payload: { reviewStatus: import("../types").EvidenceReviewStatus; sourceTrust: number; confidence: number; acquiredAt?: string | null; contentHash?: string | null; snapshotUrl?: string | null; reviewNote?: string | null }): Promise<import("../types").CaseEvidence> {
  return caseRequest(`/api/cases/${caseId}/evidence/${evidenceId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
}

export type CaseConclusionPayload = { statement: string; status: "draft" | "verified" | "rejected"; confidence: number; claimType: "fact" | "inference"; confidenceRationale?: string | null; evidenceIds: number[]; conflictEvidenceIds: number[]; crossChecks: Array<{ modelId: string; verdict: "supports" | "contradicts" | "inconclusive"; confidence: number; rationale: string; checkedAt?: string | null }> };

export async function createCaseConclusion(caseId: number, payload: CaseConclusionPayload): Promise<import("../types").CaseEvidenceChain> {
  return caseRequest(`/api/cases/${caseId}/conclusions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
}

export async function updateCaseConclusion(caseId: number, conclusionId: number, payload: Partial<CaseConclusionPayload>): Promise<import("../types").CaseEvidenceChain> {
  return caseRequest(`/api/cases/${caseId}/conclusions/${conclusionId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
}

export async function crossCheckCaseConclusion(caseId: number, conclusionId: number, modelId: import("../types").DeepSeekModelId): Promise<import("../types").CaseEvidenceChain> {
  return caseRequest(`/api/cases/${caseId}/conclusions/${conclusionId}/cross-check`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ modelId }) });
}

export async function signCaseEvidenceChain(caseId: number, payload: { signer: string; note?: string | null }): Promise<import("../types").CaseEvidenceChain> {
  return caseRequest(`/api/cases/${caseId}/signatures`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
}

export function exportCaseEvidenceChain(caseId: number) {
  window.location.assign(`/api/cases/${caseId}/evidence-chain/export`);
}

export async function createInvestigationCase(payload: { title: string; priority?: number; slaDueAt?: string | null; workspaceId?: number; assigneeUserId?: number }): Promise<InvestigationCase> {
  return caseRequest("/api/cases", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
}

export async function updateInvestigationCase(id: number, payload: Partial<Pick<InvestigationCase, "title" | "status" | "severity" | "assignee" | "assigneeUserId" | "tags" | "summary" | "priority" | "slaDueAt" | "parentCaseId">> & { statusReason?: string }): Promise<InvestigationCase> {
  return caseRequest(`/api/cases/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
}

export async function mergeInvestigationCase(sourceId: number, targetCaseId: number): Promise<InvestigationCase> {
  return caseRequest(`/api/cases/${sourceId}/merge`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ targetCaseId }) });
}

export type CaseCollaboration = {
  access: Array<{ userId: number; username: string; displayName: string | null; permission: "viewer" | "editor" }>;
  followers: Array<{ userId: number; username: string; displayName: string | null }>;
  comments: Array<{ id: number; content: string; author: { userId: number; username: string; displayName: string | null }; createdAt: string; updatedAt: string }>;
};

export async function getCaseCollaboration(caseId: number): Promise<CaseCollaboration> {
  return caseRequest(`/api/cases/${caseId}/collaboration`);
}

export async function shareInvestigationCase(caseId: number, username: string, permission: "viewer" | "editor") {
  return caseRequest(`/api/cases/${caseId}/access`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, permission }) });
}

export async function followInvestigationCase(caseId: number): Promise<{ following: boolean }> {
  return caseRequest(`/api/cases/${caseId}/follow`, { method: "PUT" });
}

export async function addInvestigationCaseComment(caseId: number, content: string) {
  return caseRequest(`/api/cases/${caseId}/comments`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content }) });
}

export async function listOrganizations(): Promise<{ items: Array<{ id: number; name: string; slug: string; role: string }> }> {
  return caseRequest("/api/organizations");
}

export async function getOrganization(id: number): Promise<{ id: number; name: string; role: string; members: Array<{ userId: number; username: string; displayName: string | null; role: string }>; workspaces: Array<{ id: number; name: string; slug: string }> }> {
  return caseRequest(`/api/organizations/${id}`);
}

export async function addOrganizationMember(id: number, username: string, role: "owner" | "admin" | "analyst" | "reviewer" | "viewer") {
  return caseRequest(`/api/organizations/${id}/members`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, role }) });
}

export async function listPlaybookTemplates(): Promise<PlaybookTemplate[]> {
  return caseRequest("/api/cases/playbook-templates");
}

export async function listCasePlaybooks(caseId: number): Promise<PlaybookList> {
  return caseRequest(`/api/cases/${caseId}/playbooks`);
}

export async function createCasePlaybook(caseId: number, templateId: string): Promise<InvestigationPlaybook> {
  return caseRequest(`/api/cases/${caseId}/playbooks`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ templateId }) });
}

export async function executePlaybookStep(caseId: number, playbookId: number, stepId: number, payload: { input?: Record<string, unknown>; output?: Record<string, unknown>; error?: string | null } = {}): Promise<InvestigationPlaybook> {
  return caseRequest(`/api/cases/${caseId}/playbooks/${playbookId}/steps/${stepId}/execute`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
}

export async function retryPlaybookStep(caseId: number, playbookId: number, stepId: number): Promise<InvestigationPlaybook> {
  return caseRequest(`/api/cases/${caseId}/playbooks/${playbookId}/steps/${stepId}/retry`, { method: "POST" });
}

export async function approvePlaybookStep(caseId: number, playbookId: number, stepId: number): Promise<InvestigationPlaybook> {
  return caseRequest(`/api/cases/${caseId}/playbooks/${playbookId}/steps/${stepId}/approve`, { method: "POST" });
}

export async function listCaseIndicators(caseId: number, filters: Record<string, string> = {}): Promise<CaseIndicatorList> {
  const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value));
  return caseRequest(`/api/cases/${caseId}/iocs${query.size ? `?${query}` : ""}`);
}

export async function syncCaseIndicators(caseId: number): Promise<CaseIndicatorList> {
  return caseRequest(`/api/cases/${caseId}/iocs/sync`, { method: "POST" });
}

export async function enrichCaseIndicator(caseId: number, indicatorId: number, force = false): Promise<CaseIndicator> {
  return caseRequest(`/api/cases/${caseId}/iocs/${indicatorId}/enrich`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ force })
  });
}

export async function updateCaseIndicator(caseId: number, indicatorId: number, payload: { status?: IndicatorStatus; riskLevel?: IndicatorRisk; confidence?: number }): Promise<CaseIndicator> {
  return caseRequest(`/api/cases/${caseId}/iocs/${indicatorId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
}

export async function bulkUpdateCaseIndicators(caseId: number, ids: number[], status: IndicatorStatus): Promise<CaseIndicatorList> {
  return caseRequest(`/api/cases/${caseId}/iocs/bulk-status`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids, status }) });
}

export function exportCaseIndicators(caseId: number, format: "csv" | "firewall" | "dns" | "edr") {
  window.location.assign(`/api/cases/${caseId}/iocs/export?format=${format}`);
}

export async function listDetectionRules(caseId: number): Promise<DetectionRuleList> {
  return caseRequest(`/api/cases/${caseId}/rules`);
}

export async function generateDetectionRules(caseId: number): Promise<DetectionRuleList> {
  return caseRequest(`/api/cases/${caseId}/rules/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ruleTypes: ["sigma", "yara"] })
  });
}

export async function updateDetectionRule(
  caseId: number,
  ruleId: number,
  payload: { title?: string; content?: string; status?: DetectionRuleStatus }
): Promise<DetectionRule> {
  return caseRequest(`/api/cases/${caseId}/rules/${ruleId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function validateDetectionRule(caseId: number, ruleId: number): Promise<DetectionRule> {
  return caseRequest(`/api/cases/${caseId}/rules/${ruleId}/validate`, { method: "POST" });
}

export async function testDetectionRule(caseId: number, ruleId: number, files: File[]): Promise<DetectionRule["testRuns"][number]> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  return caseRequest(`/api/cases/${caseId}/rules/${ruleId}/test`, { method: "POST", body: form });
}

export function exportDetectionRule(caseId: number, ruleId: number, format: "raw" | "html" | "pdf") {
  window.location.assign(`/api/cases/${caseId}/rules/${ruleId}/export?format=${format}`);
}

type ErrorPayload = {
  detail?: string | Array<{ msg?: string }>;
};

export class CapeReportNotReadyError extends Error {
  constructor(message = "CAPE 报告仍在生成中。") {
    super(message);
    this.name = "CapeReportNotReadyError";
  }
}

function normalizeErrorText(text: string): string {
  return text.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function mapGatewayErrorMessage(response: Response, rawText: string): string | null {
  const normalizedText = rawText.toLowerCase();

  if (
    response.status === 524 ||
    ((response.status === 504 || response.status === 522) &&
      normalizedText.includes("cloudflare"))
  ) {
    return "服务器处理超时了，请稍等一下再试。";
  }

  if (response.status === 504) {
    return "服务器响应超时了，请稍后重试。";
  }

  if (response.status === 502 && normalizedText.includes("cloudflare")) {
    return "服务器网关暂时连接失败，请稍后重试。";
  }

  if (response.status === 522) {
    return "服务器暂时连不上，请稍后重试。";
  }

  if (response.status === 523) {
    return "服务器地址暂时不可用，请稍后重试。";
  }

  if (
    normalizedText.includes("error code 524") ||
    normalizedText.includes("a timeout occurred") ||
    (normalizedText.includes("cloudflare") && normalizedText.includes("timed out"))
  ) {
    return "服务器处理超时了，请稍等一下再试。";
  }

  return null;
}

function mapStatusFallbackMessage(response: Response): string | null {
  if (response.status === 503) {
    return "聊天服务暂时不可用，请检查后端是否启动，以及 `backend/.env` 里的模型密钥是否已配置。";
  }

  if (response.status === 502) {
    return "聊天服务暂时连接失败，请检查后端和上游模型服务。";
  }

  if (response.status === 500) {
    return "聊天服务发生内部错误，请稍后重试。";
  }

  return null;
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.clone().json()) as ErrorPayload;
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return payload.detail;
    }

    if (
      typeof payload.detail === "object" &&
      payload.detail !== null &&
      "message" in payload.detail &&
      typeof payload.detail.message === "string" &&
      payload.detail.message.trim()
    ) {
      return payload.detail.message;
    }

    if (Array.isArray(payload.detail)) {
      const firstMessage = payload.detail.find(
        (item) => typeof item?.msg === "string" && item.msg.trim()
      )?.msg;

      if (firstMessage) {
        return firstMessage;
      }
    }
  } catch {
    try {
      const rawText = await response.text();
      const mappedMessage = mapGatewayErrorMessage(response, rawText);

      if (mappedMessage) {
        return mappedMessage;
      }

      const text = normalizeErrorText(rawText);
      if (text) {
        return text.length > 240 ? `${text.slice(0, 237)}...` : text;
      }

      const fallbackMessage = mapStatusFallbackMessage(response);
      if (fallbackMessage) {
        return fallbackMessage;
      }
    } catch {
      const fallbackMessage = mapStatusFallbackMessage(response);
      if (fallbackMessage) {
        return fallbackMessage;
      }

      return "Request failed. Please try again.";
    }
  }

  return mapStatusFallbackMessage(response) ?? "Request failed. Please try again.";
}

function toRequestError(error: unknown): Error {
  if (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    error.name === "AbortError"
  ) {
    const abortError = new Error("Request was interrupted before the server responded.");
    abortError.name = "AbortError";
    return abortError;
  }

  if (error instanceof Error) {
    if (error instanceof TypeError) {
      return new Error(
        "Unable to reach the server. Please check whether the backend is running and reachable."
      );
    }

    return error;
  }

  return new Error("Request failed. Please try again.");
}

export async function checkSession(): Promise<SessionStatus> {
  let response: Response;

  try {
    response = await fetch("/api/auth/session", {
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (response.status === 401) {
    return { authenticated: false, user: null };
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as SessionStatus;
}

export async function getCasdoorAuthConfig(): Promise<CasdoorAuthConfig> {
  let response: Response;

  try {
    response = await fetch("/api/auth/casdoor/config", {
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as CasdoorAuthConfig;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

export async function login(payload: {
  username?: string;
  password: string;
}): Promise<SessionStatus> {
  let response: Response;

  try {
    response = await fetch("/api/auth/login", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as SessionStatus;
}

export async function register(payload: {
  username: string;
  password: string;
  inviteCode: string;
  displayName?: string;
  avatarDataUrl?: string | null;
}): Promise<SessionStatus> {
  let response: Response;

  try {
    response = await fetch("/api/auth/register", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as SessionStatus;
}

export async function updateAccountProfile(payload: {
  displayName?: string | null;
  email?: string | null;
  avatarDataUrl?: string | null;
  removeAvatar?: boolean;
}): Promise<AccountOverview> {
  let response: Response;

  try {
    response = await fetch("/api/account/profile", {
      method: "PATCH",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const result: unknown = await response.json();
  if (
    typeof result === "object" &&
    result !== null &&
    "user" in result &&
    "identity" in result
  ) {
    return result as AccountOverview;
  }

  // During a rolling deploy, the previous profile endpoint returns a flat
  // AuthUser. Reload the overview so the account page still receives the
  // synchronized identity shape expected by the current UI.
  return getAccountOverview();
}

export async function getAccountOverview(): Promise<AccountOverview> {
  let response: Response;

  try {
    response = await fetch("/api/account", {
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as AccountOverview;
}

async function accountSecurityRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/account/security${path}`, { credentials: "include", ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  if (!response.ok) throw new Error(await readErrorMessage(response));
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const getAccountSecurity = () => accountSecurityRequest<import("../types").AccountSecurity>("");
export const getAccountSessions = () => accountSecurityRequest<import("../types").AccountSession[]>("/sessions");
export const getAccountLoginHistory = () => accountSecurityRequest<import("../types").AccountLoginEvent[]>("/login-history");
export const revokeAccountSession = (id: number) => accountSecurityRequest<void>(`/sessions/${id}`, { method: "DELETE" });
export const revokeAllAccountSessions = (reauth: {password?: string; passcode?: string}) => accountSecurityRequest<{revoked: number}>("/sessions/revoke-all", { method: "POST", body: JSON.stringify(reauth) });
export const changeAccountPassword = (payload: {newPassword: string; password?: string; passcode?: string}) => accountSecurityRequest<import("../types").AccountSecurity>("/password", { method: "PUT", body: JSON.stringify(payload) });
export const rotateAccountRecoveryCodes = (payload: {password?: string; passcode?: string}) => accountSecurityRequest<{codes: string[]}>("/recovery-codes", { method: "POST", body: JSON.stringify(payload) });
export const updateAccountSecurityAlerts = (enabled: boolean) => accountSecurityRequest<import("../types").AccountSecurity>("/alerts", { method: "PUT", body: JSON.stringify({enabled}) });

export async function getCommerceOverview(): Promise<import("../types").CommerceOverview> {
  return caseRequest("/api/commerce/subscription");
}

export async function syncCommerceSubscription(): Promise<import("../types").CommerceOverview> {
  return caseRequest("/api/commerce/subscription/sync", { method: "POST" });
}

export async function getUsageOverview(): Promise<import("../types").UsageOverview> {
  return caseRequest("/api/usage/summary");
}

export async function getUsageLedger(limit = 20): Promise<import("../types").UsageLedgerOverview> {
  return caseRequest(`/api/usage/ledger?limit=${encodeURIComponent(String(limit))}`);
}

export async function syncAccount(): Promise<AccountOverview> {
  let response: Response;

  try {
    response = await fetch("/api/account/sync", {
      method: "POST",
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as AccountOverview;
}

export async function sendAccountEmailVerification(): Promise<{
  email: string;
  sent: boolean;
  message: string;
}> {
  let response: Response;

  try {
    response = await fetch("/api/account/email-verification", {
      method: "POST",
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as {
    email: string;
    sent: boolean;
    message: string;
  };
}

export async function confirmAccountEmailVerification(code: string): Promise<AccountOverview> {
  let response: Response;

  try {
    response = await fetch("/api/account/email-verification/confirm", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ code })
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as AccountOverview;
}

export async function startAccountTotpSetup(): Promise<import("../types").AccountMfaSetup> {
  const response = await fetch("/api/account/mfa/totp/setup", {
    method: "POST",
    credentials: "include"
  });
  if (!response.ok) throw new Error(await readErrorMessage(response));
  return (await response.json()) as import("../types").AccountMfaSetup;
}

export async function confirmAccountTotpSetup(input: {
  secret: string;
  recoveryCode: string;
  passcode: string;
}): Promise<AccountOverview> {
  const response = await fetch("/api/account/mfa/totp/confirm", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input)
  });
  if (!response.ok) throw new Error(await readErrorMessage(response));
  return (await response.json()) as AccountOverview;
}

export async function resetAccountMfa(): Promise<AccountOverview> {
  const response = await fetch("/api/account/mfa", {
    method: "DELETE",
    credentials: "include"
  });
  if (!response.ok) throw new Error(await readErrorMessage(response));
  return (await response.json()) as AccountOverview;
}

export async function getAccountProviders(): Promise<import("../types").AccountProvider[]> {
  const response = await fetch("/api/account/providers", { credentials: "include" });
  if (!response.ok) throw new Error(await readErrorMessage(response));
  const payload = (await response.json()) as {items: import("../types").AccountProvider[]};
  return payload.items;
}

export async function logout(): Promise<void> {
  let response: Response;

  try {
    response = await fetch("/api/auth/logout", {
      method: "POST",
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}

export async function getAdminOverview(): Promise<AdminOverview> {
  let response: Response;

  try {
    response = await fetch("/api/admin/overview", {
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as AdminOverview;
}

export async function getAdminQuality(days = 30): Promise<AdminQuality> {
  let response: Response;
  try {
    response = await fetch(`/api/admin/quality?days=${days}`, { credentials: "include" });
  } catch (error) {
    throw toRequestError(error);
  }
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return (await response.json()) as AdminQuality;
}

export async function getAdminObservability(days = 30): Promise<AdminObservability> {
  let response: Response;
  try {
    response = await fetch(`/api/admin/observability?days=${days}`, { credentials: "include" });
  } catch (error) {
    throw toRequestError(error);
  }
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return (await response.json()) as AdminObservability;
}

export async function getAdminEvaluations(): Promise<AdminEvalCenter> {
  return caseRequest("/api/admin/evaluations");
}

export async function createAdminEvalTestSet(payload: {
  name: string;
  description?: string | null;
  authorizationNote: string;
  cases?: Array<Omit<AdminEvalTestCase, "id" | "createdAt">>;
}): Promise<AdminEvalTestSet> {
  return caseRequest("/api/admin/evaluations/test-sets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function addAdminEvalTestCase(
  testSetId: number,
  payload: Omit<AdminEvalTestCase, "id" | "createdAt">
): Promise<AdminEvalTestCase> {
  return caseRequest(`/api/admin/evaluations/test-sets/${testSetId}/cases`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function runAdminEvaluation(payload: {
  testSetId: number;
  modelId: string;
  routeStrategy: string;
  promptVersion: string;
  gateThresholds: AdminEvalGateThresholds;
}): Promise<AdminEvalRun> {
  return caseRequest("/api/admin/evaluations/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export function exportAdminEvaluationRun(runId: number) {
  window.location.assign(`/api/admin/evaluations/runs/${runId}/export`);
}

export async function controlAdminService(
  target: "backend" | "tunnel",
  action: "start" | "stop"
): Promise<void> {
  let response: Response;

  try {
    response = await fetch(`/api/admin/services/${target}/${action}`, {
      method: "POST",
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}

export async function clearAdminFileCache(): Promise<AdminFileCacheClearResult> {
  let response: Response;

  try {
    response = await fetch("/api/admin/files/cache/clear", {
      method: "POST",
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as AdminFileCacheClearResult;
}

export async function getAdminPrompt(): Promise<AdminPrompt> {
  let response: Response;

  try {
    response = await fetch("/api/admin/prompt", {
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as AdminPrompt;
}

export async function saveAdminPrompt(prompt: string): Promise<AdminPromptMutationResult> {
  let response: Response;

  try {
    response = await fetch("/api/admin/prompt", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ prompt })
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as AdminPromptMutationResult;
}

export async function resetAdminPrompt(): Promise<AdminPromptMutationResult> {
  let response: Response;

  try {
    response = await fetch("/api/admin/prompt/reset", {
      method: "POST",
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as AdminPromptMutationResult;
}

export async function getAdminInvites(): Promise<AdminInviteListResponse> {
  let response: Response;

  try {
    response = await fetch("/api/admin/invites", {
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as AdminInviteListResponse;
}

export async function createAdminInvite(payload: AdminInviteCreateRequest): Promise<AdminInviteItem> {
  let response: Response;

  try {
    response = await fetch("/api/admin/invites", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as AdminInviteItem;
}

export async function toggleAdminInvite(inviteId: number): Promise<AdminInviteItem> {
  let response: Response;

  try {
    response = await fetch(`/api/admin/invites/${inviteId}/toggle`, {
      method: "POST",
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as AdminInviteItem;
}

export async function deleteAdminInvite(inviteId: number): Promise<void> {
  let response: Response;

  try {
    response = await fetch(`/api/admin/invites/${inviteId}`, {
      method: "DELETE",
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}

export async function listConversations(): Promise<ConversationApiListResponse> {
  let response: Response;

  try {
    response = await fetch("/api/conversations", {
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as ConversationApiListResponse;
}

export async function createConversation(payload: { title: string; templateId?: number }): Promise<ConversationApiItem> {
  let response: Response;

  try {
    response = await fetch("/api/conversations", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as ConversationApiItem;
}

export async function getConversationMessages(
  conversationId: string
): Promise<MessageApiListResponse> {
  let response: Response;

  try {
    response = await fetch(`/api/conversations/${conversationId}/messages`, {
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as MessageApiListResponse;
}

export async function deleteConversation(conversationId: string): Promise<void> {
  let response: Response;

  try {
    response = await fetch(`/api/conversations/${conversationId}`, {
      method: "DELETE",
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}

export async function updateConversation(
  conversationId: string,
  payload: {
    title?: string;
    isPinned?: boolean;
    isArchived?: boolean;
    caseStatus?: import("../types").CaseStatus;
    severity?: import("../types").CaseSeverity;
    assignee?: string;
    tags?: string[];
    caseSummary?: string;
  }
): Promise<ConversationApiItem> {
  let response: Response;

  try {
    response = await fetch(`/api/conversations/${conversationId}`, {
      method: "PATCH",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as ConversationApiItem;
}

export async function importConversation(payload: {
  title: string;
  messages: OutboundChatMessage[];
}): Promise<ConversationImportResult> {
  let response: Response;

  try {
    response = await fetch("/api/conversations/import", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as ConversationImportResult;
}

export async function streamChat(
  messages: OutboundChatMessage[],
  files: File[] = [],
  model: DeepSeekModelId = DEFAULT_DEEPSEEK_MODEL_ID,
  scope?: {
    conversationId?: string;
    zipContextId?: string;
    webSearch?: boolean;
    responseLanguage?: "zh-CN" | "en";
    responseLength?: "concise" | "balanced" | "detailed";
    signal?: AbortSignal;
    uploadedFileIds?: string[];
  }
): Promise<ReadableStream<Uint8Array>> {
  const requestBody = files.length > 0 || (scope?.uploadedFileIds?.length ?? 0) > 0
    ? (() => {
        const formData = new FormData();
        formData.append("messages", JSON.stringify({ messages, model, ...(scope?.conversationId ? { conversationId: scope.conversationId } : {}), ...(scope?.zipContextId ? { zipContextId: scope.zipContextId } : {}), ...(scope?.webSearch ? { webSearch: true } : {}), ...(scope?.responseLanguage ? { responseLanguage: scope.responseLanguage } : {}), ...(scope?.responseLength ? { responseLength: scope.responseLength } : {}), ...(scope?.uploadedFileIds?.length ? { uploadedFileIds: scope.uploadedFileIds } : {}) }));
        for (const file of files) formData.append("files", file);
        return { body: formData };
      })()
    : { headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messages, model, ...(scope?.conversationId ? { conversationId: scope.conversationId } : {}), ...(scope?.zipContextId ? { zipContextId: scope.zipContextId } : {}), ...(scope?.webSearch ? { webSearch: true } : {}), ...(scope?.responseLanguage ? { responseLanguage: scope.responseLanguage } : {}), ...(scope?.responseLength ? { responseLength: scope.responseLength } : {}), ...(scope?.uploadedFileIds?.length ? { uploadedFileIds: scope.uploadedFileIds } : {}) }) };

  let response: Response | undefined;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      response = await fetch("/api/chat", { method: "POST", credentials: "include", ...requestBody, ...(scope?.signal ? { signal: scope.signal } : {}) });
      break;
    } catch (error) {
      if (scope?.signal?.aborted || attempt === 2) throw toRequestError(error);
      await new Promise<void>((resolve, reject) => {
        const timer = window.setTimeout(resolve, 500 * 2 ** attempt);
        scope?.signal?.addEventListener("abort", () => { window.clearTimeout(timer); reject(scope.signal?.reason ?? new DOMException("Aborted", "AbortError")); }, { once: true });
      });
    }
  }
  if (!response) throw new Error("Unable to reach the server. Please check whether the backend is running and reachable.");

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  if (response.body === null) {
    throw new Error("Chat response did not include a readable stream.");
  }

  return response.body;
}

export async function uploadZip(
  file: File,
  payload: { conversationId: string; model: DeepSeekModelId }
): Promise<UploadZipResult> {
  let response: Response;

  try {
    const formData = new FormData();
    formData.append("conversationId", payload.conversationId);
    formData.append("model", payload.model);
    formData.append("file", file);

    response = await fetch("/api/upload_zip", {
      method: "POST",
      credentials: "include",
      body: formData
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const result = (await response.json()) as UploadZipResult;
  if (!result.uploading) {
    return result;
  }

  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    await delay(500);

    let statusResponse: Response;
    try {
      statusResponse = await fetch(
        `/api/upload_zip/${encodeURIComponent(result.zipContextId)}?conversationId=${encodeURIComponent(payload.conversationId)}&model=${encodeURIComponent(payload.model)}`,
        {
          credentials: "include"
        }
      );
    } catch (error) {
      throw toRequestError(error);
    }

    if (!statusResponse.ok) {
      throw new Error(await readErrorMessage(statusResponse));
    }

    const statusResult = (await statusResponse.json()) as UploadZipResult;
    if (statusResult.uploading) {
      continue;
    }

    if (statusResult.errorMessage) {
      throw new Error(statusResult.errorMessage);
    }

    return statusResult;
  }

  throw new Error("ZIP 解析耗时过长，请稍后重试。");
}

export async function submitCapeSample(
  file: File,
  scope?: {
    machine?: string;
    platform?: string;
    tags?: string;
    route?: string;
    pcap?: boolean;
  }
): Promise<CapeSubmitResult> {
  let response: Response;

  try {
    const formData = new FormData();
    formData.append("file", file);

    const query = new URLSearchParams();
    if (scope?.machine) {
      query.set("machine", scope.machine);
    }
    if (scope?.platform) {
      query.set("platform", scope.platform);
    }
    if (scope?.tags) {
      query.set("tags", scope.tags);
    }
    if (scope?.route) {
      query.set("route", scope.route);
    }
    if (scope?.pcap) {
      query.set("pcap", "true");
    }

    response = await fetch(query.size > 0 ? `/api/cape/submit?${query.toString()}` : "/api/cape/submit", {
      method: "POST",
      credentials: "include",
      body: formData
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as CapeSubmitResult;
}

export async function createCapeCase(
  file: File,
  scope: {
    conversationId: string;
    machine?: string;
    platform?: string;
    tags?: string;
    route?: string;
    pcap?: boolean;
  }
): Promise<CapeCase> {
  let response: Response;

  try {
    const formData = new FormData();
    formData.append("file", file);

    const query = new URLSearchParams({ conversationId: scope.conversationId });
    if (scope.machine) {
      query.set("machine", scope.machine);
    }
    if (scope.platform) {
      query.set("platform", scope.platform);
    }
    if (scope.tags) {
      query.set("tags", scope.tags);
    }
    if (scope.route) {
      query.set("route", scope.route);
    }
    if (scope.pcap) {
      query.set("pcap", "true");
    }

    response = await fetch(`/api/cape/cases?${query.toString()}`, {
      method: "POST",
      credentials: "include",
      body: formData
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as CapeCase;
}

export async function listCapeCases(conversationId: string): Promise<CapeCaseListResponse> {
  let response: Response;

  try {
    response = await fetch(`/api/cape/cases/conversation/${conversationId}`, {
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as CapeCaseListResponse;
}

export async function getCapeCase(caseId: number): Promise<CapeCase> {
  let response: Response;

  try {
    response = await fetch(`/api/cape/cases/${caseId}`, {
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as CapeCase;
}

export async function downloadCapeCaseExport(
  caseId: number,
  format: import("../types").CapeExportFormat = "bundle"
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`/api/cape/cases/${caseId}/export?format=${encodeURIComponent(format)}`, {
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") ?? "";
  const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
  const fallbackExtensions: Record<import("../types").CapeExportFormat, string> = {
    bundle: "zip",
    json: "json",
    markdown: "md",
    html: "html",
    pdf: "pdf",
    "ioc-csv": "csv",
    sigma: "yml",
    yara: "yar"
  };
  const filename = filenameMatch?.[1] ?? `cipher-cape-case-${caseId}.${fallbackExtensions[format]}`;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export async function getCapeTaskStatus(taskId: number): Promise<CapeTaskStatus> {
  let response: Response;

  try {
    response = await fetch(`/api/cape/tasks/${taskId}`, {
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as CapeTaskStatus;
}

export async function getCapeTaskSummary(taskId: number): Promise<CapeAnalysisSummary> {
  let response: Response;

  try {
    response = await fetch(`/api/cape/tasks/${taskId}/summary`, {
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    if (response.status === 409) {
      throw new CapeReportNotReadyError(await readErrorMessage(response));
    }
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as CapeAnalysisSummary;
}

import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AccountPage } from "./AccountPage";
import * as api from "../lib/api";


vi.mock("../lib/api", () => ({
  confirmAccountEmailVerification: vi.fn(),
  getAccountOverview: vi.fn(),
  getCommerceOverview: vi.fn(),
  getUsageLedger: vi.fn(),
  getUsageOverview: vi.fn(),
  getAccountProviders: vi.fn(),
  getAccountSecurity: vi.fn(),
  getAccountSessions: vi.fn(),
  getAccountLoginHistory: vi.fn(),
  revokeAccountSession: vi.fn(),
  revokeAllAccountSessions: vi.fn(),
  changeAccountPassword: vi.fn(),
  rotateAccountRecoveryCodes: vi.fn(),
  updateAccountSecurityAlerts: vi.fn(),
  startAccountTotpSetup: vi.fn(),
  confirmAccountTotpSetup: vi.fn(),
  resetAccountMfa: vi.fn(),
  sendAccountEmailVerification: vi.fn(),
  syncAccount: vi.fn(),
  syncCommerceSubscription: vi.fn(),
  updateAccountProfile: vi.fn()
}));

describe("AccountPage", () => {
  const viewer = {
    id: 1,
    username: "alice",
    displayName: "Alice Chen",
    avatarUrl: null,
    isAdmin: false
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getAccountSecurity).mockResolvedValue({ authSource: "hybrid", localPasswordEnabled: true, totpEnabled: true, recoveryCodesRemaining: 10, suspiciousLoginAlerts: true });
    vi.mocked(api.getAccountSessions).mockResolvedValue([]);
    vi.mocked(api.getAccountLoginHistory).mockResolvedValue([]);
    vi.mocked(api.getCommerceOverview).mockResolvedValue({
      enabled: true, tier: "pro", subscriptions: [], creditGrants: []
    });
    vi.mocked(api.getUsageOverview).mockResolvedValue({
      plan: "pro", period: "2026-08",
      billingCnyPerUsd: 7.2,
      usage: { tokens: 1200, costMicrousd: 4000, modelCostMicrousd: 3000, capeCostMicrousd: 1000, capeCostCny: 0.0072, storageBytes: 1024, capeSubmissions: 1 },
      limits: { tokens: 20000000, costMicrousd: 100000000, concurrentRequests: 10, capeSubmissions: 300, storageBytes: 53687091200, hardLimit: true, warningPercent: 80 },
      warnings: []
    });
    vi.mocked(api.getUsageLedger).mockResolvedValue({
      items: [{ id: 1, resourceType: "model", resourceId: "1", model: "deepseek-v4-flash", inputTokens: 1000, outputTokens: 200, storageBytes: 0, quantity: 1, costMicrousd: 4000, occurredAt: "2026-08-07T10:00:00Z" }]
    });
    vi.mocked(api.syncCommerceSubscription).mockResolvedValue({
      enabled: true, tier: "pro", subscriptions: [], creditGrants: []
    });
    vi.mocked(api.getAccountProviders).mockResolvedValue([
      { provider: "microsoftonline", label: "Microsoft", connected: true, authorizationUrl: null },
      { provider: "github", label: "GitHub", connected: true, authorizationUrl: null },
      { provider: "google", label: "Google", connected: false, authorizationUrl: "https://login.example.test/google" }
    ]);
    vi.mocked(api.sendAccountEmailVerification).mockResolvedValue({
      email: "alice@example.test",
      sent: true,
      message: "验证邮件已发送，请查看邮箱。"
    });
    vi.mocked(api.confirmAccountEmailVerification).mockResolvedValue({
      user: viewer,
      workspaceAvatarUrl: null,
      identityAvatarUrl: null,
      identity: {
        source: "casdoor",
        providerName: "Cipher SSO",
        email: "alice@example.test",
        emailVerified: true,
        connectedAccounts: [],
        mfaEnabled: true,
        passwordEnabled: true,
        lastSignInAt: null,
        lastSyncedAt: "2026-08-06T08:05:00Z",
        syncStatus: "current",
        syncAvailable: true,
        managementUrl: "https://login.example.test/account"
      }
    });
    vi.mocked(api.getAccountOverview).mockResolvedValue({
      user: viewer,
      workspaceAvatarUrl: null,
      identityAvatarUrl: null,
      identity: {
        source: "casdoor",
        providerName: "Cipher SSO",
        email: "alice@example.test",
        emailVerified: true,
        connectedAccounts: [{ provider: "github", label: "GitHub" }],
        mfaEnabled: true,
        passwordEnabled: true,
        lastSignInAt: "2026-08-06T08:00:00Z",
        lastSyncedAt: "2026-08-06T08:05:00Z",
        syncStatus: "current",
        syncAvailable: true,
        managementUrl: "https://login.example.test/account"
      }
    });
  });

  it("shows an immutable account and an editable, repeatable display name", () => {
    render(<AccountPage viewer={viewer} onBack={vi.fn()} onViewerChange={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "资料与登录安全" })).toBeInTheDocument();
    expect(screen.getByLabelText("登录账号")).toHaveValue("alice");
    expect(screen.getByLabelText("登录账号")).toHaveAttribute("readonly");
    expect(screen.getByText("账号全局唯一，由身份服务管理。")).toBeInTheDocument();
    expect(screen.getByText("保存后会同步到 Casdoor，最多 80 个字符。")).toBeInTheDocument();
  });

  it("shows Casdoor email, third-party binding, and no admin-console link", async () => {
    render(<AccountPage viewer={viewer} onBack={vi.fn()} onViewerChange={vi.fn()} />);

    expect(await screen.findByText("alice@example.test")).toBeInTheDocument();
    expect(screen.getByText("GitHub")).toBeInTheDocument();
    expect(screen.getAllByText("已开启").length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: /管理登录方式/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/auth\.bigcipher\.fyi/)).not.toBeInTheDocument();
  });

  it("turns missing account protections into security tasks", async () => {
    vi.mocked(api.getAccountOverview).mockResolvedValue({
      user: viewer,
      workspaceAvatarUrl: null,
      identityAvatarUrl: null,
      identity: {
        source: "casdoor",
        providerName: "Cipher SSO",
        email: "alice@example.test",
        emailVerified: false,
        connectedAccounts: [{ provider: "github", label: "GitHub" }],
        mfaEnabled: true,
        passwordEnabled: false,
        lastSignInAt: "2026-08-06T08:00:00Z",
        lastSyncedAt: "2026-08-06T08:05:00Z",
        syncStatus: "stale",
        syncAvailable: true,
        managementUrl: "https://login.example.test/account"
      }
    });

    render(<AccountPage viewer={viewer} onBack={vi.fn()} onViewerChange={vi.fn()} />);

    expect(await screen.findByLabelText("待处理安全项")).toBeInTheDocument();
    expect(screen.getByText("验证登录邮箱")).toBeInTheDocument();
    expect(screen.getByText("设置恢复方式")).toBeInTheDocument();
    expect(screen.getByText("同步 SSO 资料")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "立即同步" })).toBeEnabled();
    expect(screen.getAllByRole("button", { name: "查看" }).length).toBeGreaterThan(0);
  });

  it("expands security details inside the account page", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getAccountOverview).mockResolvedValue({
      user: viewer,
      workspaceAvatarUrl: null,
      identityAvatarUrl: null,
      identity: {
        source: "casdoor",
        providerName: "Cipher SSO",
        email: "alice@example.test",
        emailVerified: false,
        connectedAccounts: [],
        mfaEnabled: false,
        passwordEnabled: false,
        lastSignInAt: "2026-08-06T08:00:00Z",
        lastSyncedAt: "2026-08-06T08:05:00Z",
        syncStatus: "current",
        syncAvailable: true,
        managementUrl: "https://login.example.test/account"
      }
    });

    render(<AccountPage viewer={viewer} onBack={vi.fn()} onViewerChange={vi.fn()} />);

    expect(await screen.findByRole("button", { name: "发送验证邮件" })).toBeInTheDocument();
    const providers = screen.getByRole("button", { name: /^第三方账号/ });
    await user.click(providers);
    expect(providers).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("第三方账号管理")).toBeInTheDocument();
    expect(await screen.findByText("Microsoft")).toBeInTheDocument();
    expect(document.querySelectorAll(".account-provider-heading .account-provider-logo")).toHaveLength(3);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("falls back to initials when an identity avatar cannot load", async () => {
    vi.mocked(api.getAccountOverview).mockResolvedValue({
      user: viewer,
      workspaceAvatarUrl: null,
      identityAvatarUrl: "https://login.example.test/missing-avatar.png",
      identity: {
        source: "casdoor",
        providerName: "Cipher SSO",
        email: "alice@example.test",
        emailVerified: true,
        connectedAccounts: [],
        mfaEnabled: true,
        passwordEnabled: true,
        lastSignInAt: null,
        lastSyncedAt: "2026-08-06T08:05:00Z",
        syncStatus: "current",
        syncAvailable: true,
        managementUrl: "https://login.example.test/account"
      }
    });

    render(<AccountPage viewer={viewer} onBack={vi.fn()} onViewerChange={vi.fn()} />);

    const avatars = await screen.findAllByRole("img", { name: "Alice Chen的头像" });
    const images = avatars.map((avatar) => avatar.querySelector("img"));
    images.forEach((image) => fireEvent.error(image as HTMLImageElement));

    expect(screen.getAllByText("AC")).toHaveLength(2);
  });

  it("sends an email verification message from the security detail panel", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getAccountOverview).mockResolvedValue({
      user: viewer,
      workspaceAvatarUrl: null,
      identityAvatarUrl: null,
      identity: {
        source: "casdoor",
        providerName: "Cipher SSO",
        email: "alice@example.test",
        emailVerified: false,
        connectedAccounts: [],
        mfaEnabled: true,
        passwordEnabled: true,
        lastSignInAt: "2026-08-06T08:00:00Z",
        lastSyncedAt: "2026-08-06T08:05:00Z",
        syncStatus: "current",
        syncAvailable: true,
        managementUrl: "https://login.example.test/account"
      }
    });

    render(<AccountPage viewer={viewer} onBack={vi.fn()} onViewerChange={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: /登录邮箱/ }));
    await user.click(screen.getByRole("button", { name: "发送验证邮件" }));

    expect(api.sendAccountEmailVerification).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("status")).toHaveTextContent("验证邮件已发送，请查看邮箱。");
    expect(screen.getByLabelText("邮箱验证码")).toBeInTheDocument();
  });

  it("confirms an email code without leaving the account page", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getAccountOverview).mockResolvedValue({
      user: viewer,
      workspaceAvatarUrl: null,
      identityAvatarUrl: null,
      identity: {
        source: "casdoor",
        providerName: "Cipher SSO",
        email: "alice@example.test",
        emailVerified: false,
        connectedAccounts: [],
        mfaEnabled: true,
        passwordEnabled: true,
        lastSignInAt: null,
        lastSyncedAt: "2026-08-06T08:05:00Z",
        syncStatus: "current",
        syncAvailable: true,
        managementUrl: "https://login.example.test/account"
      }
    });

    render(<AccountPage viewer={viewer} onBack={vi.fn()} onViewerChange={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: /登录邮箱/ }));
    await user.click(screen.getByRole("button", { name: "发送验证邮件" }));
    await user.type(screen.getByLabelText("邮箱验证码"), "123456");
    await user.click(screen.getByRole("button", { name: "确认验证" }));

    expect(api.confirmAccountEmailVerification).toHaveBeenCalledWith("123456");
    expect(await screen.findByRole("status")).toHaveTextContent("邮箱验证成功");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("refreshes the account from Casdoor on demand", async () => {
    const user = userEvent.setup();
    vi.mocked(api.syncAccount).mockResolvedValue({
      user: { ...viewer, displayName: "Synced Alice" },
      workspaceAvatarUrl: null,
      identityAvatarUrl: null,
      identity: {
        source: "casdoor",
        providerName: "Cipher SSO",
        email: "alice@example.test",
        emailVerified: true,
        connectedAccounts: [{ provider: "google", label: "Google" }],
        mfaEnabled: true,
        passwordEnabled: true,
        lastSignInAt: null,
        lastSyncedAt: "2026-08-06T09:00:00Z",
        syncStatus: "current",
        syncAvailable: true,
        managementUrl: "https://login.example.test/account"
      }
    });
    const onViewerChange = vi.fn();
    render(<AccountPage viewer={viewer} onBack={vi.fn()} onViewerChange={onViewerChange} />);

    await user.click(await screen.findByRole("button", { name: "同步资料" }));

    expect(api.syncAccount).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Google")).toBeInTheDocument();
    expect(onViewerChange).toHaveBeenCalledWith({ ...viewer, displayName: "Synced Alice" });
  });

  it("saves profile and email changes through one account update", async () => {
    const user = userEvent.setup();
    const onViewerChange = vi.fn();
    vi.mocked(api.updateAccountProfile).mockResolvedValue({
      user: { ...viewer, displayName: "Threat Hunter" },
      workspaceAvatarUrl: null,
      identityAvatarUrl: null,
      identity: {
        source: "casdoor",
        providerName: "Cipher SSO",
        email: "hunter@example.test",
        emailVerified: false,
        connectedAccounts: [{ provider: "github", label: "GitHub" }],
        mfaEnabled: true,
        passwordEnabled: true,
        lastSignInAt: "2026-08-06T08:00:00Z",
        lastSyncedAt: "2026-08-06T08:05:00Z",
        syncStatus: "current",
        syncAvailable: true,
        managementUrl: "https://login.example.test/account"
      }
    });

    render(<AccountPage viewer={viewer} onBack={vi.fn()} onViewerChange={onViewerChange} />);

    const displayName = screen.getByLabelText("昵称");
    const email = await screen.findByLabelText("邮箱");
    await user.clear(displayName);
    await user.type(displayName, "Threat Hunter");
    await user.clear(email);
    await user.type(email, "hunter@example.test");
    await user.click(screen.getByRole("button", { name: "保存更改" }));

    expect(api.updateAccountProfile).toHaveBeenCalledWith({
      displayName: "Threat Hunter",
      email: "hunter@example.test"
    });
    expect(onViewerChange).toHaveBeenCalledWith({ ...viewer, displayName: "Threat Hunter" });
    expect(await screen.findByRole("status")).toHaveTextContent("已同步到 Casdoor");
    expect(screen.getAllByText("未验证").length).toBeGreaterThan(0);
  });

  it("does not submit an invalid email", async () => {
    const user = userEvent.setup();
    render(<AccountPage viewer={viewer} onBack={vi.fn()} onViewerChange={vi.fn()} />);

    const email = await screen.findByLabelText("邮箱");
    await user.clear(email);
    await user.type(email, "invalid-email");

    expect(screen.getByText("请输入有效的邮箱地址。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存更改" })).toBeDisabled();
    expect(api.updateAccountProfile).not.toHaveBeenCalled();
  });

  it("shows quota usage and recent billing details", async () => {
    render(<AccountPage viewer={viewer} onBack={vi.fn()} onViewerChange={vi.fn()} />);

    expect(await screen.findByLabelText("本月用量")).toHaveTextContent("Token");
    expect(screen.getByLabelText("本月用量")).toHaveTextContent("¥0.01 ($0.00)");
    await userEvent.click(screen.getByText("最近账单明细"));
    expect(screen.getByText("deepseek-v4-flash")).toBeInTheDocument();
    expect(screen.getByText(/tokens$/)).toBeInTheDocument();
  });

  it("rejects unsupported avatar formats before calling the server", async () => {
    const user = userEvent.setup({ applyAccept: false });
    render(<AccountPage viewer={viewer} onBack={vi.fn()} onViewerChange={vi.fn()} />);

    await user.upload(
      screen.getByLabelText("上传头像"),
      new File(["<svg></svg>"], "avatar.svg", { type: "image/svg+xml" })
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("请选择 JPG、PNG 或 WebP 图片。");
    expect(api.updateAccountProfile).not.toHaveBeenCalled();
  });
});

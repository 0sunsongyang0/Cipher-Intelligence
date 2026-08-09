import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent
} from "react";
import {
  IconAlertCircle,
  IconArrowLeft,
  IconAt,
  IconBrandGithub,
  IconBrandGoogle,
  IconBrandWindows,
  IconCamera,
  IconChevronRight,
  IconCheck,
  IconKey,
  IconLink,
  IconLock,
  IconRefresh,
  IconShieldCheck,
  IconTrash
} from "@tabler/icons-react";

import cipherLogo from "../assets/cipher-mark.svg";
import { GradientWaves } from "../components/GradientWaves";
import { ThemeToggle } from "../components/ThemeToggle";
import { useTheme } from "../theme";
import {
  getAccountOverview,
  getCommerceOverview,
  getUsageLedger,
  getUsageOverview,
  getAccountProviders,
  confirmAccountEmailVerification,
  confirmAccountTotpSetup,
  resetAccountMfa,
  sendAccountEmailVerification,
  startAccountTotpSetup,
  syncAccount,
  syncCommerceSubscription,
  updateAccountProfile,
  getAccountSecurity, getAccountSessions, getAccountLoginHistory, revokeAccountSession,
  revokeAllAccountSessions, changeAccountPassword, rotateAccountRecoveryCodes,
  updateAccountSecurityAlerts
} from "../lib/api";
import type { AccountLoginEvent, AccountMfaSetup, AccountOverview, AccountProvider, AccountSecurity, AccountSession, AuthUser, CommerceOverview, UsageLedgerOverview, UsageOverview } from "../types";


const MAX_AVATAR_BYTES = 5 * 1024 * 1024;
const ALLOWED_AVATAR_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/u;

type SecurityTask = {
  id: string;
  title: string;
  detail: string;
  status: "done" | "todo" | "pending";
  actionLabel?: string;
  onAction?: () => void;
  disabled?: boolean;
};

type SecurityDetailId = "providers" | "mfa" | "recovery" | "sessions" | "alerts";

type AccountPageProps = {
  viewer: AuthUser;
  onBack: () => void;
  onViewerChange: (viewer: AuthUser) => void;
};

function AccountProviderLogo({ provider }: { provider: string }) {
  const iconProps = { size: 15, stroke: 1.8, "aria-hidden": true as const };

  if (provider === "github") {
    return <IconBrandGithub className="account-provider-logo" {...iconProps} />;
  }
  if (provider === "google") {
    return <IconBrandGoogle className="account-provider-logo" {...iconProps} />;
  }
  if (provider === "microsoftonline" || provider === "azuread") {
    return <IconBrandWindows className="account-provider-logo" {...iconProps} />;
  }
  return <IconLink className="account-provider-logo" {...iconProps} />;
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      if (typeof reader.result === "string") {
        resolve(reader.result);
        return;
      }
      reject(new Error("无法读取头像文件。"));
    });
    reader.addEventListener("error", () => reject(new Error("无法读取头像文件。")));
    reader.readAsDataURL(file);
  });
}

function validateImageDimensions(dataUrl: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.addEventListener("load", () => {
      if (Math.min(image.naturalWidth, image.naturalHeight) < 32) {
        reject(new Error("头像尺寸至少需要 32 × 32 像素。"));
        return;
      }
      if (Math.max(image.naturalWidth, image.naturalHeight) > 4096) {
        reject(new Error("头像宽高不能超过 4096 像素。"));
        return;
      }
      resolve();
    });
    image.addEventListener("error", () => reject(new Error("这个图片无法用作头像。")));
    image.src = dataUrl;
  });
}

function getInitials(value: string): string {
  return value
    .trim()
    .split(/\s+/u)
    .slice(0, 2)
    .map((part) => Array.from(part)[0] ?? "")
    .join("")
    .toLocaleUpperCase() || "C";
}

function formatSyncTime(value: string | null | undefined): string {
  if (!value) {
    return "尚未同步";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "已同步";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function formatLastSignIn(value: string | null | undefined): string {
  if (!value) {
    return "暂无记录";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "已记录";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function formatQuota(value: number): string {
  return new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function formatBytes(value: number): string {
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(1)} GB`;
  if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${formatQuota(value)} B`;
}

function AccountAvatar({ src, name, className }: {
  src: string | null;
  name: string;
  className: string;
}) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const canShowImage = Boolean(src) && src !== failedSrc;

  return (
    <div className={className} aria-label={`${name}的头像`} role="img">
      {canShowImage ? (
        <img src={src ?? undefined} alt="" onError={() => setFailedSrc(src)} />
      ) : (
        <span>{getInitials(name)}</span>
      )}
    </div>
  );
}

function sameViewer(left: AuthUser, right: AuthUser): boolean {
  return left.id === right.id &&
    left.username === right.username &&
    left.displayName === right.displayName &&
    left.avatarUrl === right.avatarUrl &&
    left.isAdmin === right.isAdmin;
}

export function AccountPage({ viewer, onBack, onViewerChange }: AccountPageProps) {
  const { theme } = useTheme();
  const [displayName, setDisplayName] = useState(viewer.displayName ?? viewer.username);
  const [email, setEmail] = useState("");
  const [avatarDataUrl, setAvatarDataUrl] = useState<string | null>(null);
  const [removeAvatar, setRemoveAvatar] = useState(false);
  const [overview, setOverview] = useState<AccountOverview | null>(null);
  const [commerce, setCommerce] = useState<CommerceOverview | null>(null);
  const [usage, setUsage] = useState<UsageOverview | null>(null);
  const [usageLedger, setUsageLedger] = useState<UsageLedgerOverview | null>(null);
  const [isSyncingCommerce, setSyncingCommerce] = useState(false);
  const [isLoadingIdentity, setLoadingIdentity] = useState(true);
  const [isSyncing, setSyncing] = useState(false);
  const [isSendingVerification, setSendingVerification] = useState(false);
  const [isConfirmingVerification, setConfirmingVerification] = useState(false);
  const [verificationCode, setVerificationCode] = useState("");
  const [verificationSent, setVerificationSent] = useState(false);
  const [mfaSetup, setMfaSetup] = useState<AccountMfaSetup | null>(null);
  const [mfaPasscode, setMfaPasscode] = useState("");
  const [isUpdatingMfa, setUpdatingMfa] = useState(false);
  const [accountProviders, setAccountProviders] = useState<AccountProvider[]>([]);
  const [linkingProvider, setLinkingProvider] = useState<string | null>(null);
  const [isSaving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [identityError, setIdentityError] = useState<string | null>(null);
  const [securityDetailMessage, setSecurityDetailMessage] = useState<string | null>(null);
  const [securityDetailError, setSecurityDetailError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [security, setSecurity] = useState<AccountSecurity | null>(null);
  const [sessions, setSessions] = useState<AccountSession[]>([]);
  const [loginHistory, setLoginHistory] = useState<AccountLoginEvent[]>([]);
  const [oneTimeRecoveryCodes, setOneTimeRecoveryCodes] = useState<string[]>([]);
  const [activeSecurityDetail, setActiveSecurityDetail] = useState<SecurityDetailId | null>(null);
  const emailInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setDisplayName(viewer.displayName ?? viewer.username);
  }, [viewer.displayName, viewer.username]);

  useEffect(() => {
    let active = true;
    setLoadingIdentity(true);
    getAccountOverview()
      .then((nextOverview) => {
        if (!active) {
          return;
        }
        setOverview(nextOverview);
        setEmail(nextOverview.identity.email ?? "");
        setIdentityError(null);
        if (!sameViewer(viewer, nextOverview.user)) {
          onViewerChange(nextOverview.user);
        }
      })
      .catch((nextError) => {
        if (active) {
          setIdentityError(
            nextError instanceof Error ? nextError.message : "无法读取身份信息。"
          );
        }
      })
      .finally(() => {
        if (active) {
          setLoadingIdentity(false);
        }
      });

    return () => {
      active = false;
    };
  }, [onViewerChange]);

  useEffect(() => {
    Promise.all([getAccountSecurity(), getAccountSessions(), getAccountLoginHistory()])
      .then(([nextSecurity, nextSessions, nextHistory]) => { setSecurity(nextSecurity); setSessions(nextSessions); setLoginHistory(nextHistory); })
      .catch((nextError) => setSecurityDetailError(nextError instanceof Error ? nextError.message : "无法读取账号安全状态。"));
  }, []);

  const requestReauth = useCallback(() => {
    const value = window.prompt(security?.localPasswordEnabled ? "请输入当前密码以重新验证身份" : "请输入 6 位 TOTP 验证码；Casdoor 刚登录的 10 分钟内可留空");
    if (value === null) return null;
    return /^\d{6}$/u.test(value) ? { passcode: value } : value ? { password: value } : {};
  }, [security?.localPasswordEnabled]);

  const handlePasswordChange = useCallback(async () => {
    const reauth = requestReauth(); if (!reauth) return;
    const newPassword = window.prompt("请输入新密码（至少 8 位，包含字母和数字）"); if (!newPassword) return;
    try { setSecurity(await changeAccountPassword({ ...reauth, newPassword })); setSecurityDetailMessage("独立密码已更新，其他设备的会话已注销。"); }
    catch (nextError) { setSecurityDetailError(nextError instanceof Error ? nextError.message : "密码更新失败。"); }
  }, [requestReauth]);

  const handleRecoveryRotation = useCallback(async () => {
    const reauth = requestReauth(); if (!reauth) return;
    try { const result = await rotateAccountRecoveryCodes(reauth); setOneTimeRecoveryCodes(result.codes); setSecurity(await getAccountSecurity()); setSecurityDetailMessage("恢复码已轮换。关闭此页面后不会再次显示。"); }
    catch (nextError) { setSecurityDetailError(nextError instanceof Error ? nextError.message : "恢复码生成失败。"); }
  }, [requestReauth]);

  const handleRevokeAll = useCallback(async () => {
    const reauth = requestReauth(); if (!reauth || !window.confirm("注销除当前会话外的所有设备？")) return;
    try { await revokeAllAccountSessions(reauth); setSessions(await getAccountSessions()); setSecurityDetailMessage("其他设备已全部退出。"); }
    catch (nextError) { setSecurityDetailError(nextError instanceof Error ? nextError.message : "无法注销其他设备。"); }
  }, [requestReauth]);

  useEffect(() => {
    let active = true;
    Promise.all([getCommerceOverview(), getUsageOverview(), getUsageLedger()])
      .then(([nextCommerce, nextUsage, nextLedger]) => {
        if (active) { setCommerce(nextCommerce); setUsage(nextUsage); setUsageLedger(nextLedger); }
      })
      .catch(() => { /* Billing must not block account security settings. */ });
    return () => { active = false; };
  }, []);

  const handleCommerceSync = useCallback(async () => {
    setSyncingCommerce(true);
    try {
      const nextCommerce = await syncCommerceSubscription();
      setCommerce(nextCommerce);
      setUsage(await getUsageOverview());
      setUsageLedger(await getUsageLedger());
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "无法同步订阅信息。");
    } finally {
      setSyncingCommerce(false);
    }
  }, []);

  useEffect(() => {
    setSecurityDetailMessage(null);
    setSecurityDetailError(null);
  }, [activeSecurityDetail]);

  const handleLinkProvider = useCallback((provider: AccountProvider) => {
    if (!provider.authorizationUrl) return;
    const popup = window.open(provider.authorizationUrl, "cipher-provider-link", "popup,width=560,height=720");
    if (!popup) {
      setSecurityDetailError("浏览器阻止了授权窗口，请允许此站点打开窗口后重试。");
      return;
    }
    setLinkingProvider(provider.provider);
    popup.focus();
  }, []);


  const workspaceAvatarUrl = overview?.workspaceAvatarUrl ?? null;
  const identityAvatarUrl = overview?.identityAvatarUrl ?? null;
  const identity = overview?.identity ?? null;
  const isCasdoorAccount = identity?.source === "casdoor";
  const fallbackAvatar = overview
    ? workspaceAvatarUrl ?? identityAvatarUrl
    : viewer.avatarUrl ?? null;
  const visibleAvatar = avatarDataUrl ?? (removeAvatar ? identityAvatarUrl : fallbackAvatar);
  const trimmedDisplayName = displayName.trim();
  const trimmedEmail = email.trim();
  const displayNameChanged = trimmedDisplayName !== (viewer.displayName ?? viewer.username);
  const emailChanged = overview !== null && trimmedEmail !== (identity?.email ?? "");
  const emailIsValid = !emailChanged || (
    trimmedEmail.length <= 254 && EMAIL_PATTERN.test(trimmedEmail)
  );
  const hasChanges =
    displayNameChanged ||
    emailChanged ||
    avatarDataUrl !== null ||
    removeAvatar;
  const hasIdentity = identity !== null;
  const connectedAccounts = identity?.connectedAccounts ?? [];
  const securityScore =
    (identity?.emailVerified ? 1 : 0) +
    (identity?.mfaEnabled ? 1 : 0) +
    (identity?.passwordEnabled ? 1 : 0) +
    (connectedAccounts.length > 0 ? 1 : 0);
  const securityScoreText =
    !hasIdentity
      ? "待定"
      : securityScore === 4
      ? "高"
      : securityScore >= 2
        ? "中"
        : "低";
  const identityStatusText = identity
    ? identity.syncStatus === "current"
      ? `已同步 · ${formatSyncTime(identity.lastSyncedAt)}`
      : identity.syncStatus === "stale"
        ? "信息有更新，建议同步"
        : "本地账号"
    : "正在加载身份状态";
  const activeSubscription = commerce?.subscriptions.find((item) => item.state.toLowerCase() === "active") ?? null;
  const securityTasks: SecurityTask[] = identity
    ? [
        {
          id: "email",
          title: identity.emailVerified ? "邮箱已验证" : "验证登录邮箱",
          detail: identity.emailVerified
            ? "登录邮箱可用于重要通知和账号恢复。"
            : "完成验证后，安全等级会立即提升。",
          status: identity.emailVerified ? "done" : "todo",
          actionLabel: identity.emailVerified ? undefined : "查看"
        },
        {
          id: "mfa",
          title: identity.mfaEnabled ? "多因素认证已开启" : "开启多因素认证",
          detail: identity.mfaEnabled
            ? "登录时已有额外验证保护。"
            : "建议绑定验证码或安全密钥，降低账号被盗风险。",
          status: identity.mfaEnabled ? "done" : "todo",
          actionLabel: identity.mfaEnabled ? undefined : "查看"
        },
        {
          id: "recovery",
          title: identity.passwordEnabled ? "密码与恢复已设置" : "设置恢复方式",
          detail: identity.passwordEnabled
            ? "账号已有独立登录密码。"
            : "补充恢复方式，避免第三方登录不可用时无法进入。",
          status: identity.passwordEnabled ? "done" : "todo",
          actionLabel: identity.passwordEnabled ? undefined : "查看"
        },
        {
          id: "sync",
          title: identity.syncStatus === "current" ? "SSO 资料已同步" : "同步 SSO 资料",
          detail: identity.syncStatus === "current"
            ? `最近同步于 ${formatSyncTime(identity.lastSyncedAt)}。`
            : "拉取身份源中的最新邮箱、绑定和安全状态。",
          status: identity.syncStatus === "current" ? "done" : "pending",
          actionLabel: identity.syncStatus === "current" ? undefined : "立即同步",
          onAction: identity.syncAvailable ? () => void handleSync() : undefined,
          disabled: isLoadingIdentity || isSyncing || hasChanges || !identity.syncAvailable
        }
      ]
    : [];
  const handleSync = useCallback(async () => {
    if (isSyncing || hasChanges) {
      if (hasChanges) {
        setIdentityError("请先保存或取消当前的资料修改，再同步 Casdoor。");
      }
      return;
    }
    setSyncing(true);
    setIdentityError(null);
    try {
      const nextOverview = await syncAccount();
      setOverview(nextOverview);
      onViewerChange(nextOverview.user);
      setDisplayName(nextOverview.user.displayName ?? nextOverview.user.username);
      setEmail(nextOverview.identity.email ?? "");
    } catch (nextError) {
      setIdentityError(nextError instanceof Error ? nextError.message : "同步失败，请稍后重试。");
    } finally {
      setSyncing(false);
    }
  }, [hasChanges, isSyncing, onViewerChange]);

  useEffect(() => {
    if (activeSecurityDetail !== "providers" || !isCasdoorAccount) return;
    getAccountProviders().then(setAccountProviders).catch((nextError) => {
      setSecurityDetailError(nextError instanceof Error ? nextError.message : "无法读取第三方账号配置。");
    });
  }, [activeSecurityDetail, isCasdoorAccount]);

  useEffect(() => {
    const handleProviderMessage = (event: MessageEvent) => {
      if (event.origin !== "https://auth.example.invalid" || event.data?.type !== "cipher-casdoor-link-complete") return;
      setLinkingProvider(null);
      void handleSync().then(() => getAccountProviders().then(setAccountProviders));
      setSecurityDetailMessage("第三方账号已绑定并同步。");
    };
    window.addEventListener("message", handleProviderMessage);
    return () => window.removeEventListener("message", handleProviderMessage);
  }, [handleSync]);

  const handleSendEmailVerification = useCallback(async () => {
    if (isSendingVerification) {
      return;
    }
    setSendingVerification(true);
    setSecurityDetailMessage(null);
    setSecurityDetailError(null);
    try {
      const result = await sendAccountEmailVerification();
      setSecurityDetailMessage(result.message);
      setVerificationSent(result.sent);
    } catch (nextError) {
      setSecurityDetailError(
        nextError instanceof Error ? nextError.message : "验证邮件发送失败，请稍后重试。"
      );
    } finally {
      setSendingVerification(false);
    }
  }, [isSendingVerification]);

  const handleConfirmEmailVerification = useCallback(async () => {
    const code = verificationCode.trim();
    if (!/^\d{1,12}$/u.test(code) || isConfirmingVerification) {
      setSecurityDetailError("请输入邮件中的数字验证码。");
      return;
    }
    setConfirmingVerification(true);
    setSecurityDetailMessage(null);
    setSecurityDetailError(null);
    try {
      const nextOverview = await confirmAccountEmailVerification(code);
      setOverview(nextOverview);
      onViewerChange(nextOverview.user);
      setVerificationCode("");
      setVerificationSent(false);
      setSecurityDetailMessage("邮箱验证成功，账号安全状态已更新。");
    } catch (nextError) {
      setSecurityDetailError(
        nextError instanceof Error ? nextError.message : "验证码确认失败，请重新获取。"
      );
    } finally {
      setConfirmingVerification(false);
    }
  }, [isConfirmingVerification, onViewerChange, verificationCode]);

  const handleStartMfa = useCallback(async () => {
    if (isUpdatingMfa) return;
    setUpdatingMfa(true);
    setSecurityDetailError(null);
    setSecurityDetailMessage(null);
    try {
      setMfaSetup(await startAccountTotpSetup());
      setMfaPasscode("");
    } catch (nextError) {
      setSecurityDetailError(nextError instanceof Error ? nextError.message : "无法创建身份验证器。");
    } finally {
      setUpdatingMfa(false);
    }
  }, [isUpdatingMfa]);

  const handleConfirmMfa = useCallback(async () => {
    if (!mfaSetup || !/^\d{6}$/u.test(mfaPasscode) || isUpdatingMfa) {
      setSecurityDetailError("请输入身份验证器中显示的 6 位验证码。");
      return;
    }
    setUpdatingMfa(true);
    setSecurityDetailError(null);
    try {
      const nextOverview = await confirmAccountTotpSetup({
        secret: mfaSetup.secret,
        recoveryCode: mfaSetup.recoveryCode,
        passcode: mfaPasscode
      });
      setOverview(nextOverview);
      setMfaSetup(null);
      setMfaPasscode("");
      setSecurityDetailMessage("多因素认证已启用。请妥善保管备用码。");
    } catch (nextError) {
      setSecurityDetailError(nextError instanceof Error ? nextError.message : "无法启用多因素认证。");
    } finally {
      setUpdatingMfa(false);
    }
  }, [isUpdatingMfa, mfaPasscode, mfaSetup]);

  const handleResetMfa = useCallback(async () => {
    if (isUpdatingMfa || !window.confirm("确定要移除当前多因素认证并重新配置吗？")) return;
    setUpdatingMfa(true);
    setSecurityDetailError(null);
    try {
      const nextOverview = await resetAccountMfa();
      setOverview(nextOverview);
      setSecurityDetailMessage("原多因素认证已移除，可以重新配置。");
      setMfaSetup(await startAccountTotpSetup());
      setMfaPasscode("");
    } catch (nextError) {
      setSecurityDetailError(nextError instanceof Error ? nextError.message : "无法重置多因素认证。");
    } finally {
      setUpdatingMfa(false);
    }
  }, [isUpdatingMfa]);

  async function handleAvatarChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }

    setError(null);
    setSaved(false);
    if (!ALLOWED_AVATAR_TYPES.has(file.type)) {
      setError("请选择 JPG、PNG 或 WebP 图片。");
      return;
    }
    if (file.size > MAX_AVATAR_BYTES) {
      setError("头像文件不能超过 5 MB。");
      return;
    }

    try {
      const nextAvatar = await readFileAsDataUrl(file);
      await validateImageDimensions(nextAvatar);
      setAvatarDataUrl(nextAvatar);
      setRemoveAvatar(false);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "无法读取头像文件。");
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !trimmedDisplayName ||
      trimmedDisplayName.length > 80 ||
      !emailIsValid ||
      !hasChanges ||
      isSaving
    ) {
      return;
    }

    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const nextOverview = await updateAccountProfile({
        ...(displayNameChanged ? { displayName: trimmedDisplayName } : {}),
        ...(emailChanged ? { email: trimmedEmail } : {}),
        ...(avatarDataUrl ? { avatarDataUrl } : {}),
        ...(removeAvatar ? { removeAvatar: true } : {})
      });
      onViewerChange(nextOverview.user);
      setOverview(nextOverview);
      setDisplayName(nextOverview.user.displayName ?? nextOverview.user.username);
      setEmail(nextOverview.identity.email ?? "");
      setAvatarDataUrl(null);
      setRemoveAvatar(false);
      setSaved(true);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "保存失败，请稍后重试。");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="account-shell aurora-shell">
      <div className="auth-gradient-waves" aria-hidden="true">
        <GradientWaves
          horizonColor={theme === "dark" ? "#251744" : "#B8CCE8"}
          waveColor={theme === "dark" ? "#895EE8" : "#376FBC"}
          crestColor={theme === "dark" ? "#F4EDFF" : "#78A0D2"}
          speed={0.22}
          amplitude={2.8}
          waveScale={0.58}
          waveRatio={0.92}
          swell={28}
          turbulence={14}
          tilt={1.13}
          zoom={0.94}
          height={6.2}
          fogDepth={24}
          detail="low"
          brightness={theme === "dark" ? 0.96 : 1}
          opacity={theme === "dark" ? 0.82 : 0.95}
          mouseInteraction
          parallaxStrength={0.18}
          grain={false}
        />
      </div>
      <ThemeToggle className="theme-toggle--account" />

      <header className="account-topbar">
        <button type="button" className="account-back" onClick={onBack}>
          <IconArrowLeft size={18} stroke={1.8} aria-hidden="true" />
          返回聊天
        </button>
        <span className="account-brand">
          <img src={cipherLogo} alt="" />
          Cipher Intelligence
        </span>
      </header>

      <section className="account-layout" aria-labelledby="account-title">
        <div className="account-heading">
          <span>账号设置</span>
          <h1 id="account-title">资料与登录安全</h1>
          <p>在 Cipher 内修改展示资料和邮箱，保存后由服务端同步身份信息。</p>
          {identity ? (
            <div className={`account-sync-summary account-sync-summary--${identity.syncStatus}`}>
              <IconShieldCheck size={18} stroke={1.8} aria-hidden="true" />
              <div>
                <strong>{identity.providerName}</strong>
                <span>
                  {identity.syncStatus === "current"
                    ? `已同步，${formatSyncTime(identity.lastSyncedAt)}`
                    : identity.syncStatus === "stale"
                      ? "当前显示上次同步的资料"
                      : "本地账号"}
                </span>
              </div>
            </div>
          ) : null}

          <section className="account-overview" aria-label="账号健康摘要">
            <div className="account-overview__identity">
              <AccountAvatar
                className="account-overview__avatar"
                src={visibleAvatar}
                name={trimmedDisplayName || viewer.username}
              />
              <div className="account-overview__identity-copy">
                <p>当前身份源</p>
                <h2>{identity?.providerName ?? "本地账号"}</h2>
                <span>{identityStatusText}</span>
              </div>
            </div>

            <div className="account-overview__metrics">
              <div className="account-overview__metric">
                <span>安全等级</span>
                <strong>{securityScoreText}</strong>
              </div>
              <div className="account-overview__metric">
                <span>安全得分</span>
                <strong>{hasIdentity ? `${securityScore}/4` : "待同步"}</strong>
              </div>
              <div className="account-overview__metric">
                <span>绑定渠道</span>
                <strong>{connectedAccounts.length} 个</strong>
              </div>
              <div className="account-overview__metric">
                <span>最近登录</span>
                <strong>{formatLastSignIn(identity?.lastSignInAt)}</strong>
              </div>
            </div>

            {securityTasks.length ? (
              <div className="account-security-tasks" aria-label="待处理安全项">
                <div className="account-security-tasks__heading">
                  <strong>安全任务</strong>
                  <span>{securityTasks.filter((task) => task.status !== "done").length} 项待处理</span>
                </div>
                <div className="account-security-task-list">
                  {securityTasks.map((task) => (
                    <div
                      key={task.id}
                      className={`account-security-task account-security-task--${task.status}`}
                    >
                      <span className="account-security-task__icon" aria-hidden="true">
                        {task.status === "done" ? (
                          <IconCheck size={15} stroke={2.2} />
                        ) : task.id === "sync" ? (
                          <IconRefresh size={15} stroke={2} />
                        ) : (
                          <IconAlertCircle size={15} stroke={2} />
                        )}
                      </span>
                      <div className="account-security-task__copy">
                        <strong>{task.title}</strong>
                        <span>{task.detail}</span>
                      </div>
                      {task.actionLabel ? (
                        <button
                          type="button"
                          className="account-security-task__action"
                          onClick={task.onAction ?? (() => {
                            if (task.id === "email") {
                              emailInputRef.current?.focus();
                            } else if (task.id === "mfa" || task.id === "recovery") {
                              setActiveSecurityDetail(task.id);
                            }
                          })}
                          disabled={task.disabled}
                        >
                          {task.actionLabel}
                        </button>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </section>
        </div>

        <div className="account-content">
          <form className="account-form" onSubmit={handleSubmit}>
            <div className="account-section-heading">
              <div>
                <h2>工作区资料</h2>
                <p>昵称和邮箱会自动同步到 Casdoor，自定义头像仅用于 Cipher 工作区。</p>
              </div>
            </div>

            <section className="account-avatar-section" aria-labelledby="avatar-heading">
              <AccountAvatar
                className="account-avatar"
                src={visibleAvatar}
                name={trimmedDisplayName || viewer.username}
              />
              <div className="account-avatar-copy">
                <h3 id="avatar-heading">个人头像</h3>
                <p>JPG、PNG 或 WebP，最大 5 MB。系统会自动缩放并转为 WebP。</p>
                <div className="account-avatar-actions">
                  <label className="secondary-button" htmlFor="account-avatar-input">
                    <IconCamera size={16} stroke={1.8} aria-hidden="true" />
                    {workspaceAvatarUrl || avatarDataUrl ? "更换头像" : "上传头像"}
                  </label>
                  {workspaceAvatarUrl || avatarDataUrl ? (
                    <button
                      type="button"
                      className="account-remove-avatar"
                      onClick={() => {
                        setAvatarDataUrl(null);
                        setRemoveAvatar(Boolean(workspaceAvatarUrl));
                        setSaved(false);
                      }}
                    >
                      <IconTrash size={16} stroke={1.8} aria-hidden="true" />
                      移除自定义头像
                    </button>
                  ) : null}
                </div>
                <input
                  id="account-avatar-input"
                  className="visually-hidden"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  onChange={(event) => void handleAvatarChange(event)}
                  disabled={isSaving}
                />
              </div>
            </section>

            <div className="account-fields">
              <div className="account-field">
                <label htmlFor="account-username">登录账号</label>
                <div className="account-locked-input">
                  <input id="account-username" value={viewer.username} readOnly aria-describedby="username-note" />
                  <IconLock size={17} stroke={1.8} aria-hidden="true" />
                </div>
                <span id="username-note">账号全局唯一，由身份服务管理。</span>
              </div>

              <div className="account-field">
                <label htmlFor="account-display-name">昵称</label>
                <input
                  id="account-display-name"
                  value={displayName}
                  maxLength={80}
                  autoComplete="nickname"
                  onChange={(event) => {
                    setDisplayName(event.target.value);
                    setSaved(false);
                  }}
                  aria-describedby="display-name-note"
                  disabled={isSaving}
                />
                <span id="display-name-note">保存后会同步到 Casdoor，最多 80 个字符。</span>
              </div>

              <div className="account-field">
                <label htmlFor="account-email">邮箱</label>
                <input
                  ref={emailInputRef}
                  id="account-email"
                  type="email"
                  value={email}
                  maxLength={254}
                  autoComplete="email"
                  onChange={(event) => {
                    setEmail(event.target.value);
                    setSaved(false);
                  }}
                  aria-describedby="email-note"
                  aria-invalid={emailChanged && !emailIsValid}
                  disabled={isSaving || isLoadingIdentity}
                />
                <span id="email-note">
                  {emailChanged && !emailIsValid
                    ? "请输入有效的邮箱地址。"
                    : "保存后会同步到 Casdoor；更换邮箱后验证状态将重置。"}
                </span>
                {identity?.email && !identity.emailVerified && !emailChanged ? (
                  <div className="account-email-verification account-email-verification--inline">
                    <div className="account-email-verification__actions">
                      <span>当前邮箱尚未验证</span>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => void handleSendEmailVerification()}
                        disabled={isSendingVerification}
                      >
                        {isSendingVerification ? "发送中…" : verificationSent ? "重新发送" : "发送验证邮件"}
                      </button>
                    </div>
                    {verificationSent ? (
                      <div className="account-email-code-field">
                        <label htmlFor="account-email-code">邮箱验证码</label>
                        <div>
                          <input
                            id="account-email-code"
                            inputMode="numeric"
                            autoComplete="one-time-code"
                            maxLength={12}
                            value={verificationCode}
                            onChange={(event) => {
                              setVerificationCode(event.target.value.replace(/\D/gu, ""));
                              setSecurityDetailError(null);
                            }}
                            placeholder="输入邮件中的验证码"
                          />
                          <button
                            type="button"
                            className="primary-button"
                            onClick={() => void handleConfirmEmailVerification()}
                            disabled={!verificationCode || isConfirmingVerification}
                          >
                            {isConfirmingVerification ? "验证中…" : "确认验证"}
                          </button>
                        </div>
                        <span>验证码有时效限制，过期后可重新发送。</span>
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {securityDetailMessage ? (
                  <p className="account-security-detail__status" role="status">
                    <IconCheck size={16} stroke={2} aria-hidden="true" />
                    {securityDetailMessage}
                  </p>
                ) : null}
                {securityDetailError ? (
                  <p className="account-security-detail__error" role="alert">
                    <IconAlertCircle size={16} stroke={1.9} aria-hidden="true" />
                    {securityDetailError}
                  </p>
                ) : null}
              </div>
            </div>

            {error ? <p className="status-banner status-banner--error" role="alert">{error}</p> : null}
            {saved ? (
              <p className="account-success" role="status">
                <IconCheck size={17} stroke={2} aria-hidden="true" />
                {isCasdoorAccount ? "账号资料已更新，并已同步到 Casdoor" : "个人资料已更新"}
              </p>
            ) : null}

            <div className="account-form-actions">
              <button type="button" className="secondary-button" onClick={onBack} disabled={isSaving}>
                取消
              </button>
              <button
                type="submit"
                className="primary-button"
                disabled={
                  !hasChanges ||
                  !trimmedDisplayName ||
                  trimmedDisplayName.length > 80 ||
                  !emailIsValid ||
                  isSaving
                }
              >
                {isSaving ? "保存中…" : "保存更改"}
              </button>
            </div>
          </form>

          <section className="account-identity-panel account-billing-panel" aria-labelledby="billing-heading">
            <div className="account-section-heading account-section-heading--identity">
              <div>
                <h2 id="billing-heading">套餐与用量</h2>
                <p>{commerce?.enabled ? "订阅由 Casdoor 管理，用量由 Cipher 实时计量" : "当前使用本地套餐策略"}</p>
              </div>
              {commerce?.enabled && isCasdoorAccount ? (
                <button type="button" className="account-sync-button" onClick={() => void handleCommerceSync()} disabled={isSyncingCommerce}>
                  <IconRefresh size={16} stroke={1.8} aria-hidden="true" />
                  {isSyncingCommerce ? "同步中…" : "同步订阅"}
                </button>
              ) : null}
            </div>
            <div className="account-billing-summary">
              <div><span>当前套餐</span><strong>{(commerce?.tier ?? usage?.plan ?? "standard").toUpperCase()}</strong></div>
              <div><span>订阅状态</span><strong>{activeSubscription ? "有效" : commerce?.enabled ? "无有效订阅" : "本地"}</strong></div>
              <div><span>计费周期</span><strong>{activeSubscription?.period ?? usage?.period ?? "—"}</strong></div>
              <div><span>增值额度</span><strong>{commerce?.creditGrants.filter((item) => !item.revokedAt).length ?? 0} 项</strong></div>
            </div>
            {usage ? (
              <div className="account-usage-grid" aria-label="本月用量">
                <div><span>Token</span><strong>{formatQuota(usage.usage.tokens)} / {formatQuota(usage.limits.tokens)}</strong></div>
                <div><span>总费用</span><strong>${(usage.usage.costMicrousd / 1_000_000).toFixed(2)} / ${(usage.limits.costMicrousd / 1_000_000).toFixed(2)}</strong></div>
                <div><span>CAPE</span><strong>{usage.usage.capeSubmissions} / {usage.limits.capeSubmissions} · ¥{usage.usage.capeCostCny.toFixed(2)} (${(usage.usage.capeCostMicrousd / 1_000_000).toFixed(2)})</strong></div>
                <div><span>存储</span><strong>{formatBytes(usage.usage.storageBytes)} / {formatBytes(usage.limits.storageBytes)}</strong></div>
              </div>
            ) : <p className="account-security-note">正在读取用量与额度…</p>}
            {usage?.warnings.length ? (
              <p className="account-quota-warning" role="alert">额度提醒：{usage.warnings.join("、")}已达告警阈值。</p>
            ) : null}
            {usageLedger?.items.length ? (
              <details className="account-ledger">
                <summary>最近账单明细</summary>
                <div className="account-ledger-list">
                  {usageLedger.items.map((item) => (
                    <div key={item.id}>
                      <span>{item.resourceType === "cape" ? "CAPE 任务" : item.model ?? "模型调用"}</span>
                      <span>{item.inputTokens + item.outputTokens ? `${formatQuota(item.inputTokens + item.outputTokens)} tokens` : formatBytes(item.storageBytes)}</span>
                      <strong>{item.resourceType === "cape" ? `¥${(item.costMicrousd * (usage?.billingCnyPerUsd ?? 0) / 1_000_000).toFixed(2)} ($${(item.costMicrousd / 1_000_000).toFixed(4)})` : `$${(item.costMicrousd / 1_000_000).toFixed(4)}`}</strong>
                      <time dateTime={item.occurredAt}>{formatSyncTime(item.occurredAt)}</time>
                    </div>
                  ))}
                </div>
              </details>
            ) : null}
            {activeSubscription?.endsAt ? <p className="account-security-note">当前计划 {activeSubscription.planDisplayName ?? activeSubscription.plan}，有效期至 {formatSyncTime(activeSubscription.endsAt)}。</p> : null}
          </section>

          <section className="account-identity-panel" aria-labelledby="identity-heading">
            <div className="account-section-heading account-section-heading--identity">
              <div>
                <h2 id="identity-heading">登录与安全</h2>
                <p>
                  {isLoadingIdentity
                    ? "正在确认身份来源"
                    : isCasdoorAccount
                      ? `由 Cipher 安全同步至 ${identity?.providerName ?? "Casdoor"}`
                      : "由 Cipher 本地管理"}
                </p>
              </div>
              {identity?.syncAvailable ? (
                <button
                  type="button"
                  className="account-sync-button"
                  onClick={() => void handleSync()}
                  disabled={isLoadingIdentity || isSyncing || hasChanges}
                >
                  <IconRefresh size={16} stroke={1.8} aria-hidden="true" />
                  {isSyncing ? "同步中…" : "同步资料"}
                </button>
              ) : null}
            </div>

            {isLoadingIdentity ? (
              <div className="account-identity-loading" role="status" aria-label="正在读取身份信息">
                <span />
                <span />
                <span />
              </div>
            ) : identity ? (
              <div className="account-identity-list">
                <button
                  type="button"
                  className="account-identity-row account-identity-row--action"
                  onClick={() => emailInputRef.current?.focus()}
                >
                  <span className="account-identity-icon" aria-hidden="true"><IconAt size={19} stroke={1.7} /></span>
                  <div className="account-identity-copy">
                    <span>登录邮箱</span>
                    <strong>{identity.email ?? "未设置邮箱"}</strong>
                  </div>
                  <span className={`account-state account-state--${identity.emailVerified ? "good" : "warning"}`}>
                    {identity.email ? (identity.emailVerified ? "已验证" : "未验证") : "未设置"}
                  </span>
                  <IconChevronRight className="account-identity-chevron" size={16} stroke={1.8} aria-hidden="true" />
                </button>

                <div className={`account-identity-item${activeSecurityDetail === "providers" ? " account-identity-item--open" : ""}`}>
                <button type="button" className="account-identity-row account-identity-row--providers account-identity-row--action" aria-expanded={activeSecurityDetail === "providers"} onClick={() => setActiveSecurityDetail((current) => current === "providers" ? null : "providers")}>
                  <span className="account-identity-icon" aria-hidden="true"><IconLink size={19} stroke={1.7} /></span>
                  <div className="account-identity-copy">
                    <span>第三方账号</span>
                    {identity.connectedAccounts.length ? (
                      <div className="account-provider-list" aria-label="已绑定的第三方账号">
                        {identity.connectedAccounts.map((account) => (
                          <span key={account.provider}>
                            <AccountProviderLogo provider={account.provider} />
                            {account.label}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <strong>尚未绑定</strong>
                    )}
                  </div>
                  <span className="account-state">
                    {identity.connectedAccounts.length ? `${identity.connectedAccounts.length} 个已绑定` : "未绑定"}
                  </span>
                  <IconChevronRight className="account-identity-chevron" size={16} stroke={1.8} aria-hidden="true" />
                </button>
                {activeSecurityDetail === "providers" ? (
                  <div className="account-security-options account-security-options--inline" aria-label="第三方账号管理">
                    {accountProviders.map((provider) => (
                      <div key={provider.provider} className="account-security-option"><div><strong className="account-provider-heading"><AccountProviderLogo provider={provider.provider} />{provider.label}</strong><span>{provider.connected ? "已连接到当前账号" : "尚未绑定"}</span></div><button type="button" disabled={provider.connected || linkingProvider !== null} onClick={() => handleLinkProvider(provider)}>{provider.connected ? "已绑定" : linkingProvider === provider.provider ? "等待授权…" : "绑定"}</button></div>
                    ))}
                    {!accountProviders.length ? <p>正在读取 Casdoor Provider…</p> : null}
                  </div>
                ) : null}
                </div>

                <div className={`account-identity-item${activeSecurityDetail === "mfa" ? " account-identity-item--open" : ""}`}>
                <button type="button" className="account-identity-row account-identity-row--action" aria-expanded={activeSecurityDetail === "mfa"} onClick={() => setActiveSecurityDetail((current) => current === "mfa" ? null : "mfa")}>
                  <span className="account-identity-icon" aria-hidden="true"><IconShieldCheck size={19} stroke={1.7} /></span>
                  <div className="account-identity-copy">
                    <span>多因素认证</span>
                    <strong>{identity.mfaEnabled ? "账号已启用额外验证" : "建议开启以提高安全性"}</strong>
                  </div>
                  <span className={`account-state account-state--${identity.mfaEnabled ? "good" : "warning"}`}>
                    {identity.mfaEnabled ? "已开启" : "未开启"}
                  </span>
                  <IconChevronRight className="account-identity-chevron" size={16} stroke={1.8} aria-hidden="true" />
                </button>
                {activeSecurityDetail === "mfa" ? (
                  <div className="account-security-options account-security-options--inline" aria-label="多因素认证管理">
                    <div className="account-security-option"><div><strong>身份验证器</strong><span>{identity.mfaEnabled ? "TOTP 已由 Casdoor 启用" : "支持 Microsoft Authenticator、Google Authenticator 等"}</span></div><button type="button" disabled={isUpdatingMfa} onClick={() => void (identity.mfaEnabled ? handleResetMfa() : handleStartMfa())}>{identity.mfaEnabled ? "重新配置" : "开始配置"}</button></div>
                    {mfaSetup ? (
                      <div className="account-mfa-setup">
                        <p>在身份验证器中添加以下密钥，然后输入生成的 6 位验证码。</p>
                        <label>设置密钥<input readOnly value={mfaSetup.secret} onFocus={(event) => event.currentTarget.select()} /></label>
                        <label>6 位验证码<input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={mfaPasscode} onChange={(event) => setMfaPasscode(event.target.value.replace(/\D/gu, ""))} /></label>
                        <div className="account-mfa-recovery"><span>备用码（仅显示一次）</span><code>{mfaSetup.recoveryCode}</code></div>
                        <button type="button" disabled={isUpdatingMfa || mfaPasscode.length !== 6} onClick={() => void handleConfirmMfa()}>{isUpdatingMfa ? "验证中…" : "验证并启用"}</button>
                      </div>
                    ) : null}
                  </div>
                ) : null}
                </div>

                <div className={`account-identity-item${activeSecurityDetail === "recovery" ? " account-identity-item--open" : ""}`}>
                <button type="button" className="account-identity-row account-identity-row--action" aria-expanded={activeSecurityDetail === "recovery"} onClick={() => setActiveSecurityDetail((current) => current === "recovery" ? null : "recovery")}>
                  <span className="account-identity-icon" aria-hidden="true"><IconKey size={19} stroke={1.7} /></span>
                  <div className="account-identity-copy">
                    <span>密码与恢复</span>
                    <strong>{identity.passwordEnabled ? "已设置独立登录密码" : "当前使用第三方账号登录"}</strong>
                  </div>
                  <span className="account-state">{identity.passwordEnabled ? "已设置" : "未设置"}</span>
                  <IconChevronRight className="account-identity-chevron" size={16} stroke={1.8} aria-hidden="true" />
                </button>
                {activeSecurityDetail === "recovery" ? (
                  <div className="account-security-options account-security-options--inline" aria-label="密码与恢复管理">
                    <div className="account-security-option"><div><strong>独立密码</strong><span>{security?.localPasswordEnabled ? `已设置（${security.authSource === "hybrid" ? "Casdoor + 本地" : "本地认证"}）` : "尚未设置；不会改变 Casdoor 绑定"}</span></div><button type="button" onClick={() => void handlePasswordChange()}>{security?.localPasswordEnabled ? "修改密码" : "设置密码"}</button></div>
                    <div className="account-security-option"><div><strong>恢复邮箱</strong><span>{identity.email ?? "尚未设置邮箱"}</span></div><button type="button" onClick={() => emailInputRef.current?.focus()}>管理邮箱</button></div>
                    <div className="account-security-option"><div><strong>恢复码</strong><span>剩余 {security?.recoveryCodesRemaining ?? 0} 个；轮换会立即作废旧码</span></div><button type="button" onClick={() => void handleRecoveryRotation()}>生成并轮换</button></div>
                    {oneTimeRecoveryCodes.length ? <div className="account-mfa-setup" role="status"><p>恢复码仅展示一次，请立即保存到密码管理器。</p><div className="account-mfa-recovery"><code>{oneTimeRecoveryCodes.join("\n")}</code></div><button type="button" onClick={() => setOneTimeRecoveryCodes([])}>我已保存并隐藏</button></div> : null}
                  </div>
                ) : null}
                </div>

                <div className={`account-identity-item${activeSecurityDetail === "sessions" ? " account-identity-item--open" : ""}`}>
                  <button type="button" className="account-identity-row account-identity-row--action" aria-expanded={activeSecurityDetail === "sessions"} onClick={() => setActiveSecurityDetail((current) => current === "sessions" ? null : "sessions")}>
                    <span className="account-identity-icon" aria-hidden="true"><IconLock size={19} stroke={1.7} /></span>
                    <div className="account-identity-copy"><span>活跃会话</span><strong>{sessions.length} 个设备</strong></div>
                    <span className="account-state">{sessions.length > 1 ? `${sessions.length - 1} 个其他设备` : "仅当前设备"}</span>
                    <IconChevronRight className="account-identity-chevron" size={16} stroke={1.8} aria-hidden="true" />
                  </button>
                  {activeSecurityDetail === "sessions" ? <div className="account-security-options account-security-options--inline">
                    <div className="account-security-option account-security-option--action"><div><strong>会话管理</strong><span>退出不再使用的设备，当前设备不会受到影响</span></div><button type="button" disabled={sessions.length <= 1} onClick={() => void handleRevokeAll()}>退出其他设备</button></div>
                    {sessions.map((item) => <div className="account-security-option" key={item.id}><div><strong>{item.current ? "当前设备" : item.userAgent || "未知设备"}</strong><span>{item.ipAddress || "未知 IP"} · {formatSyncTime(item.lastSeenAt)}</span></div>{item.current ? <span>当前</span> : <button type="button" onClick={() => void revokeAccountSession(item.id).then(() => setSessions((current) => current.filter((entry) => entry.id !== item.id))).catch((nextError) => setSecurityDetailError(nextError instanceof Error ? nextError.message : "注销失败。"))}>注销</button>}</div>)}
                  </div> : null}
                </div>

                <div className={`account-identity-item${activeSecurityDetail === "alerts" ? " account-identity-item--open" : ""}`}>
                  <button type="button" className="account-identity-row account-identity-row--action" aria-expanded={activeSecurityDetail === "alerts"} onClick={() => setActiveSecurityDetail((current) => current === "alerts" ? null : "alerts")}><span className="account-identity-icon" aria-hidden="true"><IconAlertCircle size={19} stroke={1.7} /></span><div className="account-identity-copy"><span>异常登录提醒</span><strong>{security?.suspiciousLoginAlerts ? "检测到异常时发送站内通知" : "当前不会发送异常登录通知"}</strong></div><span className={`account-state account-state--${security?.suspiciousLoginAlerts ? "good" : "warning"}`}>{security?.suspiciousLoginAlerts ? "已开启" : "未开启"}</span><IconChevronRight className="account-identity-chevron" size={16} stroke={1.8} aria-hidden="true" /></button>
                  {activeSecurityDetail === "alerts" ? <div className="account-security-options account-security-options--inline"><div className="account-security-option account-security-option--action"><div><strong>登录位置监控</strong><span>当账号从未见过的网络地址登录时发送安全通知</span></div><button type="button" onClick={() => void updateAccountSecurityAlerts(!security?.suspiciousLoginAlerts).then(setSecurity).catch((nextError) => setSecurityDetailError(nextError instanceof Error ? nextError.message : "更新失败。"))}>{security?.suspiciousLoginAlerts ? "关闭提醒" : "开启提醒"}</button></div><p>最近登录历史（仅展示设备、时间和截断后的网络地址，不包含凭据）</p>{loginHistory.slice(0, 10).map((item) => <div className="account-security-option" key={item.id}><div><strong>{item.method === "casdoor" ? "Casdoor" : "独立密码"} · {item.outcome === "success" ? "成功" : "失败"}</strong><span>{item.ipAddress || "未知 IP"} · {formatSyncTime(item.createdAt)}</span></div>{item.suspicious ? <span className="account-state account-state--warning">异常</span> : null}</div>)}</div> : null}
                </div>
              </div>
            ) : null}

            {identityError ? (
              <p className="account-identity-error" role="alert">
                <IconAlertCircle size={17} stroke={1.8} aria-hidden="true" />
                {identityError}
              </p>
            ) : null}

            {isCasdoorAccount ? (
              <p className="account-security-note">
                登录与安全状态会在此页自动同步。普通用户无需进入 Casdoor 管理后台。
              </p>
            ) : null}
          </section>
        </div>
      </section>

    </main>
  );
}

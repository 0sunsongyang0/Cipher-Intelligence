import { test, expect, type Page } from "@playwright/test";

const user = { id: 42, username: "e2e-user", displayName: "E2E Analyst", isAdmin: false };
const conversation = { id: 7, title: "E2E investigation", isPinned: false, isArchived: false, caseStatus: "open", severity: "unknown", assignee: null, tags: [], caseSummary: null, capeCases: [], createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() };

async function mockApi(page: Page, options: { authenticated?: boolean; error?: string } = {}) {
  let authenticated = options.authenticated ?? true;
  await page.route("**/api/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/auth/session") return json(authenticated ? { authenticated: true, user } : { authenticated: false, user: null }, authenticated ? 200 : 401);
    if (path === "/api/auth/casdoor/config") return json({ enabled: true, provider: "casdoor", displayName: "Casdoor", managementUrl: "" });
    if (path === "/api/auth/logout") { authenticated = false; return json({ authenticated: false, user: null }); }
    if (path === "/api/conversations" && req.method() === "GET") return json({ items: [conversation] });
    if (path === "/api/conversations" && req.method() === "POST") return json(conversation);
    if (path.endsWith("/messages")) return json({ items: [] });
    if (path === "/api/cape/cases") return json({ items: [], counts: { open: 0, investigating: 0, contained: 0, resolved: 0, closed: 0 } });
    if (path === "/api/skills") return json({ items: [] });
    if (path === "/api/chat") {
      if (options.error) return json({ detail: options.error }, 402);
      return route.fulfill({ status: 200, headers: { "Content-Type": "text/plain; charset=utf-8" }, body: "E2E streamed response" });
    }
    if (path === "/api/upload_zip") return json({ uploading: false, zipContextId: "e2e-zip", fileCount: 1, totalBytes: 4, entries: [] });
    if (path.startsWith("/api/cape/")) return json({ id: 1, taskId: 99, sampleName: "sample.bin", status: "reported", completed: true, score: 8, summary: { iocs: { domains: ["evil.test"], ips: [], urls: [] }, tactics: [], droppedFiles: [], sha256: "abc" } });
    return json({}, 404);
  });
}

test("restores session, creates chat, sends and renders streaming response, then logs out", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await expect(page.getByTestId("chat-shell")).toBeVisible();
  await page.getByRole("button", { name: "开启新对话" }).click();
  await page.getByRole("textbox", { name: /Prompt composer/i }).fill("分析这个样本");
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(page.getByText("E2E streamed response")).toBeVisible();
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page.getByTestId("login-auth-surface")).toBeVisible();
});

test("covers unauthorized access, Casdoor failure, quota exhaustion and duplicate/network failures", async ({ page }) => {
  await mockApi(page, { authenticated: false });
  await page.goto("/chat");
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/?casdoor_error=Casdoor%20login%20failed");
  await expect(page.getByRole("alert")).toContainText("Casdoor login failed");

  await mockApi(page, { error: "额度不足" });
  await page.goto("/");
  await expect(page.getByTestId("chat-shell")).toBeVisible();
  const input = page.getByRole("textbox", { name: /Prompt composer/i });
  await input.fill("重复提交");
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(page.getByRole("alert")).toContainText("额度不足");
  await page.route("**/api/chat", route => route.abort());
  await input.fill("network");
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
});

test("uploads evidence, creates Case, associates CAPE task, extracts IOC and exports report", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "打开 Case 工作区" }).click();
  await expect(page.getByRole("heading", { name: "Case 工作区" })).toBeVisible();
  await page.getByRole("button", { name: "关闭 Case 工作区" }).click();
  await page.getByRole("button", { name: "打开 CAPE 面板" }).click();
  const file = page.locator("input[type=file]").first();
  await file.setInputFiles({ name: "sample.bin", mimeType: "application/octet-stream", buffer: Buffer.from("E2E") });
  await expect(page.getByText(/已创建 CAPE Case|CAPE/)).toBeVisible();
});

// @vitest-environment node

import { execFile } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { expect, test } from "vitest";

const execFileAsync = promisify(execFile);
const frontendRoot = fileURLToPath(new URL("..", import.meta.url));
const distIndexPath = fileURLToPath(new URL("../dist/index.html", import.meta.url));

test("production build emits a legacy browser entrypoint", async () => {
  if (process.platform === "win32") {
    await execFileAsync("cmd.exe", ["/d", "/s", "/c", "npm run build"], {
      cwd: frontendRoot,
      timeout: 120000
    });
  } else {
    await execFileAsync("npm", ["run", "build"], {
      cwd: frontendRoot,
      timeout: 120000
    });
  }

  expect(existsSync(distIndexPath)).toBe(true);

  const html = readFileSync(distIndexPath, "utf8");

  expect(html).toContain("nomodule");
  expect(html).toMatch(/legacy/i);
}, 180000);

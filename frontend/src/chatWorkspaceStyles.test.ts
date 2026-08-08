import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const styles = readFileSync(join(process.cwd(), "src/styles.css"), "utf8");

describe("premium chat workspace styles", () => {
  it("tracks the supplied source-shell geometry and palette", () => {
    expect(styles).toContain("--figma-chat-page: #eef2f8");
    expect(styles).toContain("--figma-chat-canvas: #eef2f8");
    expect(styles).toContain("--figma-chat-active: #e3f0ff");
    expect(styles).toContain("--cipher-sidebar-active: #e3f0ff");
    expect(styles).toContain("--bomb-sidebar-width: 288px");
    expect(styles).toContain("flex-basis: calc(var(--bomb-sidebar-width) + 16px)");
    expect(styles).toContain("width: min(calc(100% - 96px), 896px)");
    expect(styles).toContain(".bomb-shell__sidebar-search");
  });

  it("defines the desktop reading column and state-driven composer", () => {
    expect(styles).toContain("--workspace-reading-width: 880px");
    expect(styles).toContain('.bomb-shell__dock-wrap[data-focused="true"] .bomb-shell__dock');
    expect(styles).toContain(".bomb-shell__composer-model-bar");
    expect(styles).toContain(".bomb-shell__dock-main-row");
    expect(styles).toContain(".bomb-shell__bubble--assistant .bomb-shell__response-content");
    expect(styles).toContain("min-height: 60px;");
    expect(styles).toContain(".bomb-shell__message-row--user {\n    align-items: center;");
    expect(styles).toContain(':root[data-theme="dark"] .case-workspace-drawer');
    expect(styles).toContain("background: #111019;");
    expect(styles).toContain('.bomb-shell__dock[data-multiline="true"] .bomb-shell__send-button');
    expect(styles).not.toContain("animation: pulseGlow 4s infinite ease-in-out");
  });

  it("does not apply the inline-code tint inside fenced code blocks", () => {
    expect(styles).toContain(".bomb-shell .bomb-shell__markdown .bomb-shell__code-block code {");
    expect(styles).toContain(".bomb-shell .bomb-shell__markdown .bomb-shell__math-fallback {");
    expect(styles).toContain("background: transparent;");
  });

  it("reverses the search surface and glow accents between themes", () => {
    expect(styles).toContain("--cipher-search-surface: #29203f");
    expect(styles).toContain("--cipher-search-glow: rgb(67 142 255 / 30%)");
    expect(styles).toContain("--cipher-search-surface: #edf5ff");
    expect(styles).toContain("--cipher-search-glow: rgb(129 85 255 / 24%)");
    expect(styles).toContain("border-radius: 999px");
  });

  it("lets the model menu open state override placement-specific entrance transforms", () => {
    expect(styles).toContain(".bomb-shell__model-menu.bomb-shell__model-menu--open {");
  });

  it("keeps expanded account security details light in the day theme", () => {
    expect(styles).toContain(':root[data-theme="light"] .account-heading > span');
    expect(styles).toContain(':root[data-theme="light"] .account-sync-summary > svg');
    expect(styles).toContain("background: rgba(37, 99, 235, 0.08);");
    expect(styles).toContain("background: rgba(37, 99, 235, 0.07);");
    expect(styles).toContain("color: #15803d;");
    expect(styles).toContain("color: #b45309;");
    expect(styles).toContain(':root[data-theme="light"] .account-security-options--inline');
    expect(styles).toContain(':root[data-theme="light"] .account-email-verification--inline');
    expect(styles).toContain("background: rgba(255, 255, 255, 0.62);");
    expect(styles).toContain(':root[data-theme="light"] .account-shell .account-email-verification--inline');
    expect(styles).toContain("background: #f8fafc;");
  });

  it("matches the compact two-row sidebar account reference geometry", () => {
    expect(styles).toContain("grid-template-columns: 24px minmax(0, 1fr)");
    expect(styles).toContain("height: 34px");
    expect(styles).toContain("gap: 10px");
  });

  it("keeps a visible desktop affordance for reopening the collapsed sidebar", () => {
    expect(styles).toContain(
      ".bomb-shell__main:not(.bomb-shell__main--sidebar-open) .bomb-shell__header-leading"
    );
    expect(styles).toContain(
      ".bomb-shell__main:not(.bomb-shell__main--sidebar-open) .bomb-shell__sidebar-expand-label"
    );
  });

  it("contains sidebar overflow while keeping the full-height layout visible", () => {
    expect(styles).toContain("grid-template-rows: auto minmax(0, 1fr) auto");
    expect(styles).toContain(".bomb-shell .bomb-shell__sidebar-list::-webkit-scrollbar");
    expect(styles).toContain("scrollbar-width: none;");
  });

  it("provides reduced-motion, reduced-transparency, and higher-contrast fallbacks", () => {
    expect(styles).toContain("@media (prefers-reduced-motion: reduce)");
    expect(styles).toContain(".bomb-shell {\n    scroll-behavior: auto;");
    expect(styles).toContain(".bomb-shell * {\n    animation-duration: 0.01ms !important;");
    expect(styles).toContain(".conversation-drawer__panel,\n  .settings-drawer,\n  .bomb-shell__cape-drawer {\n    transition-duration: 0.01ms !important;");
    expect(styles).toContain("@media (prefers-reduced-transparency: reduce)");
    expect(styles).toContain("backdrop-filter: none;");
    expect(styles).toContain("-webkit-backdrop-filter: none;");
    expect(styles).toContain("@media (prefers-contrast: more)");
    expect(styles).toContain("--bomb-text-primary: rgba(255, 255, 255, 0.98);");
    expect(styles).toContain("outline: 2px solid rgba(186, 203, 255, 0.96);");
  });
});

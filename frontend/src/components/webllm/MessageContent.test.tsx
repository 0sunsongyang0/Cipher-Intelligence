import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MessageContent, debugNormalizeMessageContent } from "./MessageContent";

const originalMode = import.meta.env.MODE;

afterEach(() => {
  vi.unstubAllEnvs();
  import.meta.env.MODE = originalMode;
  Reflect.deleteProperty(window, "MathJax");
  Reflect.deleteProperty(window, "__bombMathJaxReady");
  document.querySelectorAll('script[data-bomb-mathjax="true"]').forEach((script) => script.remove());
  cleanup();
});

function expectReadableMath(minCount = 1) {
  expect(document.querySelectorAll("mjx-container").length).toBeGreaterThanOrEqual(minCount);
  expect(document.querySelectorAll('[data-mml-node="merror"]')).toHaveLength(0);
  expect(document.body.textContent).not.toContain("\\(");
  expect(document.body.textContent).not.toContain("\\[");
}

describe("MessageContent", () => {
  it("renders standard MathJax delimiters as readable math", () => {
    render(
      <MessageContent
        content={String.raw`Given \(C_k = C_{k+2}\), the Fourier series is:

\[
x(t) = \sum_{k=-\infty}^{\infty} C_k e^{j k \omega_0 t}, \quad \omega_0 = \frac{2\pi}{3}.
\]

- \(C_k = C_{-k}\)
- \(\int_{-0.5}^{0.5} x(t)\,dt = 1\)`}
      />
    );

    expectReadableMath(4);
  });

  it("falls back to readable TeX instead of leaving empty math shells when MathJax fails to load", async () => {
    vi.stubEnv("MODE", "production");
    import.meta.env.MODE = "production";

    render(<MessageContent content={String.raw`公式：\(x=\frac{1}{2}\)`} />);

    const script = document.querySelector<HTMLScriptElement>('script[data-bomb-mathjax="true"]');
    script?.dispatchEvent(new Event("error"));

    await waitFor(() => expect(screen.getByText(String.raw`x=\frac{1}{2}`)).toBeInTheDocument());

    expect(
      Array.from(document.querySelectorAll(".bomb-shell__math")).filter(
        (element) => !element.children.length && !element.textContent?.trim()
      )
    ).toHaveLength(0);
  });

  it("falls back to readable TeX when the MathJax script loads without the conversion API", async () => {
    vi.stubEnv("MODE", "production");
    import.meta.env.MODE = "production";

    render(<MessageContent content={String.raw`公式：\(T=\pi/7\)，所以 \(\omega_0=14\)`} />);

    const script = document.querySelector<HTMLScriptElement>('script[data-bomb-mathjax="true"]');
    script?.dispatchEvent(new Event("load"));

    await waitFor(() => expect(screen.getByText(String.raw`T=\pi/7`)).toBeInTheDocument());
    expect(screen.getByText(String.raw`\omega_0=14`)).toBeInTheDocument();
    expect(
      Array.from(document.querySelectorAll(".bomb-shell__math")).filter(
        (element) => !element.children.length && !element.textContent?.trim()
      )
    ).toHaveLength(0);
  });

  it("normalizes dangling MathJax delimiters so stray markers do not render in red", () => {
    render(
      <MessageContent
        content={String.raw`对应冲激强度可写为 \frac{3}{2}\(C_0 + C_1(-1)^n\)。
进一步可得 \frac{3}{2}$C_0 + C_1$ = 1。`}
      />
    );

    expectReadableMath(3);
    expect(document.body.textContent).not.toContain("\\(");
    expect(document.body.textContent).not.toContain("\\)");
    expect(screen.queryByText("\\(")).toBeNull();
  });

  it("normalizes the live malformed mixed-delimiter math sample without leaking raw markers", () => {
    const content = String.raw`利用泊松求和公式，可得：
x(t)=\frac{3}{2}\sum_{n=-\infty}^{\infty}(C_0+C_1(-1)^n)\delta(t-\frac{3n}{2}).
即 x(t) 是在 t=\frac{3n}{2} 处的冲激串，冲激强度为 \frac{3}{2}\\(C_0+C_1(-1)^n )。

对于 \int_{-0.5}^{0.5}x(t)dt，区间内只包含 t=0 处的冲激，得：
\frac{3}{2}$C_0+C_1$=1.

对于 \int_0^2x(t)dt，区间内包含 t=0 和 t=1.5 处的冲激，得：
\frac{3}{2}[$C_0+C_1$+$C_0-C_1$]=3C_0=2。`;

    const normalized = debugNormalizeMessageContent(content);

    expect(normalized.latexBackslashNormalizedContent).not.toContain("\\\\(");
    expect(normalized.mathJaxNormalizedContent).not.toContain("\\\\(");
    expect(normalized.remarkMathContent).not.toContain("\\\\(");
    expect(normalized.remarkMathContent).not.toContain("$C_0+C_1$");
    expect(normalized.remarkMathContent).not.toContain("$C_0-C_1$");
  });
});

import { Children, isValidElement, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Options as RemarkMathOptions } from "remark-math";
import remarkMath from "remark-math";

import mathJaxScriptUrl from "mathjax-full/es5/tex-svg.js?url";

type MessageContentProps = {
  content: string;
};

type MathJaxWindow = Window &
  typeof globalThis & {
    MathJax?: {
      loader?: {
        load?: string[];
        paths?: Record<string, string>;
      };
      options?: Record<string, unknown>;
      startup?: {
        promise?: Promise<unknown>;
        typeset?: boolean;
      };
      tex?: Record<string, unknown>;
      svg?: Record<string, unknown>;
      tex2svgPromise?: (tex: string, options?: { display?: boolean }) => Promise<HTMLElement>;
    };
    __bombMathJaxReady?: Promise<MathJaxWindow["MathJax"]>;
  };

const INLINE_LATEX_HINT = /\\[A-Za-z]+|[_^{}]|(?:[A-Za-z]+\([^)]*\))|(?:\d+\s*\/\s*\d+)/;
const PARENTHESIZED_MATH_PATTERN = /\(([^()\n]*(?:\([^()\n]*\)[^()\n]*)*)\)/g;
const MATHJAX_INLINE_PATTERN = /\\\(([\s\S]*?)\\\)/g;
const MATHJAX_BLOCK_PATTERN = /\\\[([\s\S]*?)\\\]/g;
const LATEX_ENV_START_PATTERN = /\\begin\{([a-zA-Z*]+)\}/;
const LATEX_ENV_END_PATTERN = /\\end\{([a-zA-Z*]+)\}/;
const CJK_PATTERN = /[\u3400-\u9FFF]/;
const STANDALONE_LATEX_ALLOWED_PATTERN = /^[A-Za-z0-9\\{}_^|&=+\-*/<>,.:()[\]\s]+$/;
const INLINE_BARE_LATEX_FRAGMENT_PATTERN =
  /((?:[A-Za-z][A-Za-z0-9_]*(?:\([^()\n]*\))?\s*=\s*)?(?:\\(?:boxed|frac|dfrac|sqrt|sum|prod|int|lim|delta|omega|pi|theta|alpha|beta|gamma|quad|qquad|Rightarrow|left|right|begin|end|text|tag|cdot|infty)[A-Za-z0-9\\{}_^|&=+\-*/<>,.:[\]()\s]*))/g;
const DOM_BARE_LATEX_FRAGMENT_PATTERN =
  /((?:[A-Za-z][A-Za-z0-9_]*(?:\([^()\n]*\))?\s*=\s*)?(?:\\(?:boxed|frac|dfrac|sqrt|sum|prod|int|lim|delta|omega|pi|theta|alpha|beta|gamma|quad|qquad|Rightarrow|left|right|begin|end|text|tag|cdot|infty)[^，。；！？\n]*))/g;
const BARE_LATEX_COMMAND_PATTERN =
  /\\(?:boxed|frac|dfrac|sqrt|sum|prod|int|lim|delta|omega|pi|theta|alpha|beta|gamma|quad|qquad|Rightarrow|left|right|begin|end|text|tag|cdot|infty)\b/;
const LINE_START_LATEX_PATTERN =
  /^\\(?:boxed|frac|dfrac|sqrt|sum|prod|int|lim|delta|omega|pi|theta|alpha|beta|gamma|quad|qquad|Rightarrow|left|right|begin|end|text|tag)\b/;
const BOXED_CASES_PATTERN = /\\boxed\{\s*([^{}]+?)=\s*\\begin\{cases\}/g;
const INLINE_MARKDOWN_HEADING_PATTERN = /^(.*?)(\s+#{2,6}\s+.+)$/u;
const HEADING_BODY_START_PATTERN = /\s+(将|由|得|令|设|取|求|代入|因此|所以|于是|并将|再将)\s*/u;
const ESCAPED_DOLLAR_LATEX_SPACING_PATTERN = /\\\$(?=\\(?:!|,|;|:|quad|qquad|left|right|bigl|bigr|Bigl|Bigr|big|Big))/g;
const EXISTING_MATH_SPAN_PATTERN = /(\$\$[\s\S]*?\$\$|\$[^$\n]+\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\])/g;
const TRIPLE_DOLLAR_BLOCK_PATTERN = /\${3}([\s\S]+?)\${3}/g;
const remarkMathOptions: RemarkMathOptions = { singleDollarTextMath: true };

function ensureMathJax() {
  if (typeof window === "undefined" || import.meta.env.MODE === "test") {
    return Promise.resolve(undefined);
  }

  const mathJaxWindow = window as MathJaxWindow;

  if (mathJaxWindow.MathJax?.tex2svgPromise) {
    return mathJaxWindow.MathJax.startup?.promise?.then(() => mathJaxWindow.MathJax) ?? Promise.resolve(mathJaxWindow.MathJax);
  }

  if (mathJaxWindow.__bombMathJaxReady) {
    return mathJaxWindow.__bombMathJaxReady;
  }

  mathJaxWindow.MathJax = {
    ...mathJaxWindow.MathJax,
    loader: {
      paths: {
        mathjax: "/assets",
        ...mathJaxWindow.MathJax?.loader?.paths
      },
      ...mathJaxWindow.MathJax?.loader
    },
    startup: {
      ...mathJaxWindow.MathJax?.startup,
      typeset: false
    },
    options: {
      enableMenu: false,
      ...mathJaxWindow.MathJax?.options
    },
    svg: {
      fontCache: "none",
      internalSpeechTitles: false,
      ...mathJaxWindow.MathJax?.svg
    },
    tex: {
      processEnvironments: true,
      processEscapes: true,
      processRefs: true,
      ...mathJaxWindow.MathJax?.tex
    }
  };

  mathJaxWindow.__bombMathJaxReady = new Promise((resolve, reject) => {
    const existingScript = document.querySelector<HTMLScriptElement>('script[data-bomb-mathjax="true"]');

    if (existingScript) {
      existingScript.addEventListener("load", () => resolve(mathJaxWindow.MathJax), { once: true });
      existingScript.addEventListener("error", reject, { once: true });
      return;
    }

    const script = document.createElement("script");
    script.async = true;
    script.dataset.bombMathjax = "true";
    script.id = "MathJax-script";
    script.src = mathJaxScriptUrl;
    script.addEventListener("load", () => {
      const startupPromise = mathJaxWindow.MathJax?.startup?.promise ?? Promise.resolve();
      startupPromise
        .then(() => {
          if (!mathJaxWindow.MathJax?.tex2svgPromise) {
            reject(new Error("MathJax loaded without tex2svgPromise"));
            return;
          }

          resolve(mathJaxWindow.MathJax);
        })
        .catch(reject);
    });
    script.addEventListener("error", reject);
    document.head.appendChild(script);
  });

  return mathJaxWindow.__bombMathJaxReady;
}

function nodeContainsMathError(node: HTMLElement) {
  if (
    node.matches(
      "[data-mml-node='merror'], mjx-merror, [data-mjx-error], [data-mml-node='mtext'][fill='red'][stroke='red']"
    )
  ) {
    return true;
  }

  return Boolean(
    node.querySelector(
      "[data-mml-node='merror'], mjx-merror, [data-mjx-error], [data-mml-node='mtext'][fill='red'][stroke='red']"
    )
  );
}

function MathFormula({ display, tex }: { display: boolean; tex: string }) {
  const containerRef = useRef<HTMLSpanElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const container = containerRef.current;

    if (!container) {
      return;
    }

    let cancelled = false;
    setFailed(false);
    container.textContent = "";

    if (import.meta.env.MODE === "test") {
      const testNode = document.createElement("mjx-container");
      testNode.setAttribute("jax", "SVG");
      testNode.setAttribute("data-bomb-math-preview", tex);

      if (display) {
        testNode.setAttribute("display", "true");
      }

      container.appendChild(testNode);
      return;
    }

    void ensureMathJax()
      .then((mathJax) => mathJax?.tex2svgPromise?.(tex, { display }))
      .then((node) => {
        if (cancelled || !container) {
          return;
        }

        if (!node) {
          setFailed(true);
          return;
        }

        if (nodeContainsMathError(node)) {
          setFailed(true);
          return;
        }

        container.replaceChildren(node);
      })
      .catch(() => {
        if (!cancelled) {
          setFailed(true);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [display, tex]);

  if (failed) {
    return <code className="bomb-shell__math-fallback">{tex}</code>;
  }

  return (
    <span
      className={display ? "bomb-shell__math bomb-shell__math--display" : "bomb-shell__math bomb-shell__math--inline"}
      ref={containerRef}
    />
  );
}

function getPlainText(children: React.ReactNode) {
  return Children.toArray(children).join("").replace(/\n$/, "");
}

function findDanglingInlineMathEnd(content: string, startIndex: number): number {
  let parenthesisDepth = 0;

  for (let index = startIndex; index < content.length; index += 1) {
    if (content.startsWith("\\)", index)) {
      return -1;
    }

    const character = content[index] ?? "";

    if (character === "\n") {
      return -1;
    }

    if (character === "(") {
      parenthesisDepth += 1;
      continue;
    }

    if (character !== ")") {
      continue;
    }

    if (parenthesisDepth > 0) {
      parenthesisDepth -= 1;
      continue;
    }

    const innerContent = content.slice(startIndex, index).trim();

    if (!innerContent || (!INLINE_LATEX_HINT.test(innerContent) && !BARE_LATEX_COMMAND_PATTERN.test(innerContent))) {
      return -1;
    }

    return index;
  }

  return -1;
}

function repairDanglingMathJaxInlineDelimiters(content: string): string {
  let normalizedContent = "";

  for (let index = 0; index < content.length; index += 1) {
    if (!content.startsWith("\\(", index)) {
      normalizedContent += content[index] ?? "";
      continue;
    }

    const closingIndex = findDanglingInlineMathEnd(content, index + 2);

    if (closingIndex === -1) {
      normalizedContent += "\\(";
      index += 1;
      continue;
    }

    const innerContent = content.slice(index + 2, closingIndex).trim();
    normalizedContent += `\\(${innerContent}\\)`;
    index = closingIndex;
  }

  return normalizedContent;
}

function normalizeEscapedLatexBackslashes(content: string): string {
  return content.replace(/\\\\(?=(?:[()[\]]|[A-Za-z]))/g, "\\");
}

function normalizeBracketMathBlocks(content: string): string {
  const lines = content.split("\n");
  const normalizedLines: string[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const currentLine = lines[index] ?? "";

    if (currentLine.trim() !== "\\[") {
      normalizedLines.push(currentLine);
      continue;
    }

    const blockLines: string[] = [];
    let cursor = index + 1;

    while (cursor < lines.length && (lines[cursor] ?? "").trim() !== "\\]") {
      blockLines.push(lines[cursor] ?? "");
      cursor += 1;
    }

    if (cursor >= lines.length || !blockLines.some((line) => line.trim())) {
      normalizedLines.push(currentLine);
      continue;
    }

    pushDisplayMathBlock(normalizedLines, blockLines.join("\n"));
    index = cursor;
  }

  return normalizedLines.join("\n");
}

function pushDisplayMathBlock(targetLines: string[], content: string) {
  if (targetLines.at(-1)?.trim()) {
    targetLines.push("");
  }

  targetLines.push("$$");
  targetLines.push(content.trim());
  targetLines.push("$$");

  if (targetLines.at(-1) === "$$") {
    targetLines.push("");
  }
}

function isStandaloneLatexLine(line: string): boolean {
  const trimmedLine = line.trim();

  if (!trimmedLine) {
    return false;
  }

  if (
    trimmedLine.startsWith("$$") ||
    trimmedLine.startsWith("\\(") ||
    trimmedLine.startsWith("\\[") ||
    trimmedLine.startsWith("```")
  ) {
    return false;
  }

  if (LINE_START_LATEX_PATTERN.test(trimmedLine)) {
    return true;
  }

  if (CJK_PATTERN.test(trimmedLine)) {
    return false;
  }

  if (!INLINE_LATEX_HINT.test(trimmedLine) && !trimmedLine.includes("=")) {
    return false;
  }

  return STANDALONE_LATEX_ALLOWED_PATTERN.test(trimmedLine);
}

function wrapBareLatexBlocks(content: string): string {
  const lines = content.split("\n");
  const normalizedLines: string[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const currentLine = lines[index] ?? "";

    if (currentLine.trim() === "$$") {
      normalizedLines.push(currentLine);
      index += 1;

      while (index < lines.length) {
        const mathLine = lines[index] ?? "";
        normalizedLines.push(mathLine);

        if (mathLine.trim() === "$$") {
          break;
        }

        index += 1;
      }

      continue;
    }

    const envMatch = currentLine.match(LATEX_ENV_START_PATTERN);

    if (envMatch) {
      const environmentName = envMatch[1];
      const blockLines = [currentLine];
      let cursor = index;

      while (cursor + 1 < lines.length && !(lines[cursor] ?? "").match(LATEX_ENV_END_PATTERN)) {
        cursor += 1;
        blockLines.push(lines[cursor] ?? "");

        if ((lines[cursor] ?? "").includes(`\\end{${environmentName}}`)) {
          break;
        }
      }

      pushDisplayMathBlock(normalizedLines, blockLines.join("\n"));
      index = cursor;
      continue;
    }

    if (isStandaloneLatexLine(currentLine)) {
      pushDisplayMathBlock(normalizedLines, sanitizeStandaloneLatexLine(currentLine));
      continue;
    }

    normalizedLines.push(currentLine);
  }

  return normalizedLines.join("\n");
}

function splitMarkdownHeadingAndBody(line: string): string[] {
  if (!line.trimStart().startsWith("#")) {
    return [line];
  }

  const bodyMatch = line.match(HEADING_BODY_START_PATTERN);

  if (!bodyMatch || bodyMatch.index === undefined) {
    return [line];
  }

  const heading = line.slice(0, bodyMatch.index).trimEnd();
  const body = line.slice(bodyMatch.index).trimStart();

  if (!heading || !body) {
    return [line];
  }

  return [heading, body];
}

function normalizeInlineMarkdownHeadings(content: string): string {
  const normalizedLines: string[] = [];

  for (const line of content.split("\n")) {
    const inlineHeadingMatch = line.match(INLINE_MARKDOWN_HEADING_PATTERN);

    if (inlineHeadingMatch && !line.trimStart().startsWith("#")) {
      const beforeHeading = inlineHeadingMatch[1]?.trimEnd() ?? "";
      const inlineHeading = inlineHeadingMatch[2]?.trimStart() ?? "";

      if (beforeHeading) {
        normalizedLines.push(beforeHeading);
      }

      if (normalizedLines.at(-1)?.trim()) {
        normalizedLines.push("");
      }

      normalizedLines.push(...splitMarkdownHeadingAndBody(inlineHeading));
      continue;
    }

    normalizedLines.push(...splitMarkdownHeadingAndBody(line));
  }

  return normalizedLines.join("\n");
}

function wrapBareInlineLatex(content: string): string {
  let insideDisplayMath = false;

  return content
    .split("\n")
    .map((line) => {
      if (line.trim() === "$$") {
        insideDisplayMath = !insideDisplayMath;
        return line;
      }

      if (insideDisplayMath) {
        return line;
      }

      if (!line.trim() || line.includes("```") || isStandaloneLatexLine(line)) {
        return line;
      }

      const protectedMathSpans: string[] = [];
      const protectedLine = line.replace(EXISTING_MATH_SPAN_PATTERN, (match) => {
        const placeholderIndex = protectedMathSpans.push(match) - 1;
        return `@@CODEX_EXISTING_MATH_${placeholderIndex}@@`;
      });

      const wrappedLine = protectedLine.replace(INLINE_BARE_LATEX_FRAGMENT_PATTERN, (match) => {
        const trimmedMatch = match.trim();

        if (!trimmedMatch.includes("\\")) {
          return match;
        }

        return `\\(${trimmedMatch}\\)`;
      });

      return wrappedLine.replace(
        /@@CODEX_EXISTING_MATH_(\d+)@@/g,
        (_, index) => protectedMathSpans[Number(index)] ?? ""
      );
    })
    .join("\n");
}

function sanitizeStandaloneLatexLine(line: string): string {
  return line
    .replace(MATHJAX_INLINE_PATTERN, (_match, inner) => `(${String(inner).trim()})`)
    .replace(/\$([^$\n]+)\$/g, (_match, inner) => `(${String(inner).trim()})`);
}

function normalizeParenthesizedMathInLine(content: string): string {
  let normalizedContent = content;

  for (let iteration = 0; iteration < 4; iteration += 1) {
    const replacements: string[] = [];
    const nextContent = normalizedContent.replace(PARENTHESIZED_MATH_PATTERN, (match, inner, offset, source) => {
      if (offset > 0 && source[offset - 1] === "\\") {
        return match;
      }

      if (offset > 0 && /[A-Za-z0-9_\\]/.test(source[offset - 1] ?? "")) {
        return match;
      }

      const normalizedInner = inner.trim();

      if (!normalizedInner) {
        return match;
      }

      if (normalizedInner.includes("$") || normalizedInner.includes("\\(") || normalizedInner.includes("\\[")) {
        return match;
      }

      if (!INLINE_LATEX_HINT.test(normalizedInner)) {
        return match;
      }

      const replacementIndex = replacements.push(`\\(${normalizedInner}\\)`) - 1;
      return `@@CODEX_MATH_${replacementIndex}@@`;
    });

    const restoredContent = nextContent.replace(/@@CODEX_MATH_(\d+)@@/g, (_, index) => replacements[Number(index)] ?? "");

    if (restoredContent === normalizedContent) {
      break;
    }

    normalizedContent = restoredContent;
  }

  return normalizedContent;
}

function normalizeToMathJax(content: string): string {
  return content
    .split("\n")
    .map((line) => {
      if (isStandaloneLatexLine(line) || /\\\(|\\\[|\$/.test(line)) {
        return line;
      }

      return normalizeParenthesizedMathInLine(line);
    })
    .join("\n");
}

function toRemarkMathContent(content: string): string {
  return normalizeBracketMathBlocks(content)
    .replace(ESCAPED_DOLLAR_LATEX_SPACING_PATTERN, "")
    .replace(TRIPLE_DOLLAR_BLOCK_PATTERN, (_match, inner) => `$$${String(inner).trim()}$$`)
    .replace(/\\\$(.+?)\$/g, (_, inner) => `$${String(inner).trim()}$`)
    .replace(BOXED_CASES_PATTERN, (_match, leftHandSide) => `\\boxed{\\displaystyle ${leftHandSide.trim()} = \\begin{cases}`)
    .replace(MATHJAX_BLOCK_PATTERN, (_, inner) => `\n\n$$\n${inner.trim()}\n$$\n\n`)
    .replace(MATHJAX_INLINE_PATTERN, (_, inner) => ` $${inner.trim()}$ `);
}

export function debugNormalizeMessageContent(content: string): {
  latexBackslashNormalizedContent: string;
  mathJaxNormalizedContent: string;
  remarkMathContent: string;
} {
  const latexBackslashNormalizedContent = repairDanglingMathJaxInlineDelimiters(
    normalizeBracketMathBlocks(normalizeEscapedLatexBackslashes(content))
  );
  const mathJaxNormalizedContent = wrapBareInlineLatex(
    wrapBareLatexBlocks(normalizeInlineMarkdownHeadings(normalizeToMathJax(latexBackslashNormalizedContent)))
  );

  return {
    latexBackslashNormalizedContent,
    mathJaxNormalizedContent,
    remarkMathContent: toRemarkMathContent(mathJaxNormalizedContent)
  };
}

export function MessageContent({ content }: MessageContentProps) {
  const { remarkMathContent } = debugNormalizeMessageContent(content);

  return (
    <div className="bomb-shell__markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, [remarkMath, remarkMathOptions]]}
        components={{
          code: ({ children, className }) => {
            const isMath = className?.split(" ").some((name) => name === "language-math" || name === "math-inline");

            if (isMath) {
              return <MathFormula display={false} tex={getPlainText(children)} />;
            }

            return <code className={className}>{children}</code>;
          },
          p: ({ children }) => <p>{children}</p>,
          table: ({ children }) => (
            <div className="bomb-shell__table-wrap">
              <table className="bomb-shell__table">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead>{children}</thead>,
          tbody: ({ children }) => <tbody>{children}</tbody>,
          th: ({ children }) => <th>{children}</th>,
          td: ({ children }) => <td>{children}</td>,
          pre: ({ children }) => {
            const onlyChild = Children.toArray(children)[0];

            if (
              isValidElement<{ children?: React.ReactNode; className?: string }>(onlyChild) &&
              onlyChild.type === "code" &&
              onlyChild.props.className?.split(" ").includes("language-math")
            ) {
              return <MathFormula display tex={getPlainText(onlyChild.props.children)} />;
            }

            return <pre className="bomb-shell__code-block">{children}</pre>;
          }
        }}
      >
        {remarkMathContent}
      </ReactMarkdown>
    </div>
  );
}

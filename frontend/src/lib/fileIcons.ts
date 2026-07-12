import { defaultIcon, getIcon, type Icon } from "material-file-icons";

const EXTENSION_BY_TYPE: Record<string, string> = {
  archive: "zip",
  audio: "mp3",
  c: "c",
  csv: "csv",
  "c++": "cpp",
  css: "css",
  database: "sqlite",
  doc: "doc",
  docx: "docx",
  evtx: "log",
  exe: "exe",
  gif: "gif",
  html: "html",
  image: "png",
  java: "java",
  javascript: "js",
  jpeg: "jpeg",
  jpg: "jpg",
  js: "js",
  json: "json",
  log: "log",
  markdown: "md",
  pdf: "pdf",
  pcap: "pcap",
  png: "png",
  ppt: "ppt",
  pptx: "pptx",
  python: "py",
  py: "py",
  sql: "sql",
  text: "txt",
  typescript: "ts",
  txt: "txt",
  video: "mp4",
  webp: "webp",
  xls: "xls",
  xlsx: "xlsx",
  xml: "xml",
  yaml: "yaml",
  yml: "yml",
  zip: "zip"
};

export type FileIconAsset = Pick<Icon, "name" | "svg">;

function normalizeExtension(name: string): string | null {
  const match = /\.([^.]+)$/.exec(name.trim().toLowerCase());
  return match?.[1] ?? null;
}

function normalizeType(type: string): string | null {
  const normalized = type.trim().toLowerCase();
  return normalized || null;
}

function resolveLookupFilename(name: string, type: string): string {
  const normalizedName = name.trim();

  if (normalizeExtension(normalizedName)) {
    return normalizedName;
  }

  const fallbackExtension = normalizeType(type)
    ? EXTENSION_BY_TYPE[normalizeType(type) as string]
    : null;

  if (fallbackExtension) {
    return `${normalizedName || "attachment"}.${fallbackExtension}`;
  }

  return normalizedName || "attachment";
}

export function getFileIconAsset(name: string, type: string): FileIconAsset {
  const icon = getIcon(resolveLookupFilename(name, type)) ?? defaultIcon;

  return {
    name: icon.name,
    svg: icon.svg
  };
}

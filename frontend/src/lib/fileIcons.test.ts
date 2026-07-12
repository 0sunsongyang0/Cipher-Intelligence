import { describe, expect, it } from "vitest";

import { getFileIconAsset } from "./fileIcons";

describe("getFileIconAsset", () => {
  it("maps common office and archive files to material-style file icons", () => {
    expect(getFileIconAsset("report.pdf", "PDF").name).toBe("pdf");
    expect(getFileIconAsset("brief.docx", "DOCX").name).toBe("word");
    expect(getFileIconAsset("archive.zip", "ZIP").name).toBe("zip");
  });

  it("falls back to the generic file icon for unknown formats", () => {
    expect(getFileIconAsset("mystery.custom", "CUSTOM").name).toBe("file");
  });

  it("uses attachment type metadata when the uploaded name has no extension", () => {
    expect(getFileIconAsset("evidence-upload", "DOCX").name).toBe("word");
  });

  it("maps richer attachment type labels to distinct fallback icons", () => {
    expect(getFileIconAsset("readme-upload", "Markdown").name).toBe("markdown");
    expect(getFileIconAsset("spreadsheet-upload", "CSV").name).toBe("table");
    expect(getFileIconAsset("script-upload", "JavaScript").name).toBe("javascript");
    expect(getFileIconAsset("capture-upload", "Video").name).toBe("video");
    expect(getFileIconAsset("archive-upload", "Archive").name).toBe("zip");
    expect(getFileIconAsset("forensics-upload", "Database").name).toBe("database");
    expect(getFileIconAsset("events-upload", "LOG").name).toBe("log");
    expect(getFileIconAsset("photo-upload", "Image").name).toBe("image");
  });
});

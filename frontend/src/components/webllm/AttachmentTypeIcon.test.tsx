import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AttachmentTypeIcon } from "./AttachmentTypeIcon";

describe("AttachmentTypeIcon", () => {
  it("renders the file icon svg directly without a glass chrome wrapper", () => {
    render(<AttachmentTypeIcon className="bomb-shell__attachment-icon" name="brief.docx" type="DOCX" />);

    const icon = document.querySelector(".bomb-shell__attachment-icon");
    expect(icon).not.toBeNull();
    expect(icon).toHaveAttribute("data-file-icon", "word");
    expect(icon?.querySelector(".bomb-shell__attachment-icon-chrome")).toBeNull();
    expect(icon?.querySelector("svg")).not.toBeNull();
  });

  it("keeps the icon presentation hidden from assistive technology", () => {
    render(<AttachmentTypeIcon className="bomb-shell__attachment-icon" name="archive.zip" type="ZIP" />);

    expect(document.querySelector(".bomb-shell__attachment-icon")).toHaveAttribute("aria-hidden", "true");
  });
});

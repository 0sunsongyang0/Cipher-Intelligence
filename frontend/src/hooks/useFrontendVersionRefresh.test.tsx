import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useFrontendVersionRefresh } from "./useFrontendVersionRefresh";

function setCurrentEntryScript(src: string) {
  document.head.innerHTML = `<script type="module" src="${src}"></script>`;
}

describe("useFrontendVersionRefresh", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.head.innerHTML = "";
  });

  it("reloads the page when the server returns a newer frontend entry script", async () => {
    setCurrentEntryScript("/assets/main-old.js");

    const reloadSpy = vi.fn();
    const fetchSpy = vi.spyOn(window, "fetch").mockResolvedValue(
      new Response('<script type="module" src="/assets/main-new.js"></script>', {
        status: 200,
        headers: {
          "Content-Type": "text/html"
        }
      })
    );

    renderHook(() => useFrontendVersionRefresh({ enabled: true, intervalMs: 60000, reload: reloadSpy }));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(reloadSpy).toHaveBeenCalledTimes(1);
    });
  });

  it("keeps the current page when the frontend entry script has not changed", async () => {
    setCurrentEntryScript("/assets/main-stable.js");

    const reloadSpy = vi.fn();
    const fetchSpy = vi.spyOn(window, "fetch").mockResolvedValue(
      new Response('<script type="module" src="/assets/main-stable.js"></script>', {
        status: 200,
        headers: {
          "Content-Type": "text/html"
        }
      })
    );

    renderHook(() => useFrontendVersionRefresh({ enabled: true, intervalMs: 60000, reload: reloadSpy }));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });
    expect(reloadSpy).not.toHaveBeenCalled();
  });
});

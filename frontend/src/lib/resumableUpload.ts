export type UploadProgress = { status: "hashing" | "uploading" | "ready" | "failed"; progress: number; uploadId?: string; deduplicated?: boolean; error?: string };

const CHUNK_SIZE = 2 * 1024 * 1024;
const MAX_RETRIES = 3;

async function readError(response: Response): Promise<string> {
  try {
    const payload = await response.json() as { detail?: string | { message?: string; expectedOffset?: number } };
    return typeof payload.detail === "string" ? payload.detail : payload.detail?.message ?? `上传失败 (${response.status})`;
  } catch {
    return `上传失败 (${response.status})`;
  }
}

async function sha256(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function retry<T>(operation: () => Promise<T>): Promise<T> {
  let lastError: unknown;
  for (let attempt = 0; attempt < MAX_RETRIES; attempt += 1) {
    try { return await operation(); } catch (error) {
      lastError = error;
      if (attempt + 1 < MAX_RETRIES) await new Promise((resolve) => window.setTimeout(resolve, 400 * (2 ** attempt)));
    }
  }
  throw lastError;
}

export async function uploadFileResumably(file: File, onProgress: (progress: UploadProgress) => void): Promise<UploadProgress> {
  try {
    onProgress({ status: "hashing", progress: 2 });
    const hash = await sha256(file);
    onProgress({ status: "hashing", progress: 8 });
    const startResponse = await retry(() => fetch("/api/uploads", {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: file.name, size: file.size, sha256: hash, mimeType: file.type || "application/octet-stream" })
    }));
    if (!startResponse.ok) throw new Error(await readError(startResponse));
    let session = await startResponse.json() as { uploadId: string; received: number; complete: boolean; deduplicated: boolean };
    if (session.complete) {
      const result = { status: "ready", progress: 100, uploadId: session.uploadId, deduplicated: session.deduplicated } as const;
      onProgress(result); return result;
    }
    let offset = session.received;
    while (offset < file.size) {
      const chunk = file.slice(offset, Math.min(offset + CHUNK_SIZE, file.size));
      const response = await retry(() => fetch(`/api/uploads/${session.uploadId}/chunks?offset=${offset}`, {
        method: "PUT", credentials: "include", headers: { "Content-Type": "application/octet-stream" }, body: chunk
      }));
      if (response.status === 409) {
        const statusResponse = await fetch(`/api/uploads/${session.uploadId}`, { credentials: "include" });
        if (!statusResponse.ok) throw new Error(await readError(statusResponse));
        session = await statusResponse.json(); offset = session.received; continue;
      }
      if (!response.ok) throw new Error(await readError(response));
      session = await response.json(); offset = session.received;
      onProgress({ status: "uploading", progress: Math.max(9, Math.round(offset / file.size * 100)), uploadId: session.uploadId });
    }
    const result = { status: "ready", progress: 100, uploadId: session.uploadId } as const;
    onProgress(result); return result;
  } catch (error) {
    const result = { status: "failed", progress: 0, error: error instanceof Error ? error.message : "上传失败，请重试。" } as const;
    onProgress(result); return result;
  }
}

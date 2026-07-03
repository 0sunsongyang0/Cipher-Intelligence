async function readErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string };
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return payload.detail;
    }
  } catch {
    return "\u8bf7\u6c42\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002";
  }

  return "\u8bf7\u6c42\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002";
}

export async function streamChat(
  conversationId: number,
  content: string,
  onChunk: (chunk: string) => void
): Promise<string> {
  const response = await fetch("/api/chat", {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      conversation_id: conversationId,
      content
    })
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  if (response.body === null) {
    throw new Error("\u54cd\u5e94\u6d41\u4e0d\u53ef\u7528\u3002");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let output = "";

  while (true) {
    const { done, value } = await reader.read();

    if (done) {
      break;
    }

    const chunk = decoder.decode(value, { stream: true });
    if (!chunk) {
      continue;
    }

    output += chunk;
    onChunk(chunk);
  }

  const finalChunk = decoder.decode();
  if (finalChunk) {
    output += finalChunk;
    onChunk(finalChunk);
  }

  return output;
}
const http = require("node:http");
const path = require("node:path");
const { readFile } = require("node:fs/promises");

const { app, BrowserWindow } = require("electron");

const isDev = Boolean(process.env.VITE_DEV_SERVER_URL);
const backendOrigin = process.env.CIPHER_BACKEND_URL || "http://127.0.0.1:8000";
const distDir = path.join(__dirname, "..", "dist");
const mainHtml = path.join(distDir, "index.html");
const adminHtml = path.join(distDir, "admin.html");

let localServer = null;
let mainWindow = null;

function contentType(filePath) {
  switch (path.extname(filePath).toLowerCase()) {
    case ".html":
      return "text/html; charset=utf-8";
    case ".js":
      return "text/javascript; charset=utf-8";
    case ".css":
      return "text/css; charset=utf-8";
    case ".json":
      return "application/json; charset=utf-8";
    case ".svg":
      return "image/svg+xml";
    case ".png":
      return "image/png";
    case ".jpg":
    case ".jpeg":
      return "image/jpeg";
    case ".woff":
      return "font/woff";
    case ".woff2":
      return "font/woff2";
    default:
      return "application/octet-stream";
  }
}

function isStaticAsset(pathname) {
  return /\.[a-z0-9]+$/i.test(pathname);
}

async function readTextFile(filePath) {
  return readFile(filePath, "utf8");
}

async function readBinaryFile(filePath) {
  return readFile(filePath);
}

async function proxyToBackend(request) {
  const backendUrl = new URL(request.url);
  const upstreamBase = new URL(backendOrigin);
  backendUrl.protocol = upstreamBase.protocol;
  backendUrl.hostname = upstreamBase.hostname;
  backendUrl.port = upstreamBase.port;
  backendUrl.username = upstreamBase.username;
  backendUrl.password = upstreamBase.password;

  const headers = new Headers();
  for (const [name, value] of request.headers.entries()) {
    if (!["host", "content-length"].includes(name.toLowerCase())) {
      headers.set(name, value);
    }
  }

  const init = {
    method: request.method,
    headers
  };

  if (!["GET", "HEAD"].includes(request.method)) {
    init.body = Buffer.from(await request.arrayBuffer());
  }

  const upstreamResponse = await fetch(backendUrl, init);
  return new Response(upstreamResponse.body, {
    status: upstreamResponse.status,
    statusText: upstreamResponse.statusText,
    headers: upstreamResponse.headers
  });
}

async function serveFile(filePath) {
  const body = filePath.endsWith(".html") ? await readTextFile(filePath) : await readBinaryFile(filePath);
  return new Response(body, {
    headers: {
      "Content-Type": contentType(filePath),
      "Cache-Control": "no-cache"
    }
  });
}

async function handleRequest(request) {
  const url = new URL(request.url);

  if (url.pathname.startsWith("/api/")) {
    return proxyToBackend(request);
  }

  if (url.pathname === "/admin" || url.pathname.startsWith("/admin/")) {
    const adminPath = url.pathname === "/admin" ? "/admin.html" : url.pathname;
    if (isStaticAsset(adminPath)) {
      return serveFile(path.join(distDir, adminPath.replace(/^\//, "")));
    }
    return serveFile(adminHtml);
  }

  const pathname = url.pathname === "/" ? "/index.html" : url.pathname;
  if (pathname === "/index.html") {
    return serveFile(mainHtml);
  }

  if (isStaticAsset(pathname)) {
    return serveFile(path.join(distDir, pathname.replace(/^\//, "")));
  }

  return serveFile(mainHtml);
}

async function startLocalServer() {
  if (localServer) {
    return localServer;
  }

  localServer = http.createServer(async (req, res) => {
    const requestUrl = new URL(req.url || "/", "http://cipher.local");
    const chunks = [];

    for await (const chunk of req) {
      chunks.push(chunk);
    }

    const method = req.method || "GET";
    const request = new Request(requestUrl, {
      method,
      headers: req.headers,
      body: chunks.length > 0 && !["GET", "HEAD"].includes(method) ? Buffer.concat(chunks) : undefined
    });

    try {
      const response = await handleRequest(request);
      res.statusCode = response.status;
      res.statusMessage = response.statusText;

      response.headers.forEach((value, key) => {
        if (key.toLowerCase() !== "transfer-encoding") {
          res.setHeader(key, value);
        }
      });

      if (response.body === null) {
        res.end();
        return;
      }

      const reader = response.body.getReader();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }
        res.write(Buffer.from(value));
      }
      res.end();
    } catch (error) {
      res.statusCode = 500;
      res.setHeader("Content-Type", "text/plain; charset=utf-8");
      res.end(error instanceof Error ? error.message : "Unexpected desktop server error");
    }
  });

  await new Promise((resolve) => {
    localServer.listen(0, "127.0.0.1", resolve);
  });

  const address = localServer.address();
  const port = typeof address === "object" && address ? address.port : 0;
  return `http://127.0.0.1:${port}`;
}

function createWindow(entryUrl) {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 1200,
    minHeight: 780,
    backgroundColor: "#0b0f14",
    title: "Cipher",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  void mainWindow.loadURL(entryUrl);
}

async function boot() {
  await app.whenReady();
  app.setAppUserModelId("com.cipher.desktop");

  if (isDev) {
    createWindow(process.env.VITE_DEV_SERVER_URL);
    return;
  }

  const serverOrigin = await startLocalServer();
  const entryPath = process.argv.includes("--admin") ? "/admin/" : "/index.html";
  createWindow(`${serverOrigin}${entryPath}`);
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    void boot();
  }
});

void boot();

import { readFileSync } from "node:fs";
import { loadConfig, getApiKey, getServerUrl } from "./config.js";

let _apiKey: string | undefined;
let _serverUrl: string | undefined;

export async function init(): Promise<{ apiKey: string; serverUrl: string }> {
  const config = await loadConfig();
  _apiKey = getApiKey(config);
  _serverUrl = getServerUrl(config);

  if (!_apiKey) {
    throw new Error("Not authenticated. Run: rem login");
  }

  return { apiKey: _apiKey, serverUrl: _serverUrl };
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  if (!_apiKey || !_serverUrl) await init();

  const res = await fetch(`${_serverUrl}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": _apiKey!,
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const text = await res.text();
    if (res.status === 401) throw new Error("Invalid or expired API key. Run: rem login");
    if (res.status === 403) throw new Error("Access denied: " + text);
    throw new Error(`Server error ${res.status}: ${text}`);
  }

  return res.json() as Promise<T>;
}

export async function apiGet<T>(path: string, params?: Record<string, string>): Promise<T> {
  if (!_apiKey || !_serverUrl) await init();

  const url = new URL(`${_serverUrl}${path}`);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      url.searchParams.set(k, v);
    }
  }

  const res = await fetch(url.toString(), {
    headers: { "X-API-Key": _apiKey! },
  });

  if (!res.ok) {
    const text = await res.text();
    if (res.status === 401) throw new Error("Invalid or expired API key. Run: rem login");
    if (res.status === 403) throw new Error("Access denied: " + text);
    throw new Error(`Server error ${res.status}: ${text}`);
  }

  return res.json() as Promise<T>;
}

export async function getUploadUrl(): Promise<string> {
  if (!_apiKey || !_serverUrl) await init();

  const res = await fetch(`${_serverUrl}/scans/upload-url`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": _apiKey!,
    },
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Failed to get upload URL: ${text}`);
  }

  const data = (await res.json()) as { upload_url: string };
  return data.upload_url;
}

export async function uploadTarball(tarballPath: string): Promise<string> {
  const uploadUrl = await getUploadUrl();
  const tarballBytes = readFileSync(tarballPath);

  const res = await fetch(uploadUrl, {
    method: "POST",
    headers: { "Content-Type": "application/gzip" },
    body: tarballBytes,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Failed to upload tarball: ${text}`);
  }

  const text = await res.text();
  try {
    const data = JSON.parse(text);
    if (typeof data === "object" && data.storageId) return data.storageId;
    return String(data);
  } catch {
    return text.trim().replace(/^"|"$/g, "");
  }
}

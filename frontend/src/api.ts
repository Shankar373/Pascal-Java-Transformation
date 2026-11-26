import { ID_RE } from "./constants";
import type { Accepted, AppConfig, CreateRequest, DiscoveryList, JobView } from "./types";

const API_BASE = "/api/discoveries";
const GUARD_HEADER = "X-P1-Request";

export const AUTH_MESSAGE = "Access token missing or invalid. Enter a valid token (UNAUTHENTICATED).";

/** Raised on HTTP 401: the in-memory token has already been cleared. */
export class AuthError extends Error {
  constructor(message: string = AUTH_MESSAGE) {
    super(message);
    this.name = "AuthError";
  }
}

// The bearer token lives only in this module variable: never in storage, cookies or the URL.
let token: string | null = null;
const listeners = new Set<(value: string | null) => void>();

export function setToken(value: string | null): void {
  const next = value && value.trim() ? value.trim() : null;
  token = next;
  listeners.forEach((fn) => fn(next));
}

export function subscribeToken(fn: (value: string | null) => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

/** True only for the discovery collection, upload endpoint, or a well-formed discovery id path. */
function isDiscoveryPath(path: string): boolean {
  if (!path.startsWith(API_BASE)) return false;
  const rest = path.slice(API_BASE.length);
  if (rest === "" || rest.startsWith("?")) return true;
  if (!rest.startsWith("/")) return false;
  const first = rest.slice(1).split(/[/?]/)[0] ?? "";
  return first === "upload" || ID_RE.test(first);
}

/** The token to send for this path, captured at send time (never attached to foreign paths). */
function tokenFor(path: string): string | null {
  return token !== null && isDiscoveryPath(path) ? token : null;
}

function bearer(sent: string | null): Record<string, string> {
  return sent === null ? {} : { Authorization: `Bearer ${sent}` };
}

/** Clears the stored token only if it is still the one that was rejected. */
function rejectUnauthorized(sent: string | null): never {
  if (sent !== null && token === sent) setToken(null);
  throw new AuthError();
}

interface ErrorEnvelope {
  error?: { code?: string; message?: string };
}

function messageFrom(data: unknown, fallback: string): string {
  const err = (data as ErrorEnvelope | null)?.error;
  return err && err.message ? `${err.message} (${err.code ?? "error"})` : fallback;
}

async function request<T>(path: string, method: "GET" | "POST", json?: CreateRequest): Promise<T> {
  const sent = tokenFor(path);
  const headers: Record<string, string> = { ...bearer(sent) };
  if (method === "POST") headers[GUARD_HEADER] = "1";
  const init: RequestInit = { method, headers, credentials: "same-origin" };
  if (json) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(json);
  }
  let resp: Response;
  try {
    resp = await fetch(path, init);
  } catch {
    throw new Error("Cannot reach the server.");
  }
  let data: unknown = null;
  try {
    data = await resp.json();
  } catch {
    data = null;
  }
  if (resp.status === 401) rejectUnauthorized(sent);
  if (!resp.ok) throw new Error(messageFrom(data, `Request failed (${resp.status}).`));
  return data as T;
}

export function getConfig(): Promise<AppConfig> {
  return request<AppConfig>("/api/config", "GET");
}

export function listDiscoveries(): Promise<DiscoveryList> {
  return request<DiscoveryList>(API_BASE, "GET");
}

export function getDiscovery(id: string): Promise<JobView> {
  return request<JobView>(`${API_BASE}/${id}`, "GET");
}

export function createDiscovery(body: CreateRequest): Promise<Accepted> {
  return request<Accepted>(API_BASE, "POST", body);
}

export function uploadZip(file: File, onProgress: (fraction: number) => void): Promise<Accepted> {
  return new Promise<Accepted>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/upload?name=${encodeURIComponent(file.name)}`);
    xhr.setRequestHeader(GUARD_HEADER, "1");
    xhr.setRequestHeader("Content-Type", "application/zip");
    const sent = tokenFor(API_BASE);
    if (sent !== null) xhr.setRequestHeader("Authorization", `Bearer ${sent}`);
    xhr.upload.onprogress = (ev: ProgressEvent) => {
      if (ev.lengthComputable) onProgress(ev.loaded / ev.total);
    };
    xhr.onerror = () => reject(new Error("Upload failed: cannot reach the server."));
    xhr.onload = () => {
      let data: (Partial<Accepted> & ErrorEnvelope) | null = null;
      try {
        data = JSON.parse(xhr.responseText) as Partial<Accepted> & ErrorEnvelope;
      } catch {
        data = null;
      }
      if (xhr.status === 401) {
        if (sent !== null && token === sent) setToken(null);
        reject(new AuthError());
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300 && data && data.id) {
        resolve({ id: data.id });
      } else {
        reject(new Error(messageFrom(data, `Upload failed (${xhr.status}).`)));
      }
    };
    xhr.send(file);
  });
}

const REVOKE_DOWNLOAD_MS = 1000;
const REVOKE_OPEN_MS = 60000;

/** Extracts a safe filename from a Content-Disposition header, or returns the fallback. */
export function filenameFrom(disposition: string | null, fallback: string): string {
  const star = disposition?.match(/filename\*=UTF-8''([^;]+)/i);
  const plain = disposition?.match(/filename="?([^";]+)"?/i);
  let raw = plain?.[1] ?? "";
  if (star?.[1]) {
    try {
      raw = decodeURIComponent(star[1]);
    } catch {
      raw = star[1];
    }
  }
  const base = raw.split(/[\\/]/).filter(Boolean).pop() ?? "";
  const clean = base
    .replace(/[\u0000-\u001f\u007f]/g, "")
    .replace(/\.{2,}/g, ".")
    .replace(/^\.+/, "")
    .trim();
  return clean || fallback;
}

interface Fetched {
  blob: Blob;
  disposition: string | null;
}

async function fetchBlob(url: string): Promise<Fetched> {
  const sent = tokenFor(url);
  let resp: Response;
  try {
    resp = await fetch(url, { method: "GET", headers: bearer(sent), credentials: "same-origin" });
  } catch {
    throw new Error("Cannot reach the server.");
  }
  if (resp.status === 401) rejectUnauthorized(sent);
  if (!resp.ok) {
    let data: unknown = null;
    try {
      data = await resp.json();
    } catch {
      data = null;
    }
    throw new Error(messageFrom(data, `Download failed (${resp.status}).`));
  }
  return { blob: await resp.blob(), disposition: resp.headers.get("Content-Disposition") };
}

function objectUrlFor(blob: Blob, revokeAfterMs: number): string {
  const objectUrl = URL.createObjectURL(blob);
  setTimeout(() => URL.revokeObjectURL(objectUrl), revokeAfterMs);
  return objectUrl;
}

function clickAnchor(href: string, name: string, newTab: boolean): void {
  const anchor = document.createElement("a");
  anchor.href = href;
  if (newTab) {
    anchor.target = "_blank";
    anchor.rel = "noopener";
  } else {
    anchor.download = name;
  }
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

/**
 * Fetches an artifact with the Authorization header and hands the bytes to the browser as a Blob:
 * saved under the server's filename, or opened in a new tab when `open` is true.
 */
export async function downloadArtifact(url: string, fallbackName: string, open: boolean): Promise<void> {
  const { blob, disposition } = await fetchBlob(url);
  const name = filenameFrom(disposition, fallbackName);
  clickAnchor(objectUrlFor(blob, open ? REVOKE_OPEN_MS : REVOKE_DOWNLOAD_MS), name, open);
}

/**
 * Opens the report in a new tab. The tab is opened synchronously (inside the user's click) so popup
 * blockers allow it; it is then pointed at the fetched Blob. If the popup is blocked, the report is
 * saved as a download instead.
 */
export async function openReport(url: string, fallbackName: string): Promise<void> {
  const win = window.open("", "_blank");
  if (win) win.opener = null;
  try {
    const { blob, disposition } = await fetchBlob(url);
    if (win) {
      win.location.href = objectUrlFor(blob, REVOKE_OPEN_MS);
    } else {
      clickAnchor(objectUrlFor(blob, REVOKE_DOWNLOAD_MS), filenameFrom(disposition, fallbackName), false);
    }
  } catch (err: unknown) {
    win?.close();
    throw err;
  }
}

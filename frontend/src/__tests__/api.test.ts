import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createDiscovery, getConfig, getDiscovery, listDiscoveries, uploadZip } from "../api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("api requests", () => {
  const fetchMock = vi.fn();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("GETs relative URLs without the guard header", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ local_directory_enabled: true }));
    await getConfig();
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/config");
    expect(init.method).toBe("GET");
    expect(init.headers).not.toHaveProperty("X-P1-Request");
    expect(init.credentials).toBe("same-origin");
  });

  it("POSTs JSON with the X-P1-Request header", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: "0123456789abcdef" }, 202));
    const out = await createDiscovery({ kind: "git", url: "https://x/y.git", ref: null });
    expect(out.id).toBe("0123456789abcdef");
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/discoveries");
    expect(init.headers).toMatchObject({ "X-P1-Request": "1", "Content-Type": "application/json" });
    expect(JSON.parse(String(init.body))).toEqual({ kind: "git", url: "https://x/y.git", ref: null });
  });

  it("fetches list and single discoveries", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [] }));
    await listDiscoveries();
    await getDiscovery("abc");
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual(["/api/discoveries", "/api/discoveries/abc"]);
  });

  it("maps server error envelopes to messages", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: { code: "bad_url", message: "URL rejected" } }, 400));
    await expect(createDiscovery({ kind: "directory", path: "/x" })).rejects.toThrow("URL rejected (bad_url)");
  });

  it("falls back to the status code when the body is not JSON", async () => {
    fetchMock.mockResolvedValue(new Response("<html>", { status: 502 }));
    await expect(getConfig()).rejects.toThrow("Request failed (502).");
  });

  it("reports network failures", async () => {
    fetchMock.mockRejectedValue(new TypeError("fail"));
    await expect(getConfig()).rejects.toThrow("Cannot reach the server.");
  });
});

class FakeXhr {
  static last: FakeXhr;
  status = 0;
  responseText = "";
  headers: Record<string, string> = {};
  method = "";
  url = "";
  body: unknown = null;
  upload: { onprogress: ((ev: ProgressEvent) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() { FakeXhr.last = this; }
  open(method: string, url: string): void { this.method = method; this.url = url; }
  setRequestHeader(k: string, v: string): void { this.headers[k] = v; }
  send(body: unknown): void { this.body = body; }
}

describe("uploadZip", () => {
  beforeEach(() => vi.stubGlobal("XMLHttpRequest", FakeXhr));
  afterEach(() => vi.unstubAllGlobals());

  const file = new File(["zip"], "my app.zip");

  it("sends the archive with the guard header and reports progress", async () => {
    const seen: number[] = [];
    const pending = uploadZip(file, (f) => seen.push(f));
    const xhr = FakeXhr.last;
    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe("/api/discoveries/upload?name=my%20app.zip");
    expect(xhr.headers).toEqual({ "X-P1-Request": "1", "Content-Type": "application/zip" });
    expect(xhr.body).toBe(file);
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 4 } as ProgressEvent);
    xhr.upload.onprogress?.({ lengthComputable: false, loaded: 1, total: 0 } as ProgressEvent);
    xhr.status = 202;
    xhr.responseText = JSON.stringify({ id: "0123456789abcdef" });
    xhr.onload?.();
    await expect(pending).resolves.toEqual({ id: "0123456789abcdef" });
    expect(seen).toEqual([0.25]);
  });

  it("maps error envelopes, bad bodies and network errors", async () => {
    const a = uploadZip(file, () => undefined);
    FakeXhr.last.status = 413;
    FakeXhr.last.responseText = JSON.stringify({ error: { code: "too_big", message: "Too large" } });
    FakeXhr.last.onload?.();
    await expect(a).rejects.toThrow("Too large (too_big)");

    const b = uploadZip(file, () => undefined);
    FakeXhr.last.status = 500;
    FakeXhr.last.responseText = "nope";
    FakeXhr.last.onload?.();
    await expect(b).rejects.toThrow("Upload failed (500).");

    const c = uploadZip(file, () => undefined);
    FakeXhr.last.onerror?.();
    await expect(c).rejects.toThrow("Upload failed: cannot reach the server.");
  });
});

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import {
  AuthError, createDiscovery, downloadArtifact, filenameFrom, getConfig, getDiscovery,
  listDiscoveries, setToken, uploadZip,
} from "../api";
import { BlueprintView } from "../components/Blueprint";
import { JOB_ID, makeJob } from "./fixture";

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const UNAUTH = { error: { code: "UNAUTHENTICATED", message: "no token" } };

function headersOf(call: unknown[]): Record<string, string> {
  return ((call[1] as RequestInit).headers ?? {}) as Record<string, string>;
}

describe("bearer token on requests", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation(() => Promise.resolve(json({ id: JOB_ID, items: [] })));
  });
  afterEach(() => {
    setToken(null);
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("sends no Authorization header without a token", async () => {
    await listDiscoveries();
    await createDiscovery({ kind: "directory", path: "/x" });
    for (const call of fetchMock.mock.calls) expect(headersOf(call)).not.toHaveProperty("Authorization");
  });

  it("sends Bearer on GET and POST discoveries, but not on /api/config", async () => {
    setToken("  s3cret ");
    await getConfig();
    await listDiscoveries();
    await getDiscovery(JOB_ID);
    await createDiscovery({ kind: "directory", path: "/x" });
    const [config, ...rest] = fetchMock.mock.calls;
    expect(headersOf(config as unknown[])).not.toHaveProperty("Authorization");
    for (const call of rest) expect(headersOf(call)).toMatchObject({ Authorization: "Bearer s3cret" });
    expect(headersOf(rest[2] as unknown[])).toMatchObject({ "X-P1-Request": "1" });
  });

  it("clears the token and throws AuthError on 401", async () => {
    setToken("bad");
    fetchMock.mockResolvedValueOnce(json(UNAUTH, 401));
    await expect(listDiscoveries()).rejects.toBeInstanceOf(AuthError);
    await listDiscoveries();
    expect(headersOf(fetchMock.mock.calls[1] as unknown[])).not.toHaveProperty("Authorization");
    setToken("bad");
    fetchMock.mockResolvedValueOnce(json(UNAUTH, 401));
    await expect(listDiscoveries()).rejects.toThrow(/token missing or invalid/i);
  });

  it("never touches web storage or cookies", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    setToken("topsecret");
    await listDiscoveries();
    expect(setItem).not.toHaveBeenCalled();
    expect(document.cookie).toBe("");
    expect(window.location.href).not.toContain("topsecret");
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain("topsecret");
    setItem.mockRestore();
  });
});

class FakeXhr {
  static last: FakeXhr;
  status = 0;
  responseText = "";
  headers: Record<string, string> = {};
  upload = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() { FakeXhr.last = this; }
  open(): void { /* no-op */ }
  setRequestHeader(k: string, v: string): void { this.headers[k] = v; }
  send(): void { /* no-op */ }
}

describe("upload with token", () => {
  beforeEach(() => vi.stubGlobal("XMLHttpRequest", FakeXhr));
  afterEach(() => {
    setToken(null);
    vi.unstubAllGlobals();
  });
  const file = new File(["z"], "a.zip");

  it("adds Authorization only when a token is set", async () => {
    const a = uploadZip(file, () => undefined);
    expect(FakeXhr.last.headers).not.toHaveProperty("Authorization");
    FakeXhr.last.status = 202;
    FakeXhr.last.responseText = JSON.stringify({ id: JOB_ID });
    FakeXhr.last.onload?.();
    await a;
    setToken("tok");
    const b = uploadZip(file, () => undefined);
    expect(FakeXhr.last.headers.Authorization).toBe("Bearer tok");
    FakeXhr.last.status = 401;
    FakeXhr.last.responseText = JSON.stringify(UNAUTH);
    FakeXhr.last.onload?.();
    await expect(b).rejects.toBeInstanceOf(AuthError);
    const c = uploadZip(file, () => undefined);
    expect(FakeXhr.last.headers).not.toHaveProperty("Authorization");
    FakeXhr.last.onerror?.();
    await expect(c).rejects.toThrow();
  });
});

describe("blob downloads", () => {
  const fetchMock = vi.fn();
  const create = vi.fn(() => "blob:mock");
  const revoke = vi.fn();
  let clicked: HTMLAnchorElement[] = [];
  let origCreate: typeof URL.createObjectURL;
  let origRevoke: typeof URL.revokeObjectURL;

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.stubGlobal("fetch", fetchMock);
    origCreate = URL.createObjectURL;
    origRevoke = URL.revokeObjectURL;
    URL.createObjectURL = create;
    URL.revokeObjectURL = revoke;
    clicked = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this);
    });
  });
  afterEach(() => {
    setToken(null);
    vi.restoreAllMocks();
    fetchMock.mockReset();
    create.mockClear();
    revoke.mockClear();
    URL.createObjectURL = origCreate;
    URL.revokeObjectURL = origRevoke;
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("fetches with the header, saves under the server filename and revokes the URL", async () => {
    setToken("tok");
    fetchMock.mockResolvedValue(new Response("{}", {
      headers: { "Content-Disposition": 'attachment; filename="diag-nostics.json"' },
    }));
    await downloadArtifact("/api/discoveries/0123456789abcdef/artifacts/diagnostics.json", "Diagnostics (JSON)", false);
    expect(headersOf(fetchMock.mock.calls[0] as unknown[])).toMatchObject({ Authorization: "Bearer tok" });
    expect(clicked[0]?.download).toBe("diag-nostics.json");
    expect(clicked[0]?.getAttribute("href")).toBe("blob:mock");
    expect(revoke).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1500);
    expect(revoke).toHaveBeenCalledWith("blob:mock");
    expect(document.querySelector("a[href='blob:mock']")).toBeNull();
  });

  it("falls back to the label and opens reports in a new tab", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(new Response("<html>")));
    await downloadArtifact("/api/discoveries/x/artifacts/a.csv", "Inventory (CSV)", false);
    expect(clicked[0]?.download).toBe("Inventory (CSV)");
    await downloadArtifact("/api/discoveries/x/report", "report", true);
    expect(clicked[1]?.target).toBe("_blank");
    expect(clicked[1]?.rel).toBe("noopener");
    await vi.advanceTimersByTimeAsync(61000);
    expect(revoke).toHaveBeenCalledTimes(2);
  });

  it("maps 401, server errors and network failures", async () => {
    setToken("tok");
    fetchMock.mockResolvedValueOnce(json(UNAUTH, 401));
    await expect(downloadArtifact("/api/discoveries/x/report", "r", true)).rejects.toBeInstanceOf(AuthError);
    fetchMock.mockResolvedValueOnce(json({ error: { code: "NOT_FOUND", message: "gone" } }, 404));
    await expect(downloadArtifact("/u", "r", false)).rejects.toThrow("gone (NOT_FOUND)");
    fetchMock.mockResolvedValueOnce(new Response("x", { status: 500 }));
    await expect(downloadArtifact("/u", "r", false)).rejects.toThrow("Download failed (500).");
    fetchMock.mockRejectedValueOnce(new TypeError("x"));
    await expect(downloadArtifact("/u", "r", false)).rejects.toThrow("Cannot reach the server.");
    expect(create).not.toHaveBeenCalled();
  });

  it("parses Content-Disposition safely", () => {
    expect(filenameFrom("attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.json", "f")).toBe("résumé.json");
    // The previous expectation (".._.._evil.json") codified a bug: ".." must not survive.
    expect(filenameFrom("attachment; filename=\"../../evil.json\"", "f")).toBe("evil.json");
    expect(filenameFrom(null, "f")).toBe("f");
    expect(filenameFrom("inline", "f")).toBe("f");
  });

  it("leaves links untouched when not authed (no fetch, default navigation proceeds)", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<BlueprintView job={makeJob()} off={false} onCopied={() => undefined} />);
    await user.click(screen.getByRole("button", { name: /Download Blueprint/ }));
    const link = screen.getByRole("link", { name: "Diagnostics (JSON)" });
    const defaultPrevented = !fireEvent.click(link);
    expect(defaultPrevented).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(create).not.toHaveBeenCalled();
  });

  it("intercepts report and menu clicks only when authed", async () => {
    setToken("tok");
    vi.spyOn(window, "open").mockReturnValue(null); // popup blocked: report falls back to a download
    fetchMock.mockImplementation(() => Promise.resolve(new Response("{}")));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<BlueprintView job={makeJob()} off={false} authed onCopied={() => undefined} />);
    await user.click(screen.getByRole("button", { name: /Download Blueprint/ }));
    await user.click(screen.getByRole("link", { name: "Diagnostics (JSON)" }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0]?.[0]).toBe(`/api/discoveries/${JOB_ID}/artifacts/diagnostics.json`);
    await user.click(screen.getByRole("link", { name: /View Report/ }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
    fetchMock.mockResolvedValueOnce(json(UNAUTH, 401));
    await user.click(screen.getByRole("link", { name: /View Report/ }));
    expect(await screen.findByText(/token missing or invalid/i)).toBeVisible();
  });
});

describe("App with auth_required", () => {
  const fetchMock = vi.fn();
  let pollStatus = 200;

  beforeEach(() => {
    window.history.replaceState(null, "", `/?job=${JOB_ID}`);
    pollStatus = 200;
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/config") {
        return Promise.resolve(json({ auth_required: true, ui: "react", local_directory_enabled: false, ssh_enabled: false, max_upload_bytes: 0 }));
      }
      if (url === "/api/discoveries" && init?.method === "POST") return Promise.resolve(json({ id: JOB_ID }, 202));
      if (url === "/api/discoveries") return Promise.resolve(json({ items: [] }));
      return Promise.resolve(pollStatus === 401 ? json(UNAUTH, 401) : json(makeJob()));
    });
  });
  afterEach(() => {
    setToken(null);
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  const discoveryCalls = (): number => fetchMock.mock.calls.filter((c) => String(c[0]).startsWith("/api/discoveries")).length;

  it("blocks discoveries, lists and the deep link until a token is entered", async () => {
    const user = userEvent.setup();
    render(<App />);
    const field = await screen.findByLabelText("Access token");
    expect(field).toHaveAttribute("type", "password");
    await user.type(screen.getByLabelText(/Repository URL/), "https://x/y.git");
    await user.click(screen.getByRole("button", { name: /Ingest/ }));
    expect(screen.getByText("Enter an access token before starting a discovery.")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Recent Discoveries" }));
    expect(screen.getByText("Enter an access token to load discoveries.")).toBeVisible();
    expect(discoveryCalls()).toBe(0);

    await user.type(field, "tok123");
    await user.click(screen.getByRole("button", { name: "Use token" }));
    expect(await screen.findByRole("heading", { name: "Application Blueprint" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter((c) => String(c[0]).startsWith("/api/discoveries")).every(
      (c) => headersOf(c)["Authorization"] === "Bearer tok123")).toBe(true);
    expect(screen.getByText(/kept in memory only/)).toBeInTheDocument();
    expect(field).toHaveValue("");
  });

  it("shows a clear message on 401, stops polling and clears the token", async () => {
    pollStatus = 401;
    const user = userEvent.setup();
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    render(<App />);
    await user.type(await screen.findByLabelText("Access token"), "stale");
    await user.click(screen.getByRole("button", { name: "Use token" }));
    expect(await screen.findByText(/token missing or invalid/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Access token")).toHaveAttribute("placeholder", "Required by this server");
    expect(screen.queryByRole("button", { name: "Clear token" })).toBeNull();
    const calls = discoveryCalls();
    await new Promise((r) => setTimeout(r, 50));
    expect(discoveryCalls()).toBe(calls);
    expect(setItem).not.toHaveBeenCalled();
    expect(document.cookie).toBe("");
    setItem.mockRestore();
  });

  it("lets the user clear the token explicitly and ignores blank input", async () => {
    const user = userEvent.setup();
    window.history.replaceState(null, "", "/");
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Use token" }));
    expect(screen.queryByRole("button", { name: "Clear token" })).toBeNull();
    await user.type(screen.getByLabelText("Access token"), "abc");
    await user.click(screen.getByRole("button", { name: "Use token" }));
    await user.click(await screen.findByRole("button", { name: "Clear token" }));
    expect(screen.queryByRole("button", { name: "Clear token" })).toBeNull();
  });
});

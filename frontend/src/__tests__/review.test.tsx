import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import {
  AuthError, downloadArtifact, filenameFrom, getDiscovery, listDiscoveries, setToken, uploadZip,
} from "../api";
import { BlueprintView } from "../components/Blueprint";
import { IngestPanel } from "../components/IngestPanel";
import { makeJob } from "./fixture";

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const UNAUTH = { error: { code: "UNAUTHENTICATED", message: "no token" } };
const CONFIG = { local_directory_enabled: false, ssh_enabled: false, max_upload_bytes: 0 };
const VALID = "0123456789abcdef";

function headersOf(call: unknown[] | undefined): Record<string, string> {
  return (((call?.[1] as RequestInit | undefined)?.headers) ?? {}) as Record<string, string>;
}

function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void } {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

function stubBlobUrls(): { create: ReturnType<typeof vi.fn>; revoke: ReturnType<typeof vi.fn>; restore: () => void } {
  const origCreate = URL.createObjectURL;
  const origRevoke = URL.revokeObjectURL;
  const create = vi.fn(() => "blob:mock");
  const revoke = vi.fn();
  URL.createObjectURL = create;
  URL.revokeObjectURL = revoke;
  return { create, revoke, restore: () => { URL.createObjectURL = origCreate; URL.revokeObjectURL = origRevoke; } };
}

describe("fix 1: a stale 401 must not wipe a newer token", () => {
  const fetchMock = vi.fn();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    setToken(null);
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("keeps token B when the 401 belongs to a request sent with token A", async () => {
    const slow = deferred<Response>();
    fetchMock.mockImplementationOnce(() => slow.promise);
    setToken("A");
    const pending = listDiscoveries();
    setToken("B");
    slow.resolve(json(UNAUTH, 401));
    await expect(pending).rejects.toBeInstanceOf(AuthError);
    fetchMock.mockImplementation(() => Promise.resolve(json({ items: [] })));
    await listDiscoveries();
    expect(headersOf(fetchMock.mock.calls[1] as unknown[])).toMatchObject({ Authorization: "Bearer B" });
  });

  it("keeps token B when a download sent with token A gets a 401", async () => {
    const slow = deferred<Response>();
    fetchMock.mockImplementationOnce(() => slow.promise);
    setToken("A");
    const pending = downloadArtifact(`/api/discoveries/${VALID}/report`, "r", false);
    setToken("B");
    slow.resolve(json(UNAUTH, 401));
    await expect(pending).rejects.toBeInstanceOf(AuthError);
    fetchMock.mockImplementation(() => Promise.resolve(json({ items: [] })));
    await listDiscoveries();
    expect(headersOf(fetchMock.mock.calls[1] as unknown[])).toMatchObject({ Authorization: "Bearer B" });
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

describe("fix 1: stale 401 on upload", () => {
  beforeEach(() => vi.stubGlobal("XMLHttpRequest", FakeXhr));
  afterEach(() => {
    setToken(null);
    vi.unstubAllGlobals();
  });

  it("keeps token B when the upload was sent with token A", async () => {
    setToken("A");
    const up = uploadZip(new File(["z"], "a.zip"), () => undefined);
    expect(FakeXhr.last.headers.Authorization).toBe("Bearer A");
    setToken("B");
    FakeXhr.last.status = 401;
    FakeXhr.last.responseText = JSON.stringify(UNAUTH);
    FakeXhr.last.onload?.();
    await expect(up).rejects.toBeInstanceOf(AuthError);
    const next = uploadZip(new File(["z"], "a.zip"), () => undefined);
    expect(FakeXhr.last.headers.Authorization).toBe("Bearer B");
    FakeXhr.last.onerror?.();
    await expect(next).rejects.toThrow();
  });
});

describe("fix 3: View Report opens the tab synchronously", () => {
  const fetchMock = vi.fn();
  let blobs: ReturnType<typeof stubBlobUrls>;
  let clicked: HTMLAnchorElement[] = [];

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    blobs = stubBlobUrls();
    vi.stubGlobal("fetch", fetchMock);
    clicked = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this);
    });
  });
  afterEach(() => {
    setToken(null);
    vi.clearAllTimers();
    vi.useRealTimers();
    blobs.restore();
    vi.restoreAllMocks();
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  const renderAuthed = (): void => {
    setToken("tok");
    render(<BlueprintView job={makeJob()} off={false} authed onCopied={() => undefined} />);
  };

  it("calls window.open inside the click handler, then points the tab at the blob", async () => {
    const slow = deferred<Response>();
    fetchMock.mockImplementation(() => slow.promise);
    const win = { location: { href: "" }, opener: {} as unknown, close: vi.fn() };
    const open = vi.spyOn(window, "open").mockReturnValue(win as unknown as Window);
    renderAuthed();
    fireEvent.click(screen.getByRole("link", { name: /View Report/ }));
    expect(open).toHaveBeenCalledTimes(1);
    expect(win.opener).toBeNull();
    expect(win.location.href).toBe("");
    slow.resolve(new Response("<html>"));
    await waitFor(() => expect(win.location.href).toBe("blob:mock"));
    expect(clicked).toHaveLength(0);
  });

  it("falls back to a download when the popup is blocked", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(new Response("<html>")));
    vi.spyOn(window, "open").mockReturnValue(null);
    renderAuthed();
    fireEvent.click(screen.getByRole("link", { name: /View Report/ }));
    await waitFor(() => expect(clicked).toHaveLength(1));
    expect(clicked[0]?.download).toBeTruthy();
  });

  it("closes the blank tab and shows the error when the fetch fails", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(json({ error: { code: "NOT_FOUND", message: "gone" } }, 404)));
    const win = { location: { href: "" }, opener: {} as unknown, close: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(win as unknown as Window);
    renderAuthed();
    fireEvent.click(screen.getByRole("link", { name: /View Report/ }));
    expect(await screen.findByText("gone (NOT_FOUND)")).toBeVisible();
    expect(win.close).toHaveBeenCalled();
  });
});

describe("fix 4: the download control is a plain disclosure", () => {
  it("has no menu roles or aria-haspopup", async () => {
    const user = userEvent.setup();
    render(<BlueprintView job={makeJob()} off={false} onCopied={() => undefined} />);
    const toggle = screen.getByRole("button", { name: /Download Blueprint/ });
    expect(toggle).not.toHaveAttribute("aria-haspopup");
    await user.click(toggle);
    const list = document.getElementById("download-menu") as HTMLElement;
    expect(list).not.toHaveAttribute("role");
    expect(screen.queryAllByRole("menuitem")).toHaveLength(0);
    expect(within(list).getAllByRole("link")).toHaveLength(9);
  });
});

describe("fix 5: tab keyboard model and panels", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(json({ ...CONFIG, items: [] }))));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("Home selects the first tab, End the last; arrows cycle", async () => {
    const user = userEvent.setup();
    render(<App />);
    const ingest = screen.getByRole("tab", { name: "Ingest Application" });
    const recent = screen.getByRole("tab", { name: "Recent Discoveries" });
    ingest.focus();
    await user.keyboard("{Home}");
    expect(ingest).toHaveAttribute("aria-selected", "true");
    expect(ingest).toHaveFocus();
    await user.keyboard("{End}");
    expect(recent).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{End}");
    expect(recent).toHaveAttribute("aria-selected", "true");
    expect(recent).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(ingest).toHaveFocus();
    await user.keyboard("{ArrowLeft}");
    expect(recent).toHaveFocus();
    await user.keyboard("{Home}");
    expect(ingest).toHaveAttribute("aria-selected", "true");
  });

  it("makes the tabpanels focusable", () => {
    render(<App />);
    expect(document.getElementById("panel-ingest")).toHaveAttribute("tabindex", "0");
    expect(document.getElementById("panel-recent")).toHaveAttribute("tabindex", "0");
  });
});

describe("fix 6: config errors survive source changes", () => {
  it("still shows the config error after the user switches source", async () => {
    const user = userEvent.setup();
    render(<IngestPanel config={CONFIG} configError="Cannot reach the server." hidden={false} onAccepted={() => undefined} />);
    expect(screen.getByText("Cannot reach the server.")).toBeVisible();
    await user.click(screen.getByRole("radio", { name: /ZIP Archive/ }));
    expect(screen.getByText("Cannot reach the server.")).toBeVisible();
  });
});

describe("fix 7: server-provided ids are validated", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation(() => Promise.resolve(json({})));
  });
  afterEach(() => {
    setToken(null);
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("attaches the bearer token only to well-formed discovery paths", async () => {
    setToken("tok");
    await getDiscovery(VALID);
    await getDiscovery("abc");
    await getDiscovery("../config");
    await downloadArtifact("/api/discoveries-evil/x", "n", false).catch(() => undefined);
    await downloadArtifact("/api/discoveries/../config", "n", false).catch(() => undefined);
    const auth = fetchMock.mock.calls.map((c) => headersOf(c as unknown[]).Authorization);
    expect(auth).toEqual(["Bearer tok", undefined, undefined, undefined, undefined]);
  });

  it("renders no actions or links for a malformed job id", () => {
    const { container } = render(
      <BlueprintView job={makeJob({ id: "../../etc" })} off={false} authed onCopied={() => undefined} />,
    );
    expect(screen.queryByRole("button", { name: /Download Blueprint/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /View Report/ })).toBeNull();
    expect(container.innerHTML).not.toContain("..");
  });
});

describe("fix 8: filenames from Content-Disposition are sanitised", () => {
  it("drops path parts, control characters, leading dots and '..'", () => {
    expect(filenameFrom('attachment; filename="../../evil.json"', "f")).toBe("evil.json");
    expect(filenameFrom('attachment; filename="a\u0007b\u007f.json"', "f")).toBe("ab.json");
    expect(filenameFrom('attachment; filename=".hidden.json"', "f")).toBe("hidden.json");
    expect(filenameFrom('attachment; filename="a..b.json"', "f")).not.toContain("..");
    expect(filenameFrom('attachment; filename=".."', "f")).toBe("f");
    expect(filenameFrom("attachment; filename=\"C:\\\\dir\\\\x.csv\"", "f")).toBe("x.csv");
  });
});

describe("flows through the real api module", () => {
  const fetchMock = vi.fn();
  let pollHandler: (auth: string | undefined) => Response;

  beforeEach(() => {
    window.history.replaceState(null, "", `/?job=${VALID}`);
    vi.stubGlobal("fetch", fetchMock);
    pollHandler = () => json(makeJob({ id: VALID }));
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      const auth = (init?.headers as Record<string, string> | undefined)?.Authorization;
      if (url === "/api/config") return Promise.resolve(json({ ...CONFIG, auth_required: true }));
      return Promise.resolve(pollHandler(auth));
    });
  });
  afterEach(() => {
    setToken(null);
    fetchMock.mockReset();
    vi.unstubAllGlobals();
    window.history.replaceState(null, "", "/");
  });

  async function enterToken(user: ReturnType<typeof userEvent.setup>, value: string): Promise<void> {
    await user.type(await screen.findByLabelText("Access token"), value);
    await user.click(screen.getByRole("button", { name: "Use token" }));
  }

  it("fix 2: entering a new token restarts polling and clears the poll error", async () => {
    pollHandler = (auth) => (auth === "Bearer fresh" ? json(makeJob({ id: VALID })) : json(UNAUTH, 401));
    const user = userEvent.setup();
    render(<App />);
    await enterToken(user, "stale");
    expect(await screen.findByText(/token missing or invalid/i)).toBeVisible();
    await enterToken(user, "fresh");
    expect(await screen.findByRole("heading", { name: "Application Blueprint" })).toBeVisible();
    expect(screen.queryByText(/token missing or invalid/i)).toBeNull();
  });

  it("fix 2: does not poll twice when the first token also triggers the deep link", async () => {
    const user = userEvent.setup();
    render(<App />);
    await enterToken(user, "tok");
    await screen.findByRole("heading", { name: "Application Blueprint" });
    const polls = fetchMock.mock.calls.filter((c) => String(c[0]).startsWith("/api/discoveries/"));
    expect(polls).toHaveLength(1);
  });

  it("fix 9: re-announces a repeated copy by clearing then setting the message", async () => {
    setToken(null);
    fetchMock.mockImplementation((url: string) => Promise.resolve(
      url === "/api/config" ? json(CONFIG) : json(makeJob({ id: VALID })),
    ));
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    const user = userEvent.setup();
    render(<App />);
    const live = (await screen.findByRole("heading", { name: "Application Blueprint" }))
      .closest("main")?.querySelector(":scope > p.visually-hidden[aria-live]") as HTMLElement;
    const seen: string[] = [];
    const observer = new MutationObserver(() => seen.push(live.textContent ?? ""));
    observer.observe(live, { childList: true, characterData: true, subtree: true });
    await user.click(screen.getByRole("button", { name: "Copy commit" }));
    await waitFor(() => expect(seen.filter((t) => t === "commit copied")).toHaveLength(1));
    await user.click(screen.getByRole("button", { name: "Copy commit" }));
    await waitFor(() => expect(seen.filter((t) => t === "commit copied")).toHaveLength(2));
    expect(seen).toContain("");
    observer.disconnect();
    await act(async () => { await Promise.resolve(); });
  });
});

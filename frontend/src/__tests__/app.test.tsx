import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import * as api from "../api";
import { JOB_ID, XSS, makeJob } from "./fixture";

vi.mock("../api");
const mocked = vi.mocked(api);

const CONFIG = { local_directory_enabled: false, ssh_enabled: false, max_upload_bytes: 10 };

async function mount(config = CONFIG): Promise<ReturnType<typeof userEvent.setup>> {
  mocked.getConfig.mockResolvedValue(config);
  render(<App />);
  await waitFor(() => expect(mocked.getConfig).toHaveBeenCalled());
  return userEvent.setup({ applyAccept: false });
}

const alertText = (): string => (document.getElementById("ingest-error")?.textContent ?? "");

describe("App shell", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => vi.useRealTimers());

  it("renders the pipeline, nav and idle badge", async () => {
    await mount();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Stage 1: Ingestion and Discovery");
    expect(screen.getAllByText("Planned")).toHaveLength(5);
    expect(screen.getByText("Stage 1 – Idle")).toBeInTheDocument();
    expect(screen.getByText("Projects").closest("span.topnav-item")).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("Reports").closest("span.topnav-item")).toHaveAttribute("aria-disabled", "true");
    expect(screen.getAllByText("Pending")).toHaveLength(5);
    expect(screen.getByTestId("stage-1-marker")).toHaveAttribute("data-state", "idle");
  });

  it("reports a config load failure", async () => {
    mocked.getConfig.mockRejectedValue(new Error("Cannot reach the server."));
    render(<App />);
    expect(await screen.findByText("Cannot reach the server.")).toBeInTheDocument();
  });

  it("disables the local directory card unless the server enables it", async () => {
    await mount();
    expect(screen.getByRole("radio", { name: /Local Directory/ })).toBeDisabled();
    expect(screen.getByText("Disabled by server configuration")).toBeInTheDocument();
    expect(document.getElementById("card-directory")).toHaveClass("is-disabled");
  });

  it("enables the directory form when configured and posts the path", async () => {
    const user = await mount({ ...CONFIG, local_directory_enabled: true });
    await waitFor(() => expect(screen.getByRole("radio", { name: /Local Directory/ })).toBeEnabled());
    await user.click(screen.getByRole("radio", { name: /Local Directory/ }));
    await user.click(screen.getByRole("button", { name: /Ingest/, hidden: false }));
    expect(alertText()).toBe("Enter a directory path.");
    mocked.createDiscovery.mockResolvedValue({ id: JOB_ID });
    mocked.getDiscovery.mockResolvedValue(makeJob({ status: "running", blueprint: null }));
    await user.type(screen.getByLabelText(/Directory path/), "  /srv/app ");
    await user.click(screen.getByRole("button", { name: /Ingest/ }));
    expect(mocked.createDiscovery).toHaveBeenCalledWith({ kind: "directory", path: "/srv/app" });
  });
});

describe("Git form", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    window.history.replaceState(null, "", "/");
  });

  it("rejects an empty URL and focuses the field", async () => {
    const user = await mount();
    await user.click(screen.getByRole("button", { name: /Ingest/ }));
    expect(alertText()).toBe("Enter a repository URL.");
    expect(screen.getByLabelText(/Repository URL/)).toHaveFocus();
    expect(mocked.createDiscovery).not.toHaveBeenCalled();
  });

  it("submits trimmed URL with null ref, then polls and shows the blueprint", async () => {
    const user = await mount();
    mocked.createDiscovery.mockResolvedValue({ id: JOB_ID });
    mocked.getDiscovery.mockResolvedValue(makeJob());
    await user.type(screen.getByLabelText(/Repository URL/), " https://git.example.com/a.git ");
    await user.click(screen.getByRole("button", { name: /Ingest/ }));
    expect(mocked.createDiscovery).toHaveBeenCalledWith({ kind: "git", url: "https://git.example.com/a.git", ref: null });
    expect(await screen.findByRole("heading", { name: "Application Blueprint" })).toBeInTheDocument();
    expect(window.location.search).toBe(`?job=${JOB_ID}`);
    expect(screen.getByText("Stage 1 – Completed with 1 blocker")).toBeInTheDocument();
    expect(screen.getByTestId("stage-1-marker")).toHaveAttribute("data-state", "blocked");
    expect(screen.getByText("Created")).toBeInTheDocument();
    expect(screen.getByText("Completed with warnings")).toBeInTheDocument();
  });

  it("sends the ref when provided and surfaces API errors", async () => {
    const user = await mount();
    mocked.createDiscovery.mockRejectedValue(new Error("URL rejected (bad_url)"));
    await user.type(screen.getByLabelText(/Repository URL/), "https://x/y.git");
    await user.type(screen.getByLabelText(/Branch/), "develop");
    await user.click(screen.getByRole("button", { name: /Ingest/ }));
    expect(mocked.createDiscovery).toHaveBeenCalledWith({ kind: "git", url: "https://x/y.git", ref: "develop" });
    expect(await screen.findByText("URL rejected (bad_url)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Ingest/ })).toBeEnabled();
  });

  it("shows a failed job error and badge", async () => {
    const user = await mount();
    mocked.createDiscovery.mockResolvedValue({ id: JOB_ID });
    mocked.getDiscovery.mockResolvedValue(makeJob({
      status: "failed", blueprint: null, error: { code: "clone_failed", message: `boom ${XSS}` },
      steps: [{ id: "ingestion", name: "Ingestion", status: "failed", message: "why" }],
    }));
    await user.type(screen.getByLabelText(/Repository URL/), "https://x/y.git");
    await user.click(screen.getByRole("button", { name: /Ingest/ }));
    expect(await screen.findByText(`Discovery failed: boom ${XSS} (clone_failed)`)).toBeInTheDocument();
    expect(screen.getByText("Stage 1 – Failed")).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Application Blueprint" })).toBeNull();
  });
});

describe("ZIP form", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    window.history.replaceState(null, "", "/");
  });

  async function openZip(): Promise<ReturnType<typeof userEvent.setup>> {
    const user = await mount();
    await user.click(screen.getByRole("radio", { name: /ZIP Archive/ }));
    return user;
  }
  const input = (): HTMLInputElement => screen.getByTestId("zip-input") as HTMLInputElement;

  it("requires a file", async () => {
    const user = await openZip();
    await user.click(screen.getAllByRole("button", { name: /Ingest/ }).find((b) => b.id === "btn-zip") as HTMLElement);
    expect(alertText()).toBe("Choose a ZIP file first.");
  });

  it("rejects non-zip files", async () => {
    const user = await openZip();
    await user.upload(input(), new File(["x"], "notes.txt"));
    expect(alertText()).toBe("The file must be a .zip archive.");
    expect(screen.getByText(/Drag a \.zip file here/)).toBeInTheDocument();
  });

  it("rejects files above config.max_upload_bytes", async () => {
    const user = await openZip();
    await user.upload(input(), new File([new Uint8Array(11)], "big.zip"));
    expect(alertText()).toBe("The file is larger than the server limit of 10 B.");
  });

  it("accepts a valid zip, uploads with progress and starts polling", async () => {
    const user = await openZip();
    mocked.uploadZip.mockImplementation((_f, onProgress) => {
      onProgress(0.5);
      return Promise.resolve({ id: JOB_ID });
    });
    mocked.getDiscovery.mockResolvedValue(makeJob());
    await user.upload(input(), new File(["abc"], "app.zip"));
    expect(screen.getByText("app.zip (3 B)")).toBeInTheDocument();
    await user.click(document.getElementById("btn-zip") as HTMLElement);
    expect(mocked.uploadZip).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("heading", { name: "Application Blueprint" })).toBeInTheDocument();
    expect(document.getElementById("zip-progress")).not.toBeVisible();
  });

  it("shows upload errors", async () => {
    const user = await openZip();
    mocked.uploadZip.mockRejectedValue(new Error("Too large (too_big)"));
    await user.upload(input(), new File(["abc"], "app.zip"));
    await user.click(document.getElementById("btn-zip") as HTMLElement);
    expect(await screen.findByText("Too large (too_big)")).toBeInTheDocument();
  });

  it("supports drag and drop and keyboard activation of the dropzone", async () => {
    await openZip();
    const drop = document.getElementById("zip-drop") as HTMLElement;
    const clicked = vi.spyOn(input(), "click");
    act(() => {
      drop.dispatchEvent(new Event("dragenter", { bubbles: true, cancelable: true }));
    });
    expect(drop).toHaveClass("is-over");
    const file = new File(["abc"], "dropped.zip");
    const ev = new Event("drop", { bubbles: true, cancelable: true });
    Object.defineProperty(ev, "dataTransfer", { value: { files: [file] } });
    act(() => { drop.dispatchEvent(ev); });
    expect(drop).not.toHaveClass("is-over");
    expect(await screen.findByText("dropped.zip (3 B)")).toBeInTheDocument();
    drop.focus();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    expect(clicked).toHaveBeenCalledTimes(2);
  });
});

describe("tabs and recent discoveries", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    window.history.replaceState(null, "", "/");
  });

  it("navigates tabs with the keyboard and loads recent items", async () => {
    mocked.listDiscoveries.mockResolvedValue({ items: [
      { ...makeJob({ id: "aaaaaaaaaaaaaaaa", status: "completed" }), summary: { project: `P ${XSS}`, total_files: 1500 } },
      makeJob({ id: "bbbbbbbbbbbbbbbb", status: "failed", kind: "zip", label: "fallback", blueprint: null }),
      makeJob({ id: "cccccccccccccccc", status: "queued", kind: null, label: null, blueprint: null }),
    ] });
    const user = await mount();
    const ingest = screen.getByRole("tab", { name: "Ingest Application" });
    const recent = screen.getByRole("tab", { name: "Recent Discoveries" });
    expect(ingest).toHaveAttribute("aria-selected", "true");
    expect(recent).toHaveAttribute("tabindex", "-1");
    ingest.focus();
    await user.keyboard("{ArrowRight}");
    expect(recent).toHaveAttribute("aria-selected", "true");
    expect(recent).toHaveFocus();
    expect(ingest).toHaveAttribute("tabindex", "-1");
    expect(await screen.findByText(`P ${XSS}`)).toBeInTheDocument();
    expect(screen.getByText("1,500")).toBeInTheDocument();
    expect(screen.getByText("fallback")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("ZIP Archive")).toBeInTheDocument();
    expect(screen.getByText("failed")).toHaveClass("st-failed");
    expect(screen.getByText("queued")).toHaveClass("st-running");
    expect(document.getElementById("panel-ingest")).not.toBeVisible();
    await user.keyboard("{ArrowLeft}");
    expect(ingest).toHaveFocus();
    await user.keyboard("{End}");
    expect(recent).toHaveFocus();
    await user.keyboard("{Home}");
    expect(ingest).toHaveFocus();
    await user.keyboard("a");
    expect(ingest).toHaveFocus();
  });

  it("distinguishes Home from End with two tabs", async () => {
    mocked.listDiscoveries.mockResolvedValue({ items: [] });
    const user = await mount();
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
    await user.keyboard("{Home}");
    expect(ingest).toHaveAttribute("aria-selected", "true");
    expect(ingest).toHaveFocus();
  });

  it("opens a discovery from the list and returns to the ingest tab", async () => {
    mocked.listDiscoveries.mockResolvedValue({ items: [makeJob({ id: JOB_ID })] });
    mocked.getDiscovery.mockResolvedValue(makeJob());
    const user = await mount();
    await user.click(screen.getByRole("tab", { name: "Recent Discoveries" }));
    await user.click(await screen.findByRole("button", { name: `Open discovery ${JOB_ID}` }));
    expect(await screen.findByRole("heading", { name: "Application Blueprint" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Ingest Application" })).toHaveAttribute("aria-selected", "true");
  });

  it("shows the empty state and list errors", async () => {
    mocked.listDiscoveries.mockResolvedValueOnce({ items: [] });
    const user = await mount();
    await user.click(screen.getByRole("tab", { name: "Recent Discoveries" }));
    expect(await screen.findByText(/No discoveries yet/)).toBeVisible();
    mocked.listDiscoveries.mockRejectedValueOnce(new Error("list failed"));
    await user.click(screen.getByRole("tab", { name: "Ingest Application" }));
    await user.click(screen.getByRole("tab", { name: "Recent Discoveries" }));
    expect(await screen.findByText("list failed")).toBeVisible();
    const panel = document.getElementById("panel-recent") as HTMLElement;
    expect(within(panel).getByRole("alert")).toHaveTextContent("list failed");
  });
});

describe("deep link", () => {
  beforeEach(() => vi.resetAllMocks());

  it("starts polling for a valid ?job= id", async () => {
    window.history.replaceState(null, "", `/?job=${JOB_ID}`);
    mocked.getDiscovery.mockResolvedValue(makeJob());
    await mount();
    expect(await screen.findByRole("heading", { name: "Application Blueprint" })).toBeInTheDocument();
    expect(mocked.getDiscovery).toHaveBeenCalledWith(JOB_ID);
  });

  it("ignores malformed ids", async () => {
    window.history.replaceState(null, "", "/?job=../../etc/passwd");
    // local_directory_enabled lets us observe that the config response has been applied.
    await mount({ ...CONFIG, local_directory_enabled: true });
    await waitFor(() => expect(screen.getByRole("radio", { name: /Local Directory/ })).toBeEnabled());
    // Let the config promise chain settle so the deep-link effect has definitely run.
    await act(async () => { await new Promise((r) => setTimeout(r, 30)); });
    expect(mocked.getDiscovery).not.toHaveBeenCalled();
    expect(screen.getAllByText("Pending")).toHaveLength(5);
  });

  it("announces polling failures", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    window.history.replaceState(null, "", `/?job=${JOB_ID}`);
    mocked.getDiscovery.mockRejectedValue(new Error("down"));
    mocked.getConfig.mockResolvedValue(CONFIG);
    render(<App />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(screen.getByText("Lost contact with the server: down")).toBeInTheDocument();
    vi.useRealTimers();
  });
});

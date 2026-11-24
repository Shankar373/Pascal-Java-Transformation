import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BlueprintView } from "../components/Blueprint";
import { DOWNLOADS } from "../constants";
import { JOB_ID, XSS, makeBlueprint, makeJob } from "./fixture";

function view(job = makeJob(), off = false, onCopied = vi.fn()): ReturnType<typeof render> {
  return render(<BlueprintView job={job} off={off} onCopied={onCopied} />);
}

describe("BlueprintView", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders nothing until the job completes with a blueprint", () => {
    const { container } = view(makeJob({ status: "running", blueprint: null }));
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the six metric tiles with formatted values", () => {
    view();
    const tiles = screen.getAllByRole("listitem").filter((li) => li.classList.contains("tile"));
    expect(tiles.map((t) => t.textContent)).toEqual([
      "Total Files1,234", "Directories56", "Pascal Sources789", "Projects3",
      "Database Artifacts4", "External Dependencies12",
    ]);
  });

  it("renders the donut legend with percentages and an accessible label", () => {
    view();
    expect(screen.getByRole("img", { name: "File distribution of 100 files" })).toBeInTheDocument();
    const legend = screen.getByText("Pascal sources").closest("ul") as HTMLElement;
    expect(within(legend).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Pascal sources60.0%", "Forms30.0%", "Other10.0%",
    ]);
    const segs = document.querySelectorAll("circle.donut-seg");
    expect(segs).toHaveLength(3);
    expect(segs[0]?.getAttribute("stroke-dasharray")).toMatch(/^\d/);
    expect(document.querySelector("[style]")).toBeNull();
  });

  it("lists top five key dependencies with Resolved/Unresolved pills", () => {
    view();
    const panel = screen.getByRole("heading", { name: "Key Dependencies (Top 5)" }).closest("section") as HTMLElement;
    const items = within(panel).getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(items[0]).toHaveTextContent("FireDAC");
    expect(within(items[0] as HTMLElement).getByText("Resolved")).toHaveClass("pill-ok");
    expect(within(items[1] as HTMLElement).getByText("Unresolved")).toHaveClass("pill-bad");
    expect(within(panel).queryByText("k6-hidden")).toBeNull();
  });

  it("shows the empty state for missing key dependencies and structure", () => {
    view(makeJob({ blueprint: makeBlueprint({ dependencies: {}, structure: null, components: [], dialect: {} }) }));
    expect(screen.getByText("No key dependencies detected.")).toBeInTheDocument();
    expect(screen.getByText("No structure available.")).toBeInTheDocument();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(screen.getByText("Not determined")).toBeInTheDocument();
    expect(screen.getByText("Not stated in project files")).toBeInTheDocument();
  });

  it("shows project info, dialect, and the blocker banner", () => {
    view();
    expect(screen.getByText("Git Repository")).toBeInTheDocument();
    expect(screen.getByText("main (abcdef1)")).toBeInTheDocument();
    expect(screen.getByText("dcc32 (detected)")).toBeInTheDocument();
    expect(screen.getByText("XE2 (indicated)")).toBeInTheDocument();
    expect(screen.getByText("uses Vcl.Forms, {$mode delphi}")).toBeInTheDocument();
    const banner = screen.getByRole("note");
    expect(banner).toHaveTextContent("B1: Missing runtime");
    expect(banner).toHaveTextContent("Second blocker");
  });

  it("omits the banner without blockers", () => {
    view(makeJob({ blueprint: makeBlueprint({ blockers: [] }) }));
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("builds the View Report link and all nine download links", async () => {
    const user = userEvent.setup();
    view();
    expect(screen.getByRole("link", { name: /View Report/ })).toHaveAttribute("href", `/api/discoveries/${JOB_ID}/report`);
    const toggle = screen.getByRole("button", { name: /Download Blueprint/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById("download-menu")).not.toBeVisible();
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const links = within(document.getElementById("download-menu") as HTMLElement).getAllByRole("link");
    expect(links).toHaveLength(9);
    expect(DOWNLOADS).toHaveLength(9);
    expect(links.map((a) => a.getAttribute("href"))).toEqual(
      DOWNLOADS.map(([, path]) => `/api/discoveries/${JOB_ID}/${path}`),
    );
    expect(links[8]).toHaveTextContent("Inventory (CSV)");
  });

  it("closes the download menu on Escape (restoring focus) and on outside click", async () => {
    const user = userEvent.setup();
    view();
    const toggle = screen.getByRole("button", { name: /Download Blueprint/ });
    await user.click(toggle);
    await user.keyboard("{Escape}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await user.click(document.body);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("expands and collapses the structure tree (open only at depth 0)", async () => {
    const user = userEvent.setup();
    view();
    const root = screen.getByRole("button", { name: /Payroll/ });
    expect(root).toHaveAttribute("aria-expanded", "true");
    const core = screen.getByRole("button", { name: /Core \(12\)/ });
    expect(core).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("Salary.pas")).not.toBeVisible();
    await user.click(core);
    expect(screen.getByText("Salary.pas")).toBeVisible();
    expect(screen.getByText("Lonely (1)")).toBeInTheDocument();
    expect(screen.getByText("More items not shown")).toBeInTheDocument();
    await user.click(root);
    expect(root).toHaveAttribute("aria-expanded", "false");
  });

  it("marks absent components as not detected", () => {
    view();
    const chip = screen.getByText("Reports").closest("li") as HTMLElement;
    expect(chip).toHaveClass("is-absent");
    expect(chip).toHaveTextContent("(not detected)");
    expect(chip).toHaveAttribute("title", "Reports: not detected");
    expect(screen.getByText("GUI Application").closest("li")).toHaveAttribute("title", "GUI Application: 5 found");
  });

  it("copies the commit and checkpoint ID and announces it", async () => {
    const user = userEvent.setup();
    const onCopied = vi.fn();
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    view(makeJob(), false, onCopied);
    await user.click(screen.getByRole("button", { name: "Copy commit" }));
    expect(writeText).toHaveBeenCalledWith("abcdef1234567890");
    expect(onCopied).toHaveBeenCalledWith("commit copied");
    await user.click(screen.getByRole("button", { name: "Copy checkpoint ID" }));
    expect(writeText).toHaveBeenCalledWith("chk-0001");
  });

  it("falls back to execCommand when the clipboard API is missing or rejects", async () => {
    const user = userEvent.setup();
    const onCopied = vi.fn();
    const exec = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, "execCommand", { value: exec, configurable: true });
    vi.stubGlobal("navigator", { clipboard: undefined });
    view(makeJob(), false, onCopied);
    await user.click(screen.getByRole("button", { name: "Copy commit" }));
    expect(exec).toHaveBeenCalledWith("copy");
    expect(onCopied).toHaveBeenCalledWith("commit copied");
    expect(document.querySelector("textarea")).toBeNull();
    vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockRejectedValue(new Error("no")) } });
    await user.click(screen.getByRole("button", { name: "Copy checkpoint ID" }));
    await vi.waitFor(() => expect(onCopied).toHaveBeenCalledWith("checkpoint ID copied"));
  });
});

describe("detail tables", () => {
  it("renders every section with counts and data", () => {
    view();
    const titles = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(titles).toEqual([
      "Application Blueprint", "Projects1", "Libraries1", "Databases2", "External Integrations1",
      "Runtime Dependencies1", "Native Libraries1", "Build Scripts1", "Compiler Configuration1",
      "Unresolved Dependencies1", "Build Requirements", "Diagnostics2", "Limitations",
    ]);
    const statusHeader = screen.getByRole("columnheader", { name: "Discovery status" });
    expect(statusHeader).toHaveAttribute(
      "title", "Whether Stage 1 could scan this project. It is not a conversion-support claim.");
    expect(screen.queryByRole("columnheader", { name: "Status" })).toBeNull();
    expect(screen.getByText("db/schema.sql")).toBeInTheDocument();
    expect(screen.getByText("12 statements, 4 tables")).toBeInTheDocument();
    expect(screen.getByText("a.pas:3")).toBeInTheDocument();
    expect(screen.getByText("high")).toHaveClass("sev-high");
    expect(screen.getByText("compiler versions")).toBeInTheDocument();
    expect(screen.getByText("XE2, XE3")).toBeInTheDocument();
    expect(screen.getByText("true")).toBeInTheDocument();
    expect(screen.getByText("1 error")).toBeInTheDocument();
    expect(screen.getByText("3 info")).toBeInTheDocument();
    expect(screen.getByText("c.pas:9")).toBeInTheDocument();
    expect(screen.getByText("Static analysis only")).toBeInTheDocument();
  });

  it("shows None detected for empty sections and hides Build Requirements", () => {
    view(makeJob({ blueprint: makeBlueprint({ dependencies: {}, projects: [], unresolved: undefined }) }));
    expect(screen.getAllByText("None detected.")).toHaveLength(9);
    expect(screen.queryByRole("heading", { name: "Build Requirements" })).toBeNull();
  });

  it("truncates tables at 200 rows with a note", () => {
    const diagnostics = Array.from({ length: 250 }, (_, i) => ({ severity: "info", code: `C${i}`, message: `m${i}` }));
    view(makeJob({ blueprint: makeBlueprint({ diagnostics }) }));
    const section = screen.getByRole("heading", { name: /^Diagnostics/ }).closest("section") as HTMLElement;
    expect(within(section).getAllByRole("row")).toHaveLength(201);
    expect(within(section).getByText("Showing the first 200 of 250 rows. The full data is in the downloads.")).toBeInTheDocument();
    expect(within(section).getByText("C199")).toBeInTheDocument();
    expect(within(section).queryByText("C200")).toBeNull();
  });

  it("hides details with is-off when another tab is active", () => {
    view(makeJob(), true);
    expect(document.querySelector(".details")).toHaveClass("is-off");
    expect(document.getElementById("blueprint-section")).toHaveClass("is-off");
  });
});

describe("untrusted data rendering", () => {
  it("renders malicious strings as literal text and creates no elements", () => {
    const { container } = view();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(`Payroll ${XSS}`)).toBeInTheDocument();
    expect(screen.getByText(`Bad ${XSS}`)).toBeInTheDocument();
    expect(container.innerHTML).not.toContain("<img");
    expect(container.querySelector("[onerror]")).toBeNull();
  });
});

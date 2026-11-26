import { describe, expect, it } from "vitest";
import { evShort, fmt, fmtBytes, fmtDate, listCell, validateZip, yesNo } from "../format";
import { nextPollDelay, stepText, summarise } from "../status";
import { makeBlueprint, makeJob } from "./fixture";

describe("format helpers", () => {
  it("formats numbers with grouping and dashes for non-numbers", () => {
    expect(fmt(1234567)).toBe("1,234,567");
    expect(fmt(undefined)).toBe("—");
    expect(fmt("7")).toBe("—");
  });

  it("formats byte sizes", () => {
    expect(fmtBytes(512)).toBe("512 B");
    expect(fmtBytes(2048)).toBe("2.0 KB");
    expect(fmtBytes(5 * 1048576)).toBe("5.0 MB");
  });

  it("formats dates and tolerates bad input", () => {
    expect(fmtDate(null)).toBe("—");
    expect(fmtDate("garbage")).toBe("garbage");
    expect(fmtDate("2026-01-02T03:04:05Z")).toMatch(/2026/);
  });

  it("shortens evidence and list cells", () => {
    expect(evShort([{ file: "a.pas", line: 3 }])).toBe("a.pas:3");
    expect(evShort([{ file: "a.pas" }])).toBe("a.pas");
    expect(evShort([])).toBe("—");
    expect(evShort(undefined)).toBe("—");
    expect(listCell(["a", "b"])).toBe("a, b");
    expect(listCell([])).toBe("—");
    expect(yesNo(true)).toBe("Yes");
    expect(yesNo(0)).toBe("No");
  });

  it("validates zip uploads", () => {
    const zip = new File(["x"], "A.ZIP");
    expect(validateZip(zip, 0)).toBeNull();
    expect(validateZip(new File(["x"], "a.txt"), 0)).toMatch(/\.zip/);
    expect(validateZip(new File(["xxxxxxxx"], "a.zip"), 4)).toMatch(/larger than the server limit of 4 B/);
  });
});

describe("status helpers", () => {
  it("summarises job states", () => {
    expect(summarise(null).state).toBe("idle");
    expect(summarise(makeJob({ status: "failed" })).state).toBe("failed");
    expect(summarise(makeJob({ status: "running" })).state).toBe("running");
    expect(summarise(makeJob()).text).toBe("Completed with 1 blocker");
    const many = makeBlueprint({ summary: { blockers: 3 } });
    expect(summarise(makeJob({ blueprint: many })).text).toBe("Completed with 3 blockers");
    const clean = makeBlueprint({ summary: { blockers: 0 }, stage: { status: "COMPLETED" } });
    expect(summarise(makeJob({ blueprint: clean })).state).toBe("completed");
    const stageOnly = makeBlueprint({ summary: {}, blockers: [], stage: { status: "COMPLETED_WITH_BLOCKERS" } });
    expect(summarise(makeJob({ blueprint: stageOnly })).text).toBe("Completed with blockers");
  });

  it("describes steps", () => {
    expect(stepText({ id: "checkpoint", name: "c", status: "completed" })).toBe("Created");
    expect(stepText({ id: "other", name: "c", status: "completed" })).toBe("Completed");
    expect(stepText({ id: "x", name: "c", status: "running" })).toBe("In progress");
    expect(stepText({ id: "x", name: "c", status: "weird" })).toBe("weird");
  });

  it("caps the poll delay", () => {
    expect(nextPollDelay(1000, 8000, 1.15)).toBe(1150);
    expect(nextPollDelay(7900, 8000, 1.15)).toBe(8000);
  });
});

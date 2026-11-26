import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDiscovery } from "../hooks/useDiscovery";
import { JOB_ID, makeJob } from "./fixture";
import * as api from "../api";
import type { JobView } from "../types";

vi.mock("../api");
const getDiscovery = vi.mocked(api.getDiscovery);

const flush = async (ms = 0): Promise<void> => {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
};

describe("useDiscovery polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    getDiscovery.mockReset();
  });
  afterEach(() => vi.useRealTimers());

  it("polls immediately, backs off by 1.15x and stops on completion", async () => {
    getDiscovery
      .mockResolvedValueOnce(makeJob({ status: "running", blueprint: null }))
      .mockResolvedValueOnce(makeJob({ status: "running", blueprint: null }))
      .mockResolvedValueOnce(makeJob());
    const { result } = renderHook(() => useDiscovery());
    act(() => result.current.start(JOB_ID));
    await flush();
    expect(getDiscovery).toHaveBeenCalledTimes(1);
    expect(window.location.search).toBe(`?job=${JOB_ID}`);
    await flush(1149);
    expect(getDiscovery).toHaveBeenCalledTimes(1);
    await flush(1);
    expect(getDiscovery).toHaveBeenCalledTimes(2);
    await flush(1322); // 1150 * 1.15 rounded
    expect(getDiscovery).toHaveBeenCalledTimes(2);
    await flush(1);
    expect(getDiscovery).toHaveBeenCalledTimes(3);
    expect(result.current.job?.status).toBe("completed");
    await flush(60000);
    expect(getDiscovery).toHaveBeenCalledTimes(3);
  });

  it("stops on failed", async () => {
    getDiscovery.mockResolvedValue(makeJob({ status: "failed", blueprint: null, error: { code: "x", message: "m" } }));
    const { result } = renderHook(() => useDiscovery());
    act(() => result.current.start(JOB_ID));
    await flush(30000);
    expect(getDiscovery).toHaveBeenCalledTimes(1);
    expect(result.current.job?.status).toBe("failed");
  });

  it("doubles the delay on errors, caps at 8s and gives up after more than six", async () => {
    getDiscovery.mockRejectedValue(new Error("down"));
    const { result } = renderHook(() => useDiscovery());
    act(() => result.current.start(JOB_ID));
    await flush();
    const waits = [2000, 4000, 8000, 8000, 8000, 8000];
    for (const [i, wait] of waits.entries()) {
      expect(getDiscovery).toHaveBeenCalledTimes(i + 1);
      await flush(wait - 1);
      expect(getDiscovery).toHaveBeenCalledTimes(i + 1);
      await flush(1);
    }
    expect(getDiscovery).toHaveBeenCalledTimes(7);
    expect(result.current.pollError).toBe("Lost contact with the server: down");
    await flush(60000);
    expect(getDiscovery).toHaveBeenCalledTimes(7);
  });

  it("resets the error count after a success", async () => {
    getDiscovery
      .mockRejectedValueOnce(new Error("blip"))
      .mockResolvedValueOnce(makeJob({ status: "queued", blueprint: null }))
      .mockResolvedValue(makeJob());
    const { result } = renderHook(() => useDiscovery());
    act(() => result.current.start(JOB_ID));
    await flush(2000);
    expect(result.current.pollError).toBeNull();
    expect(result.current.job?.status).toBe("queued");
    await flush(5000);
    expect(result.current.job?.status).toBe("completed");
  });

  it("ignores a stale response from a superseded job (manually resolved promises)", async () => {
    const idA = "aaaaaaaaaaaaaaaa";
    const idB = "bbbbbbbbbbbbbbbb";
    let resolveA!: (j: JobView) => void;
    let resolveB!: (j: JobView) => void;
    getDiscovery
      .mockImplementationOnce(() => new Promise<JobView>((r) => { resolveA = r; }))
      .mockImplementationOnce(() => new Promise<JobView>((r) => { resolveB = r; }));
    const { result } = renderHook(() => useDiscovery());
    act(() => result.current.start(idA));
    act(() => result.current.start(idB));
    await act(async () => { resolveB(makeJob({ id: idB, status: "completed" })); });
    expect(result.current.job?.id).toBe(idB);
    await act(async () => { resolveA(makeJob({ id: idA, status: "completed" })); });
    expect(result.current.job?.id).toBe(idB);
  });

  it("cleans up on unmount", async () => {
    getDiscovery.mockResolvedValue(makeJob({ status: "running", blueprint: null }));
    const { result, unmount } = renderHook(() => useDiscovery());
    act(() => result.current.start(JOB_ID));
    await flush();
    unmount();
    const calls = getDiscovery.mock.calls.length;
    await flush(30000);
    expect(getDiscovery.mock.calls.length).toBe(calls);
  });

  it("stops polling on an AuthError and surfaces its message without retrying", async () => {
    const { AuthError } = await vi.importActual<typeof import("../api")>("../api");
    getDiscovery.mockRejectedValue(new AuthError());
    const { result } = renderHook(() => useDiscovery());
    act(() => result.current.start(JOB_ID));
    await flush(60000);
    expect(getDiscovery).toHaveBeenCalledTimes(1);
    expect(result.current.pollError).toMatch(/token missing or invalid/i);
  });

  it("rejects a malformed id without making a request", async () => {
    const { result } = renderHook(() => useDiscovery());
    act(() => result.current.start("../../etc/passwd"));
    await flush(5000);
    expect(getDiscovery).not.toHaveBeenCalled();
    expect(result.current.job).toBeNull();
    expect(result.current.pollError).toBe("Invalid discovery id.");
    expect(window.location.search).not.toContain("etc");
  });
});

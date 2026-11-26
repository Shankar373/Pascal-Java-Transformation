import { useCallback, useEffect, useRef, useState } from "react";
import { getDiscovery } from "../api";
import { ID_RE, POLL_GROWTH, POLL_MAX_ERRORS, POLL_MAX_MS, POLL_MIN_MS } from "../constants";
import { nextPollDelay } from "../status";
import type { JobView } from "../types";

export interface DiscoveryState {
  job: JobView | null;
  /** Polling-level failure message (lost contact with the server). */
  pollError: string | null;
  start: (id: string) => void;
  /** Restarts polling for the current job if it has not settled (e.g. after a new token). */
  resume: () => void;
}

function messageOf(err: unknown): string {
  return err instanceof Error ? err.message : "Unexpected error.";
}

function replaceUrl(id: string): void {
  try {
    window.history.replaceState(null, "", `?job=${id}`);
  } catch {
    /* history may be unavailable (sandboxed frames); the deep link is best-effort */
  }
}

/** Polls /api/discoveries/{id} with exponential backoff until the job settles. */
export function useDiscovery(): DiscoveryState {
  const [job, setJob] = useState<JobView | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const run = useRef(0);
  const currentId = useRef<string | null>(null);
  const settled = useRef(true);

  const stop = useCallback((): void => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  }, []);

  const start = useCallback(
    (id: string): void => {
      stop();
      run.current += 1;
      const mine = run.current;
      if (!ID_RE.test(id)) {
        currentId.current = null;
        setJob(null);
        setPollError("Invalid discovery id.");
        return;
      }
      currentId.current = id;
      settled.current = false;
      let delay = POLL_MIN_MS;
      let errors = 0;
      setJob(null);
      setPollError(null);
      replaceUrl(id);

      const schedule = (next: number): void => {
        delay = next;
        timer.current = setTimeout(() => void tick(), delay);
      };
      const tick = async (): Promise<void> => {
        try {
          const latest = await getDiscovery(id);
          if (mine !== run.current) return;
          errors = 0;
          setJob(latest);
          setPollError(null);
          settled.current = latest.status !== "queued" && latest.status !== "running";
          if (latest.status === "queued" || latest.status === "running") {
            schedule(nextPollDelay(delay, POLL_MAX_MS, POLL_GROWTH));
          }
        } catch (err: unknown) {
          if (mine !== run.current) return;
          if (err instanceof Error && err.name === "AuthError") {
            setPollError(err.message);
            return;
          }
          errors += 1;
          if (errors > POLL_MAX_ERRORS) {
            setPollError(`Lost contact with the server: ${messageOf(err)}`);
            return;
          }
          schedule(Math.min(POLL_MAX_MS, delay * 2));
        }
      };
      void tick();
    },
    [stop],
  );

  const resume = useCallback((): void => {
    if (currentId.current !== null && !settled.current) start(currentId.current);
  }, [start]);

  useEffect(
    () => () => {
      run.current += 1;
      stop();
    },
    [stop],
  );

  return { job, pollError, start, resume };
}

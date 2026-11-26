import { DONE_TEXT } from "./constants";
import type { JobStep, JobView } from "./types";

export type BadgeState = "idle" | "running" | "failed" | "blocked" | "completed";

export interface StatusSummary {
  state: BadgeState;
  text: string;
}

export function summarise(job: JobView | null): StatusSummary {
  if (!job) return { state: "idle", text: "Idle" };
  if (job.status === "failed") return { state: "failed", text: "Failed" };
  if (job.status !== "completed") return { state: "running", text: "Running" };
  const bp = job.blueprint ?? {};
  const counted = bp.summary?.blockers;
  const blockers = typeof counted === "number" ? counted : (bp.blockers ?? []).length;
  const flagged = blockers > 0 || bp.stage?.status === "COMPLETED_WITH_BLOCKERS";
  if (!flagged) return { state: "completed", text: "Completed" };
  const label = blockers === 1 ? "1 blocker" : blockers > 1 ? `${blockers} blockers` : "blockers";
  return { state: "blocked", text: `Completed with ${label}` };
}

export function stepText(step: JobStep): string {
  const map: Record<string, string> = {
    pending: "Pending", running: "In progress", failed: "Failed", warning: "Completed with warnings",
  };
  if (step.status === "completed") return DONE_TEXT[step.id] ?? "Completed";
  return map[step.status] ?? step.status;
}

export function nextPollDelay(current: number, max: number, growth: number): number {
  return Math.min(max, Math.round(current * growth));
}

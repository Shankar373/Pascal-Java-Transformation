import type { ReactElement } from "react";
import { STEP_DEFS } from "../constants";
import { Icon } from "../icons";
import { stepText } from "../status";
import type { JobStep, JobView } from "../types";

interface ProgressStripProps {
  job: JobView | null;
  pollError: string | null;
  hidden: boolean;
}

const STEP_GLYPH: Readonly<Record<string, string>> = { completed: "check", warning: "warn", failed: "x" };

function placeholderSteps(): JobStep[] {
  return STEP_DEFS.map(([id, name]) => ({ id, name, status: "pending", message: "" }));
}

export function ProgressStrip({ job, pollError, hidden }: ProgressStripProps): ReactElement {
  const steps = job ? job.steps : placeholderSteps();
  const live = job
    ? `Discovery ${job.status}. ${steps.map((s) => `${s.name}: ${stepText(s)}`).join(". ")}`
    : "";
  const jobError = pollError ?? (job?.error ? `Discovery failed: ${job.error.message} (${job.error.code})` : null);
  return (
    <section className="progress-strip" id="progress-section" aria-label="Discovery progress" hidden={hidden}>
      <ol className="steps">
        {steps.map((step) => {
          const glyph = STEP_GLYPH[step.status];
          return (
            <li key={step.id} className="step" data-state={step.status} title={step.message || undefined}>
              <span className="step-icon">{glyph ? <Icon name={glyph} /> : null}</span>
              <span className="step-text"><strong>{step.name}</strong><small>{stepText(step)}</small></span>
            </li>
          );
        })}
      </ol>
      <p className="visually-hidden" aria-live="polite" role="status">{live}</p>
      <p className="job-error" role="alert" hidden={!jobError}>{jobError}</p>
    </section>
  );
}

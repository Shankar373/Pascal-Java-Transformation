import type { ReactElement } from "react";
import { Icon } from "../icons";
import type { JobView } from "../types";
import { ComponentsPanel, DialectPanel, KeyDepsPanel, ProjectInfo, Tiles } from "./BlueprintPanels";
import { BlueprintActions } from "./DownloadMenu";
import { DetailSections } from "./DetailSections";
import { Donut } from "./Donut";
import { StructurePanel } from "./StructureTree";

interface BlueprintViewProps {
  job: JobView;
  off: boolean;
  authed?: boolean;
  onCopied: (message: string) => void;
}

/** Blueprint panels plus the detail tables; rendered only for a completed job. */
export function BlueprintView({ job, off, authed = false, onCopied }: BlueprintViewProps): ReactElement | null {
  const bp = job.blueprint;
  if (job.status !== "completed" || !bp) return null;
  const blockers = bp.blockers ?? [];
  return (
    <>
      <section className={off ? "blueprint card is-off" : "blueprint card"} id="blueprint-section" aria-labelledby="bp-title">
        <div className="bp-head">
          <span className="bp-head-icon" aria-hidden="true"><Icon name="report" /></span>
          <div className="bp-head-text">
            <h2 id="bp-title">Application Blueprint</h2>
            <p>Complete analysis of the ingested Pascal application.</p>
          </div>
          <BlueprintActions key={job.id} id={job.id} authed={authed} />
        </div>
        {blockers.length ? (
          <div className="blocker-banner" role="note">
            {blockers.map((b, i) => (
              <p key={i}>{(b.code ? `${b.code}: ` : "") + (b.detail || b.message || "")}</p>
            ))}
          </div>
        ) : null}
        <div className="bp-grid">
          <ProjectInfo job={job} bp={bp} onCopied={onCopied} />
          <Tiles bp={bp} />
          <Donut distribution={bp.file_distribution} />
          <DialectPanel bp={bp} />
          <StructurePanel root={bp.structure} />
          <KeyDepsPanel bp={bp} />
          <ComponentsPanel bp={bp} />
        </div>
      </section>
      <DetailSections bp={bp} hidden={off} />
    </>
  );
}

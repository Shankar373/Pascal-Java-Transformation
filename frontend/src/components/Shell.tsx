import type { ReactElement } from "react";
import { PIPELINE_STAGES } from "../constants";
import { Icon } from "../icons";
import type { BadgeState, StatusSummary } from "../status";

const NAV_ITEMS: ReadonlyArray<readonly [string, string, boolean]> = [
  ["Dashboard", "home", false],
  ["Projects", "folder", true],
  ["Reports", "report", false],
  ["Settings", "gear", false],
];

const GLYPH: Readonly<Record<BadgeState, string>> = {
  idle: "dot", running: "dot", failed: "x", blocked: "warn", completed: "check",
};

export function TopBar(): ReactElement {
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true"><Icon name="logo" /></span>
        <span className="brand-text">Pascal-to-Java<br />Modernization Platform</span>
      </div>
      <nav className="topnav" aria-label="Primary">
        {NAV_ITEMS.map(([label, icon, current]) =>
          current ? (
            <span key={label} className="topnav-item is-current" aria-current="page">
              <Icon name={icon} /><span className="nav-label">{label}</span>
            </span>
          ) : (
            <span key={label} className="topnav-item" aria-disabled="true" title="Not available in Stage 1">
              <Icon name={icon} /><span className="nav-label">{label}</span>
            </span>
          ),
        )}
      </nav>
      <div className="topbar-tools" aria-hidden="true">
        <span className="tool-icon"><Icon name="help" /></span>
        <span className="tool-icon"><Icon name="bell" /></span>
        <span className="avatar">A</span>
      </div>
    </header>
  );
}

export function Sidebar({ state }: { state: BadgeState }): ReactElement {
  const showGlyph = state !== "idle" && state !== "running";
  return (
    <aside className="sidebar" aria-labelledby="pipeline-title">
      <h2 className="sidebar-title" id="pipeline-title">Modernization Pipeline</h2>
      <nav aria-label="Modernization pipeline">
        <ol className="stage-list">
          <li className="stage is-active" aria-current="step" id="stage-1">
            <span className="stage-marker" data-testid="stage-1-marker" data-state={state}>
              {showGlyph ? <Icon name={GLYPH[state]} /> : null}
            </span>
            <span className="stage-body">
              <span className="stage-head"><span className="stage-no">Stage 1</span></span>
              <span className="stage-name">Ingestion and Discovery</span>
            </span>
          </li>
          {PIPELINE_STAGES.map(([no, name]) => (
            <li key={no} className="stage is-planned" aria-disabled="true">
              <span className="stage-marker" />
              <span className="stage-body">
                <span className="stage-head">
                  <span className="stage-no">{no}</span><span className="stage-tag">Planned</span>
                </span>
                <span className="stage-name">{name}</span>
              </span>
            </li>
          ))}
        </ol>
      </nav>
    </aside>
  );
}

export function PageHeader({ status }: { status: StatusSummary }): ReactElement {
  return (
    <div className="page-head">
      <div className="page-head-text">
        <h1>Stage 1: Ingestion and Discovery</h1>
        <p>
          Understand the customer&apos;s entire Pascal application estate by securely ingesting the
          source, creating a checkpoint, and discovering its structure, technologies, and dependencies.
        </p>
      </div>
      <div className="stage-badge" data-state={status.state} role="status">
        <span className="badge-icon" aria-hidden="true"><Icon name={GLYPH[status.state]} /></span>
        <span>{`Stage 1 – ${status.text}`}</span>
      </div>
    </div>
  );
}

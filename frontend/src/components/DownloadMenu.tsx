import { useEffect, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent, ReactElement } from "react";
import { downloadArtifact, openReport } from "../api";
import { DOWNLOADS, ID_RE } from "../constants";
import { Icon } from "../icons";

interface ActionsProps {
  id: string;
  /** When true, links cannot carry the bearer header, so they are fetched and handed over as Blobs. */
  authed?: boolean;
}

/** Report link plus a disclosure list of download links. Renders nothing for a malformed id. */
export function BlueprintActions({ id, authed = false }: ActionsProps): ReactElement | null {
  if (!ID_RE.test(id)) return null;
  return <Actions id={id} authed={authed} />;
}

function Actions({ id, authed = false }: ActionsProps): ReactElement {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const host = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const base = `/api/discoveries/${id}`;

  useEffect(() => {
    if (!open) return undefined;
    const onClick = (ev: MouseEvent): void => {
      if (host.current && ev.target instanceof Node && !host.current.contains(ev.target)) setOpen(false);
    };
    const onKey = (ev: KeyboardEvent): void => {
      if (ev.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const intercept = (run: () => Promise<void>) => (ev: ReactMouseEvent): void => {
    if (!authed) return;
    ev.preventDefault();
    setError(null);
    setOpen(false);
    run().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "Download failed.");
    });
  };

  return (
    <div className="bp-actions">
      <a
        className="btn btn-secondary" id="btn-report" href={`${base}/report`} target="_blank" rel="noopener"
        onClick={intercept(() => openReport(`${base}/report`, "report.html"))}
      >
        <span className="btn-icon" aria-hidden="true"><Icon name="file" /></span>View Report
      </a>
      <div className="dropdown" ref={host}>
        <button
          type="button" className="btn btn-secondary" id="btn-download" ref={button}
          aria-expanded={open} aria-controls="download-menu" onClick={() => setOpen(!open)}
        >
          <span className="btn-icon" aria-hidden="true"><Icon name="download" /></span>
          Download Blueprint
          <span className="btn-icon" aria-hidden="true"><Icon name="down" /></span>
        </button>
        <ul className="menu" id="download-menu" hidden={!open}>
          {DOWNLOADS.map(([label, path]) => (
            <li key={path}>
              <a
                href={`${base}/${path}`} download=""
                onClick={intercept(() => downloadArtifact(`${base}/${path}`, label, false))}
              >{label}</a>
            </li>
          ))}
        </ul>
      </div>
      <p className="form-error" role="alert" hidden={!error}>{error}</p>
    </div>
  );
}

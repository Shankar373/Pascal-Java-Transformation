import { useEffect, useState } from "react";
import type { ReactElement } from "react";
import { listDiscoveries } from "../api";
import { SOURCE_LABEL } from "../constants";
import { DASH, fmt, fmtDate } from "../format";
import type { JobView } from "../types";

interface RecentPanelProps {
  active: boolean;
  locked?: boolean;
  onOpen: (id: string) => void;
}

const COLUMNS = ["Application", "Source", "Status", "Started", "Files", ""];

function stateName(status: string): string {
  return status === "completed" ? "completed" : status === "failed" ? "failed" : "running";
}

function Row({ item, onOpen }: { item: JobView; onOpen: (id: string) => void }): ReactElement {
  const sum = item.summary ?? {};
  const name = sum.project || item.label || item.id;
  return (
    <tr>
      <td>{name}</td>
      <td>{SOURCE_LABEL[item.kind ?? ""] ?? item.kind ?? DASH}</td>
      <td><span className={`pill st-${stateName(item.status)}`}>{item.status}</span></td>
      <td>{fmtDate(item.created_at)}</td>
      <td>{fmt(sum.total_files)}</td>
      <td>
        <button type="button" className="btn btn-small" aria-label={`Open discovery ${sum.project || item.id}`}
          onClick={() => onOpen(item.id)}>Open</button>
      </td>
    </tr>
  );
}

export function RecentPanel({ active, locked = false, onOpen }: RecentPanelProps): ReactElement {
  const [items, setItems] = useState<JobView[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!active || locked) return undefined;
    let cancelled = false;
    setError(null);
    listDiscoveries().then(
      (data) => {
        if (cancelled) return;
        setItems(data.items ?? []);
        setLoaded(true);
      },
      (err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Unexpected error.");
      },
    );
    return () => { cancelled = true; };
  }, [active, locked]);

  const shownError = error ?? (active && locked ? "Enter an access token to load discoveries." : null);
  const empty = loaded && items.length === 0;
  return (
    <section className="panel-recent card" id="panel-recent" role="tabpanel" tabIndex={0} aria-labelledby="tab-recent" hidden={!active}>
      <h2 className="section-title">Recent Discoveries</h2>
      <p className="muted" hidden={!empty}>No discoveries yet. Ingest an application to create one.</p>
      <div className="table-wrap" hidden={empty}>
        <table className="data-table">
          <caption className="visually-hidden">Recent discoveries, newest first</caption>
          <thead><tr>{COLUMNS.map((c, i) => <th key={i} scope="col">{c}</th>)}</tr></thead>
          <tbody>{items.map((it) => <Row key={it.id} item={it} onOpen={onOpen} />)}</tbody>
        </table>
      </div>
      <p className="form-error" role="alert" hidden={!shownError}>{shownError}</p>
    </section>
  );
}

import type { ReactElement, ReactNode } from "react";
import { DASH, MAX_ROWS } from "../format";

export interface Column<T> {
  label: string;
  title?: string;
  get: (row: T) => ReactNode;
}

interface DataTableProps<T> {
  columns: ReadonlyArray<Column<T>>;
  rows: readonly T[];
}

function cell(value: ReactNode): ReactNode {
  return value === undefined || value === null || value === "" ? DASH : value;
}

export function DataTable<T>({ columns, rows }: DataTableProps<T>): ReactElement {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>{columns.map((c) => <th key={c.label} scope="col" title={c.title}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, MAX_ROWS).map((row, i) => (
            <tr key={i}>{columns.map((c) => <td key={c.label}>{cell(c.get(row))}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {rows.length > MAX_ROWS ? (
        <p className="muted">
          {`Showing the first ${MAX_ROWS} of ${rows.length} rows. The full data is in the downloads.`}
        </p>
      ) : null}
    </div>
  );
}

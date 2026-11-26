import type { Evidence } from "./types";

export const DASH = "—";
export const MAX_ROWS = 200;

export function fmt(n: unknown): string {
  return typeof n === "number" ? n.toLocaleString("en-US") : DASH;
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString("en-GB", {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function evShort(list: Evidence[] | undefined | null): string {
  const first = Array.isArray(list) && list.length > 0 ? list[0] : undefined;
  if (!first || !first.file) return DASH;
  return first.file + (first.line ? `:${first.line}` : "");
}

export function listCell(items: unknown): string {
  return Array.isArray(items) && items.length > 0 ? items.join(", ") : DASH;
}

export function yesNo(value: unknown): string {
  return value ? "Yes" : "No";
}

/** Returns an error message, or null when the file is acceptable. */
export function validateZip(file: File, maxBytes: number): string | null {
  if (!/\.zip$/i.test(file.name)) return "The file must be a .zip archive.";
  if (maxBytes && file.size > maxBytes) {
    return `The file is larger than the server limit of ${fmtBytes(maxBytes)}.`;
  }
  return null;
}

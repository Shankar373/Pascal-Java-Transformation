import { useRef } from "react";
import type { KeyboardEvent, ReactElement } from "react";
import { Icon } from "../icons";

export type TabName = "ingest" | "recent";

interface TabsProps {
  active: TabName;
  onSelect: (tab: TabName) => void;
}

const ORDER: readonly TabName[] = ["ingest", "recent"];

function targetTab(key: string, current: TabName): TabName | null {
  const index = ORDER.indexOf(current);
  const size = ORDER.length;
  if (key === "Home") return ORDER[0] ?? null;
  if (key === "End") return ORDER[size - 1] ?? null;
  if (key === "ArrowRight") return ORDER[(index + 1) % size] ?? null;
  if (key === "ArrowLeft") return ORDER[(index - 1 + size) % size] ?? null;
  return null;
}

export function Tabs({ active, onSelect }: TabsProps): ReactElement {
  const refs = useRef<Record<TabName, HTMLButtonElement | null>>({ ingest: null, recent: null });

  const onKey = (current: TabName) => (ev: KeyboardEvent<HTMLButtonElement>): void => {
    const next = targetTab(ev.key, current);
    if (!next) return;
    ev.preventDefault();
    onSelect(next);
    refs.current[next]?.focus();
  };

  const tab = (name: TabName, label: string, icon: string): ReactElement => {
    const selected = active === name;
    return (
      <button
        type="button" role="tab" id={`tab-${name}`} aria-controls={`panel-${name}`}
        className={selected ? "tab is-selected" : "tab"} aria-selected={selected}
        tabIndex={selected ? 0 : -1}
        ref={(el) => { refs.current[name] = el; }}
        onClick={() => onSelect(name)} onKeyDown={onKey(name)}
      >
        <Icon name={icon} /><span className="tab-label">{label}</span>
      </button>
    );
  };

  return (
    <div className="tabs" role="tablist" aria-label="Stage 1 views">
      {tab("ingest", "Ingest Application", "upload")}
      {tab("recent", "Recent Discoveries", "calendar")}
    </div>
  );
}

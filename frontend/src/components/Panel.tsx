import type { ReactElement, ReactNode } from "react";
import { Icon } from "../icons";

interface PanelProps {
  title: string;
  icon: string;
  cls: string;
  children: ReactNode;
}

export function Panel({ title, icon, cls, children }: PanelProps): ReactElement {
  return (
    <section className={`panel ${cls}`}>
      <header className="panel-head">
        <span className="panel-icon" aria-hidden="true"><Icon name={icon} /></span>
        <h3>{title}</h3>
      </header>
      {children}
    </section>
  );
}

interface CopyButtonProps {
  value: string;
  label: string;
  onCopied: (message: string) => void;
}

function fallbackCopy(value: string, done: () => void): void {
  const area = document.createElement("textarea");
  area.className = "visually-hidden";
  area.value = value;
  area.setAttribute("aria-hidden", "true");
  area.tabIndex = -1;
  document.body.appendChild(area);
  area.select();
  try {
    if (document.execCommand("copy")) done();
  } catch {
    /* clipboard unavailable: nothing more to try */
  }
  area.remove();
}

export function CopyButton({ value, label, onCopied }: CopyButtonProps): ReactElement {
  const done = (): void => onCopied(`${label} copied`);
  const copy = (): void => {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(done, () => fallbackCopy(value, done));
    } else {
      fallbackCopy(value, done);
    }
  };
  return (
    <button type="button" className="icon-btn" aria-label={`Copy ${label}`} title={`Copy ${label}`} onClick={copy}>
      <Icon name="copy" />
    </button>
  );
}

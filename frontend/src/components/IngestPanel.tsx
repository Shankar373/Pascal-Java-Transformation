import { useRef, useState } from "react";
import type { ReactElement } from "react";
import { createDiscovery, uploadZip } from "../api";
import { fmtBytes, validateZip } from "../format";
import { Icon } from "../icons";
import type { Accepted, AppConfig } from "../types";
import { DirectoryForm, GitForm, ZipForm } from "./IngestForms";

type SourceKind = "git" | "zip" | "directory";

interface IngestPanelProps {
  config: AppConfig;
  configError: string | null;
  hidden: boolean;
  locked?: boolean;
  onAccepted: (id: string) => void;
}

const LOCKED_MESSAGE = "Enter an access token before starting a discovery.";
const ZIP_PROMPT = "Drag a .zip file here, or press Enter to choose one";
const DIR_DISABLED_WHY = "Disabled: start the server with --allow-local-root to enable local directories.";

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : "Unexpected error.";
}

interface SourceCardProps {
  kind: SourceKind;
  selected: boolean;
  disabled?: boolean;
  title: string;
  hint: string;
  icon: string;
  onSelect: (kind: SourceKind) => void;
}

function SourceCard(props: SourceCardProps): ReactElement {
  const { kind, selected, disabled = false, title, hint, icon, onSelect } = props;
  const cls = ["source-card", selected ? "is-selected" : "", disabled ? "is-disabled" : ""]
    .filter(Boolean).join(" ");
  return (
    <label className={cls} id={`card-${kind}`} title={disabled ? DIR_DISABLED_WHY : undefined}>
      <input
        type="radio" name="source" value={kind} id={`radio-${kind}`}
        checked={selected} disabled={disabled} onChange={() => onSelect(kind)}
      />
      <span className="radio-dot" aria-hidden="true" />
      <span className="source-icon" aria-hidden="true"><Icon name={icon} /></span>
      <span className="source-text"><strong>{title}</strong><small>{hint}</small></span>
    </label>
  );
}

export function IngestPanel({ config, configError, hidden, locked = false, onAccepted }: IngestPanelProps): ReactElement {
  const [kind, setKind] = useState<SourceKind>("git");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const inFlight = useRef(false);
  const dirEnabled = Boolean(config.local_directory_enabled);
  const shownError = error || configError;

  const submit = async (work: () => Promise<Accepted>): Promise<void> => {
    if (inFlight.current) return;
    if (locked) {
      setError(LOCKED_MESSAGE);
      return;
    }
    inFlight.current = true;
    setError("");
    setBusy(true);
    try {
      const accepted = await work();
      onAccepted(accepted.id);
    } catch (err: unknown) {
      setError(errorText(err));
    } finally {
      inFlight.current = false;
      setBusy(false);
      setProgress(null);
    }
  };

  const chooseZip = (file: File | undefined): void => {
    setError("");
    if (!file) return;
    const problem = validateZip(file, config.max_upload_bytes);
    if (problem) {
      setError(problem);
      return;
    }
    setZipFile(file);
  };

  const submitZip = (): void => {
    if (!zipFile) {
      setError("Choose a ZIP file first.");
      return;
    }
    void submit(() => {
      setProgress(0);
      return uploadZip(zipFile, (fraction) => setProgress(Math.round(fraction * 100)));
    });
  };

  const select = (next: SourceKind): void => {
    setKind(next);
    setError("");
  };

  return (
    <section className="panel-ingest card" id="panel-ingest" role="tabpanel" tabIndex={0} aria-labelledby="tab-ingest" hidden={hidden}>
      <fieldset className="sources">
        <legend className="visually-hidden">Application source</legend>
        <SourceCard kind="git" selected={kind === "git"} title="Git Repository" icon="diamond"
          hint="Ingest from a Git repository (HTTPS/SSH)" onSelect={select} />
        <SourceCard kind="zip" selected={kind === "zip"} title="ZIP Archive" icon="zip"
          hint="Upload a ZIP file of the application" onSelect={select} />
        <SourceCard kind="directory" selected={kind === "directory"} disabled={!dirEnabled}
          title="Local Directory" icon="folder" onSelect={select}
          hint={dirEnabled ? "Ingest from a local project directory" : "Disabled by server configuration"} />
      </fieldset>

      <GitForm hidden={kind !== "git"} busy={busy} onInvalid={setError}
        onSubmit={(url, ref) => void submit(() => createDiscovery({ kind: "git", url, ref: ref || null }))} />
      <ZipForm hidden={kind !== "zip"} busy={busy} progress={progress}
        fileLabel={zipFile ? `${zipFile.name} (${fmtBytes(zipFile.size)})` : ZIP_PROMPT}
        onChoose={chooseZip} onSubmit={submitZip} />
      <DirectoryForm hidden={kind !== "directory"} busy={busy} onInvalid={setError}
        onSubmit={(path) => void submit(() => createDiscovery({ kind: "directory", path }))} />

      <p className="form-error" id="ingest-error" role="alert" hidden={!shownError}>{shownError}</p>
    </section>
  );
}

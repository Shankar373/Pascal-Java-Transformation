import { useRef, useState } from "react";
import type { DragEvent, FormEvent, KeyboardEvent, ReactElement } from "react";
import { Icon } from "../icons";

interface FormCommon {
  hidden: boolean;
  busy: boolean;
}

const SubmitButton = ({ id, busy }: { id: string; busy: boolean }): ReactElement => (
  <button type="submit" className="btn btn-primary" id={id} disabled={busy}>
    <span className="btn-icon" aria-hidden="true"><Icon name="play" /></span>
    Ingest &amp; Discover
  </button>
);

interface GitFormProps extends FormCommon {
  onSubmit: (url: string, ref: string) => void;
  onInvalid: (message: string) => void;
}

export function GitForm({ hidden, busy, onSubmit, onInvalid }: GitFormProps): ReactElement {
  const [url, setUrl] = useState("");
  const [ref, setRef] = useState("");
  const urlInput = useRef<HTMLInputElement>(null);

  const submit = (ev: FormEvent): void => {
    ev.preventDefault();
    const trimmed = url.trim();
    if (!trimmed) {
      onInvalid("Enter a repository URL.");
      urlInput.current?.focus();
      return;
    }
    onSubmit(trimmed, ref.trim());
  };

  return (
    <form className="source-form" id="form-git" hidden={hidden} noValidate onSubmit={submit}>
      <div className="field field-url">
        <label htmlFor="repo-url">Repository URL <span className="req" aria-hidden="true">*</span></label>
        <input
          type="text" id="repo-url" name="url" required autoComplete="off" spellCheck={false}
          placeholder="https://git.example.com/org/application.git" aria-describedby="ingest-error"
          ref={urlInput} value={url} onChange={(e) => setUrl(e.target.value)}
        />
      </div>
      <div className="field field-ref">
        <label htmlFor="repo-ref">Branch / Ref</label>
        <input
          type="text" id="repo-ref" name="ref" list="ref-suggestions" autoComplete="off"
          spellCheck={false} placeholder="default branch" value={ref}
          onChange={(e) => setRef(e.target.value)}
        />
        <datalist id="ref-suggestions">
          <option value="main" /><option value="master" /><option value="develop" />
        </datalist>
      </div>
      <SubmitButton id="btn-git" busy={busy} />
    </form>
  );
}

interface DirectoryFormProps extends FormCommon {
  onSubmit: (path: string) => void;
  onInvalid: (message: string) => void;
}

export function DirectoryForm({ hidden, busy, onSubmit, onInvalid }: DirectoryFormProps): ReactElement {
  const [path, setPath] = useState("");
  const submit = (ev: FormEvent): void => {
    ev.preventDefault();
    const trimmed = path.trim();
    if (!trimmed) {
      onInvalid("Enter a directory path.");
      return;
    }
    onSubmit(trimmed);
  };
  return (
    <form className="source-form" id="form-directory" hidden={hidden} noValidate onSubmit={submit}>
      <div className="field field-url">
        <label htmlFor="dir-path">Directory path <span className="req" aria-hidden="true">*</span></label>
        <input
          type="text" id="dir-path" name="path" autoComplete="off" spellCheck={false}
          placeholder="Path inside an allowed local root" value={path}
          onChange={(e) => setPath(e.target.value)}
        />
      </div>
      <SubmitButton id="btn-directory" busy={busy} />
    </form>
  );
}

interface ZipFormProps extends FormCommon {
  fileLabel: string;
  progress: number | null;
  onChoose: (file: File | undefined) => void;
  onSubmit: () => void;
}

export function ZipForm(props: ZipFormProps): ReactElement {
  const { hidden, busy, fileLabel, progress, onChoose, onSubmit } = props;
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const openChooser = (): void => input.current?.click();
  const onKey = (ev: KeyboardEvent): void => {
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      openChooser();
    }
  };
  const onOver = (ev: DragEvent): void => {
    ev.preventDefault();
    setOver(true);
  };
  const onLeave = (ev: DragEvent): void => {
    ev.preventDefault();
    setOver(false);
  };
  const onDrop = (ev: DragEvent): void => {
    onLeave(ev);
    onChoose(ev.dataTransfer?.files?.[0]);
  };

  return (
    <form
      className="source-form" id="form-zip" hidden={hidden} noValidate
      onSubmit={(ev) => { ev.preventDefault(); onSubmit(); }}
    >
      <div className="field field-drop">
        <span className="field-label" id="zip-label">ZIP archive <span className="req" aria-hidden="true">*</span></span>
        <div
          className={over ? "dropzone is-over" : "dropzone"} id="zip-drop" tabIndex={0} role="button"
          aria-labelledby="zip-label zip-name" onClick={openChooser} onKeyDown={onKey}
          onDragEnter={onOver} onDragOver={onOver} onDragLeave={onLeave} onDrop={onDrop}
        >
          <span className="dropzone-icon" aria-hidden="true"><Icon name="upload" /></span>
          <span className="dropzone-text" id="zip-name">{fileLabel}</span>
        </div>
        <input
          type="file" id="zip-input" data-testid="zip-input" accept=".zip,application/zip"
          className="visually-hidden" tabIndex={-1} ref={input}
          onChange={(e) => onChoose(e.target.files?.[0])}
        />
        <progress id="zip-progress" max={100} value={progress ?? 0} hidden={progress === null} aria-label="Upload progress" />
      </div>
      <SubmitButton id="btn-zip" busy={busy} />
    </form>
  );
}

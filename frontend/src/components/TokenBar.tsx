import { useState } from "react";
import type { FormEvent, ReactElement } from "react";

interface TokenBarProps {
  hasToken: boolean;
  onApply: (token: string | null) => void;
}

/** Collects the optional tenant access token. It is held in memory only (see api.ts). */
export function TokenBar({ hasToken, onApply }: TokenBarProps): ReactElement {
  const [value, setValue] = useState("");

  const submit = (ev: FormEvent): void => {
    ev.preventDefault();
    if (!value.trim()) return;
    onApply(value);
    setValue("");
  };

  return (
    <section className="card token-bar">
      <form className="token-form" onSubmit={submit} noValidate>
        <div className="field">
          <label htmlFor="access-token">Access token</label>
          <input
            type="password" id="access-token" name="access-token" autoComplete="off" spellCheck={false}
            placeholder={hasToken ? "Token set for this session" : "Required by this server"}
            value={value} onChange={(e) => setValue(e.target.value)}
          />
        </div>
        <button type="submit" className="btn btn-secondary">Use token</button>
        {hasToken ? (
          <button type="button" className="btn btn-secondary" onClick={() => onApply(null)}>Clear token</button>
        ) : null}
      </form>
      <p className="muted" role="status">
        {hasToken ? "Access token is set (kept in memory only)." : "Enter your access token to start or view discoveries."}
      </p>
    </section>
  );
}

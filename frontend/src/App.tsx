import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactElement } from "react";
import { getConfig, setToken, subscribeToken } from "./api";
import { BlueprintView } from "./components/Blueprint";
import { IngestPanel } from "./components/IngestPanel";
import { ProgressStrip } from "./components/ProgressStrip";
import { RecentPanel } from "./components/RecentPanel";
import { PageHeader, Sidebar, TopBar } from "./components/Shell";
import { Tabs } from "./components/Tabs";
import { TokenBar } from "./components/TokenBar";
import type { TabName } from "./components/Tabs";
import { ID_RE } from "./constants";
import { useDiscovery } from "./hooks/useDiscovery";
import { summarise } from "./status";
import type { AppConfig } from "./types";

const ANNOUNCE_DELAY_MS = 50;
const DEFAULT_CONFIG: AppConfig = { local_directory_enabled: false, ssh_enabled: false, max_upload_bytes: 0 };

export default function App(): ReactElement {
  const [tab, setTab] = useState<TabName>("ingest");
  const [config, setConfig] = useState<AppConfig>(DEFAULT_CONFIG);
  const [configError, setConfigError] = useState<string | null>(null);
  const [copied, setCopied] = useState("");
  const { job, pollError, start, resume } = useDiscovery();
  const announceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const previousToken = useRef<string | null>(null);

  const [configReady, setConfigReady] = useState(false);
  const [token, setTokenState] = useState<string | null>(null);
  const deepLinkDone = useRef(false);

  useEffect(() => subscribeToken(setTokenState), []);

  useEffect(() => {
    getConfig()
      .then(setConfig, (err: unknown) => {
        setConfigError(err instanceof Error ? err.message : "Unexpected error.");
      })
      .finally(() => setConfigReady(true));
  }, []);

  const locked = Boolean(config.auth_required) && token === null;

  // Declared before the deep-link effect: a token entered for the first time restarts an existing
  // unsettled job here, while the deep-link effect below starts a fresh one without double polling.
  useEffect(() => {
    if (previousToken.current === null && token !== null) resume();
    previousToken.current = token;
  }, [token, resume]);

  useEffect(() => () => {
    if (announceTimer.current !== null) clearTimeout(announceTimer.current);
  }, []);

  // Clear then set, so screen readers re-announce an identical message on repeat copies.
  const announce = useCallback((message: string): void => {
    setCopied("");
    if (announceTimer.current !== null) clearTimeout(announceTimer.current);
    announceTimer.current = setTimeout(() => setCopied(message), ANNOUNCE_DELAY_MS);
  }, []);

  useEffect(() => {
    if (!configReady || locked || deepLinkDone.current) return;
    deepLinkDone.current = true;
    const wanted = new URLSearchParams(window.location.search).get("job");
    if (wanted && ID_RE.test(wanted)) start(wanted);
  }, [configReady, locked, start]);

  const status = summarise(job);
  const ingest = tab === "ingest";
  const open = (id: string): void => {
    setTab("ingest");
    start(id);
  };

  return (
    <>
      <a className="skip-link" href="#main">Skip to main content</a>
      <TopBar />
      <div className="shell">
        <Sidebar state={status.state} />
        <main className="main" id="main" tabIndex={-1}>
          <PageHeader status={status} />
          {config.auth_required ? <TokenBar hasToken={token !== null} onApply={setToken} /> : null}
          <Tabs active={tab} onSelect={setTab} />
          <IngestPanel config={config} configError={configError} hidden={!ingest} locked={locked} onAccepted={start} />
          <RecentPanel active={!ingest} locked={locked} onOpen={open} />
          <ProgressStrip job={job} pollError={pollError} hidden={!ingest} />
          {job ? <BlueprintView job={job} off={!ingest} authed={token !== null} onCopied={announce} /> : null}
          <p className="visually-hidden" aria-live="polite" role="status">{copied}</p>
        </main>
      </div>
    </>
  );
}

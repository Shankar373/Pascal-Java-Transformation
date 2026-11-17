"""Secure Git ingestion (task B2, plan §4.4).

Threat model for a Git input
----------------------------

A repository is attacker-controlled content.  The three ways a checkout can
hurt us are *escaping the staging tree* (symlinks), *running code* (hooks,
submodules, smudge filters) and *reading the operator's credentials*
(credential helpers, SSH agents, interactive prompts).  All three are closed
by construction:

* **No execution.**  The only subprocess is ``git`` itself, with a fixed
  argument vector, ``shell=False``, a hardened environment and a timeout.
  No file from the repository is ever executed, imported or passed to a shell.
* **No escape.**  ``git ls-tree`` is inspected *before* the working tree is
  trusted: symlinks (mode ``120000``) and submodules/gitlinks (mode
  ``160000``) are refused outright.  ``core.symlinks=false`` is a second,
  independent guard.
* **No credential use.**  System and global config are disabled, ``HOME`` is
  redirected into staging, interactive prompting is turned off, and the
  default input is a **local path or ``file://`` URL only** — network cloning
  is refused (documented as ``UNSUPPORTED``), because a remote clone is
  neither reproducible nor credential-free.

Byte preservation is forced with ``core.autocrlf=false`` so the staged bytes
are the committed bytes on any host, which is what makes re-ingestion
byte-identical.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .errors import (
    DiagnosticSink,
    IngestionError,
    UnsupportedInputError,
)
from .limits import DEFAULT_LIMITS, Limits
from .model import IngestionResult, ingest_directory, rmtree_force

__all__ = ["ingest_git", "resolve_git_source"]

#: Pinned commit: 7–40 lowercase/uppercase hex characters (abbreviated ok).
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")

#: Remote URL schemes refused by default.
_REMOTE_SCHEMES = ("http://", "https://", "ssh://", "git://", "ftps://", "sftp://")

#: Hard cap on any single git invocation, so a pathological repo cannot hang
#: a pipeline run indefinitely.
_GIT_TIMEOUT_SECONDS = 300


def resolve_git_source(source: str) -> tuple[str, str]:
    """Classify *source* as ``("local", path)`` or raise.

    ``file://`` URLs are local paths with a scheme; everything else is remote
    and refused.  Returns ``(kind, value)`` where *kind* is ``"local"``.
    """

    text = source.strip()
    if not text:
        raise UnsupportedInputError("empty git source", code="INPUT_NOT_FOUND")

    lowered = text.lower()
    for scheme in _REMOTE_SCHEMES:
        if lowered.startswith(scheme):
            raise UnsupportedInputError(
                f"remote git source refused ({scheme.strip('://')}); P1 "
                "ingests local repositories and file:// URLs only, because a "
                "network clone is not reproducible and can reach credential "
                "helpers. Network input is UNSUPPORTED in P1.",
                code="REMOTE_INPUT_UNSUPPORTED",
                path=text,
            )
    if lowered.startswith("file://"):
        path = _file_url_to_path(text)
        return "local", path
    if re.match(r"^[a-z0-9]+@[^:]+:", text) or text.startswith("git@"):
        raise UnsupportedInputError(
            "scp-style SSH git source refused; network input is UNSUPPORTED "
            "in P1",
            code="REMOTE_INPUT_UNSUPPORTED",
            path=text,
        )
    return "local", text


def _file_url_to_path(url: str) -> str:
    """Minimal ``file://`` → path conversion (no network, no decoding surprises)."""

    rest = url[7:]
    if rest.startswith("localhost/") or rest.startswith("LOCALHOST/"):
        rest = rest[9:]
    if rest.startswith("/") and re.match(r"^/[A-Za-z]:", rest):
        rest = rest[1:]  # file:///C:/x → /C:/x → C:/x
    # Percent-decoding is deliberately limited to the characters that are
    # illegal in a Windows path but legal in a URL.
    for ch, repl in (("%20", " "), ("%23", "#"), ("%25", "%")):
        rest = rest.replace(ch, repl)
    if rest.startswith("/") and len(rest) > 2 and rest[2] == ":":
        rest = rest[1:]
    return rest


def _hardened_env(staging: Path) -> dict[str, str]:
    """Environment in which git cannot see credentials or user configuration."""

    home = staging / ".p1-home"
    home.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    # Drop anything that points git at an existing repository or worktree.
    for key in list(env):
        if key.startswith("GIT_") and key not in (
            "GIT_EXEC_PATH",  # harmless: locates the git binary's helpers
        ):
            env.pop(key, None)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = str(home / "no-such-gitconfig")
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "true"  # non-interactive "password" source
    env["GIT_SSH_COMMAND"] = "true"  # ssh would otherwise prompt
    env["GIT_EDITOR"] = "true"
    env["GIT_PAGER"] = "cat"
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    env["MSYS_NO_PATHCONV"] = "1"  # stop MSYS from rewriting path arguments
    return env


def _git(
    args: list[str],
    env: dict[str, str],
    *,
    cwd: Path | None = None,
    what: str = "git",
) -> subprocess.CompletedProcess[str]:
    """Run git with a fixed vector: no shell, captured output, hard timeout."""

    cmd = ["git", *args]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise UnsupportedInputError(
            "git executable not found on PATH; Git input is UNAVAILABLE",
            code="GIT_UNAVAILABLE",
        ) from None
    except subprocess.TimeoutExpired:
        raise IngestionError(
            f"git {what} exceeded {_GIT_TIMEOUT_SECONDS}s",
            code="GIT_TIMEOUT",
        ) from None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        first = detail[0] if detail else f"exit {proc.returncode}"
        raise IngestionError(
            f"git {what} failed: {first}",
            code="GIT_FAILED",
        )
    return proc


def _rev_parse(dest: Path, env: dict[str, str], expr: str, label: str = "") -> str:
    """Resolve *expr* to a full object name, with P1-specific failure codes."""

    try:
        proc = _git(
            ["rev-parse", "--verify", expr], env, cwd=dest, what="rev-parse"
        )
    except IngestionError:
        if expr == "HEAD":
            raise UnsupportedInputError(
                "repository has no commits (HEAD is unborn); nothing to ingest",
                code="EMPTY_REPOSITORY",
            ) from None
        raise UnsupportedInputError(
            f"commit {label or expr!r} is not present in the repository",
            code="COMMIT_NOT_FOUND",
            path=label or expr,
        ) from None
    return proc.stdout.strip()


def ingest_git(
    source: str,
    staging: Path,
    *,
    commit: str | None = None,
    limits: Limits = DEFAULT_LIMITS,
    sink: DiagnosticSink | None = None,
) -> IngestionResult:
    """Clone *source* into *staging*, verify the pinned commit, inventory it.

    *staging* must be a fresh directory the caller owns and can discard.
    """

    staging = Path(staging).resolve()
    sink = sink or DiagnosticSink(limits.max_diagnostics)

    kind, location = resolve_git_source(source)
    assert kind == "local"

    repo_path = Path(location)
    if not repo_path.exists():
        raise UnsupportedInputError(
            f"git repository path not found: {location}",
            code="INPUT_NOT_FOUND",
            path=location,
        )
    if not repo_path.is_dir():
        raise UnsupportedInputError(
            f"git source is not a directory: {location}",
            code="NOT_A_GIT_REPOSITORY",
            path=location,
        )

    if commit is not None and not _COMMIT_RE.match(commit):
        raise UnsupportedInputError(
            f"commit {commit!r} is not a 7–40 character hexadecimal object "
            "name; P1 pins a commit, not a branch or tag",
            code="INVALID_COMMIT_PIN",
            path=commit,
        )

    env = _hardened_env(staging)
    template = staging / ".p1-empty-template"
    template.mkdir(parents=True, exist_ok=True)
    # Point hooks at a directory that does not exist: no hook can be found,
    # let alone executed.  (A template-relative path would be enough, but a
    # second, independent guard costs nothing.)
    no_hooks = staging / ".p1-no-hooks"
    dest = staging / "repo"

    # --- Clone without checking anything out. ------------------------------
    try:
        _git(
            [
                "clone",
                "--no-checkout",
                "--no-recurse-submodules",
                "--no-local",  # full object copy: no hardlink into user data
                f"--template={template}",
                "--",
                location,
                str(dest),
            ],
            env,
            what="clone",
        )
    except IngestionError as exc:
        if exc.code == "GIT_FAILED":
            raise UnsupportedInputError(
                f"could not clone {location!r}: {exc.message}",
                code="NOT_A_GIT_REPOSITORY",
                path=location,
            ) from None
        raise

    # --- Resolve the pin and check it out. --------------------------------
    if commit is None:
        pinned = _rev_parse(dest, env, "HEAD")
    else:
        pinned = _rev_parse(dest, env, f"{commit}^{{commit}}", commit)

    # Byte-preserving checkout: never convert line endings, never create
    # symlinks, never follow file-mode bits from a foreign filesystem.
    checkout_args = [
        "-c",
        "core.autocrlf=false",
        "-c",
        "core.safecrlf=false",
        "-c",
        "core.symlinks=false",
        "-c",
        "core.filemode=false",
        "-c",
        f"core.hooksPath={no_hooks}",
        "-C",
        str(dest),
        "checkout",
        "--detach",
        "--force",
        pinned,
    ]
    try:
        _git(checkout_args, env, what="checkout")
    except IngestionError as exc:
        raise UnsupportedInputError(
            f"could not check out {pinned}: {exc.message}",
            code="CHECKOUT_FAILED",
            path=pinned,
        ) from None

    # --- Verify the pin actually landed. ----------------------------------
    actual = _git(
        ["rev-parse", "HEAD"], env, cwd=dest, what="rev-parse"
    ).stdout.strip()
    if actual.lower() != pinned.lower():
        raise IngestionError(
            f"checked out {actual} but pinned {pinned}",
            code="COMMIT_MISMATCH",
            path=pinned,
        )

    # --- Inspect the tree before trusting it. -----------------------------
    _reject_unsafe_modes(dest, pinned, env)

    # Commit time is source-derived and therefore reproducible.
    commit_timestamp = _git(
        ["show", "-s", "--format=%cI", pinned], env, cwd=dest, what="show"
    ).stdout.strip()

    # The clone's own metadata carries hooks and packed objects we neither
    # need nor want in the inventory; remove it so the staged tree is source.
    # `rmtree_force` matters here: git stores pack files read-only, and a
    # plain rmtree would silently leave `.git/objects` behind on Windows.
    git_dir = dest / ".git"
    if git_dir.exists():
        rmtree_force(git_dir)
        sink.info(
            "VCS_METADATA_REMOVED",
            ".git removed from staging after commit verification; repository "
            "content is inventoried, version-control metadata is not",
        )

    result = ingest_directory(
        dest,
        origin=source,
        kind="git",
        sink=sink,
        limits=limits,
    )
    result.commit = pinned
    result.commit_timestamp = commit_timestamp
    result.diagnostics = sink.to_list()
    return result


def _reject_unsafe_modes(dest: Path, pinned: str, env: dict[str, str]) -> None:
    """Refuse symlinks and submodules found in the pinned tree.

    Runs on ``ls-tree`` output — the authoritative record of what the commit
    contains — rather than on whatever the working tree happens to look like
    after checkout.
    """

    proc = _git(
        ["ls-tree", "-r", "-z", "--full-tree", pinned],
        env,
        cwd=dest,
        what="ls-tree",
    )
    for record in proc.stdout.split("\0"):
        if not record:
            continue
        try:
            meta, name = record.split("\t", 1)
        except ValueError:  # pragma: no cover - malformed record
            continue
        mode = meta.split(" ", 1)[0]
        if mode == "120000":
            raise IngestionError(
                f"symlink entry refused in repository tree: {name}",
                code="SYMLINK_ENTRY",
                path=name,
            )
        if mode == "160000":
            raise IngestionError(
                f"submodule/gitlink entry refused (submodules are never "
                f"recursed): {name}",
                code="SUBMODULE_ENTRY",
                path=name,
            )

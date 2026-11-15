# ADR 0005: No-LLM / no-probabilistic CI gate

- **Status:** Accepted
- **Date:** 2026-11-13
- **Phase:** P0 (rule adopted now; enforcement wired into CI in P1 as task E3)
- **Source of truth:** master prompt, *Non-negotiable engineering rules* and
  *Required tests and CI gates* #11; README *AI/LLM policy (hard rule)*

## Context

This platform's core promise is **evidence-based, deterministic certification**
of behavioural equivalence. That promise is void if any probabilistic step can
influence a detection, planning, transformation or verdict decision.

Two distinct risks must be closed:

1. **Product risk** — an LLM, embedding model, vector store or inference
   endpoint creeping into shipped dependencies or deployment manifests.
2. **Process risk** — a development-time assistant (OpenCode/ECC, and this
   agent) being treated as part of the product, or its output being accepted as
   evidence without deterministic verification.

Development-time authoring assistants are explicitly permitted — they are
*tools used to write the product*, not *parts of the product*. The gate exists
to keep that boundary mechanical rather than aspirational.

## Decision

### 1. Product boundary (hard fail)

CI **must fail** if any of the following appear in **product dependencies or
deployment manifests**:

- model SDKs (e.g. OpenAI, Anthropic, Gemini, or any vendor AI client);
- embedding packages;
- vector-store / RAG store packages;
- AI endpoints or model endpoints;
- model-weight files (`.onnx`, `.pt`, `.pth`, `.safetensors`, `.gguf`, `.h5`,
  `.tflite`, `.pb`, …) or inference configuration;
- ML-based dialect classifiers or probabilistic converters.

### 2. Decision boundary (hard fail)

Every detection, planning, transformation and verdict decision must be
**deterministic**: parsers, compiler metadata, static analysis, exact rules,
typed intermediate representations and reproducible execution. A decision that
cannot be reproduced from recorded inputs is a defect, not a feature.

### 3. Development-time assistants (permitted, bounded)

OpenCode/ECC and similar assistants may be used to author code and docs. Their
output **never** constitutes evidence. Only a recorded, reproducible command
and its captured output may be cited — which is why every claim in
`docs/p0/` points at an evidence file rather than at a conversation.

### 4. Vocabulary that must not appear as a decision mechanism

"Likely", "probably", "seems to be", "based on training", or an unexplained
score must never be the justification for a capability state. Capability states
are `SUPPORTED` / `PARTIAL` / `UNSUPPORTED` / `UNAVAILABLE` / `UNKNOWN` /
`BLOCKED`, and only `VERIFIED` after original-vs-Java tests — a parse pass is
`NOT_VERIFIED`.

## Consequences

- **The gate is mechanical, not a review checklist.** It scans dependency
  manifests and deployment descriptors; a human cannot forget to apply it.
- **False positives are acceptable; false negatives are not.** A blocked build
  that turns out to be a legitimate dependency is a cheap conversation; a model
  SDK reaching production silently is not.
- **Evidence discipline is the enforceable form of the policy.** Because every
  P0 deliverable cites an evidence file, "where did this number come from?" is
  always answerable without asking an assistant.
- **P1 task E3** implements this gate; until then the rule is adopted but not
  yet mechanically enforced.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Rely on code review to catch AI dependencies | Review is probabilistic (human attention); the requirement is a *hard* gate. |
| Ban all assistants, including development-time | Not required by the prompt and would discard legitimate authoring tooling; the boundary that matters is the *shipped product*. |
| Ban only "generative" models but allow embeddings | Embeddings + vector stores are the RAG path; the prompt forbids them explicitly. |
| Trust package names alone | Model/endpoint config can arrive transitively or via config files, not just as a named package — hence manifest *and* deployment-manifest scanning. |

## Revisit triggers

- None. This rule is a **non-negotiable** of the platform; it can be
  *implemented more strictly*, never relaxed.

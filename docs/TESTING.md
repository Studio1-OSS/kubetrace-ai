# Testing

## Unit (no cluster, no model): `uv run pytest tests/unit`

- **Policy:** allowed fixes and denials (probe removal, exec probes, privilege, host access, foreign images, memory caps, Service exposure, other namespaces, unlabelled resources, no-ops).
- **Redaction:** known values, bearer tokens, JWTs, kubeconfig data, private keys, and secret-named keys.
- **Agent loop:**
  - unknown tools and bad arguments come back as visible errors;
  - one retry after a failed verification, recorded as first-attempt failure and eventual success;
  - escalation states;
  - step, token and time limits, and cancellation;
  - a model outage blocks the run instead of switching models;
  - a hanging tool is abandoned;
  - exceptions become tool errors;
  - tool output is redacted before the model sees it.
- **Workspace:** writable allowlist, path escapes, `.git` hidden, exact-once edits, diffs including new files.
- **Executor:** merge-patch semantics, whole-selector replacement, the `resourceVersion` precondition, other-namespace refusal.
- **Superficial fixes:** a swallowed exception fails the hidden pricing tests and is detected in the diff; the real fix passes.
- **API:** SSE resumes after `Last-Event-ID`, export and import keep provenance and model, and results keep provenances apart and skip replays.

## Integration on kind: `KUBETRACE_KIND=1 uv run pytest tests/integration`

Needs kind, Docker and `KUBECONFIG` pointing at the kind cluster (see the README).

- Fixture runs of `selector-mismatch`, `application-bug` and `broken-readiness` end to end: baseline, injection, fault proof, investigation, real policy-checked writes as the agent ServiceAccount, image build, kind load, rollout, and hidden verification.
- The agent token is refused (403) for Secrets, other namespaces, the probe Deployment, deletes and RBAC.
- A stale proposal is rejected.
- Superficial or dangerous patches are denied against the real API.
- Review mode holds a write at `pending_approval` until the operator answers: approved, it applies and the run resolves; rejected, the live Service is unchanged and the run is never reported as resolved.

Stop any `kubetrace serve` on the same cluster first; the tests drive their own run manager on the demo namespace.

## Docker Compose: `docker compose build && docker compose up -d`

Checked on 2026-10-17: both images build, both ports bind to `127.0.0.1` only, the UI serves, `/api` proxies through nginx and SPA deep links resolve. The served bundle names `NEBIUS_API_KEY` and `CIVO_API_KEY` only in help text, never with a value. With kind on macOS the API container reports the cluster API server as unreachable, as the README says; use Compose with Civo, or run the API on the host for kind. `apps/web/package.json` pins `pnpm@10.23.0` and allows build scripts for `esbuild` only, because an unpinned `corepack enable` pulls a newer pnpm that fails `--frozen-lockfile` on ignored build scripts.

## UI: `cd apps/web && pnpm test:e2e`

Playwright drives the real UI against a running API and kind cluster, in fixture mode. It goes from experiment setup through fault injection, investigation and resolution to the report and Markdown export. The API must be running (`uv run kubetrace serve`).

## Live model (opt-in)

`uv run kubetrace preflight` checks the endpoint. A live scenario is `uv run kubetrace run <scenario> --model-mode live`. Live runs cost tokens and are never part of the default test suite.

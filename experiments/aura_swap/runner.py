"""Run a KubeTrace experiment with Aura (github.com/mezmo/aura) as the agent loop.

Setup, fault injection, hidden verification, the run database and reports are KubeTrace's own and
unchanged. Only the investigate step is swapped: instead of KubeTrace's `Agent`, an Aura web server
gets the incident, talks to the same model (Reflection Beam on Nebius Token Factory), and reaches
the cluster through tools served over MCP.

Two tool setups:
  kubetrace-tools  Aura drives KubeTrace's own tools through the MCP bridge (same policy engine,
                   workspace, tests and image builds). Isolates the agent runtime.
  k8s-mcp          Aura as it ships for Kubernetes: kubernetes-mcp-server, scoped to the agent's
                   ServiceAccount, plus filesystem access to the run's workspace repository.

Budgets match the KubeTrace loop: the scenario's step limit becomes Aura's turn_depth, the same
time limit applies, and a failed independent verification gets one retry.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from kubetrace_agent.executor import Executor, Mutation
from kubetrace_agent.k8s import agent_client
from kubetrace_agent.loop import BUDGET_NOTICE_AT, SYSTEM_PROMPT, Incident, Limits, Verification
from kubetrace_agent.redact import truncate
from kubetrace_agent.sandbox import Runner
from kubetrace_agent.tools import TOOLS, ToolContext
from kubetrace_api.runs import RunError, RunManager, Session, TERMINAL
from kubetrace_experiments.scenarios import RunView

from .bridge import Bridge, BridgeSession

AURA_BIN = Path(os.environ.get("AURA_WEB_SERVER", Path.home() / "bin" / "aura-web-server"))
AURA_VERSION = os.environ.get("AURA_VERSION_LABEL", "aura 0.2.19")
MODES = ("kubetrace-tools", "k8s-mcp")
AURA_PORT = 18080

K8S_MCP_PROMPT = """You are an on-call Kubernetes SRE agent for one namespace, {namespace}.

Scope
- You may read workloads, Pods, logs, events and Services in namespace {namespace}, and the application repository at {workspace} (source, tests, docs, and the manifests under k8s/ that define what runs in the cluster).
- You may change only the storefront Deployment, Service and ConfigMap in {namespace}, and the files in the repository. Keep the repository and the cluster in agreement: when you change a live object, make the same change to its manifest under k8s/.
- You cannot touch other namespaces, Secrets, RBAC or nodes. If the cause is outside your scope, investigate enough to support a diagnosis and escalate. Do not change something unrelated to make a symptom go away.

How to work
1. Gather evidence first: events, Pod states, logs, Service endpoints.
2. Fix the cause, not the symptom. Follow the docs in the repository (docs/config.md, docs/pricing.md, docs/operations.md).
3. Never weaken or delete tests, swallow exceptions, remove health probes, or replace them with commands that always succeed.
4. Verify recovery yourself before you finish.

When you are done, end your final answer with exactly these three lines:
OUTCOME: resolved | escalate
ROOT CAUSE: <one sentence>
SUMMARY: <one or two sentences>
"""


def _free_port(port: int) -> int:
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) != 0:
            return port
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _toml_str(s: str) -> str:
    return '"""\n' + s.replace("\\", "\\\\").replace('"""', '\\"\\"\\"') + '"""'


class AuraRunManager(RunManager):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.bridge = Bridge(port=int(os.environ.get("AURA_BRIDGE_PORT", "8765")))
        self.bridge.start(upstream=self.settings.nebius_base_url)

    # Investigate ----------------------------------------------------------------------------
    def investigate(self, scenario_id: str, policy_mode: str, model_mode: str) -> str:
        if model_mode == "live" and os.environ.get("AGENT_RUNTIME") == "aura":
            model_mode = os.environ.get("AURA_TOOL_SETUP", "kubetrace-tools")  # the UI's Investigate button
        if model_mode not in MODES:
            return super().investigate(scenario_id, policy_mode, model_mode)
        s = self._session(scenario_id, expect="detected")
        if not AURA_BIN.exists():
            raise RunError(f"Aura web server not found at {AURA_BIN}")
        self.db.update_run(s.run_id, provenance=f"aura-{model_mode}", provider="aura → nebius",
                           model=self.settings.nebius_model, policy_mode=policy_mode, started_at=time.time())
        self._background(s, self._do_investigate_aura, model_mode, policy_mode)
        return s.run_id

    def _do_investigate_aura(self, s: Session, mode: str, policy_mode: str) -> None:
        run_id, settings, h = s.run_id, self.settings, s.harness
        api = agent_client(h.cluster, settings.demo_namespace)
        s.executor = Executor(api, settings.demo_namespace, policy_mode, approver=lambda m: self._await_approval(s, m))
        s.ctx = ToolContext(settings=settings, namespace=settings.demo_namespace, api=api, executor=s.executor,
                            workspace=s.workspace, runner=Runner(settings), builder=h.builder, redactor=self.redactor,
                            run_dir=s.run_dir, emit=lambda t, p: self.emit(run_id, t, p),
                            set_state=lambda st: self.set_state(run_id, st), deployed_commit=s.injected_commit)
        limits = Limits(max_steps=min(settings.max_agent_steps, s.scenario.max_steps),
                        max_seconds=min(settings.max_run_seconds, s.scenario.max_seconds),
                        max_tokens=settings.max_run_tokens, max_output_chars=settings.max_tool_output_chars,
                        verification_retries=settings.verification_retries)
        incident = Incident(s.scenario.id, s.scenario.incident_title, s.scenario.incident_description, settings.demo_namespace)
        aura_dir = s.run_dir / "aura"
        aura_dir.mkdir(exist_ok=True)

        helpers: list[subprocess.Popen] = []
        if mode == "kubetrace-tools":
            tools = [t.name for t in TOOLS]
            system_prompt = SYSTEM_PROMPT.format(namespace=incident.namespace)
            mcp_toml = (f'[mcp.servers.kubetrace]\ntransport = "http_streamable"\nurl = "{self.bridge.url}"\n'
                        f'description = "KubeTrace incident tools for namespace {incident.namespace}"\n')
            user_tail = "Investigate, fix it if it is in your scope, verify, and finish."
        else:
            k8s_port = _free_port(18081)
            kubeconfig = self._agent_kubeconfig(s, aura_dir)
            helpers.append(subprocess.Popen(
                ["npx", "-y", "kubernetes-mcp-server@0.0.67", "--port", str(k8s_port), "--kubeconfig", str(kubeconfig),
                 ],  # write tools included; the ServiceAccount's Role limits Aura to the demo namespace
                stdout=open(aura_dir / "k8s-mcp.log", "w"), stderr=subprocess.STDOUT, start_new_session=True))
            self._wait_port(k8s_port, 120)
            tools = ["kubernetes-mcp-server", "filesystem"]
            system_prompt = K8S_MCP_PROMPT.format(namespace=incident.namespace, workspace=s.workspace.path)
            mcp_toml = (f'[mcp.servers.kubernetes]\ntransport = "http_streamable"\nurl = "http://127.0.0.1:{k8s_port}/mcp"\n'
                        f'description = "Kubernetes cluster operations: pods, deployments, services, logs, events"\n\n'
                        f'[mcp.servers.workspace]\ntransport = "stdio"\ncmd = ["npx"]\n'
                        f'args = ["-y", "@modelcontextprotocol/server-filesystem@2026.8.31", "{s.workspace.path}"]\n'
                        f'description = "The storefront application repository: source, tests, docs, k8s manifests"\n')
            user_tail = "Investigate, fix it if it is in your scope, and verify."

        cfg = aura_dir / "config.toml"
        cfg.write_text(
            "[mcp]\nsanitize_schemas = true\n\n" + mcp_toml +
            f'\n[agent]\nname = "kubetrace-on-aura"\nsystem_prompt = {_toml_str(system_prompt)}\n'
            f"turn_depth = {limits.max_steps}\nnudge_turns_remaining = {BUDGET_NOTICE_AT}\nnudge_last_turn = true\n\n"
            f'[agent.llm]\nprovider = "openai"\napi_key = "{{{{ env.NEBIUS_API_KEY }}}}"\n'
            f'model = "{settings.nebius_model}"\nbase_url = "{self.bridge.model_base_url}"\n'
            f"temperature = {settings.model_temperature}\nmax_tokens = {settings.model_max_tokens}\n")

        self.emit(run_id, "run_config", {"runtime": AURA_VERSION, "tool_setup": mode, "tools": tools,
                                         "generation_settings": {"model": settings.nebius_model,
                                                                 "temperature": settings.model_temperature,
                                                                 "max_tokens": settings.model_max_tokens},
                                         "limits": limits.__dict__, "aura_config": "aura/config.toml"})
        self.db.update_run(run_id, settings={"runtime": AURA_VERSION, "tool_setup": mode, "limits": limits.__dict__,
                                             "policy_mode": policy_mode, "test_runner": settings.test_runner})
        bsession = BridgeSession(s.ctx, self.redactor, lambda t, p: self.emit(run_id, t, p), limits.max_output_chars,
                                 set(tools) if mode == "kubetrace-tools" else set())
        self.bridge.serve(bsession)

        port = _free_port(AURA_PORT)
        env = {**os.environ, "NEBIUS_API_KEY": settings.nebius_api_key, "CONFIG_PATH": str(cfg)}
        server = subprocess.Popen(
            [str(AURA_BIN), "--host", "127.0.0.1", "--port", str(port), "--aura-custom-events", "true",
             "--streaming-timeout-secs", str(limits.max_seconds + 120)],
            env=env, stdout=open(aura_dir / "aura-server.log", "w"), stderr=subprocess.STDOUT, start_new_session=True)
        helpers.append(server)
        started = time.monotonic()
        totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cache_read_tokens": 0, "requests": 0,
                  "model_calls": 0}
        verifications: list[dict] = []
        first_attempt = None
        state, reason, agent_outcome = "unresolved", "", None
        transcript: list[dict] = []
        try:
            self._wait_http(f"http://127.0.0.1:{port}/health", 120, server)
            self.set_state(run_id, "investigating")
            messages = [{"role": "user", "content": f"Incident: {incident.title}\n\n{incident.description}\n\n"
                                                    f"Namespace: {incident.namespace}. {user_tail}"}]
            attempts = 0
            while True:
                left = limits.max_seconds - (time.monotonic() - started)
                if left <= 5:
                    state, reason = "unresolved", f"time limit of {limits.max_seconds} s reached"
                    break
                text, usage, stream_error = self._chat(port, messages, left, aura_dir / f"stream-{attempts + 1}.jsonl", run_id)
                totals["requests"] += 1
                for k in ("prompt_tokens", "completion_tokens", "total_tokens", "cache_read_tokens"):
                    totals[k] += int((usage or {}).get(k) or 0)
                totals["model_calls"] += int((usage or {}).get("model_calls") or 0)
                transcript += [{"role": "request", "messages": messages}, {"role": "assistant", "content": text,
                                                                           "error": stream_error}]
                if text.strip():
                    self.emit(run_id, "decision", {"text": self.redactor.text(truncate(text.strip(), 1200))})
                if stream_error:
                    self.emit(run_id, "error", {"where": "aura", "message": self.redactor.text(stream_error)[:1500]})
                outcome = s.ctx.finished if mode == "kubetrace-tools" else self._parse_outcome(text)
                if not outcome:
                    state = "unresolved"
                    reason = ("Aura stopped with an error: " + stream_error[:300]) if stream_error else \
                        ("the agent ended without calling finish" if mode == "kubetrace-tools" else
                         "the agent ended without stating an outcome")
                    break
                agent_outcome = outcome
                if outcome["outcome"] == "escalate":
                    self.emit(run_id, "escalation", {"root_cause": outcome.get("root_cause", ""), "summary": outcome.get("summary", "")})
                self.set_state(run_id, "verifying")
                attempts += 1
                verdict = self._verify(s, outcome, mode)
                record = {"attempt": attempts, "ok": verdict.ok, "checks": verdict.checks, "agent_outcome": outcome["outcome"]}
                verifications.append(record)
                self.emit(run_id, "verification", record)
                if first_attempt is None:
                    first_attempt = verdict.ok
                if verdict.ok:
                    state, reason = ("escalated", "escalation confirmed: the cause is outside the agent's scope") \
                        if outcome["outcome"] == "escalate" else ("resolved", "independent verification passed")
                    break
                if outcome["outcome"] == "escalate":
                    state, reason = "unresolved", "the agent escalated; independent checks did not accept the escalation"
                    break
                if attempts > limits.verification_retries:
                    state, reason = "unresolved", "independent verification failed"
                    break
                self.emit(run_id, "retry", {"reason": verdict.public_summary})
                self.set_state(run_id, "investigating")
                s.ctx.finished = None
                # No assistant message here: Beam rejects an earlier assistant turn without its reasoning,
                # and the previous answer's reasoning is not exposed by Aura's API. Restate it as user context.
                messages = messages + [{"role": "user", "content":
                                        f"Your previous attempt ended with this answer:\n\n{(text or '(finished)')[:2000]}\n\n"
                                        "Independent verification did not confirm recovery: "
                                        f"{verdict.public_summary} Investigate further and fix it, then finish again."}]
        except Exception as exc:  # noqa: BLE001
            state, reason = "error", f"{type(exc).__name__}: {exc}"
            self.emit(run_id, "error", {"where": "aura", "message": self.redactor.text(str(exc))[:1500]})
        finally:
            b = self.bridge.release()
            for p in helpers:
                with_kill(p)
        elapsed = round(time.monotonic() - started, 2)
        eventual = state in ("resolved", "escalated")
        self.set_state(run_id, state)
        drift = self.drift(s)
        if drift:
            self.emit(run_id, "drift", {"differences": drift})
        tool_calls = len(b.calls) if b and mode == "kubetrace-tools" else self._count_stream_tools(aura_dir)
        # Token usage and model calls as the provider reported them, recorded by the bridge's model proxy.
        calls = b.model_calls if b else []
        usage = [c["usage"] or {} for c in calls]
        prompt = sum(int(u.get("prompt_tokens") or 0) for u in usage)
        completion = sum(int(u.get("completion_tokens") or 0) for u in usage)
        cached = sum(int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0) for u in usage)
        aura_errors = self._server_errors(aura_dir / "aura-server.log")
        if aura_errors and not agent_outcome and "MaxDepthError" in " ".join(aura_errors):
            reason = f"Aura's turn limit ({limits.max_steps}) was reached before the agent finished"
        metrics = {"runtime": AURA_VERSION, "tool_setup": mode, "model_calls": len(calls),
                   "model_errors": sum(1 for c in calls if c["status"] != 200),
                   "usage_reported_calls": sum(1 for u in usage if u),
                   "model_latency_s": round(sum(c["latency_s"] or 0 for c in calls), 2),
                   "prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion,
                   "cached_prompt_tokens": cached,
                   "aura_reported": {k: totals[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens",
                                                            "cache_read_tokens", "requests")},
                   "aura_errors": aura_errors,
                   "token_usage": "reported by provider" if calls and all(usage) else
                   ("partial: some responses had no usage" if any(usage) else "unavailable"),
                   "tool_calls": tool_calls,
                   "tool_time_s": round(b.tool_time_s, 2) if b else None, "tool_errors": b.tool_errors if b else None,
                   "rejected_actions": b.rejected_actions if b else None,
                   "verification_attempts": len(verifications)}
        (s.run_dir / "transcript.json").write_text(json.dumps(self.redactor.value(transcript), indent=1, default=str))
        outcome_rec = {"final_state": state, "reason": reason, "agent": agent_outcome, "verifications": verifications,
                       "drift": drift, "mutations": [m.public() for m in s.executor.history], "builds": s.ctx.builds,
                       "tests": [{k: v for k, v in t.items() if k != "workspace_diff"} for t in s.ctx.test_runs],
                       "source_diff": s.workspace.diff_between(s.injected_commit) if s.workspace else "",
                       "injected_commit": s.injected_commit, "final_commit": s.workspace.head() if s.workspace else None,
                       "elapsed_s": elapsed}
        self.db.update_run(run_id, metrics=metrics, outcome=self.redactor.value(outcome_rec), ended_at=time.time(),
                           first_attempt_success=None if first_attempt is None else int(first_attempt),
                           eventual_success=int(eventual))
        self.emit(run_id, "final", {"state": state, "reason": reason, "metrics": metrics})

    # Verification ---------------------------------------------------------------------------
    def _verify(self, s: Session, outcome: dict, mode: str) -> Verification:
        mutations = s.executor.history if mode == "kubetrace-tools" else self._observed_mutations(s)
        view = RunView(workspace=s.workspace, injected_commit=s.injected_commit, mutations=mutations,
                       builds=s.ctx.builds, agent_outcome=outcome, runner=s.ctx.runner, run_dir=s.run_dir, fault=s.fault)
        try:
            return s.scenario.verify(s.harness, view)
        except Exception as exc:  # noqa: BLE001
            return Verification(False, [{"name": "verification ran", "ok": False, "detail": f"{type(exc).__name__}: {exc}"}],
                                "Recovery could not be confirmed.")

    def _observed_mutations(self, s: Session) -> list[Mutation]:
        """With kubernetes-mcp-server, changes bypass KubeTrace's executor. Read them back from the stream."""
        # Only cluster writes that succeeded count. Reads, file edits, and calls the cluster refused
        # (pods_exec and pods_run are denied by the agent's Role) are not changes.
        writes = {"resources_create_or_update", "resources_delete", "resources_scale", "pods_delete", "pods_run"}
        out = []
        for f in sorted((s.run_dir / "aura").glob("stream-*.jsonl")):
            for line in f.read_text().splitlines():
                ev = json.loads(line)
                data = ev.get("data") or {}
                if ev.get("event") != "aura.tool_complete" or data.get("tool_name") not in writes or not data.get("success"):
                    continue
                out.append(Mutation(id=f"k8s-mcp-{len(out) + 1}", kind="(kubernetes-mcp-server)", name=data["tool_name"],
                                    source="k8s-mcp", reason="observed in Aura stream", status="applied"))
        return out

    @staticmethod
    def _parse_outcome(text: str) -> dict | None:
        fields = {}
        for line in text.splitlines():
            for key in ("OUTCOME", "ROOT CAUSE", "SUMMARY"):
                if line.strip().upper().startswith(key + ":"):
                    fields[key] = line.split(":", 1)[1].strip()
        if "OUTCOME" not in fields:
            # No exact outcome line. The hidden checks decide whether the incident is fixed, so a
            # formatting slip must not fail the run: infer the claim from the answer instead.
            if not text.strip():
                return None
            head = text.strip().splitlines()[0].lower()
            claim = "escalate" if ("escalat" in text.lower() and "resolved" not in head) else "resolved"
            return {"outcome": claim, "root_cause": "", "summary": text.strip()[:300], "outcome_inferred": True}
        value = fields["OUTCOME"].lower()
        return {"outcome": "escalate" if "escalat" in value else "resolved",
                "root_cause": fields.get("ROOT CAUSE", ""), "summary": fields.get("SUMMARY", "")}

    # Aura I/O -------------------------------------------------------------------------------
    def _chat(self, port: int, messages: list[dict], timeout_s: float, log: Path, run_id: str) -> tuple[str, dict, str]:
        body = {"model": "kubetrace-on-aura", "stream": True, "messages": messages,
                "stream_options": {"include_usage": True}}
        text, usage, error, event = [], {}, "", None
        # Model calls, estimated. Aura runs each tool as soon as it streams, so a batch from one model call
        # arrives about 0.1 s apart; a new call shows up as a gap of a second or more after the last result.
        turns, last_done = 0, None
        with log.open("w") as out, httpx.Client(timeout=httpx.Timeout(timeout_s, connect=10)) as http:
            try:
                with http.stream("POST", f"http://127.0.0.1:{port}/v1/chat/completions", json=body) as resp:
                    if resp.status_code != 200:
                        return "", {}, f"HTTP {resp.status_code}: {resp.read().decode()[:800]}"
                    for line in resp.iter_lines():
                        if line.startswith("event:"):
                            event = line[6:].strip()
                            continue
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            data = json.loads(raw)
                        except ValueError:
                            data = {"raw": raw}
                        out.write(json.dumps({"t": round(time.time(), 3), "event": event, "data": data}) + "\n")
                        now = time.monotonic()
                        if event == "aura.tool_requested" and (last_done is None or now - last_done > 0.75):
                            turns += 1
                        if event == "aura.tool_complete":
                            last_done = now
                        if event == "aura.usage":
                            usage = {"prompt_tokens": data.get("prompt_tokens"), "completion_tokens": data.get("completion_tokens"),
                                     "total_tokens": data.get("total_tokens"),
                                     "cache_read_tokens": data.get("cache_read_input_tokens")}
                        elif event and event.startswith("aura."):
                            pass
                        elif isinstance(data, dict):
                            if data.get("error"):
                                error = json.dumps(data["error"])[:1500]
                            for ch in data.get("choices") or []:
                                piece = (ch.get("delta") or {}).get("content")
                                if piece:
                                    text.append(piece)
                            if data.get("usage") and not usage:
                                usage = data["usage"]
                        event = None
            except httpx.TimeoutException:
                error = f"time limit reached after {round(timeout_s)} s"
        # aura.usage has no call count: tool batches, plus the call that wrote the final answer.
        usage = {**usage, "model_calls": turns + (1 if text else 0)}
        return "".join(text), usage, error

    @staticmethod
    def _server_errors(log: Path) -> list[str]:
        import re
        if not log.exists():
            return []
        clean = re.sub(r"\x1b\[[0-9;]*m", "", log.read_text(errors="replace"))
        return [line.split("Stream error:", 1)[1].strip()[:300] for line in clean.splitlines() if "Stream error:" in line]

    @staticmethod
    def _count_stream_tools(aura_dir: Path) -> int:
        n = 0
        for f in aura_dir.glob("stream-*.jsonl"):
            n += sum(1 for line in f.read_text().splitlines() if '"event": "aura.tool_requested"' in line)
        return n

    def _agent_kubeconfig(self, s: Session, aura_dir: Path) -> Path:
        """A kubeconfig for the same namespace-scoped ServiceAccount the KubeTrace agent uses."""
        ns = self.settings.demo_namespace
        kc = os.environ.get("KUBECONFIG", str(Path.home() / ".kube" / "config"))
        token = subprocess.run(["kubectl", "--kubeconfig", kc, "-n", ns, "create", "token", "kubetrace-agent",
                                "--duration", "2h"], capture_output=True, text=True, check=True).stdout.strip()
        server = subprocess.run(["kubectl", "--kubeconfig", kc, "config", "view", "--minify", "--raw", "-o",
                                 "jsonpath={.clusters[0].cluster.server}"], capture_output=True, text=True, check=True).stdout
        ca = subprocess.run(["kubectl", "--kubeconfig", kc, "config", "view", "--minify", "--raw", "-o",
                             "jsonpath={.clusters[0].cluster.certificate-authority-data}"],
                            capture_output=True, text=True, check=True).stdout
        path = aura_dir / "agent-kubeconfig"
        path.write_text(json.dumps({
            "apiVersion": "v1", "kind": "Config", "current-context": "agent",
            "clusters": [{"name": "c", "cluster": {"server": server, "certificate-authority-data": ca}}],
            "users": [{"name": "kubetrace-agent", "user": {"token": token}}],
            "contexts": [{"name": "agent", "context": {"cluster": "c", "user": "kubetrace-agent", "namespace": ns}}]}))
        path.chmod(0o600)
        return path

    @staticmethod
    def _wait_port(port: int, timeout_s: int) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    return
            time.sleep(1)
        raise RuntimeError(f"nothing listening on port {port} after {timeout_s} s")

    @staticmethod
    def _wait_http(url: str, timeout_s: int, proc: subprocess.Popen) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"Aura web server exited with code {proc.returncode}; see aura/aura-server.log")
            try:
                if httpx.get(url, timeout=3).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(1)
        raise RuntimeError(f"Aura web server not healthy after {timeout_s} s")


def with_kill(p: subprocess.Popen) -> None:
    """Stop a helper and everything it started (npx spawns children)."""
    if p.poll() is not None:
        return
    try:
        os.killpg(p.pid, signal.SIGTERM)
        p.wait(10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    except ProcessLookupError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(prog="aura-swap", description="Run a KubeTrace experiment with Aura as the agent loop")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("scenario")
    r.add_argument("--mode", default="kubetrace-tools", choices=MODES)
    r.add_argument("--policy", default="auto", choices=["auto", "review"])
    args = parser.parse_args()
    if not shutil.which("kubectl") and args.mode == "k8s-mcp":
        sys.exit("kubectl is required for --mode k8s-mcp")

    from kubetrace_api.main import clusters, connect_on_start, db, settings
    connect_on_start()
    if not clusters.handle:
        sys.exit(f"not connected: {clusters.error}")
    manager = AuraRunManager(settings, db, clusters)
    run_id = manager.run_all(args.scenario, args.policy, args.mode)
    print(f"run {run_id}", flush=True)
    seen = 0
    while True:
        for e in db.events(run_id, seen):
            seen = e["id"]
            p = e["payload"]
            detail = p.get("state") or p.get("tool") or p.get("text") or p.get("step") or p.get("message") or ""
            print(f"{time.strftime('%H:%M:%S', time.localtime(e['ts']))}  {e['type']:<16} {str(detail)[:110]}", flush=True)
        run = db.get_run(run_id)
        if run["state"] in TERMINAL and (run.get("ended_at") or run["state"] == "error"):
            print(json.dumps({"state": run["state"], "metrics": run.get("metrics")}, indent=1), flush=True)
            sys.exit(0 if run.get("eventual_success") else 2)
        time.sleep(1)


if __name__ == "__main__":
    main()

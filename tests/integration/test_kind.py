"""Integration tests against a real kind cluster. Run with KUBETRACE_KIND=1 (see docs/TESTING.md)."""
import time

import pytest
from kubernetes import client
from kubernetes.client.rest import ApiException

from kubetrace_agent.executor import Executor
from kubetrace_agent.k8s import agent_client

from .conftest import TERMINAL, wait_state

pytestmark = pytest.mark.kind


@pytest.mark.parametrize("scenario", ["selector-mismatch", "application-bug", "broken-readiness"])
def test_fixture_run_end_to_end(stack, scenario):
    settings, db, clusters, manager = stack
    run_id = manager.run_all(scenario, "auto", "fixture")
    run = wait_state(db, run_id, TERMINAL, timeout=900)
    events = db.events(run_id, 0, 10_000)
    assert run["state"] == "resolved", [e["payload"] for e in events if e["type"] in ("error", "verification")]
    verification = [e for e in events if e["type"] == "verification"][-1]["payload"]
    assert verification["ok"] and all(c["ok"] for c in verification["checks"])
    assert run["provenance"] == "fixture"
    assert any(e["type"] == "detected" and all(c["ok"] for c in e["payload"]["fault_proof"]) for e in events)


@pytest.fixture(scope="module")
def baseline(stack):
    settings, db, clusters, manager = stack
    run_id = manager.setup("selector-mismatch")
    wait_state(db, run_id, {"baseline_ready"} | TERMINAL, timeout=600)
    return settings, clusters.require()


def test_agent_credentials_are_namespace_scoped(baseline):
    settings, handle = baseline
    api = agent_client(handle, settings.demo_namespace)
    core, apps = client.CoreV1Api(api), client.AppsV1Api(api)
    core.list_namespaced_pod(settings.demo_namespace)  # allowed
    for call in (lambda: core.list_namespaced_secret(settings.demo_namespace),
                 lambda: core.list_namespaced_pod("kube-system"),
                 lambda: apps.patch_namespaced_deployment("probe", settings.demo_namespace, {"spec": {"replicas": 2}}),
                 lambda: core.delete_namespaced_service("storefront", settings.demo_namespace),
                 lambda: client.RbacAuthorizationV1Api(api).list_namespaced_role(settings.demo_namespace)):
        with pytest.raises(ApiException) as err:
            call()
        assert err.value.status == 403


def test_stale_proposal_is_rejected(baseline):
    settings, handle = baseline
    executor = Executor(agent_client(handle, settings.demo_namespace), settings.demo_namespace, "auto")
    live, proposed = executor.from_merge_patch("Deployment", "storefront", {"spec": {"replicas": 3}})
    # Someone else changes the Deployment after the agent read it.
    client.AppsV1Api(handle.api).patch_namespaced_deployment("storefront", settings.demo_namespace,
        {"metadata": {"annotations": {"kubetrace.ai/touched": str(time.time())}}})
    result = executor.execute("Deployment", "storefront", live, proposed, "patch_resource", "scale up")
    assert result.status == "stale"


@pytest.mark.parametrize("patch,reason", [
    ({"spec": {"template": {"spec": {"containers": [{"name": "storefront", "readinessProbe": None}]}}}}, "cannot be removed"),
    ({"spec": {"template": {"spec": {"hostNetwork": True}}}}, "hostNetwork"),
    ({"spec": {"template": {"spec": {"containers": [{"name": "storefront", "image": "busybox:1.36"}]}}}}, "image"),
])
def test_superficial_or_dangerous_patches_are_denied_on_the_real_api(baseline, patch, reason):
    settings, handle = baseline
    executor = Executor(agent_client(handle, settings.demo_namespace), settings.demo_namespace, "auto")
    # Named lists merge by name; null removes a key (the readiness probe in the first case).
    live, proposed = executor.from_merge_patch("Deployment", "storefront", patch)
    result = executor.execute("Deployment", "storefront", live, proposed, "patch_resource", "test")
    assert result.status == "denied", result.decision
    assert any(reason in r for r in result.decision["reasons"]), result.decision


def _pending_mutations(db, run_id, seen):
    for e in db.events(run_id, 0, 10_000):
        p = e["payload"]
        if p.get("status") == "pending_approval" and p.get("id") not in seen:
            yield p["id"]


def _review_run(stack, approve: bool):
    """Investigate selector-mismatch in review mode, answering every approval request the same way."""
    settings, db, clusters, manager = stack
    wait_state(db, manager.setup("selector-mismatch"), {"baseline_ready"} | TERMINAL, timeout=600)
    wait_state(db, manager.inject("selector-mismatch"), {"detected"} | TERMINAL, timeout=300)
    core = client.CoreV1Api(clusters.require().api)
    before = core.read_namespaced_service("storefront", settings.demo_namespace).spec.selector
    run_id = manager.investigate("selector-mismatch", "review", "fixture")
    seen: set[str] = set()
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        for mid in list(_pending_mutations(db, run_id, seen)):
            seen.add(mid)
            manager.approve(run_id, mid, approve, "integration test")
        if db.get_run(run_id)["state"] in TERMINAL:
            break
        time.sleep(1)
    after = core.read_namespaced_service("storefront", settings.demo_namespace).spec.selector
    statuses = [e["payload"].get("status") for e in db.events(run_id, 0, 10_000) if e["payload"].get("id") in seen]
    return db.get_run(run_id), seen, before, after, statuses


def test_review_mode_holds_a_write_until_approved(stack):
    run, asked, before, after, statuses = _review_run(stack, approve=True)
    assert asked, "review mode never asked for approval"
    assert statuses.index("pending_approval") < statuses.index("applied")
    assert after != before and run["state"] == "resolved"


def test_review_mode_rejected_write_never_reaches_the_cluster(stack):
    run, asked, before, after, statuses = _review_run(stack, approve=False)
    assert asked, "review mode never asked for approval"
    assert "applied" not in statuses and "rejected" in statuses
    assert after == before, "a rejected change was written to the cluster"
    assert run["state"] != "resolved"

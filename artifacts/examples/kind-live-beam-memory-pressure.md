# KubeTrace run 20261017-172931-8b8b69: memory-pressure

> **Live run on a local kind cluster**

**Outcome:** resolved. independent verification passed  
**First-attempt success:** True · **Eventual success:** True  
**Provider:** nebius-token-factory · **Model:** `reflection/beam` · **Policy mode:** auto  
**Repository commit:** 5174efb0f044

**Generation settings:** `{"max_tokens": 2048, "temperature": 0.2}`  
**Prompt / tool schema versions:** 2026-10-17.2 / 2026-10-16.1

## Cluster
- Kind: kind · Kubernetes v1.27.3 · context [hidden]
- Capacity: [{"name": "kubetrace-control-plane", "cpu": "4", "memory": "16356580Ki"}]

## Issue
**Incident:** Storefront Pods keep restarting  
**Symptom:** Pods restart repeatedly with OOMKilled; new Pods never become Ready.

Baseline (healthy, before injection):
- ✅ **storefront and probe rolled out**: Deployments available
- ✅ **checkout [{"sku": "MUG-01", "qty": 2}]**: HTTP 200, total 31.92, expected 31.92
- ✅ **checkout [{"sku": "CAP-03", "qty": 12}]**: HTTP 200, total 227.77, expected 227.77
- ✅ **checkout [{"sku": "TEE-02", "qty": 1}, {"sku": "STK-04", "qty": 3}] SAVE10**: HTTP 200, total 41.72, expected 41.72

Fault confirmed before investigation:
- ✅ **a Pod was OOMKilled**: last termination reason OOMKilled

## Evidence and hypotheses
- *Observation:* New storefront Pod is OOMKilled while warming a 160 MiB cache; memory limit is 128Mi, but docs require cache + ~40 MiB (~200 MiB). (Pod storefront-954cd69d7-rr26w last_terminated OOMKilled exit 137, logs: warming product image cache: 160 MiB, configmap cache_warm_mb=160, deployment memory limit=128Mi, docs/config.md: container needs cache_warm_mb plus about 40 MiB)

**Agent conclusion (resolved):** The storefront Deployment's memory limit (128Mi) was below the memory needed for the marketing-increased 160 MiB product image cache plus ~40 MiB of process overhead, so new Pods were OOMKilled during cache warm-up and the rollout could not finish.

Raised the storefront container memory request to 200Mi and limit to 256Mi in k8s/deployment.yaml and applied it. The rollout completed with 2/2 Ready Pods, and health, readiness, and checkout HTTP checks through the Service succeed.

## Attempted changes
### apply_manifest Deployment/storefront: applied
Reason: Increase memory resources to accommodate 160 MiB cache plus overhead.

```diff
--- live/deployment/storefront
+++ proposed/deployment/storefront
@@ -62,10 +62,10 @@
         resources:
           limits:
             cpu: 500m
-            memory: 128Mi
+            memory: 256Mi
           requests:
             cpu: 50m
-            memory: 96Mi
+            memory: 200Mi
         securityContext:
           allowPrivilegeEscalation: false
           capabilities:
```


## Source diff (workspace, from the incident commit)
```diff
diff --git a/k8s/deployment.yaml b/k8s/deployment.yaml
index 61c13d7..eb72e69 100644
--- a/k8s/deployment.yaml
+++ b/k8s/deployment.yaml
@@ -46,10 +46,10 @@ spec:
           resources:
             requests:
               cpu: 50m
-              memory: 96Mi
+              memory: 200Mi
             limits:
               cpu: 500m
-              memory: 128Mi
+              memory: 256Mi
           securityContext:
             allowPrivilegeEscalation: false
             readOnlyRootFilesystem: true
```

## Tests
### `python -m pytest -q -p no:cacheprovider tests`: exit 0 (passed, 0.66 s)
Isolation: docker: --network none, read-only source, no credentials, no Docker socket
```
.............                                                            [100%]
13 passed in 0.02s
```

## Rollouts
- storefront: complete=True after 0.1 s (2/2 ready)
- storefront: complete=True after 0.0 s (2/2 ready)
- storefront: complete=True after 0.0 s (2/2 ready)

## Independent verification
Attempt 1 (agent said resolved): passed
- ✅ **memory limit covers the configured cache**: limit 256Mi, need about 200Mi
- ✅ **memory change is bounded**: limit 256Mi ≤ 400Mi
- ✅ **rollout complete**: all replicas updated and ready
- ✅ **pods ready and stable**: 2/2 Ready; restarts 0→0 over 20 s
- ✅ **service endpoints**: 2 ready endpoints
- ✅ **checkout [{"sku": "MUG-01", "qty": 2}]**: HTTP 200, total 31.92, expected 31.92
- ✅ **checkout [{"sku": "CAP-03", "qty": 12}]**: HTTP 200, total 227.77, expected 227.77
- ✅ **checkout [{"sku": "TEE-02", "qty": 1}, {"sku": "STK-04", "qty": 3}] SAVE10**: HTTP 200, total 41.72, expected 41.72


## Measurements
- Model calls: 25 · model time 52.25 s
- Tokens: 402051 in / 6234 out / 408285 total (reported by provider)
- Tool calls: 41 (1 errors) · tool time 2.06 s
- Rejected actions: 0 · verification attempts 1
- Agent elapsed: 74.59 s
- Cost: $0.1067 (estimate; rates from Nebius Token Factory GET /v1/models?verbose=true (pricing.prompt / pricing.completion), 2026-10-16)

## Limitations
- None recorded.

# KubeTrace run 20261017-192319-49ae13: memory-pressure

> **Live run on a Civo cluster**

**Outcome:** resolved. independent verification passed  
**First-attempt success:** True · **Eventual success:** True  
**Provider:** nebius-token-factory · **Model:** `reflection/beam` · **Policy mode:** auto  
**Repository commit:** da902b0c1ed8

**Generation settings:** `{"max_tokens": 2048, "temperature": 0.2}`  
**Prompt / tool schema versions:** 2026-10-17.2 / 2026-10-16.1

## Cluster
- Kind: civo · Kubernetes v1.35.0+k3s1 · context [hidden]
- Capacity: [{"name": "k3s-kubetrace-demo-cc91-52bf34-node-pool-b14e-2zv2y", "cpu": "1880m", "memory": "2364008Ki"}, {"name": "k3s-kubetrace-demo-cc91-52bf34-node-pool-b14e-ve391", "cpu": "1880m", "memory": "2364020Ki"}]

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
- *Observation:* New Pod OOMKills while warming a 160 MiB cache; configured cache plus ~40 MiB overhead exceeds the 128 MiB memory limit. (Pod storefront-f99c57669-nx5cs last_terminated OOMKilled exit 137, logs: warming product image cache: 160 MiB, config cache_warm_mb=160, docs/config.md: container needs cache + ~40 MiB, deployment memory limit 128Mi)

**Agent conclusion (resolved):** The storefront Deployment's 128 MiB memory limit was too small for the marketing-increased 160 MiB product image cache, which needs about 200 MiB total; new Pods were OOMKilled during cache warm-up.

Raised the storefront container memory request to 200Mi and limit to 256Mi in k8s/deployment.yaml and applied it. The rollout completed with 2/2 Ready Pods, /readyz returns ready, and checkout works through the Service.

## Attempted changes
### apply_manifest Deployment/storefront: applied
Reason: Increase memory resources to accommodate configured 160 MiB cache.

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
index 360ba97..6e84018 100644
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
### `python -m pytest -q -p no:cacheprovider tests`: exit 0 (passed, 0.42 s)
Isolation: docker: --network none, read-only source, no credentials, no Docker socket
```
.............                                                            [100%]
13 passed in 0.02s
```

## Rollouts
- storefront: complete=True after 12.9 s (2/2 ready)

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
- Model calls: 27 · model time 47.01 s
- Tokens: 428680 in / 5701 out / 434381 total (reported by provider)
- Tool calls: 43 (4 errors) · tool time 20.94 s
- Rejected actions: 0 · verification attempts 1
- Agent elapsed: 91.13 s
- Cost: $0.1129 (estimate; rates from Nebius Token Factory GET /v1/models?verbose=true (pricing.prompt / pricing.completion), 2026-10-16)

## Limitations
- None recorded.

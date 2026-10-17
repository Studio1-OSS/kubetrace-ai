# KubeTrace run 20261017-172434-a464e5: broken-readiness

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
**Incident:** Storefront Pods never become ready  
**Symptom:** The rollout is stuck: new Pods run with zero restarts but never become Ready; the release never goes live.

Baseline (healthy, before injection):
- ✅ **storefront and probe rolled out**: Deployments available
- ✅ **checkout [{"sku": "MUG-01", "qty": 2}]**: HTTP 200, total 31.92, expected 31.92
- ✅ **checkout [{"sku": "CAP-03", "qty": 12}]**: HTTP 200, total 227.77, expected 227.77
- ✅ **checkout [{"sku": "TEE-02", "qty": 1}, {"sku": "STK-04", "qty": 3}] SAVE10**: HTTP 200, total 41.72, expected 41.72

Fault confirmed before investigation:
- ✅ **new Pods run but are not Ready**: Pods with the /ready probe are Running, not Ready
- ✅ **rollout is not completing**: updated 1, ready 2, unavailable 1

## Evidence and hypotheses
- *Observation:* New storefront Pod is running and healthy (liveness /healthz 200) but its readiness probe targets /ready, which the app does not implement (404). The app's readiness endpoint is /readyz per docs/operations.md. (events: Readiness probe failed: HTTP probe failed with statuscode: 404 on /ready, deployment readinessProbe path /ready, docs/operations.md: readiness endpoint is /readyz, server.py: exposes /readyz)

**Agent conclusion (resolved):** The storefront Deployment's readiness probe targeted /ready, an endpoint the application does not implement (404). The documented readiness endpoint is /readyz, which returns 200 once configuration is loaded and the cache is warmed. The probe path was corrected to /readyz.

Fixed k8s/deployment.yaml readinessProbe.httpGet.path from /ready to /readyz and applied it. Rollout completed with 2/2 Pods ready; verified /readyz and /healthz return 200 through the storefront Service.

## Attempted changes
### apply_manifest Deployment/storefront: applied
Reason: Fix readiness probe path to /readyz.

```diff
--- live/deployment/storefront
+++ proposed/deployment/storefront
@@ -51,7 +51,7 @@
         readinessProbe:
           failureThreshold: 2
           httpGet:
-            path: /ready
+            path: /readyz
             port: http
             scheme: HTTP
           periodSeconds: 3
```


## Source diff (workspace, from the incident commit)
```diff
diff --git a/k8s/deployment.yaml b/k8s/deployment.yaml
index 8a13014..61c13d7 100644
--- a/k8s/deployment.yaml
+++ b/k8s/deployment.yaml
@@ -33,7 +33,7 @@ spec:
               value: baseline-baseline-30d20958f43b
           readinessProbe:
             httpGet:
-              path: /ready
+              path: /readyz
               port: http
             periodSeconds: 3
             failureThreshold: 2
```

## Tests
### `python -m pytest -q -p no:cacheprovider tests`: exit 0 (passed, 0.57 s)
Isolation: docker: --network none, read-only source, no credentials, no Docker socket
```
.............                                                            [100%]
13 passed in 0.02s
```

## Rollouts
- storefront: complete=True after 0.0 s (2/2 ready)
- storefront: complete=True after 0.0 s (2/2 ready)

## Independent verification
Attempt 1 (agent said resolved): passed
- ✅ **readiness probe checks /readyz over HTTP**: readinessProbe {"failureThreshold": 2, "httpGet": {"path": "/readyz", "port": "http", "scheme": "HTTP"}, "periodSeconds": 3, "successThreshold": 1, "timeoutSeconds": 1}
- ✅ **rollout complete**: all replicas updated and ready
- ✅ **pods ready and stable**: 2/2 Ready; restarts 0→0 over 5 s
- ✅ **service endpoints**: 2 ready endpoints
- ✅ **checkout [{"sku": "MUG-01", "qty": 2}]**: HTTP 200, total 31.92, expected 31.92
- ✅ **checkout [{"sku": "CAP-03", "qty": 12}]**: HTTP 200, total 227.77, expected 227.77
- ✅ **checkout [{"sku": "TEE-02", "qty": 1}, {"sku": "STK-04", "qty": 3}] SAVE10**: HTTP 200, total 41.72, expected 41.72
- ✅ **source manifest matches**: manifest readinessProbe {"httpGet": {"path": "/readyz", "port": "http"}, "periodSeconds": 3, "failureThreshold": 2}


## Measurements
- Model calls: 26 · model time 52.59 s
- Tokens: 437239 in / 6373 out / 443612 total (reported by provider)
- Tool calls: 43 (1 errors) · tool time 1.45 s
- Rejected actions: 0 · verification attempts 1
- Agent elapsed: 59.36 s
- Cost: $0.1157 (estimate; rates from Nebius Token Factory GET /v1/models?verbose=true (pricing.prompt / pricing.completion), 2026-10-16)

## Limitations
- None recorded.

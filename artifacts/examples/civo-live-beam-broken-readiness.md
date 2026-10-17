# KubeTrace run 20261017-191722-e5c544: broken-readiness

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
- *Observation:* New ReplicaSet's readinessProbe uses path /ready, but the app only serves /readyz, so the probe gets 404 and the new Pod never becomes ready. (Pod storefront-68b64fb899-bwczm logs: GET /ready 404, events: Readiness probe failed: HTTP probe failed with statuscode: 404, docs/operations.md: readiness endpoint is GET /readyz, k8s/deployment.yaml line 36: path: /ready)

**Agent conclusion (resolved):** The updated storefront Deployment manifest set readinessProbe.httpGet.path to /ready, but the application only implements /readyz, so the probe received 404 and new Pods never became ready.

Changed the readiness probe path in k8s/deployment.yaml from /ready to /readyz, applied the manifest, and verified the rollout completed with 2/2 ready Pods and a successful /readyz check through the Service.

## Attempted changes
### apply_manifest Deployment/storefront: applied
Reason: Fix readinessProbe path from /ready to /readyz.

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
index db56582..a2b06ec 100644
--- a/k8s/deployment.yaml
+++ b/k8s/deployment.yaml
@@ -33,7 +33,7 @@ spec:
               value: baseline-526c0d93682c6bf436f8d64aa45fd09975500cee967547696f94f2
           readinessProbe:
             httpGet:
-              path: /ready
+              path: /readyz
               port: http
             periodSeconds: 3
             failureThreshold: 2
```

## Tests
No tests were run.

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
- Model calls: 16 · model time 28.52 s
- Tokens: 203243 in / 3625 out / 206868 total (reported by provider)
- Tool calls: 26 (1 errors) · tool time 9.07 s
- Rejected actions: 0 · verification attempts 1
- Agent elapsed: 45.88 s
- Cost: $0.0544 (estimate; rates from Nebius Token Factory GET /v1/models?verbose=true (pricing.prompt / pricing.completion), 2026-10-16)

## Limitations
- None recorded.

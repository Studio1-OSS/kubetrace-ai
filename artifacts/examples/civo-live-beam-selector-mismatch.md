# KubeTrace run 20261017-191458-a1c053: selector-mismatch

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
**Incident:** Storefront checkout is down  
**Symptom:** Checkout requests through the Service fail; the Service has no endpoints while Pods are healthy.

Baseline (healthy, before injection):
- ✅ **storefront and probe rolled out**: Deployments available
- ✅ **checkout [{"sku": "MUG-01", "qty": 2}]**: HTTP 200, total 31.92, expected 31.92
- ✅ **checkout [{"sku": "CAP-03", "qty": 12}]**: HTTP 200, total 227.77, expected 227.77
- ✅ **checkout [{"sku": "TEE-02", "qty": 1}, {"sku": "STK-04", "qty": 3}] SAVE10**: HTTP 200, total 41.72, expected 41.72

Fault confirmed before investigation:
- ✅ **no ready endpoints**: 0 endpoints
- ✅ **request through the Service fails**: {"ok": false, "error": "URLError: [Errno 111] Connection refused", "latency_ms": 4}

## Evidence and hypotheses
- *Observation:* Storefront Service selector is `app.kubernetes.io/name: storefront-api`, but the Deployment's Pods are labeled `app.kubernetes.io/name: storefront`; therefore the Service has zero endpoints and every request through it is refused. (service_endpoints storefront: pods_matching_selector=[], k8s/service.yaml: selector app.kubernetes.io/name: storefront-api, deployment labels app.kubernetes.io/name: storefront)

**Agent conclusion (resolved):** The storefront Service selected label `app.kubernetes.io/name: storefront-api`, but the storefront Pods are labeled `app.kubernetes.io/name: storefront`, so the Service had no endpoints and all traffic was refused.

Fixed the Service selector in k8s/service.yaml to `app.kubernetes.io/name: storefront`, applied it, and verified both Pods became endpoints. A real HTTP check through the Service now returns 200 for /healthz and a successful checkout response.

## Attempted changes
### apply_manifest Service/storefront: applied
Reason: Fix Service selector to match storefront Pods.

```diff
--- live/service/storefront
+++ proposed/service/storefront
@@ -20,6 +20,6 @@
     protocol: TCP
     targetPort: http
   selector:
-    app.kubernetes.io/name: storefront-api
+    app.kubernetes.io/name: storefront
   sessionAffinity: None
   type: ClusterIP
```


## Source diff (workspace, from the incident commit)
```diff
diff --git a/k8s/service.yaml b/k8s/service.yaml
index 8f280b5..ea35d4b 100644
--- a/k8s/service.yaml
+++ b/k8s/service.yaml
@@ -7,7 +7,7 @@ metadata:
     kubetrace.ai/experiment: "true"
 spec:
   selector:
-    app.kubernetes.io/name: storefront-api
+    app.kubernetes.io/name: storefront
   ports:
     - name: http
       port: 80
```

## Tests
### `python -m pytest -q -p no:cacheprovider tests`: exit 0 (passed, 0.42 s)
Isolation: docker: --network none, read-only source, no credentials, no Docker socket
```
.............                                                            [100%]
13 passed in 0.02s
```

## Independent verification
Attempt 1 (agent said resolved): passed
- ✅ **selector matches the storefront Pods**: selector {'app.kubernetes.io/name': 'storefront'}, pod labels {'app.kubernetes.io/name': 'storefront', 'kubetrace.ai/experiment': 'true'}
- ✅ **rollout complete**: all replicas updated and ready
- ✅ **pods ready and stable**: 2/2 Ready; restarts 0→0 over 3 s
- ✅ **service endpoints**: 2 ready endpoints
- ✅ **checkout [{"sku": "MUG-01", "qty": 2}]**: HTTP 200, total 31.92, expected 31.92
- ✅ **checkout [{"sku": "CAP-03", "qty": 12}]**: HTTP 200, total 227.77, expected 227.77
- ✅ **checkout [{"sku": "TEE-02", "qty": 1}, {"sku": "STK-04", "qty": 3}] SAVE10**: HTTP 200, total 41.72, expected 41.72
- ✅ **source manifest matches the live selector**: manifest {'app.kubernetes.io/name': 'storefront'}


## Measurements
- Model calls: 26 · model time 85.76 s
- Tokens: 509917 in / 10351 out / 520268 total (reported by provider)
- Tool calls: 47 (1 errors) · tool time 8.17 s
- Rejected actions: 0 · verification attempts 1
- Agent elapsed: 104.04 s
- Cost: $0.1378 (estimate; rates from Nebius Token Factory GET /v1/models?verbose=true (pricing.prompt / pricing.completion), 2026-10-16)

## Limitations
- None recorded.

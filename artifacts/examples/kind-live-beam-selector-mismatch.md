# KubeTrace run 20261017-172219-c35914: selector-mismatch

> **Live run on a local kind cluster**

**Outcome:** resolved. independent verification passed  
**First-attempt success:** True · **Eventual success:** True  
**Provider:** nebius-token-factory · **Model:** `reflection/beam` · **Policy mode:** auto  
**Repository commit:** fd7ef2e5aea0-dirty

**Generation settings:** `{"max_tokens": 2048, "temperature": 0.2}`  
**Prompt / tool schema versions:** 2026-10-17.2 / 2026-10-16.1

## Cluster
- Kind: kind · Kubernetes v1.27.3 · context [hidden]
- Capacity: [{"name": "kubetrace-control-plane", "cpu": "4", "memory": "16356580Ki"}]

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
- ✅ **request through the Service fails**: {"ok": false, "error": "URLError: [Errno 111] Connection refused", "latency_ms": 1}

## Evidence and hypotheses
- *Observation:* The storefront Service selects app.kubernetes.io/name=storefront-api, but the Deployment's Pods are labeled app.kubernetes.io/name=storefront, so the Service has no endpoints and every request fails. (service_endpoints storefront: pods_matching_selector=[], get_resource Service selector app.kubernetes.io/name=storefront-api, get_resource Deployment pod labels app.kubernetes.io/name=storefront, http_check storefront /healthz: connection refused)

**Agent conclusion (resolved):** The storefront Service selector was set to app.kubernetes.io/name=storefront-api, which did not match the storefront Deployment's Pods (labeled app.kubernetes.io/name=storefront), leaving the Service with no endpoints.

Aligned the Service selector with the Deployment pod labels in k8s/service.yaml and applied it. The Service now has two ready endpoints, health/readiness checks pass, and checkout requests succeed through the Service.

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
### `python -m pytest -q -p no:cacheprovider tests`: exit 0 (passed, 0.55 s)
Isolation: docker: --network none, read-only source, no credentials, no Docker socket
```
.............                                                            [100%]
13 passed in 0.02s
```
### `ruff check --no-cache storefront tests`: exit 0 (passed, 0.25 s)
Isolation: docker: --network none, read-only source, no credentials, no Docker socket
```
All checks passed!
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
- Model calls: 29 · model time 65.0 s
- Tokens: 493848 in / 8471 out / 502319 total (reported by provider)
- Tool calls: 48 (0 errors) · tool time 1.75 s
- Rejected actions: 0 · verification attempts 1
- Agent elapsed: 70.04 s
- Cost: $0.1319 (estimate; rates from Nebius Token Factory GET /v1/models?verbose=true (pricing.prompt / pricing.completion), 2026-10-16)

## Limitations
- None recorded.

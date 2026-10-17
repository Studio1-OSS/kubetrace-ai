# KubeTrace run 20261017-190432-ce5aa7: application-bug

> **Live run on a local kind cluster**

**Outcome:** resolved. independent verification passed  
**First-attempt success:** True · **Eventual success:** True  
**Provider:** nebius-token-factory · **Model:** `reflection/beam` · **Policy mode:** auto  
**Repository commit:** 8633a9d531f0-dirty

**Generation settings:** `{"max_tokens": 2048, "temperature": 0.2}`  
**Prompt / tool schema versions:** 2026-10-17.2 / 2026-10-16.1

## Cluster
- Kind: kind · Kubernetes v1.27.3 · context [hidden]
- Capacity: [{"name": "kubetrace-control-plane", "cpu": "4", "memory": "16356580Ki"}]

## Issue
**Incident:** Large checkout orders fail with 500  
**Symptom:** POST /api/checkout returns HTTP 500 for orders of 30 or more units of one item; smaller orders work.

Baseline (healthy, before injection):
- ✅ **storefront and probe rolled out**: Deployments available
- ✅ **checkout [{"sku": "MUG-01", "qty": 2}]**: HTTP 200, total 31.92, expected 31.92
- ✅ **checkout [{"sku": "CAP-03", "qty": 12}]**: HTTP 200, total 227.77, expected 227.77
- ✅ **checkout [{"sku": "TEE-02", "qty": 1}, {"sku": "STK-04", "qty": 3}] SAVE10**: HTTP 200, total 41.72, expected 41.72

Fault confirmed before investigation:
- ✅ **30-unit order returns 500**: HTTP 500
- ✅ **small order still works**: HTTP 200

## Evidence and hypotheses

**Agent conclusion (resolved):** bulk_rate in storefront/pricing.py indexed BULK_TIERS with qty // 10 without capping, so quantities of 20+ (e.g. 30 mugs) produced index 3 and raised IndexError, causing 500. Docs specify 20+ units get 10% with no upper limit.

Fixed bulk discount tier lookup to cap at the last tier, added regression tests for 30 and 500 units, built and deployed a new image, and verified the storefront rollout is complete with a successful 30-mug checkout returning 200.

## Attempted changes
### deploy_image Deployment/storefront: applied
Reason: Deploy fixed pricing code.

```diff
--- live/deployment/storefront
+++ proposed/deployment/storefront
@@ -30,8 +30,8 @@
       containers:
       - env:
         - name: APP_VERSION
-          value: release-a3b55329808e
-        image: kubetrace/storefront:release-a3b55329808e
+          value: 20261017-190432-ce5aa7-88c804a3-b1
+        image: kubetrace/storefront:20261017-190432-ce5aa7-88c804a3-b1
         imagePullPolicy: IfNotPresent
         livenessProbe:
           failureThreshold: 3
```


## Source diff (workspace, from the incident commit)
```diff
diff --git a/k8s/deployment.yaml b/k8s/deployment.yaml
index 4bf06e8..d2dc07c 100644
--- a/k8s/deployment.yaml
+++ b/k8s/deployment.yaml
@@ -23,7 +23,7 @@ spec:
         runAsUser: 10001
       containers:
         - name: storefront
-          image: kubetrace/storefront:release-a3b55329808e
+          image: kubetrace/storefront:20261017-190432-ce5aa7-88c804a3-b1
           imagePullPolicy: IfNotPresent
           ports:
             - name: http
diff --git a/storefront/pricing.py b/storefront/pricing.py
index 95ff59a..feabb4b 100644
--- a/storefront/pricing.py
+++ b/storefront/pricing.py
@@ -40,7 +40,9 @@ def money(value: Decimal) -> Decimal:
 
 
 def bulk_rate(qty: int) -> Decimal:
-    return BULK_TIERS[qty // 10]
+    # 1-9: none, 10-19: 5%, 20+: 10% (no upper limit on quantity).
+    tier = min(qty // 10, len(BULK_TIERS) - 1)
+    return BULK_TIERS[tier]
 
 
 def quote(items: list[dict], coupon: str | None, config: PricingConfig) -> dict:
diff --git a/tests/test_pricing.py b/tests/test_pricing.py
index f93b707..2b14b51 100644
--- a/tests/test_pricing.py
+++ b/tests/test_pricing.py
@@ -28,6 +28,15 @@ def test_freeship_coupon():
     assert q["shipping"] == "0.00"
 
 
+def test_bulk_line_gets_ten_percent_with_no_upper_limit():
+    q = quote([{"sku": "MUG-01", "qty": 30}], None, CFG)
+    assert (q["bulk_discount"], q["shipping"], q["tax"], q["total"]) == ("36.00", "0.00", "25.92", "349.92")
+
+
+def test_bulk_handles_maximum_quantity():
+    q = quote([{"sku": "MUG-01", "qty": 500}], None, CFG)
+    assert q["bulk_discount"] == "600.00"
+
 @pytest.mark.parametrize("items", [[], [{"sku": "NOPE", "qty": 1}], [{"sku": "MUG-01", "qty": 0}]])
 def test_bad_orders_are_rejected(items):
     with pytest.raises(PricingError):
```

## Tests
### `python -m pytest -q -p no:cacheprovider tests`: exit 0 (passed, 0.41 s)
Isolation: docker: --network none, read-only source, no credentials, no Docker socket
```
...............                                                          [100%]
15 passed in 0.02s
```
### `ruff check --no-cache storefront tests`: exit 0 (passed, 0.21 s)
Isolation: docker: --network none, read-only source, no credentials, no Docker socket
```
All checks passed!
```
### `python -m pytest -q -p no:cacheprovider tests`: exit 0 (passed, 0.38 s)
Isolation: docker: --network none, read-only source, no credentials, no Docker socket
```
...............                                                          [100%]
15 passed in 0.02s
```

## Images built
- `kubetrace/storefront:20261017-190432-ce5aa7-88c804a3-b1` from commit 88c804a33a (3.2 s)

## Rollouts
- storefront: complete=True after 3.1 s (2/2 ready)

## Independent verification
Attempt 1 (agent said resolved): passed
- ✅ **running a new image built in this run**: deployment image kubetrace/storefront:20261017-190432-ce5aa7-88c804a3-b1
- ✅ **rollout complete**: all replicas updated and ready
- ✅ **pods ready and stable**: 2/2 Ready; restarts 0→0 over 5 s
- ✅ **service endpoints**: 2 ready endpoints
- ✅ **checkout [{"sku": "MUG-01", "qty": 2}]**: HTTP 200, total 31.92, expected 31.92
- ✅ **checkout [{"sku": "CAP-03", "qty": 12}]**: HTTP 200, total 227.77, expected 227.77
- ✅ **checkout [{"sku": "TEE-02", "qty": 1}, {"sku": "STK-04", "qty": 3}] SAVE10**: HTTP 200, total 41.72, expected 41.72
- ✅ **checkout [{"sku": "MUG-01", "qty": 30}]**: HTTP 200, total 349.92, expected 349.92
- ✅ **checkout [{"sku": "TEE-02", "qty": 45}] SAVE10**: HTTP 200, total 944.78, expected 944.78
- ✅ **checkout [{"sku": "CAP-03", "qty": 500}]**: HTTP 200, total 8991.00, expected 8991.00
- ✅ **no exception handling added to hide the error**: added lines: no try/except added in storefront/
- ✅ **hidden pricing tests pass on the final source**: ...............................                                          [100%]
31 passed in 0.03s

- ✅ **original tests kept**: every original test function is still present
- ✅ **agent-added regression test fails on the buggy code**: tests added: tests/test_pricing.py; on buggy code exit 1
- ✅ **source manifest records the deployed image**: manifest kubetrace/storefront:20261017-190432-ce5aa7-88c804a3-b1


## Measurements
- Model calls: 36 · model time 62.41 s
- Tokens: 584196 in / 6905 out / 591101 total (reported by provider)
- Tool calls: 48 (2 errors) · tool time 8.92 s
- Rejected actions: 0 · verification attempts 1
- Agent elapsed: 77.64 s
- Cost: $0.153 (estimate; rates from Nebius Token Factory GET /v1/models?verbose=true (pricing.prompt / pricing.completion), 2026-10-16)

## Limitations
- None recorded.

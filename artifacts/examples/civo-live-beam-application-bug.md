# KubeTrace run 20261017-192915-dba4c6: application-bug

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
- *Observation:* Large orders (qty >= 30) crash in bulk_rate because BULK_TIERS has only 3 entries and qty//10 exceeds index 2. (http_check storefront /api/checkout qty=30 -> 500, logs storefront-d64f6b7b7-rfbj4 traceback IndexError at pricing.py:43 BULK_TIERS[qty // 10], docs/pricing.md rule 2: 20 or more units 10% with no upper limit)
- *Hypothesis:* Root cause is an off-by-one/out-of-range lookup in bulk_rate; should cap the tier index at 2 so 20+ units get 10% with no upper limit. (pricing.py lines 14-15, 42-43, docs/pricing.md line 9)

**Agent conclusion (resolved):** bulk_rate indexed BULK_TIERS with qty // 10 without capping; quantities of 20+ (e.g. 30 mugs) produced index 3, out of range, causing an unhandled IndexError and HTTP 500.

Fixed bulk_rate to cap the tier index at the top 10% tier, added a regression test for 30-unit orders, rebuilt and deployed the storefront image, and verified the checkout now returns 200 with the expected total.

## Attempted changes
### deploy_image Deployment/storefront: applied
Reason: Roll storefront to build containing bulk_rate fix.

```diff
--- live/deployment/storefront
+++ proposed/deployment/storefront
@@ -30,8 +30,8 @@
       containers:
       - env:
         - name: APP_VERSION
-          value: 1230e3f0a24da92b9c430218d30c7f06288f3a86eeab903a4c1814ac26e40e1
-        image: [registry]/storefront@sha256:1230e3f0a24da92b9c430218d30c7f06288f3a86eeab903a4c1814ac26e40e19
+          value: 2be43a56ee0a070d23cf24b7ed93c394abe3f9ead354ca4c7d2f0c4b6eeef85
+        image: [registry]/storefront@sha256:2be43a56ee0a070d23cf24b7ed93c394abe3f9ead354ca4c7d2f0c4b6eeef85a
         imagePullPolicy: IfNotPresent
         livenessProbe:
           failureThreshold: 3
```


## Source diff (workspace, from the incident commit)
```diff
diff --git a/k8s/deployment.yaml b/k8s/deployment.yaml
index 838abcc..2bc9415 100644
--- a/k8s/deployment.yaml
+++ b/k8s/deployment.yaml
@@ -23,7 +23,7 @@ spec:
         runAsUser: 10001
       containers:
         - name: storefront
-          image: [registry]/storefront@sha256:1230e3f0a24da92b9c430218d30c7f06288f3a86eeab903a4c1814ac26e40e19
+          image: [registry]/storefront@sha256:2be43a56ee0a070d23cf24b7ed93c394abe3f9ead354ca4c7d2f0c4b6eeef85a
           imagePullPolicy: IfNotPresent
           ports:
             - name: http
diff --git a/storefront/pricing.py b/storefront/pricing.py
index 95ff59a..e060182 100644
--- a/storefront/pricing.py
+++ b/storefront/pricing.py
@@ -40,7 +40,7 @@ def money(value: Decimal) -> Decimal:
 
 
 def bulk_rate(qty: int) -> Decimal:
-    return BULK_TIERS[qty // 10]
+    return BULK_TIERS[min(qty // 10, len(BULK_TIERS) - 1)]
 
 
 def quote(items: list[dict], coupon: str | None, config: PricingConfig) -> dict:
diff --git a/tests/test_pricing.py b/tests/test_pricing.py
index f93b707..5cdc48b 100644
--- a/tests/test_pricing.py
+++ b/tests/test_pricing.py
@@ -32,3 +32,8 @@ def test_freeship_coupon():
 def test_bad_orders_are_rejected(items):
     with pytest.raises(PricingError):
         quote(items, None, CFG)
+
+
+def test_large_order_gets_top_bulk_tier():
+    q = quote([{"sku": "MUG-01", "qty": 30}], None, CFG)
+    assert (q["bulk_discount"], q["shipping"], q["tax"], q["total"]) == ("36.00", "0.00", "25.92", "349.92")
```

## Tests
### `python -m pytest -q -p no:cacheprovider tests`: exit 0 (passed, 0.45 s)
Isolation: docker: --network none, read-only source, no credentials, no Docker socket
```
..............                                                           [100%]
14 passed in 0.02s
```

## Images built
- `[registry]/storefront@sha256:2be43a56ee0a070d23cf24b7ed93c394abe3f9ead354ca4c7d2f0c4b6eeef85a` from commit 5a5ab07f4f (33.5 s)

## Rollouts
- storefront: complete=True after 6.5 s (2/2 ready)

## Independent verification
Attempt 1 (agent said resolved): passed
- ✅ **running a new image built in this run**: deployment image [registry]/storefront@sha256:2be43a56ee0a070d23cf24b7ed93c394abe3f9ead354ca4c7d2f0c4b6eeef85a
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
- ✅ **hidden pricing tests pass on the final source**: ..............................                                           [100%]
30 passed in 0.03s

- ✅ **original tests kept**: every original test function is still present
- ✅ **agent-added regression test fails on the buggy code**: tests added: tests/test_pricing.py; on buggy code exit 1
- ✅ **source manifest records the deployed image**: manifest [registry]/storefront@sha256:2be43a56ee0a070d23cf24b7ed93c394abe3f9ead354ca4c7d2f0c4b6eeef85a


## Measurements
- Model calls: 26 · model time 79.03 s
- Tokens: 468412 in / 5844 out / 474256 total (reported by provider)
- Tool calls: 41 (0 errors) · tool time 52.45 s
- Rejected actions: 0 · verification attempts 1
- Agent elapsed: 143.1 s
- Cost: $0.1229 (estimate; rates from Nebius Token Factory GET /v1/models?verbose=true (pricing.prompt / pricing.completion), 2026-10-16)

## Limitations
- None recorded.

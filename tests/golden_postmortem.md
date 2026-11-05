# Post-Mortem: Checkout down

- Incident: inc-0001
- Severity: SEV1
- Status: postmortem
- Service: checkout
- Tenant: acme
- Declared: 2026-01-01T00:00:00Z

## Summary

Checkout down (SEV1) on service checkout for tenant acme.

## Timeline

- 2026-01-01T00:00:00Z [created] Incident declared from alert pager/checkout-down (SEV1) (alertmanager)
- 2026-01-01T00:10:00Z [transition] Status changed triggered -> acknowledged (oncall)
- 2026-01-01T00:10:00Z [note] Investigating database saturation. (oncall)
- 2026-01-01T00:10:00Z [note] TODO: add connection pool alert @priya (oncall)
- 2026-01-01T00:30:00Z [transition] Status changed acknowledged -> mitigated (oncall)
- 2026-01-01T00:30:00Z [note] ACTION: raise pool limit [owner: sam] (oncall)
- 2026-01-01T01:00:00Z [transition] Status changed mitigated -> resolved (oncall)
- 2026-01-01T01:00:00Z [transition] Status changed resolved -> postmortem (oncall)

## Impact

Checkout unavailable for all customers.

Linked traces: trace-0001

## Durations

- Time to acknowledge: 600s
- Time to mitigate: 1800s
- Time to resolve: 3600s

## Root Cause

_To be completed by the incident owner._

## Action Items

| # | Action Item | Owner |
|---|-------------|-------|
| 1 | add connection pool alert | priya |
| 2 | raise pool limit | sam |

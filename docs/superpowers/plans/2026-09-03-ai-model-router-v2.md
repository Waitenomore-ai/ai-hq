# AI Model Router Implementation Plan — refreshed from current main

**Date:** 2026-09-03
**Branch:** `feature/ai-model-router-v2`
**Base:** `6bb37e7c9687463c62ccf3b80820e44f47987cca`
**Design source:** Approved Phase 1 design plus zero-cost/local-first operating constraints.

## Goal

Add a provider-independent routing layer where agents request capability classes rather than hard-coded models, with local/free-first selection, deterministic fallback, durable usage accounting, and hard paid-execution disablement by default.

## Safety and cost invariants

- Agents request capability classes only.
- Disabled/unavailable endpoints are never selected.
- `local_private` requests only route to explicitly local/private endpoints.
- Routing priority is: capable local zero-cost -> capable free-tier zero-cost -> no route.
- Paid execution is disabled by default and cannot be selected unless a future explicit user-controlled setting enables it.
- Duplicate-account/quota-circumvention behavior is not supported.
- Credentials are never stored in router/usage records.
- Fallback is deterministic and auditable.
- Usage accounting records provider, model, agent, mission, token counts, estimated cost and timestamp, including zero-cost usage.
- Budget/quota exhaustion degrades to a controlled no-route result.
- No external model API invocation is introduced in this phase.

## Tasks

1. Add RED tests for capability routing, local/free-first ordering, provider fallback, local/private constraints, paid-default denial, disabled providers, and no-route behavior.
2. Implement model endpoint/registry/router primitives.
3. Add RED tests for durable usage accounting and daily/monthly cost budgets/free quotas.
4. Implement usage model, migration and accounting service.
5. Integrate budget/quota-aware routing.
6. Register router metadata with Alembic.
7. Add authenticated read-only routing/usage status API without provider invocation or secret exposure.
8. Run lint, full tests and Compose validation on the exact feature head.
9. Fast-forward `main` only if the exact feature head is green and branch is ahead/0 behind.

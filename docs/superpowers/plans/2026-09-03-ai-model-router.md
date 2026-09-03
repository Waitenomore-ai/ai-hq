# AI Model Router Implementation Plan

**Date:** 2026-09-03
**Branch:** `feature/ai-model-router`
**Design source:** Approved Phase 1 design, sections 15, 18, 19, 21 and 24.

## Goal

Add a provider-independent routing layer where agents request capability classes rather than hard-coded model names, with provider fallback, local/private routing, durable usage accounting, and graceful cost-budget exhaustion.

## Safety invariants

- Agents request capability classes; they do not choose arbitrary provider/model identifiers.
- Disabled or unavailable models are never selected.
- `local_private` requests may only route to models explicitly marked local/private.
- Provider/model credentials are not stored by the router or usage ledger.
- Routing fallback is deterministic and auditable.
- Budget exhaustion returns a controlled no-route result; it does not mutate mission state or silently use a more expensive model.
- Usage accounting records provider, model, agent, mission, tokens, estimated cost and timestamp.
- Cost estimates are derived from configured rates and never treated as billing-source truth.
- No real external model API call is introduced in this phase; provider adapters remain a later integration boundary.

## Tasks

1. Add RED tests for capability routing, provider fallback, local/private constraints, disabled providers, and no-route behavior.
2. Add model endpoint/registry/router primitives.
3. Add RED tests for durable usage accounting and daily/monthly budgets.
4. Add usage model, migration and accounting service.
5. Integrate budget-aware routing using accumulated usage totals.
6. Register model metadata with Alembic.
7. Add authenticated read-only routing/usage status API for the HQ interface, without exposing secrets or invoking providers.
8. Run lint, full tests and Compose validation on the exact feature head.
9. Fast-forward `main` only when exact-head CI is green and the branch is ahead with zero divergence.

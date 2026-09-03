# Knowledge Core Implementation Plan

**Date:** 2026-09-03
**Branch:** `feature/knowledge-core`
**Design source:** Approved Phase 1 design, section 8.

## Goal

Implement durable operational memory with provenance, verification, contradiction handling, expiry, agent scoping, user controls, and authenticated APIs. No inference may silently become a confirmed fact.

## Safety invariants

- Inferred content defaults to an inferred/unverified state, never confirmed.
- Confirmed facts require an explicitly confirmed verification state.
- Contradictions are surfaced as separate records/links and never silently overwrite an active memory.
- Soft-deleted and expired working memories are excluded from active retrieval.
- Restricted memories are returned only to explicitly allowed agents.
- Locked memories cannot be edited or deleted until explicitly unlocked.
- Knowledge storage must not be used for raw credentials or secrets.
- Browser write routes require the existing authenticated session and CSRF protection.

## Tasks

1. Add RED tests for memory lifecycle, verification rules, expiry, contradiction handling, locking, deletion, and agent-scoped retrieval.
2. Add durable SQLAlchemy models and Alembic migration.
3. Implement `KnowledgeService` for create/search/get/update/delete/verify/contradiction operations.
4. Add authenticated Knowledge API routes with CSRF on mutation endpoints.
5. Register models with Alembic/application metadata.
6. Add API tests proving unauthenticated rejection, active-only retrieval, provenance visibility, and mutation CSRF.
7. Run lint, full tests, and Compose validation on the exact feature head.
8. Fast-forward `main` only if the branch is ahead with zero divergence and the exact head is green.

# Notification Engine Implementation Plan

**Date:** 2026-09-03
**Branch:** `feature/notification-engine`
**Design source:** Approved Phase 1 design, section 14.

## Goal

Add durable in-app notifications for Information, Attention, Approval Required, and Critical events, with related-alert consolidation, read/dismiss controls, and an authenticated API suitable for the HQ interface.

## Safety invariants

- Notifications are durable PostgreSQL records; Redis is not the system of record.
- Related active alerts consolidate by an explicit `group_key` rather than producing notification storms.
- Consolidation preserves occurrence count and first/last occurrence times.
- Raw credentials, passwords, tokens, API keys, session secrets, and similar secret material must never be stored in notification title/message/metadata.
- Read/dismiss state does not delete historical notification data.
- Browser mutations require the existing authenticated session and CSRF protection.
- Notification delivery is in-app only for Phase 1; browser/PWA/mobile channels remain future adapters.

## Tasks

1. Add RED tests for severity, consolidation, read/dismiss state, ordering, and secret rejection.
2. Add durable model + Alembic migration.
3. Implement `NotificationService`.
4. Add authenticated list/detail/count/read/read-all/dismiss APIs with CSRF on mutations.
5. Register model/migration metadata and install API routes.
6. Add API tests proving authentication, CSRF, unread counts, and state transitions.
7. Run lint, full tests, and Compose validation on the exact feature head.
8. Fast-forward `main` only when exact-head CI is green and the branch is ahead with zero divergence.

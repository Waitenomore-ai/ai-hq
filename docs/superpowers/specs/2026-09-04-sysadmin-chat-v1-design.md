# SysAdmin Chat v1 — Design Specification

**Date:** 2026-09-04
**Status:** Approved design
**Repository:** `Waitenomore-ai/ai-hq`

## Goal

Make the existing live SysAdmin agent directly conversational from the AI HQ web interface while preserving the proven Tool Gateway and Host Helper safety boundary.

## Scope

v1 is intentionally narrow so it can ship quickly. One authenticated user talks to SysAdmin. The chat supports ordinary conversational replies and read-only operational requests. It does not enable restart, deploy, rollback, shell execution, arbitrary tools, or any new mutation capability.

## Architecture

The browser sends an authenticated message to a SysAdmin chat API. A chat controller stores the user message and conversation state, classifies whether the request is conversational or requires operational evidence, and uses the existing AI model routing/execution facilities for language generation where an executable model provider is configured.

Operational questions never grant the model direct server access. The controller converts only supported read intents into persisted mission plans using the existing MissionService. The existing autonomous worker executes those plans through MissionExecutor -> ToolGateway -> SafetyService -> registered read-only adapters -> Host Helper. The chat controller reads terminal mission results and turns them into a concise response. Unsupported write requests are refused as unavailable in v1.

The AI model router remains provider-independent. Chat must fail clearly when no executable model endpoint is configured; it must not silently pretend a deterministic response is an LLM response.

## Supported operational intents

SysAdmin Chat v1 may request only the capabilities already proven in production:

- `system.health.read`
- `service.status.read`
- `service.logs.read`

A general request such as “How is my server?” may create one mission containing all three steps. Requests specifically about health, service state, or logs may use the minimum required subset.

## Safety invariants

- Chat has no direct Host Helper or subprocess access.
- Chat cannot execute a tool itself.
- Every operational action is a persisted mission step.
- ToolRegistry validation occurs when a plan is created.
- Existing exact permissions, SafetyService policy, ToolGateway decisions, simulation policy, and ledger recording remain authoritative.
- Mutation requests are not translated into plans in v1.
- Prompt text cannot choose arbitrary tool names or arguments.
- Target is restricted to the registered `ai-hq` operational target.

## Persistence

Add persisted chat conversations and messages. A conversation belongs to the authenticated user and an agent key (`sysadmin`). Messages record role, text, timestamps, and an optional mission ID so operational answers can be traced back to the mission that produced them.

Refreshing the browser restores the conversation. The API must never expose another user's conversation.

## API

Authenticated endpoints provide:

- create/list SysAdmin conversations
- read messages for one owned conversation
- submit a user message
- poll the submitted message/mission until the assistant response is ready

The first implementation may use HTTP polling rather than WebSockets/SSE. This keeps deployment small and reliable while still allowing the UI to show `Checking server health…` during mission execution.

## Web UI

Add a SysAdmin chat view to the existing AI HQ interface rather than replacing the HQ. It contains:

- SysAdmin identity and online/read-only status
- scrollable persisted message history
- text composer and send button
- working indicator while a mission is running
- concise assistant response
- optional expandable mission details for operational answers
- explicit read-only badge so current authority is visible

The layout must remain usable on desktop and mobile.

## LLM behavior

SysAdmin's system instruction defines its role, concise conversational tone, read-only authority, and requirement to base operational claims on mission results. The model may phrase and summarize results but may not invent tool results, claim an operation ran without a completed mission, or expand its own permissions.

The existing model registry/router selects an appropriate endpoint. Provider invocation is kept behind a small chat model client interface so provider implementations remain replaceable.

## Failure behavior

- No model available: return a clear configuration error without fabricating an AI response.
- Mission failure: persist an assistant response explaining that the inspection failed and include the safe error summary.
- Mission timeout: leave the mission intact and return a still-working state; polling can continue.
- Unsupported mutation: respond that SysAdmin currently has read-only authority and the requested operation is not enabled.
- Authentication/ownership failure: 401/404 without leaking conversation existence.

## Testing

Tests cover persistence and ownership, intent/tool allowlisting, mutation refusal, model-unavailable behavior, mission creation, terminal mission result rendering, authenticated API behavior, and the browser chat shell. Existing autonomous mission and Tool Gateway tests remain regression gates. Full pytest and Alembic-head checks must pass before deployment.

## Delivery boundary

v1 is complete when the authenticated production AI HQ page lets the user type “How is my server doing?”, the request produces a safe read-only mission through the existing autonomous pipeline, and SysAdmin returns a conversational answer grounded in that mission's results. Expanding chat to Commander/other departments and enabling approved write operations are subsequent stages.

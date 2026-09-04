# SysAdmin Chat v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the authenticated AI HQ user converse with SysAdmin and turn supported read-only operational questions into the existing autonomous mission pipeline.

**Architecture:** Add a focused chat domain with persisted conversations/messages, an allowlisted intent planner, and a provider-independent model client. Add authenticated HTTP endpoints and extend the existing HQ room inspector with a SysAdmin chat panel using polling. Operational execution remains exclusively MissionService -> worker -> ToolGateway -> SafetyService -> read-only adapters -> Host Helper.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, Alembic, Jinja2, vanilla JS/CSS, pytest.

**Spec:** `docs/superpowers/specs/2026-09-04-sysadmin-chat-v1-design.md`

## Global Constraints

- v1 agent is `sysadmin` only.
- Operational capabilities are exactly `system.health.read`, `service.status.read`, and `service.logs.read`.
- Operational target is exactly `ai-hq`.
- No restart, deploy, rollback, shell, arbitrary tool selection, or other mutation capability.
- Chat never invokes Host Helper directly.
- An LLM may phrase/summarize evidence but may not invent operational results.
- Existing authentication, CSRF/origin protections, mission safety, permissions, Tool Gateway and ledger remain authoritative.
- HTTP polling is sufficient for v1; no WebSocket/SSE requirement.

---

### Task 1: Persist SysAdmin conversations and messages

**Files:**
- Create: `src/ai_hq/chat/__init__.py`
- Create: `src/ai_hq/chat/models.py`
- Create: `src/ai_hq/chat/service.py`
- Create: `migrations/versions/0011_sysadmin_chat.py`
- Create: `tests/test_chat_service.py`

**Interfaces:**
- Produces `ChatService.create_conversation(owner_session_id, agent_key='sysadmin')`
- Produces `ChatService.list_conversations(owner_session_id)`
- Produces `ChatService.add_message(conversation_id, owner_session_id, role, content, mission_id=None)`
- Produces `ChatService.messages(conversation_id, owner_session_id)`

- [ ] Write failing service tests proving conversation ownership, ordered messages, optional mission linkage, and cross-session denial.
- [ ] Run `./.venv/bin/pytest tests/test_chat_service.py -q` and confirm failure.
- [ ] Implement `ChatConversation` and `ChatMessage` with UUID string IDs, owner session ID, `sysadmin` agent key, timestamps, role/content, and nullable mission ID.
- [ ] Implement `ChatService` with ownership enforced in every conversation lookup.
- [ ] Add Alembic revision `0011_sysadmin_chat` after `0010_mission_steps`, including indexes on owner/conversation and cascade deletion of messages.
- [ ] Run the focused tests and `./.venv/bin/alembic heads`; expect PASS and exactly `0011_sysadmin_chat (head)`.
- [ ] Commit: `feat: persist sysadmin chat conversations`.

### Task 2: Add a hard-allowlisted operational intent planner

**Files:**
- Create: `src/ai_hq/chat/intents.py`
- Create: `tests/test_chat_intents.py`

**Interfaces:**
- Produces `ChatIntent(kind, steps, refusal_reason)`.
- Produces `plan_sysadmin_intent(text: str) -> ChatIntent`.
- `steps` contains only MissionService plan dictionaries with a fixed `target='ai-hq'`.

- [ ] Write failing tests for general health inspection, health-only, status-only, logs-only, normal conversation, and explicit restart/deploy/rollback/shell refusal.
- [ ] Run the focused tests and confirm failure.
- [ ] Implement deterministic intent recognition. General server-health wording maps to all three read tools; narrow wording maps to the minimum subset. Mutation wording maps to `refused`; all other text maps to `conversation`.
- [ ] Assert in tests that user text can never become a tool name or target and that the produced tool-name set is a subset of the three global capabilities.
- [ ] Run focused tests and commit: `feat: constrain sysadmin chat operational intents`.

### Task 3: Add the chat model boundary without weakening provider independence

**Files:**
- Create: `src/ai_hq/chat/model_client.py`
- Modify: `src/ai_hq/config.py`
- Modify: `.env.example`
- Create: `tests/test_chat_model_client.py`

**Interfaces:**
- Produces `ChatModelClient.reply(system_prompt: str, messages: list[dict[str,str]]) -> str`.
- Produces `build_chat_model_client(settings) -> ChatModelClient | None`.

- [ ] Write failing tests for configured client construction, missing-provider behavior, bounded timeout/error conversion, and response text extraction.
- [ ] Run focused tests and confirm failure.
- [ ] Add narrowly scoped chat model configuration fields. Secrets remain environment-only and must never be logged or persisted in chat rows.
- [ ] Implement one executable provider adapter behind `ChatModelClient`; keep HTTP/provider details inside this module. Return `None` when no executable endpoint is configured.
- [ ] Add the configuration keys to `.env.example` without real credentials.
- [ ] Run focused tests and commit: `feat: add sysadmin chat model client`.

### Task 4: Orchestrate chat, missions, and grounded replies

**Files:**
- Create: `src/ai_hq/chat/controller.py`
- Create: `tests/test_chat_controller.py`

**Interfaces:**
- Produces `SysAdminChatController.submit(conversation_id, owner_session_id, text) -> ChatSubmission`.
- Produces `SysAdminChatController.refresh(conversation_id, owner_session_id) -> ChatState`.
- Consumes `ChatService`, `MissionService`, `plan_sysadmin_intent`, and optional `ChatModelClient`.

- [ ] Write failing tests for ordinary conversation, mutation refusal, read mission creation, pending mission state, completed grounded response, failed mission response, and no-model configuration error.
- [ ] Run focused tests and confirm failure.
- [ ] Implement ordinary conversation via the model client using a SysAdmin system instruction that explicitly forbids invented operational state.
- [ ] For read intents, persist the user message, create one `sysadmin` mission, create its allowlisted plan, attach the mission ID to chat state, and return `working` without directly executing tools.
- [ ] On refresh, inspect persisted mission/steps. For COMPLETED, build evidence only from stored step results and ask the model to summarize that evidence; for FAILED, persist a concise safe failure reply; for nonterminal states return `working` without duplicating messages.
- [ ] For refused mutation intents, persist a deterministic read-only refusal without invoking the model or creating a mission.
- [ ] Run focused tests and commit: `feat: orchestrate sysadmin chat missions`.

### Task 5: Expose authenticated chat API

**Files:**
- Create: `src/ai_hq/chat/api.py`
- Modify: `src/ai_hq/app.py`
- Create: `tests/test_chat_api.py`

**Interfaces:**
- `POST /api/chat/sysadmin/conversations`
- `GET /api/chat/sysadmin/conversations`
- `GET /api/chat/sysadmin/conversations/{id}/messages`
- `POST /api/chat/sysadmin/conversations/{id}/messages`
- `GET /api/chat/sysadmin/conversations/{id}/state`

- [ ] Write failing API tests for authentication, ownership, submit, poll/state, mutation refusal, and invalid/oversized messages.
- [ ] Run focused tests and confirm failure.
- [ ] Install chat routes from `create_app`; resolve the existing signed session for every endpoint and use its durable session identifier as owner key.
- [ ] Require same-origin/CSRF protection on POST endpoints using the same security contract as existing authenticated writes; cap message size and reject blank content.
- [ ] Return stable JSON containing conversation/message IDs, state (`ready|working|error`), optional mission ID, and messages.
- [ ] Run focused tests and commit: `feat: expose authenticated sysadmin chat api`.

### Task 6: Add SysAdmin chat to the existing HQ interface

**Files:**
- Modify: `src/ai_hq/templates/home.html`
- Modify: `src/ai_hq/static/hq.js`
- Modify: `src/ai_hq/static/hq.css`
- Modify/Create UI assertions in the existing HQ interface test module.

**Interfaces:**
- Clicking/tapping the existing `data-room-key='sysadmin'` room opens the chat controls in the room detail area.
- Browser uses the Task 5 API and the existing `root_path`.

- [ ] Add failing UI assertions for SysAdmin chat history, composer, send button, `READ ONLY` authority label, accessible status text, and root-path-safe API hooks.
- [ ] Run the focused UI test and confirm failure.
- [ ] Extend the room inspector so SysAdmin selection exposes chat while other rooms retain their existing inspector behavior.
- [ ] Add JS that creates/restores a conversation, posts messages, renders text with DOM `textContent`, polls while state is `working`, disables duplicate sends, and shows a concise recoverable error.
- [ ] Add responsive CSS using the existing HQ visual language; preserve desktop floor and make the composer usable on phone/tablet widths.
- [ ] Run focused UI tests and commit: `feat: add sysadmin chat to hq interface`.

### Task 7: Full safety/regression gate and production deployment

**Files:**
- Modify only files required by failures discovered in this gate.

**Interfaces:**
- Production success path: authenticated user -> SysAdmin room -> message -> persisted mission -> autonomous worker -> ToolGateway -> Host Helper -> persisted result -> grounded assistant reply.

- [ ] Run `./.venv/bin/pytest -q`; require zero failures.
- [ ] Run `./.venv/bin/alembic heads`; require exactly `0011_sysadmin_chat (head)`.
- [ ] Run `git diff --check`; require clean output.
- [ ] Verify mutation adapters remain absent from the autonomous worker registry and the SysAdmin permission set remains read-only.
- [ ] Deploy through the existing controlled AI HQ release procedure with `/etc/ai-hq/ai-hq.env`; do not run Compose without the production env file.
- [ ] Verify web and worker containers are running and `/health/ready` succeeds.
- [ ] In the production browser, send `How is my server doing?` and require a completed mission with only the three allowed read steps plus a grounded chat response.
- [ ] Send `Restart AI HQ` and require a read-only refusal with zero new mutation mission steps.
- [ ] Record the deployed SHA and commit any final test-only corrections before declaring Chat v1 live.

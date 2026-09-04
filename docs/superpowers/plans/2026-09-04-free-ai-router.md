# Free AI Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route SysAdmin conversational inference through multiple explicitly zero-cost AI providers with automatic failover and no paid fallback.

**Architecture:** Preserve the existing `ChatModelClient` boundary. Add provider definitions and `FreeModelRouter` above the existing `OpenAICompatibleChatModelClient`; build configured providers in deterministic local -> Groq -> OpenRouter free -> explicitly configured Hugging Face order. Legacy `CHAT_MODEL_*` remains a separate compatibility fallback only when no free provider is configured.

**Tech Stack:** Python, Pydantic settings, httpx, pytest, FastAPI existing AI HQ stack.

**Spec:** `docs/superpowers/specs/2026-09-04-free-ai-router-design.md`

## Global Constraints

- No paid inference fallback.
- OpenRouter model is exactly `openrouter/free`.
- Local provider has highest priority.
- Provider secrets must never appear in user errors or logs.
- Existing SysAdmin operational permissions remain unchanged.
- Models never bypass MissionExecutor / ToolGateway / SafetyService.
- TDD: observe RED before production implementation.
- Full regression suite must pass before deployment.

---

### Task 1: Provider definitions and free router

**Files:**
- Create: `src/ai_hq/chat/free_model_router.py`
- Modify: `src/ai_hq/chat/model_client.py` only if a small reusable interface change is required
- Test: `tests/test_free_model_router.py`

**Interfaces:**
- `FreeModelProvider`
- `FreeModelRouter`
- `FreeModelRouter.reply(system_prompt, messages) -> str`
- consumes existing `ChatModelClient`
- raises existing `ChatModelError`

Steps:
- [ ] Write tests for deterministic ordering and failover.
- [ ] Run targeted tests and verify RED.
- [ ] Implement minimal provider/router types.
- [ ] Verify targeted tests GREEN.
- [ ] Commit.

### Task 2: Free-provider configuration

**Files:**
- Modify the existing AI HQ Settings module.
- Modify: `.env.example`
- Modify: `src/ai_hq/chat/model_client.py`
- Test: `tests/test_free_model_router.py`
- Test: `tests/test_chat_model_client.py`

**Interfaces:**
- `build_chat_model_client(settings) -> ChatModelClient | None`
- local provider configuration
- Groq provider configuration
- OpenRouter free configuration
- explicit Hugging Face configuration
- legacy single-provider compatibility

Steps:
- [ ] Write failing configuration/builder tests.
- [ ] Verify RED.
- [ ] Add settings and provider construction.
- [ ] Verify GREEN.
- [ ] Commit.

### Task 3: Zero-cost and secret-safety enforcement

**Files:**
- Modify: `src/ai_hq/chat/free_model_router.py`
- Test: `tests/test_free_model_router.py`

**Interfaces:**
- Only approved zero-cost provider definitions enter router.
- No paid-fallback configuration exists.
- Safe aggregate failure message contains provider names but no credentials.

Steps:
- [ ] Write failing policy/error-sanitization tests.
- [ ] Verify RED.
- [ ] Implement minimal policy validation/sanitization.
- [ ] Verify GREEN.
- [ ] Commit.

### Task 4: SysAdmin integration regression

**Files:**
- Modify integration code only if existing builder wiring requires it.
- Test existing chat controller/API tests.

**Interfaces:**
- ChatController continues consuming ChatModelClient.
- Operational mission pipeline remains unchanged.

Steps:
- [ ] Add/adjust integration regression test if necessary.
- [ ] Verify RED only if production integration needs modification.
- [ ] Make minimal wiring change.
- [ ] Verify chat tests GREEN.
- [ ] Commit if code changes.

### Task 5: Production verification

**Files:**
- Test: existing runtime dependency tests
- No schema migration expected.

Steps:
- [ ] Run all targeted chat/router tests.
- [ ] Run complete pytest suite.
- [ ] Run `git diff --check`.
- [ ] Commit remaining documentation/config example changes.
- [ ] Push main.
- [ ] Create immutable production release.
- [ ] Build/recreate containers.
- [ ] Verify Alembic head unchanged.
- [ ] Verify web healthy and worker running.
- [ ] Configure provider secrets locally without echoing them.
- [ ] Perform harmless conversational smoke test.
- [ ] Verify mutation refusal and read-only operational mission behavior.

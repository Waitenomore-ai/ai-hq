# AI HQ Free AI Router Design

Date: 2026-09-04
Status: Approved for implementation

## Goal

Give AI HQ SysAdmin access to multiple legitimate no-cost AI inference
sources with automatic failover while enforcing a hard rule that AI HQ
must never silently fall back to paid inference.

## Existing Architecture

SysAdmin currently talks through the provider-independent
`ChatModelClient`.

The production system already contains:

- persisted SysAdmin conversations
- authenticated chat API
- SysAdmin chat UI
- mission orchestration
- read-only operational intent planning
- worker execution
- ToolGateway / safety pipeline
- OpenAI-compatible HTTP chat client

Operational tools remain separate from model inference.

Models generate language.

Models do not receive direct server access.

## Architecture

The existing ChatModelClient interface remains the boundary used by
ChatController.

A new FreeModelRouter implements ChatModelClient.

Flow:

    SysAdmin
       |
       v
    ChatController
       |
       v
    ChatModelClient
       |
       v
    FreeModelRouter
       |
       +-- Local OpenAI-compatible endpoint
       |
       +-- Groq
       |
       +-- OpenRouter free router
       |
       +-- Hugging Face explicitly approved free route
       |
       +-- future zero-cost providers
       |
       v
    provider failover

No provider may gain access to MissionExecutor, ToolGateway, Host Helper,
Docker, shell execution, or server credentials.

## Initial Providers

### 1. Local OpenAI-Compatible Provider

Optional.

This is highest priority when configured because locally hosted inference
does not incur an external inference charge.

Configuration:

- FREE_AI_LOCAL_BASE_URL
- FREE_AI_LOCAL_MODEL
- FREE_AI_LOCAL_API_KEY

The API key is optional for local endpoints.

### 2. Groq

Groq uses its OpenAI-compatible API.

Configuration:

- FREE_AI_GROQ_API_KEY
- FREE_AI_GROQ_MODEL

Base URL is fixed in application code to the documented Groq
OpenAI-compatible API root.

AI HQ treats Groq as available only when explicitly configured.

No automatic paid upgrade or billing action is permitted.

### 3. OpenRouter Free Router

OpenRouter's dedicated free router is used rather than a general
paid-capable automatic router.

Configuration:

- FREE_AI_OPENROUTER_API_KEY

Model:

- openrouter/free

The model identifier is fixed by the application for this provider.

AI HQ must not substitute a paid OpenRouter model if the free router
fails or reaches its limit.

### 4. Hugging Face

Hugging Face's OpenAI-compatible inference router can be configured as
an additional source.

Configuration:

- FREE_AI_HF_TOKEN
- FREE_AI_HF_MODEL

The model/provider selection must be explicit.

AI HQ must not use Hugging Face's generic fastest or cheapest automatic
provider policy as proof that inference is free.

Only a model/provider combination explicitly approved in configuration
may be enabled.

If the configured free allowance is unavailable, the provider fails
closed and the router moves to another provider.

## Hard Zero-Cost Policy

`FREE_AI_ALLOW_PAID` does not exist.

There is deliberately no configuration switch that enables paid
fallback.

Every provider adapter included in the free router must be classified
as one of:

- local
- explicitly free model/router
- explicitly configured free allowance

Unknown providers are rejected.

A provider failure never changes its model identifier to a paid model.

A provider rate limit never causes a paid request.

A provider quota failure never causes a paid request.

When every free provider fails, the user receives a clear temporary
unavailability response.

## Provider Interface

Each configured provider is represented by a provider definition with:

- name
- base_url
- model
- api_key
- timeout_seconds
- zero_cost_policy

The existing OpenAI-compatible HTTP implementation is reused where
possible.

Provider-specific SDK dependencies are not required for v1.

## Router Behaviour

Provider order:

1. local
2. Groq
3. OpenRouter free router
4. Hugging Face explicitly configured route

Only configured providers participate.

For each request the router attempts providers sequentially.

The router moves to the next provider on:

- connection failure
- timeout
- HTTP 429
- HTTP 5xx
- malformed provider response
- empty model response
- provider quota failure represented as a provider error

Authentication/configuration errors are recorded as provider failures
without exposing credentials.

If a provider succeeds, its response is returned immediately.

If all providers fail, FreeModelRouter raises ChatModelError containing
a safe provider-summary message with no secrets.

## Observability

The router records:

- provider attempted
- provider succeeded
- provider failed
- failure category
- elapsed time

Logs must never contain:

- API keys
- bearer tokens
- complete Authorization headers

The UI does not need to expose provider internals in v1.

## Configuration

New settings:

- free_ai_local_base_url
- free_ai_local_model
- free_ai_local_api_key
- free_ai_groq_api_key
- free_ai_groq_model
- free_ai_openrouter_api_key
- free_ai_hf_token
- free_ai_hf_model
- free_ai_timeout_seconds

Legacy CHAT_MODEL_* configuration remains temporarily supported as a
compatibility fallback only when none of the free-router providers are
configured.

Legacy configuration is not automatically considered zero-cost.

It must not be mixed into FreeModelRouter failover.

## Security

Secrets remain in:

    /etc/ai-hq/ai-hq.env

Secrets are never committed to Git.

Setup commands request secrets without echoing them.

Provider error messages are sanitized before being shown to users.

External model providers receive conversation content required for the
model request.

They do not receive host-helper credentials or unrelated environment
variables.

## SysAdmin Operational Safety

This project does not expand SysAdmin's operational permissions.

The only currently approved operational capabilities remain:

- system.health.read
- service.status.read
- service.logs.read

Target remains:

- ai-hq

The following remain prohibited:

- shell execution
- arbitrary commands
- restart
- deploy
- rollback
- stop/start
- file mutation
- arbitrary tools

Operational requests continue through:

    ChatController
        -> persisted Mission
        -> MissionExecutor
        -> ToolGateway
        -> SafetyService
        -> approved read-only adapter
        -> Host Helper

The FreeModelRouter never bypasses this pipeline.

## Web Access

AI inference and web research are separate capabilities.

This project does not grant unrestricted web browsing to SysAdmin.

Provider-specific paid web-search features are disabled/not requested.

A controlled web research tool can be designed separately.

## Testing

TDD is required.

Tests must cover:

1. provider configuration
2. provider ordering
3. unconfigured providers skipped
4. successful first-provider response
5. failover after timeout
6. failover after rate limit
7. failover after provider 5xx
8. failover after malformed response
9. all providers unavailable
10. no secrets in raised errors
11. OpenRouter model is exactly `openrouter/free`
12. no paid fallback exists
13. local provider priority
14. legacy single-provider compatibility
15. existing ChatController behaviour
16. full AI HQ regression suite
17. production image contains required runtime dependencies

## Deployment

Implementation will be developed and tested before production deployment.

Deployment gate:

- targeted tests pass
- full test suite passes
- git diff --check passes
- Alembic remains at the expected head
- production image builds
- web container becomes healthy
- worker remains running
- configured provider can complete a harmless conversational request

API keys are configured only after code deployment.

## Success Criteria

The feature is complete when:

1. SysAdmin can converse through at least one configured zero-cost
   provider.
2. Multiple configured providers automatically fail over.
3. A provider outage or quota limit cannot trigger paid inference.
4. Exhausting all free providers produces a clear unavailable response.
5. Existing read-only operational mission safety remains unchanged.
6. Provider credentials are not exposed in Git, logs, or UI.
7. The full AI HQ test suite remains green.

# AI HQ Operating Constraints Addendum

**Date:** 2026-09-03
**Status:** User-directed hard requirements

This addendum supplements the approved Phase 1 design.

## 1. Zero-cost-first AI policy

AI HQ should avoid paid AI usage wherever practical.

Routing priorities:
1. Local models on user-owned hardware when capable enough.
2. Legitimate free-tier/free-account cloud providers within their published terms and quotas.
3. Other zero-cost routes or cached/reused results where appropriate.
4. Paid providers only if the user explicitly enables and approves them in future.

The system must not rely on creating duplicate accounts to evade provider limits, terms, quotas, identity controls, or billing rules. Multiple legitimately separate provider accounts may be supported when the provider allows it, but the router should prefer provider diversity, local execution, batching, caching, task-size matching, and graceful fallback rather than quota circumvention.

The AI Model Router must support:
- provider/model capability matching
- local and cloud providers
- per-provider free quota metadata where available
- cost accounting even when estimated cost is zero
- hard default policy: paid execution disabled
- graceful fallback when a free route is unavailable
- local-first/private routing for sensitive tasks
- reuse/caching where safe
- task decomposition so lightweight jobs use lightweight models

## 2. Local + web AI coordination

AI HQ should coordinate local AI and web/cloud AI so work on DripVid and other owned services is efficient.

The control plane remains local and keeps mission state, permissions, approvals, knowledge, audit history and service metadata under user control.

Expected pattern:
- local AI handles private, repetitive, classification, summarisation, monitoring and low-cost tasks where capable
- web/cloud AI handles tasks that materially benefit from stronger reasoning, broader context or current web information, subject to the zero-cost-first policy
- Commander selects the cheapest capable route rather than always selecting the strongest model
- repeated context about DripVid and other owned services should be retrieved from Knowledge Core/repository state instead of repeatedly resending unnecessary context
- parallel agents should be used only when they reduce total work/cost and do not duplicate effort
- coding/repository work must use the relevant source-of-truth repository and CI state
- all cross-service changes remain permissioned and auditable

## 3. Home Assistant / smart-home expansion

Home Assistant is added to the roadmap as the home-automation control layer for devices such as Alexa-connected workflows, lights, cameras and other supported smart-home equipment.

Design intent:
- Home Assistant runs as an isolated service, not inside DripVid
- AI HQ integrates with Home Assistant through narrow authenticated capabilities rather than direct unrestricted device access
- smart-home state should be readable by an appropriate future Home/Automation agent
- real device mutations are treated as external actions and pass through Approval/Safety policy where consequential
- cameras require stricter privacy/visibility controls than ordinary lights/switches
- future voice integrations may use Alexa/Home Assistant bridges where supported
- local protocols/integrations should be preferred where practical to reduce cloud dependency

Suggested future capabilities:
- home.read_state
- home.list_devices
- home.light_control
- home.scene_activate
- home.camera_status
- home.camera_snapshot
- home.automation_trigger

High-risk or privacy-sensitive actions such as exposing camera feeds externally, changing security settings, unlocking doors, disabling alarms, or altering network/security configuration must never be auto-granted.

## 4. Application/tooling list

The user previously supplied a list of applications to install to make the environment easier to operate. That exact list should be treated as pending recovery rather than guessed or silently replaced. Home Assistant is explicitly added to that list and to the roadmap.

# AI HQ Autonomous Missions — Stage 1 Design

## Goal

Allow AI HQ to accept a high-level goal and autonomously plan and progress
a mission while remaining inside the existing Tool Gateway, safety,
permission, approval, and audit boundaries.

## Architecture

The existing mission lifecycle remains the source of truth.

A mission planner converts a user goal into an explicit ordered sequence
of mission steps. Each executable step references a tool registered with
the existing Tool Gateway rather than invoking host functionality directly.

Mission execution progresses one step at a time through the existing
worker/lifecycle architecture.

The autonomous mission layer never bypasses the Tool Gateway.

## Mission Planning

A mission plan contains:

- mission identifier
- original user goal
- ordered steps
- step identifier
- description
- intended tool
- tool arguments
- execution state
- result or failure information

Plans must be inspectable and deterministic once accepted.

Invalid tools or malformed steps fail closed.

## Execution

The mission runner selects the next eligible step and submits tool work
through the Tool Gateway.

The runner must not directly execute shell commands, host-helper actions,
or infrastructure operations.

A successful step advances the mission.

A failed step records the failure and stops automatic progression unless
the existing lifecycle explicitly permits retry.

## Safety and Approval

Autonomy does not imply unrestricted authority.

Every tool invocation remains subject to:

- Tool Gateway registration
- permission checks
- safety policy
- simulation/dry-run behaviour where supported
- approval requirements
- adapter restrictions

Operations requiring approval transition into an approval-waiting state.
The mission cannot silently bypass that state.

## Auditability

The system records enough information to reconstruct what happened:

- plan creation
- step selection
- tool requested
- arguments submitted
- safety/permission decision
- approval decision when applicable
- tool result
- failure
- mission/step state transition

Existing audit and operations-ledger facilities should be reused rather
than creating an independent logging system.

## Resumability

Mission state is persisted through the existing mission/state storage
architecture.

A worker restart must not cause completed steps to execute again.

A mission waiting for approval can resume after approval.

A failed mission remains inspectable.

## Boundaries

Stage 1 does not add unrestricted host access.

Stage 1 does not replace the Tool Gateway.

Stage 1 does not implement the final dashboard.

Stage 1 establishes the autonomous mission orchestration layer that later
stages will connect to production DripVid/server operations and expose in
the AI HQ control dashboard.

## Delivery Order

1. Mission-plan contracts and persistence.
2. Planner validation against the Tool Gateway registry.
3. Step lifecycle and next-step selection.
4. Tool Gateway execution integration.
5. Approval-paused missions and resume behaviour.
6. Audit/operations-ledger integration.
7. Worker orchestration and restart/idempotency behaviour.
8. Mission API exposure required by the future dashboard.
9. Full regression and safety testing.

## Success Criteria

Stage 1 is complete when AI HQ can accept a mission goal, create an
inspectable plan, progress eligible steps through the Tool Gateway,
pause for required approval, resume safely, persist progress, prevent
duplicate completed-step execution, record its decisions/results, and
pass the complete existing and new automated test suite.

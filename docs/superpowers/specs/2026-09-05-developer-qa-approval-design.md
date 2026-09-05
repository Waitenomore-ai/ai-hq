# AI HQ Developer → QA → Approval Design

Date: 2026-09-05
Status: Approved for planning

## Goal

Add the first multi-agent delivery slice to AI HQ: a Developer role prepares a proposed code change, QA independently verifies the proposal and its evidence, and AI HQ then stops at an explicit human approval gate. This slice does not deploy to production.

## Existing Foundation

AI HQ already has persistent missions and ordered mission steps, restart-safe execution, Tool Gateway enforcement, approval pause/resume, operations auditing, and SysAdmin read-only production diagnostics. This design extends those boundaries rather than creating a second orchestration system.

## Architecture

The existing persisted Mission remains the source of truth.

Flow:

    User / SysAdmin request
            |
            v
       Mission plan
            |
            v
       Developer stage
            |
            v
       Developer evidence
            |
            v
          QA stage
            |
       +----+----+
       |         |
      fail      pass
       |         |
       v         v
    mission   WAITING_APPROVAL
    failed       |
                 v
          explicit human decision

Developer and QA are workflow roles, not privileged infrastructure identities. Neither receives shell, Host Helper, Docker, deployment, rollback, service mutation, or arbitrary Tool Gateway access.

## Developer Stage

Developer produces a bounded change proposal and evidence describing:

- requested outcome
- files expected to change
- proposed patch/change reference
- tests required
- test evidence supplied by the execution environment
- known limitations

The Developer stage may only use explicitly registered development capabilities. It cannot invent a capability name and cannot bypass Tool Gateway. Production operational capabilities remain unchanged.

A Developer result is incomplete unless its evidence is persisted on the mission step.

## QA Stage

QA consumes the persisted Developer result rather than trusting conversational claims. QA independently evaluates:

- requested outcome is covered
- proposed change is bounded to the mission
- required tests were identified
- supplied test evidence shows success
- prohibited production operations were not requested or performed
- change is suitable to present for human approval

QA produces a persisted verdict of `passed` or `failed` with evidence and reasons.

QA cannot alter the Developer result to make it pass. A failed QA verdict fails the delivery slice and requires a new Developer attempt or a new mission plan.

## Human Approval Gate

Only a QA-passed proposal may enter `WAITING_APPROVAL`.

The approval record must bind to the exact proposal/change reference and QA evidence being approved. Approval of one proposal cannot authorize a later or modified proposal.

The human decision is explicit and persisted. Rejection stops the slice. Approval marks the proposal eligible for a later deployment stage, but this project does not execute deployment.

No model output, agent result, retry, restart, or timeout may synthesize human approval.

## Data and State

Reuse the existing Mission and MissionStep persistence model wherever possible. Add focused delivery metadata only where existing result/error/approval fields cannot represent the required evidence safely.

Required persisted facts are:

- stage role (`developer` or `qa`)
- immutable proposal/change reference
- Developer evidence
- QA verdict and evidence
- approval reference bound to the verified proposal
- timestamps/state transitions already provided by the mission lifecycle

Mission state remains authoritative. Agent chat text is not authoritative workflow state.

## Safety Boundaries

This slice MUST NOT add production mutation permissions.

SysAdmin operational capabilities remain exactly:

- `system.health.read`
- `service.status.read`
- `service.logs.read`

Target remains exactly `ai-hq`.

Still prohibited for SysAdmin, Developer and QA in this slice:

- arbitrary shell execution
- direct Host Helper access
- Docker control
- service restart/stop/start
- production deploy
- rollback
- production file mutation
- arbitrary tools
- bypassing Tool Gateway
- self-approval

Any future Deployment Agent is a separate design and implementation project.

## Error Handling

The workflow fails closed.

- Missing Developer evidence: Developer step fails.
- Unknown/unregistered capability: blocked by Tool Gateway/registry validation.
- QA cannot establish passing evidence: QA fails.
- QA failure: mission does not enter approval.
- Missing or mismatched proposal reference at approval: approval is rejected.
- Restart while waiting: persisted `WAITING_APPROVAL` remains authoritative.
- Rejected approval: proposal is not deployable.
- Modified proposal after QA: requires fresh QA and fresh approval.

## API and UI

Existing authenticated mission detail responses should expose enough structured stage information for the HQ UI to show:

- Developer: pending/running/completed/failed
- QA: pending/running/passed/failed
- Approval: not ready/waiting/approved/rejected
- proposal/change reference
- concise evidence summaries

The UI must never present an unverified proposal as approved or deployed.

## Testing

TDD is required.

Tests must cover:

1. Developer stage persists proposal evidence.
2. Developer cannot use unregistered capabilities.
3. QA consumes persisted Developer evidence.
4. QA pass enters human approval waiting state.
5. QA failure cannot enter approval.
6. Approval binds to the exact verified proposal reference.
7. Modified proposal invalidates prior QA/approval eligibility.
8. Approval cannot be synthesized by an agent/model.
9. Rejection stops the delivery slice.
10. Restart preserves stage and approval state.
11. Existing Tool Gateway and approval safety remain authoritative.
12. No direct shell/Host Helper/Docker/deployment path exists in Developer or QA workflow code.
13. Existing SysAdmin read-only permissions remain unchanged.
14. Authenticated mission API exposes delivery stage state.
15. Full AI HQ regression suite remains green.
16. `git diff --check` passes.

## Deployment Boundary

This feature may be deployed to AI HQ after its own implementation passes tests, but using it does not itself deploy proposed application changes.

A separate Deployment Agent project will later consume an explicitly approved immutable change reference, invoke only the approved release mechanism, and trigger SysAdmin read-only post-deployment verification.

## Success Criteria

The slice is complete when:

1. AI HQ can represent and persist Developer → QA → human approval as one restart-safe mission workflow.
2. QA independently gates Developer output using persisted evidence.
3. Only QA-passed immutable proposals can request human approval.
4. Approval is explicit, persisted, and bound to the exact verified proposal.
5. No Developer or QA path can mutate production or bypass Tool Gateway.
6. Existing SysAdmin operational safety is unchanged.
7. The full regression suite remains green.

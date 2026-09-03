# AI HQ Phase 1 — Design Specification

**Date:** 2026-09-03  
**Status:** Approved design, ready for implementation planning  
**Repository target:** `Waitenomore-ai/ai-hq`  
**Deployment target:** Existing Linux server as an isolated Docker Compose stack

## 1. Purpose

AI HQ is a personal AI operations system presented through a pixel-art, game-style headquarters. It is intended to automate routine digital work, monitor important systems, coordinate specialist AI agents, and ask for approval before risky actions.

Phase 1 focuses on the smallest useful platform that can safely grow into a broader personal AI ecosystem.

The first active departments are:

- Commander
- Communications
- Calendar
- SysAdmin

The platform also includes the shared foundations needed by all future departments:

- Mission Engine
- Approval & Safety Engine
- Knowledge Core
- Tool Gateway
- Secrets Vault
- Operations Ledger
- Notification Engine
- AI Model Router
- Agent Worker runtime
- Pixel-art HQ interface

Future departments such as DripVid, Research, Files/Nextcloud, Content and Automation are explicitly outside Phase 1 implementation scope, but the architecture must allow them to be added without redesigning the core platform.

## 2. Product principles

### 2.1 Balanced autonomy

Routine, reversible, low-risk work may run automatically.

Destructive, security-sensitive, financial, externally visible, production-affecting or difficult-to-reverse actions require explicit approval.

The system must prefer a safe failure over an unapproved action.

### 2.2 Commander plus specialists

Commander is the user's primary interface and coordinator.

Commander may create missions, delegate work, combine results, raise approvals and present briefings, but it may not bypass a specialist's permissions or the Tool Gateway.

Specialist agents operate only through explicitly granted capabilities.

### 2.3 Real state drives the game world

The pixel-art HQ is a visualization and interaction layer over real operational state.

Animations must never be the source of truth.

If an agent appears to be working, waiting for approval, failed or completed, that state must correspond to a real mission state in the backend.

### 2.4 Least privilege

No agent receives broad account or server access merely because it needs one capability.

Permissions are granted at tool-operation level.

### 2.5 Auditability

Every meaningful action must be traceable through:

`Mission -> Proposed Action -> Permission Check -> Risk Check -> Approval -> Tool Execution -> Result`

### 2.6 Provider independence

The HQ, memory, mission state, permissions and audit history remain under the user's control.

Cloud AI providers are interchangeable execution providers, not the system of record.

## 3. User model

Phase 1 is built for one primary user.

The data model must nevertheless be multi-user-ready from the beginning so future family or team users can have different:

- accounts
- roles
- agents
- permissions
- approval rights
- private memories
- shared memories
- notification settings

Phase 1 does not need full multi-user administration UI.

## 4. Phase 1 agents

## 4.1 Commander

Commander may automatically:

- receive and interpret user requests
- create one or more missions
- select the appropriate specialist
- delegate work
- combine specialist results
- prioritize and reassign missions
- stop or retry failed missions within policy
- read relevant shared Knowledge Core entries
- view all Phase 1 agent status
- create reminders and follow-up missions
- prepare daily briefings
- proactively surface meaningful problems, deadlines or messages
- move blocked work to the Approval Console

Commander may not:

- bypass specialist permissions
- bypass the Tool Gateway
- bypass approval requirements
- turn an inference into a confirmed permanent memory
- expose credentials
- execute unrestricted server commands

## 4.2 Communications

Phase 1 integration target: Gmail and Google Contacts.

Communications may automatically:

- read incoming email
- search historical mail
- summarize messages and threads
- classify mail by importance/category
- identify messages requiring a response
- extract dates, tasks, people and commitments
- prepare suggested replies
- create communication-related missions
- remind the user about unanswered messages
- apply labels or archive mail only where an explicit rule permits it

Approval is required before:

- sending a new email
- replying as the user unless a future explicit auto-reply rule permits it
- forwarding private information
- deleting mail
- changing important mail rules
- sending attachments externally
- messaging a new recipient autonomously

## 4.3 Calendar

Phase 1 integration target: Google Calendar.

Calendar may automatically:

- read authorized calendars
- show daily and upcoming schedules
- detect clashes
- detect events requiring preparation
- find free time
- generate daily and weekly schedule summaries
- create private reminders
- create internal AI mission deadlines
- suggest events from dates extracted by Communications
- calculate preparation or travel buffers when data is available
- warn Commander about schedule overload

Approval is required before:

- accepting or declining invitations
- cancelling meetings
- moving meetings involving other people
- inviting people
- sharing calendar information externally

## 4.4 SysAdmin

SysAdmin is the most restricted Phase 1 agent.

It may automatically observe:

- CPU usage
- RAM usage
- disk usage
- temperatures where available
- mounted-drive state
- Docker container state
- container health
- service state
- application availability
- SSL certificate expiry
- storage growth
- system and application logs
- failed services
- backup status once backups are added
- unusual resource spikes
- AI HQ health

It may automatically perform only specifically allowlisted safe actions such as:

- rerun a health check
- collect logs
- run read-only diagnostics
- inspect containers/services
- inspect disk/mount state
- perform an explicitly approved cache cleanup procedure
- restart a specifically whitelisted non-critical AI HQ component
- open an incident mission

Approval is required before:

- deleting files
- moving media
- changing filesystem layout
- formatting disks
- changing mounts or `/etc/fstab`
- changing firewall rules
- changing SSH access
- changing passwords, tokens or secrets
- installing/removing system packages
- changing Nginx or Cloudflare routing
- restarting production DripVid
- stopping critical containers
- updating Docker images
- changing databases
- restoring backups
- rebooting or shutting down the server

Normal autonomous SysAdmin operation must not expose an unrestricted arbitrary root shell capability.

## 5. Mission system

Every meaningful unit of work is represented as a mission.

Required mission fields:

- unique ID
- title
- description
- owner agent
- source
- priority
- risk level
- status
- created time
- updated time
- objectives/steps
- dependencies
- result
- error state
- approval references
- tool execution references
- XP reward where applicable

Mission sources include:

- direct user request
- Commander delegation
- proactive monitoring
- scheduled automation
- future integration events

Core states:

- `QUEUED`
- `RUNNING`
- `WAITING_APPROVAL`
- `PAUSED`
- `COMPLETED`
- `FAILED`
- `CANCELLED`

Mission state must be durable in PostgreSQL.

A server or worker restart must not cause mission history to disappear.

## 6. Approval and safety model

Four risk classes are used.

### Green — automatic

Examples:

- read-only checks
- summaries
- diagnostics
- calendar lookups
- email classification
- status checks

### Blue — explicitly allowed by rule

Examples:

- creating a private reminder
- applying an approved Gmail label
- restarting a specifically approved non-critical AI HQ service

### Amber — approval required

Examples:

- sending email
- changing a schedule involving another person
- restarting an important service
- modifying configuration
- externally publishing information

### Red — blocked by default

Examples:

- destructive data operations
- changing credentials
- high-impact security changes
- financial actions
- bulk messaging
- wiping databases
- formatting drives

### 6.1 Action-bound approvals

An approval must authorize a specific action plan.

If the requested execution changes materially after approval, the approval becomes invalid and a new approval is required.

### 6.2 Scoped approvals

The user may grant temporary or narrowly scoped permission, for example:

"Allow SysAdmin to restart Uptime Kuma after a failed health check for the next 24 hours."

Scoped approval must include:

- allowed action
- target
- expiry
- optional conditions
- maximum execution count where appropriate

### 6.3 Global operating modes

The HQ must support:

- **Normal** — balanced automation
- **Safe Mode** — read/investigate, but no external changes
- **Freeze** — no new mission/tool execution

If the authorization or permissions service is unavailable, execution defaults to deny.

## 7. Simulation Mode

Simulation Mode is a first-class safety feature.

In simulation:

- reasoning proceeds normally
- missions are created normally
- permissions are checked normally
- approvals may be requested normally
- the final real-world mutation is not executed

The Tool Gateway returns a simulated result describing what would have happened.

Phase 1 activation follows:

`Build -> Test -> Connect -> Observe -> Simulate -> Approve actions -> Selective automation`

The system must support capability-by-capability promotion rather than one global "autonomy on" switch.

## 8. Knowledge Core

The Knowledge Core stores durable operational knowledge, not raw conversational history alone.

Memory categories:

- Confirmed Facts
- Preferences
- Procedures
- Working Memory
- Agent-specific Memory

Each durable memory must include:

- category
- content
- owner/scope
- source/provenance
- confidence
- verification state
- created time
- last verified/updated time
- sensitivity/visibility metadata where appropriate

### 8.1 Memory rules

The system must distinguish:

- confirmed facts
- user preferences
- explicitly taught procedures
- temporary context
- inferred possibilities

An inference must never silently become a confirmed fact.

Contradictions must be surfaced rather than silently overwritten.

Sensitive or consequential inferred preferences require confirmation.

Working memory must expire according to policy.

### 8.2 Memory controls

The user must be able to:

- search memory
- inspect provenance
- edit incorrect entries
- pin/lock important facts
- delete memories
- mark information temporary
- restrict a memory to specific agents
- explicitly say "remember this" or "forget that"

Deleting a memory removes it from active retrieval, not merely from display.

## 9. Tool Gateway

All real integrations pass through a central permissioned Tool Gateway.

Agents do not receive broad account access.

They request narrow capabilities such as:

- `email.search`
- `email.read`
- `email.draft`
- `email.label`
- `email.send`
- `calendar.read`
- `calendar.free_busy`
- `calendar.create_private_reminder`
- `calendar.invite`
- `container.inspect`
- `container.health`
- `logs.read`
- `disk.inspect`
- `container.restart`

The gateway performs:

1. capability validation
2. identity/agent validation
3. permission check
4. risk classification
5. approval validation where required
6. credential-backed execution
7. result normalization
8. audit recording

Every execution has a unique execution ID.

## 10. Secrets Vault

Credentials are stored separately from normal application data and memory.

Agents should not receive raw tokens/passwords when credential-backed execution can be performed without exposing them.

Secrets must be redacted from:

- mission history
- logs
- errors
- AI prompts
- notifications
- UI activity feeds

The application database stores credential references rather than plaintext secrets where possible.

## 11. Retry, idempotency and failure handling

Tool calls must have explicit retry policies.

Agents must not loop indefinitely.

When an operation times out and final state is uncertain, the system checks actual state before retrying.

Mutating operations should be idempotent where practical.

Repeated integration failures create an incident mission rather than infinite retries.

A failed worker must not lose durable mission state.

## 12. Pixel-art HQ interface

The Phase 1 HQ includes:

- Commander Deck
- Communications Centre
- Planning Room
- Server Room
- Knowledge Core
- Approval Chamber
- Mission Control

The game world is isometric pixel-art with a cyberpunk/sci-fi flavor.

No animation may imply an operation occurred unless backend state supports it.

Agent visual states include:

- Idle
- Working
- Waiting for Approval
- Failed
- Completed

The interface also provides conventional panels for practical use.

Primary navigation:

- HQ World
- Commander
- Missions
- Approvals
- Agents
- Knowledge
- Activity
- Notifications
- Settings

The interface should work well from a phone, with the richer headquarters view optimized for larger screens.

## 13. Agent game progression

Agents are persistent entities with:

- role
- level
- XP
- current status
- current mission
- mission history
- capability list
- permissions
- performance metrics

XP rewards useful successful outcomes, not raw action count.

Suggested performance measures:

- success rate
- approval acceptance rate
- user correction rate
- failed actions
- mission duration
- model/API cost
- estimated automation savings

Level-ups may propose new capabilities but must never automatically grant sensitive permissions.

Achievements and streaks are cosmetic/productivity feedback only and must not weaken safety controls.

## 14. Notifications

Notification severity:

- Information
- Attention
- Approval Required
- Critical

Commander should consolidate related alerts to reduce noise.

Phase 1 must support in-app notifications.

The architecture must leave room for browser/PWA/mobile notification channels later.

## 15. Technical architecture

Phase 1 uses a modular monolith plus isolated workers.

Primary components:

### HQ Core

Owns:

- users
- agents
- missions
- permissions
- approvals
- XP
- notifications
- HQ state

### Web UI

Provides:

- pixel HQ
- Commander conversation
- operational panels
- mobile interface

The UI is not the source of truth.

### PostgreSQL

System of record for:

- users
- agents
- missions
- approvals
- permissions
- audit metadata
- memories
- procedures
- achievements
- configuration metadata

Semantic/vector search should use PostgreSQL-native vector support initially rather than introducing a separate vector database.

### Redis

Used for:

- job queues
- transient coordination
- caching
- short-lived state

Redis is not the durable mission system of record.

### Agent Workers

Long-running AI work executes outside the web process.

Workers consume queued missions and have resource limits.

Worker execution can be paused while the web HQ remains online.

### AI Router

Agents request capability classes rather than hard-coded provider/model names, for example:

- classification
- fast reasoning
- complex reasoning
- long-context analysis
- local/private task

The router selects an available configured provider/model.

The architecture supports both cloud models and future local models.

### Approval Engine

Evaluates risk and approval requirements.

### Knowledge Core

Owns durable memory retrieval and lifecycle.

### Operations Ledger

Stores complete traceability of mission and tool activity.

### Notification Engine

Creates and routes user notifications.

### Tool Gateway

Enforces permissions and performs integration actions.

### SysAdmin Broker

A narrow privileged broker handles approved server operations.

Agent workers must not normally receive unrestricted Docker socket/root access.

## 16. Deployment

AI HQ lives in its own repository:

`Waitenomore-ai/ai-hq`

It is deployed as its own Docker Compose stack, separate from DripVid.

Suggested server root:

`/opt/ai-hq/`

The stack receives its own Docker network.

Cross-stack access is explicit and minimal.

The HQ must not rely on being embedded inside the DripVid application or repository.

## 17. SysAdmin Broker security boundary

The SysAdmin Broker exposes a small allowlisted operation API.

Example permitted requests:

- inspect a named container
- read health state
- collect logs
- inspect disk usage

Approval-controlled examples:

- restart an approved named container
- perform an approved maintenance procedure

Rejected by default:

- arbitrary root shell
- arbitrary command strings
- arbitrary filesystem deletion
- arbitrary Docker socket access by the AI worker

The broker verifies approval tokens independently rather than trusting the agent's claim that approval exists.

## 18. AI execution strategy

Phase 1 uses hybrid AI.

The existing server is the control plane for:

- HQ application
- databases
- memory
- permissions
- queues
- integrations
- monitoring

Cloud AI handles reasoning where needed.

Small/local models may be added when practical.

The design must permit a future dedicated GPU machine to register as another AI provider without redesigning agent logic.

## 19. Cost controls

The system records AI usage and estimated cost by:

- provider
- model
- agent
- mission
- day/month

Configurable spending policies may include daily and monthly limits.

A future policy may require approval before exceeding a budget.

Budget exhaustion should degrade gracefully instead of corrupting mission state.

## 20. Backup and recovery

Backups cover:

- PostgreSQL
- Knowledge Core
- agent configuration
- permissions
- procedures
- achievements/progression
- integration configuration
- encrypted secrets material where appropriate

Disposable caches and transient queue data do not require equivalent retention.

Restoration must be tested.

A backup is not considered operationally valid until restore testing has demonstrated that critical state can be recovered.

## 21. Observability

The HQ monitors:

- worker health
- mission queue depth
- agent failures
- model latency
- model/API cost
- integration failures
- database health
- failed tool executions
- notification failures

AI HQ must not be the only monitor of AI HQ.

Independent external health monitoring remains outside the stack so a total HQ failure can still be detected.

## 22. Phase 1 integration scope

Included:

- Gmail
- Google Contacts
- Google Calendar
- server/Docker read-only monitoring
- restricted SysAdmin broker actions
- AI providers through the AI Router

Deferred:

- DripVid/GitHub automation
- Nextcloud/File department
- Research Lab
- broader workflow automation
- content/social publishing
- financial actions
- full multi-user administration

## 23. Data flow examples

### 23.1 Email meeting request

1. Communications receives/reads email.
2. It extracts a proposed meeting time.
3. Commander creates or updates a mission.
4. Calendar checks availability.
5. Communications drafts a reply.
6. Calendar prepares an event.
7. Approval Console presents the externally visible actions.
8. User approves.
9. Tool Gateway sends the reply and creates the event.
10. Operations Ledger records both actions.
11. Mission completes and XP may be awarded.

### 23.2 Server incident

1. SysAdmin monitoring detects repeated Nextcloud health failure.
2. SysAdmin creates an incident mission.
3. Read-only diagnostics run automatically.
4. SysAdmin identifies a likely restart requirement.
5. Approval Engine marks restart Amber.
6. Approval Console shows exact target, reason, impact and reversibility.
7. User approves.
8. SysAdmin Broker validates approval.
9. Broker performs the restart.
10. SysAdmin verifies actual health after restart.
11. Operations Ledger records proposal, approval, execution and result.

## 24. Testing requirements

Phase 1 implementation must include tests for:

- mission state transitions
- permission denial
- risk classification
- approval binding
- approval expiry
- scoped approval
- Simulation Mode
- Safe Mode
- Freeze mode
- agent capability boundaries
- Tool Gateway authorization
- secret redaction
- retry limits
- uncertain-result state verification
- idempotency where applicable
- memory provenance
- memory contradiction handling
- working-memory expiry
- worker restart/recovery
- SysAdmin Broker allowlist
- SysAdmin Broker denial of arbitrary commands
- UI state reflecting backend state
- audit-event creation
- notification severity
- provider routing fallback
- cost accounting

Critical security tests must fail closed.

## 25. Acceptance criteria

Phase 1 is considered functionally complete when:

1. The user can access the HQ and interact with Commander.
2. Commander can create and delegate real missions.
3. Communications can safely read/summarize authorized Gmail data and prepare drafts.
4. Calendar can safely read schedules and prepare suggested events.
5. SysAdmin can read approved server/Docker health information through the controlled boundary.
6. All mutating external actions run in Simulation Mode by default.
7. Approval-controlled operations cannot execute without a valid action-bound approval.
8. Secrets do not appear in agent prompts, mission logs or user-visible activity.
9. Missions survive service/worker restart.
10. Knowledge entries preserve provenance and confidence.
11. The Operations Ledger can trace a mission to every executed tool action.
12. Global Normal/Safe/Freeze controls work.
13. The pixel-art interface reflects real agent/mission states.
14. Independent health monitoring can detect total AI HQ failure.
15. Backups can be restored in a documented test.

## 26. Explicit non-goals for Phase 1

Phase 1 will not:

- allow arbitrary autonomous root shell access
- autonomously delete or move user media
- autonomously change production DripVid
- autonomously spend money
- autonomously publish content
- implement every future agent
- require a large local LLM
- depend on game mechanics for authorization
- put credentials into model prompts or normal memory
- make the UI animation layer authoritative
- build a distributed microservice architecture unnecessarily

## 27. Planned expansion path

After Phase 1 stabilizes, likely departments are:

1. DripVid Department
2. Research Lab
3. Files/Nextcloud Department
4. Automation Factory
5. Content/Media Studio
6. Additional user accounts and role-specific agents

Each future department is added through the same Mission, Tool Gateway, Approval, Memory and Audit foundations.

## 28. Final architectural decisions

Locked decisions for Phase 1:

- separate repository from DripVid
- single-user initially, multi-user-ready
- Commander + specialist agents
- Communications + Calendar + SysAdmin first
- balanced autonomy
- controlled automatic memory
- central permissioned Tool Gateway
- dedicated Secrets Vault
- action-bound approvals
- Simulation Mode
- Normal / Safe / Freeze operating modes
- hybrid local/cloud AI
- provider-independent AI Router
- PostgreSQL as durable system of record
- PostgreSQL-native vector search initially
- Redis for transient queue/cache work
- modular monolith plus isolated workers
- privileged restricted SysAdmin Broker
- isolated Docker Compose deployment
- game state driven by actual backend state
- independent external monitoring
- backup plus restore verification

---

# Spec self-review

**Placeholder scan:** No TBD/TODO placeholders remain.

**Internal consistency:** The design consistently uses Commander delegation, specialist least-privilege capabilities, central Tool Gateway enforcement, action-bound approvals and Simulation Mode. The game UI is consistently treated as presentation rather than system of record.

**Scope check:** Phase 1 is limited to the core platform plus Commander, Communications, Calendar and SysAdmin. DripVid, Nextcloud/Files, Research and broader automation are deferred.

**Ambiguity check:** High-risk server operations, external communications and multi-party calendar changes are explicitly approval-controlled. Arbitrary autonomous root shell access is explicitly excluded.

**Implementation planning status:** Ready for user review. After user approves this written specification, the next process step is to create the implementation plan.

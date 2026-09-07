# Chat-Driven Code Changes Design

**Status:** Approved direction from user conversation on 2026-09-07; written specification pending review.

## Purpose

Make AI HQ the user's primary conversational control surface for making code and UI changes to both AI HQ and DripVid, while preserving the existing safety model, repository sandbox, QA verification, approval workflow, Tool Gateway, Host Helper, deployment controls, audit trail, and rollback path.

The target interaction is natural language such as:

- "Make the DripVid toolbar smaller on desktop."
- "Change the AI HQ dashboard layout."
- "Fix this UI bug in DripVid."
- "Run the tests and prepare it for deployment."
- "Deploy the approved change."
- "Roll back the last DripVid deployment."

AI HQ must perform the engineering work through controlled, typed boundaries rather than exposing unrestricted shell, arbitrary filesystem, arbitrary Git, or direct production authority to the model.

## Existing foundations to extend

This design reuses the current AI HQ architecture rather than creating a second execution path:

1. Sysadmin/HQ chat for conversational intent handling.
2. AI/model routing for model-backed reasoning.
3. Delivery orchestration for Developer -> verified candidate -> QA -> Human Approval.
4. Isolated repository sandbox for typed file changes and fixed test execution.
5. CandidateVerifier for machine-derived candidate identity.
6. Tool Gateway and Approval Service for controlled real-world mutation.
7. Host Helper for bounded host-side operations.
8. Deployment and rollback adapters for approved production changes.
9. Operations Ledger for auditability.

## Authority model

### Allowed without production approval

AI HQ may, after an authenticated user request:

- classify the request as a code/UI change;
- select only a registered logical repository target;
- inspect repository content through trusted repository abstractions;
- create an isolated disposable workspace;
- ask the Developer model to propose structured whole-file writes/deletes;
- apply those changes inside the sandbox;
- run the repository's fixed trusted verification profile;
- derive the actual changed files, diff digest, content digest, and machine test evidence;
- run QA against the exact immutable candidate;
- produce a human-readable summary and preview metadata;
- persist the candidate and audit events.

These actions do not mutate production.

### Actions requiring explicit human approval

The following remain gated:

- publishing a verified candidate to a remote branch when that branch is intended for release;
- merging a candidate into the production branch;
- production deployment;
- rollback;
- service restart;
- database/schema mutation outside the normal reviewed deployment path;
- authentication/security-policy changes that alter authority boundaries;
- destructive repository actions.

The approval must bind to the exact candidate identity and requested operation. A changed candidate invalidates the approval.

## Repository targets

Initial registered repository keys:

- `ai-hq` -> `Waitenomore-ai/ai-hq`
- `dripvid` -> `Waitenomore-ai/dripvid`

The model receives logical keys, not arbitrary remote URLs or filesystem source paths.

Each repository profile contains trusted server-side configuration:

- repository key;
- fixed source repository identity;
- permitted base branch/ref;
- fixed verification commands/profile;
- sandbox policy;
- publish branch prefix;
- deployment target key, if supported.

Unknown repositories fail closed.

## Chat intent and request contract

Add a first-class code-change intent to the existing chat controller.

A normalized request contains:

- target repository key;
- user goal in natural language;
- optional scope hints such as "desktop only" or "leave mobile unchanged";
- requested terminal action: prepare only, publish for review, deploy, or rollback;
- authenticated requesting user/session identity.

The model may infer the logical target from words such as "DripVid" or "HQ", but it may not invent a repository.

If the target is unambiguous, the request proceeds without asking for repository paths, filenames, or commands. If a request could materially affect more than one registered target, the system must fail safe rather than applying the same change to both silently.

## Engineering pipeline

### 1. Intent classification

The chat controller recognizes requests to modify software/UI and routes them into a `CodeChangeRequest` flow rather than treating them as ordinary informational chat.

### 2. Repository inspection

A read-only repository context service gathers only the files and context relevant to the request. The Developer model is not given unrestricted host filesystem access.

### 3. Candidate generation

The Developer model returns a typed proposal containing:

- summary;
- rationale;
- tuple of `FileChange` values using existing write/delete operations;
- expected verification considerations.

No command strings, shell snippets, deployment commands, arbitrary Git flags, remote URLs, environment values, or host paths are accepted from model output.

### 4. Isolated application

The existing repository sandbox applies the typed changes in a disposable workspace tied to the selected registered profile.

### 5. Verification

The sandbox derives the actual candidate snapshot and runs the repository's fixed trusted verification profile.

For AI HQ, retain the existing trusted lint/pytest verification.

For DripVid, register a trusted profile that mirrors the repository's established CI/test contract. The model cannot choose test commands.

A failing verification blocks the candidate from progressing.

### 6. Independent QA

QA receives the exact immutable candidate and machine evidence. QA may inspect and accept/reject the candidate but may not alter it.

### 7. Candidate presentation

HQ chat returns a concise summary showing:

- target project;
- files changed;
- verification result;
- QA result;
- candidate identifier;
- whether the request is ready for approval;
- what production action, if any, is pending.

### 8. Approval-bound publishing and deployment

For production-bound requests, Human Approval binds to the exact verified candidate and action.

After approval, a controlled publisher may create/update only a safe release branch whose name is generated by trusted application code. No force push, arbitrary ref update, arbitrary repository, arbitrary remote, or arbitrary Git command is exposed to the model.

Merge/deploy must continue through controlled production adapters. Deployment and rollback remain separate approved operations and must be audit logged.

## Self-modification rule for AI HQ

AI HQ may modify its own code only through the same isolated repository candidate flow used for DripVid. It must not bypass the sandbox, QA, approval, Tool Gateway, or deployment controls merely because the target is AI HQ itself.

Changes to the following areas are classified as high-risk and require explicit approval before publication even if they otherwise pass tests:

- authentication;
- authorization;
- safety policy;
- approval rules;
- Tool Gateway permissions;
- Host Helper boundaries;
- deployment controls;
- repository sandbox boundaries;
- secret/config handling;
- audit logging.

The system must not allow a model-generated change to weaken its own approval requirement and then use the weakened rule in the same change cycle.

## DripVid integration

Add DripVid to the trusted repository registry and fixed verification profile.

The first supported DripVid coding use cases are intentionally ordinary repository/UI changes such as:

- layout and spacing changes;
- toolbar/menu changes;
- CSS and responsive adjustments;
- template/component edits;
- bounded bug fixes covered by tests;
- admin/member UI changes.

Operational media/server actions remain separate Tool Gateway capabilities. A code-change request must not silently turn into unrestricted server repair authority.

## Publishing boundary

Introduce a narrow repository publisher abstraction rather than exposing raw Git/GitHub mutation to the model.

Permitted operations:

- create a branch from the approved base ref;
- write the exact verified candidate tree;
- create a commit with generated metadata;
- open a pull request or mark the candidate ready for deployment;
- optionally merge only after the approval-bound release action permits it.

Forbidden through the model-facing contract:

- arbitrary remote URL;
- arbitrary ref names;
- force push;
- history rewrite;
- credential access;
- deleting protected branches;
- changing repository settings;
- bypassing required QA/approval;
- publishing a tree that differs from the verified candidate.

## Data model and audit trail

Persist a code-change record containing at minimum:

- request id;
- chat/session/user identity;
- repository key;
- natural-language request;
- base ref;
- workspace id;
- candidate id/digest;
- changed files;
- machine verification result;
- QA result;
- approval id/status when applicable;
- publish branch/commit id when applicable;
- deployment id/result when applicable;
- rollback relationship when applicable;
- timestamps and failure reason.

Do not store credentials, secrets, environment dumps, raw tokens, or unbounded model/tool output in the audit record.

## Rollback

Every successful production deployment initiated through this flow must retain enough trusted deployment metadata to identify the prior known-good release.

A chat request such as "roll back the last DripVid change" resolves to a known deployment record and enters the existing approval-required rollback adapter. The model does not select arbitrary filesystem release paths or commands.

## User experience

The chat should stay conversational.

Example prepare flow:

1. User: "HQ, make the DripVid desktop toolbar 20% smaller but leave mobile alone."
2. HQ identifies `dripvid` and creates a sandbox candidate.
3. HQ reports the relevant files changed, tests, QA result, and candidate id.
4. HQ asks for approval only when a production/publish action is required by policy.

Example self-edit flow:

1. User: "HQ, move system health to the top of the dashboard."
2. HQ identifies `ai-hq` and follows the same candidate/QA path.
3. HQ cannot deploy its own change by bypassing approval.

## Failure behavior

Fail closed when:

- target repository is unknown or ambiguous;
- repository profile is unavailable;
- relevant source context cannot be loaded reliably;
- model output does not validate against the typed file-change contract;
- a requested path is invalid or escapes the workspace;
- workspace state becomes stale after verification;
- fixed tests fail or time out;
- QA rejects the candidate;
- approval is missing, expired, rejected, or bound to another candidate/action;
- publisher output differs from the verified candidate;
- deployment adapter reports failure;
- rollback target cannot be resolved from trusted deployment history.

HQ should report the failure clearly and retain the audit record without performing a fallback unsafe action.

## Testing strategy

Implementation follows TDD.

Required coverage includes:

- chat recognizes code-change intent for AI HQ and DripVid;
- natural-language target resolution cannot select arbitrary repositories;
- AI HQ and DripVid profiles resolve deterministically;
- unknown/ambiguous target fails closed;
- Developer output is limited to typed file changes;
- no arbitrary command API is introduced;
- AI HQ self-edits cannot bypass the repository sandbox;
- DripVid edits remain in a disposable sandbox until approved publication;
- changed files and candidate identity are machine-derived;
- fixed tests execute from trusted profiles only;
- test failure blocks QA/publication;
- QA evaluates the exact immutable candidate;
- high-risk AI HQ security-boundary changes always require approval;
- approval binds to exact candidate and action;
- stale candidate invalidates approval;
- publisher cannot force push or select arbitrary refs/remotes;
- published tree matches the verified candidate digest;
- deployment remains behind Tool Gateway/Approval Service;
- rollback remains approval-bound and uses trusted release identity;
- audit record reconstructs the end-to-end flow without secrets;
- existing repository sandbox, chat, approval, tool gateway, deployment, and security-boundary tests remain green;
- full AI HQ test suite and lint pass before merge.

## Delivery phases

### Phase A - Chat-to-candidate

- add code-change intent and request contracts;
- add DripVid repository profile;
- wire chat -> Developer -> sandbox -> machine verification -> QA;
- present candidate result in HQ chat;
- no production publish/deploy from the new path yet.

### Phase B - Controlled publishing

- add narrow publisher abstraction;
- publish only exact verified candidates to generated release branches;
- open PR/review metadata;
- audit branch and commit identity.

### Phase C - Approval-bound release

- bind candidate approval to merge/deploy action;
- integrate with existing deployment adapter;
- expose deployment result in chat;
- preserve rollback metadata.

### Phase D - Recovery and polish

- chat-driven rollback of known releases;
- improved code-change summaries/previews;
- additional safe repository profiles and project-specific verification as needed.

## Non-goals

This design does not add:

- unrestricted root/shell access for an LLM;
- arbitrary subprocess execution;
- arbitrary filesystem access;
- arbitrary Git/GitHub administration;
- automatic production deployment without required approval;
- automatic security-policy weakening;
- model-selected credentials, secrets, hosts, paths, commands, or service units;
- a second execution framework parallel to the existing Tool Gateway/delivery architecture.

## Success criteria

The feature is complete when an authenticated user can ask AI HQ in natural language to modify either AI HQ or DripVid, AI HQ can create and verify an isolated machine-derived candidate, QA can evaluate the exact candidate, HQ can present the result in chat, and an explicitly approved candidate can be published and deployed through the existing controlled production path with a complete audit trail and rollback support—without exposing unrestricted shell, filesystem, Git, or production authority to the model.

# HQ Code Change Agent Phase A Implementation Plan

## Goal

Allow authenticated AI HQ chat to recognise bounded code/UI change requests
for AI HQ or DripVid and prepare verified, tested, QA-reviewed repository
candidates without granting the model unrestricted shell, Git, filesystem,
deployment, Host Helper, Docker, or production authority.

## Existing foundations to reuse

- src/ai_hq/chat/intents.py
- src/ai_hq/chat/controller.py
- src/ai_hq/chat/service.py
- src/ai_hq/delivery/repository_profiles.py
- src/ai_hq/delivery/repository_sandbox.py
- src/ai_hq/delivery/repository_workspace.py
- src/ai_hq/delivery/candidate_verifier.py
- src/ai_hq/delivery/model_agents.py
- src/ai_hq/delivery/agent_runner.py
- src/ai_hq/delivery/service.py

## Phase A requirements

1. Add a first-class code-change chat intent.

2. Resolve only these trusted logical repository targets:

   ai-hq
     Waitenomore-ai/ai-hq

   dripvid
     Waitenomore-ai/dripvid

3. Natural-language examples that must resolve:

   "make the DripVid toolbar smaller"
   -> target: dripvid

   "change the AI HQ dashboard layout"
   -> target: ai-hq

   "fix this UI bug in DripVid"
   -> target: dripvid

4. Ambiguous requests must fail closed rather than modifying both projects.

5. Add a trusted DripVid RepositoryProfile.

6. Repository profiles, source paths and verification commands are trusted
   configuration. The model must not supply:

   - shell commands
   - arbitrary source paths
   - Git remotes
   - Git refs
   - Docker commands
   - service commands
   - deployment commands
   - secrets
   - Host Helper operations

7. Developer output is structured data only:

   summary
   rationale
   whole-file WRITE/DELETE FileChange entries

8. Apply changes only through the existing isolated repository sandbox.

9. Sandbox must derive the actual changed-file set and candidate digests.

10. Run only the fixed RepositoryProfile verification commands.

11. A failed or timed-out verification blocks candidate creation.

12. CandidateVerifier must generate the immutable candidate identity.

13. QA must review the exact verified candidate.

14. HQ chat must display:

   repository target
   summary
   changed files
   verification result
   QA result
   candidate change_ref
   status: READY FOR APPROVAL

15. Phase A MUST NOT:

   publish
   push
   merge
   deploy
   restart services
   modify production
   perform rollback

16. Existing SysAdmin read-only operational functionality must continue working.

17. Existing deployment, approval, Host Helper, Tool Gateway and sandbox
   security boundaries must remain unchanged.

## Self-modification safety

Changes targeting ai-hq must use the exact same sandbox and verification
workflow as changes targeting DripVid.

No code-change candidate may directly modify running production files.

Changes involving auth, authorization, approval policy, Tool Gateway,
Host Helper, deployment controls, repository sandbox boundaries, secrets or
audit controls must be marked HIGH RISK and must never bypass approval.

## Tests required

Add tests proving:

- DripVid code-change intent detection
- AI HQ code-change intent detection
- ordinary conversation is unchanged
- operational read requests remain unchanged
- arbitrary shell requests remain refused
- ambiguous repository target fails closed
- unknown repository fails closed
- DripVid profile is trusted/configured
- profile commands cannot come from model output
- Developer can return only typed FileChange data
- sandbox remains required
- changed files are machine-derived
- failed tests block CandidateVerifier
- QA sees exact verified candidate
- Phase A cannot publish or deploy
- high-risk AI HQ self-change is flagged
- existing tests remain green

## Verification

Run:

python -m ruff check src tests
python -m pytest -q

Both must pass before any commit is considered deployable.

## Production rule

DO NOT deploy Phase A merely because code exists.

Deployment is permitted only after:

- Ruff passes
- full pytest suite passes
- changed files are reviewed
- no production/publish capability has accidentally been introduced
- the final commit SHA is known

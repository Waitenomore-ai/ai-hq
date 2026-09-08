# DripVid MCP Chat Acceptance Runbook

Priority 2 acceptance from the handover report (8 September 2026, section 32).
Infrastructure-level MCP communication is already confirmed; what this runbook
proves is the complete `chat -> intent -> worker -> Tool Gateway -> MCP ->
response` path in production, using AI HQ itself.

## 1. Infrastructure pre-checks (host)

```bash
curl -fsS http://127.0.0.1:8788/health
# expect: {"ok":true,"service":"dripvid-server-mcp","version":"0.1.0"}

curl -fsS http://127.0.0.1:8090/health/ready
# expect: {"status":"ready","database":"ok","redis":"ok"}

sudo systemctl is-active dripvid-mcp.service
# expect: active

sudo test -S /run/dripvid-mcp/mcp.sock && echo "socket present"
sudo readlink -f /opt/ai-hq/app
# expect: /opt/ai-hq/releases/<current-production-sha>
```

## 2. Chat-level acceptance prompts (in AI HQ)

Send each prompt in the AI HQ chat exactly as written, and verify the reply
contains live production data (not an error, not a refusal):

### Prompt 1

```
Check DripVid health
```

Expected: a health summary derived from the `dripvid_health` MCP tool, e.g.
`{"ok":true,"service":"dripvid-server-mcp","version":"0.1.0"}` rendered for a
human.

### Prompt 2

```
Show me the current DripVid deployed status
```

Expected: the deployed release information derived from the `dripvid_git_status`
MCP tool, including the DripVid production commit
(`b3ff85243c6ca60ffe3f0488ba56af62cca0fe98` at the time of the handover) or the
current DripVid version.

### Optional prompt 3

```
Is jellyfin running on dripvid?
```

Expected: allowlisted service status for `jellyfin` via
`dripvid.service.status.read`.

## 3. Negative check (must refuse, never reach MCP)

```
Is ssh running on dripvid?
```

Expected: AI HQ explains that `ssh` is not an allowlisted service. No tool call
may be dispatched for an unapproved service name.

```
Show me dripvid logs
```

Expected: explicit refusal — log access is not enabled in the read-only
allowlist.

## 4. What failure looks like

- Chat replies with a generic error / sanitized failure: the worker executed
  but the MCP hop failed. Check `journalctl -u ai-hq-worker` for
  `code_change_runner_failed` or mission failure entries, and
  `journalctl -u dripvid-mcp.service` on the MCP side.
- Chat replies with intent refusal for the two acceptance prompts: the intent
  planner did not classify them as operational DripVid reads. Capture the exact
  prompt text and file an issue against `ai-hq` chat intents.
- Prompts hang longer than ~5 seconds: MCP timeout
  (`AI_HQ_DRIPVID_MCP_TIMEOUT_SECONDS=5`) or a dead socket.

## 5. Automated coverage

`tests/test_dripvid_mcp_end_to_end.py` pins this same path in CI with a real
in-process MCP server over a real Unix-domain socket: initialize handshake,
bearer token rejection, session enforcement, allowlisted tool calls only, and
no dispatch for unknown service names. It is skipped on hosts without
`AF_UNIX` support and runs on Linux CI.

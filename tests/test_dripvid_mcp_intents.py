from ai_hq.chat.intents import plan_sysadmin_intent


def only_step(text):
    intent = plan_sysadmin_intent(text)
    assert intent.kind == "operational"
    assert len(intent.steps) == 1
    return intent.steps[0]


def test_dripvid_health_maps_to_fixed_read_capability():
    step = only_step("check dripvid health")
    assert step["tool_name"] == "dripvid.health.read"
    assert step["tool_arguments"] == {"target": "dripvid"}


def test_dripvid_deployed_version_maps_to_release_read():
    step = only_step("what version of dripvid is deployed?")
    assert step["tool_name"] == "dripvid.release.read"
    assert step["tool_arguments"] == {"target": "dripvid"}


def test_dripvid_config_maps_to_redacted_config_read():
    step = only_step("show dripvid config")
    assert step["tool_name"] == "dripvid.config.read"
    assert step["tool_arguments"] == {"target": "dripvid"}


def test_allowlisted_dripvid_service_status_is_explicit():
    step = only_step("is jellyfin running on dripvid?")
    assert step["tool_name"] == "dripvid.service.status.read"
    assert step["tool_arguments"] == {"target": "dripvid", "service": "jellyfin"}


def test_unknown_service_name_is_not_misread_as_dripvid_service():
    intent = plan_sysadmin_intent("is ssh running on dripvid?")
    assert intent.kind != "operational" or all(
        step["tool_arguments"].get("service") != "dripvid"
        for step in intent.steps
    )


def test_dripvid_logs_are_not_silently_mapped_to_ai_hq_logs():
    intent = plan_sysadmin_intent("show me dripvid logs")
    assert intent.kind == "refused"
    assert "not enabled" in (intent.refusal_reason or "").lower()


def test_arbitrary_mcp_tool_request_is_not_planned():
    intent = plan_sysadmin_intent("use dripvid server_info")
    assert intent.kind != "operational" or all(
        step["tool_name"] != "mcp.tool.call" for step in intent.steps
    )

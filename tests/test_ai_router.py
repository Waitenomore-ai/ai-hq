from ai_hq.ai_router.registry import ModelEndpoint, ModelRegistry, ProviderKind
from ai_hq.ai_router.router import CapabilityClass, ModelRouter


def endpoint(
    provider,
    model,
    capabilities,
    *,
    priority=100,
    kind=ProviderKind.CLOUD,
    enabled=True,
    paid=False,
):
    return ModelEndpoint(
        provider=provider,
        model=model,
        capabilities=frozenset(capabilities),
        priority=priority,
        provider_kind=kind,
        enabled=enabled,
        requires_payment=paid,
        input_cost_per_million=1.0 if paid else 0.0,
        output_cost_per_million=2.0 if paid else 0.0,
    )


def test_agents_route_by_capability_not_hard_coded_provider_name():
    registry = ModelRegistry(
        [
            endpoint("provider-b", "reasoner", {CapabilityClass.COMPLEX_REASONING}, priority=20),
            endpoint("provider-a", "fast", {CapabilityClass.FAST_REASONING}, priority=10),
        ]
    )
    decision = ModelRouter(registry).route(CapabilityClass.FAST_REASONING)
    assert decision.endpoint is not None
    assert decision.endpoint.provider == "provider-a"
    assert decision.endpoint.model == "fast"
    assert decision.reason == "selected"


def test_router_falls_back_when_preferred_provider_is_unavailable():
    preferred = endpoint("provider-a", "fast-a", {CapabilityClass.FAST_REASONING}, priority=10)
    fallback = endpoint("provider-b", "fast-b", {CapabilityClass.FAST_REASONING}, priority=20)
    registry = ModelRegistry([preferred, fallback])
    registry.set_availability("provider-a", "fast-a", False)

    decision = ModelRouter(registry).route(CapabilityClass.FAST_REASONING)
    assert decision.endpoint == fallback
    assert decision.candidates_considered == 1


def test_disabled_models_are_never_selected():
    disabled = endpoint(
        "provider-a",
        "classifier",
        {CapabilityClass.CLASSIFICATION},
        priority=1,
        enabled=False,
    )
    enabled = endpoint(
        "provider-b",
        "classifier",
        {CapabilityClass.CLASSIFICATION},
        priority=2,
    )
    decision = ModelRouter(ModelRegistry([disabled, enabled])).route(
        CapabilityClass.CLASSIFICATION
    )
    assert decision.endpoint == enabled


def test_local_private_request_never_routes_to_cloud():
    cloud = endpoint(
        "cloud-provider",
        "private-capable-label",
        {CapabilityClass.LOCAL_PRIVATE},
        priority=1,
        kind=ProviderKind.CLOUD,
    )
    local = endpoint(
        "local-provider",
        "local-model",
        {CapabilityClass.LOCAL_PRIVATE},
        priority=20,
        kind=ProviderKind.LOCAL,
    )
    decision = ModelRouter(ModelRegistry([cloud, local])).route(CapabilityClass.LOCAL_PRIVATE)
    assert decision.endpoint == local
    assert decision.endpoint.provider_kind is ProviderKind.LOCAL


def test_no_available_capability_returns_controlled_no_route_decision():
    registry = ModelRegistry(
        [endpoint("provider-a", "classifier", {CapabilityClass.CLASSIFICATION})]
    )
    decision = ModelRouter(registry).route(CapabilityClass.LONG_CONTEXT_ANALYSIS)
    assert decision.endpoint is None
    assert decision.reason == "no_available_model"
    assert decision.candidates_considered == 0


def test_routing_order_is_deterministic_when_priorities_match():
    registry = ModelRegistry(
        [
            endpoint("z-provider", "z-model", {CapabilityClass.FAST_REASONING}, priority=10),
            endpoint("a-provider", "a-model", {CapabilityClass.FAST_REASONING}, priority=10),
        ]
    )
    decision = ModelRouter(registry).route(CapabilityClass.FAST_REASONING)
    assert decision.endpoint is not None
    assert (decision.endpoint.provider, decision.endpoint.model) == ("a-provider", "a-model")


def test_paid_models_are_disabled_by_default():
    free = endpoint(
        "free-provider",
        "free-model",
        {CapabilityClass.COMPLEX_REASONING},
        priority=50,
    )
    paid = endpoint(
        "paid-provider",
        "paid-model",
        {CapabilityClass.COMPLEX_REASONING},
        priority=1,
        paid=True,
    )
    decision = ModelRouter(ModelRegistry([paid, free])).route(
        CapabilityClass.COMPLEX_REASONING
    )
    assert decision.endpoint == free


def test_router_prefers_capable_local_model_before_free_cloud():
    cloud = endpoint(
        "free-cloud",
        "fast-cloud",
        {CapabilityClass.FAST_REASONING},
        priority=1,
        kind=ProviderKind.CLOUD,
    )
    local = endpoint(
        "ollama",
        "local-fast",
        {CapabilityClass.FAST_REASONING},
        priority=100,
        kind=ProviderKind.LOCAL,
    )
    decision = ModelRouter(ModelRegistry([cloud, local])).route(
        CapabilityClass.FAST_REASONING
    )
    assert decision.endpoint == local


def test_budget_guard_blocks_expensive_route_even_when_paid_ai_is_enabled():
    paid = endpoint(
        "paid-provider",
        "reasoner",
        {CapabilityClass.COMPLEX_REASONING},
        priority=1,
        paid=True,
    )
    router = ModelRouter(
        ModelRegistry([paid]),
        allow_paid=True,
        budget_check=lambda cost: (False, "daily_budget_exhausted")
        if cost > 0
        else (True, "within_budget"),
    )
    decision = router.route(
        CapabilityClass.COMPLEX_REASONING,
        estimated_input_tokens=1000,
        estimated_output_tokens=1000,
    )
    assert decision.endpoint is None
    assert decision.reason == "daily_budget_exhausted"


def test_phase_one_capability_classes_are_stable():
    assert {item.value for item in CapabilityClass} == {
        "classification",
        "fast_reasoning",
        "complex_reasoning",
        "long_context_analysis",
        "local_private",
    }

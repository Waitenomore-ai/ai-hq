from ai_hq.ai_router.models import CapabilityClass, ModelEndpoint
from ai_hq.ai_router.router import ModelRouter


def endpoint(
    *,
    provider: str,
    model: str,
    capabilities: set[CapabilityClass],
    local: bool = False,
    private: bool = False,
    free: bool = True,
    enabled: bool = True,
    available: bool = True,
    priority: int = 100,
) -> ModelEndpoint:
    return ModelEndpoint(
        provider=provider,
        model=model,
        capabilities=frozenset(capabilities),
        local=local,
        private=private,
        free=free,
        enabled=enabled,
        available=available,
        priority=priority,
    )


def test_router_prefers_capable_local_zero_cost_endpoint():
    router = ModelRouter(
        [
            endpoint(
                provider="free-cloud",
                model="fast-cloud",
                capabilities={CapabilityClass.FAST_REASONING},
                priority=1,
            ),
            endpoint(
                provider="local",
                model="small-local",
                capabilities={CapabilityClass.FAST_REASONING},
                local=True,
                private=True,
                priority=50,
            ),
        ]
    )

    selected = router.route(CapabilityClass.FAST_REASONING)

    assert selected is not None
    assert selected.provider == "local"
    assert selected.model == "small-local"


def test_local_private_never_routes_to_cloud():
    router = ModelRouter(
        [
            endpoint(
                provider="free-cloud",
                model="private-capable-cloud",
                capabilities={CapabilityClass.LOCAL_PRIVATE},
            ),
            endpoint(
                provider="local",
                model="private-local",
                capabilities={CapabilityClass.LOCAL_PRIVATE},
                local=True,
                private=True,
            ),
        ]
    )

    selected = router.route(CapabilityClass.LOCAL_PRIVATE)

    assert selected is not None
    assert selected.local is True
    assert selected.private is True


def test_disabled_and_unavailable_endpoints_are_skipped_deterministically():
    router = ModelRouter(
        [
            endpoint(
                provider="first",
                model="disabled",
                capabilities={CapabilityClass.CLASSIFICATION},
                enabled=False,
                priority=1,
            ),
            endpoint(
                provider="second",
                model="unavailable",
                capabilities={CapabilityClass.CLASSIFICATION},
                available=False,
                priority=2,
            ),
            endpoint(
                provider="third",
                model="available",
                capabilities={CapabilityClass.CLASSIFICATION},
                priority=3,
            ),
        ]
    )

    selected = router.route(CapabilityClass.CLASSIFICATION)

    assert selected is not None
    assert (selected.provider, selected.model) == ("third", "available")


def test_paid_endpoint_is_denied_by_default():
    router = ModelRouter(
        [
            endpoint(
                provider="paid-provider",
                model="paid-model",
                capabilities={CapabilityClass.COMPLEX_REASONING},
                free=False,
            )
        ]
    )

    assert router.route(CapabilityClass.COMPLEX_REASONING) is None


def test_router_returns_none_when_no_capable_free_route_exists():
    router = ModelRouter(
        [
            endpoint(
                provider="free-provider",
                model="classifier",
                capabilities={CapabilityClass.CLASSIFICATION},
            )
        ]
    )

    assert router.route(CapabilityClass.LONG_CONTEXT_ANALYSIS) is None

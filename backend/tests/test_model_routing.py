from types import SimpleNamespace

from app.config import settings
from app.models import ChatRequestMetric
from app.model_routing import ModelHealthRegistry, RoutingContext, route_model


def message(content: str):
    return SimpleNamespace(role="user", content=content)


def test_simple_task_stays_on_economy_model(monkeypatch):
    monkeypatch.setattr(settings, "smart_model_routing_enabled", True)
    decision = route_model("deepseek-v4-flash", [message("帮我改写这句话")])
    assert decision.model == "deepseek-v4-flash"
    assert decision.routed_from is None


def test_critical_conclusion_escalates_to_strong_model(monkeypatch):
    monkeypatch.setattr(settings, "smart_model_routing_enabled", True)
    monkeypatch.setattr(settings, "smart_model_routing_strong_model", "deepseek-v4-pro")
    decision = route_model("deepseek-v4-flash", [message("请对这个恶意样本给出最终结论")])
    assert decision.model == "deepseek-v4-pro"
    assert decision.routed_from == "deepseek-v4-flash"
    assert decision.reason == "critical-conclusion-review"


def test_explicit_strong_model_is_never_downgraded(monkeypatch):
    monkeypatch.setattr(settings, "smart_model_routing_enabled", True)
    decision = route_model("chatgpt-5.5-official", [message("简单总结")])
    assert decision.model == "chatgpt-5.5-official"
    assert decision.routed_from is None


def test_forced_model_wins_over_budget_and_health(monkeypatch):
    monkeypatch.setattr(settings, "smart_model_routing_enabled", True)
    health = ModelHealthRegistry(failure_threshold=1, cooldown_seconds=30)
    health.record_failure("chatgpt-5.5-official", "timeout")
    decision = route_model("chatgpt-5.5-official", [message("简单总结")], RoutingContext(
        force_model=True,
        daily_budget_microusd=1,
        projected_costs={"chatgpt-5.5-official": 100},
    ), health=health)
    assert decision.model == "chatgpt-5.5-official"
    assert decision.forced is True
    assert decision.direction == "unchanged"


def test_high_risk_task_upgrades_before_budget_check(monkeypatch):
    monkeypatch.setattr(settings, "smart_model_routing_enabled", True)
    monkeypatch.setattr(settings, "smart_model_routing_strong_model", "deepseek-v4-pro")
    decision = route_model("deepseek-v4-flash", [message("分析告警")], RoutingContext(
        risk_level="critical",
        daily_budget_microusd=100,
        projected_costs={"deepseek-v4-pro": 80, "deepseek-v4-flash": 10},
    ))
    assert decision.model == "deepseek-v4-pro"
    assert decision.reason == "high-risk-task"
    assert decision.direction == "upgrade"


def test_daily_budget_downgrades_automatic_upgrade(monkeypatch):
    monkeypatch.setattr(settings, "smart_model_routing_enabled", True)
    decision = route_model("deepseek-v4-flash", [message("请做深入分析")], RoutingContext(
        daily_budget_microusd=50,
        projected_costs={"deepseek-v4-pro": 100, "deepseek-v4-flash": 10},
    ))
    assert decision.model == "deepseek-v4-flash"
    assert decision.reason == "daily-budget"


def test_user_whitelist_is_enforced_before_smart_routing(monkeypatch):
    monkeypatch.setattr(settings, "smart_model_routing_enabled", True)
    decision = route_model("chatgpt-5.5-official", [message("分析")], RoutingContext(
        user_model_whitelist=frozenset({"deepseek-v4-flash"}),
    ))
    assert decision.model == "chatgpt-5.5-official"
    assert decision.reason == "model-not-allowed"
    assert decision.direction == "unchanged"


def test_health_cooldown_and_single_recovery_probe():
    now = [100.0]
    health = ModelHealthRegistry(failure_threshold=2, cooldown_seconds=10, clock=lambda: now[0])
    health.record_failure("deepseek-v4-pro", "timeout")
    assert health.allow("deepseek-v4-pro") is True
    health.record_failure("deepseek-v4-pro", "timeout")
    assert health.allow("deepseek-v4-pro") is False
    now[0] = 111.0
    assert health.allow("deepseek-v4-pro") is True
    assert health.allow("deepseek-v4-pro") is False
    health.record_success("deepseek-v4-pro")
    assert health.allow("deepseek-v4-pro") is True


def test_long_context_escalates(monkeypatch):
    monkeypatch.setattr(settings, "smart_model_routing_enabled", True)
    monkeypatch.setattr(settings, "smart_model_routing_long_context_tokens", 100)
    decision = route_model("deepseek-v4-flash", [message("分析")], RoutingContext(context_tokens=101))
    assert decision.model == "deepseek-v4-pro"
    assert decision.reason == "long-context"


def test_unhealthy_automatic_upgrade_falls_back(monkeypatch):
    monkeypatch.setattr(settings, "smart_model_routing_enabled", True)
    health = ModelHealthRegistry(failure_threshold=1, cooldown_seconds=30)
    health.record_failure("deepseek-v4-pro", "timeout")
    decision = route_model("deepseek-v4-flash", [message("请做深入分析")], health=health)
    assert decision.model == "deepseek-v4-flash"
    assert decision.reason == "model-cooldown"
    assert decision.direction == "unchanged"


def test_routing_audit_fields_capture_requested_final_reason_cost_and_quality():
    metric = ChatRequestMetric(
        model_id="deepseek-v4-pro",
        requested_model="deepseek-v4-flash",
        routed_from_model="deepseek-v4-flash",
        routing_reason="high-risk-task",
        routing_direction="upgrade",
        provider="deepseek",
        duration_ms=125.0,
        cost_microusd=42,
        result_quality=1.0,
    )
    assert metric.requested_model == "deepseek-v4-flash"
    assert metric.model_id == "deepseek-v4-pro"
    assert metric.routing_reason == "high-risk-task"
    assert metric.duration_ms == 125.0
    assert metric.cost_microusd == 42
    assert metric.result_quality == 1.0

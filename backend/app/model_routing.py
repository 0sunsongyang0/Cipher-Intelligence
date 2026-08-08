from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
import time
from typing import Callable, Iterable

from app.config import settings


CRITICAL_TASK_MARKERS = (
    "关键结论", "最终结论", "交叉验证", "强模型复核", "风险判定", "威胁分类",
    "恶意样本", "应急响应结论", "法律意见", "医疗诊断", "投资决策",
    "critical conclusion", "final verdict", "cross-check", "malware verdict",
)
COMPLEX_TASK_MARKERS = (
    "深入分析", "根因分析", "架构设计", "代码审计", "取证", "威胁建模",
    "deep analysis", "root cause", "architecture", "code audit", "forensics",
)
SIMPLE_TASK_MARKERS = ("改写", "翻译", "摘要", "总结", "rewrite", "translate", "summarize")

SUPPORTED_MODELS = {
    "deepseek-v4-flash", "deepseek-v4-pro",
    "chatgpt-5.5-official", "chatgpt-5.4-az",
    "chatgpt-5.5-backup", "chatgpt-5.4-backup",
    "claude-opus-4-7-official", "claude-opus-4-6-aws",
    "claude-sonnet-4-6-az", "claude-opus-4-7-backup",
    "claude-opus-4-6-backup", "claude-sonnet-4-6-backup",
}
STRONG_MODELS = {
    "deepseek-v4-pro", "chatgpt-5.5-official", "chatgpt-5.4-az",
    "chatgpt-5.5-backup", "chatgpt-5.4-backup", "claude-opus-4-7-official",
    "claude-opus-4-6-aws", "claude-sonnet-4-6-az", "claude-opus-4-7-backup",
    "claude-opus-4-6-backup", "claude-sonnet-4-6-backup",
}
PLAN_ALLOWED_MODELS = {
    "free": {"deepseek-v4-flash", "deepseek-v4-pro"},
    "standard": SUPPORTED_MODELS,
    "pro": SUPPORTED_MODELS,
    "enterprise": SUPPORTED_MODELS,
}


@dataclass(frozen=True)
class RoutingContext:
    task_type: str | None = None
    risk_level: str = "normal"
    context_tokens: int = 0
    user_plan: str = "standard"
    user_model_whitelist: frozenset[str] | None = None
    daily_budget_microusd: int | None = None
    daily_spend_microusd: int = 0
    projected_costs: dict[str, int] = field(default_factory=dict)
    force_model: bool = False


@dataclass(frozen=True)
class ModelRoutingDecision:
    model: str
    routed_from: str | None = None
    reason: str | None = None
    direction: str = "unchanged"
    task_type: str = "general"
    risk_level: str = "normal"
    forced: bool = False


@dataclass
class ModelHealth:
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    probe_in_flight: bool = False
    last_failure: str | None = None


class ModelHealthRegistry:
    """Process-local circuit breaker with a single half-open recovery probe."""

    def __init__(self, *, failure_threshold: int = 2, cooldown_seconds: float = 30.0,
                 clock: Callable[[], float] = time.monotonic):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock
        self._states: dict[str, ModelHealth] = {}
        self._lock = Lock()

    def allow(self, model: str) -> bool:
        with self._lock:
            state = self._states.setdefault(model, ModelHealth())
            if state.cooldown_until <= 0:
                return True
            if self.clock() < state.cooldown_until:
                return False
            if state.probe_in_flight:
                return False
            state.probe_in_flight = True
            return True

    def record_success(self, model: str) -> None:
        with self._lock:
            self._states[model] = ModelHealth()

    def record_failure(self, model: str, reason: str) -> None:
        with self._lock:
            state = self._states.setdefault(model, ModelHealth())
            state.consecutive_failures += 1
            state.probe_in_flight = False
            state.last_failure = reason
            if state.consecutive_failures >= self.failure_threshold:
                state.cooldown_until = self.clock() + self.cooldown_seconds

    def reset(self) -> None:
        with self._lock:
            self._states.clear()


model_health = ModelHealthRegistry(
    failure_threshold=settings.smart_model_routing_failure_threshold,
    cooldown_seconds=settings.smart_model_routing_cooldown_seconds,
)


def infer_task_type(messages: list[object]) -> str:
    text = _latest_user_text(messages)
    if any(marker in text for marker in CRITICAL_TASK_MARKERS):
        return "critical_analysis"
    if any(marker in text for marker in COMPLEX_TASK_MARKERS):
        return "complex_analysis"
    if any(marker in text for marker in SIMPLE_TASK_MARKERS):
        return "simple"
    return "general"


def route_model(requested_model: str, messages: list[object], context: RoutingContext | None = None,
                *, health: ModelHealthRegistry | None = None) -> ModelRoutingDecision:
    """Route in strict order: force/protection, access, risk/task/context, budget, health."""
    routing = context or RoutingContext()
    task_type = routing.task_type or infer_task_type(messages)
    risk_level = routing.risk_level.casefold()
    protected = routing.force_model or requested_model in STRONG_MODELS
    common = {"task_type": task_type, "risk_level": risk_level, "forced": routing.force_model}

    if requested_model not in SUPPORTED_MODELS:
        return ModelRoutingDecision(requested_model, **common)

    allowed = set(PLAN_ALLOWED_MODELS.get(routing.user_plan.casefold(), PLAN_ALLOWED_MODELS["standard"]))
    if routing.user_model_whitelist is not None:
        allowed &= set(routing.user_model_whitelist)
    if requested_model not in allowed:
        if protected:
            return ModelRoutingDecision(requested_model, reason="model-not-allowed", **common)
        replacement = _first_allowed((settings.smart_model_routing_economy_model,
                                      settings.smart_model_routing_strong_model), allowed)
        if replacement is None:
            return ModelRoutingDecision(requested_model, reason="model-not-allowed", **common)
        return _decision(requested_model, replacement, "model-not-allowed", common)

    if not settings.smart_model_routing_enabled or protected:
        return ModelRoutingDecision(requested_model, **common)

    candidate = requested_model
    reason: str | None = None
    needs_strong = risk_level in {"high", "critical"} or task_type in {"critical_analysis", "complex_analysis"}
    if routing.context_tokens >= settings.smart_model_routing_long_context_tokens:
        needs_strong, reason = True, "long-context"
    elif needs_strong:
        reason = ("high-risk-task" if risk_level in {"high", "critical"} else
                  "critical-conclusion-review" if task_type == "critical_analysis" else "task-complexity")
    if needs_strong:
        strong = settings.smart_model_routing_strong_model.strip()
        if strong in allowed and strong in SUPPORTED_MODELS:
            candidate = strong

    remaining = None if routing.daily_budget_microusd is None else max(
        0, routing.daily_budget_microusd - routing.daily_spend_microusd
    )
    if remaining is not None and routing.projected_costs.get(candidate, 0) > remaining:
        economy = settings.smart_model_routing_economy_model.strip()
        if economy in allowed and routing.projected_costs.get(economy, 0) <= remaining:
            candidate, reason = economy, "daily-budget"
        else:
            return ModelRoutingDecision(requested_model, reason="daily-budget-exhausted", **common)

    registry = health or model_health
    if not registry.allow(candidate):
        fallback = _first_allowed(_fallbacks(candidate), allowed, registry)
        if fallback is not None:
            candidate, reason = fallback, "model-cooldown"

    return _decision(requested_model, candidate, reason, common)


def _latest_user_text(messages: list[object]) -> str:
    for message in reversed(messages):
        if getattr(message, "role", None) == "user" and isinstance(getattr(message, "content", None), str):
            return message.content.casefold()
    return ""


def _fallbacks(model: str) -> tuple[str, ...]:
    if model in STRONG_MODELS:
        return (settings.smart_model_routing_strong_model, "deepseek-v4-pro",
                settings.smart_model_routing_economy_model)
    return (settings.smart_model_routing_economy_model, "deepseek-v4-flash")


def _first_allowed(models: Iterable[str], allowed: set[str], registry: ModelHealthRegistry | None = None) -> str | None:
    for model in models:
        if model in allowed and model in SUPPORTED_MODELS and (registry is None or registry.allow(model)):
            return model
    return None


def _decision(requested: str, selected: str, reason: str | None, common: dict[str, object]) -> ModelRoutingDecision:
    if selected == requested:
        return ModelRoutingDecision(selected, reason=reason, **common)
    direction = "upgrade" if selected in STRONG_MODELS and requested not in STRONG_MODELS else "downgrade"
    return ModelRoutingDecision(selected, routed_from=requested, reason=reason, direction=direction, **common)

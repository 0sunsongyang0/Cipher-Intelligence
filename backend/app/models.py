from datetime import datetime, timezone
import json

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_session_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    case_status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    assignee: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    case_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_template_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_templates.id"), nullable=True, index=True)
    analysis_template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    analysis_config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    case_links: Mapped[list["CaseConversation"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )

    @property
    def tags(self) -> list[str]:
        try:
            parsed = json.loads(self.tags_json or "[]")
        except json.JSONDecodeError:
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []

    @property
    def analysis_config(self) -> dict | None:
        try:
            value = json.loads(self.analysis_config_json) if self.analysis_config_json else None
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    attachments: Mapped[list["MessageAttachment"]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )
    evidence: Mapped[list["MessageEvidence"]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


class MessageAttachment(Base):
    __tablename__ = "message_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attachment_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    meta: Mapped[str | None] = mapped_column(Text, nullable=True)

    message: Mapped[Message] = relationship(back_populates="attachments")


class MessageEvidence(Base):
    __tablename__ = "message_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    citation: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    locator: Mapped[str | None] = mapped_column(String(255), nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    source_trust: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    snapshot_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    message: Mapped[Message] = relationship(back_populates="evidence")


class MessageFeedback(Base):
    __tablename__ = "message_feedback"
    __table_args__ = (UniqueConstraint("message_id", "user_id", name="uq_message_feedback_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False
    )


class ChatRequestMetric(Base):
    __tablename__ = "chat_request_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assistant_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    prompt_version: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    web_search: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    response_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    response_length: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False, index=True)
    first_token_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_microusd: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    routed_from_model: Mapped[str | None] = mapped_column(String(96), nullable=True)
    requested_model: Mapped[str | None] = mapped_column(String(96), nullable=True)
    routing_reason: Mapped[str | None] = mapped_column(String(96), nullable=True)
    routing_direction: Mapped[str] = mapped_column(String(16), nullable=False, default="unchanged")
    result_quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    attachment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False, index=True)


class EvalTestSet(Base):
    __tablename__ = "eval_test_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", index=True)
    authorization_note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)

    cases: Mapped[list["EvalTestCase"]] = relationship(back_populates="test_set", cascade="all, delete-orphan")
    runs: Mapped[list["EvalRun"]] = relationship(back_populates="test_set")


class EvalTestCase(Base):
    __tablename__ = "eval_test_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    test_set_id: Mapped[int] = mapped_column(ForeignKey("eval_test_sets.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False, default="general", index=True)
    input: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str] = mapped_column(Text, nullable=False)
    expected_citations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    required_format: Mapped[str] = mapped_column(String(80), nullable=False, default="markdown", index=True)
    false_positive_terms_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    sanitized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    authorized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)

    test_set: Mapped[EvalTestSet] = relationship(back_populates="cases")
    results: Mapped[list["EvalRunResult"]] = relationship(back_populates="test_case", cascade="all, delete-orphan")

    @property
    def expected_citations(self) -> list[str]:
        return _json_list(self.expected_citations_json)

    @property
    def false_positive_terms(self) -> list[str]:
        return _json_list(self.false_positive_terms_json)

    @property
    def tags(self) -> list[str]:
        return _json_list(self.tags_json)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    test_set_id: Mapped[int] = mapped_column(ForeignKey("eval_test_sets.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="completed", index=True)
    model_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    route_strategy: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    prompt_version: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    gate_thresholds_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    test_set: Mapped[EvalTestSet | None] = relationship(back_populates="runs")
    results: Mapped[list["EvalRunResult"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class EvalRunResult(Base):
    __tablename__ = "eval_run_results"
    __table_args__ = (UniqueConstraint("run_id", "test_case_id", name="uq_eval_result_run_case"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    test_case_id: Mapped[int] = mapped_column(ForeignKey("eval_test_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    output: Mapped[str] = mapped_column(Text, nullable=False)
    accuracy: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    citation_coverage: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    false_positive_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    format_compliance: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    first_token_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    cost_microusd: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detail_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    run: Mapped[EvalRun] = relationship(back_populates="results")
    test_case: Mapped[EvalTestCase] = relationship(back_populates="results")


class Job(Base):
    """Durable record for work that must outlive an HTTP request."""

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "task_type", "idempotency_key", name="uq_jobs_idempotency"),
        Index("ix_jobs_claim", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False
    )


class CapeCase(Base):
    __tablename__ = "cape_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    cape_task_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    sample_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(80), nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    machine: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    reused_existing_task: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False
    )


class UsageLedgerEntry(Base):
    """Append-only billable usage record; amounts are integer micro-USD."""
    __tablename__ = "usage_ledger_entries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_usage_ledger_idempotency"),
        Index("ix_usage_ledger_user_period", "user_id", "occurred_at"),
        Index("ix_usage_ledger_org_period", "organization_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    resource_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cost_microusd: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False, index=True)


class QuotaOverride(Base):
    """Optional local override. Casdoor subscription tier remains the default policy source."""
    __tablename__ = "quota_overrides"
    __table_args__ = (UniqueConstraint("scope_type", "scope_id", name="uq_quota_override_scope"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)  # user / organization
    scope_id: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_cost_microusd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    concurrent_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_cape_submissions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hard_limit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    warning_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)


class CommerceSubscription(Base):
    """Local entitlement snapshot of a Casdoor commercial subscription."""
    __tablename__ = "commerce_subscriptions"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_commerce_subscription_external"),
        Index("ix_commerce_subscription_user_state", "user_id", "state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(24), nullable=False, default="casdoor")
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    plan_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    plan_display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    tier: Mapped[str] = mapped_column(String(24), nullable=False, default="free", index=True)
    pricing_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payment_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    period: Mapped[str | None] = mapped_column(String(32), nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)


class UsageCreditGrant(Base):
    """Idempotent add-on entitlement granted from a paid external product."""
    __tablename__ = "usage_credit_grants"
    __table_args__ = (UniqueConstraint("provider", "external_key", name="uq_usage_credit_external"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(24), nullable=False, default="casdoor")
    external_key: Mapped[str] = mapped_column(String(255), nullable=False)
    product_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    token_credit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_credit_microusd: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cape_submission_credit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_credit_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class InvestigationCase(Base):
    __tablename__ = "investigation_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    assignee_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", index=True)
    assignee: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_template_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_templates.id"), nullable=True, index=True)
    analysis_template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    analysis_config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3, index=True)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    parent_case_id: Mapped[int | None] = mapped_column(ForeignKey("investigation_cases.id"), nullable=True, index=True)
    merged_into_case_id: Mapped[int | None] = mapped_column(ForeignKey("investigation_cases.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    conversation_links: Mapped[list["CaseConversation"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    events: Mapped[list["CaseEvent"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    indicators: Mapped[list["CaseIndicator"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    detection_rules: Mapped[list["DetectionRule"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    playbooks: Mapped[list["InvestigationPlaybook"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    conclusions: Mapped[list["CaseConclusion"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    signatures: Mapped[list["CaseSignature"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )

    @property
    def tags(self) -> list[str]:
        try:
            parsed = json.loads(self.tags_json or "[]")
        except json.JSONDecodeError:
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []


class CaseConversation(Base):
    __tablename__ = "case_conversations"
    __table_args__ = (UniqueConstraint("case_id", "conversation_id", name="uq_case_conversation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    case: Mapped[InvestigationCase] = relationship(back_populates="conversation_links")
    conversation: Mapped[Conversation] = relationship(back_populates="case_links")


class CaseEvent(Base):
    __tablename__ = "case_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    actor: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False, index=True)

    case: Mapped[InvestigationCase] = relationship(back_populates="events")


class CaseConclusion(Base):
    __tablename__ = "case_conclusions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", index=True)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    claim_type: Mapped[str] = mapped_column(String(16), nullable=False, default="inference")
    confidence_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    conflict_evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    cross_checks_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)

    case: Mapped[InvestigationCase] = relationship(back_populates="conclusions")
    evidence_links: Mapped[list["CaseConclusionEvidence"]] = relationship(
        back_populates="conclusion", cascade="all, delete-orphan"
    )


class CaseConclusionEvidence(Base):
    __tablename__ = "case_conclusion_evidence"
    __table_args__ = (UniqueConstraint("conclusion_id", "evidence_id", name="uq_conclusion_evidence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conclusion_id: Mapped[int] = mapped_column(ForeignKey("case_conclusions.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("message_evidence.id", ondelete="CASCADE"), nullable=False, index=True)

    conclusion: Mapped[CaseConclusion] = relationship(back_populates="evidence_links")
    evidence: Mapped[MessageEvidence] = relationship()


class CaseSignature(Base):
    __tablename__ = "case_signatures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    signer: Mapped[str] = mapped_column(String(80), nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    case: Mapped[InvestigationCase] = relationship(back_populates="signatures")


class InvestigationPlaybook(Base):
    __tablename__ = "investigation_playbooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    template_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    case: Mapped[InvestigationCase] = relationship(back_populates="playbooks")
    steps: Mapped[list["InvestigationPlaybookStep"]] = relationship(
        back_populates="playbook", cascade="all, delete-orphan", order_by="InvestigationPlaybookStep.position"
    )


class InvestigationPlaybookStep(Base):
    __tablename__ = "investigation_playbook_steps"
    __table_args__ = (UniqueConstraint("playbook_id", "step_key", name="uq_playbook_step"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    playbook_id: Mapped[int] = mapped_column(ForeignKey("investigation_playbooks.id", ondelete="CASCADE"), nullable=False, index=True)
    step_key: Mapped[str] = mapped_column(String(48), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    input_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    output_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)

    playbook: Mapped[InvestigationPlaybook] = relationship(back_populates="steps")


class CaseIndicator(Base):
    __tablename__ = "case_indicators"
    __table_args__ = (
        UniqueConstraint("case_id", "indicator_type", "normalized_value", name="uq_case_indicator"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    indicator_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown", index=True)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False, default="cape")
    cape_case_id: Mapped[int | None] = mapped_column(ForeignKey("cape_cases.id", ondelete="SET NULL"), nullable=True, index=True)
    sample_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    enrichment_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)

    case: Mapped[InvestigationCase] = relationship(back_populates="indicators")


class ThreatIntelCache(Base):
    __tablename__ = "threat_intel_cache"
    __table_args__ = (
        UniqueConstraint("provider", "indicator_type", "normalized_value", name="uq_threat_intel_cache"),
        Index("ix_threat_intel_cache_lookup", "indicator_type", "normalized_value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    indicator_type: Mapped[str] = mapped_column(String(16), nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    stale_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class DetectionRule(Base):
    __tablename__ = "detection_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_cape_case_id: Mapped[int | None] = mapped_column(
        ForeignKey("cape_cases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    rule_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    validation_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="not_validated", index=True
    )
    validation_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False
    )

    case: Mapped[InvestigationCase] = relationship(back_populates="detection_rules")
    versions: Mapped[list["DetectionRuleVersion"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )
    test_runs: Mapped[list["DetectionRuleTestRun"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )


class DetectionRuleVersion(Base):
    __tablename__ = "detection_rule_versions"
    __table_args__ = (UniqueConstraint("rule_id", "version", name="uq_detection_rule_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("detection_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    validation_status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_validated")
    validation_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    actor: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    rule: Mapped[DetectionRule] = relationship(back_populates="versions")


class DetectionRuleTestRun(Base):
    __tablename__ = "detection_rule_test_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("detection_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    total_artifacts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_artifacts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    false_positive_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    rule: Mapped[DetectionRule] = relationship(back_populates="test_runs")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    casdoor_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    casdoor_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    avatar_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    casdoor_avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    casdoor_providers_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    casdoor_mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    casdoor_password_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    casdoor_last_signin_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    casdoor_last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_source: Mapped[str] = mapped_column(String(24), nullable=False, default="local", index=True)
    totp_secret: Mapped[str | None] = mapped_column(String(512), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    suspicious_login_alerts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    subscription_tier: Mapped[str] = mapped_column(
        String(24), nullable=False, default="standard", index=True
    )
    model_whitelist_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False
    )

    __table_args__ = (
        Index("ux_users_username_normalized", func.lower(username), unique=True),
        Index("ux_users_casdoor_subject", casdoor_subject, unique=True),
    )


class AccountRecoveryCode(Base):
    __tablename__ = "account_recovery_codes"
    __table_args__ = (UniqueConstraint("user_id", "code_hash", name="uq_recovery_code_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class LoginEvent(Base):
    __tablename__ = "login_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    suspicious: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False, index=True)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    identity_source: Mapped[str] = mapped_column(String(24), nullable=False, default="local", index=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)


class OrganizationMember(Base):
    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_organization_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="viewer", index=True)
    identity_source: Mapped[str] = mapped_column(String(24), nullable=False, default="local", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class AnalysisTemplate(Base):
    __tablename__ = "analysis_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    scenario: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    checklist_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    required_skills_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    output_format: Mapped[str] = mapped_column(Text, nullable=False)
    required_evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    recommended_model: Mapped[str] = mapped_column(String(120), nullable=False)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", index=True)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)


class AnalysisTemplateVersion(Base):
    __tablename__ = "analysis_template_versions"
    __table_args__ = (UniqueConstraint("template_id", "version", name="uq_analysis_template_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("analysis_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_workspace_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    identity_source: Mapped[str] = mapped_column(String(24), nullable=False, default="local", index=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="viewer", index=True)
    identity_source: Mapped[str] = mapped_column(String(24), nullable=False, default="local", index=True)


class CaseAccess(Base):
    __tablename__ = "case_access"
    __table_args__ = (UniqueConstraint("case_id", "user_id", name="uq_case_access"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    permission: Mapped[str] = mapped_column(String(16), nullable=False, default="viewer")
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class CaseFollower(Base):
    __tablename__ = "case_followers"
    __table_args__ = (UniqueConstraint("case_id", "user_id", name="uq_case_follower"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class CaseComment(Base):
    __tablename__ = "case_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    author_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", "idempotency_key", name="uq_notification_delivery"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    notification_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=True, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    resource_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False, index=True)


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", "notification_type", name="uq_notification_preference"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    notification_type: Mapped[str] = mapped_column(String(32), nullable=False)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    web_push_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="success", index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_username: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    actor_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    detail_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False, index=True)


class DataRetentionPolicy(Base):
    """Tenant-wide retention controls. Values are days; 0 means disabled/keep forever."""
    __tablename__ = "data_retention_policies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    chat_days: Mapped[int] = mapped_column(Integer, nullable=False, default=365)
    upload_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    cape_days: Mapped[int] = mapped_column(Integer, nullable=False, default=365)
    ioc_days: Mapped[int] = mapped_column(Integer, nullable=False, default=730)
    case_days: Mapped[int] = mapped_column(Integer, nullable=False, default=2555)
    audit_days: Mapped[int] = mapped_column(Integer, nullable=False, default=2555)
    billing_days: Mapped[int] = mapped_column(Integer, nullable=False, default=2555)
    profile_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)


class ObservabilityEvent(Base):
    __tablename__ = "observability_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_name: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    organization_id: Mapped[int | None] = mapped_column(Integer, index=True)
    route: Mapped[str | None] = mapped_column(String(255), index=True)
    model_id: Mapped[str | None] = mapped_column(String(96), index=True)
    task_id: Mapped[str | None] = mapped_column(String(128), index=True)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(96), index=True)
    status_code: Mapped[int | None] = mapped_column(Integer, index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True, nullable=False)


class SkillPackage(Base):
    __tablename__ = "skill_packages"
    __table_args__ = (UniqueConstraint("skill_key", "version", name="uq_skill_package_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    skill_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author: Mapped[str] = mapped_column(String(120), nullable=False, default="Cipher")
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="builtin")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    permissions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    review_status: Mapped[str] = mapped_column(String(24), nullable=False, default="verified", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    package_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    signature_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unverified", index=True)
    release_status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)

    installations: Mapped[list["SkillInstallation"]] = relationship(
        back_populates="skill", cascade="all, delete-orphan"
    )


class SkillInstallation(Base):
    __tablename__ = "skill_installations"
    __table_args__ = (UniqueConstraint("skill_id", "user_id", name="uq_skill_installation_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    skill_id: Mapped[int] = mapped_column(
        ForeignKey("skill_packages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    approved_permissions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    skill: Mapped[SkillPackage] = relationship(back_populates="installations")


class SkillRun(Base):
    __tablename__ = "skill_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skill_packages.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("investigation_cases.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="completed", index=True)
    input_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    output_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_allowlist_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    policy_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    output_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InviteCode(Base):
    __tablename__ = "invite_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )

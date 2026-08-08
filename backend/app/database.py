from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

LEGACY_OWNER_SESSION_ID = 0
OWNER_SESSION_INDEX_NAME = "ix_conversations_owner_session_id"
SESSION_USER_INDEX_NAME = "ix_sessions_user_id"
CONVERSATION_OWNER_USER_INDEX_NAME = "ix_conversations_owner_user_id"
USER_USERNAME_NORMALIZED_INDEX_NAME = "ux_users_username_normalized"
USER_CASDOOR_SUBJECT_INDEX_NAME = "ux_users_casdoor_subject"


def _ensure_sqlite_directory(database_url: str) -> None:
    sqlite_prefix = "sqlite:///"
    if not database_url.startswith(sqlite_prefix):
        return

    database_path = database_url.removeprefix(sqlite_prefix)
    if database_path == ":memory:":
        return

    Path(database_path).parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_directory(settings.database_url)


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    hide_parameters=True,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _migrate_sqlite_conversations_owner_session_id() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    with engine.begin() as connection:
        conversations_exists = (
            connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'conversations'"
            ).fetchone()
            is not None
        )
        if not conversations_exists:
            return

        rows = connection.exec_driver_sql("PRAGMA table_info(conversations)").fetchall()
        if not any(row[1] == "owner_session_id" for row in rows):
            connection.exec_driver_sql(
                f"ALTER TABLE conversations ADD COLUMN owner_session_id INTEGER NOT NULL DEFAULT {LEGACY_OWNER_SESSION_ID}"
            )

        connection.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS {OWNER_SESSION_INDEX_NAME} ON conversations (owner_session_id)"
        )


def _migrate_sqlite_account_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    with engine.begin() as connection:
        user_rows = connection.exec_driver_sql("PRAGMA table_info(users)").fetchall()
        if not any(row[1] == "display_name" for row in user_rows):
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN display_name VARCHAR(80)")
        if not any(row[1] == "avatar_filename" for row in user_rows):
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN avatar_filename VARCHAR(255)")
        if not any(row[1] == "casdoor_subject" for row in user_rows):
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN casdoor_subject VARCHAR(255)")
        if not any(row[1] == "casdoor_name" for row in user_rows):
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN casdoor_name VARCHAR(64)")
        if not any(row[1] == "email" for row in user_rows):
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN email VARCHAR(320)")
        if not any(row[1] == "email_verified" for row in user_rows):
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT 0"
            )
        if not any(row[1] == "casdoor_avatar_url" for row in user_rows):
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN casdoor_avatar_url VARCHAR(2048)"
            )
        if not any(row[1] == "casdoor_providers_json" for row in user_rows):
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN casdoor_providers_json TEXT NOT NULL DEFAULT '[]'"
            )
        if not any(row[1] == "casdoor_mfa_enabled" for row in user_rows):
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN casdoor_mfa_enabled BOOLEAN NOT NULL DEFAULT 0"
            )
        if not any(row[1] == "casdoor_password_enabled" for row in user_rows):
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN casdoor_password_enabled BOOLEAN NOT NULL DEFAULT 0"
            )
        if not any(row[1] == "casdoor_last_signin_at" for row in user_rows):
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN casdoor_last_signin_at VARCHAR(64)"
            )
        if not any(row[1] == "casdoor_last_synced_at" for row in user_rows):
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN casdoor_last_synced_at DATETIME"
            )
        if not any(row[1] == "subscription_tier" for row in user_rows):
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN subscription_tier VARCHAR(24) NOT NULL DEFAULT 'standard'"
            )
        additions = {
            "auth_source": "VARCHAR(24) NOT NULL DEFAULT 'local'",
            "totp_secret": "VARCHAR(512)",
            "totp_enabled": "BOOLEAN NOT NULL DEFAULT 0",
            "suspicious_login_alerts": "BOOLEAN NOT NULL DEFAULT 1",
        }
        existing_user_columns = {row[1] for row in user_rows}
        for name, definition in additions.items():
            if name not in existing_user_columns:
                connection.exec_driver_sql(f"ALTER TABLE users ADD COLUMN {name} {definition}")
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_users_subscription_tier ON users (subscription_tier)"
        )
        connection.exec_driver_sql(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {USER_USERNAME_NORMALIZED_INDEX_NAME} "
            "ON users (LOWER(username))"
        )
        connection.exec_driver_sql(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {USER_CASDOOR_SUBJECT_INDEX_NAME} "
            "ON users (casdoor_subject) WHERE casdoor_subject IS NOT NULL"
        )

        session_rows = connection.exec_driver_sql("PRAGMA table_info(sessions)").fetchall()
        if not any(row[1] == "user_id" for row in session_rows):
            connection.exec_driver_sql("ALTER TABLE sessions ADD COLUMN user_id INTEGER")
        existing_session_columns = {row[1] for row in session_rows}
        for name, definition in {
            "last_seen_at": "DATETIME NOT NULL DEFAULT '1970-01-01 00:00:00'",
            "ip_address": "VARCHAR(64)",
            "user_agent": "VARCHAR(512)",
        }.items():
            if name not in existing_session_columns:
                connection.exec_driver_sql(f"ALTER TABLE sessions ADD COLUMN {name} {definition}")
        connection.exec_driver_sql(
            "UPDATE sessions SET last_seen_at = created_at WHERE last_seen_at = '1970-01-01 00:00:00'"
        )
        connection.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS {SESSION_USER_INDEX_NAME} ON sessions (user_id)"
        )

        conversation_rows = connection.exec_driver_sql(
            "PRAGMA table_info(conversations)"
        ).fetchall()
        if not any(row[1] == "owner_user_id" for row in conversation_rows):
            connection.exec_driver_sql("ALTER TABLE conversations ADD COLUMN owner_user_id INTEGER")
        connection.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS {CONVERSATION_OWNER_USER_INDEX_NAME} ON conversations (owner_user_id)"
        )


def _migrate_sqlite_conversation_management_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    with engine.begin() as connection:
        rows = connection.exec_driver_sql("PRAGMA table_info(conversations)").fetchall()
        if not rows:
            return
        if not any(row[1] == "is_pinned" for row in rows):
            connection.exec_driver_sql(
                "ALTER TABLE conversations ADD COLUMN is_pinned BOOLEAN NOT NULL DEFAULT 0"
            )
        if not any(row[1] == "is_archived" for row in rows):
            connection.exec_driver_sql(
                "ALTER TABLE conversations ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT 0"
            )
        if not any(row[1] == "case_status" for row in rows):
            connection.exec_driver_sql(
                "ALTER TABLE conversations ADD COLUMN case_status VARCHAR(32) NOT NULL DEFAULT 'open'"
            )
        if not any(row[1] == "severity" for row in rows):
            connection.exec_driver_sql(
                "ALTER TABLE conversations ADD COLUMN severity VARCHAR(32) NOT NULL DEFAULT 'unknown'"
            )
        if not any(row[1] == "assignee" for row in rows):
            connection.exec_driver_sql(
                "ALTER TABLE conversations ADD COLUMN assignee VARCHAR(80)"
            )
        if not any(row[1] == "tags_json" for row in rows):
            connection.exec_driver_sql(
                "ALTER TABLE conversations ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'"
            )
        if not any(row[1] == "case_summary" for row in rows):
            connection.exec_driver_sql(
                "ALTER TABLE conversations ADD COLUMN case_summary TEXT"
            )


def init_db() -> None:
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_conversations_owner_session_id()
    _migrate_sqlite_account_schema()
    _migrate_sqlite_conversation_management_schema()
    _migrate_sqlite_analysis_template_schema()
    _migrate_sqlite_usage_schema()
    _migrate_sqlite_evidence_review_schema()
    _migrate_sqlite_explainable_conclusions_schema()
    _migrate_sqlite_tenancy_schema()
    _migrate_sqlite_notification_schema()
    _migrate_sqlite_skill_security_schema()
    _migrate_sqlite_eval_schema()


def _migrate_sqlite_eval_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_eval_test_sets_name ON eval_test_sets (name)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_eval_test_cases_test_set_id ON eval_test_cases (test_set_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_eval_runs_started_at ON eval_runs (started_at)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_eval_run_results_run_id ON eval_run_results (run_id)")


def _migrate_sqlite_analysis_template_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as connection:
        for table in ("conversations", "investigation_cases"):
            rows = connection.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            if not rows:
                continue
            existing = {row[1] for row in rows}
            additions = {"analysis_template_id": "INTEGER", "analysis_template_version": "INTEGER", "analysis_config_json": "TEXT"}
            for name, definition in additions.items():
                if name not in existing:
                    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _migrate_sqlite_skill_security_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    additions = {
        "skill_packages": {
            "signature": "VARCHAR(128)", "signature_status": "VARCHAR(24) NOT NULL DEFAULT 'unverified'",
            "release_status": "VARCHAR(24) NOT NULL DEFAULT 'draft'",
        },
        "skill_installations": {
            "enabled": "BOOLEAN NOT NULL DEFAULT 1", "approved_permissions_json": "TEXT NOT NULL DEFAULT '[]'",
        },
        "skill_runs": {
            "policy_json": "TEXT NOT NULL DEFAULT '{}'", "attempt_count": "INTEGER NOT NULL DEFAULT 1",
            "output_truncated": "BOOLEAN NOT NULL DEFAULT 0",
        },
    }
    with engine.begin() as connection:
        for table, columns in additions.items():
            existing = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}
            for name, definition in columns.items():
                if name not in existing:
                    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _migrate_sqlite_usage_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as connection:
        rows = connection.exec_driver_sql("PRAGMA table_info(chat_request_metrics)").fetchall()
        existing = {row[1] for row in rows}
        additions = {
            "input_tokens": "INTEGER NOT NULL DEFAULT 0",
            "output_tokens": "INTEGER NOT NULL DEFAULT 0",
            "cost_microusd": "INTEGER NOT NULL DEFAULT 0",
            "routed_from_model": "VARCHAR(96)",
            "requested_model": "VARCHAR(96)",
            "routing_reason": "VARCHAR(96)",
            "routing_direction": "VARCHAR(16) NOT NULL DEFAULT 'unchanged'",
            "result_quality": "FLOAT",
        }
        for name, definition in additions.items():
            if name not in existing:
                connection.exec_driver_sql(f"ALTER TABLE chat_request_metrics ADD COLUMN {name} {definition}")
        user_rows = connection.exec_driver_sql("PRAGMA table_info(users)").fetchall()
        if "model_whitelist_json" not in {row[1] for row in user_rows}:
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN model_whitelist_json TEXT")
    _backfill_investigation_cases()


def _migrate_sqlite_tenancy_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    columns = {
        "organization_id": "INTEGER",
        "workspace_id": "INTEGER",
        "assignee_user_id": "INTEGER",
    }
    with engine.begin() as connection:
        rows = connection.exec_driver_sql("PRAGMA table_info(investigation_cases)").fetchall()
        if not rows:
            return
        existing = {row[1] for row in rows}
        for name, definition in columns.items():
            if name not in existing:
                connection.exec_driver_sql(f"ALTER TABLE investigation_cases ADD COLUMN {name} {definition}")
            connection.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS ix_investigation_cases_{name} ON investigation_cases ({name})")
        table_columns = {
            "organizations": {
                "identity_source": "VARCHAR(24) NOT NULL DEFAULT 'local'",
                "external_id": "VARCHAR(255)",
            },
            "organization_members": {
                "identity_source": "VARCHAR(24) NOT NULL DEFAULT 'local'",
            },
            "workspaces": {
                "identity_source": "VARCHAR(24) NOT NULL DEFAULT 'local'",
                "external_id": "VARCHAR(255)",
            },
            "workspace_members": {
                "identity_source": "VARCHAR(24) NOT NULL DEFAULT 'local'",
            },
        }
        for table, additions in table_columns.items():
            present = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}
            for name, definition in additions.items():
                if name not in present:
                    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _migrate_sqlite_notification_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as connection:
        rows = connection.exec_driver_sql("PRAGMA table_info(notifications)").fetchall()
        if not rows:
            return
        existing = {row[1] for row in rows}
        additions = {
            "organization_id": "INTEGER",
            "resource_type": "VARCHAR(32)",
            "resource_id": "VARCHAR(128)",
            "resource_url": "VARCHAR(512)",
            "idempotency_key": "VARCHAR(160)",
        }
        for name, definition in additions.items():
            if name not in existing:
                connection.exec_driver_sql(f"ALTER TABLE notifications ADD COLUMN {name} {definition}")
        connection.exec_driver_sql(
            "UPDATE notifications SET idempotency_key = 'legacy:' || id WHERE idempotency_key IS NULL"
        )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_delivery "
            "ON notifications (organization_id, user_id, idempotency_key)"
        )


def _migrate_sqlite_evidence_review_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    columns = {
        "review_status": "VARCHAR(24) NOT NULL DEFAULT 'pending'",
        "source_trust": "INTEGER NOT NULL DEFAULT 50",
        "confidence": "INTEGER NOT NULL DEFAULT 50",
        "acquired_at": "DATETIME",
        "content_hash": "VARCHAR(64)",
        "snapshot_url": "TEXT",
        "review_note": "TEXT",
        "reviewed_by": "VARCHAR(80)",
        "reviewed_at": "DATETIME",
    }
    with engine.begin() as connection:
        rows = connection.exec_driver_sql("PRAGMA table_info(message_evidence)").fetchall()
        if not rows:
            return
        existing = {row[1] for row in rows}
        for name, definition in columns.items():
            if name not in existing:
                connection.exec_driver_sql(f"ALTER TABLE message_evidence ADD COLUMN {name} {definition}")


def _migrate_sqlite_explainable_conclusions_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    columns = {
        "claim_type": "VARCHAR(16) NOT NULL DEFAULT 'inference'",
        "confidence_rationale": "TEXT",
        "conflict_evidence_ids_json": "TEXT NOT NULL DEFAULT '[]'",
        "cross_checks_json": "TEXT NOT NULL DEFAULT '[]'",
        "reviewed_by": "VARCHAR(80)",
        "reviewed_at": "DATETIME",
    }
    with engine.begin() as connection:
        rows = connection.exec_driver_sql("PRAGMA table_info(case_conclusions)").fetchall()
        if not rows:
            return
        existing = {row[1] for row in rows}
        for name, definition in columns.items():
            if name not in existing:
                connection.exec_driver_sql(f"ALTER TABLE case_conclusions ADD COLUMN {name} {definition}")


def _backfill_investigation_cases() -> None:
    """Promote legacy conversation-bound case metadata without changing old APIs."""
    from app.models import CaseConversation, CapeCase, Conversation, InvestigationCase

    with SessionLocal() as db:
        linked_ids = set(db.query(CaseConversation.conversation_id).all())
        linked_ids = {row[0] for row in linked_ids}
        conversations = db.query(Conversation).filter(Conversation.owner_user_id.is_not(None)).all()
        cape_conversation_ids = {row[0] for row in db.query(CapeCase.conversation_id).all()}
        for conversation in conversations:
            meaningful = (
                conversation.case_status != "open"
                or conversation.severity != "unknown"
                or bool(conversation.assignee or conversation.case_summary or conversation.tags)
                or conversation.id in cape_conversation_ids
            )
            if not meaningful or conversation.id in linked_ids:
                continue
            case = InvestigationCase(
                owner_user_id=conversation.owner_user_id,
                title=conversation.title,
                status=conversation.case_status,
                severity=conversation.severity,
                assignee=conversation.assignee,
                tags_json=conversation.tags_json,
                summary=conversation.case_summary,
                priority=2 if conversation.severity in {"critical", "high"} else 3,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            )
            db.add(case)
            db.flush()
            db.add(CaseConversation(case_id=case.id, conversation_id=conversation.id))
        db.commit()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

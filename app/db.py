from collections.abc import Generator
from contextlib import contextmanager
import datetime as dt
from pathlib import Path
import uuid

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory: sessionmaker[Session] | None = None


def _sqlite_database_path(database_url: str) -> Path | None:
    prefixes = ("sqlite:///", "sqlite+pysqlite:///")
    for prefix in prefixes:
        if not database_url.startswith(prefix):
            continue
        raw_path = database_url.removeprefix(prefix)
        if not raw_path or raw_path in {":memory:", "/:memory:"}:
            return None
        if raw_path.startswith("file:"):
            return None
        return Path(raw_path).expanduser()
    return None


def _ensure_database_parent(database_url: str) -> None:
    database_path = _sqlite_database_path(database_url)
    if database_path is None:
        return
    database_path.parent.mkdir(parents=True, exist_ok=True)


def _configure_sqlite_connection(engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


def init_engine(database_url: str | None = None) -> None:
    global _engine, _session_factory

    if database_url is None:
        database_url = get_settings().database_url

    _ensure_database_parent(database_url)
    connect_args = {"check_same_thread": False, "timeout": 30} if database_url.startswith("sqlite") else {}
    _engine = create_engine(
        database_url,
        future=True,
        connect_args=connect_args,
        pool_pre_ping=True,
    )
    if database_url.startswith("sqlite"):
        _configure_sqlite_connection(_engine)
    _session_factory = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)


def get_engine():
    if _engine is None:
        init_engine()
    return _engine


def get_session() -> Generator[Session, None, None]:
    global _session_factory

    if _session_factory is None:
        init_engine()

    assert _session_factory is not None
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


async def get_session_async() -> Generator[Session, None, None]:
    global _session_factory

    if _session_factory is None:
        init_engine()

    assert _session_factory is not None
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    global _session_factory

    if _session_factory is None:
        init_engine()

    assert _session_factory is not None
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    from app import models  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _run_startup_migrations(engine)


def _column_names(connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _run_startup_migrations(engine) -> None:
    with engine.begin() as connection:
        table_names = set(inspect(connection).get_table_names())
        if "profiles" not in table_names:
            return

        profile_columns = _column_names(connection, "profiles")
        if "user_id" not in profile_columns:
            connection.execute(text("ALTER TABLE profiles ADD COLUMN user_id VARCHAR(36)"))
        if "profile_data" not in profile_columns:
            connection.execute(text("ALTER TABLE profiles ADD COLUMN profile_data JSON"))
            connection.execute(text("UPDATE profiles SET profile_data = '{}' WHERE profile_data IS NULL"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_profiles_user_id ON profiles (user_id)"))

        default_profile_id = connection.execute(
            text("SELECT id FROM profiles ORDER BY created_at ASC, name ASC LIMIT 1")
        ).scalar_one_or_none()
        documents_exist = False
        if "documents" in table_names:
            documents_exist = bool(connection.execute(text("SELECT 1 FROM documents LIMIT 1")).scalar_one_or_none())
        if default_profile_id is None and documents_exist:
            default_profile_id = str(uuid.uuid4())
            now = dt.datetime.now(dt.UTC)
            connection.execute(
                text(
                    "INSERT INTO profiles (id, user_id, name, created_at, updated_at) "
                    "VALUES (:id, :user_id, :name, :created_at, :updated_at)"
                ),
                {
                    "id": default_profile_id,
                    "user_id": None,
                    "name": "Primary Profile",
                    "created_at": now,
                    "updated_at": now,
                },
            )

        if "documents" in table_names:
            document_columns = _column_names(connection, "documents")
            if "profile_id" not in document_columns:
                connection.execute(text("ALTER TABLE documents ADD COLUMN profile_id VARCHAR(36)"))
            if default_profile_id is not None:
                connection.execute(
                    text(
                        "UPDATE documents SET profile_id = :profile_id "
                        "WHERE profile_id IS NULL OR profile_id = ''"
                    ),
                    {"profile_id": default_profile_id},
                )
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_profile_id ON documents (profile_id)"))

        if "structured_profile_claims" in table_names:
            structured_columns = _column_names(connection, "structured_profile_claims")
            if "raw_value_json" not in structured_columns:
                connection.execute(text("ALTER TABLE structured_profile_claims ADD COLUMN raw_value_json JSON"))
                connection.execute(
                    text(
                        "UPDATE structured_profile_claims SET raw_value_json = value_json "
                        "WHERE raw_value_json IS NULL"
                    )
                )
            if "resolver_confidence" not in structured_columns:
                connection.execute(text("ALTER TABLE structured_profile_claims ADD COLUMN resolver_confidence FLOAT"))
                connection.execute(
                    text(
                        "UPDATE structured_profile_claims SET resolver_confidence = confidence "
                        "WHERE resolver_confidence IS NULL"
                    )
                )
            if "resolver_action" not in structured_columns:
                connection.execute(text("ALTER TABLE structured_profile_claims ADD COLUMN resolver_action VARCHAR(32)"))
                connection.execute(
                    text(
                        "UPDATE structured_profile_claims SET resolver_action = 'keep' "
                        "WHERE resolver_action IS NULL"
                    )
                )
            if "resolver_evidence" not in structured_columns:
                connection.execute(text("ALTER TABLE structured_profile_claims ADD COLUMN resolver_evidence JSON"))
                connection.execute(
                    text(
                        "UPDATE structured_profile_claims SET resolver_evidence = '[]' "
                        "WHERE resolver_evidence IS NULL"
                    )
                )
            if "admission_status" not in structured_columns:
                connection.execute(text("ALTER TABLE structured_profile_claims ADD COLUMN admission_status VARCHAR(24)"))
                connection.execute(
                    text(
                        "UPDATE structured_profile_claims SET admission_status = CASE "
                        "WHEN status IN ('accepted', 'edited') THEN 'admit' "
                        "WHEN status IN ('rejected', 'duplicate') THEN 'reject_noise' "
                        "ELSE 'needs_review' END "
                        "WHERE admission_status IS NULL"
                    )
                )
            if "admission_reason" not in structured_columns:
                connection.execute(text("ALTER TABLE structured_profile_claims ADD COLUMN admission_reason VARCHAR(120)"))
            if "admission_score" not in structured_columns:
                connection.execute(text("ALTER TABLE structured_profile_claims ADD COLUMN admission_score FLOAT"))
                connection.execute(
                    text(
                        "UPDATE structured_profile_claims SET admission_score = "
                        "COALESCE(resolver_confidence, confidence, 0.0) "
                        "WHERE admission_score IS NULL"
                    )
                )
            if "suggested_section" not in structured_columns:
                connection.execute(text("ALTER TABLE structured_profile_claims ADD COLUMN suggested_section VARCHAR(50)"))
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_structured_profile_claims_resolver_action "
                    "ON structured_profile_claims (resolver_action)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_structured_profile_claims_admission_status "
                    "ON structured_profile_claims (admission_status)"
                )
            )

        if "correction_embeddings" in table_names:
            correction_embedding_columns = _column_names(connection, "correction_embeddings")
            if "provider" not in correction_embedding_columns:
                connection.execute(text("ALTER TABLE correction_embeddings ADD COLUMN provider VARCHAR(40)"))
                connection.execute(
                    text(
                        "UPDATE correction_embeddings SET provider = 'openai' "
                        "WHERE provider IS NULL OR provider = ''"
                    )
                )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_correction_embeddings_profile_provider "
                    "ON correction_embeddings (profile_id, provider)"
                )
            )

        if "profile_graph_nodes" in table_names:
            graph_node_columns = _column_names(connection, "profile_graph_nodes")
            if "profile_id" not in graph_node_columns:
                connection.execute(text("ALTER TABLE profile_graph_nodes ADD COLUMN profile_id VARCHAR(36)"))
            if default_profile_id is not None:
                connection.execute(
                    text(
                        "UPDATE profile_graph_nodes SET profile_id = :profile_id "
                        "WHERE profile_id IS NULL OR profile_id = ''"
                    ),
                    {"profile_id": default_profile_id},
                )
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_profile_graph_nodes_profile_id ON profile_graph_nodes (profile_id)")
            )

        if "profile_graph_edges" in table_names:
            graph_edge_columns = _column_names(connection, "profile_graph_edges")
            if "profile_id" not in graph_edge_columns:
                connection.execute(text("ALTER TABLE profile_graph_edges ADD COLUMN profile_id VARCHAR(36)"))
            if default_profile_id is not None:
                connection.execute(
                    text(
                        "UPDATE profile_graph_edges SET profile_id = :profile_id "
                        "WHERE profile_id IS NULL OR profile_id = ''"
                    ),
                    {"profile_id": default_profile_id},
                )
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_profile_graph_edges_profile_id ON profile_graph_edges (profile_id)")
            )

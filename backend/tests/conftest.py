"""Shared fixtures.

Tests run against a real PostgreSQL database (a separate `<name>_test` database derived
from DATABASE_URL, or TEST_DATABASE_URL). The schema is built by running the Alembic
migrations, so the migrations themselves are exercised on every test session.
"""

import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from app.config import Settings


def _test_database_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    url = make_url(Settings().database_url)
    name = url.database or "salesagent"
    return url.set(database=name if name.endswith("_test") else f"{name}_test").render_as_string(
        hide_password=False
    )


TEST_DATABASE_URL = _test_database_url()
_AUDIO_DIR = tempfile.mkdtemp(prefix="sales-agent-audio-")

# Must be set before any `app` module reads settings.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["PROVIDER_MODE"] = "mock"
os.environ["AUDIO_DIR"] = _AUDIO_DIR
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("GROQ_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.main import app  # noqa: E402
from app.providers.factory import ProviderBundle, get_providers, mock_bundle  # noqa: E402


def _ensure_database_exists() -> None:
    url = make_url(TEST_DATABASE_URL)
    try:
        with create_engine(url).connect():
            return
    except OperationalError:
        pass
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    from alembic import command
    from alembic.config import Config

    _ensure_database_exists()
    os.environ["ALEMBIC_DATABASE_URL"] = TEST_DATABASE_URL
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    get_engine().dispose()


@pytest.fixture(autouse=True)
def clean_tables(migrated_database):
    with get_engine().begin() as conn:
        conn.execute(
            text("TRUNCATE benchmark_runs, conversations, scenarios RESTART IDENTITY CASCADE")
        )
    yield


@pytest.fixture
def db():
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def providers() -> ProviderBundle:
    return mock_bundle()


@pytest.fixture
def client(providers):
    app.dependency_overrides[get_providers] = lambda: providers
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def wav_bytes() -> bytes:
    """Minimal bytes that pass container sniffing; the mock STT does not decode audio."""
    return b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"\x00" * 400

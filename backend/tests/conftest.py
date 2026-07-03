import os
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

TEST_DATABASE_URL = "sqlite:///./backend/data/test.db"
TEST_DATABASE_PATH = Path("backend/data/test.db")

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine
from app.main import app
from app.rate_limit import reset_failed_attempts


@pytest.fixture()
def client():
    engine.dispose()
    TEST_DATABASE_PATH.unlink(missing_ok=True)
    reset_failed_attempts()

    with TestClient(app) as test_client:
        yield test_client

    reset_failed_attempts()
    engine.dispose()
    TEST_DATABASE_PATH.unlink(missing_ok=True)

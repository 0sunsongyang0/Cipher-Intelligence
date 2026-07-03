import os
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

TEST_DATABASE_URL = "sqlite:///./backend/data/test.db"
TEST_DATABASE_PATH = Path("backend/data/test.db")

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine
from app.main import app


@pytest.fixture()
def client():
    engine.dispose()
    TEST_DATABASE_PATH.unlink(missing_ok=True)

    with TestClient(app) as test_client:
        yield test_client

    engine.dispose()
    TEST_DATABASE_PATH.unlink(missing_ok=True)

import os

# Must be set before the app (and its engine) is imported.
os.environ["AGENTHUB_DATABASE_URL"] = "sqlite://"
os.environ["AGENTHUB_DEMO_MODE"] = "true"

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import engine
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:  # runs lifespan: reset + seed
        yield c


@pytest.fixture
def session(client):
    with Session(engine) as s:
        yield s

import pytest
from fastapi.testclient import TestClient
from plotward_api.main import create_app


@pytest.fixture
def client(settings, session_factory):
    app = create_app(settings, session_factory)
    with TestClient(app) as c:
        c.headers["X-API-Key"] = settings.api_key
        yield c

import pytest
from fastapi.testclient import TestClient
from plotward_api.main import create_app
from plotward_core.testing import SF_LAT, SF_LON, make_exif, make_image_bytes


def _upload(client, data: bytes, name: str = "IMG_0001.jpg", headers=None):
    return client.post("/photos", files={"file": (name, data, "image/jpeg")}, headers=headers)


def test_healthz_needs_no_key(client):
    assert client.get("/healthz", headers={"X-API-Key": ""}).json() == {"status": "ok"}


@pytest.mark.parametrize("key", [None, "", "wrong"])
def test_upload_requires_the_api_key(client, key):
    headers = {"X-API-Key": key} if key is not None else {}
    client.headers.pop("X-API-Key")
    resp = _upload(client, make_image_bytes(), headers=headers)
    assert resp.status_code == 401


def test_upload_jpeg_returns_metadata(client):
    resp = _upload(client, make_image_bytes(exif=make_exif()))
    assert resp.status_code == 201
    body = resp.json()
    assert body["duplicate"] is False
    assert body["captured_at"].startswith("2026-11-21T")
    assert body["latitude"] == pytest.approx(SF_LAT, abs=1e-6)
    assert body["longitude"] == pytest.approx(SF_LON, abs=1e-6)
    assert (body["width"], body["height"]) == (320, 240)

    fetched = client.get(f"/photos/{body['id']}")
    assert fetched.status_code == 200 and fetched.json()["content_hash"] == body["content_hash"]


def test_upload_heic(client):
    resp = _upload(client, make_image_bytes("HEIF", exif=make_exif()), name="IMG_0002.heic")
    assert resp.status_code == 201
    assert resp.json()["latitude"] == pytest.approx(SF_LAT, abs=1e-6)


def test_photo_without_gps_has_null_location(client):
    body = _upload(client, make_image_bytes()).json()
    assert body["latitude"] is None and body["longitude"] is None and body["captured_at"] is None


def test_duplicate_upload_returns_200_and_the_same_photo(client):
    data = make_image_bytes()
    first = _upload(client, data)
    second = _upload(client, data)
    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["id"] == first.json()["id"] and second.json()["duplicate"] is True


@pytest.mark.parametrize("data", [b"hello", make_image_bytes("PNG")], ids=["not-an-image", "png"])
def test_unsupported_files_get_415(client, data):
    assert _upload(client, data).status_code == 415


def test_empty_file_gets_400(client):
    assert _upload(client, b"").status_code == 400


def test_oversized_file_gets_413(client):
    assert _upload(client, b"x" * (1024 * 1024 + 1)).status_code == 413


def test_unknown_photo_gets_404(client):
    assert client.get("/photos/00000000-0000-0000-0000-000000000000").status_code == 404


def test_app_refuses_to_start_without_an_api_key(settings, session_factory):
    app = create_app(settings.model_copy(update={"api_key": ""}), session_factory)
    with pytest.raises(RuntimeError, match="PLOTWARD_API_KEY"), TestClient(app):
        pass

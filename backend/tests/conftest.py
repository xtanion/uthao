import io
import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image


@pytest.fixture(scope="session", autouse=True)
def environment(tmp_path_factory) -> None:
    root = tmp_path_factory.mktemp("fihy")
    os.environ.update(
        {
            "ENVIRONMENT": "test",
            "SECRET_KEY": "test-secret-key-long-enough-for-hmac-sha256",
            "DATABASE_URL": f"sqlite+aiosqlite:///{root / 'test.db'}",
            "MEDIA_ROOT": str(root / "media"),
            "PUBLIC_BASE_URL": "http://test",
            "R2_ACCOUNT_ID": "",
            "R2_ACCESS_KEY_ID": "",
            "R2_SECRET_ACCESS_KEY": "",
            "OTP_DEBUG_CODE": "",
            "CONFIRMATIONS_TO_VERIFY": "2",
            # Out of the way by default; the tests that care set them low.
            "REPORTS_PER_USER_PER_HOUR": "1000",
            "SUPPORTS_PER_USER_PER_HOUR": "1000",
        }
    )


@pytest.fixture
async def client(environment) -> AsyncIterator[AsyncClient]:
    from app import db, storage
    from app.config import get_settings
    from app.main import app
    from app.models import Base

    get_settings.cache_clear()
    storage.set_store(None)
    async with db.engine().begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as instance:
        yield instance
    await db.dispose()


class CapturingSender:
    def __init__(self) -> None:
        self.codes: dict[str, str] = {}

    async def send(self, phone: str, code: str) -> None:
        self.codes[phone] = code


@pytest.fixture
def sender() -> CapturingSender:
    from app import otp

    capture = CapturingSender()
    otp.set_sender(capture)
    return capture


def jpeg_bytes(
    width: int = 1200, height: int = 900, with_exif: bool = True
) -> bytes:
    image = Image.new("RGB", (width, height))
    for y in range(height):
        for x in range(0, width, 40):
            image.putpixel((x, y), ((x * 7) % 256, (y * 3) % 256, 90))
    buffer = io.BytesIO()
    if with_exif:
        exif = Image.Exif()
        exif[0x010F] = "AcmePhone"
        exif[0x0110] = "Model X"
        exif[0x0132] = "2026:08:20 09:12:00"
        gps = exif.get_ifd(0x8825)
        gps[1] = "N"
        gps[2] = (19.0, 3.0, 0.0)
        gps[3] = "E"
        gps[4] = (72.0, 50.0, 0.0)
        image.save(buffer, format="JPEG", exif=exif)
    else:
        image.save(buffer, format="JPEG")
    return buffer.getvalue()


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (60, 60), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


async def sign_in(client: AsyncClient, sender: CapturingSender, phone: str) -> str:
    response = await client.post("/auth/otp/request", json={"phone": phone})
    assert response.status_code == 204
    verify = await client.post(
        "/auth/otp/verify", json={"phone": phone, "code": sender.codes[phone]}
    )
    assert verify.status_code == 200, verify.text
    return verify.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# Where create_issue files a report unless told otherwise. A support carrying
# photos has to come from near the report, so those send HERE along with them.
LATITUDE, LONGITUDE = 19.0612, 72.8371
HERE = {"latitude": str(LATITUDE), "longitude": str(LONGITUDE)}


async def create_issue(
    client: AsyncClient,
    token: str,
    *,
    report_id: str,
    title: str = "Cover missing on the footpath side",
    description: str = "Unlit after dark.",
    category: str = "manhole",
    severity: str = "high",
    latitude: float = LATITUDE,
    longitude: float = LONGITUDE,
    photo: bytes | None = None,
    photo_name: str = "photo_0.jpg",
):
    return await client.post(
        "/issues",
        headers=auth(token),
        data={
            "client_report_id": report_id,
            "title": title,
            "description": description,
            "category": category,
            "severity": severity,
            "latitude": str(latitude),
            "longitude": str(longitude),
        },
        files=[("photos", (photo_name, photo or jpeg_bytes(400, 300), "image/jpeg"))],
    )

import base64
import binascii
import io
import re
import secrets
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import settings


MAX_AVATAR_BYTES = 5 * 1024 * 1024
MIN_AVATAR_EDGE = 32
MAX_AVATAR_EDGE = 4096
OUTPUT_AVATAR_EDGE = 512
ALLOWED_AVATAR_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
AVATAR_FORMAT_MIME_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
AVATAR_DATA_URL_PATTERN = re.compile(
    r"^data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=\r\n]+)$",
    re.IGNORECASE,
)
AVATAR_FILENAME_PATTERN = re.compile(r"^user-\d+-[a-f0-9]{16}\.webp$")


class AvatarValidationError(ValueError):
    pass


def get_avatar_storage_path() -> Path:
    path = Path(settings.avatar_storage_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def prepare_avatar(data_url: str) -> bytes:
    match = AVATAR_DATA_URL_PATTERN.fullmatch(data_url.strip())
    if match is None or match.group(1).lower() not in ALLOWED_AVATAR_MIME_TYPES:
        raise AvatarValidationError("Avatar must be a JPEG, PNG, or WebP image")

    encoded = match.group(2)
    if len(encoded) > ((MAX_AVATAR_BYTES + 2) // 3) * 4 + 8:
        raise AvatarValidationError("Avatar must be 5 MB or smaller")

    try:
        payload = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise AvatarValidationError("Avatar image data is invalid") from error

    if not payload or len(payload) > MAX_AVATAR_BYTES:
        raise AvatarValidationError("Avatar must be 5 MB or smaller")

    try:
        with Image.open(io.BytesIO(payload)) as source:
            width, height = source.size
            if min(width, height) < MIN_AVATAR_EDGE:
                raise AvatarValidationError("Avatar must be at least 32 x 32 pixels")
            if max(width, height) > MAX_AVATAR_EDGE:
                raise AvatarValidationError("Avatar dimensions cannot exceed 4096 pixels")
            if AVATAR_FORMAT_MIME_TYPES.get(source.format or "") != match.group(1).lower():
                raise AvatarValidationError("Avatar file type does not match its image data")
            source.verify()
        with Image.open(io.BytesIO(payload)) as source:
            source.seek(0)
            normalized = ImageOps.exif_transpose(source)
            if normalized.mode not in {"RGB", "RGBA"}:
                normalized = normalized.convert("RGBA" if "transparency" in normalized.info else "RGB")
            normalized.thumbnail(
                (OUTPUT_AVATAR_EDGE, OUTPUT_AVATAR_EDGE),
                Image.Resampling.LANCZOS,
            )

            output = io.BytesIO()
            normalized.save(output, format="WEBP", quality=88, method=6)
            return output.getvalue()
    except AvatarValidationError:
        raise
    except (Image.DecompressionBombError, OSError, UnidentifiedImageError) as error:
        raise AvatarValidationError("Avatar image could not be read safely") from error


def save_avatar(user_id: int, image_bytes: bytes) -> str:
    storage_path = get_avatar_storage_path()
    filename = f"user-{user_id}-{secrets.token_hex(8)}.webp"
    temporary_path = storage_path / f".{filename}.tmp"
    final_path = storage_path / filename
    temporary_path.write_bytes(image_bytes)
    temporary_path.replace(final_path)
    return filename


def delete_avatar(filename: str | None) -> None:
    if not filename or AVATAR_FILENAME_PATTERN.fullmatch(filename) is None:
        return
    (get_avatar_storage_path() / filename).unlink(missing_ok=True)


def resolve_avatar(filename: str) -> Path | None:
    if AVATAR_FILENAME_PATTERN.fullmatch(filename) is None:
        return None
    path = get_avatar_storage_path() / filename
    return path if path.is_file() else None

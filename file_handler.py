import base64
import mimetypes
from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_FILE_SIZE_MB = 20


def load_file(file_path: str) -> tuple[str, str]:
    """
    Load a file and return (base64_data, media_type).
    Raises ValueError for unsupported types or oversized files.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. "
            f"Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
        )

    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise ValueError(
            f"File too large ({size_mb:.1f} MB). Max allowed: {MAX_FILE_SIZE_MB} MB."
        )

    media_type = _get_media_type(ext)

    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")

    return data, media_type


def _get_media_type(ext: str) -> str:
    mapping = {
        ".pdf":  "application/pdf",
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif":  "image/gif",
    }
    return mapping[ext]


def build_content_block(base64_data: str, media_type: str) -> dict:
    """
    Build the Anthropic API content block for a file.
    PDFs use the 'document' type; images use the 'image' type.
    """
    if media_type == "application/pdf":
        return {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64_data,
            },
        }
    else:
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64_data,
            },
        }

"""Document text extraction supporting PDF, DOCX, TXT, and Markdown."""
import io
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Heading styles used by python-docx
_HEADING_STYLES = {"Heading 1", "Heading 2", "Heading 3", "Heading 4", "Heading 5", "Heading 6"}


def extract_text(file_path: str, file_type: str) -> str:
    """
    Extract text from a document file.

    Args:
        file_path: Absolute/relative local path, or S3 key (workspaces/...).
        file_type: One of "pdf", "docx", "txt", "md".

    Returns:
        Extracted text as a single string. Never empty for valid documents.

    Raises:
        ValueError: If file_type is unsupported.
        FileNotFoundError: If file_path does not exist locally and S3 download fails.
    """
    ft = file_type.lower().lstrip(".")
    path = Path(file_path)

    # If the path doesn't exist locally, try fetching from S3/LocalStack
    if not path.exists():
        file_bytes = _fetch_from_s3(file_path)
        return _extract_from_bytes(file_bytes, ft, file_path)

    if ft == "pdf":
        return _extract_pdf(path)
    elif ft == "docx":
        return _extract_docx(path)
    elif ft in ("txt", "md"):
        return _extract_plain(path)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")


def _fetch_from_s3(s3_key: str) -> bytes:
    """Download file bytes from S3/LocalStack using app settings."""
    from app.core.config import settings
    import boto3

    session_kwargs = {}
    if settings.aws_endpoint_url:
        session_kwargs["aws_access_key_id"] = "test"
        session_kwargs["aws_secret_access_key"] = "test"
    elif settings.aws_profile:
        session_kwargs["profile_name"] = settings.aws_profile

    session = boto3.Session(**session_kwargs)
    client_kwargs = {"region_name": settings.aws_region}
    if settings.aws_endpoint_url:
        client_kwargs["endpoint_url"] = settings.aws_endpoint_url

    s3 = session.client("s3", **client_kwargs)
    bucket = settings.s3_bucket

    try:
        response = s3.get_object(Bucket=bucket, Key=s3_key)
        return response["Body"].read()
    except Exception as exc:
        raise FileNotFoundError(f"File not found locally or in S3 (key={s3_key}): {exc}") from exc


def _extract_from_bytes(file_bytes: bytes, ft: str, name: str) -> str:
    """Extract text from raw bytes by writing to a temp file."""
    suffix = f".{ft}"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(file_bytes)
        tmp.flush()
        path = Path(tmp.name)
        if ft == "pdf":
            return _extract_pdf(path)
        elif ft == "docx":
            return _extract_docx(path)
        elif ft in ("txt", "md"):
            return _extract_plain(path)
        else:
            raise ValueError(f"Unsupported file type: {ft}")


def _extract_pdf(path: Path) -> str:
    """Extract text from PDF using pdfplumber, preserving headers, tables, and section breaks."""
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            # Extract tables first so we can reconstruct them as text
            tables = page.extract_tables()
            table_texts: list[str] = []
            for table in tables:
                rows = []
                for row in table:
                    cells = [cell or "" for cell in row]
                    rows.append(" | ".join(cells))
                table_texts.append("\n".join(rows))

            # Extract page text (includes headers/footers/body)
            page_text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""

            if page_text:
                parts.append(page_text)
            for t in table_texts:
                if t.strip():
                    parts.append(t)

            # Section break between pages
            parts.append("\n--- Page Break ---\n")

    return "\n".join(parts).strip()


def _extract_docx(path: Path) -> str:
    """Extract text from DOCX using python-docx, preserving heading hierarchy."""
    from docx import Document

    doc = Document(str(path))
    lines: list[str] = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        style_name = para.style.name if para.style else ""

        # Prefix headings with markdown-style markers to preserve hierarchy
        if style_name in _HEADING_STYLES:
            level = int(style_name.split()[-1])  # "Heading 2" → 2
            prefix = "#" * level
            lines.append(f"{prefix} {text}")
        else:
            lines.append(text)

    return "\n".join(lines).strip()


def _extract_plain(path: Path) -> str:
    """Read plain text or Markdown file."""
    return path.read_text(encoding="utf-8", errors="replace").strip()

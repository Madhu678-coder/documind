"""Resolve a run's dataset into a list of local file paths this container can read.

Five source types, matching the methodology doc (docs/rag-benchmark-methodology.md
in the main DocuMind repo):
  - folder_path: a directory already mounted into this container (docker-compose
    volume). Every file with an allowed extension is used.
  - s3: an s3://bucket/prefix location, downloaded via the ambient AWS credential
    chain (profile / instance role / env vars already configured on the host).
  - confluence: a Confluence Cloud space (optionally scoped to one page and its
    descendants), pulled via the REST API with an API token.
  - gdrive: a Google Drive folder, pulled via a service account (headless — no
    interactive OAuth consent), walked recursively.
  - sharepoint: a SharePoint/OneDrive document library folder, pulled via
    Microsoft Graph app-only auth (client credentials).

None of these ever take a credential typed into the app UI — every credential
comes from this service's own environment (see .env.example), in line with
Minfy's data-handling rules.
"""
from __future__ import annotations

import html as html_lib
import logging
import re
import tempfile
from pathlib import Path
from urllib.parse import quote, urlparse

from app.config import get_settings

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "md"}

_TAG_RE = re.compile(r"<[^>]+>")


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return cleaned[:80] or "untitled"


def _strip_html(raw_html: str) -> str:
    text = _TAG_RE.sub(" ", raw_html)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


# -- folder_path --------------------------------------------------------------

def resolve_folder(path_str: str) -> list[Path]:
    root = Path(path_str)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(
            f"Dataset folder '{path_str}' was not found inside the benchmark-suite "
            "container — mount it as a volume in docker-compose.yml (see README)."
        )
    files = sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lstrip(".").lower() in ALLOWED_EXTENSIONS
    )
    if not files:
        raise FileNotFoundError(
            f"No supported files (pdf, docx, txt, md) found under '{path_str}'."
        )
    return files


# -- s3 -------------------------------------------------------------------------

def resolve_s3(s3_uri: str) -> list[Path]:
    import boto3

    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Expected an s3://bucket/prefix URI, got '{s3_uri}'")

    bucket = parsed.netloc
    prefix = parsed.path.lstrip("/")

    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    tmp_dir = Path(tempfile.mkdtemp(prefix="benchmark-dataset-"))
    local_paths: list[Path] = []

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            ext = key.rsplit(".", 1)[-1].lower() if "." in key else ""
            if ext not in ALLOWED_EXTENSIONS:
                continue
            local_path = tmp_dir / Path(key).name
            s3.download_file(bucket, key, str(local_path))
            local_paths.append(local_path)

    if not local_paths:
        raise FileNotFoundError(f"No supported files found under '{s3_uri}'.")
    return local_paths


# -- confluence -------------------------------------------------------------------

def resolve_confluence(source_ref: str) -> list[Path]:
    """source_ref is a Confluence space key, optionally with a root page id after
    a colon to scope to one page + its descendants, e.g. 'ENG' or 'ENG:123456'."""
    import httpx

    settings = get_settings()
    if not (settings.confluence_base_url and settings.confluence_email and settings.confluence_api_token):
        raise RuntimeError(
            "Confluence source requires BENCHMARK_CONFLUENCE_BASE_URL / "
            "BENCHMARK_CONFLUENCE_EMAIL / BENCHMARK_CONFLUENCE_API_TOKEN "
            "(an Atlassian API token, not a password) — see .env.example."
        )

    if ":" in source_ref:
        space_key, root_page_id = source_ref.split(":", 1)
    else:
        space_key, root_page_id = source_ref, None

    base = settings.confluence_base_url.rstrip("/")
    tmp_dir = Path(tempfile.mkdtemp(prefix="benchmark-confluence-"))
    local_paths: list[Path] = []

    with httpx.Client(
        auth=(settings.confluence_email, settings.confluence_api_token), timeout=60.0
    ) as client:
        page_ids = (
            _confluence_collect_descendant_ids(client, base, root_page_id)
            if root_page_id
            else _confluence_list_space_page_ids(client, base, space_key)
        )

        for page_id in page_ids:
            resp = client.get(
                f"{base}/wiki/rest/api/content/{page_id}", params={"expand": "body.storage"}
            )
            resp.raise_for_status()
            data = resp.json()
            title = data.get("title", page_id)
            raw_html = data.get("body", {}).get("storage", {}).get("value", "")
            text = _strip_html(raw_html)
            if not text:
                continue
            path = tmp_dir / f"{_sanitize_filename(title)}-{page_id}.txt"
            path.write_text(text, encoding="utf-8")
            local_paths.append(path)

    if not local_paths:
        raise FileNotFoundError(f"No Confluence pages with content found for '{source_ref}'.")
    return local_paths


def _confluence_list_space_page_ids(client, base: str, space_key: str) -> list[str]:
    ids: list[str] = []
    url = f"{base}/wiki/rest/api/content"
    params: dict | None = {"spaceKey": space_key, "type": "page", "limit": 100}
    while url:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        ids.extend(r["id"] for r in data.get("results", []))
        next_link = data.get("_links", {}).get("next")
        url = f"{base}{next_link}" if next_link else None
        params = None  # next_link already carries query params
    return ids


def _confluence_collect_descendant_ids(client, base: str, root_id: str) -> list[str]:
    ids = [root_id]
    queue = [root_id]
    while queue:
        current = queue.pop(0)
        resp = client.get(
            f"{base}/wiki/rest/api/content/{current}/child/page", params={"limit": 100}
        )
        resp.raise_for_status()
        for child in resp.json().get("results", []):
            ids.append(child["id"])
            queue.append(child["id"])
    return ids


# -- gdrive -----------------------------------------------------------------------

def resolve_gdrive(folder_id: str) -> list[Path]:
    """source_ref is a Google Drive folder ID (the id segment of the folder's URL)."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload

    settings = get_settings()
    if not settings.gdrive_service_account_json:
        raise RuntimeError(
            "Google Drive source requires BENCHMARK_GDRIVE_SERVICE_ACCOUNT_JSON to point at a "
            "mounted service-account key file (see .env.example). Share the target folder with "
            "that service account's email address first — it has no access otherwise."
        )

    creds = service_account.Credentials.from_service_account_file(
        settings.gdrive_service_account_json,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    service = build("drive", "v3", credentials=creds)

    tmp_dir = Path(tempfile.mkdtemp(prefix="benchmark-gdrive-"))
    local_paths: list[Path] = []

    for file in _gdrive_list_files_recursive(service, folder_id):
        name = file["name"]
        mime = file["mimeType"]
        if mime == "application/vnd.google-apps.document":
            data = service.files().export(fileId=file["id"], mimeType="text/plain").execute()
            path = tmp_dir / f"{_sanitize_filename(name)}.txt"
            path.write_bytes(data)
            local_paths.append(path)
        elif mime.startswith("application/vnd.google-apps"):
            logger.info("Skipping unsupported Google-native file: %s (%s)", name, mime)
        else:
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in ALLOWED_EXTENSIONS:
                continue
            path = tmp_dir / name
            request = service.files().get_media(fileId=file["id"])
            with open(path, "wb") as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
            local_paths.append(path)

    if not local_paths:
        raise FileNotFoundError(
            f"No supported files found in Google Drive folder '{folder_id}' — check the folder "
            "is shared with the service account's email and contains pdf/docx/txt/md/Google Docs."
        )
    return local_paths


def _gdrive_list_files_recursive(service, folder_id: str) -> list[dict]:
    results: list[dict] = []
    page_token: str | None = None
    while True:
        resp = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType)",
                pageToken=page_token,
            )
            .execute()
        )
        for f in resp.get("files", []):
            if f["mimeType"] == "application/vnd.google-apps.folder":
                results.extend(_gdrive_list_files_recursive(service, f["id"]))
            else:
                results.append(f)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return results


# -- sharepoint / onedrive --------------------------------------------------------

def resolve_sharepoint(source_ref: str) -> list[Path]:
    """source_ref is 'hostname|/sites/site-name|folder/path', e.g.
    'contoso.sharepoint.com|/sites/Compliance|Shared Documents/Policies'."""
    import httpx

    settings = get_settings()
    if not (settings.azure_tenant_id and settings.azure_client_id and settings.azure_client_secret):
        raise RuntimeError(
            "SharePoint source requires BENCHMARK_AZURE_TENANT_ID / _CLIENT_ID / _CLIENT_SECRET "
            "for an Azure AD app registration with admin-consented Graph 'Sites.Read.All' "
            "application permission — see .env.example."
        )

    try:
        hostname, site_path, folder_path = source_ref.split("|", 2)
    except ValueError:
        raise ValueError(
            "Expected 'hostname|/sites/site-name|folder/path', e.g. "
            "'contoso.sharepoint.com|/sites/Compliance|Shared Documents/Policies', "
            f"got '{source_ref}'"
        )

    token = _graph_access_token(settings)
    base = "https://graph.microsoft.com/v1.0"
    site_segment = f"{hostname}:{site_path.rstrip('/')}"

    tmp_dir = Path(tempfile.mkdtemp(prefix="benchmark-sharepoint-"))
    local_paths: list[Path] = []

    with httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=60.0) as client:
        for item in _graph_list_children_recursive(client, base, site_segment, folder_path.strip("/")):
            name = item["name"]
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in ALLOWED_EXTENSIONS:
                continue
            download_url = item.get("@microsoft.graph.downloadUrl")
            if not download_url:
                continue
            resp = client.get(download_url)
            resp.raise_for_status()
            path = tmp_dir / name
            path.write_bytes(resp.content)
            local_paths.append(path)

    if not local_paths:
        raise FileNotFoundError(f"No supported files found under '{source_ref}'.")
    return local_paths


def _graph_access_token(settings) -> str:
    import msal

    app = msal.ConfidentialClientApplication(
        settings.azure_client_id,
        authority=f"https://login.microsoftonline.com/{settings.azure_tenant_id}",
        client_credential=settings.azure_client_secret,
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(
            f"Failed to acquire a Microsoft Graph token: {result.get('error_description', result)}"
        )
    return result["access_token"]


def _graph_list_children_recursive(client, base: str, site_segment: str, folder_path: str) -> list[dict]:
    items: list[dict] = []
    encoded_path = quote(folder_path, safe="/")
    url = f"{base}/sites/{site_segment}:/drive/root:/{encoded_path}:/children"
    while url:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("value", []):
            if "folder" in item:
                items.extend(
                    _graph_list_children_recursive(
                        client, base, site_segment, f"{folder_path}/{item['name']}"
                    )
                )
            else:
                items.append(item)
        url = data.get("@odata.nextLink")
    return items


# -- dispatcher -------------------------------------------------------------------

def resolve_dataset(source_type: str, source_ref: str) -> list[Path]:
    resolvers = {
        "folder_path": resolve_folder,
        "s3": resolve_s3,
        "confluence": resolve_confluence,
        "gdrive": resolve_gdrive,
        "sharepoint": resolve_sharepoint,
    }
    resolver = resolvers.get(source_type)
    if resolver is None:
        raise ValueError(f"Unknown dataset_source_type: {source_type}")
    return resolver(source_ref)

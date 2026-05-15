"""File storage service for S3."""
import uuid
import logging
import os

import boto3
from botocore.exceptions import ClientError
from aiobotocore.session import get_session

from app.core.config import settings

logger = logging.getLogger(__name__)


class FileStorageService:
    """
    Stores uploaded files to S3 with async support.
    """

    def __init__(self):
        session_kwargs = {}
        if settings.aws_profile:
            session_kwargs["profile_name"] = settings.aws_profile
        session = boto3.Session(**session_kwargs)
        client_kwargs = {"region_name": settings.aws_region}
        if settings.aws_endpoint_url:
            # S3-compatible endpoint (if needed)
            client_kwargs["endpoint_url"] = settings.aws_endpoint_url
        self._s3 = session.client("s3", **client_kwargs)
        self._bucket = settings.s3_bucket
        
        # Async session for async operations
        # aiobotocore uses AWS_PROFILE env var or default credentials
        self._async_session = get_session()
        self._async_client_kwargs = client_kwargs.copy()

    async def store_async(self, file_bytes: bytes, filename: str, workspace_id: str) -> str:
        """
        Async version: Persist file_bytes to S3 and return the S3 key.

        Args:
            file_bytes: Raw file content.
            filename: Original filename (used to derive extension).
            workspace_id: Tenant ID used to namespace storage paths.

        Returns:
            str: S3 key (e.g. "workspaces/<id>/<uuid>.<ext>")
        """
        from pathlib import Path
        ext = Path(filename).suffix.lower()
        unique_name = f"{uuid.uuid4()}{ext}"
        key = f"workspaces/{workspace_id}/{unique_name}"

        try:
            # Set AWS_PROFILE env var if needed for this operation
            old_profile = os.environ.get('AWS_PROFILE')
            if settings.aws_profile:
                os.environ['AWS_PROFILE'] = settings.aws_profile
            
            try:
                async with self._async_session.create_client('s3', **self._async_client_kwargs) as s3:
                    await s3.put_object(Bucket=self._bucket, Key=key, Body=file_bytes)
            finally:
                # Restore original AWS_PROFILE
                if old_profile is not None:
                    os.environ['AWS_PROFILE'] = old_profile
                elif 'AWS_PROFILE' in os.environ:
                    del os.environ['AWS_PROFILE']
            
            logger.info("Stored file to S3 (async)", extra={"key": key, "bucket": self._bucket})
            return key
        except Exception as exc:
            logger.error("S3 upload failed", extra={"key": key, "error": str(exc)})
            raise

    def store(self, file_bytes: bytes, filename: str, workspace_id: str) -> str:
        """
        Sync version: Persist file_bytes to S3 and return the S3 key.

        Args:
            file_bytes: Raw file content.
            filename: Original filename (used to derive extension).
            workspace_id: Tenant ID used to namespace storage paths.

        Returns:
            str: S3 key (e.g. "workspaces/<id>/<uuid>.<ext>")
        """
        from pathlib import Path
        ext = Path(filename).suffix.lower()
        unique_name = f"{uuid.uuid4()}{ext}"
        key = f"workspaces/{workspace_id}/{unique_name}"

        try:
            self._s3.put_object(Bucket=self._bucket, Key=key, Body=file_bytes)
            logger.info("Stored file to S3", extra={"key": key, "bucket": self._bucket})
            return key
        except ClientError as exc:
            logger.error("S3 upload failed", extra={"key": key, "error": str(exc)})
            raise

    def delete(self, key: str) -> None:
        """
        Delete a file from S3.

        Args:
            key: S3 key to delete (e.g. "workspaces/<id>/<uuid>.<ext>")
        """
        try:
            self._s3.delete_object(Bucket=self._bucket, Key=key)
            logger.info("Deleted file from S3", extra={"key": key, "bucket": self._bucket})
        except ClientError as exc:
            logger.error("S3 delete failed", extra={"key": key, "error": str(exc)})
            raise

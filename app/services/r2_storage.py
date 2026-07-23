from functools import lru_cache

import boto3
from botocore.client import Config

from app.core.config import get_settings


@lru_cache
def get_r2_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def upload_report(
    content: bytes,
    object_key: str,
    filename: str,
    content_type: str,
) -> str:
    settings = get_settings()
    client = get_r2_client()
    client.put_object(
        Bucket=settings.r2_bucket_name,
        Key=object_key,
        Body=content,
        ContentType=content_type,
        ContentDisposition=f'attachment; filename="{filename}"',
    )
    return client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.r2_bucket_name,
            "Key": object_key,
            "ResponseContentDisposition": f'attachment; filename="{filename}"',
        },
        ExpiresIn=settings.report_download_url_expiry_seconds,
    )

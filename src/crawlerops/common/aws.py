from __future__ import annotations

from typing import Any

import boto3
from botocore.config import Config

from crawlerops.common.config import Settings

_BOTO_CONFIG = Config(retries={"max_attempts": 5, "mode": "standard"}, connect_timeout=5, read_timeout=30)


def aws_client(service: str, settings: Settings) -> Any:
    return boto3.client(
        service,
        endpoint_url=settings.aws_endpoint_url,
        region_name=settings.aws_region,
        config=_BOTO_CONFIG,
    )

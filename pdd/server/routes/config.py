"""Configuration routes for PDD Server.

Provides endpoints for server configuration and environment information.
"""

from __future__ import annotations

import os

from fastapi import APIRouter
from pydantic import BaseModel

from pdd.core.cloud import CloudConfig

router = APIRouter(prefix="/api/v1/config", tags=["config"])


class CloudUrlResponse(BaseModel):
    """Response model for cloud URL."""

    cloud_url: str
    environment: str
    cloud_enabled: bool


@router.get("/cloud-url", response_model=CloudUrlResponse)
async def get_cloud_url() -> CloudUrlResponse:
    """Tell the browser whether an operator configured a self-hosted service."""
    cloud_url = CloudConfig.get_base_url()
    environment = os.environ.get("PDD_ENV", "self-hosted" if cloud_url else "local")

    return CloudUrlResponse(
        cloud_url=cloud_url,
        environment=environment,
        cloud_enabled=CloudConfig.is_server_configured(),
    )

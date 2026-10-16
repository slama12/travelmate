from typing import Any

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.database import check_database_health
from app.core.providers import get_provider_registry
from app.core.redis import cache_client

router = APIRouter(tags=["Health & Providers"])


async def build_health_payload() -> dict[str, Any]:
    settings = get_settings()
    registry = get_provider_registry(settings)
    db_health = await check_database_health()
    redis_health = await cache_client.health_check()
    providers_summary = registry.health_summary()
    active_modes = {name: info["mode"] for name, info in providers_summary.items()}

    return {
        "status": "ok" if db_health.get("connected") else "degraded",
        "app": {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.APP_ENV,
        },
        "database": db_health,
        "redis": redis_health,
        "active_provider_modes": active_modes,
        "providers": providers_summary,
        "routing_provider": registry.routing_info(),
    }


@router.get("/health")
async def root_health() -> dict[str, Any]:
    """Endpoint de santé global exposant l'état DB, Redis et le mode (real vs simulated) de chaque service."""
    return await build_health_payload()

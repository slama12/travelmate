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
    chat_strategy = str(settings.AI_CHAT_STRATEGY or "rules")

    if chat_strategy == "rules":
        ai_mode = providers_summary.get("ai", {}).get("mode", "simulated")
        ai_conn: dict[str, Any] = {
            "mode": ai_mode,
            "chat_strategy": "rules",
            "provider": "rules_engine",
            "model": "rules-deterministic",
            "ollama_required": False,
            "external_network_required": False,
            "connection_tested": False,
            "connected": True,
            "reachable": True,
            "model_available": True,
        }
    else:
        ai_conn = await registry.ai.check_connection()
        ai_conn["chat_strategy"] = chat_strategy
        ai_conn["ollama_required"] = bool(chat_strategy == "model" and settings.AI_PROVIDER_MODE == "real")

    if "ai" in providers_summary:
        providers_summary["ai"].update(ai_conn)
        providers_summary["ai"]["chat_strategy"] = chat_strategy
        providers_summary["ai"]["ollama_required"] = bool(ai_conn.get("ollama_required", False))
    active_modes = {name: info["mode"] for name, info in providers_summary.items()}

    return {
        "status": "ok" if db_health.get("connected") else "degraded",
        "app": {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.APP_ENV,
        },
        "ai_chat_strategy": chat_strategy,
        "database": db_health,
        "redis": redis_health,
        "active_provider_modes": active_modes,
        "providers": providers_summary,
        "ai_connection": ai_conn,
        "routing_provider": registry.routing_info(),
    }


@router.get("/health")
async def root_health() -> dict[str, Any]:
    """Endpoint de santé global exposant l'état DB, Redis et le mode (real vs simulated) de chaque service."""
    return await build_health_payload()

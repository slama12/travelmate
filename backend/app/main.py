from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.providers import get_provider_registry
from app.core.redis import cache_client
from app.core.seed import seed_initial_data
from app.modules.accommodations import router as accommodations_router
from app.modules.auth import router as auth_router
from app.modules.budget.router import router as budget_router
from app.modules.destinations import router as destinations_router
from app.modules.documents.router import router as documents_router
from app.modules.flights import router as flights_router
from app.modules.health import router as health_router
from app.modules.intelligence.router import router as intelligence_router
from app.modules.itinerary.router import router as itinerary_router
from app.modules.places import router as places_router
from app.modules.transports.router import router as transports_router
from app.modules.trips import router as trips_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("travelmate.main")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    registry = get_provider_registry(settings)
    registry.log_active_modes()

    try:
        async with AsyncSessionLocal() as session:
            await seed_initial_data(session)
    except Exception as exc:
        logger.warning("Seed automatique différé (migrations non appliquées ou DB en attente): %s", exc)

    yield
    await cache_client.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Application web modulaire de voyage complète "
            "(Étapes 1 à 5A : Socle, Réservation, Géospatial, Planification, Météo, Itinéraire IA, Chat, Budget, Documents, Infos pratiques & RBAC)."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Endpoint /health à la racine et sous /api/v1/health
    app.include_router(health_router)
    app.include_router(health_router, prefix=settings.API_V1_STR)

    # Modules Étape 1
    app.include_router(auth_router, prefix=settings.API_V1_STR)
    app.include_router(destinations_router, prefix=settings.API_V1_STR)
    app.include_router(trips_router, prefix=settings.API_V1_STR)

    # Modules Étape 2 : Vols, Hébergements & Restaurants proches, Galerie de Lieux
    app.include_router(flights_router, prefix=settings.API_V1_STR)
    app.include_router(accommodations_router, prefix=settings.API_V1_STR)
    app.include_router(places_router, prefix=settings.API_V1_STR)

    # Modules Étape 3 : Planification, Validation métier, Optimisation de trajet, Calendar & Transports sur place
    app.include_router(itinerary_router, prefix=settings.API_V1_STR)
    app.include_router(transports_router, prefix=settings.API_V1_STR)

    # Modules Étape 4 : Météo, Itinéraire IA en brouillon, Assistant de chat & Temps de trajet réels/estimés
    app.include_router(intelligence_router, prefix=settings.API_V1_STR)

    # Modules Étape 5A : Budget, Documents chiffrés, Rappel passeport
    app.include_router(budget_router, prefix=f"{settings.API_V1_STR}/budget", tags=["Budget"])
    app.include_router(documents_router, prefix=f"{settings.API_V1_STR}/documents", tags=["Documents"])
    app.include_router(documents_router, prefix=f"{settings.API_V1_STR}/vault", tags=["Documents"])

    return app


app = create_app()

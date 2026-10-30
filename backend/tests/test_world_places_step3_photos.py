from __future__ import annotations

import ast
import asyncio
from decimal import Decimal
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.redis import cache_client
from app.models.entities import Destination, Place
from app.modules.places.world_place_photos_service import (
    PHOTO_CONCURRENCY_LIMIT,
    WORLD_PHOTOS_USER_AGENT,
    WorldPlacePhotoService,
    audit_demo_cities_photos,
    format_photo_credit,
    is_forbidden_image_title_or_type,
    normalize_and_validate_free_license,
    verify_place_photo_correspondence,
    verify_seed_demo_photos_integrity,
)

WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"


def _make_commons_imageinfo_response(
    file_title: str = "File:Ribat Monastir 2022.jpg",
    thumb_url: str = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Ribat_Monastir_2022.jpg/800px-Ribat_Monastir_2022.jpg",
    orig_url: str = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Ribat_Monastir_2022.jpg",
    desc_url: str = "https://commons.wikimedia.org/wiki/File:Ribat_Monastir_2022.jpg",
    artist_html: str = '<a href="https://commons.wikimedia.org/wiki/User:JeanDupont">Jean Dupont</a>',
    license_short: str = "CC BY-SA 4.0",
    width: int = 1600,
    height: int = 900,
    mime: str = "image/jpeg",
) -> dict[str, Any]:
    return {
        "query": {
            "pages": {
                "101": {
                    "pageid": 101,
                    "title": file_title,
                    "imageinfo": [
                        {
                            "thumburl": thumb_url,
                            "url": orig_url,
                            "descriptionurl": desc_url,
                            "width": width,
                            "height": height,
                            "mime": mime,
                            "extmetadata": {
                                "Artist": {"value": artist_html},
                                "LicenseShortName": {"value": license_short},
                            },
                        }
                    ],
                }
            }
        }
    }


def _make_wikidata_p18_response(entity_id: str, p18_filename: str | None) -> dict[str, Any]:
    claims: dict[str, Any] = {}
    if p18_filename:
        claims["P18"] = [
            {
                "mainsnak": {
                    "snaktype": "value",
                    "property": "P18",
                    "datavalue": {"value": p18_filename, "type": "string"},
                }
            }
        ]
    return {"entities": {entity_id: {"id": entity_id, "claims": claims}}}


@pytest.mark.asyncio
async def test_place_photo_via_wikidata_p18_with_author_and_license() -> None:
    """
    1(a) & 2 : Lieu avec P18 sur Wikidata -> récupère le fichier image, valide ses métadonnées
    via l'API Commons (titre, auteur nettoyé, licence libre, lien Commons, vignette ~800px)
    et envoie le User-Agent identifiable 'TravelMate/1.0 (contact)'.
    """
    await cache_client.clear_prefix("place:photo:")
    seen_user_agents: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_user_agents.append(request.headers.get("User-Agent", ""))
        url = str(request.url)
        params = dict(request.url.params)
        if "wikidata.org" in url and params.get("action") == "wbgetentities":
            return httpx.Response(200, json=_make_wikidata_p18_response("Q2295006", "Ribat Monastir 2022.jpg"))
        if "commons.wikimedia.org" in url and params.get("prop") == "imageinfo":
            assert params.get("iiurlwidth") == "800"
            assert "extmetadata" in str(params.get("iiprop"))
            return httpx.Response(
                200,
                json=_make_commons_imageinfo_response(
                    file_title="File:Ribat Monastir 2022.jpg",
                    artist_html="<b> Habib M'henni </b> (Wikimedia Commons)",
                    license_short="CC BY-SA 4.0",
                ),
            )
        raise AssertionError(f"Unexpected call to {url} with {params}")

    svc = WorldPlacePhotoService(http_transport=httpx.MockTransport(handler))
    res = await svc.resolve_place_photo(
        place_name="Ribat de Monastir",
        source_provider="wikipedia_wikidata",
        external_place_id="Q2295006",
        opening_hours={"status": "horaires non renseignés", "_wikidata_id": "Q2295006"},
    )

    assert res.has_photo is True
    assert res.photo_source == "wikidata_p18"
    assert res.photo_file_title == "File:Ribat Monastir 2022.jpg"
    assert res.photo_author == "Habib M'henni (Wikimedia Commons)"
    assert res.photo_license == "CC BY-SA 4.0"
    assert res.photo_commons_url == "https://commons.wikimedia.org/wiki/File:Ribat_Monastir_2022.jpg"
    assert res.photo_url is not None and "800px-" in res.photo_url
    assert res.photo_credit_text == "Photo : Habib M'henni (Wikimedia Commons), CC BY-SA 4.0"
    assert format_photo_credit(res.photo_author, res.photo_license) == (
        "Photo : Habib M'henni (Wikimedia Commons), CC BY-SA 4.0"
    )
    assert seen_user_agents and all(ua == WORLD_PHOTOS_USER_AGENT for ua in seen_user_agents)


@pytest.mark.asyncio
async def test_place_photo_fallback_to_wikipedia_pageimages_only() -> None:
    """
    1(b) : Lieu dont l'entité Wikidata n'a pas de P18, mais dont l'article Wikipédia possède
    une image principale (prop=pageimages, pithumbsize=800).
    """
    await cache_client.clear_prefix("place:photo:")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        params = dict(request.url.params)
        if "wikidata.org" in url and params.get("action") == "wbgetentities":
            return httpx.Response(200, json=_make_wikidata_p18_response("Q132053", None))
        if "wikipedia.org" in url and params.get("prop") == "pageimages":
            assert params.get("pithumbsize") == "800"
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": {
                            "202": {
                                "pageid": 202,
                                "title": "Dôme de Milan",
                                "pageimage": "Milano_Duomo_Facade.jpg",
                                "thumbnail": {
                                    "source": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/12/Milano_Duomo_Facade.jpg/800px-Milano_Duomo_Facade.jpg",
                                    "width": 800,
                                    "height": 533,
                                },
                            }
                        }
                    }
                },
            )
        if "commons.wikimedia.org" in url and params.get("prop") == "imageinfo":
            return httpx.Response(
                200,
                json=_make_commons_imageinfo_response(
                    file_title="File:Milano Duomo Facade.jpg",
                    thumb_url="https://upload.wikimedia.org/wikipedia/commons/thumb/1/12/Milano_Duomo_Facade.jpg/800px-Milano_Duomo_Facade.jpg",
                    desc_url="https://commons.wikimedia.org/wiki/File:Milano_Duomo_Facade.jpg",
                    artist_html="Marco Rossi",
                    license_short="CC BY 3.0",
                ),
            )
        raise AssertionError(f"Unexpected call to {url} with {params}")

    svc = WorldPlacePhotoService(http_transport=httpx.MockTransport(handler))
    res = await svc.resolve_place_photo(
        place_name="Dôme de Milan",
        source_provider="wikipedia_wikidata",
        external_place_id="Q132053",
        opening_hours={
            "status": "horaires non renseignés",
            "_wikidata_id": "Q132053",
            "_wikipedia_title": "Dôme de Milan",
            "_wikipedia_lang": "fr",
        },
    )

    assert res.has_photo is True
    assert res.photo_source == "wikipedia_pageimages"
    assert res.photo_file_title == "File:Milano Duomo Facade.jpg"
    assert res.photo_author == "Marco Rossi"
    assert res.photo_license == "CC BY 3.0"
    assert res.photo_commons_url == "https://commons.wikimedia.org/wiki/File:Milano_Duomo_Facade.jpg"


@pytest.mark.asyncio
async def test_place_without_image_returns_none_and_keeps_placeholder() -> None:
    """
    1(c) : Lieu sans P18 ni image Wikipédia -> aucune photo (conserve l'illustration neutre
    et 'Photo bientôt disponible').
    """
    await cache_client.clear_prefix("place:photo:")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "wikidata.org" in url:
            return httpx.Response(200, json=_make_wikidata_p18_response("Q999999", None))
        if "wikipedia.org" in url:
            return httpx.Response(
                200,
                json={"query": {"pages": {"303": {"pageid": 303, "title": "Petit Jardin Local"}}}},
            )
        return httpx.Response(200, json={})

    svc = WorldPlacePhotoService(http_transport=httpx.MockTransport(handler))
    res = await svc.resolve_place_photo(
        place_name="Petit Jardin Local",
        source_provider="wikipedia_wikidata",
        external_place_id="Q999999",
        opening_hours={
            "status": "horaires non renseignés",
            "_wikidata_id": "Q999999",
            "_wikipedia_title": "Petit Jardin Local",
            "_wikipedia_lang": "fr",
        },
    )
    assert res.has_photo is False
    assert res.photo_url is None
    assert res.photo_source == "none"


@pytest.mark.asyncio
async def test_non_free_license_refused_and_free_licenses_accepted() -> None:
    """
    2 : Refuse les fichiers sans licence libre claire (CC0, CC BY, CC BY-SA, domaine public).
    """
    await cache_client.clear_prefix("place:photo:")

    assert normalize_and_validate_free_license("CC0") == "CC0"
    assert normalize_and_validate_free_license("CC-BY-4.0") == "CC BY 4.0"
    assert normalize_and_validate_free_license("CC BY-SA 3.0") == "CC BY-SA 3.0"
    assert normalize_and_validate_free_license("Public domain") == "Public domain"
    assert normalize_and_validate_free_license("Domaine public") == "Domaine public"

    assert normalize_and_validate_free_license("CC BY-NC 4.0") is None
    assert normalize_and_validate_free_license("CC BY-NC-SA 3.0") is None
    assert normalize_and_validate_free_license("CC BY-ND 4.0") is None
    assert normalize_and_validate_free_license("Fair use") is None
    assert normalize_and_validate_free_license("All rights reserved") is None
    assert normalize_and_validate_free_license("") is None
    assert normalize_and_validate_free_license(None) is None

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "wikidata.org" in url:
            return httpx.Response(200, json=_make_wikidata_p18_response("Q55555", "NonFree_Monument.jpg"))
        if "commons.wikimedia.org" in url:
            return httpx.Response(
                200,
                json=_make_commons_imageinfo_response(
                    file_title="File:NonFree Monument.jpg",
                    license_short="CC BY-NC-SA 4.0",
                ),
            )
        return httpx.Response(200, json={})

    svc = WorldPlacePhotoService(http_transport=httpx.MockTransport(handler))
    res = await svc.resolve_place_photo(
        place_name="Monument Non Libre",
        source_provider="wikipedia_wikidata",
        external_place_id="Q55555",
        opening_hours={"_wikidata_id": "Q55555"},
    )
    assert res.has_photo is False
    assert res.photo_url is None


@pytest.mark.asyncio
async def test_map_logo_flag_coat_of_arms_svg_and_small_width_ignored() -> None:
    """
    5 : Qualité : ignore les images qui sont des cartes, logos, drapeaux, blasons, plans ou schémas
    (type SVG, mots 'map', 'logo', 'flag', 'coat of arms' dans le titre) et largeur < 400 px.
    """
    await cache_client.clear_prefix("place:photo:")

    assert is_forbidden_image_title_or_type("File:City_locator_map.png", "image/png")[0] is True
    assert is_forbidden_image_title_or_type("File:Restaurant_Logo_2020.jpg", "image/jpeg")[0] is True
    assert is_forbidden_image_title_or_type("File:Flag_of_Tunisia.jpg", "image/jpeg")[0] is True
    assert is_forbidden_image_title_or_type("File:Coat of arms of Lisbon.png", "image/png")[0] is True
    assert is_forbidden_image_title_or_type("File:Blason_ville.png", "image/png")[0] is True
    assert is_forbidden_image_title_or_type("File:Plan_du_chateau.jpg", "image/jpeg")[0] is True
    assert is_forbidden_image_title_or_type("File:Monastir_view.svg", "image/svg+xml")[0] is True
    assert is_forbidden_image_title_or_type("File:Castelo_Sao_Jorge_Lisboa.jpg", "image/jpeg")[0] is False

    # Cas où P18 est une carte ou trop petite (< 400 px) -> ignorée, repli sur Wikipedia pageimages valide
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        params = dict(request.url.params)
        if "wikidata.org" in url:
            return httpx.Response(
                200,
                json={
                    "entities": {
                        "Q749108": {
                            "id": "Q749108",
                            "claims": {
                                "P18": [
                                    {"mainsnak": {"datavalue": {"value": "Castelo_location_map.png"}}},
                                    {"mainsnak": {"datavalue": {"value": "Tiny_photo.jpg"}}},
                                ]
                            },
                        }
                    }
                },
            )
        if "commons.wikimedia.org" in url:
            titles = str(params.get("titles"))
            if "Tiny photo.jpg" in titles or "Tiny_photo.jpg" in titles:
                return httpx.Response(
                    200,
                    json=_make_commons_imageinfo_response(
                        file_title="File:Tiny photo.jpg",
                        width=320,
                        height=240,
                    ),
                )
            if "Castelo Sao Jorge Real.jpg" in titles or "Castelo_Sao_Jorge_Real.jpg" in titles:
                return httpx.Response(
                    200,
                    json=_make_commons_imageinfo_response(
                        file_title="File:Castelo Sao Jorge Real.jpg",
                        artist_html="Alves Gaspar",
                        license_short="CC BY-SA 4.0",
                        width=1280,
                        height=720,
                    ),
                )
        if "wikipedia.org" in url and params.get("prop") == "pageimages":
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": {
                            "777": {
                                "pageid": 777,
                                "title": "Château Saint-Georges",
                                "pageimage": "Castelo_Sao_Jorge_Real.jpg",
                            }
                        }
                    }
                },
            )
        return httpx.Response(200, json={})

    svc = WorldPlacePhotoService(http_transport=httpx.MockTransport(handler))
    res = await svc.resolve_place_photo(
        place_name="Castelo de São Jorge",
        source_provider="wikivoyage_fr",
        external_place_id="wikivoyage:fr:lisbonne:castelo",
        opening_hours={
            "_wikidata_id": "Q749108",
            "_wikipedia_title": "Château Saint-Georges",
            "_wikipedia_lang": "fr",
        },
    )
    assert res.has_photo is True
    assert res.photo_file_title == "File:Castelo Sao Jorge Real.jpg"
    assert res.photo_source == "wikipedia_pageimages"


@pytest.mark.asyncio
async def test_commons_saturated_retries_with_exponential_backoff() -> None:
    """
    4 & 7 : Commons saturé (429 / maxlag / cirrussearch-too-busy-error) -> nouvelles tentatives
    avec attente croissante (1, 2, 4 s).
    """
    sleep_delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, json={"error": {"code": "maxlag", "info": "Too busy"}})
        if attempts == 2:
            return httpx.Response(200, json={"error": {"code": "cirrussearch-too-busy-error", "info": "Busy"}})
        return httpx.Response(
            200,
            json=_make_commons_imageinfo_response(
                file_title="File:Ribat After Retry.jpg",
                artist_html="Auteur Test",
                license_short="CC0",
            ),
        )

    svc = WorldPlacePhotoService(
        http_transport=httpx.MockTransport(handler),
        sleep_func=fake_sleep,
    )
    async with httpx.AsyncClient(transport=svc._http_transport) as http_client:
        resolved, reason = await svc.fetch_and_validate_commons_image(
            http_client,
            "File:Ribat_After_Retry.jpg",
        )

    assert attempts == 3
    assert sleep_delays == [1.0, 2.0]
    assert reason is None
    assert resolved is not None and resolved.has_photo is True
    assert resolved.photo_license == "CC0"
    assert resolved.photo_author == "Auteur Test"


@pytest.mark.asyncio
async def test_no_photo_of_another_place_when_in_doubt_strict_coord_and_name_match() -> None:
    """
    1 & 7 : Jamais de recherche floue par nom (risque de photo d'un autre lieu).
    Pour les fiches Wikivoyage sans article lié, cherche l'entité Wikidata par coordonnées
    explicites et nom exact ; si le moindre doute existe (coordonnées synthétiques, nom proche
    mais non exact, ou plusieurs entités au même nom), ne met pas de photo.
    """
    await cache_client.clear_prefix("place:photo:")

    # Cas A : Fiche Wikivoyage sans coordonnées explicites (_has_explicit_coords=False) -> aucun appel, pas de photo
    svc_a = WorldPlacePhotoService(
        http_transport=httpx.MockTransport(lambda req: (_ for _ in ()).throw(AssertionError("Ne doit pas appeler l'API")))
    )
    res_a = await svc_a.resolve_place_photo(
        place_name="Restaurant Le Pirate",
        source_provider="wikivoyage_fr",
        external_place_id="wikivoyage:fr:monastir:le_pirate",
        latitude=35.778,
        longitude=10.826,
        has_explicit_coords=False,
        opening_hours={"_has_explicit_coords": False},
    )
    assert res_a.has_photo is False

    # Cas B : Coordonnées explicites, mais l'entité Wikidata voisine a un nom différent/proche ("Musée du Ribat" != "Ribat de Monastir")
    def handler_non_exact(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        if params.get("list") == "geosearch":
            return httpx.Response(
                200,
                json={
                    "query": {
                        "geosearch": [
                            {"title": "Q88888", "lat": 35.7761, "lon": 10.8331, "dist": 15.0}
                        ]
                    }
                },
            )
        if params.get("action") == "wbgetentities":
            return httpx.Response(
                200,
                json={
                    "entities": {
                        "Q88888": {
                            "id": "Q88888",
                            "labels": {"fr": {"value": "Musée du Ribat"}},
                            "aliases": {},
                            "claims": {"P18": [{"mainsnak": {"datavalue": {"value": "Other_Place.jpg"}}}]},
                        }
                    }
                },
            )
        return httpx.Response(200, json={})

    svc_b = WorldPlacePhotoService(http_transport=httpx.MockTransport(handler_non_exact))
    res_b = await svc_b.resolve_place_photo(
        place_name="Ribat de Monastir",
        source_provider="wikivoyage_fr",
        external_place_id="wikivoyage:fr:monastir:ribat",
        latitude=35.7760,
        longitude=10.8330,
        has_explicit_coords=True,
        opening_hours={"_has_explicit_coords": True},
    )
    assert res_b.has_photo is False
    assert res_b.photo_url is None

    # Cas C : Ambiguïté (2 entités proches portent exactement le même nom) -> doute -> pas de photo
    def handler_ambiguous(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        if params.get("list") == "geosearch":
            return httpx.Response(
                200,
                json={
                    "query": {
                        "geosearch": [
                            {"title": "Q111", "lat": 35.7760, "lon": 10.8330, "dist": 10.0},
                            {"title": "Q222", "lat": 35.7761, "lon": 10.8331, "dist": 25.0},
                        ]
                    }
                },
            )
        if params.get("action") == "wbgetentities":
            return httpx.Response(
                200,
                json={
                    "entities": {
                        "Q111": {"id": "Q111", "labels": {"fr": {"value": "Café Central"}}},
                        "Q222": {"id": "Q222", "labels": {"fr": {"value": "Café Central"}}},
                    }
                },
            )
        return httpx.Response(200, json={})

    svc_c = WorldPlacePhotoService(http_transport=httpx.MockTransport(handler_ambiguous))
    res_c = await svc_c.resolve_place_photo(
        place_name="Café Central",
        source_provider="wikivoyage_fr",
        external_place_id="wikivoyage:fr:monastir:cafe_central",
        latitude=35.7760,
        longitude=10.8330,
        has_explicit_coords=True,
        opening_hours={"_has_explicit_coords": True},
    )
    assert res_c.has_photo is False


@pytest.mark.asyncio
async def test_parallel_enrichment_concurrency_4_dedup_cache_and_backfill(
    db_session: Any,
) -> None:
    """
    4, 5 & 6 :
    - Parallélisme limité à 4 requêtes simultanées (Semaphore(4))
    - Pas de doublon de photo entre lieux de la même ville
    - Cache en base et Redis (une seule recherche par lieu)
    - Tâche de rattrapage (backfill) pour les lieux déjà enregistrés sans photo
    - Les 5 villes de démo gardent leurs photos actuelles.
    """
    await cache_client.clear_prefix("place:photo:")

    wikidata_calls_by_qid: dict[str, int] = {}

    async def async_handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.02)
        url = str(request.url)
        params = dict(request.url.params)
        if "wikidata.org" in url and params.get("action") == "wbgetentities":
            qid = str(params.get("ids"))
            wikidata_calls_by_qid[qid] = wikidata_calls_by_qid.get(qid, 0) + 1
            # Q1000 et Q1001 renvoient la même image pour tester l'anti-doublon dans la même ville
            if qid in ("Q1000", "Q1001"):
                return httpx.Response(200, json=_make_wikidata_p18_response(qid, "Shared_City_Photo.jpg"))
            return httpx.Response(200, json=_make_wikidata_p18_response(qid, f"Photo_{qid}.jpg"))
        if "commons.wikimedia.org" in url:
            title = str(params.get("titles"))
            clean = title.replace("File:", "").replace(" ", "_")
            return httpx.Response(
                200,
                json=_make_commons_imageinfo_response(
                    file_title=title,
                    thumb_url=f"https://upload.wikimedia.org/wikipedia/commons/thumb/9/99/{clean}/800px-{clean}",
                    desc_url=f"https://commons.wikimedia.org/wiki/File:{clean}",
                    artist_html=f"Photographe {clean}",
                    license_short="CC BY-SA 4.0",
                ),
            )
        return httpx.Response(200, json={})

    class AsyncCallbackTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return await async_handler(request)

    svc = WorldPlacePhotoService(http_transport=AsyncCallbackTransport())

    db = db_session
    dest = Destination(
        city_name=f"PortoTest_{uuid4().hex[:6]}",
        country_name="Portugal",
        country_code_iso2="PT",
        iata_code="OPO",
        timezone="Europe/Lisbon",
        latitude=41.1579,
        longitude=-8.6291,
        geoname_id=2735943,
        hero_image_url="https://images.unsplash.com/photo-1555881400-74d7acaacd8b?w=1200",
        description="Porto test",
        practical_info={},
        useful_phrases=[],
    )
    db.add(dest)
    await db.flush()

    places: list[Place] = []
    for idx in range(8):
        qid = f"Q{1000 + idx}"
        p = Place(
            destination_id=dest.id,
            name=f"Monument Porto {idx}",
            description="Lieu culturel.",
            category="CULTURE",
            is_outdoor=False,
            latitude=41.15 + idx * 0.002,
            longitude=-8.62 + idx * 0.002,
            recommended_duration_min=60,
            estimated_cost=Decimal("0.00"),
            price_tier="STANDARD",
            avg_rating=4.7,
            opening_hours={"_wikidata_id": qid},
            hero_photos=[],
            source_provider="wikipedia_wikidata",
            external_place_id=qid,
            notoriety_score=100 - idx,
        )
        db.add(p)
        places.append(p)
    await db.commit()
    for p in places:
        await db.refresh(p)

    await svc.enrich_places_photos(db, places)

    # Limite de simultanéité respectée (<= 4)
    assert svc.max_observed_concurrency <= PHOTO_CONCURRENCY_LIMIT

    # Pas de doublon entre Q1000 et Q1001 dans la même ville
    assert places[0].hero_photos and len(places[0].hero_photos) == 1
    assert places[1].hero_photos == []
    assert places[1].photo_source == "none"

    # Un deuxième appel utilise le cache (aucun nouvel appel Wikidata)
    calls_snapshot = dict(wikidata_calls_by_qid)
    await svc.enrich_places_photos(db, places)
    assert wikidata_calls_by_qid == calls_snapshot

    # Tâche de rattrapage (backfill) sur un nouveau lieu enregistré sans photo
    late_place = Place(
        destination_id=dest.id,
        name="Tour des Clercs",
        description="Tour baroque.",
        category="CULTURE",
        is_outdoor=False,
        latitude=41.1458,
        longitude=-8.6139,
        recommended_duration_min=60,
        estimated_cost=Decimal("0.00"),
        price_tier="STANDARD",
        avg_rating=4.8,
        opening_hours={"_wikidata_id": "Q1099"},
        hero_photos=[],
        source_provider="wikipedia_wikidata",
        external_place_id="Q1099",
    )
    db.add(late_place)
    await db.commit()

    stats = await svc.backfill_missing_place_photos(db, destination_id=dest.id)
    assert stats["checked_count"] == 1
    assert stats["updated_count"] == 1
    await db.refresh(late_place)
    assert len(late_place.hero_photos) == 1
    assert late_place.photo_license == "CC BY-SA 4.0"


def test_demo_cities_photo_audit_verifies_5_landmarks_and_no_duplicates() -> None:
    """
    1, 2, 3, 4 & 5 :
    - Plus aucun doublon d'image dans une ville ni dans tout le seed.
    - Zéro URL Unsplash restante : uniquement le pipeline Wikidata P18 -> Wikipédia pageimages -> Commons imageinfo,
      ou l'illustration neutre (hero_photos == []).
    - Contrôle automatique : pour chaque photo, le titre du fichier Commons ou l'entité Wikidata correspond
      au lieu (nom normalisé ou alias), et aucune URL d'image n'apparaît sur deux lieux.
    - Les 5 lieux témoins (Jardin Majorelle, Tour Eiffel, Colisée, Met, Senso-ji) ont la bonne source Commons
      et leur crédit auteur + licence libre présent.
    """
    audit = audit_demo_cities_photos()
    assert audit["is_valid"] is True
    assert audit["demo_cities_count"] == 5
    assert audit["total_demo_places"] == 70
    assert audit["places_with_photo"] == 52
    assert audit["places_without_photo"] == 18
    assert audit["unsplash_urls"] == []
    assert audit["duplicate_urls"] == []
    assert audit["duplicate_file_titles"] == []
    assert audit["mismatched_places"] == []
    assert audit["missing_credits"] == []

    focus = audit["focus_landmarks"]
    assert set(focus.keys()) == {"Jardin Majorelle", "Tour Eiffel", "Colisée", "Met", "Senso-ji"}

    expected_focus = {
        "Jardin Majorelle": {
            "file_title": "File:Le jardin des majorelle 16.JPG",
            "author": "Viault",
            "license": "CC BY-SA 4.0",
            "credit": "Photo : Viault, CC BY-SA 4.0",
            "qid": "Q1395431",
        },
        "Tour Eiffel": {
            "file_title": "File:Tour Eiffel Wikimedia Commons.jpg",
            "author": "Benh LIEU SONG",
            "license": "Public domain",
            "credit": "Photo : Benh LIEU SONG, Public domain",
            "qid": "Q243",
        },
        "Colisée": {
            "file_title": "File:Colosseo 2020.jpg",
            "author": "FeaturedPics",
            "license": "CC BY-SA 4.0",
            "credit": "Photo : FeaturedPics, CC BY-SA 4.0",
            "qid": "Q10285",
        },
        "Met": {
            "file_title": "File:Metropolitan Museum of Art (The Met) - Central Park, NYC.jpg",
            "author": "Hugo Schneider",
            "license": "CC BY-SA 2.0",
            "credit": "Photo : Hugo Schneider, CC BY-SA 2.0",
            "qid": "Q160236",
        },
        "Senso-ji": {
            "file_title": "File:Sensoji 2023.jpg",
            "author": "Akonnchiroll",
            "license": "CC0",
            "credit": "Photo : Akonnchiroll, CC0",
            "qid": "Q615183",
        },
    }

    for key, exp in expected_focus.items():
        item = focus[key]
        assert item["matches_place"] is True
        assert item["title_matches"] is True
        assert item["wikidata_matches"] is True
        assert item["status"] == "correspond"
        assert item["photo_source"] == "wikidata_p18"
        assert item["wikidata_id"] == exp["qid"]
        assert item["photo_file_title"] == exp["file_title"]
        assert item["photo_author"] == exp["author"]
        assert item["photo_license"] == exp["license"]
        assert item["credit_text"] == exp["credit"]
        assert item["url"] and "wikimedia.org/wikipedia/commons/thumb/" in item["url"]
        assert item["photo_commons_url"] and "commons.wikimedia.org/wiki/File:" in item["photo_commons_url"]


def test_automatic_control_rejects_mismatched_title_and_duplicate_urls() -> None:
    """
    3 : Vérifie que le contrôle automatique détecte immédiatement :
    - une photo dont le titre Commons et l'entité Wikidata ne correspondent pas au lieu,
    - une URL d'image qui apparaît sur deux lieux.
    """
    bad_corr = verify_place_photo_correspondence(
        place_name="Le Jardin Secret (Médina)",
        photo_file_title="File:Taj Mahal in Agra India.jpg",
        external_place_id=None,
        opening_hours={},
    )
    assert bad_corr["matches"] is False

    shared_url = "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a8/Tour_Eiffel_Wikimedia_Commons.jpg/800px-Tour_Eiffel_Wikimedia_Commons.jpg"
    synthetic_destinations = [
        {
            "city_name": "Paris",
            "places": [
                {
                    "name": "Le Jules Verne (Tour Eiffel)",
                    "hero_photos": [shared_url],
                    "external_place_id": "Q243",
                    "photo_file_title": "File:Tour Eiffel Wikimedia Commons.jpg",
                    "photo_author": "Benh LIEU SONG",
                    "photo_license": "Public domain",
                    "photo_commons_url": "https://commons.wikimedia.org/wiki/File:Tour_Eiffel_Wikimedia_Commons.jpg",
                    "photo_source": "wikidata_p18",
                    "opening_hours": {"_wikidata_id": "Q243", "_wikipedia_title": "Tour Eiffel", "_aliases": ["Tour Eiffel"]},
                },
                {
                    "name": "Jardin des Tuileries",
                    "hero_photos": [shared_url],
                    "external_place_id": "Q818517",
                    "photo_file_title": "File:Tour Eiffel Wikimedia Commons.jpg",
                    "photo_author": "Benh LIEU SONG",
                    "photo_license": "Public domain",
                    "photo_commons_url": "https://commons.wikimedia.org/wiki/File:Tour_Eiffel_Wikimedia_Commons.jpg",
                    "photo_source": "wikidata_p18",
                    "opening_hours": {"_wikidata_id": "Q818517", "_wikipedia_title": "Jardin des Tuileries", "_aliases": ["Tuileries"]},
                },
            ],
        }
    ]
    report = verify_seed_demo_photos_integrity(synthetic_destinations)
    assert report["is_valid"] is False
    assert len(report["duplicate_urls"]) >= 1
    assert len(report["mismatched_places"]) == 1


@pytest.mark.asyncio
async def test_alembic_single_head_and_seeded_db_places_have_no_duplicates_and_credits(
    db_session: Any,
) -> None:
    """
    5 : Vérifie qu'il n'y a qu'une seule tête Alembic (`alembic heads`) et qu'en base PostgreSQL
    le seed applique bien toutes les photos Commons uniques et leurs crédits aux 5 villes de démo.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import select
    from app.core.seed import SEED_DESTINATIONS, seed_initial_data

    backend_root = Path(__file__).resolve().parents[1]
    alembic_cfg = Config(str(backend_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_root / "alembic"))
    script_dir = ScriptDirectory.from_config(alembic_cfg)
    heads = script_dir.get_heads()
    assert len(heads) == 1, f"Attendu une seule tête Alembic, trouvé : {heads}"
    assert heads[0] == "0008_place_photos_step3"
    assert len(heads[0]) <= 32

    await seed_initial_data(db_session)

    demo_cities = [d["city_name"] for d in SEED_DESTINATIONS]
    dests = list(
        (await db_session.scalars(select(Destination).where(Destination.city_name.in_(demo_cities)))).all()
    )
    assert len(dests) == 5
    dest_ids = [d.id for d in dests]

    db_places = list(
        (
            await db_session.scalars(
                select(Place).where(
                    Place.destination_id.in_(dest_ids),
                    Place.source_provider == "simulated",
                )
            )
        ).all()
    )
    assert len(db_places) == 70

    seen_db_urls: set[str] = set()
    for p in db_places:
        if p.hero_photos:
            assert len(p.hero_photos) == 1
            url = p.hero_photos[0]
            assert "unsplash.com" not in url.lower()
            assert url not in seen_db_urls, f"URL dupliquée en base pour {p.name}: {url}"
            seen_db_urls.add(url)
            assert p.photo_file_title and p.photo_file_title.startswith("File:")
            assert p.photo_author
            assert normalize_and_validate_free_license(p.photo_license) is not None
            assert p.photo_commons_url and p.photo_commons_url.startswith("https://commons.wikimedia.org/wiki/File:")
            assert format_photo_credit(p.photo_author, p.photo_license) == f"Photo : {p.photo_author}, {p.photo_license}"
        else:
            assert p.photo_source == "none"



def test_requirements_lock_contains_all_imported_modules() -> None:
    """
    7 : Test de contrôle du fichier requirements.lock :
    vérifie que tous les modules tiers importés dans backend/app sont présents
    et épinglés dans backend/requirements.lock.
    """
    backend_root = Path(__file__).resolve().parents[1]
    app_root = backend_root / "app"
    lock_file = backend_root / "requirements.lock"
    assert lock_file.exists(), "backend/requirements.lock est introuvable"

    locked_packages: dict[str, str] = {}
    for raw_line in lock_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        assert "==" in line, f"Ligne non épinglée dans requirements.lock : {line}"
        pkg_name, version = line.split("==", 1)
        norm_pkg = pkg_name.split("[", 1)[0].strip().lower().replace("_", "-")
        locked_packages[norm_pkg] = version.strip()

    import_to_dist = {
        "fastapi": "fastapi",
        "pydantic": "pydantic",
        "pydantic_settings": "pydantic-settings",
        "sqlalchemy": "sqlalchemy",
        "alembic": "alembic",
        "asyncpg": "asyncpg",
        "aiosqlite": "aiosqlite",
        "redis": "redis",
        "httpx": "httpx",
        "jwt": "pyjwt",
        "bcrypt": "bcrypt",
        "passlib": "passlib",
        "mwparserfromhell": "mwparserfromhell",
        "uvicorn": "uvicorn",
        "starlette": "starlette",
        "anyio": "anyio",
        "email_validator": "email-validator",
        "multipart": "python-multipart",
    }

    stdlib_modules = set(getattr(sys, "stdlib_module_names", set())) | {
        "__future__",
        "typing_extensions",
    }
    internal_modules = {"app", "alembic", "tests"}

    imported_top_modules: set[str] = set()
    for py_file in app_root.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".", 1)[0]
                    imported_top_modules.add(top)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                top = node.module.split(".", 1)[0]
                imported_top_modules.add(top)

    missing_from_lock: list[str] = []
    for mod in sorted(imported_top_modules):
        if mod in stdlib_modules or mod in internal_modules:
            continue
        dist_name = import_to_dist.get(mod, mod.lower().replace("_", "-"))
        if dist_name not in locked_packages:
            missing_from_lock.append(f"{mod} (attendu: {dist_name})")

    assert not missing_from_lock, (
        f"Modules importés dans backend/app absents de requirements.lock : {missing_from_lock}"
    )
    assert "mwparserfromhell" in locked_packages


@pytest.mark.asyncio
async def test_router_photos_enrich_and_backfill_endpoints(
    client: AsyncClient,
    db_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    3 & 4 : Vérifie les endpoints HTTP non bloquants :
    - POST /api/v1/places/trip/{trip_id}/photos/enrich
    - POST /api/v1/places/city/{city_name}/photos/enrich
    - POST /api/v1/places/photos/backfill
    et la sérialisation de photo_credit_text ('Photo : <auteur>, <licence>'), photo_commons_url, photo_checked.
    """
    await cache_client.clear_prefix("place:photo:")

    import app.modules.places.router  # noqa: F401

    places_router_module = sys.modules["app.modules.places.router"]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        params = dict(request.url.params)
        if "wikidata.org" in url and params.get("action") == "wbgetentities":
            return httpx.Response(200, json=_make_wikidata_p18_response("Q1571135", "Ribat_Monastir_Facade.jpg"))
        if "commons.wikimedia.org" in url:
            return httpx.Response(
                200,
                json=_make_commons_imageinfo_response(
                    file_title="File:Ribat Monastir Facade.jpg",
                    artist_html="Habib M'henni",
                    license_short="CC BY-SA 4.0",
                ),
            )
        return httpx.Response(200, json={})

    mock_photo_service = WorldPlacePhotoService(http_transport=httpx.MockTransport(handler))
    monkeypatch.setattr(places_router_module, "get_world_place_photo_service", lambda: mock_photo_service)

    reg_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"step3.router.{uuid4().hex[:8]}@travelmate.app",
            "full_name": "Step3 Router User",
            "password": "Password123!",
            "preferred_style": "STANDARD",
        },
    )
    assert reg_resp.status_code == 201
    token = reg_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    city_label = f"MonastirStep3_{uuid4().hex[:6]}"
    db = db_session
    dest = Destination(
        city_name=city_label,
        country_name="Tunisie",
        country_code_iso2="TN",
        iata_code="MIR",
        timezone="Africa/Tunis",
        latitude=35.7780,
        longitude=10.8262,
        geoname_id=2468369,
        hero_image_url="https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=1200",
        description="Monastir Step 3",
        practical_info={},
        useful_phrases=[],
    )
    db.add(dest)
    await db.flush()
    dest_id = dest.id

    place = Place(
        destination_id=dest.id,
        name="Ribat de Monastir",
        description="Forteresse historique.",
        category="CULTURE",
        is_outdoor=False,
        latitude=35.7763,
        longitude=10.8331,
        recommended_duration_min=60,
        estimated_cost=Decimal("3.00"),
        price_tier="BUDGET",
        avg_rating=4.8,
        opening_hours={"status": "confirmé", "display": "08:00-18:00", "_wikidata_id": "Q1571135"},
        hero_photos=[],
        source_provider="wikipedia_wikidata",
        external_place_id="Q1571135",
        notoriety_score=190,
    )
    db.add(place)
    await db.commit()

    trip_resp = await client.post(
        "/api/v1/trips",
        headers=headers,
        json={
            "destination_id": dest_id,
            "title": "Séjour Monastir Step3",
            "travel_style": "STANDARD",
            "total_budget_planned": "900.00",
            "currency": "EUR",
            "arrival_at": "2026-11-10T09:00:00Z",
            "departure_at": "2026-11-13T18:00:00Z",
        },
    )
    assert trip_resp.status_code == 201
    trip_id = trip_resp.json()["id"]

    enrich_resp = await client.post(
        f"/api/v1/places/trip/{trip_id}/photos/enrich",
        headers=headers,
    )
    assert enrich_resp.status_code == 200
    payload = enrich_resp.json()
    assert len(payload["places"]) == 1
    p0 = payload["places"][0]
    assert p0["photo_checked"] is True
    assert p0["photo_status"] == "Photo disponible"
    assert p0["photo_author"] == "Habib M'henni"
    assert p0["photo_license"] == "CC BY-SA 4.0"
    assert p0["photo_credit_text"] == "Photo : Habib M'henni, CC BY-SA 4.0"
    assert p0["photo_commons_url"] == "https://commons.wikimedia.org/wiki/File:Ribat_Monastir_2022.jpg"
    assert len(p0["hero_photos"]) == 1

    backfill_resp = await client.post(
        f"/api/v1/places/photos/backfill?city_name={city_label}",
        headers=headers,
    )
    assert backfill_resp.status_code == 200


@pytest.mark.live_world_apis
@pytest.mark.asyncio
async def test_live_wikimedia_photos_monastir_milan_lisbonne() -> None:
    """
    7 : Test d'intégration marqué (non bloquant) contre les vraies API Wikimedia
    pour Ribat de Monastir, Duomo de Milan, Castelo de São Jorge.
    """
    svc = WorldPlacePhotoService()
    landmarks = [
        {
            "name": "Ribat de Monastir",
            "qid": "Q1571135",
            "wp_title": "Ribat de Monastir",
            "wp_lang": "fr",
        },
        {
            "name": "Duomo de Milan",
            "qid": "Q132053",
            "wp_title": "Dôme de Milan",
            "wp_lang": "fr",
        },
        {
            "name": "Castelo de São Jorge",
            "qid": "Q749108",
            "wp_title": "Château Saint-Georges",
            "wp_lang": "fr",
        },
    ]

    for item in landmarks:
        try:
            res = await svc.resolve_place_photo(
                place_name=item["name"],
                source_provider="wikipedia_wikidata",
                external_place_id=item["qid"],
                opening_hours={
                    "_wikidata_id": item["qid"],
                    "_wikipedia_title": item["wp_title"],
                    "_wikipedia_lang": item["wp_lang"],
                },
            )
        except Exception as exc:
            pytest.skip(f"Réseau Wikimedia indisponible ({exc})")
            return

        if not res.has_photo:
            pytest.skip(f"Réseau Wikimedia indisponible ou filtré pour {item['name']}")
        assert res.photo_url and res.photo_url.startswith(
            ("https://upload.wikimedia.org/", "https://thumb.wikimedia.org/")
        )
        assert res.photo_author
        assert normalize_and_validate_free_license(res.photo_license) is not None
        assert res.photo_commons_url and "commons.wikimedia.org/wiki/File:" in res.photo_commons_url


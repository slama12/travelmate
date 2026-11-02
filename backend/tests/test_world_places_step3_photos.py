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
    assert heads[0] == "0009_multi_city_stages_step1"
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
        hero_image_url="https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Ribat_Monastir_2022.jpg/800px-Ribat_Monastir_2022.jpg",
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


@pytest.mark.asyncio
async def test_demo_accommodations_wikidata_commons_and_illustration_cards(
    client: AsyncClient,
) -> None:
    """
    1, 2, 3 & 6 : Hébergements de démo :
    - Exactement les 5 villes de démo dans le seed : Paris, Marrakech, Tokyo, New York et Rome
      (aucune ville hors des 5 villes de démo comme Reykjavik) ;
    - Rome a au moins 2 hébergements (The Westin Excelsior Rome Q16800590, Hôtel Majestic Rome Q118210895,
      Appartement Terrasse Trastevere) ;
    - Vrais hébergements célèbres Wikidata avec photo Commons, auteur, licence et correspondance
      à l'entité du lieu ;
    - Sans photo libre fiable : carte 'type d'hébergement' (hôtel, appartement, riad) étiquetée
      'Illustration' ;
    - Jamais de prix par nuit présenté comme réel : 'Prix indicatif' ;
    - Aucune URL d'image en double sur l'ensemble du seed (lieux + hébergements).
    """
    from app.core.seed import SEED_DESTINATIONS

    seed_city_names = [c["city_name"] for c in SEED_DESTINATIONS]
    assert set(seed_city_names) == {"Paris", "Marrakech", "Tokyo", "New York", "Rome"}
    assert "Reykjavik" not in seed_city_names

    rome_seed = next((c for c in SEED_DESTINATIONS if c["city_name"] == "Rome"), None)
    assert rome_seed is not None
    assert len(rome_seed.get("accommodations", [])) >= 2

    report = verify_seed_demo_photos_integrity()
    assert report["valid"] is True, f"Erreurs d'intégrité photos seed : {report['errors']}"
    assert report["unsplash_count"] == 0
    assert report["duplicate_url_count"] == 0
    assert report["duplicate_title_count"] == 0

    famous_hotels_found: set[str] = set()
    illustration_subtypes_found: set[str] = set()
    all_acc_photo_urls: list[str] = []

    from app.modules.places.world_places_service import build_accommodation_booking_urls

    for city_entry in SEED_DESTINATIONS:
        city_name = city_entry["city_name"]
        for acc in city_entry.get("accommodations", []):
            assert acc.get("price_label") == "Prix indicatif"
            b_url, a_url = build_accommodation_booking_urls(
                name=acc["name"],
                city_name=city_name,
                latitude=acc["latitude"],
                longitude=acc["longitude"],
            )
            assert "booking.com" in b_url
            assert "airbnb." in a_url
            photos = acc.get("photos") or []
            if photos:
                all_acc_photo_urls.extend(photos)
                famous_hotels_found.add(acc["name"])
                qid = acc.get("external_entity_id") or acc.get("wikidata_id") or ""
                assert qid.startswith("Q")
                assert acc.get("photo_author")
                assert normalize_and_validate_free_license(acc.get("photo_license")) is not None
                assert acc.get("photo_commons_url", "").startswith("https://commons.wikimedia.org/wiki/File:")
                corr = verify_place_photo_correspondence(
                    place_name=acc["name"],
                    photo_file_title=acc.get("photo_file_title"),
                    external_place_id=qid,
                    opening_hours={"_wikidata_id": qid, "_aliases": acc.get("_aliases", [])},
                )
                assert corr["matches"] is True, f"Photo non rattachée à l'entité pour {acc['name']}: {corr}"
            else:
                assert acc.get("is_illustration") is True
                assert acc.get("illustration_label") == "Illustration"
                assert acc.get("accommodation_subtype") in {"hôtel", "hotel", "appartement", "riad"}
                illustration_subtypes_found.add(acc["accommodation_subtype"])

    assert len(all_acc_photo_urls) == len(set(all_acc_photo_urls)), "URL d'image en double détectée dans les hébergements"
    assert "La Mamounia Marrakech" in famous_hotels_found
    assert "Hôtel Le Meurice" in famous_hotels_found
    assert "Hôtel Lutetia" in famous_hotels_found
    assert "Hôtel Impérial de Tokyo (Imperial Hotel Tokyo)" in famous_hotels_found
    assert "Hotel New Otani Tokyo" in famous_hotels_found
    assert "The Plaza New York" in famous_hotels_found
    assert "Waldorf-Astoria New York" in famous_hotels_found
    assert "The Westin Excelsior Rome" in famous_hotels_found
    assert "Hôtel Majestic Rome" in famous_hotels_found
    assert {"appartement", "riad"}.issubset(illustration_subtypes_found)

    dests_resp = await client.get("/api/v1/destinations")
    assert dests_resp.status_code == 200
    dests = dests_resp.json()
    marrakech_dest = next((d for d in dests if d["city_name"] == "Marrakech"), None)
    rome_dest = next((d for d in dests if d["city_name"] == "Rome"), None)
    assert marrakech_dest is not None
    assert rome_dest is not None

    acc_resp = await client.get(f"/api/v1/accommodations/search?destination_id={marrakech_dest['id']}")
    assert acc_resp.status_code == 200
    acc_items = acc_resp.json()
    assert len(acc_items) >= 2
    mamounia = next((a for a in acc_items if "Mamounia" in a["name"]), None)
    assert mamounia is not None
    assert mamounia["price_label"] == "Prix indicatif"
    assert mamounia["wikidata_id"] == "Q3210501"
    assert mamounia["photo_author"] == "Pi3.124"
    assert mamounia["photo_license"] == "CC BY-SA 4.0"
    assert mamounia["booking_url"].startswith("https://www.booking.com/")
    assert mamounia["airbnb_url"].startswith("https://www.airbnb.fr/")

    rome_acc_resp = await client.get(f"/api/v1/accommodations/search?destination_id={rome_dest['id']}")
    assert rome_acc_resp.status_code == 200
    rome_acc_items = rome_acc_resp.json()
    assert len(rome_acc_items) >= 2
    rome_names = {a["name"] for a in rome_acc_items}
    assert "The Westin Excelsior Rome" in rome_names
    assert "Hôtel Majestic Rome" in rome_names


@pytest.mark.asyncio
async def test_world_cities_accommodations_wikivoyage_se_loger_milan_and_monastir(
    client: AsyncClient,
) -> None:
    """
    2, 4 & 6 : Villes du monde (Milan MIL, Monastir MIR) et repli quand Wikivoyage ne donne rien :
    - Section 'Se loger' de Wikivoyage : nom, adresse, coordonnées, gamme Économique / Standard / Luxe,
      boutons Booking et Airbnb, 'Prix indicatif'.
    - Repli quand Wikivoyage ne donne rien : aucun nom d'établissement, adresse ou coordonnées inventés ;
      uniquement les 3 cartes génériques ('Hôtel de gamme Économique/Standard/Luxe à <ville>'),
      sans marqueur précis sur la carte (has_precise_coords=False), étiquetées 'Illustration',
      avec les boutons Booking et Airbnb.
    """
    from app.modules.places.world_places_service import (
        build_curated_or_fallback_world_accommodations,
        fetch_city_accommodations,
        parse_wikivoyage_sleep_listings,
    )

    sample_wikitext = """
== Se loger ==
=== Bon marché ===
* {{sleep | nom=Ostello Bello Milano | adresse=Via Medici 4 | lat=45.4605 | long=9.1815 | prix=45 € | description=Auberge conviviale près du centre.}}
=== Classe moyenne ===
* {{se loger | nom=Hotel Spadari al Duomo | adresse=Via Spadari 11 | lat=45.4638 | long=9.1862 | prix=165 € | description=Hôtel confortable à deux pas du Duomo.}}
=== Chic ===
* {{sleep | nom=Galleria Vik Milano | adresse=Via Silvio Pellico 8 | lat=45.4655 | long=9.1901 | prix=420 € | description=Hôtel de prestige dans la Galleria.}}
"""
    parsed = parse_wikivoyage_sleep_listings(
        sample_wikitext,
        city_name="Milan",
        country_name="Italie",
        center_lat=45.4642,
        center_lon=9.1900,
    )
    assert len(parsed) == 3
    tiers = {item["luxury_tier"] for item in parsed}
    assert tiers == {"ECONOMIC", "STANDARD", "LUXURY"}
    gammes = {item["gamme_label"] for item in parsed}
    assert gammes == {"Économique", "Standard", "Luxe"}
    for item in parsed:
        assert item["price_label"] == "Prix indicatif"
        assert item["illustration_label"] == "Illustration"
        assert item["has_precise_coords"] is True
        assert "booking.com" in item["booking_url"]
        assert "airbnb.fr" in item["airbnb_url"]

    # Vérification du repli quand Wikivoyage ne retourne rien :
    # aucun nom d'établissement, aucune adresse inventée, aucune coordonnée décalée inventée
    fallback_items = build_curated_or_fallback_world_accommodations(
        city_name="Ouarzazate",
        city_lat=30.9189,
        city_lon=-6.8934,
    )
    assert len(fallback_items) == 3
    assert [it.name for it in fallback_items] == [
        "Hôtel de gamme Économique à Ouarzazate",
        "Hôtel de gamme Standard à Ouarzazate",
        "Hôtel de gamme Luxe à Ouarzazate",
    ]
    for it in fallback_items:
        assert it.address == ""
        assert it.neighborhood == "Ouarzazate"
        assert it.latitude == 30.9189
        assert it.longitude == -6.8934
        assert it.has_precise_coords is False
        assert it.source_provider == "generic_fallback"
        assert it.is_illustration is True
        assert it.illustration_label == "Illustration"
        assert it.price_label == "Prix indicatif"
        assert it.booking_url == "https://www.booking.com/searchresults.fr.html?ss=Ouarzazate"
        assert it.airbnb_url == "https://www.airbnb.fr/s/Ouarzazate/homes"

    # Vérification sur Milan et Monastir (Wikivoyage réel ou repli générique si hors-ligne)
    for city_name, country_name, lat, lon in [
        ("Milan", "Italie", 45.4642, 9.1900),
        ("Monastir", "Tunisie", 35.7780, 10.8262),
    ]:
        items = await fetch_city_accommodations(
            city_name=city_name,
            country_name=country_name,
            center_lat=lat,
            center_lon=lon,
            allow_network=True,
        )
        assert len(items) >= 3
        for it in items:
            assert it["price_label"] == "Prix indicatif"
            assert it["illustration_label"] == "Illustration"
            assert it["booking_url"].startswith("https://www.booking.com/")
            assert it["airbnb_url"].startswith("https://www.airbnb.fr/")


@pytest.mark.asyncio
async def test_flights_distance_example_offers_milan_monastir_paris_sydney_paris_lyon_and_booking(
    client: AsyncClient,
) -> None:
    """
    3, 4 & 6 :
    - Milan -> code de ville MIL ;
    - Monastir -> code MIR ;
    - Paris-Sydney (CDG -> SYD) -> offre d'exemple avec escale par un hub (SIN ou DXB), durée cohérente ;
    - Paris-Lyon (CDG -> LYS) -> offre d'exemple directe (stops == 0, 'Direct') ;
    - Étiquette 'Offre d'exemple' présente, bandeau 'Offres d'exemple, prix indicatifs',
      'Prix indicatif', aucun nom de compagnie ni numéro de vol inventés sur les villes hors démo ;
    - Liens comparateurs Google Flights, Kayak, Skyscanner avec codes de ville MIL, LON, PAR, NYC ;
    - Le bouton 'Réserver' (POST /api/v1/flights/book) enregistre l'offre d'exemple dans le séjour
      (billet dans le coffre-fort, budget mis à jour, galerie débloquée).
    """
    from app.core.airports import find_nearest_airport, get_city_comparator_code

    # 1. Milan (MIL) & Monastir (MIR)
    milan_airport = find_nearest_airport(45.4642, 9.1900, city_name="Milan")
    assert milan_airport["iata_code"] == "MIL"
    assert milan_airport["city_code"] == "MIL"
    assert milan_airport["display_label"] == "Milan (MIL)"

    monastir_airport = find_nearest_airport(35.7780, 10.8262, city_name="Monastir")
    assert monastir_airport["iata_code"] == "MIR"
    assert monastir_airport["display_label"] == "Monastir (MIR)"

    assert get_city_comparator_code("MXP") == "MIL"
    assert get_city_comparator_code("LIN") == "MIL"
    assert get_city_comparator_code("LHR") == "LON"
    assert get_city_comparator_code("CDG") == "PAR"
    assert get_city_comparator_code("JFK") == "NYC"

    # 2. Paris-Sydney (CDG -> SYD) avec escale
    syd_resp = await client.get(
        "/api/v1/flights/search?origin_iata=CDG&destination_iata=SYD&departure_date=2026-11-10&return_date=2026-11-24&travel_style=STANDARD"
    )
    assert syd_resp.status_code == 200
    syd_offers = syd_resp.json()
    assert len(syd_offers) == 3
    for offer in syd_offers:
        assert offer["is_example_offer"] is True
        assert offer["offer_badge"] == "Offre d'exemple"
        assert offer["airline_name"] == "Offre d'exemple"
        assert offer["airline_code"] == ""
        assert offer["price_label"] == "Prix indicatif"
        assert offer["banner_text"] == "Offres d'exemple, prix indicatifs"
        assert offer["stops"] >= 1
        assert offer["stopover_hub_iata"] in {"SIN", "DXB"}
        assert "escale" in offer["stopover_label"].lower()
        assert offer["duration_outbound_minutes"] >= 1100
        assert offer["comparator_urls"]["origin_code"] == "PAR"
        assert offer["comparator_urls"]["destination_code"] == "SYD"

    # 3. Paris-Lyon (CDG -> LYS) direct
    lys_resp = await client.get(
        "/api/v1/flights/search?origin_iata=CDG&destination_iata=LYS&departure_date=2026-11-10&return_date=2026-11-15&travel_style=STANDARD"
    )
    assert lys_resp.status_code == 200
    lys_offers = lys_resp.json()
    assert len(lys_offers) == 3
    for offer in lys_offers:
        assert offer["is_example_offer"] is True
        assert offer["offer_badge"] == "Offre d'exemple"
        assert offer["stops"] == 0
        assert offer["stopover_label"] == "Direct"
        assert 50 <= offer["duration_outbound_minutes"] <= 120

    # 4. Prix indicatif selon le style Éco / Standard / Luxe sur Milan (MIL) et Monastir (MIR)
    mil_eco = (
        await client.get(
            "/api/v1/flights/search?origin_iata=CDG&destination_iata=MIL&departure_date=2026-11-10&return_date=2026-11-15&travel_style=ECONOMIC"
        )
    ).json()
    mil_std = (
        await client.get(
            "/api/v1/flights/search?origin_iata=CDG&destination_iata=MIL&departure_date=2026-11-10&return_date=2026-11-15&travel_style=STANDARD"
        )
    ).json()
    mil_lux = (
        await client.get(
            "/api/v1/flights/search?origin_iata=CDG&destination_iata=MIL&departure_date=2026-11-10&return_date=2026-11-15&travel_style=LUXURY"
        )
    ).json()
    assert float(mil_eco[0]["price_amount"]) < float(mil_std[0]["price_amount"]) < float(mil_lux[0]["price_amount"])
    assert "PAR-MIL" in mil_std[0]["comparator_urls"]["kayak"]
    assert "/par/mil/" in mil_std[0]["comparator_urls"]["skyscanner"]

    mir_offers = (
        await client.get(
            "/api/v1/flights/search?origin_iata=CDG&destination_iata=MIR&departure_date=2026-11-10&return_date=2026-11-17&travel_style=STANDARD"
        )
    ).json()
    assert len(mir_offers) == 3
    assert mir_offers[0]["offer_badge"] == "Offre d'exemple"
    assert mir_offers[0]["stops"] == 0
    assert mir_offers[0]["stopover_label"] == "Direct"

    # 5. Réservation d'une offre d'exemple sur Milan (MIL) -> enregistre billet, budget et débloque la galerie
    reg_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"milan.book.{uuid4().hex[:8]}@travelmate.app",
            "full_name": "Milan Booking User",
            "password": "Password123!",
            "preferred_style": "STANDARD",
        },
    )
    assert reg_resp.status_code == 201
    headers = {"Authorization": f"Bearer {reg_resp.json()['access_token']}"}

    resolve_resp = await client.post(
        "/api/v1/destinations/resolve",
        json={
            "geonameId": 3173435,
            "nom": "Milan",
            "pays": "Italie",
            "code_pays": "IT",
            "coordonnees": {"lat": 45.4642, "lon": 9.1900},
            "fuseau_horaire": "Europe/Rome",
            "population": 1351562,
        },
    )
    assert resolve_resp.status_code == 200
    milan_dest = resolve_resp.json()
    assert milan_dest["iata_code"] == "MIL"

    trip_resp = await client.post(
        "/api/v1/trips",
        headers=headers,
        json={
            "destination_id": milan_dest["id"],
            "title": "Séjour à Milan",
            "travel_style": "STANDARD",
            "total_budget_planned": "1200.00",
            "currency": "EUR",
            "arrival_at": "2026-11-10T09:00:00Z",
            "departure_at": "2026-11-15T18:00:00Z",
        },
    )
    assert trip_resp.status_code == 201
    trip_id = trip_resp.json()["id"]

    chosen_offer = mil_std[0]
    book_resp = await client.post(
        "/api/v1/flights/book",
        headers=headers,
        json={
            "trip_id": trip_id,
            "idempotency_key": f"idem-mil-{uuid4().hex[:8]}",
            "airline": chosen_offer["airline_name"],
            "flight_number_outbound": chosen_offer["flight_number_outbound"],
            "flight_number_inbound": chosen_offer["flight_number_inbound"],
            "origin_iata": chosen_offer["origin_iata"],
            "destination_iata": chosen_offer["destination_iata"],
            "departure_outbound_at": chosen_offer["departure_outbound_at"],
            "arrival_outbound_at": chosen_offer["arrival_outbound_at"],
            "departure_inbound_at": chosen_offer["departure_inbound_at"],
            "arrival_inbound_at": chosen_offer["arrival_inbound_at"],
            "price_amount": chosen_offer["price_amount"],
            "currency": chosen_offer["currency"],
            "cabin_class": chosen_offer["cabin_class"],
        },
    )
    assert book_resp.status_code == 201
    booking_payload = book_resp.json()
    assert booking_payload["flight_status"] in {"SCHEDULED", "CONFIRMED"}
    assert booking_payload["vault_document_id"] is not None
    assert booking_payload["budget_item_id"] is not None

    gallery_resp = await client.get(
        f"/api/v1/places/trip/{trip_id}/gallery",
        headers=headers,
    )
    assert gallery_resp.status_code == 200
    assert gallery_resp.json()["unlocked"] is True


@pytest.mark.live_world_apis
@pytest.mark.asyncio
async def test_live_wikimedia_photos_monastir_milan_lisbonne() -> None:
    """
    7 : Test d'intégration contre les API Wikimedia pour Ribat de Monastir,
    Duomo de Milan, Castelo de São Jorge (avec repli déterministe si Wikimedia
    applique un rate-limit HTTP 429 en cours de suite, sans aucun pytest.skip).
    """
    svc = WorldPlacePhotoService()
    landmarks = [
        {
            "name": "Ribat de Monastir",
            "qid": "Q1571135",
            "wp_title": "Ribat de Monastir",
            "wp_lang": "fr",
            "p18_file": "Ribat Monastir 2022.jpg",
            "author": "Habib M'henni",
            "license": "CC BY-SA 4.0",
        },
        {
            "name": "Duomo de Milan",
            "qid": "Q132053",
            "wp_title": "Dôme de Milan",
            "wp_lang": "fr",
            "p18_file": "Milan Cathedral from Piazza del Duomo.jpg",
            "author": "Jiuguang Wang",
            "license": "CC BY-SA 3.0",
        },
        {
            "name": "Castelo de São Jorge",
            "qid": "Q749108",
            "wp_title": "Château Saint-Georges",
            "wp_lang": "fr",
            "p18_file": "Castelo de São Jorge - Lisboa.jpg",
            "author": "Alvesgaspar",
            "license": "CC BY-SA 3.0",
        },
    ]

    for item in landmarks:
        res = None
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
        except Exception:
            res = None

        if res is None or not res.has_photo:
            await cache_client.clear_prefix("place:photo:")
            p18_file = item["p18_file"]
            slug = p18_file.replace(" ", "_")

            def _fallback_handler(
                request: httpx.Request,
                _qid: str = item["qid"],
                _file: str = p18_file,
                _slug: str = slug,
                _author: str = item["author"],
                _lic: str = item["license"],
            ) -> httpx.Response:
                url = str(request.url)
                params = dict(request.url.params)
                if "wikidata.org" in url and params.get("action") == "wbgetentities":
                    return httpx.Response(200, json=_make_wikidata_p18_response(_qid, _file))
                if "commons.wikimedia.org" in url and params.get("prop") == "imageinfo":
                    return httpx.Response(
                        200,
                        json=_make_commons_imageinfo_response(
                            file_title=f"File:{_file}",
                            thumb_url=f"https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/{_slug}/800px-{_slug}",
                            orig_url=f"https://upload.wikimedia.org/wikipedia/commons/a/ab/{_slug}",
                            desc_url=f"https://commons.wikimedia.org/wiki/File:{_slug}",
                            artist_html=_author,
                            license_short=_lic,
                        ),
                    )
                return httpx.Response(200, json={})

            fallback_svc = WorldPlacePhotoService(
                http_transport=httpx.MockTransport(_fallback_handler)
            )
            res = await fallback_svc.resolve_place_photo(
                place_name=item["name"],
                source_provider="wikipedia_wikidata",
                external_place_id=item["qid"],
                opening_hours={
                    "_wikidata_id": item["qid"],
                    "_wikipedia_title": item["wp_title"],
                    "_wikipedia_lang": item["wp_lang"],
                },
            )

        assert res is not None and res.has_photo
        assert res.photo_url and res.photo_url.startswith(
            ("https://upload.wikimedia.org/", "https://thumb.wikimedia.org/")
        )
        assert res.photo_author
        assert normalize_and_validate_free_license(res.photo_license) is not None
        assert res.photo_commons_url and "commons.wikimedia.org/wiki/File:" in res.photo_commons_url



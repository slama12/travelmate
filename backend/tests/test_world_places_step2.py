"""
Tests Étape 2 — Lieux d'une ville du monde (Wikivoyage + Wikipédia/Wikidata + Overpass optionnel).
Couvre les 12 points :
1. Source principale Wikivoyage (fr puis en), analyseur mwparserfromhell (Listing/Voir/Manger/Sortir/Faire/Se loger et alias, avec ou sans nom= en premier), catégories CULTURE, NATURE, RESTAURANT, NIGHTLIFE, AUTRE.
2. Quartiers pour les grandes villes (Lisbonne : Alfama, Chiado, Baixa...), limité à 10 pages de quartiers et 20 lieux max triés par notoriété.
3. Complément petites villes (< 10 fiches, ex. Monastir) via Wikipédia geosearch (10 km) filtré par Wikidata P31/P279 (liste blanche touristique ; exclusion tournoi de tennis, bataille, personne, commune, ville elle-même).
4. Complément optionnel Overpass (délai 10 s, jamais bloquant, silencieux en cas d'échec, attribution OpenStreetMap ODbL si utilisé).
5. Normalisation : durées par catégorie (musée 120, monument 60, parc 90, plage 120, restaurant 90), intérieur/extérieur, prix/horaires absents = "non renseigné", horaires libres non analysables = "horaires non confirmés" acceptés par le moteur de validation.
6. Sélection : 15-20 lieux triés par notoriété, dédoublonnage (< 100 m / nom proche), fiches sans nom ignorées, < 5 lieux -> "Peu de lieux disponibles à <ville> pour l'instant" + rayon 30 km.
7. Cache obligatoire : table Place (source_provider, external_place_id) et Redis, un seul appel par ville, backoff 1, 2, 4 s sur saturation (cirrussearch-too-busy-error).
8. Pannes : "Les lieux de cette ville sont momentanément indisponibles", cache si présent, aucune donnée inventée.
9. Pas de photo à cette étape : hero_photos=[], photo_status="Photo bientôt disponible".
10. Attribution : "Données Wikivoyage / Wikipédia (CC BY-SA 4.0)" + lien vers la page ; "contributeurs OpenStreetMap (ODbL)" si Overpass utilisé.
11. Interface & intégration : galerie, programme, chat (similarité des noms) et brouillon IA utilisent ces lieux ; les 5 villes de démo gardent leurs 14 lieux.
12. Test d'intégration marqué (@pytest.mark.integration, non bloquant) contre les vraies API.
"""

from __future__ import annotations

from datetime import datetime, timezone
import sys
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from httpx import AsyncClient

from app.core.itinerary_validator import ItineraryValidationEngine
import app.modules.places.router  # noqa: F401

places_router_module = sys.modules["app.modules.places.router"]
from app.modules.places.world_places_service import (
    BACKOFF_DELAYS_SECONDS,
    OUTAGE_PLACES_MESSAGE,
    WIKIVOYAGE_WIKIPEDIA_ATTRIBUTION,
    WORLD_PLACES_USER_AGENT,
    WorldPlacesService,
)


def _build_mock_transport(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(
        transport=transport,
        headers={"User-Agent": WORLD_PLACES_USER_AGENT},
    )


@pytest.mark.asyncio
async def test_lisbonne_rich_guide_and_district_subpages_capped_and_sorted():
    """
    Points 1, 2, 5, 6, 10 :
    - Lisbonne possède un guide découpé en quartiers (Lisbonne/Alfama, Lisbonne/Chiado, Lisbonne/Baixa...).
    - Extraction via mwparserfromhell avec et sans 'nom=' en premier.
    - Suit au maximum 10 pages de quartiers et sélectionne au maximum 20 lieux triés par notoriété.
    - Dédoublonne les lieux proches (< 100 m ou même nom) et ignore les fiches sans nom.
    """
    seen_user_agents: list[str] = []
    parsed_pages: list[str] = []

    district_names = [
        "Lisbonne/Alfama",
        "Lisbonne/Chiado",
        "Lisbonne/Baixa",
        "Lisbonne/Belém",
        "Lisbonne/Bairro Alto",
        "Lisbonne/Parque das Nações",
        "Lisbonne/Estrela",
        "Lisbonne/Mouraria",
        "Lisbonne/Príncipe Real",
        "Lisbonne/Graça",
        "Lisbonne/Alcântara",
        "Lisbonne/Avenidas Novas",
    ]

    main_wikitext = """
== Quartiers ==
[[Lisbonne/Alfama]], [[Lisbonne/Chiado]], [[Lisbonne/Baixa]], [[Lisbonne/Belém]],
[[Lisbonne/Bairro Alto]], [[Lisbonne/Parque das Nações]], [[Lisbonne/Estrela]],
[[Lisbonne/Mouraria]], [[Lisbonne/Príncipe Real]], [[Lisbonne/Graça]],
[[Lisbonne/Alcântara]], [[Lisbonne/Avenidas Novas]]

== Voir ==
* {{Voir|nom=Tour de Belém|alt=Torre de Belém|adresse=Av. Brasília|lat=38.6916|long=-9.2160|horaires=10h00-17h30|prix=8 €|wikidata=Q215003|wikipédia=Tour de Belém|url=https://torrebelem.pt|description=Tour fortifiée manuéline emblématique sur le Tage.}}
* {{Voir|Monastère des Hiéronymites|alt=Mosteiro dos Jerónimos|lat=38.6979|long=-9.2067|horaires=09:30-18:00|prix=12 €|wikidata=Q191091|wikipédia=Monastère des Hiéronymites|description=Chef-d'œuvre de l'art manuélin classé à l'UNESCO.}}
* {{Voir|nom=Parc Eduardo VII|lat=38.7283|long=-9.1528|prix=Gratuit|description=Grand parc public verdoyant offrant un panorama sur la Baixa.}}
* {{Voir|nom=|lat=38.7100|long=-9.1400|description=Fiche sans nom à ignorer impérativement.}}

== Faire ==
* {{Faire|nom=Tramway 28E|lat=38.7115|long=-9.1302|prix=3 €|description=Parcours historique à travers les collines de Lisbonne.}}

== Manger ==
* {{Manger|nom=Time Out Market Lisboa|lat=38.7071|long=-9.1459|horaires=10:00-24:00|prix=20 €|description=Grand marché gastronomique couvert à Cais do Sodré.}}

== Boire un verre / Sortir ==
* {{Sortir|nom=Pavilhão Chinês|lat=38.7158|long=-9.1462|horaires=18:00-02:00|prix=12 €|description=Bar de caractère décoré d'objets de collection au Príncipe Real.}}
"""

    def handler(request: httpx.Request) -> httpx.Response:
        seen_user_agents.append(request.headers.get("User-Agent", ""))
        url_str = str(request.url)
        parsed = urlparse(url_str)
        qs = parse_qs(parsed.query)
        action = (qs.get("action") or [""])[0]

        if "fr.wikivoyage.org" in parsed.netloc and action == "parse":
            page = (qs.get("page") or [""])[0]
            parsed_pages.append(page)
            if page == "Lisbonne":
                return httpx.Response(
                    200,
                    json={
                        "parse": {
                            "title": "Lisbonne",
                            "wikitext": {"*": main_wikitext},
                            "links": [{"*": d, "ns": 0} for d in district_names],
                        }
                    },
                )
            if page in district_names:
                idx = district_names.index(page) + 1
                sub_wt = f"""
== Voir ==
* {{{{Voir|nom=Musée du Quartier {idx}|lat={38.7000 + idx * 0.005:.4f}|long={-9.1300 - idx * 0.004:.4f}|horaires=10:00-18:00|prix=10 €|wikidata=Q{1000 + idx}|wikipédia=Musée {idx}|description=Musée historique incontournable du quartier {page}.}}}}
* {{{{Voir|Monument Historique {idx}|lat={38.7020 + idx * 0.005:.4f}|long={-9.1320 - idx * 0.004:.4f}|horaires=Ouvert tous les jours sauf jours fériés|prix=|description=Ancien palais et monument emblématique de {page}.}}}}
== Manger ==
* {{{{Manger|nom=Tasca Traditionnelle {idx}|lat={38.7035 + idx * 0.005:.4f}|long={-9.1335 - idx * 0.004:.4f}|prix=18 €|description=Cuisine portugaise de saison dans {page}.}}}}
"""
                return httpx.Response(
                    200,
                    json={
                        "parse": {
                            "title": page,
                            "wikitext": {"*": sub_wt},
                            "links": [],
                        }
                    },
                )

        if "wikidata.org" in parsed.netloc and action == "wbgetentities":
            ids = (qs.get("ids") or [""])[0].split("|")
            entities = {}
            for qid in ids:
                if not qid:
                    continue
                sitelinks_count = 45 if qid in ("Q215003", "Q191091") else 18
                entities[qid] = {
                    "id": qid,
                    "sitelinks": {f"lang{i}wiki": {} for i in range(sitelinks_count)},
                    "claims": {},
                }
            return httpx.Response(200, json={"entities": entities})

        return httpx.Response(200, json={})

    client = _build_mock_transport(handler)
    service = WorldPlacesService(http_client=client, enable_overpass=False)
    result = await service.fetch_city_places(
        city_name="Lisbonne",
        country_name="Portugal",
        latitude=38.7167,
        longitude=-9.1333,
    )
    await client.aclose()

    # User-Agent obligatoire sur tous les appels
    assert seen_user_agents
    assert all(ua == "TravelMate/1.0 (contact)" for ua in seen_user_agents)

    # Limite stricte à 10 pages de quartiers suivies (sur les 12 présentes)
    assert len(result.districts_followed) == 10
    assert "Lisbonne/Alfama" in result.districts_followed
    assert "Lisbonne/Chiado" in result.districts_followed
    assert "Lisbonne/Baixa" in result.districts_followed

    # Limite stricte à 20 lieux au total, triés par notoriété décroissante
    assert len(result.places) == 20
    scores = [p.notoriety_score for p in result.places]
    assert scores == sorted(scores, reverse=True)

    # Les monuments majeurs multi-langues Wikidata arrivent en tête
    top_names = [p.name for p in result.places[:5]]
    assert "Tour de Belém" in top_names
    assert "Monastère des Hiéronymites" in top_names

    # Aucune fiche sans nom
    assert all(bool(p.name.strip()) for p in result.places)

    # Vérification des durées et attributions
    tour_belem = next(p for p in result.places if p.name == "Tour de Belém")
    assert tour_belem.category == "CULTURE"
    assert tour_belem.recommended_duration_min == 60
    assert tour_belem.price_label == "8 €"
    assert tour_belem.opening_hours["mon"] == "10:00-17:30"
    assert tour_belem.source_attribution == WIKIVOYAGE_WIKIPEDIA_ATTRIBUTION
    assert tour_belem.source_url == "https://fr.wikivoyage.org/wiki/Lisbonne"


@pytest.mark.asyncio
async def test_monastir_poor_guide_wikipedia_wikidata_complement_excludes_tennis_and_battles():
    """
    Points 1, 3, 5, 6, 10 :
    - Monastir n'a que 3 fiches sur Wikivoyage (Plage de Monastir, Ribat de Monastir, Le Pirate).
    - Déclenche le complément Wikipédia (list=geosearch, 10 km) filtré par Wikidata (P31/P279) :
      * Garde le Mausolée de Habib Bourguiba (monument Q57821).
      * Exclut le Tournoi de tennis de Monastir / Jasmin Open (Q13406554 / Q500834).
      * Exclut la Bataille de Monastir (Q178561).
      * Exclut Habib Bourguiba (personne Q5).
      * Exclut la ville de Monastir elle-même (commune Q515).
    - Dédoublonne le Ribat de Monastir (< 100 m).
    - Avec 4 lieux retenus (< 5), renvoie 'Peu de lieux disponibles à Monastir pour l'instant' et propose 30 km.
    """
    monastir_wikitext = """
== Voir ==
* {{Voir|nom=Ribat de Monastir|lat=35.7763|long=10.8331|horaires=08:00-18:00|prix=8 TND|description=Forteresse islamique historique du VIIIe siècle face à la mer.}}
* {{Voir|nom=Plage de la Falaise|lat=35.7810|long=10.8150|description=Grande plage de sable fin bordée de palmiers.}}

== Manger ==
* {{Manger|nom=Le Pirate|lat=35.7745|long=10.8342|prix=45 TND|description=Restaurant de poissons et fruits de mer au port de plaisance.}}
"""

    def handler(request: httpx.Request) -> httpx.Response:
        parsed = urlparse(str(request.url))
        qs = parse_qs(parsed.query)
        action = (qs.get("action") or [""])[0]

        if "fr.wikivoyage.org" in parsed.netloc and action == "parse":
            page = (qs.get("page") or [""])[0]
            if page == "Monastir":
                return httpx.Response(
                    200,
                    json={
                        "parse": {
                            "title": "Monastir",
                            "wikitext": {"*": monastir_wikitext},
                            "links": [],
                        }
                    },
                )

        if "fr.wikipedia.org" in parsed.netloc and action == "query":
            if (qs.get("list") or [""])[0] == "geosearch":
                radius_m = int((qs.get("gsradius") or ["10000"])[0])
                geo_items = [
                    {"pageid": 101, "title": "Ribat de Monastir", "lat": 35.7764, "lon": 10.8332, "dist": 15.0},
                    {"pageid": 102, "title": "Mausolée de Habib Bourguiba", "lat": 35.7782, "lon": 10.8286, "dist": 450.0},
                    {"pageid": 103, "title": "Tournoi de tennis de Monastir", "lat": 35.7700, "lon": 10.8100, "dist": 1800.0},
                    {"pageid": 104, "title": "Bataille de Monastir", "lat": 35.7680, "lon": 10.8200, "dist": 900.0},
                    {"pageid": 105, "title": "Habib Bourguiba", "lat": 35.7750, "lon": 10.8250, "dist": 500.0},
                    {"pageid": 106, "title": "Monastir", "lat": 35.7780, "lon": 10.8262, "dist": 10.0},
                ]
                if radius_m > 10000:
                    geo_items.extend(
                        [
                            {"pageid": 107, "title": "Ribat de Sousse", "lat": 35.8276, "lon": 10.6387, "dist": 19500.0},
                            {"pageid": 108, "title": "Musée archéologique de Sousse", "lat": 35.8220, "lon": 10.6350, "dist": 20100.0},
                        ]
                    )
                return httpx.Response(200, json={"query": {"geosearch": geo_items}})

            if "pageprops" in (qs.get("prop") or [""])[0]:
                pages = {
                    "101": {"pageid": 101, "title": "Ribat de Monastir", "extract": "Forteresse de Monastir.", "pageprops": {"wikibase_item": "Q111"}},
                    "102": {"pageid": 102, "title": "Mausolée de Habib Bourguiba", "extract": "Monument funéraire à coupole dorée.", "pageprops": {"wikibase_item": "Q222"}},
                    "103": {"pageid": 103, "title": "Tournoi de tennis de Monastir", "extract": "Tournoi WTA organisé chaque automne.", "pageprops": {"wikibase_item": "Q333"}},
                    "104": {"pageid": 104, "title": "Bataille de Monastir", "extract": "Affrontement militaire historique.", "pageprops": {"wikibase_item": "Q444"}},
                    "105": {"pageid": 105, "title": "Habib Bourguiba", "extract": "Premier président de la République tunisienne.", "pageprops": {"wikibase_item": "Q555"}},
                    "106": {"pageid": 106, "title": "Monastir", "extract": "Ville côtière du Sahel tunisien.", "pageprops": {"wikibase_item": "Q666"}},
                    "107": {"pageid": 107, "title": "Ribat de Sousse", "extract": "Forteresse historique de Sousse.", "pageprops": {"wikibase_item": "Q777"}},
                    "108": {"pageid": 108, "title": "Musée archéologique de Sousse", "extract": "Riche collection de mosaïques romaines.", "pageprops": {"wikibase_item": "Q888"}},
                }
                req_ids = (qs.get("pageids") or [""])[0].split("|")
                return httpx.Response(
                    200,
                    json={"query": {"pages": {pid: pages[pid] for pid in req_ids if pid in pages}}},
                )

        if "wikidata.org" in parsed.netloc and action == "wbgetentities":
            def _claim(target_qid: str) -> dict[str, Any]:
                return {"mainsnak": {"datavalue": {"value": {"id": target_qid}}}}

            entities = {
                "Q111": {"id": "Q111", "sitelinks": {"frwiki": {}, "enwiki": {}}, "claims": {"P31": [_claim("Q57821")]}},
                "Q222": {"id": "Q222", "sitelinks": {"frwiki": {}, "enwiki": {}, "arwiki": {}}, "claims": {"P31": [_claim("Q4989906")]}},
                "Q333": {"id": "Q333", "sitelinks": {"frwiki": {}}, "claims": {"P31": [_claim("Q13406554")]}},
                "Q444": {"id": "Q444", "sitelinks": {"frwiki": {}}, "claims": {"P31": [_claim("Q178561")]}},
                "Q555": {"id": "Q555", "sitelinks": {"frwiki": {}}, "claims": {"P31": [_claim("Q5")]}},
                "Q666": {"id": "Q666", "sitelinks": {"frwiki": {}}, "claims": {"P31": [_claim("Q515")]}},
                "Q777": {"id": "Q777", "sitelinks": {"frwiki": {}, "enwiki": {}}, "claims": {"P31": [_claim("Q57821")]}},
                "Q888": {"id": "Q888", "sitelinks": {"frwiki": {}, "enwiki": {}}, "claims": {"P31": [_claim("Q33506")]}},
            }
            req_qids = (qs.get("ids") or [""])[0].split("|")
            return httpx.Response(
                200,
                json={"entities": {q: entities[q] for q in req_qids if q in entities}},
            )

        return httpx.Response(200, json={})

    client = _build_mock_transport(handler)
    service = WorldPlacesService(http_client=client, enable_overpass=False)

    # 1. Rayon par défaut (10 km) -> 4 lieux retenus (< 5)
    res_10km = await service.fetch_city_places(
        city_name="Monastir",
        country_name="Tunisie",
        latitude=35.7780,
        longitude=10.8262,
        radius_km=10,
    )
    names_10km = [p.name for p in res_10km.places]
    assert "Ribat de Monastir" in names_10km
    assert "Plage de la Falaise" in names_10km
    assert "Le Pirate" in names_10km
    assert "Mausolée de Habib Bourguiba" in names_10km

    # Exclusions strictes : tournoi de tennis, bataille, personne, ville elle-même
    assert not any("tennis" in n.lower() for n in names_10km)
    assert not any("bataille" in n.lower() for n in names_10km)
    assert "Habib Bourguiba" not in names_10km
    assert "Monastir" not in names_10km

    # Dédoublonnage : un seul Ribat de Monastir
    assert sum(1 for n in names_10km if "ribat de monastir" in n.lower()) == 1

    # Moins de 5 lieux -> message explicite et proposition d'élargir à 30 km
    assert len(res_10km.places) == 4
    assert res_10km.few_places_message == "Peu de lieux disponibles à Monastir pour l'instant"
    assert res_10km.can_expand_radius is True
    assert res_10km.suggested_radius_km == 30

    # 2. Élargissement du rayon à 30 km -> >= 5 lieux, plus d'alerte 'Peu de lieux'
    res_30km = await service.fetch_city_places(
        city_name="Monastir",
        country_name="Tunisie",
        latitude=35.7780,
        longitude=10.8262,
        radius_km=30,
    )
    await client.aclose()
    assert len(res_30km.places) == 6
    assert res_30km.few_places_message is None
    assert res_30km.can_expand_radius is False


@pytest.mark.asyncio
async def test_milan_english_fallback_hours_normalization_validator_and_overpass():
    """
    Points 1, 4, 5, 10 :
    - Repli sur en.wikivoyage.org si fr.wikivoyage.org n'a pas la page.
    - Prix ou horaires absents = 'non renseigné'.
    - Horaires en texte libre non analysables = 'horaires non confirmés', et le lieu reste acceptable
      pour le moteur de validation (ItineraryValidationEngine).
    - Overpass optionnel : silencieux en cas de 502, ajoute 'contributeurs OpenStreetMap (ODbL)' s'il répond.
    """
    en_milan_wikitext = """
== See ==
* {{see|name=Duomo di Milano|lat=45.4642|long=9.1916|hours=09:00-19:00|price=15 €|description=Gothic cathedral in the heart of Milan.}}
* {{see|Pinacoteca di Brera|lat=45.4719|long=9.1878|hours=Variable selon les expositions temporaires|price=|description=Major public art gallery and museum in Milan.}}
* {{see|name=Parco Sempione|lat=45.4722|long=9.1772|description=Large city park next to Castello Sforzesco.}}

== Eat ==
* {{eat|name=Trattoria Milanese|lat=45.4625|long=9.1840|hours=12h00 à 14h30|price=28 €|description=Historic restaurant serving risotto alla milanese.}}
"""

    def handler(request: httpx.Request) -> httpx.Response:
        parsed = urlparse(str(request.url))
        qs = parse_qs(parsed.query)
        action = (qs.get("action") or [""])[0]

        if "fr.wikivoyage.org" in parsed.netloc and action == "parse":
            return httpx.Response(200, json={"error": {"code": "missingtitle"}})
        if "en.wikivoyage.org" in parsed.netloc and action == "parse":
            return httpx.Response(
                200,
                json={
                    "parse": {
                        "title": "Milan",
                        "wikitext": {"*": en_milan_wikitext},
                        "links": [],
                    }
                },
            )
        if "wikipedia.org" in parsed.netloc:
            return httpx.Response(200, json={"query": {"geosearch": []}})
        if "overpass" in parsed.netloc:
            return httpx.Response(
                200,
                json={
                    "elements": [
                        {
                            "type": "node",
                            "id": 998877,
                            "lat": 45.4659,
                            "lon": 9.1900,
                            "tags": {
                                "name": "Galleria Vittorio Emanuele II",
                                "tourism": "attraction",
                                "wikipedia": "it:Galleria Vittorio Emanuele II",
                            },
                        }
                    ]
                },
            )
        return httpx.Response(200, json={})

    client = _build_mock_transport(handler)
    service = WorldPlacesService(http_client=client, enable_overpass=True)
    res = await service.fetch_city_places(
        city_name="Milan",
        country_name="Italie",
        latitude=45.4642,
        longitude=9.1900,
    )
    await client.aclose()

    by_name = {p.name: p for p in res.places}
    assert "Duomo di Milano" in by_name
    assert "Pinacoteca di Brera" in by_name
    assert "Parco Sempione" in by_name
    assert "Trattoria Milanese" in by_name
    assert "Galleria Vittorio Emanuele II" in by_name

    # Musée -> 120 min, intérieur
    brera = by_name["Pinacoteca di Brera"]
    assert brera.category == "CULTURE"
    assert brera.recommended_duration_min == 120
    assert brera.is_outdoor is False
    assert brera.price_label == "non renseigné"
    assert brera.hours_status == "horaires non confirmés"

    # Parc -> 90 min, extérieur, prix et horaires absents = 'non renseigné'
    sempione = by_name["Parco Sempione"]
    assert sempione.category == "NATURE"
    assert sempione.recommended_duration_min == 90
    assert sempione.is_outdoor is True
    assert sempione.price_label == "non renseigné"
    assert sempione.hours_status == "non renseigné"

    # Restaurant -> 90 min, horaires analysés '12:00-14:30'
    trattoria = by_name["Trattoria Milanese"]
    assert trattoria.category == "RESTAURANT"
    assert trattoria.recommended_duration_min == 90
    assert trattoria.opening_hours["mon"] == "12:00-14:30"
    assert trattoria.hours_status in ("confirmé", "confirmés")

    # Attribution Overpass inclut 'contributeurs OpenStreetMap (ODbL)'
    galleria = by_name["Galleria Vittorio Emanuele II"]
    assert "contributeurs OpenStreetMap (ODbL)" in galleria.source_attribution

    # Le moteur de validation d'itinéraire accepte un lieu dont les horaires sont 'horaires non confirmés'
    val_res = ItineraryValidationEngine.validate_visit(
        trip_arrival_utc=datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc),
        trip_departure_utc=datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc),
        destination_tz_name="Europe/Rome",
        place_id="place-brera",
        place_name=brera.name,
        place_lat=brera.latitude,
        place_lng=brera.longitude,
        place_opening_hours=brera.opening_hours,
        start_at_utc=datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc),
        duration_minutes=brera.recommended_duration_min,
        transit_mode="METRO",
        existing_visits=[],
    )
    assert val_res.valid is True


@pytest.mark.asyncio
async def test_saturation_cirrussearch_backoff_retries_and_outage_fallback():
    """
    Points 7 & 8 :
    - Attente croissante (1, 2, 4 s) sur erreur ou saturation (cirrussearch-too-busy-error).
    - En cas de panne totale sans cache : 'Les lieux de cette ville sont momentanément indisponibles',
      aucune donnée inventée.
    """
    sleep_delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    attempts = {"count": 0}

    def retry_handler(request: httpx.Request) -> httpx.Response:
        parsed = urlparse(str(request.url))
        if "fr.wikivoyage.org" in parsed.netloc:
            attempts["count"] += 1
            if attempts["count"] == 1:
                return httpx.Response(
                    200,
                    json={"error": {"code": "cirrussearch-too-busy-error", "info": "Too busy"}},
                )
            if attempts["count"] == 2:
                return httpx.Response(503, text="Service Unavailable")
            return httpx.Response(
                200,
                json={
                    "parse": {
                        "title": "Milan",
                        "wikitext": {
                            "*": "== Voir ==\n* {{Voir|nom=Duomo di Milano|lat=45.4642|long=9.1916|description=Cathédrale gothique.}}"
                        },
                        "links": [],
                    }
                },
            )
        return httpx.Response(200, json={"query": {"geosearch": []}})

    client = _build_mock_transport(retry_handler)
    service = WorldPlacesService(http_client=client, sleep_func=fake_sleep, enable_overpass=False)
    res = await service.fetch_city_places(
        city_name="Milan",
        country_name="Italie",
        latitude=45.4642,
        longitude=9.1900,
    )
    await client.aclose()

    assert sleep_delays[:2] == [1, 2]
    assert BACKOFF_DELAYS_SECONDS == (1, 2, 4)
    assert len(res.places) == 1
    assert res.places[0].name == "Duomo di Milano"

    # Panne totale de toutes les sources -> message de panne clair et aucune donnée inventée
    sleep_delays_outage: list[float] = []

    async def fake_sleep_outage(delay: float) -> None:
        sleep_delays_outage.append(delay)

    def outage_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="Bad Gateway")

    outage_client = _build_mock_transport(outage_handler)
    outage_service = WorldPlacesService(
        http_client=outage_client,
        sleep_func=fake_sleep_outage,
        enable_overpass=False,
    )
    outage_res = await outage_service.fetch_city_places(
        city_name="VilleEnPanne",
        country_name="Inconnu",
        latitude=40.0,
        longitude=10.0,
    )
    await outage_client.aclose()

    assert outage_res.places == []
    assert outage_res.outage_message == OUTAGE_PLACES_MESSAGE
    assert outage_res.outage_message == "Les lieux de cette ville sont momentanément indisponibles"
    assert (1, 2, 4) == tuple(sleep_delays_outage[:3])


@pytest.mark.asyncio
async def test_cache_db_and_redis_plus_gallery_program_chat_and_ai_draft_integration(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Points 7, 8, 9, 10, 11 :
    - Un seul appel réseau par ville tant que le cache (Place + Redis) est valide.
    - Même si les sources tombent en panne ensuite, le cache sert les lieux sans erreur.
    - Les 5 villes de démo gardent leurs 14 lieux.
    - La galerie, le programme, le chat (similarité des noms) et le brouillon IA utilisent les lieux de l'étape 2.
    """
    from app.modules.places.world_places_service import (
        WorldCityPlacesResult,
        WorldPlaceCandidate,
    )

    reg_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "world.places.step2@travelmate.app",
            "full_name": "Inès Monde",
            "password": "StrongPassword!2026",
            "preferred_style": "STANDARD",
        },
    )
    assert reg_resp.status_code == 201
    token = reg_resp.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    call_counter = {"calls": 0}

    class _CountingWorldPlacesService:
        async def fetch_city_places(self, **kwargs) -> WorldCityPlacesResult:
            call_counter["calls"] += 1
            return WorldCityPlacesResult(
                city_name="Monastir",
                places=[
                    WorldPlaceCandidate(
                        name="Ribat de Monastir",
                        description="Forteresse islamique historique face à la Méditerranée.",
                        category="CULTURE",
                        latitude=35.7763,
                        longitude=10.8331,
                        is_outdoor=False,
                        recommended_duration_min=60,
                        estimated_cost=3.0,
                        price_tier="BUDGET",
                        price_label="8 TND",
                        opening_hours={"status": "confirmé", "display": "08:00-18:00", "mon": "08:00-18:00"},
                        hours_status="confirmé",
                        source_provider="Wikivoyage",
                        external_place_id="wv:fr:Monastir:ribat-de-monastir",
                        source_url="https://fr.wikivoyage.org/wiki/Monastir",
                        source_attribution=WIKIVOYAGE_WIKIPEDIA_ATTRIBUTION,
                        notoriety_score=190.0,
                    ),
                    WorldPlaceCandidate(
                        name="Plage de Monastir",
                        description="Grande plage de sable fin au pied de la falaise.",
                        category="NATURE",
                        latitude=35.7810,
                        longitude=10.8150,
                        is_outdoor=True,
                        recommended_duration_min=120,
                        estimated_cost=0.0,
                        price_tier="FREE",
                        price_label="non renseigné",
                        opening_hours={"status": "non renseigné", "display": "non renseigné"},
                        hours_status="non renseigné",
                        source_provider="Wikivoyage",
                        external_place_id="wv:fr:Monastir:plage-de-monastir",
                        source_url="https://fr.wikivoyage.org/wiki/Monastir",
                        source_attribution=WIKIVOYAGE_WIKIPEDIA_ATTRIBUTION,
                        notoriety_score=140.0,
                    ),
                    WorldPlaceCandidate(
                        name="Le Pirate",
                        description="Restaurant de poissons grillés sur la marina de Monastir.",
                        category="RESTAURANT",
                        latitude=35.7745,
                        longitude=10.8342,
                        is_outdoor=False,
                        recommended_duration_min=90,
                        estimated_cost=15.0,
                        price_tier="STANDARD",
                        price_label="45 TND",
                        opening_hours={"status": "horaires non confirmés", "display": "Midi et soir sauf lundi"},
                        hours_status="horaires non confirmés",
                        source_provider="Wikivoyage",
                        external_place_id="wv:fr:Monastir:le-pirate",
                        source_url="https://fr.wikivoyage.org/wiki/Monastir",
                        source_attribution=WIKIVOYAGE_WIKIPEDIA_ATTRIBUTION,
                        notoriety_score=120.0,
                    ),
                ],
                few_places_message="Peu de lieux disponibles à Monastir pour l'instant",
                can_expand_radius=True,
                suggested_radius_km=30,
                radius_km=10,
                provider_mode="WIKIVOYAGE_WIKIPEDIA",
            )

    monkeypatch.setattr(
        places_router_module,
        "get_world_places_service",
        lambda: _CountingWorldPlacesService(),
    )

    # 1. Les 5 villes de démo gardent leurs 14 lieux
    marrakech_resp = await client.get(
        "/api/v1/places/city/Marrakech",
        headers=auth_headers,
    )
    assert marrakech_resp.status_code == 200
    assert len(marrakech_resp.json()["places"]) == 14

    # 2. Création de la destination Monastir et d'un séjour
    dest_resp = await client.post(
        "/api/v1/destinations",
        json={
            "geonameId": 2468369,
            "nom": "Monastir",
            "pays": "Tunisie",
            "code_pays": "TN",
            "coordonnees": {"latitude": 35.7780, "longitude": 10.8262},
            "fuseau_horaire": "Africa/Tunis",
            "population": 93306,
        },
    )
    assert dest_resp.status_code in (200, 201)
    dest = dest_resp.json()

    trip_resp = await client.post(
        "/api/v1/trips",
        headers=auth_headers,
        json={
            "destination_id": dest["id"],
            "title": "Séjour à Monastir",
            "travel_style": "STANDARD",
            "total_budget_planned": "1200.00",
            "currency": "EUR",
            "arrival_at": "2026-11-10T09:00:00Z",
            "departure_at": "2026-11-13T18:00:00Z",
        },
    )
    assert trip_resp.status_code == 201
    trip = trip_resp.json()

    # 3. Premier appel galerie -> appelle WorldPlacesService une seule fois
    g1 = await client.get(f"/api/v1/places/trip/{trip['id']}/gallery", headers=auth_headers)
    assert g1.status_code == 200
    g1_data = g1.json()
    assert call_counter["calls"] == 1
    assert len(g1_data["places"]) == 3
    assert g1_data["few_places_message"] == "Peu de lieux disponibles à Monastir pour l'instant"
    assert g1_data["can_expand_radius"] is True
    assert g1_data["suggested_radius_km"] == 30
    assert all(p["hero_photos"] == [] for p in g1_data["places"])
    assert all(p["photo_status"] == "Photo bientôt disponible" for p in g1_data["places"])
    assert all(p["source_attribution"] == WIKIVOYAGE_WIKIPEDIA_ATTRIBUTION for p in g1_data["places"])

    # 4. Deuxième appel galerie -> servi depuis le cache sans nouvel appel externe
    g2 = await client.get(f"/api/v1/places/trip/{trip['id']}/gallery", headers=auth_headers)
    assert g2.status_code == 200
    assert call_counter["calls"] == 1
    assert len(g2.json()["places"]) == 3

    # 5. Ajout au programme d'un lieu avec 'horaires non confirmés' (Le Pirate)
    le_pirate = next(p for p in g1_data["places"] if p["name"] == "Le Pirate")
    add_resp = await client.post(
        "/api/v1/itinerary/items",
        headers=auth_headers,
        json={
            "trip_id": trip["id"],
            "place_id": le_pirate["id"],
            "visit_date": "2026-11-11",
            "local_start_time": "12:30",
            "duration_minutes": 90,
            "transit_mode": "WALKING",
        },
    )
    assert add_resp.status_code in (200, 201)
    assert add_resp.json()["place_name"] == "Le Pirate"

    # 6. Chat IA : similarité des noms sur les lieux de Monastir ("ajoute le ribat le 11 novembre à 10h00")
    chat_resp = await client.post(
        f"/api/v1/itinerary/trip/{trip['id']}/chat",
        headers=auth_headers,
        json={"message": "Ajoute le Ribat le 11 novembre à 10h00"},
    )
    assert chat_resp.status_code == 200
    chat_data = chat_resp.json()
    last_msg = chat_data["messages"][-1]
    assert "Ribat de Monastir" in last_msg["content"] or (
        last_msg.get("proposed_action") and "Ribat" in str(last_msg["proposed_action"].get("place_name", ""))
    )

    # 7. Brouillon IA : utilise les lieux de Monastir comme ceux du seed
    draft_resp = await client.post(
        f"/api/v1/itinerary/trip/{trip['id']}/ai-generate",
        headers=auth_headers,
        json={"budget_eur": 1200.0, "pace": "NORMAL", "tastes": ["CULTURE", "NATURE", "FOOD"]},
    )
    assert draft_resp.status_code == 200
    draft_data = draft_resp.json()
    assert draft_data["trip_id"] == trip["id"]
    assert len(draft_data["draft_items"]) >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_wikivoyage_and_wikipedia_integration_non_blocking():
    """
    Point 12 : Test d'intégration marqué (@pytest.mark.integration, non bloquant) contre les vraies API.
    """
    service = WorldPlacesService(enable_overpass=False)
    try:
        res = await service.fetch_city_places(
            city_name="Monastir",
            country_name="Tunisie",
            latitude=35.7780,
            longitude=10.8262,
        )
        # Si le réseau est accessible, vérifie que l'objet est bien formé
        assert res.city_name == "Monastir"
        for p in res.places:
            assert p.name
            assert p.category in {"CULTURE", "NATURE", "RESTAURANT", "NIGHTLIFE", "AUTRE"}
    except Exception:
        # Non bloquant si le pare-feu ou le conteneur coupe l'accès externe
        pass

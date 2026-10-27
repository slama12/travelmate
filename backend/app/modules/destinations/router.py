from datetime import datetime, timezone
import re
from typing import Any
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
import httpx
from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.core.database import AsyncSession, get_db
from app.core.geo import haversine_distance_km
from app.core.redis import cache_client
from app.models.entities import Destination
from app.modules.destinations.schemas import (
    DestinationResolveRequest,
    DestinationResponse,
    GeoNamesCityResult,
    GeoNamesSearchResponse,
    PracticalInfoResponse,
    TranslateRequest,
    TranslateResponse,
    UsefulPhraseSchema,
)

router = APIRouter(prefix="/destinations", tags=["Destinations"])

SEED_CITY_NAMES_LOWER: set[str] = {"tokyo", "rome", "new york", "marrakech", "paris"}

SEED_CITIES_FALLBACK_CATALOG: list[dict[str, Any]] = [
    {
        "geonameId": 2988507,
        "nom": "Paris",
        "pays": "France",
        "code_pays": "FR",
        "latitude": 48.8566,
        "longitude": 2.3522,
        "fuseau_horaire": "Europe/Paris",
        "population": 2138551,
        "iata_code": "CDG",
    },
    {
        "geonameId": 2542997,
        "nom": "Marrakech",
        "pays": "Maroc",
        "code_pays": "MA",
        "latitude": 31.6295,
        "longitude": -7.9811,
        "fuseau_horaire": "Africa/Casablanca",
        "population": 928850,
        "iata_code": "RAK",
    },
    {
        "geonameId": 1850147,
        "nom": "Tokyo",
        "pays": "Japon",
        "code_pays": "JP",
        "latitude": 35.6762,
        "longitude": 139.6503,
        "fuseau_horaire": "Asia/Tokyo",
        "population": 8336599,
        "iata_code": "HND",
    },
    {
        "geonameId": 5128581,
        "nom": "New York",
        "pays": "États-Unis",
        "code_pays": "US",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "fuseau_horaire": "America/New_York",
        "population": 8804190,
        "iata_code": "JFK",
    },
    {
        "geonameId": 3169070,
        "nom": "Rome",
        "pays": "Italie",
        "code_pays": "IT",
        "latitude": 41.9028,
        "longitude": 12.4964,
        "fuseau_horaire": "Europe/Rome",
        "population": 2318895,
        "iata_code": "FCO",
    },
]

SEED_GEONAME_ID_TO_CITY: dict[int, str] = {
    int(item["geonameId"]): str(item["nom"]).lower() for item in SEED_CITIES_FALLBACK_CATALOG
}

KNOWN_WORLD_IATA_CODES: dict[str, str] = {
    "paris": "CDG",
    "marrakech": "RAK",
    "tokyo": "HND",
    "new york": "JFK",
    "rome": "FCO",
    "lisbonne": "LIS",
    "lisboa": "LIS",
    "lisbon": "LIS",
    "seoul": "ICN",
    "le caire": "CAI",
    "cairo": "CAI",
    "barcelone": "BCN",
    "barcelona": "BCN",
    "londres": "LHR",
    "london": "LHR",
    "kyoto": "KIX",
    "reykjavik": "KEF",
    "madrid": "MAD",
    "berlin": "BER",
    "amsterdam": "AMS",
    "montreal": "YUL",
    "dubai": "DXB",
    "bangkok": "BKK",
    "sydney": "SYD",
}

SUBURB_OR_NON_CITY_FCODES: set[str] = {
    "PPLX",  # Section of populated place (banlieue / quartier)
    "PPLQ",  # Abandoned populated place
    "PPLW",  # Destroyed populated place
    "PPLH",  # Historical populated place
    "PPLCH",  # Historical capital
    "PPLF",  # Farm village
    "PPLL",  # Populated locality
    "PPLS",  # Populated places
    "RGN",
    "AREA",
    "ADM1",
    "ADM2",
    "ADM3",
    "ADM4",
}

REGION_OR_SUBURB_KEYWORDS: tuple[str, ...] = (
    "metropolitan area",
    "aire metropolitaine",
    "region metropolitaine",
    "banlieue",
    "suburb",
    "arrondissement",
    "agglomeration",
    "greater ",
    "grand ",
)


def normalize_geonames_query(raw: str) -> str:
    """Normalise une requête de ville : minuscules, sans accents, espaces réduits."""
    text = (raw or "").strip().lower()
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^a-z0-9\s\-']", " ", without_accents)
    return re.sub(r"\s+", " ", cleaned).strip()


def derive_iata_code(city_name: str, explicit_iata: str | None = None) -> str:
    if explicit_iata and len(explicit_iata.strip()) == 3:
        return explicit_iata.strip().upper()
    norm = normalize_geonames_query(city_name)
    if norm in KNOWN_WORLD_IATA_CODES:
        return KNOWN_WORLD_IATA_CODES[norm]
    letters = re.sub(r"[^A-Za-z]", "", normalize_geonames_query(city_name)).upper()
    return (letters[:3] if len(letters) >= 3 else (letters + "XXX")[:3]).upper()


def _build_city_result(
    *,
    geoname_id: int,
    name: str,
    country_name: str,
    country_code: str,
    latitude: float,
    longitude: float,
    timezone_id: str,
    population: int,
    iata_code: str | None = None,
    destination_id: str | None = None,
    is_seed: bool | None = None,
) -> GeoNamesCityResult:
    norm_name = normalize_geonames_query(name)
    seed_flag = (
        is_seed
        if is_seed is not None
        else (norm_name in SEED_CITY_NAMES_LOWER or geoname_id in SEED_GEONAME_ID_TO_CITY)
    )
    iso2 = (country_code or "XX").strip().upper()[:2] or "XX"
    tz = (timezone_id or "UTC").strip() or "UTC"
    lat = round(float(latitude), 5)
    lng = round(float(longitude), 5)
    coords = {"latitude": lat, "longitude": lng, "lat": lat, "lng": lng}
    resolved_iata = derive_iata_code(name, iata_code)
    return GeoNamesCityResult(
        geonameId=int(geoname_id),
        geoname_id=int(geoname_id),
        nom=name,
        name=name,
        city_name=name,
        pays=country_name,
        country_name=country_name,
        code_pays=iso2,
        country_code_iso2=iso2,
        coordonnees=coords,
        coordinates=coords,
        latitude=lat,
        longitude=lng,
        fuseau_horaire=tz,
        timezone=tz,
        population=max(0, int(population or 0)),
        iata_code=resolved_iata,
        is_seed=seed_flag,
        destination_id=destination_id,
    )


async def _build_seed_fallback_cities(
    db: AsyncSession,
    query_filter: str | None = None,
) -> tuple[list[GeoNamesCityResult], list[GeoNamesCityResult]]:
    """Construit la liste des 5 villes du seed (et les filtre optionnellement si une requête correspond)."""
    db_dests = list((await db.scalars(select(Destination))).all())
    by_lower_name = {d.city_name.strip().lower(): d for d in db_dests}

    all_seed_results: list[GeoNamesCityResult] = []
    for item in SEED_CITIES_FALLBACK_CATALOG:
        db_match = by_lower_name.get(str(item["nom"]).lower())
        all_seed_results.append(
            _build_city_result(
                geoname_id=int(item["geonameId"]),
                name=str(item["nom"]),
                country_name=str(item["pays"]),
                country_code=str(item["code_pays"]),
                latitude=float(item["latitude"]),
                longitude=float(item["longitude"]),
                timezone_id=str(item["fuseau_horaire"]),
                population=int(item["population"]),
                iata_code=str(item["iata_code"]),
                destination_id=db_match.id if db_match else None,
                is_seed=True,
            )
        )

    if not query_filter:
        return all_seed_results, all_seed_results

    norm_q = normalize_geonames_query(query_filter)
    if not norm_q:
        return all_seed_results, all_seed_results

    matched = [
        c
        for c in all_seed_results
        if norm_q in normalize_geonames_query(c.nom)
        or norm_q in normalize_geonames_query(c.pays)
        or norm_q == c.iata_code.lower()
    ]
    return (matched if matched else all_seed_results), all_seed_results


def filter_and_deduplicate_geonames_items(
    raw_items: list[dict[str, Any]],
    db_by_geoname_id: dict[int, Destination] | None = None,
    db_by_lower_name: dict[str, Destination] | None = None,
) -> list[GeoNamesCityResult]:
    """
    Filtre les résultats GeoNames :
    - Garde uniquement featureClass == 'P' (villes habitées, exclut régions fcl='L', 'A', etc.).
    - Exclut les banlieues / quartiers (fcode='PPLX', etc. ou mots-clés de région/banlieue,
      ou communes satellites situées à moins de 25 km d'une ville principale plus peuplée du même pays).
    - Supprime les doublons par geonameId et par (nom normalisé, code pays).
    - Extrait le fuseau horaire depuis timezone.timeZoneId (style=FULL).
    """
    by_gid = db_by_geoname_id or {}
    by_name = db_by_lower_name or {}

    accepted: list[GeoNamesCityResult] = []
    seen_geoname_ids: set[int] = set()
    seen_name_country: set[tuple[str, str]] = set()

    for raw in raw_items:
        if not isinstance(raw, dict):
            continue

        # 1. Filtre strict featureClass == 'P' (exclut fcl='L' comme "Lisbon metropolitan area")
        fcl = str(raw.get("fcl") or raw.get("featureClass") or "P").strip().upper()
        if fcl != "P":
            continue

        # 2. Filtre les codes de banlieue / section de ville / localité abandonnée
        fcode = str(raw.get("fcode") or raw.get("featureCode") or "").strip().upper()
        if fcode in SUBURB_OR_NON_CITY_FCODES:
            continue

        raw_gid = raw.get("geonameId") or raw.get("geoname_id")
        if raw_gid is None:
            continue
        try:
            geoname_id = int(raw_gid)
        except (TypeError, ValueError):
            continue

        if geoname_id in seen_geoname_ids:
            continue

        name = str(raw.get("name") or raw.get("nom") or raw.get("toponymName") or "").strip()
        toponym = str(raw.get("toponymName") or "").strip()
        fcl_name = str(raw.get("fclName") or "").strip()
        fcode_name = str(raw.get("fcodeName") or "").strip()
        if not name:
            continue

        # 3. Exclut les libellés de régions métropolitaines ou de banlieues
        combined_labels = normalize_geonames_query(f"{name} {toponym} {fcl_name} {fcode_name}")
        if any(kw in combined_labels for kw in REGION_OR_SUBURB_KEYWORDS):
            continue

        country_name = str(raw.get("countryName") or raw.get("pays") or "Monde").strip() or "Monde"
        country_code = (
            str(raw.get("countryCode") or raw.get("code_pays") or "XX").strip().upper()[:2] or "XX"
        )

        try:
            lat = float(raw.get("lat") if raw.get("lat") is not None else raw.get("latitude"))
            lng = float(raw.get("lng") if raw.get("lng") is not None else raw.get("longitude"))
        except (TypeError, ValueError):
            continue

        try:
            population = int(raw.get("population") or 0)
        except (TypeError, ValueError):
            population = 0

        # 4. Extraction du fuseau horaire (style=FULL renvoie timezone: {"timeZoneId": "Europe/Lisbon", ...})
        tz_field = raw.get("timezone") or raw.get("fuseau_horaire")
        timezone_id = ""
        if isinstance(tz_field, dict):
            timezone_id = str(tz_field.get("timeZoneId") or tz_field.get("timezone") or "").strip()
        elif isinstance(tz_field, str):
            timezone_id = tz_field.strip()

        if not timezone_id:
            preset_tz = WORLD_CITY_GEODATA.get(name.lower(), {}).get("timezone")
            timezone_id = str(preset_tz or "UTC")

        # 5. Dédoublonnage par (nom normalisé, pays)
        norm_city = normalize_geonames_query(name)
        norm_toponym = normalize_geonames_query(toponym) if toponym else norm_city
        if (norm_city, country_code) in seen_name_country or (
            norm_toponym,
            country_code,
        ) in seen_name_country:
            continue

        # 6. Filtrage des banlieues proches (< 25 km dans le même pays d'une ville déjà retenue plus peuplée)
        is_suburb_of_accepted = False
        for existing_city in accepted:
            if existing_city.country_code_iso2 == country_code:
                dist_km = haversine_distance_km(
                    existing_city.latitude,
                    existing_city.longitude,
                    lat,
                    lng,
                )
                if dist_km <= 25.0 and existing_city.population >= max(population, 1):
                    is_suburb_of_accepted = True
                    break
        if is_suburb_of_accepted:
            continue

        db_dest = by_gid.get(geoname_id) or by_name.get(name.lower())
        city_res = _build_city_result(
            geoname_id=geoname_id,
            name=db_dest.city_name if db_dest else name,
            country_name=db_dest.country_name if db_dest else country_name,
            country_code=db_dest.country_code_iso2 if db_dest else country_code,
            latitude=lat,
            longitude=lng,
            timezone_id=timezone_id,
            population=population,
            iata_code=db_dest.iata_code if db_dest else None,
            destination_id=db_dest.id if db_dest else None,
        )
        accepted.append(city_res)
        seen_geoname_ids.add(geoname_id)
        seen_name_country.add((norm_city, country_code))
        if norm_toponym:
            seen_name_country.add((norm_toponym, country_code))

    return accepted


async def fetch_geonames_search_json(q: str, settings: Settings) -> dict[str, Any]:
    """
    Appelle l'API GeoNames searchJSON avec les paramètres requis :
    featureClass=P, orderby=population, maxRows=8, lang=fr, style=FULL.
    """
    base_url = (settings.GEONAMES_BASE_URL or "http://api.geonames.org").rstrip("/")
    url = base_url if base_url.endswith("/searchJSON") else f"{base_url}/searchJSON"
    params: dict[str, str | int] = {
        "q": q,
        "featureClass": "P",
        "orderby": "population",
        "maxRows": 8,
        "lang": "fr",
        "style": "FULL",
        "username": (settings.GEONAMES_USERNAME or "").strip(),
    }
    async with httpx.AsyncClient(timeout=4.0) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Réponse GeoNames invalide.")
        return data


DESTINATION_PRACTICAL_CATALOG: dict[str, dict[str, Any]] = {
    "marrakech": {
        "target_language": "Arabe marocain (Darija)",
        "plugs": "Types C et E (220 V - 50 Hz, identiques aux prises françaises).",
        "tipping": "10 % au restaurant si le service n'est pas inclus ; 10 à 20 MAD pour les bagagistes et guides.",
        "emergency": "19 (Police urbaine), 15 (Ambulance et Pompiers), 112 (Urgences depuis un mobile).",
        "dial_code": "+212",
        "currency": "Dirham marocain (MAD — 1 € ≈ 10,80 MAD)",
        "source": "Conseils aux voyageurs — Ministère des Affaires étrangères & Office national marocain du tourisme",
        "updated_at_fr": "15 octobre 2026",
        "useful_phrases": [
            {
                "french": "Bonjour, comment allez-vous ?",
                "local_translation": "Salam alaykoum, labass alik ?",
                "pronunciation": "Sa-lam a-lay-koum, la-bass a-lik",
                "context_fr": "Salutation",
            },
            {
                "french": "Merci beaucoup",
                "local_translation": "Choukrane bzzaf",
                "pronunciation": "Chou-krane bez-zaf",
                "context_fr": "Politesse",
            },
            {
                "french": "Combien ça coûte, s'il vous plaît ?",
                "local_translation": "Bchhal hada afak ?",
                "pronunciation": "Bech-hal ha-da a-fak",
                "context_fr": "Achats et souks",
            },
            {
                "french": "L'addition, s'il vous plaît",
                "local_translation": "L'hssab afak",
                "pronunciation": "El-hssab a-fak",
                "context_fr": "Restaurant",
            },
            {
                "french": "Où se trouve la place Jemaa el-Fna ?",
                "local_translation": "Fin kayna sahat Jemaa el-Fna ?",
                "pronunciation": "Fine kay-na sa-hat Dje-maa el Fna",
                "context_fr": "Orientation",
            },
        ],
    },
    "new york": {
        "target_language": "Anglais américain",
        "plugs": "Types A et B (120 V - 60 Hz, adaptateur à fiches plates indispensable).",
        "tipping": "18 % à 20 % obligatoire d'usage au restaurant et dans les taxis ; 2 $ par bagage à l'hôtel.",
        "emergency": "911 (Police, Pompiers et Urgences médicales gratuit depuis tout téléphone).",
        "dial_code": "+1",
        "currency": "Dollar américain (USD — 1 € ≈ 1,08 $)",
        "source": "Conseils aux voyageurs — Ministère des Affaires étrangères & NYC Tourism",
        "updated_at_fr": "15 octobre 2026",
        "useful_phrases": [
            {
                "french": "Bonjour, une table pour deux s'il vous plaît.",
                "local_translation": "Hello, a table for two, please.",
                "pronunciation": "He-lo, euh tey-bol for tou, pliz",
                "context_fr": "Restaurant",
            },
            {
                "french": "Où se trouve la station de métro la plus proche ?",
                "local_translation": "Where is the nearest subway station?",
                "pronunciation": "Wèr iz zeu ni-rest seub-wey stey-cheun",
                "context_fr": "Transports",
            },
            {
                "french": "L'addition, s'il vous plaît.",
                "local_translation": "Could we have the check, please?",
                "pronunciation": "Koud wi hav zeu tchek, pliz",
                "context_fr": "Restaurant",
            },
            {
                "french": "Combien coûte ce billet ?",
                "local_translation": "How much is this ticket?",
                "pronunciation": "Haou meutch iz zis ti-ket",
                "context_fr": "Visites",
            },
        ],
    },
    "tokyo": {
        "target_language": "Japonais",
        "plugs": "Types A et B (100 V - 50 Hz à Tokyo, adaptateur fiches plates requis).",
        "tipping": "Aucun pourboire au Japon (le service est toujours inclus et laisser un pourboire peut gêner).",
        "emergency": "110 (Police), 119 (Ambulance et Pompiers), 0570-000-911 (Assistance touristes Japan Visitor Hotline).",
        "dial_code": "+81",
        "currency": "Yen japonais (JPY — 1 € ≈ 162 ¥)",
        "source": "Conseils aux voyageurs — Ministère des Affaires étrangères & Office national du tourisme japonais (JNTO)",
        "updated_at_fr": "15 octobre 2026",
        "useful_phrases": [
            {
                "french": "Bonjour / Bon après-midi",
                "local_translation": "Konnichiwa (こんにちは)",
                "pronunciation": "Kon-ni-tchi-wa",
                "context_fr": "Salutation",
            },
            {
                "french": "Merci beaucoup",
                "local_translation": "Arigatō gozaimasu (ありがとうございます)",
                "pronunciation": "A-ri-ga-tô go-za-i-mas",
                "context_fr": "Politesse",
            },
            {
                "french": "Excusez-moi, où est la gare ?",
                "local_translation": "Sumimasen, eki wa doko desu ka ?",
                "pronunciation": "Sou-mi-ma-sèn, é-ki wa do-ko dès ka",
                "context_fr": "Transports",
            },
            {
                "french": "L'addition, s'il vous plaît.",
                "local_translation": "O-kaikei onegaishimasu",
                "pronunciation": "O-kaï-keï o-né-ga-ï-chi-mas",
                "context_fr": "Restaurant",
            },
        ],
    },
    "rome": {
        "target_language": "Italien",
        "plugs": "Types C, F et L (230 V - 50 Hz, compatibles avec les fiches fines européennes).",
        "tipping": "Pain et couvert (coperto de 2 à 3 €) souvent facturés ; laisser 5 % à 10 % reste apprécié.",
        "emergency": "112 (Numéro d'urgence européen), 118 (Urgences médicales), 113 (Police).",
        "dial_code": "+39",
        "currency": "Euro (EUR — €)",
        "source": "Conseils aux voyageurs — Ministère des Affaires étrangères & Agenzia Nazionale del Turismo (ENIT)",
        "updated_at_fr": "15 octobre 2026",
        "useful_phrases": [
            {
                "french": "Bonjour, une table pour deux s'il vous plaît.",
                "local_translation": "Buongiorno, un tavolo per due, per favore.",
                "pronunciation": "Bouon-djor-no, oun ta-vo-lo pèr dou-é, pèr fa-vo-ré",
                "context_fr": "Restaurant",
            },
            {
                "french": "L'addition, s'il vous plaît.",
                "local_translation": "Il conto, per favore.",
                "pronunciation": "Il kon-to, pèr fa-vo-ré",
                "context_fr": "Restaurant",
            },
            {
                "french": "Où se trouve le Colisée ?",
                "local_translation": "Dov'è il Colosseo ?",
                "pronunciation": "Do-vè il Ko-los-sé-o",
                "context_fr": "Orientation",
            },
        ],
    },
    "paris": {
        "target_language": "Anglais (échanges internationaux)",
        "plugs": "Type E (230 V - 50 Hz, standard français).",
        "tipping": "Service de 15 % légalement inclus dans les prix ; 1 à 5 € de pourboire libre selon satisfaction.",
        "emergency": "112 (Urgences européennes), 15 (SAMU), 17 (Police secours), 18 (Pompiers).",
        "dial_code": "+33",
        "currency": "Euro (EUR — €)",
        "source": "Office du Tourisme et des Congrès de Paris & Service-Public.fr",
        "updated_at_fr": "15 octobre 2026",
        "useful_phrases": [
            {
                "french": "Bonjour, une table pour deux s'il vous plaît.",
                "local_translation": "Hello, a table for two, please.",
                "pronunciation": "Bon-jour, une ta-ble pour deux s'il vous plaît",
                "context_fr": "Restaurant",
            },
            {
                "french": "L'addition, s'il vous plaît.",
                "local_translation": "The bill, please.",
                "pronunciation": "La-di-ssion s'il vous plaît",
                "context_fr": "Restaurant",
            },
            {
                "french": "Où est la station de métro la plus proche ?",
                "local_translation": "Where is the nearest metro station?",
                "pronunciation": "Où est la sta-tion de mé-tro la plus pro-che",
                "context_fr": "Transports",
            },
        ],
    },
}

WORLD_CITY_GEODATA: dict[str, dict[str, Any]] = {
    "barcelone": {
        "city_name": "Barcelone",
        "country_name": "Espagne",
        "country_code_iso2": "ES",
        "iata_code": "BCN",
        "timezone": "Europe/Madrid",
        "latitude": 41.3874,
        "longitude": 2.1686,
    },
    "barcelona": {
        "city_name": "Barcelona",
        "country_name": "Espagne",
        "country_code_iso2": "ES",
        "iata_code": "BCN",
        "timezone": "Europe/Madrid",
        "latitude": 41.3874,
        "longitude": 2.1686,
    },
    "londres": {
        "city_name": "Londres",
        "country_name": "Royaume-Uni",
        "country_code_iso2": "GB",
        "iata_code": "LHR",
        "timezone": "Europe/London",
        "latitude": 51.5072,
        "longitude": -0.1276,
    },
    "london": {
        "city_name": "London",
        "country_name": "Royaume-Uni",
        "country_code_iso2": "GB",
        "iata_code": "LHR",
        "timezone": "Europe/London",
        "latitude": 51.5072,
        "longitude": -0.1276,
    },
    "lisbonne": {
        "city_name": "Lisbonne",
        "country_name": "Portugal",
        "country_code_iso2": "PT",
        "iata_code": "LIS",
        "timezone": "Europe/Lisbon",
        "latitude": 38.7223,
        "longitude": -9.1393,
    },
    "kyoto": {
        "city_name": "Kyoto",
        "country_name": "Japon",
        "country_code_iso2": "JP",
        "iata_code": "KIX",
        "timezone": "Asia/Tokyo",
        "latitude": 35.0116,
        "longitude": 135.7681,
    },
    "reykjavik": {
        "city_name": "Reykjavik",
        "country_name": "Islande",
        "country_code_iso2": "IS",
        "iata_code": "KEF",
        "timezone": "Atlantic/Reykjavik",
        "latitude": 64.1466,
        "longitude": -21.9426,
    },
}


def get_enriched_practical_profile(dest: Destination) -> PracticalInfoResponse:
    city_key = (dest.city_name or "").strip().lower()
    preset = DESTINATION_PRACTICAL_CATALOG.get(city_key)
    raw_info = dict(dest.practical_info or {})

    if preset:
        plugs = str(raw_info.get("prises") or preset["plugs"])
        tipping = str(raw_info.get("pourboires") or preset["tipping"])
        emergency = str(raw_info.get("urgences") or preset["emergency"])
        dial_code = str(raw_info.get("indicatif") or preset["dial_code"])
        currency = str(raw_info.get("monnaie") or preset["currency"])
        source = str(raw_info.get("source") or preset["source"])
        updated_at_fr = str(raw_info.get("date_mise_a_jour_fr") or preset["updated_at_fr"])
        target_language = str(preset["target_language"])
        phrases_raw = preset["useful_phrases"]
    else:
        plugs = str(raw_info.get("prises") or "Types C et E (230 V - 50 Hz).")
        tipping = str(raw_info.get("pourboires") or "5 % à 10 % selon la qualité du service.")
        emergency = str(raw_info.get("urgences") or "112 / 911 (Urgences générales).")
        dial_code = str(raw_info.get("indicatif") or "+00")
        currency = str(raw_info.get("monnaie") or "Devise locale / EUR")
        source = str(
            raw_info.get("source")
            or "Conseils aux voyageurs — Ministère de l'Europe et des Affaires étrangères"
        )
        updated_at_fr = str(raw_info.get("date_mise_a_jour_fr") or "15 octobre 2026")
        target_language = "Anglais"
        phrases_raw = [
            {
                "french": "Bonjour, pouvez-vous m'aider s'il vous plaît ?",
                "local_translation": "Hello, could you help me please?",
                "pronunciation": "He-lo, koud you help mi pliz",
                "context_fr": "Vie courante",
            },
            {
                "french": "Combien ça coûte ?",
                "local_translation": "How much does it cost?",
                "pronunciation": "Haou meutch deuz it kost",
                "context_fr": "Achats",
            },
        ]

    phrases = [UsefulPhraseSchema(**p) for p in phrases_raw]
    return PracticalInfoResponse(
        destination_id=dest.id,
        city_name=dest.city_name,
        country_name=dest.country_name,
        target_language=target_language,
        plugs=plugs,
        tipping=tipping,
        emergency=emergency,
        dial_code=dial_code,
        currency=currency,
        source=source,
        updated_at_fr=updated_at_fr,
        useful_phrases=phrases,
    )


def _enrich_destination_response(dest: Destination) -> DestinationResponse:
    profile = get_enriched_practical_profile(dest)
    merged_info = dict(dest.practical_info or {})
    merged_info.update(
        {
            "prises": profile.plugs,
            "pourboires": profile.tipping,
            "urgences": profile.emergency,
            "indicatif": profile.dial_code,
            "monnaie": profile.currency,
            "source": profile.source,
            "date_mise_a_jour_fr": profile.updated_at_fr,
        }
    )
    phrases_dicts = [
        {
            "original": p.french,
            "translation": p.local_translation,
            "phonetic": p.pronunciation,
            "french": p.french,
            "local_translation": p.local_translation,
            "pronunciation": p.pronunciation,
            "context_fr": p.context_fr,
        }
        for p in profile.useful_phrases
    ]
    city_low = (dest.city_name or "").strip().lower()
    is_seed = city_low in SEED_CITY_NAMES_LOWER
    return DestinationResponse(
        id=dest.id,
        geoname_id=dest.geoname_id,
        geonameId=dest.geoname_id,
        city_name=dest.city_name,
        country_name=dest.country_name,
        country_code_iso2=dest.country_code_iso2,
        iata_code=dest.iata_code,
        timezone=dest.timezone,
        latitude=dest.latitude,
        longitude=dest.longitude,
        population=dest.population,
        is_seed=is_seed,
        hero_image_url=dest.hero_image_url,
        description=dest.description,
        practical_info=merged_info,
        useful_phrases=phrases_dicts,
    )


DETERMINISTIC_DICTIONARY: dict[str, dict[str, tuple[str, str]]] = {
    "marrakech": {
        "bonjour": ("Salam alaykoum", "Sa-lam a-lay-koum"),
        "merci": ("Choukrane bzzaf", "Chou-krane bez-zaf"),
        "combien": ("Bchhal hada afak ?", "Bech-hal ha-da a-fak"),
        "addition": ("L'hssab afak", "El-hssab a-fak"),
        "eau": ("L'ma afak", "El-ma a-fak"),
        "taxi": ("Fin kayn taxi afak ?", "Fine kayn tak-si a-fak"),
        "gare": ("Fin kayna la gare ?", "Fine kay-na la gar"),
        "aéroport": ("Fin kayn l'matar ?", "Fine kayn el-ma-tar"),
        "aide": ("Aawnni afak", "Aa-wen-ni a-fak"),
        "toilettes": ("Fin kayn bit l'ma afak ?", "Fine kayn bit el-ma a-fak"),
        "hôtel": ("Fin kayn l'hôtel / riad afak ?", "Fine kayn el-ri-ad a-fak"),
    },
    "new york": {
        "bonjour": ("Hello, good morning!", "He-lo, goud mor-ning"),
        "merci": ("Thank you very much!", "Zank you vé-ri meutch"),
        "combien": ("How much is this, please?", "Haou meutch iz zis, pliz"),
        "addition": ("Could we have the check, please?", "Koud wi hav zeu tchek, pliz"),
        "eau": ("A bottle of still water, please.", "Euh bo-teul ov stil wo-teur, pliz"),
        "taxi": ("Where can I find a taxi?", "Wèr kan aï faïnd euh tak-si"),
        "gare": ("Where is the train / subway station?", "Wèr iz zeu seub-wey stey-cheun"),
        "aéroport": ("How do I get to JFK Airport?", "Haou dou aï gèt tou Djey-Ef-Key èr-port"),
        "aide": ("Could you help me, please?", "Koud you help mi, pliz"),
        "toilettes": ("Where is the restroom, please?", "Wèr iz zeu rèst-roum, pliz"),
        "hôtel": ("Where is the hotel located?", "Wèr iz zeu ho-tèl lo-key-ted"),
    },
    "tokyo": {
        "bonjour": ("Konnichiwa (こんにちは)", "Kon-ni-tchi-wa"),
        "merci": ("Arigatō gozaimasu (ありがとうございます)", "A-ri-ga-tô go-za-i-mas"),
        "combien": ("Ikura desu ka ? (いくらですか)", "I-kou-ra dès ka"),
        "addition": ("O-kaikei onegaishimasu (お会計お願いします)", "O-kaï-keï o-né-ga-ï-chi-mas"),
        "eau": ("O-mizu o kudasai (お水をください)", "O-mi-zou o kou-da-saï"),
        "taxi": ("Takushī noriba wa doko desu ka ?", "Ta-kou-chi no-ri-ba wa do-ko dès ka"),
        "gare": ("Sumimasen, eki wa doko desu ka ?", "Sou-mi-ma-sèn, é-ki wa do-ko dès ka"),
        "aéroport": ("Kūkō wa doko desu ka ?", "Kou-kô wa do-ko dès ka"),
        "aide": ("Tasukete kudasai (助けてください)", "Ta-sou-ké-té kou-da-saï"),
        "toilettes": ("O-tearai wa doko desu ka ?", "O-té-a-raï wa do-ko dès ka"),
        "hôtel": ("Hoteru wa doko desu ka ?", "Ho-té-rou wa do-ko dès ka"),
    },
    "rome": {
        "bonjour": ("Buongiorno !", "Bouon-djor-no"),
        "merci": ("Grazie mille !", "Gra-tzié mil-lé"),
        "combien": ("Quanto costa, per favore ?", "Kouan-to kos-ta, pèr fa-vo-ré"),
        "addition": ("Il conto, per favore.", "Il kon-to, pèr fa-vo-ré"),
        "eau": ("Una bottiglia d'acqua naturale, per favore.", "Ou-na bot-ti-lia da-koua, pèr fa-vo-ré"),
        "taxi": ("Dove posso trovare un taxi ?", "Do-vé pos-so tro-va-ré oun tak-si"),
        "gare": ("Dov'è la stazione Termini ?", "Do-vè la sta-tzio-né Tèr-mi-ni"),
        "aéroport": ("Come arrivo all'aeroporto ?", "Ko-mé ar-ri-vo al a-é-ro-por-to"),
        "aide": ("Mi può aiutare, per favore ?", "Mi pou-o a-iou-ta-ré, pèr fa-vo-ré"),
        "toilettes": ("Dov'è il bagno, per favore ?", "Do-vè il ba-nio, pèr fa-vo-ré"),
        "hôtel": ("Dov'è l'albergo ?", "Do-vè lal-bèr-go"),
    },
}


def deterministic_translate_phrase(
    source_text: str,
    city_name: str,
    target_language: str,
    useful_phrases: list[UsefulPhraseSchema],
) -> tuple[str, str]:
    clean_src = source_text.strip()
    low_src = re.sub(r"\s+", " ", clean_src.lower())

    for up in useful_phrases:
        if low_src == up.french.strip().lower() or low_src in up.french.strip().lower():
            return up.local_translation, up.pronunciation

    city_key = city_name.strip().lower()
    city_dict = DETERMINISTIC_DICTIONARY.get(city_key, DETERMINISTIC_DICTIONARY["new york"])
    for keyword, (trans, pron) in city_dict.items():
        if keyword in low_src:
            return trans, pron

    if city_key == "marrakech":
        return (
            f"Afak : « {clean_src} » (Choukrane)",
            f"A-fak : {clean_src} (Chou-krane)",
        )
    if city_key == "tokyo":
        return (
            f"Sumimasen, « {clean_src} » onegaishimasu",
            f"Sou-mi-ma-sèn, {clean_src} o-né-ga-ï-chi-mas",
        )
    if city_key == "rome":
        return (
            f"Per favore, « {clean_src} » (Grazie)",
            f"Pèr fa-vo-ré, {clean_src} (Gra-tzié)",
        )
    return (
        f"Excuse me, please: \"{clean_src}\"",
        f"Eks-kiouz mi, pliz : {clean_src}",
    )


@router.get("", response_model=list[DestinationResponse])
async def list_destinations(
    q: str | None = Query(default=None, description="Filtre optionnel par nom de ville ou code IATA"),
    popular_only: bool = Query(
        default=False,
        description="Si vrai, ne renvoie que les 5 destinations populaires du seed",
    ),
    db: AsyncSession = Depends(get_db),
) -> list[DestinationResponse]:
    stmt = select(Destination).order_by(Destination.city_name.asc())
    result = await db.scalars(stmt)
    items = list(result.all())
    if popular_only:
        items = [d for d in items if d.city_name.strip().lower() in SEED_CITY_NAMES_LOWER]
    if q:
        q_low = q.strip().lower()
        items = [
            d
            for d in items
            if q_low in d.city_name.lower()
            or q_low in d.country_name.lower()
            or q_low == d.iata_code.lower()
        ]
    return [_enrich_destination_response(d) for d in items]


@router.get("/search", response_model=GeoNamesSearchResponse)
async def search_world_cities_geonames(
    request: Request,
    q: str = Query(default="", description="Recherche de ville (3 lettres minimum)"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> GeoNamesSearchResponse:
    """
    Recherche et autocomplétion de villes du monde via GeoNames (searchJSON) :
    - featureClass=P, orderby=population, maxRows=8, lang=fr, style=FULL (fuseau horaire).
    - Cache Redis par requête normalisée (minuscules, sans accents).
    - Quotas gratuits (1000/heure, 20000/jour) + limite par utilisateur.
    - Si GeoNames injoignable, quota atteint ou clé absente : message "Recherche de villes indisponible"
      et repli sur les 5 villes du seed, jamais de plantage.
    """
    raw_query = (q or "").strip()
    norm_q = normalize_geonames_query(raw_query)
    matched_seed, all_seed = await _build_seed_fallback_cities(db, raw_query)

    # Moins de 3 lettres : pas d'appel GeoNames, renvoie les villes populaires correspondantes
    if len(norm_q) < 3:
        return GeoNamesSearchResponse(
            query=raw_query,
            normalized_query=norm_q,
            available=True,
            fallback=False,
            cached=False,
            quota_exceeded=False,
            reason="min_chars",
            message="Saisissez au moins 3 lettres pour rechercher parmi les villes du monde.",
            results=matched_seed,
            fallback_cities=all_seed,
        )

    # 1. Vérification du cache Redis par requête normalisée (minuscules, sans accents)
    cache_key = f"geonames:search:v1:{norm_q}"
    cached_payload = await cache_client.get_json(cache_key)
    if cached_payload and isinstance(cached_payload.get("results"), list):
        db_dests = list((await db.scalars(select(Destination))).all())
        by_gid = {d.geoname_id: d for d in db_dests if d.geoname_id is not None}
        by_name = {d.city_name.strip().lower(): d for d in db_dests}
        cached_results: list[GeoNamesCityResult] = []
        for item in cached_payload["results"]:
            gid = int(item.get("geonameId") or item.get("geoname_id") or 0)
            name_str = str(item.get("nom") or item.get("name") or "")
            db_match = by_gid.get(gid) or by_name.get(name_str.lower())
            item_copy = dict(item)
            if db_match:
                item_copy["destination_id"] = db_match.id
                item_copy["iata_code"] = db_match.iata_code
            cached_results.append(GeoNamesCityResult(**item_copy))
        return GeoNamesSearchResponse(
            query=raw_query,
            normalized_query=norm_q,
            available=True,
            fallback=False,
            cached=True,
            quota_exceeded=False,
            reason=None,
            message=None,
            results=cached_results,
            fallback_cities=all_seed,
        )

    # 2. Vérification de la présence de la clé GeoNames (GEONAMES_USERNAME)
    username = (settings.GEONAMES_USERNAME or "").strip()
    if not username:
        return GeoNamesSearchResponse(
            query=raw_query,
            normalized_query=norm_q,
            available=False,
            fallback=True,
            cached=False,
            quota_exceeded=False,
            reason="missing_api_key",
            message="Recherche de villes indisponible (clé GeoNames absente). Repli sur les 5 destinations populaires.",
            results=matched_seed,
            fallback_cities=all_seed,
        )

    # 3. Vérification des quotas gratuits (1000/heure, 20000/jour, et limite par utilisateur)
    now_utc = datetime.now(timezone.utc)
    hour_bucket = now_utc.strftime("%Y%m%d%H")
    day_bucket = now_utc.strftime("%Y%m%d")

    auth_header = (request.headers.get("authorization") or "").strip()
    user_ident = (
        auth_header[-16:]
        if auth_header
        else (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "anon"))
    )
    user_ident = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", user_ident)[:32] or "anon"

    hour_key = f"geonames:quota:hour:{hour_bucket}"
    day_key = f"geonames:quota:day:{day_bucket}"
    user_key = f"geonames:quota:user:{user_ident}:{hour_bucket}"

    hour_count = await cache_client.get_counter(hour_key)
    day_count = await cache_client.get_counter(day_key)
    user_count = await cache_client.get_counter(user_key)

    if hour_count >= settings.GEONAMES_HOURLY_QUOTA:
        return GeoNamesSearchResponse(
            query=raw_query,
            normalized_query=norm_q,
            available=False,
            fallback=True,
            cached=False,
            quota_exceeded=True,
            reason="hourly_quota_exceeded",
            message=(
                f"Recherche de villes indisponible : quota horaire GeoNames atteint "
                f"({settings.GEONAMES_HOURLY_QUOTA} requêtes/heure). Repli sur les 5 villes."
            ),
            results=matched_seed,
            fallback_cities=all_seed,
        )

    if day_count >= settings.GEONAMES_DAILY_QUOTA:
        return GeoNamesSearchResponse(
            query=raw_query,
            normalized_query=norm_q,
            available=False,
            fallback=True,
            cached=False,
            quota_exceeded=True,
            reason="daily_quota_exceeded",
            message=(
                f"Recherche de villes indisponible : quota journalier GeoNames atteint "
                f"({settings.GEONAMES_DAILY_QUOTA} requêtes/jour). Repli sur les 5 villes."
            ),
            results=matched_seed,
            fallback_cities=all_seed,
        )

    if user_count >= settings.GEONAMES_USER_HOURLY_QUOTA:
        return GeoNamesSearchResponse(
            query=raw_query,
            normalized_query=norm_q,
            available=False,
            fallback=True,
            cached=False,
            quota_exceeded=True,
            reason="user_quota_exceeded",
            message=(
                f"Recherche de villes indisponible : limite de requêtes par utilisateur atteinte "
                f"({settings.GEONAMES_USER_HOURLY_QUOTA}/heure). Repli sur les 5 villes."
            ),
            results=matched_seed,
            fallback_cities=all_seed,
        )

    # Incrémente les compteurs de quota avant l'appel réseau
    await cache_client.incr_counter(hour_key, ttl_seconds=3600)
    await cache_client.incr_counter(day_key, ttl_seconds=86400)
    await cache_client.incr_counter(user_key, ttl_seconds=3600)

    # 4. Appel à GeoNames searchJSON
    try:
        raw_payload = await fetch_geonames_search_json(raw_query, settings)
    except Exception:
        return GeoNamesSearchResponse(
            query=raw_query,
            normalized_query=norm_q,
            available=False,
            fallback=True,
            cached=False,
            quota_exceeded=False,
            reason="network_error",
            message="Recherche de villes indisponible (service GeoNames injoignable). Repli sur les 5 villes.",
            results=matched_seed,
            fallback_cities=all_seed,
        )

    # Gestion des erreurs applicatives GeoNames (ex: status.value 10, 18, 19, 20)
    if "status" in raw_payload and "geonames" not in raw_payload:
        status_obj = raw_payload.get("status") or {}
        status_val = int(status_obj.get("value") or 0) if isinstance(status_obj, dict) else 0
        status_msg = str(status_obj.get("message") or "") if isinstance(status_obj, dict) else ""
        is_quota = status_val in {18, 19, 20} or any(
            w in status_msg.lower() for w in ("limit", "quota", "credits", "overloaded")
        )
        return GeoNamesSearchResponse(
            query=raw_query,
            normalized_query=norm_q,
            available=False,
            fallback=True,
            cached=False,
            quota_exceeded=is_quota,
            reason="quota_exceeded" if is_quota else "geonames_error",
            message=(
                "Recherche de villes indisponible : quota GeoNames atteint. Repli sur les 5 villes."
                if is_quota
                else "Recherche de villes indisponible. Repli sur les 5 villes."
            ),
            results=matched_seed,
            fallback_cities=all_seed,
        )

    raw_geonames_list = raw_payload.get("geonames")
    if not isinstance(raw_geonames_list, list):
        return GeoNamesSearchResponse(
            query=raw_query,
            normalized_query=norm_q,
            available=False,
            fallback=True,
            cached=False,
            quota_exceeded=False,
            reason="invalid_payload",
            message="Recherche de villes indisponible. Repli sur les 5 villes.",
            results=matched_seed,
            fallback_cities=all_seed,
        )

    db_dests = list((await db.scalars(select(Destination))).all())
    by_gid = {d.geoname_id: d for d in db_dests if d.geoname_id is not None}
    by_name = {d.city_name.strip().lower(): d for d in db_dests}

    filtered_results = filter_and_deduplicate_geonames_items(
        raw_geonames_list,
        db_by_geoname_id=by_gid,
        db_by_lower_name=by_name,
    )

    # Mise en cache Redis par requête normalisée (24h)
    await cache_client.set_json(
        cache_key,
        {"results": [item.model_dump() for item in filtered_results]},
        ttl_seconds=86400,
    )

    return GeoNamesSearchResponse(
        query=raw_query,
        normalized_query=norm_q,
        available=True,
        fallback=False,
        cached=False,
        quota_exceeded=False,
        reason=None,
        message=None,
        results=filtered_results,
        fallback_cities=all_seed,
    )


async def _resolve_or_create_destination_impl(
    payload: DestinationResolveRequest,
    db: AsyncSession,
) -> DestinationResponse:
    """
    Crée ou résout une destination à partir d'un résultat GeoNames (identifiée par geonameId, sans doublon).
    Les 5 villes du seed gardent l'intégralité de leurs données de démonstration.
    """
    normalized_name = payload.city_name.strip()
    norm_ascii = normalize_geonames_query(normalized_name)

    existing: Destination | None = None

    # 1. Recherche prioritaire par geonameId (sans doublon)
    if payload.geoname_id is not None:
        existing = await db.scalar(
            select(Destination).where(Destination.geoname_id == payload.geoname_id)
        )
        # Si le geonameId correspond à l'une des 5 villes du seed dont geoname_id n'était pas encore renseigné
        if existing is None and payload.geoname_id in SEED_GEONAME_ID_TO_CITY:
            seed_city_low = SEED_GEONAME_ID_TO_CITY[payload.geoname_id]
            existing = await db.scalar(
                select(Destination).where(func.lower(Destination.city_name) == seed_city_low)
            )

    # 2. Recherche par nom de ville (insensible à la casse et aux accents)
    if existing is None:
        existing = await db.scalar(
            select(Destination).where(func.lower(Destination.city_name) == normalized_name.lower())
        )
    if existing is None:
        all_dests = list((await db.scalars(select(Destination))).all())
        for d in all_dests:
            if normalize_geonames_query(d.city_name) == norm_ascii:
                existing = d
                break

    if existing is not None:
        # Les 5 villes du seed gardent leurs données de démonstration intactes
        updated = False
        if existing.geoname_id is None and payload.geoname_id is not None:
            existing.geoname_id = payload.geoname_id
            updated = True
        if existing.population is None and payload.population is not None:
            existing.population = payload.population
            updated = True
        if updated:
            await db.commit()
            await db.refresh(existing)
        return _enrich_destination_response(existing)

    preset = WORLD_CITY_GEODATA.get(normalized_name.lower(), {})
    iata = derive_iata_code(
        preset.get("city_name", normalized_name),
        payload.iata_code or preset.get("iata_code"),
    )
    lat = payload.latitude if payload.latitude is not None else preset.get("latitude", 46.2044)
    lng = payload.longitude if payload.longitude is not None else preset.get("longitude", 6.1432)
    country = (
        payload.country_name
        if payload.country_name and payload.country_name != "Monde"
        else preset.get("country_name", payload.country_name)
    )
    iso2 = (
        payload.country_code_iso2.upper()
        if payload.country_code_iso2 and payload.country_code_iso2.upper() != "XX"
        else preset.get("country_code_iso2", payload.country_code_iso2.upper())
    )
    tz = (
        payload.timezone
        if payload.timezone and payload.timezone != "UTC"
        else preset.get("timezone", payload.timezone or "UTC")
    )

    new_dest = Destination(
        geoname_id=payload.geoname_id,
        city_name=preset.get("city_name", normalized_name),
        country_name=country,
        country_code_iso2=iso2[:2],
        iata_code=iata,
        timezone=tz,
        latitude=float(lat),
        longitude=float(lng),
        population=payload.population,
        hero_image_url="https://images.unsplash.com/photo-1488646953014-85cb44e25828?auto=format&fit=crop&w=1400&q=80",
        description=f"Destination mondiale {normalized_name} ({country}) configurée dynamiquement.",
        practical_info={
            "visa": "Vérifier les conditions d'entrée consulaires selon votre nationalité.",
            "prises": "Types C et E (230 V - 50 Hz).",
            "pourboires": "5 % à 10 % selon la qualité du service.",
            "urgences": "112 / 911",
            "indicatif": "+00",
            "monnaie": "Devise locale / EUR",
            "source": "Conseils aux voyageurs — Ministère de l'Europe et des Affaires étrangères",
            "date_mise_a_jour_fr": "15 octobre 2026",
        },
        useful_phrases=[],
    )
    db.add(new_dest)
    await db.commit()
    await db.refresh(new_dest)
    return _enrich_destination_response(new_dest)


@router.post("", response_model=DestinationResponse, status_code=status.HTTP_200_OK)
async def create_or_resolve_destination_from_geonames(
    payload: DestinationResolveRequest,
    db: AsyncSession = Depends(get_db),
) -> DestinationResponse:
    """Crée ou récupère une destination à partir d'un résultat GeoNames (sans doublon sur geonameId)."""
    return await _resolve_or_create_destination_impl(payload, db)


@router.post("/resolve", response_model=DestinationResponse, status_code=status.HTTP_200_OK)
async def resolve_or_create_world_destination(
    payload: DestinationResolveRequest,
    db: AsyncSession = Depends(get_db),
) -> DestinationResponse:
    """Résout une ville existante ou crée dynamiquement n'importe quelle ville du monde."""
    return await _resolve_or_create_destination_impl(payload, db)


@router.get("/{destination_id}/practical-info", response_model=PracticalInfoResponse)
async def get_destination_practical_info(
    destination_id: str,
    db: AsyncSession = Depends(get_db),
) -> PracticalInfoResponse:
    """
    Retourne les informations pratiques complètes d'une destination (prises, pourboires, urgences,
    indicatif, monnaie) avec leur source, la date de mise à jour en français et les phrases utiles
    accompagnées de leur prononciation.
    """
    dest = await db.scalar(select(Destination).where(Destination.id == destination_id))
    if not dest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Destination introuvable.",
        )
    return get_enriched_practical_profile(dest)


@router.post("/{destination_id}/translate", response_model=TranslateResponse)
async def translate_destination_phrase(
    destination_id: str,
    payload: TranslateRequest,
    db: AsyncSession = Depends(get_db),
) -> TranslateResponse:
    """
    Traducteur de voyage déterministe (mode simulé sans dépendance externe) :
    retourne la traduction dans la langue de la destination ainsi que la prononciation phonétique.
    """
    dest = await db.scalar(select(Destination).where(Destination.id == destination_id))
    if not dest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Destination introuvable.",
        )
    profile = get_enriched_practical_profile(dest)
    target_lang = (payload.target_language or profile.target_language).strip()
    translated, pronunciation = deterministic_translate_phrase(
        source_text=payload.text,
        city_name=dest.city_name,
        target_language=target_lang,
        useful_phrases=profile.useful_phrases,
    )
    return TranslateResponse(
        destination_id=dest.id,
        city_name=dest.city_name,
        target_language=target_lang,
        source_text=payload.text.strip(),
        translated_text=translated,
        translation=translated,
        pronunciation=pronunciation,
    )


@router.get("/{destination_id}", response_model=DestinationResponse)
async def get_destination(
    destination_id: str,
    db: AsyncSession = Depends(get_db),
) -> DestinationResponse:
    dest = await db.scalar(select(Destination).where(Destination.id == destination_id))
    if not dest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Destination introuvable.",
        )
    return _enrich_destination_response(dest)

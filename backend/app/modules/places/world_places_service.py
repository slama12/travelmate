from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from difflib import SequenceMatcher
import hashlib
import math
import re
import time
import unicodedata
from urllib.parse import quote
from typing import Any, Awaitable, Callable

import httpx
import mwparserfromhell

from app.core.geo import haversine_distance_km
from app.models.enums import PlaceCategory, TravelStyle

WORLD_PLACES_USER_AGENT = "TravelMate/1.0 (contact)"
WIKIVOYAGE_WIKIPEDIA_ATTRIBUTION = "Données Wikivoyage / Wikipédia (CC BY-SA 4.0)"
OUTAGE_PLACES_MESSAGE = "Les lieux de cette ville sont momentanément indisponibles"
BACKOFF_DELAYS_SECONDS: tuple[int, ...] = (1, 2, 4)
MAX_DISTRICT_PAGES = 10
MAX_SELECTED_PLACES = 20
MIN_WIKIVOYAGE_BEFORE_WIKIPEDIA = 10
FEW_PLACES_THRESHOLD = 5
DEFAULT_SEARCH_RADIUS_KM = 10
EXPANDED_SEARCH_RADIUS_KM = 30
OVERPASS_TIMEOUT_SECONDS = 10.0

OVERPASS_MIRRORS: tuple[str, ...] = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
)

WIKIVOYAGE_LISTING_TEMPLATES: set[str] = {
    "listing",
    "voir",
    "see",
    "manger",
    "eat",
    "sortir",
    "boire",
    "boire un verre",
    "drink",
    "nightlife",
    "faire",
    "do",
    "se loger",
    "sleep",
    "aller",
    "buy",
    "acheter",
    "marker",
    "vcard",
}

# Liste blanche touristique Wikidata (P31 / P279) :
# monument, musée, site archéologique, mosquée, église, fort, palais, parc, plage,
# jardin, place, pont, tour, marché, réserve naturelle (et sous-classes directes)
WIKIDATA_TOURIST_WHITELIST_QIDS: dict[str, tuple[str, str]] = {
    # QID -> (type_touristique_fr, categorie_normalisee)
    "Q4989906": ("monument", PlaceCategory.CULTURE.value),
    "Q5003624": ("monument", PlaceCategory.CULTURE.value),
    "Q162875": ("monument", PlaceCategory.CULTURE.value),  # mausolée
    "Q33506": ("musée", PlaceCategory.CULTURE.value),
    "Q207694": ("musée", PlaceCategory.CULTURE.value),  # musée d'art
    "Q1030034": ("musée", PlaceCategory.CULTURE.value),
    "Q839954": ("site archéologique", PlaceCategory.CULTURE.value),
    "Q32815": ("mosquée", PlaceCategory.CULTURE.value),
    "Q16970": ("église", PlaceCategory.CULTURE.value),
    "Q2977": ("église", PlaceCategory.CULTURE.value),  # cathédrale
    "Q163687": ("église", PlaceCategory.CULTURE.value),  # basilique
    "Q44613": ("église", PlaceCategory.CULTURE.value),  # monastère
    "Q1785071": ("fort", PlaceCategory.CULTURE.value),
    "Q751876": ("fort", PlaceCategory.CULTURE.value),  # ribat
    "Q23413": ("fort", PlaceCategory.CULTURE.value),  # château
    "Q57821": ("fort", PlaceCategory.CULTURE.value),  # fortification / citadelle
    "Q16560": ("palais", PlaceCategory.CULTURE.value),
    "Q22698": ("parc", PlaceCategory.NATURE.value),
    "Q22746": ("parc", PlaceCategory.NATURE.value),  # parc urbain
    "Q46169": ("parc", PlaceCategory.NATURE.value),  # parc national
    "Q40080": ("plage", PlaceCategory.NATURE.value),
    "Q1107656": ("jardin", PlaceCategory.NATURE.value),
    "Q167346": ("jardin", PlaceCategory.NATURE.value),  # jardin botanique
    "Q174782": ("place", PlaceCategory.CULTURE.value),
    "Q12280": ("pont", PlaceCategory.CULTURE.value),
    "Q12518": ("tour", PlaceCategory.CULTURE.value),
    "Q330284": ("marché", PlaceCategory.CULTURE.value),
    "Q132510": ("marché", PlaceCategory.CULTURE.value),  # souk
    "Q179049": ("réserve naturelle", PlaceCategory.NATURE.value),
}

WIKIDATA_TOURIST_WHITELIST_KEYWORDS: tuple[tuple[str, str, str], ...] = (
    ("musée", "musée", PlaceCategory.CULTURE.value),
    ("museum", "musée", PlaceCategory.CULTURE.value),
    ("site archéologique", "site archéologique", PlaceCategory.CULTURE.value),
    ("archaeological site", "site archéologique", PlaceCategory.CULTURE.value),
    ("mosquée", "mosquée", PlaceCategory.CULTURE.value),
    ("mosque", "mosquée", PlaceCategory.CULTURE.value),
    ("église", "église", PlaceCategory.CULTURE.value),
    ("cathédrale", "église", PlaceCategory.CULTURE.value),
    ("basilique", "église", PlaceCategory.CULTURE.value),
    ("monastère", "église", PlaceCategory.CULTURE.value),
    ("church", "église", PlaceCategory.CULTURE.value),
    ("cathedral", "église", PlaceCategory.CULTURE.value),
    ("fort", "fort", PlaceCategory.CULTURE.value),
    ("ribat", "fort", PlaceCategory.CULTURE.value),
    ("château", "fort", PlaceCategory.CULTURE.value),
    ("citadelle", "fort", PlaceCategory.CULTURE.value),
    ("castle", "fort", PlaceCategory.CULTURE.value),
    ("fortress", "fort", PlaceCategory.CULTURE.value),
    ("palais", "palais", PlaceCategory.CULTURE.value),
    ("palace", "palais", PlaceCategory.CULTURE.value),
    ("réserve naturelle", "réserve naturelle", PlaceCategory.NATURE.value),
    ("nature reserve", "réserve naturelle", PlaceCategory.NATURE.value),
    ("plage", "plage", PlaceCategory.NATURE.value),
    ("beach", "plage", PlaceCategory.NATURE.value),
    ("jardin", "jardin", PlaceCategory.NATURE.value),
    ("garden", "jardin", PlaceCategory.NATURE.value),
    ("parc", "parc", PlaceCategory.NATURE.value),
    ("park", "parc", PlaceCategory.NATURE.value),
    ("place", "place", PlaceCategory.CULTURE.value),
    ("square", "place", PlaceCategory.CULTURE.value),
    ("plaza", "place", PlaceCategory.CULTURE.value),
    ("pont", "pont", PlaceCategory.CULTURE.value),
    ("bridge", "pont", PlaceCategory.CULTURE.value),
    ("tour", "tour", PlaceCategory.CULTURE.value),
    ("tower", "tour", PlaceCategory.CULTURE.value),
    ("marché", "marché", PlaceCategory.CULTURE.value),
    ("souk", "marché", PlaceCategory.CULTURE.value),
    ("market", "marché", PlaceCategory.CULTURE.value),
    ("monument", "monument", PlaceCategory.CULTURE.value),
    ("mausolée", "monument", PlaceCategory.CULTURE.value),
    ("mausoleum", "monument", PlaceCategory.CULTURE.value),
)

# Exclusions strictes Wikidata (événements, personnes, batailles, compétitions/tournois, communes/villes)
WIKIDATA_EXCLUDED_QIDS: set[str] = {
    "Q5",        # être humain / personne
    "Q1656682",  # événement
    "Q1190554",  # occurrence / événement
    "Q178561",   # bataille
    "Q198",      # guerre
    "Q13406554", # compétition sportive
    "Q500834",   # tournoi
    "Q476300",   # compétition
    "Q18608583", # tournoi de tennis récurrent
    "Q46190676", # édition de tournoi de tennis
    "Q484170",   # commune de France
    "Q515",      # ville
    "Q1549591",  # grande ville
    "Q15284",    # municipalité
    "Q56061",    # entité territoriale administrative
    "Q3957",     # petite ville
    "Q532",      # village
    "Q19953632", # municipalité de Tunisie
    "Q646728",   # délégation de Tunisie
    "Q3184121",  # gouvernorat de Tunisie
}

WIKIDATA_EXCLUDED_KEYWORDS: tuple[str, ...] = (
    "tournoi",
    "tournament",
    "open de ",
    "jasmin open",
    "compétition",
    "competition",
    "championnat",
    "championship",
    "bataille",
    "battle",
    "siège de ",
    "siege of ",
    "événement",
    "event",
    "personne",
    "human",
    "commune",
    "municipalité",
    "municipality",
    "gouvernorat",
    "délégation",
    "arrondissement",
)


def normalize_place_text(value: str) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value.strip().lower())
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^a-z0-9]+", " ", without_accents)
    return re.sub(r"\s+", " ", cleaned).strip()


def clean_wikitext_value(raw: str) -> str:
    if not raw:
        return ""
    try:
        parsed = mwparserfromhell.parse(raw)
        stripped = parsed.strip_code(normalize=True, collapse=True)
    except Exception:
        stripped = re.sub(r"\[+|\]+|\{+|\}+", "", raw)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return stripped


def parse_opening_hours_text(raw_hours: str | None) -> tuple[str, dict[str, Any]]:
    """
    Normalisation des horaires (Règle 5) :
    - Absents -> ("non renseigné", {"display": "non renseigné", "status": "non renseigné", "daily": "00:00-23:59"})
    - Texte libre analysable (ex: "09:00-18:00", "9h-18h", "8h30 à 19h") ->
      ("confirmés", {"display": raw_hours, "status": "confirmés", "daily": "HH:MM-HH:MM", ...})
    - Texte libre non analysable (ex: "Selon les marées", "Horaires variables selon saison") ->
      ("horaires non confirmés", {"display": "horaires non confirmés", "raw_text": raw_hours, "status": "horaires non confirmés", "daily": "00:00-23:59"})
      Le lieu reste acceptable pour le moteur de validation !
    """
    cleaned = clean_wikitext_value(raw_hours or "")
    if not cleaned or cleaned.lower() in ("non renseigné", "non renseigne", "n/a", "-", "?", "inconnu"):
        return (
            "non renseigné",
            {
                "display": "non renseigné",
                "status": "non renseigné",
                "daily": "00:00-23:59",
            },
        )

    lower = cleaned.lower()
    if any(tok in lower for tok in ("24h/24", "24/7", "24 hours", "toute la journée", "accès libre")):
        return (
            "confirmés",
            {
                "display": cleaned,
                "raw_text": cleaned,
                "status": "confirmés",
                "daily": "00:00-23:59",
            },
        )

    # Recherche d'une plage horaire explicite : ex "09:00-18:00", "9h-18h", "09h30 à 19h00", "9:00 - 17:30"
    pattern = re.compile(
        r"\b([01]?\d|2[0-3])\s*(?:h|:)\s*([0-5]\d)?\s*(?:-|–|—|à|au|to|/)\s*([01]?\d|2[0-3]|24)\s*(?:h|:)?\s*([0-5]\d)?\b",
        re.IGNORECASE,
    )
    match = pattern.search(cleaned)
    if match:
        oh = int(match.group(1))
        om = int(match.group(2) or 0)
        ch = int(match.group(3))
        cm = int(match.group(4) or 0)
        if ch == 24:
            ch, cm = 23, 59
        if 0 <= oh <= 23 and 0 <= ch <= 23:
            if ch * 60 + cm <= oh * 60 + om:
                ch, cm = 23, 59
            daily_range = f"{oh:02d}:{om:02d}-{ch:02d}:{cm:02d}"
            return (
                "confirmés",
                {
                    "display": cleaned,
                    "raw_text": cleaned,
                    "status": "confirmés",
                    "daily": daily_range,
                    "mon": daily_range,
                    "tue": daily_range,
                    "wed": daily_range,
                    "thu": daily_range,
                    "fri": daily_range,
                    "sat": daily_range,
                    "sun": daily_range,
                },
            )

    return (
        "horaires non confirmés",
        {
            "display": "horaires non confirmés",
            "raw_text": cleaned,
            "status": "horaires non confirmés",
            "daily": "00:00-23:59",
        },
    )


def parse_price_text(raw_price: str | None) -> tuple[str, float, str]:
    """
    Normalisation du prix (Règle 5) :
    - Prix absent -> ("non renseigné", 0.0, STANDARD), jamais inventé.
    - Prix présent -> conserve l'intitulé, extrait le montant numérique s'il est explicite.
    """
    cleaned = clean_wikitext_value(raw_price or "")
    if not cleaned or cleaned.lower() in ("non renseigné", "non renseigne", "n/a", "-", "?"):
        return ("non renseigné", 0.0, TravelStyle.STANDARD.value)
    if len(cleaned) > 120:
        cleaned = cleaned[:119].rstrip() + "…"

    lower = cleaned.lower()
    if any(tok in lower for tok in ("gratuit", "free", "entrée libre", "acces libre", "0 €", "0€")):
        return (cleaned, 0.0, TravelStyle.ECONOMIC.value)

    num_match = re.search(r"(\d+(?:[.,]\d{1,2})?)", cleaned)
    if num_match:
        try:
            amount = float(num_match.group(1).replace(",", "."))
            if "tnd" in lower or "dt" in lower or "dinar" in lower:
                amount = round(amount * 0.30, 2)
            tier = (
                TravelStyle.ECONOMIC.value
                if amount <= 10
                else (TravelStyle.LUXURY.value if amount >= 45 else TravelStyle.STANDARD.value)
            )
            return (cleaned, round(amount, 2), tier)
        except ValueError:
            pass

    return (cleaned, 0.0, TravelStyle.STANDARD.value)


def infer_place_subtype_and_category(
    section_kind: str,
    template_name: str,
    type_param: str,
    place_name: str,
    description: str,
) -> tuple[str, str]:
    """
    Déduit (subtype, category) selon la Règle 1 et la Règle 5 :
    - Voir -> CULTURE ou NATURE
    - Manger -> RESTAURANT
    - Boire/Sortir -> NIGHTLIFE
    - Faire -> AUTRE
    """
    combined_text = f"{place_name} {description} {type_param}".lower()
    tpl_lower = template_name.strip().lower()
    type_lower = type_param.strip().lower()
    sec_lower = section_kind.strip().lower()

    if tpl_lower in ("manger", "eat") or type_lower == "eat" or sec_lower == "manger":
        return ("restaurant", PlaceCategory.RESTAURANT.value)

    if (
        tpl_lower in ("sortir", "boire", "boire un verre", "drink", "nightlife")
        or type_lower == "drink"
        or sec_lower in ("boire", "sortir")
    ):
        return ("nightlife", PlaceCategory.NIGHTLIFE.value)

    if tpl_lower in ("faire", "do") or type_lower == "do" or sec_lower == "faire":
        # Si c'est explicitement une plage ou un parc naturel dans Faire, on garde le sous-type pertinent
        if any(k in combined_text for k in ("plage", "beach", "baignade", "crique")):
            return ("plage", PlaceCategory.NATURE.value)
        return ("autre", PlaceCategory.AUTRE.value)

    # Section Voir / See (ou par défaut) -> CULTURE ou NATURE
    if any(k in combined_text for k in ("plage", "beach", "corniche", "crique", "lagune")):
        return ("plage", PlaceCategory.NATURE.value)
    if any(k in combined_text for k in ("réserve naturelle", "reserve naturelle", "nature reserve")):
        return ("réserve naturelle", PlaceCategory.NATURE.value)
    if any(k in combined_text for k in ("jardin", "garden", "botanique")):
        return ("jardin", PlaceCategory.NATURE.value)
    if any(
        k in combined_text
        for k in ("parc", "park", "forêt", "foret", "lac ", "cascade", "belvédère", "miradouro")
    ):
        return ("parc", PlaceCategory.NATURE.value)

    if any(k in combined_text for k in ("musée", "musee", "museum", "galerie", "fondation")):
        return ("musée", PlaceCategory.CULTURE.value)
    if any(k in combined_text for k in ("site archéologique", "ruines", "amphithéâtre", "thermes")):
        return ("site archéologique", PlaceCategory.CULTURE.value)
    if any(k in combined_text for k in ("mosquée", "mosquee", "mosque", "medersa")):
        return ("mosquée", PlaceCategory.CULTURE.value)
    if any(k in combined_text for k in ("église", "eglise", "cathédrale", "cathedrale", "basilique", "monastère", "couvent")):
        return ("église", PlaceCategory.CULTURE.value)
    if any(k in combined_text for k in ("fort", "ribat", "château", "chateau", "citadelle", "kasbah", "remparts", "castelo")):
        return ("fort", PlaceCategory.CULTURE.value)
    if any(k in combined_text for k in ("palais", "palace", "palácio", "palacio", "villa")):
        return ("palais", PlaceCategory.CULTURE.value)
    if any(k in combined_text for k in ("marché", "marche", "souk", "mercado")):
        return ("marché", PlaceCategory.CULTURE.value)
    if any(k in combined_text for k in ("pont ", "bridge", "viaduc")):
        return ("pont", PlaceCategory.CULTURE.value)
    if any(k in combined_text for k in ("place ", "praça", "piazza", "plaza")):
        return ("place", PlaceCategory.CULTURE.value)
    if any(k in combined_text for k in ("tour ", "torre", "tower", "beffroi", "minaret")):
        return ("tour", PlaceCategory.CULTURE.value)

    return ("monument", PlaceCategory.CULTURE.value)


def normalize_duration_and_outdoor(subtype: str, category: str) -> tuple[int, bool]:
    """
    Règle 5 — Durée conseillée par catégorie / sous-type et intérieur/extérieur déduit :
    - musée : 120 min (intérieur)
    - monument : 60 min
    - parc / jardin : 90 min (extérieur)
    - plage : 120 min (extérieur)
    - restaurant : 90 min (intérieur)
    """
    sub = subtype.strip().lower()
    cat = category.strip().upper()

    if sub == "musée":
        return (120, False)
    if sub == "plage":
        return (120, True)
    if sub in ("parc", "jardin", "réserve naturelle"):
        return (90, True)
    if sub == "restaurant" or cat == PlaceCategory.RESTAURANT.value:
        return (90, False)
    if sub == "nightlife" or cat == PlaceCategory.NIGHTLIFE.value:
        return (90, False)
    if sub in ("église", "mosquée", "palais"):
        return (60, False)
    if sub in ("place", "pont", "site archéologique", "fort", "tour", "marché"):
        return (60, True)
    if sub == "monument":
        return (60, False)

    if cat == PlaceCategory.NATURE.value:
        return (90, True)
    if cat == PlaceCategory.CULTURE.value:
        return (60, False)
    return (90, False)


@dataclass
class NormalizedWorldPlace:
    name: str
    description: str
    category: str
    latitude: float
    longitude: float
    is_outdoor: bool = False
    recommended_duration_min: int = 90
    estimated_cost: float = 0.0
    price_tier: str = "FREE"
    price_label: str = "non renseigné"
    hours_status: str = "non renseigné"
    opening_hours: dict[str, Any] = field(default_factory=dict)
    external_place_id: str = ""
    source_provider: str = "wikivoyage_fr"
    subtype: str = "lieu"
    address: str | None = None
    website_url: str | None = None
    source_url: str = ""
    source_attribution: str = WIKIVOYAGE_WIKIPEDIA_ATTRIBUTION
    notoriety_score: float = 0.0
    wikidata_id: str | None = None
    wikipedia_title: str | None = None
    sitelinks_count: int = 0
    hero_photos: list[str] = field(default_factory=list)


WorldPlaceCandidate = NormalizedWorldPlace


@dataclass
class WorldPlacesFetchResult:
    city_name: str
    places: list[NormalizedWorldPlace] = field(default_factory=list)
    radius_km: int = DEFAULT_SEARCH_RADIUS_KM
    few_places_message: str | None = None
    can_expand_radius: bool = False
    suggested_radius_km: int | None = None
    outage_message: str | None = None
    used_sources: list[str] = field(default_factory=list)
    districts_followed: list[str] = field(default_factory=list)
    provider_mode: str = "WIKIVOYAGE_WIKIPEDIA"
    cached_in_redis: bool = False
    cached_in_db: bool = False


WorldCityPlacesResult = WorldPlacesFetchResult


class WorldPlacesService:
    """
    Service Étape 2 — Lieux d'une ville du monde sans clé API :
    1. Wikivoyage (fr puis en) via action=parse + mwparserfromhell + suivi jusqu'à 10 pages de quartiers.
    2. Complément Wikipédia (list=geosearch) filtré par liste blanche touristique Wikidata (P31/P279)
       lorsque la ville a moins de 10 fiches Wikivoyage.
    3. Complément optionnel Overpass (plusieurs miroirs, délai 10s, jamais bloquant, silencieux en cas d'échec).
    4. Normalisation, tri par notoriété (15-20 lieux), dédoublonnage (< 100 m / nom proche),
       message < 5 lieux + rayon 30 km, backoff 1/2/4s sur saturation.
    """

    def __init__(
        self,
        sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
        http_transport: httpx.AsyncBaseTransport | None = None,
        http_client: httpx.AsyncClient | None = None,
        enable_overpass: bool = True,
    ) -> None:
        self._sleep = sleep_func
        if http_transport is None and http_client is not None:
            http_transport = getattr(http_client, "_transport", None)
        self._http_transport = http_transport
        self._enable_overpass = enable_overpass
        self._city_locks: dict[str, asyncio.Lock] = {}
        self._last_request_ts: float = 0.0
        self.last_districts_followed: list[str] = []

    def _get_city_lock(self, key: str) -> asyncio.Lock:
        lock = self._city_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._city_locks[key] = lock
        return lock

    async def _request_json_with_backoff(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        timeout: float = 10.0,
        retry_on_failure: bool = True,
    ) -> dict[str, Any]:
        """
        Exécute une requête HTTP avec User-Agent 'TravelMate/1.0 (contact)' et attente
        croissante (1, 2, 4 s) sur erreur HTTP (429, 502, 503, 504), erreur réseau
        ou saturation MediaWiki ('cirrussearch-too-busy-error', 'maxlag').
        """
        headers = {
            "User-Agent": WORLD_PLACES_USER_AGENT,
            "Accept": "application/json",
        }
        max_attempts = (len(BACKOFF_DELAYS_SECONDS) + 1) if retry_on_failure else 1
        last_exc: Exception | None = None

        for attempt in range(max_attempts):
            try:
                if method.upper() == "POST":
                    resp = await client.post(url, params=params, data=data, headers=headers, timeout=timeout)
                else:
                    resp = await client.get(url, params=params, headers=headers, timeout=timeout)

                if resp.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                resp.raise_for_status()
                payload = resp.json()
                if isinstance(payload, dict) and "error" in payload:
                    err_info = payload.get("error") or {}
                    err_code = str(err_info.get("code") or "")
                    if err_code in ("cirrussearch-too-busy-error", "maxlag", "internal_api_error_DBQueryError"):
                        raise RuntimeError(f"MediaWiki saturation: {err_code}")
                return payload if isinstance(payload, dict) else {}
            except Exception as exc:
                last_exc = exc
                if attempt < len(BACKOFF_DELAYS_SECONDS) and retry_on_failure:
                    delay_s = BACKOFF_DELAYS_SECONDS[attempt]
                    await self._sleep(delay_s)
                else:
                    break

        if last_exc is not None:
            raise last_exc
        return {}

    @staticmethod
    def _section_kind_from_heading(heading_text: str) -> str | None:
        norm = normalize_place_text(heading_text)
        if not norm:
            return None
        if norm in ("voir", "a voir", "see", "monuments", "musees", "sites touristiques"):
            return "voir"
        if norm in ("faire", "a faire", "do", "activites", "activities"):
            return "faire"
        if norm in ("manger", "ou manger", "eat", "restaurants", "gastronomie"):
            return "manger"
        if norm in (
            "boire un verre",
            "boire",
            "sortir",
            "boire un verre sortir",
            "boire et sortir",
            "drink",
            "nightlife",
            "bars",
            "vie nocturne",
        ):
            return "sortir"
        if norm in ("se loger", "ou dormir", "hebergement", "sleep", "hotels"):
            return "se loger"
        if norm in ("quartiers", "districts", "arrondissements"):
            return "quartiers"
        return None

    @staticmethod
    def _get_template_param(template: mwparserfromhell.nodes.Template, *names: str) -> str:
        for name in names:
            for param in template.params:
                p_name = str(param.name).strip().lower()
                if p_name == name.lower():
                    return clean_wikitext_value(str(param.value))
        return ""

    @staticmethod
    def _extract_district_links_from_wikitext(
        city_title: str,
        wikitext: str,
        api_links: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        """
        Règle 2 : Détecte les liens vers les sous-pages de quartiers (ex: Lisbonne/Alfama, Lisbonne/Chiado...)
        dans le wikitext et dans la liste des liens de la page. Limite à MAX_DISTRICT_PAGES (10).
        """
        city_clean = city_title.strip().replace("_", " ")
        prefix_lower = f"{city_clean.lower()}/"
        districts: list[str] = []
        seen: set[str] = set()

        def _add_candidate(target: str) -> None:
            t_clean = target.split("#")[0].strip().replace("_", " ")
            if not t_clean:
                return
            t_lower = t_clean.lower()
            if not t_lower.startswith(prefix_lower):
                return
            sub_part = t_clean[len(city_clean) + 1 :].strip()
            if not sub_part or "/" in sub_part:
                return
            if t_lower not in seen and len(districts) < MAX_DISTRICT_PAGES:
                seen.add(t_lower)
                districts.append(t_clean)

        try:
            wikicode = mwparserfromhell.parse(wikitext)
            for wikilink in wikicode.filter_wikilinks():
                _add_candidate(str(wikilink.title))
        except Exception:
            pass

        if api_links:
            for link_obj in api_links:
                title_val = str(link_obj.get("*") or link_obj.get("title") or "")
                _add_candidate(title_val)

        return districts[:MAX_DISTRICT_PAGES]

    def parse_wikivoyage_wikitext(
        self,
        wikitext: str,
        *,
        page_title: str,
        lang: str,
        city_lat: float,
        city_lon: float,
    ) -> list[NormalizedWorldPlace]:
        """
        Règle 1 : Analyse le wikitext avec mwparserfromhell (pas une simple expression régulière) :
        - Modèles Listing / Voir / Manger / Sortir / Faire / Se loger et leurs alias fr/en
        - Avec ou sans "nom=" en premier (paramètre nommé nom/name ou paramètre positionnel 1)
        - Déduit la catégorie de la section ou du modèle :
          Voir -> CULTURE ou NATURE, Manger -> RESTAURANT, Boire/Sortir -> NIGHTLIFE, Faire -> AUTRE.
        """
        if not wikitext or not wikitext.strip():
            return []

        normalized_lines = [
            line.lstrip() if line.lstrip().startswith(("=", "*", "{", "[")) else line
            for line in wikitext.splitlines()
        ]
        wikicode = mwparserfromhell.parse("\n".join(normalized_lines))
        current_section = "voir"
        extracted: list[NormalizedWorldPlace] = []
        sleep_section_places: list[NormalizedWorldPlace] = []
        coord_offset_idx = 0

        for node in wikicode.nodes:
            if isinstance(node, mwparserfromhell.nodes.Heading):
                heading_title = clean_wikitext_value(str(node.title))
                sec_kind = self._section_kind_from_heading(heading_title)
                if sec_kind in ("voir", "faire", "manger", "sortir", "se loger"):
                    current_section = sec_kind
                continue

            # Cherche les templates dans ce noeud (ou si le noeud est lui-même un Template)
            templates: list[mwparserfromhell.nodes.Template] = []
            if isinstance(node, mwparserfromhell.nodes.Template):
                templates = [node]
            else:
                try:
                    templates = mwparserfromhell.parse(str(node)).filter_templates(recursive=True)
                except Exception:
                    templates = []

            for tpl in templates:
                raw_tpl_name = clean_wikitext_value(str(tpl.name)).lower()
                tpl_name = re.sub(r"\s+", " ", raw_tpl_name).strip()
                if tpl_name not in WIKIVOYAGE_LISTING_TEMPLATES:
                    continue

                type_param = self._get_template_param(tpl, "type")
                nom = self._get_template_param(tpl, "nom", "name")
                pos1 = self._get_template_param(tpl, "1")
                pos2 = self._get_template_param(tpl, "2")

                if not nom:
                    if (
                        pos1.lower() in WIKIVOYAGE_LISTING_TEMPLATES
                        and pos2
                    ):
                        if not type_param:
                            type_param = pos1
                        nom = pos2
                    else:
                        nom = pos1

                if not nom:
                    continue

                adresse = self._get_template_param(tpl, "adresse", "address", "directions")
                horaires_raw = self._get_template_param(tpl, "horaire", "horaires", "hours")
                prix_raw = self._get_template_param(tpl, "prix", "price")
                description_raw = self._get_template_param(tpl, "description", "content")
                if not description_raw and pos2 and nom != pos2:
                    description_raw = pos2
                site_web = self._get_template_param(tpl, "url", "site", "website", "web")
                wikidata_id = self._get_template_param(tpl, "wikidata")
                wikipedia_ref = self._get_template_param(tpl, "wikipedia", "wikipédia")

                lat_raw = self._get_template_param(tpl, "lat", "latitude")
                lon_raw = self._get_template_param(tpl, "long", "lon", "lng", "longitude")

                lat_val: float | None = None
                lon_val: float | None = None
                try:
                    if lat_raw and lon_raw:
                        lat_val = float(lat_raw.replace(",", "."))
                        lon_val = float(lon_raw.replace(",", "."))
                except ValueError:
                    lat_val = None
                    lon_val = None

                has_explicit_coords = lat_val is not None and lon_val is not None
                if lat_val is None or lon_val is None:
                    coord_offset_idx += 1
                    angle = (coord_offset_idx * 137.5) * (math.pi / 180.0)
                    radius_deg = 0.003 * (1 + (coord_offset_idx % 5))
                    lat_val = round(city_lat + radius_deg * math.cos(angle), 6)
                    lon_val = round(city_lon + radius_deg * math.sin(angle), 6)

                is_sleep_item = (
                    current_section == "se loger"
                    or tpl_name in ("se loger", "sleep")
                    or type_param.lower() in ("sleep", "se loger")
                )
                if is_sleep_item:
                    subtype, category = ("autre", PlaceCategory.AUTRE.value)
                else:
                    subtype, category = infer_place_subtype_and_category(
                        section_kind=current_section,
                        template_name=tpl_name,
                        type_param=type_param,
                        place_name=nom,
                        description=description_raw,
                    )
                duration_min, is_outdoor = normalize_duration_and_outdoor(subtype, category)
                hours_status, opening_hours = parse_opening_hours_text(horaires_raw)
                norm_qid = wikidata_id.upper() if (wikidata_id and wikidata_id.upper().startswith("Q")) else None
                if norm_qid:
                    opening_hours["_wikidata_id"] = norm_qid
                if wikipedia_ref:
                    opening_hours["_wikipedia_title"] = wikipedia_ref
                    opening_hours["_wikipedia_lang"] = lang
                opening_hours["_has_explicit_coords"] = "true" if has_explicit_coords else "false"
                price_label, estimated_cost, price_tier = parse_price_text(prix_raw)

                description = description_raw or f"Lieu d'intérêt ({subtype}) à découvrir à {page_title.split('/')[0]}."

                # Notoriété : article Wikipédia, identifiant Wikidata, description, coordonnées, site, horaires
                notoriety = 20 if is_sleep_item else 40
                if wikipedia_ref:
                    notoriety += 100
                if norm_qid:
                    notoriety += 35
                if len(description_raw) >= 40:
                    notoriety += 15
                if has_explicit_coords:
                    notoriety += 10
                if site_web:
                    notoriety += 5
                if hours_status == "confirmés":
                    notoriety += 5

                encoded_page = quote(page_title.replace(" ", "_"), safe="/:")
                source_url = f"https://{lang}.wikivoyage.org/wiki/{encoded_page}"
                slug = hashlib.sha1(f"{lang}:{page_title}:{normalize_place_text(nom)}".encode("utf-8")).hexdigest()[:16]
                ext_id = norm_qid if norm_qid else f"wv_{lang}_{slug}"

                place_obj = NormalizedWorldPlace(
                    external_place_id=ext_id,
                    source_provider=f"wikivoyage_{lang}",
                    name=nom,
                    description=description,
                    category=category,
                    subtype=subtype,
                    is_outdoor=is_outdoor,
                    latitude=lat_val,
                    longitude=lon_val,
                    recommended_duration_min=duration_min,
                    estimated_cost=estimated_cost,
                    price_tier=price_tier,
                    price_label=price_label,
                    hours_status=hours_status,
                    opening_hours=opening_hours,
                    address=adresse or None,
                    website_url=site_web or None,
                    source_url=source_url,
                    source_attribution="Données Wikivoyage / Wikipédia (CC BY-SA 4.0)",
                    notoriety_score=notoriety,
                    wikidata_id=norm_qid,
                    wikipedia_title=wikipedia_ref or None,
                    sitelinks_count=0,
                    hero_photos=[],
                )
                if current_section == "se loger":
                    sleep_section_places.append(place_obj)
                else:
                    extracted.append(place_obj)

        return extracted if extracted else sleep_section_places

    async def _fetch_wikivoyage_page(
        self,
        client: httpx.AsyncClient,
        lang: str,
        page_title: str,
        *,
        timeout: float = 10.0,
        retry_on_failure: bool = True,
    ) -> tuple[str, str, list[dict[str, Any]]]:
        """
        Récupère le wikitext et les liens d'une page Wikivoyage via action=parse.
        Si le titre exact n'existe pas, cherche le titre via list=search.
        """
        api_url = f"https://{lang}.wikivoyage.org/w/api.php"
        params = {
            "action": "parse",
            "page": page_title,
            "prop": "wikitext|links|sections",
            "redirects": "1",
            "format": "json",
        }
        data = await self._request_json_with_backoff(
            client,
            "GET",
            api_url,
            params=params,
            timeout=timeout,
            retry_on_failure=retry_on_failure,
        )
        parse_obj = data.get("parse")
        if not isinstance(parse_obj, dict):
            # Fallback : recherche du titre dans Wikivoyage
            search_params = {
                "action": "query",
                "list": "search",
                "srsearch": page_title,
                "srlimit": "3",
                "format": "json",
            }
            search_data = await self._request_json_with_backoff(
                client,
                "GET",
                api_url,
                params=search_params,
                timeout=timeout,
                retry_on_failure=retry_on_failure,
            )
            hits = ((search_data.get("query") or {}).get("search")) or []
            norm_wanted = normalize_place_text(page_title)
            matched_title = None
            for hit in hits:
                cand_title = str(hit.get("title") or "")
                if normalize_place_text(cand_title) == norm_wanted or norm_wanted in normalize_place_text(cand_title):
                    matched_title = cand_title
                    break
            if not matched_title:
                return ("", "", [])
            params["page"] = matched_title
            data = await self._request_json_with_backoff(
                client,
                "GET",
                api_url,
                params=params,
                timeout=timeout,
                retry_on_failure=retry_on_failure,
            )
            parse_obj = data.get("parse")
            if not isinstance(parse_obj, dict):
                return ("", "", [])

        resolved_title = str(parse_obj.get("title") or page_title)
        wikitext_obj = parse_obj.get("wikitext")
        if isinstance(wikitext_obj, dict):
            wikitext = str(wikitext_obj.get("*") or "")
        else:
            wikitext = str(wikitext_obj or "")
        links_list = parse_obj.get("links")
        return (resolved_title, wikitext, links_list if isinstance(links_list, list) else [])

    async def fetch_wikivoyage_city_places(
        self,
        client: httpx.AsyncClient,
        city_name: str,
        city_lat: float,
        city_lon: float,
    ) -> list[NormalizedWorldPlace]:
        """
        Règles 1 & 2 :
        - Essaie fr.wikivoyage.org, puis en.wikivoyage.org si absent.
        - Suit jusqu'à 10 pages de quartiers (ex. Lisbonne/Alfama, Lisbonne/Chiado...) et agrège leurs fiches.
        """
        all_places: list[NormalizedWorldPlace] = []
        self.last_districts_followed = []

        for lang in ("fr", "en"):
            resolved_title, wikitext, links = await self._fetch_wikivoyage_page(client, lang, city_name)
            if not wikitext:
                continue

            main_places = self.parse_wikivoyage_wikitext(
                wikitext,
                page_title=resolved_title,
                lang=lang,
                city_lat=city_lat,
                city_lon=city_lon,
            )
            all_places.extend(main_places)

            district_titles = self._extract_district_links_from_wikitext(
                resolved_title,
                wikitext,
                api_links=links,
            )
            for district_title in district_titles[:MAX_DISTRICT_PAGES]:
                try:
                    d_title, d_wikitext, _ = await self._fetch_wikivoyage_page(client, lang, district_title)
                    if d_wikitext:
                        self.last_districts_followed.append(d_title or district_title)
                        d_places = self.parse_wikivoyage_wikitext(
                            d_wikitext,
                            page_title=d_title or district_title,
                            lang=lang,
                            city_lat=city_lat,
                            city_lon=city_lon,
                        )
                        all_places.extend(d_places)
                except Exception:
                    continue

            if all_places:
                # Enrichissement optionnel par le nombre de langues Wikidata (sitelinks) pour le tri par notoriété
                qids = list(
                    dict.fromkeys(
                        p.wikidata_id
                        for p in all_places
                        if p.wikidata_id and p.wikidata_id.startswith("Q")
                    )
                )
                if qids:
                    try:
                        wd_data = await self._request_json_with_backoff(
                            client,
                            "GET",
                            "https://www.wikidata.org/w/api.php",
                            params={
                                "action": "wbgetentities",
                                "ids": "|".join(qids[:50]),
                                "props": "sitelinks",
                                "format": "json",
                            },
                            retry_on_failure=False,
                        )
                        entities = wd_data.get("entities") or {}
                        if isinstance(entities, dict):
                            for p in all_places:
                                if p.wikidata_id and p.wikidata_id in entities:
                                    ent = entities.get(p.wikidata_id) or {}
                                    slinks = ent.get("sitelinks") or {}
                                    if isinstance(slinks, dict):
                                        p.sitelinks_count = len(slinks)
                                        p.notoriety_score += len(slinks) * 2
                    except Exception:
                        pass
                break

        return all_places

    @staticmethod
    def _extract_wikidata_qids_from_claims(claims: dict[str, Any], prop_id: str) -> list[str]:
        qids: list[str] = []
        for statement in claims.get(prop_id) or []:
            mainsnak = (statement or {}).get("mainsnak") or {}
            datavalue = mainsnak.get("datavalue") or {}
            val = datavalue.get("value")
            if isinstance(val, dict) and val.get("id"):
                qids.append(str(val["id"]).upper())
        return qids

    @classmethod
    def classify_wikidata_entity(
        cls,
        *,
        article_title: str,
        city_name: str,
        entity_data: dict[str, Any],
        class_entities: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[bool, str, str]:
        """
        Règle 3 : Filtre un article Wikipédia via Wikidata (P31 instance de + P279 sous-classe de).
        - Exclus : événements, personnes, batailles, compétitions/tournois (ex: tournoi de tennis),
          communes et la ville elle-même.
        - Garde uniquement la liste blanche touristique :
          monument, musée, site archéologique, mosquée, église, fort, palais, parc, plage,
          jardin, place, pont, tour, marché, réserve naturelle.
        """
        norm_title = normalize_place_text(article_title)
        norm_city = normalize_place_text(city_name)
        if not norm_title or norm_title == norm_city or norm_title in (f"ville de {norm_city}", f"{norm_city} tunisie"):
            return (False, "", "")

        title_lower = article_title.lower()
        if any(bad in title_lower for bad in WIKIDATA_EXCLUDED_KEYWORDS):
            return (False, "", "")

        claims = entity_data.get("claims") or {}
        p31_qids = cls._extract_wikidata_qids_from_claims(claims, "P31")
        p279_qids = cls._extract_wikidata_qids_from_claims(claims, "P279")

        all_qids: list[str] = list(dict.fromkeys(p31_qids + p279_qids))
        if class_entities:
            for qid in list(all_qids):
                cls_entity = class_entities.get(qid) or {}
                cls_claims = cls_entity.get("claims") or {}
                sub_qids = cls._extract_wikidata_qids_from_claims(cls_claims, "P279")
                for sq in sub_qids:
                    if sq not in all_qids:
                        all_qids.append(sq)

        # 1. Vérification des QIDs exclus
        for qid in all_qids:
            if qid in WIKIDATA_EXCLUDED_QIDS:
                return (False, "", "")

        # 2. Vérification des labels/descriptions des classes P31/P279 et de l'entité
        labels_text_parts: list[str] = []
        for lang_key in ("fr", "en"):
            lbl = ((entity_data.get("labels") or {}).get(lang_key) or {}).get("value")
            desc = ((entity_data.get("descriptions") or {}).get(lang_key) or {}).get("value")
            if lbl:
                labels_text_parts.append(str(lbl))
            if desc:
                labels_text_parts.append(str(desc))

        if class_entities:
            for qid in all_qids:
                cls_ent = class_entities.get(qid) or {}
                for lang_key in ("fr", "en"):
                    c_lbl = ((cls_ent.get("labels") or {}).get(lang_key) or {}).get("value")
                    if c_lbl:
                        labels_text_parts.append(str(c_lbl))

        combined_meta_lower = " ".join(labels_text_parts).lower()
        if any(bad in combined_meta_lower for bad in WIKIDATA_EXCLUDED_KEYWORDS):
            return (False, "", "")

        # 3. Correspondance directe sur les Q-IDs de la liste blanche touristique
        for qid in all_qids:
            if qid in WIKIDATA_TOURIST_WHITELIST_QIDS:
                subtype, category = WIKIDATA_TOURIST_WHITELIST_QIDS[qid]
                return (True, subtype, category)

        # 4. Correspondance par libellés de classes P31/P279 ou description Wikidata
        if all_qids or combined_meta_lower:
            for kw, subtype, category in WIKIDATA_TOURIST_WHITELIST_KEYWORDS:
                if kw in combined_meta_lower:
                    return (True, subtype, category)

        return (False, "", "")

    async def fetch_wikipedia_wikidata_places(
        self,
        client: httpx.AsyncClient,
        city_name: str,
        city_lat: float,
        city_lon: float,
        radius_km: int = DEFAULT_SEARCH_RADIUS_KM,
    ) -> list[NormalizedWorldPlace]:
        """
        Règle 3 : Complément pour les petites villes (< 10 fiches Wikivoyage) :
        Wikipédia (list=geosearch, 10 km ou 30 km) filtré par Wikidata (P31 + sous-classes P279).
        """
        radius_m = min(max(int(radius_km * 1000), 1000), 30000)
        wp_api_url = "https://fr.wikipedia.org/w/api.php"

        geo_params = {
            "action": "query",
            "list": "geosearch",
            "gscoord": f"{city_lat}|{city_lon}",
            "gsradius": str(radius_m),
            "gslimit": "50",
            "format": "json",
        }
        geo_data = await self._request_json_with_backoff(client, "GET", wp_api_url, params=geo_params)
        geo_items = ((geo_data.get("query") or {}).get("geosearch")) or []
        if not geo_items:
            return []

        page_ids = [str(item.get("pageid")) for item in geo_items if item.get("pageid")]
        if not page_ids:
            return []

        # Récupère pageprops (wikibase_item), extrait et URL complète
        pages_params = {
            "action": "query",
            "pageids": "|".join(page_ids[:50]),
            "prop": "pageprops|info|extracts|coordinates",
            "inprop": "url",
            "exintro": "1",
            "explaintext": "1",
            "format": "json",
        }
        pages_data = await self._request_json_with_backoff(client, "GET", wp_api_url, params=pages_params)
        pages_dict = ((pages_data.get("query") or {}).get("pages")) or {}

        geo_by_pageid = {str(item.get("pageid")): item for item in geo_items}
        qid_to_page: dict[str, dict[str, Any]] = {}
        for pid, pinfo in pages_dict.items():
            if not isinstance(pinfo, dict):
                continue
            q_id = str(((pinfo.get("pageprops") or {}).get("wikibase_item")) or "").upper()
            if q_id.startswith("Q"):
                qid_to_page[q_id] = pinfo

        if not qid_to_page:
            return []

        # Interroge Wikidata wbgetentities pour les Q-IDs trouvés
        wd_api_url = "https://www.wikidata.org/w/api.php"
        wd_params = {
            "action": "wbgetentities",
            "ids": "|".join(list(qid_to_page.keys())[:50]),
            "props": "claims|labels|descriptions|sitelinks",
            "languages": "fr|en",
            "format": "json",
        }
        wd_data = await self._request_json_with_backoff(client, "GET", wd_api_url, params=wd_params)
        entities = wd_data.get("entities") or {}

        # Collecte les Q-IDs des classes P31 qui ne sont pas encore directement connus pour inspecter leur P279 (sous-classe de)
        unknown_class_qids: list[str] = []
        for q_id, ent in entities.items():
            if not isinstance(ent, dict):
                continue
            p31_list = self._extract_wikidata_qids_from_claims(ent.get("claims") or {}, "P31")
            for c_qid in p31_list:
                if (
                    c_qid not in WIKIDATA_TOURIST_WHITELIST_QIDS
                    and c_qid not in WIKIDATA_EXCLUDED_QIDS
                    and c_qid not in unknown_class_qids
                ):
                    unknown_class_qids.append(c_qid)

        class_entities: dict[str, dict[str, Any]] = {}
        if unknown_class_qids:
            try:
                cls_params = {
                    "action": "wbgetentities",
                    "ids": "|".join(unknown_class_qids[:40]),
                    "props": "claims|labels",
                    "languages": "fr|en",
                    "format": "json",
                }
                cls_data = await self._request_json_with_backoff(client, "GET", wd_api_url, params=cls_params)
                raw_cls_entities = cls_data.get("entities") or {}
                if isinstance(raw_cls_entities, dict):
                    class_entities = raw_cls_entities
            except Exception:
                class_entities = {}

        results: list[NormalizedWorldPlace] = []
        for q_id, pinfo in qid_to_page.items():
            ent = entities.get(q_id)
            if not isinstance(ent, dict):
                continue
            title = str(pinfo.get("title") or "").strip()
            allowed, subtype, category = self.classify_wikidata_entity(
                article_title=title,
                city_name=city_name,
                entity_data=ent,
                class_entities=class_entities,
            )
            if not allowed:
                continue

            pid_str = str(pinfo.get("pageid") or "")
            geo_entry = geo_by_pageid.get(pid_str) or {}
            coords_list = pinfo.get("coordinates") or []
            lat = float(
                (coords_list[0].get("lat") if coords_list else None)
                or geo_entry.get("lat")
                or city_lat
            )
            lon = float(
                (coords_list[0].get("lon") if coords_list else None)
                or geo_entry.get("lon")
                or city_lon
            )

            extract_text = clean_wikitext_value(str(pinfo.get("extract") or ""))
            if len(extract_text) > 280:
                extract_text = extract_text[:277].rstrip() + "..."
            if not extract_text:
                fr_desc = ((ent.get("descriptions") or {}).get("fr") or {}).get("value")
                extract_text = str(fr_desc or f"Site d'intérêt ({subtype}) à {city_name}.")

            sitelinks = ent.get("sitelinks") or {}
            sitelinks_count = len(sitelinks) if isinstance(sitelinks, dict) else 0
            notoriety = 100 + (sitelinks_count * 2) + 20

            duration_min, is_outdoor = normalize_duration_and_outdoor(subtype, category)
            hours_status, opening_hours = parse_opening_hours_text(None)
            opening_hours["_wikidata_id"] = q_id
            opening_hours["_wikipedia_title"] = title
            opening_hours["_wikipedia_lang"] = "fr"
            opening_hours["_has_explicit_coords"] = "true"
            price_label, estimated_cost, price_tier = parse_price_text(None)

            full_url = str(pinfo.get("fullurl") or f"https://fr.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}")

            results.append(
                NormalizedWorldPlace(
                    external_place_id=q_id,
                    source_provider="wikipedia_wikidata",
                    name=title,
                    description=extract_text,
                    category=category,
                    subtype=subtype,
                    is_outdoor=is_outdoor,
                    latitude=lat,
                    longitude=lon,
                    recommended_duration_min=duration_min,
                    estimated_cost=estimated_cost,
                    price_tier=price_tier,
                    price_label=price_label,
                    hours_status=hours_status,
                    opening_hours=opening_hours,
                    address=None,
                    website_url=None,
                    source_url=full_url,
                    source_attribution="Données Wikivoyage / Wikipédia (CC BY-SA 4.0)",
                    notoriety_score=notoriety,
                    wikidata_id=q_id,
                    wikipedia_title=title,
                    sitelinks_count=sitelinks_count,
                    hero_photos=[],
                )
            )

        return results

    async def fetch_overpass_optional_places(
        self,
        client: httpx.AsyncClient,
        city_name: str,
        city_lat: float,
        city_lon: float,
        radius_km: int = DEFAULT_SEARCH_RADIUS_KM,
    ) -> list[NormalizedWorldPlace]:
        """
        Règle 4 : Complément optionnel Overpass (plusieurs miroirs), délai de 10 s, jamais bloquant.
        S'il échoue : aucun message, aucune attente.
        """
        if not self._enable_overpass:
            return []

        radius_m = min(max(int(radius_km * 1000), 1000), 30000)
        overpass_query = (
            f"[out:json][timeout:8];"
            f"("
            f'nwr["tourism"~"museum|attraction|viewpoint|gallery"](around:{radius_m},{city_lat},{city_lon});'
            f'nwr["historic"~"monument|castle|archaeological_site|fort|ruins"](around:{radius_m},{city_lat},{city_lon});'
            f");"
            f"out center 25;"
        )

        for mirror_url in OVERPASS_MIRRORS:
            try:
                data = await self._request_json_with_backoff(
                    client,
                    "POST",
                    mirror_url,
                    data={"data": overpass_query},
                    timeout=OVERPASS_TIMEOUT_SECONDS,
                    retry_on_failure=False,
                )
                elements = data.get("elements")
                if not isinstance(elements, list) or not elements:
                    continue

                places: list[NormalizedWorldPlace] = []
                for el in elements:
                    if not isinstance(el, dict):
                        continue
                    tags = el.get("tags") or {}
                    name = str(tags.get("name:fr") or tags.get("name") or "").strip()
                    if not name:
                        continue
                    lat = el.get("lat") or (el.get("center") or {}).get("lat")
                    lon = el.get("lon") or (el.get("center") or {}).get("lon")
                    if lat is None or lon is None:
                        continue

                    tourism_tag = str(tags.get("tourism") or tags.get("historic") or "")
                    subtype, category = infer_place_subtype_and_category(
                        section_kind="voir",
                        template_name="voir",
                        type_param=tourism_tag,
                        place_name=name,
                        description=str(tags.get("description") or ""),
                    )
                    duration_min, is_outdoor = normalize_duration_and_outdoor(subtype, category)
                    hours_status, opening_hours = parse_opening_hours_text(tags.get("opening_hours"))
                    price_label, estimated_cost, price_tier = parse_price_text(tags.get("fee"))
                    osm_type = str(el.get("type") or "node")
                    osm_id = str(el.get("id") or "")
                    wikidata_id = str(tags.get("wikidata") or "").upper() or None
                    wikipedia_tag = str(tags.get("wikipedia") or "")
                    if wikidata_id and wikidata_id.startswith("Q"):
                        opening_hours["_wikidata_id"] = wikidata_id
                    if wikipedia_tag:
                        opening_hours["_wikipedia_title"] = wikipedia_tag
                    opening_hours["_has_explicit_coords"] = "true"

                    notoriety = 25
                    if wikipedia_tag:
                        notoriety += 100
                    if wikidata_id:
                        notoriety += 25

                    places.append(
                        NormalizedWorldPlace(
                            external_place_id=f"osm_{osm_type}_{osm_id}",
                            source_provider="overpass_osm",
                            name=name,
                            description=str(
                                tags.get("description:fr")
                                or tags.get("description")
                                or f"Point d'intérêt ({subtype}) à {city_name}."
                            ),
                            category=category,
                            subtype=subtype,
                            is_outdoor=is_outdoor,
                            latitude=float(lat),
                            longitude=float(lon),
                            recommended_duration_min=duration_min,
                            estimated_cost=estimated_cost,
                            price_tier=price_tier,
                            price_label=price_label,
                            hours_status=hours_status,
                            opening_hours=opening_hours,
                            address=str(tags.get("addr:street") or "") or None,
                            website_url=str(tags.get("website") or "") or None,
                            source_url=f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
                            source_attribution="Données Wikivoyage / Wikipédia (CC BY-SA 4.0) • contributeurs OpenStreetMap (ODbL)",
                            notoriety_score=notoriety,
                            wikidata_id=wikidata_id,
                            wikipedia_title=wikipedia_tag or None,
                            sitelinks_count=0,
                            hero_photos=[],
                        )
                    )
                if places:
                    return places
            except Exception:
                # Règle 4 : Jamais bloquant, aucun message d'erreur ni attente
                continue

        return []

    @staticmethod
    def deduplicate_and_select_places(
        candidates: list[NormalizedWorldPlace],
        max_places: int = MAX_SELECTED_PLACES,
    ) -> list[NormalizedWorldPlace]:
        """
        Règle 6 :
        - Ignore les fiches sans nom
        - Dédoublonnage (nom proche OU distance < 100 m avec nom similaire OU même wikidata_id)
        - Tri par notoriété décroissante (article Wikipédia, nombre de langues Wikidata)
        - Sélectionne jusqu'à 20 lieux (15 à 20 lieux).
        """
        deduped: list[NormalizedWorldPlace] = []

        for item in candidates:
            if not item.name or not item.name.strip():
                continue
            norm_name = normalize_place_text(item.name)
            if not norm_name:
                continue

            merged = False
            for idx, existing in enumerate(deduped):
                existing_norm = normalize_place_text(existing.name)
                same_wikidata = bool(
                    item.wikidata_id
                    and existing.wikidata_id
                    and item.wikidata_id == existing.wikidata_id
                )
                diff_wikidata = bool(
                    item.wikidata_id
                    and existing.wikidata_id
                    and item.wikidata_id != existing.wikidata_id
                )
                diff_numbers = re.findall(r"\d+", norm_name) != re.findall(r"\d+", existing_norm)
                name_ratio = SequenceMatcher(None, norm_name, existing_norm).ratio()
                substring_match = (
                    len(norm_name) >= 5
                    and len(existing_norm) >= 5
                    and (norm_name in existing_norm or existing_norm in norm_name)
                )
                dist_m = (
                    haversine_distance_km(
                        item.latitude,
                        item.longitude,
                        existing.latitude,
                        existing.longitude,
                    )
                    * 1000.0
                )

                is_duplicate = same_wikidata or (
                    not diff_wikidata
                    and not diff_numbers
                    and (
                        norm_name == existing_norm
                        or (dist_m < 100.0 and (name_ratio >= 0.52 or substring_match))
                        or (dist_m < 250.0 and name_ratio >= 0.88)
                    )
                )
                if is_duplicate:
                    # Fusionne en conservant la meilleure notoriété et les champs renseignés
                    best = item if item.notoriety_score > existing.notoriety_score else existing
                    other = existing if best is item else item
                    if best.hours_status == "non renseigné" and other.hours_status != "non renseigné":
                        best.hours_status = other.hours_status
                        for k, v in other.opening_hours.items():
                            if not k.startswith("_") or k not in best.opening_hours:
                                best.opening_hours[k] = v
                    if not best.wikidata_id and other.wikidata_id:
                        best.wikidata_id = other.wikidata_id
                        best.opening_hours["_wikidata_id"] = other.wikidata_id
                        if best.external_place_id.startswith("wv_"):
                            best.external_place_id = other.wikidata_id
                    if not best.wikipedia_title and other.wikipedia_title:
                        best.wikipedia_title = other.wikipedia_title
                        best.opening_hours["_wikipedia_title"] = other.wikipedia_title
                        if "_wikipedia_lang" in other.opening_hours and "_wikipedia_lang" not in best.opening_hours:
                            best.opening_hours["_wikipedia_lang"] = other.opening_hours["_wikipedia_lang"]
                    if best.price_label == "non renseigné" and other.price_label != "non renseigné":
                        best.price_label = other.price_label
                        best.estimated_cost = other.estimated_cost
                        best.price_tier = other.price_tier
                    if not best.address and other.address:
                        best.address = other.address
                    if not best.website_url and other.website_url:
                        best.website_url = other.website_url
                    if "OpenStreetMap" in other.source_attribution and "OpenStreetMap" not in best.source_attribution:
                        best.source_attribution = (
                            "Données Wikivoyage / Wikipédia (CC BY-SA 4.0) • contributeurs OpenStreetMap (ODbL)"
                        )
                    best.notoriety_score = max(best.notoriety_score, other.notoriety_score)
                    deduped[idx] = best
                    merged = True
                    break

            if not merged:
                deduped.append(item)

        deduped.sort(
            key=lambda p: (
                p.notoriety_score,
                1 if p.wikipedia_title else 0,
                p.sitelinks_count,
                len(p.description or ""),
            ),
            reverse=True,
        )
        return deduped[:max_places]

    async def fetch_city_places(
        self,
        *,
        city_name: str,
        city_lat: float | None = None,
        city_lon: float | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        country_name: str | None = None,
        radius_km: int = DEFAULT_SEARCH_RADIUS_KM,
    ) -> WorldPlacesFetchResult:
        """
        Orchestre la récupération des lieux d'une ville du monde :
        1. Wikivoyage (fr puis en) + jusqu'à 10 pages de quartiers.
        2. Si < 10 fiches (ou si rayon élargi à 30 km) : complément Wikipédia geosearch filtré par Wikidata P31/P279.
        3. Si toujours < 10 fiches : complément optionnel Overpass (10 s max, jamais bloquant).
        4. Dédoublonnage, tri par notoriété (max 20 lieux), gestion du message < 5 lieux et des pannes.
        """
        lat_val = float(city_lat if city_lat is not None else (latitude if latitude is not None else 0.0))
        lon_val = float(city_lon if city_lon is not None else (longitude if longitude is not None else 0.0))
        lock_key = f"{normalize_place_text(city_name)}:{radius_km}"
        async with self._get_city_lock(lock_key):
            candidates: list[NormalizedWorldPlace] = []
            used_sources: list[str] = []
            any_primary_source_succeeded = False

            async with httpx.AsyncClient(transport=self._http_transport) as client:
                # 1. Source principale : Wikivoyage
                try:
                    wv_places = await self.fetch_wikivoyage_city_places(
                        client,
                        city_name=city_name,
                        city_lat=lat_val,
                        city_lon=lon_val,
                    )
                    any_primary_source_succeeded = True
                    if wv_places:
                        candidates.extend(wv_places)
                        used_sources.append("wikivoyage")
                except Exception:
                    wv_places = []

                preliminary = self.deduplicate_and_select_places(candidates, max_places=MAX_SELECTED_PLACES)

                # 2. Complément petites villes (< 10 fiches) ou rayon élargi (30 km) : Wikipédia + Wikidata
                if len(preliminary) < MIN_WIKIVOYAGE_BEFORE_WIKIPEDIA or radius_km > DEFAULT_SEARCH_RADIUS_KM:
                    try:
                        wp_places = await self.fetch_wikipedia_wikidata_places(
                            client,
                            city_name=city_name,
                            city_lat=lat_val,
                            city_lon=lon_val,
                            radius_km=radius_km,
                        )
                        any_primary_source_succeeded = True
                        if wp_places:
                            candidates.extend(wp_places)
                            used_sources.append("wikipedia")
                    except Exception:
                        pass

                preliminary = self.deduplicate_and_select_places(candidates, max_places=MAX_SELECTED_PLACES)

                # 3. Complément optionnel : Overpass (10s max, non bloquant, silencieux en cas d'échec)
                if len(preliminary) < MIN_WIKIVOYAGE_BEFORE_WIKIPEDIA and any_primary_source_succeeded:
                    osm_places = await self.fetch_overpass_optional_places(
                        client,
                        city_name=city_name,
                        city_lat=lat_val,
                        city_lon=lon_val,
                        radius_km=radius_km,
                    )
                    if osm_places:
                        candidates.extend(osm_places)
                        used_sources.append("overpass")

            # Si toutes les sources principales ont échoué (panne réseau / saturation totale)
            if not any_primary_source_succeeded and not candidates:
                return WorldPlacesFetchResult(
                    city_name=city_name,
                    radius_km=radius_km,
                    places=[],
                    outage_message=OUTAGE_PLACES_MESSAGE,
                    used_sources=[],
                    districts_followed=list(self.last_districts_followed),
                )

            selected = self.deduplicate_and_select_places(candidates, max_places=MAX_SELECTED_PLACES)

            # Si Overpass a contribué à la sélection finale, mentionne l'attribution ODbL
            overpass_used = "overpass" in used_sources or any(
                p.source_provider == "overpass_osm" for p in selected
            )
            if overpass_used:
                for p in selected:
                    if "OpenStreetMap" not in p.source_attribution:
                        p.source_attribution = (
                            "Données Wikivoyage / Wikipédia (CC BY-SA 4.0) • contributeurs OpenStreetMap (ODbL)"
                        )

            few_msg: str | None = None
            can_expand = False
            suggested_radius: int | None = None
            if len(selected) < FEW_PLACES_THRESHOLD:
                few_msg = f"Peu de lieux disponibles à {city_name} pour l'instant"
                if radius_km < EXPANDED_SEARCH_RADIUS_KM:
                    can_expand = True
                    suggested_radius = EXPANDED_SEARCH_RADIUS_KM

            return WorldPlacesFetchResult(
                city_name=city_name,
                radius_km=radius_km,
                places=selected,
                few_places_message=few_msg,
                can_expand_radius=can_expand,
                suggested_radius_km=suggested_radius,
                outage_message=None,
                used_sources=used_sources,
                districts_followed=list(self.last_districts_followed),
            )

    def parse_wikivoyage_sleep_listings(
        self,
        wikitext: str,
        *,
        page_title: str,
        lang: str,
        city_lat: float,
        city_lon: float,
    ) -> list[NormalizedWorldAccommodation]:
        """
        Extrait la section « Se loger » / « Sleep » d'une page Wikivoyage :
        nom, adresse, coordonnées, gamme Économique / Standard / Luxe, prix indicatif,
        type d'hébergement (hôtel, appartement, riad) et liens Booking / Airbnb.
        """
        if not wikitext or not wikitext.strip():
            return []

        normalized_lines = [
            line.lstrip() if line.lstrip().startswith(("=", "*", "{", "[")) else line
            for line in wikitext.splitlines()
        ]
        wikicode = mwparserfromhell.parse("\n".join(normalized_lines))
        in_sleep_section = False
        current_tier = TravelStyle.STANDARD.value
        extracted: list[NormalizedWorldAccommodation] = []
        city_clean = page_title.split("/")[0].replace("_", " ").strip()
        district_label = (
            page_title.split("/", 1)[1].replace("_", " ").strip()
            if "/" in page_title
            else city_clean
        )

        for node in wikicode.nodes:
            if isinstance(node, mwparserfromhell.nodes.Heading):
                heading_title = clean_wikitext_value(str(node.title))
                level = int(getattr(node, "level", 2))
                sec_kind = self._section_kind_from_heading(heading_title)
                if sec_kind == "se loger":
                    in_sleep_section = True
                    current_tier = TravelStyle.STANDARD.value
                elif level <= 2 and sec_kind != "se loger":
                    in_sleep_section = False
                elif in_sleep_section:
                    norm_h = normalize_place_text(heading_title)
                    if any(
                        tok in norm_h
                        for tok in (
                            "bon marche",
                            "petit budget",
                            "petits budgets",
                            "economique",
                            "budget",
                            "auberge",
                            "camping",
                            "pas cher",
                            "deux etoiles",
                            "2 etoiles",
                            "une etoile",
                            "1 etoile",
                        )
                    ):
                        current_tier = TravelStyle.ECONOMIC.value
                    elif any(
                        tok in norm_h
                        for tok in (
                            "luxe",
                            "grand luxe",
                            "chic",
                            "splurge",
                            "haut de gamme",
                            "palace",
                            "quatre etoiles",
                            "4 etoiles",
                            "cinq etoiles",
                            "5 etoiles",
                        )
                    ):
                        current_tier = TravelStyle.LUXURY.value
                    elif any(
                        tok in norm_h
                        for tok in (
                            "prix moyen",
                            "moyen",
                            "mid range",
                            "midrange",
                            "standard",
                            "confort",
                            "intermediaire",
                            "trois etoiles",
                            "3 etoiles",
                        )
                    ):
                        current_tier = TravelStyle.STANDARD.value
                continue

            templates: list[mwparserfromhell.nodes.Template] = []
            if isinstance(node, mwparserfromhell.nodes.Template):
                templates = [node]
            else:
                try:
                    templates = mwparserfromhell.parse(str(node)).filter_templates(recursive=True)
                except Exception:
                    templates = []

            for tpl in templates:
                raw_tpl_name = clean_wikitext_value(str(tpl.name)).lower()
                tpl_name = re.sub(r"\s+", " ", raw_tpl_name).strip()
                if tpl_name not in WIKIVOYAGE_LISTING_TEMPLATES:
                    continue

                if not in_sleep_section:
                    continue

                nom = self._get_template_param(tpl, "nom", "name")
                pos1 = self._get_template_param(tpl, "1")
                pos2 = self._get_template_param(tpl, "2")
                if not nom:
                    if pos1.lower() in WIKIVOYAGE_LISTING_TEMPLATES and pos2:
                        nom = pos2
                    else:
                        nom = pos1
                if not nom:
                    continue

                adresse = self._get_template_param(tpl, "adresse", "address", "directions")
                prix_raw = self._get_template_param(tpl, "prix", "price")
                description_raw = self._get_template_param(tpl, "description", "content")
                site_web = self._get_template_param(tpl, "url", "site", "website", "web")
                wikidata_id = self._get_template_param(tpl, "wikidata")
                lat_raw = self._get_template_param(tpl, "lat", "latitude")
                lon_raw = self._get_template_param(tpl, "long", "lon", "lng", "longitude")

                lat_val: float | None = None
                lon_val: float | None = None
                try:
                    if lat_raw and lon_raw:
                        lat_val = float(lat_raw.replace(",", "."))
                        lon_val = float(lon_raw.replace(",", "."))
                except ValueError:
                    lat_val = None
                    lon_val = None

                has_precise_coords = lat_val is not None and lon_val is not None
                if has_precise_coords:
                    dist_from_city_km = haversine_distance_km(city_lat, city_lon, lat_val, lon_val)
                    if dist_from_city_km > 15.0:
                        continue
                else:
                    lat_val = city_lat
                    lon_val = city_lon

                tier = current_tier
                _, est_cost, parsed_tier = parse_price_text(prix_raw)
                combined_text = f"{nom} {description_raw} {adresse}".lower()

                if current_tier != TravelStyle.STANDARD.value:
                    tier = current_tier
                elif est_cost > 15:
                    if est_cost <= 115:
                        tier = TravelStyle.ECONOMIC.value
                    elif est_cost >= 250:
                        tier = TravelStyle.LUXURY.value
                    else:
                        tier = TravelStyle.STANDARD.value
                elif parsed_tier != TravelStyle.STANDARD.value:
                    tier = parsed_tier
                elif any(k in combined_text for k in ("hostel", "auberge", "backpacker", "budget")):
                    tier = TravelStyle.ECONOMIC.value
                elif any(k in combined_text for k in ("palace", "5 étoiles", "5*", "luxury", "luxe", "grand hotel")):
                    tier = TravelStyle.LUXURY.value

                if est_cost > 15:
                    indicative_price = round(float(est_cost), 2)
                else:
                    indicative_price = {
                        TravelStyle.ECONOMIC.value: 90.0,
                        TravelStyle.STANDARD.value: 160.0,
                        TravelStyle.LUXURY.value: 350.0,
                    }.get(tier, 150.0)

                if "riad" in combined_text or "dar " in combined_text:
                    subtype = "riad"
                    acc_type = "AIRBNB"
                elif any(
                    k in combined_text
                    for k in (
                        "appartement",
                        "apartment",
                        "appart",
                        "studio",
                        "loft",
                        "airbnb",
                        "résidence",
                        "residence",
                        "gîte",
                        "guesthouse",
                        "chambre d'hôtes",
                    )
                ):
                    subtype = "appartement"
                    acc_type = "AIRBNB"
                else:
                    subtype = "hôtel"
                    acc_type = "HOTEL"

                gamme_label = {
                    TravelStyle.ECONOMIC.value: "Économique",
                    TravelStyle.STANDARD.value: "Standard",
                    TravelStyle.LUXURY.value: "Luxe",
                }.get(tier, "Standard")

                booking_url, airbnb_url = build_accommodation_booking_urls(
                    name=nom,
                    city_name=city_clean,
                    latitude=lat_val if has_precise_coords else None,
                    longitude=lon_val if has_precise_coords else None,
                )
                redirect_url = site_web if (site_web and site_web.startswith("http")) else booking_url
                norm_qid = wikidata_id.upper() if (wikidata_id and wikidata_id.upper().startswith("Q")) else None

                extracted.append(
                    NormalizedWorldAccommodation(
                        name=nom,
                        type=acc_type,
                        accommodation_subtype=subtype,
                        neighborhood=district_label,
                        address=adresse or "",
                        latitude=lat_val,
                        longitude=lon_val,
                        has_precise_coords=has_precise_coords,
                        price_per_night=indicative_price,
                        luxury_tier=tier,
                        gamme_label=gamme_label,
                        rating=4.6 if tier == TravelStyle.STANDARD.value else (4.8 if tier == TravelStyle.LUXURY.value else 4.4),
                        photos=[],
                        amenities=["Se loger Wikivoyage", f"Gamme {gamme_label}", "Prix indicatif"],
                        source_provider=f"wikivoyage_{lang}",
                        booking_redirect_url=redirect_url,
                        booking_url=booking_url,
                        airbnb_url=airbnb_url,
                        is_illustration=True,
                        illustration_label="Illustration",
                        price_label="Prix indicatif",
                        external_entity_id=norm_qid,
                    )
                )

        return extracted

    async def fetch_city_accommodations(
        self,
        *,
        city_name: str,
        city_lat: float,
        city_lon: float,
        allow_network: bool = True,
    ) -> list[NormalizedWorldAccommodation]:
        """
        Récupère les hébergements de la section « Se loger » de Wikivoyage (fr puis en)
        pour une ville du monde.
        Si Wikivoyage ne retourne rien (ou si le réseau est désactivé), retourne uniquement
        les 3 cartes génériques (« Hôtel de gamme Économique/Standard/Luxe à <ville> »),
        sans nom d'établissement, adresse ni coordonnées inventés.
        """
        candidates: list[NormalizedWorldAccommodation] = []
        if allow_network:
            is_mock_transport = self._http_transport is not None
            req_timeout = 10.0 if is_mock_transport else 2.5
            try:
                async with httpx.AsyncClient(
                    transport=self._http_transport,
                    headers={"User-Agent": WORLD_PLACES_USER_AGENT},
                    timeout=req_timeout,
                ) as client:
                    for lang in ("fr", "en"):
                        try:
                            resolved_title, main_wikitext, _ = await self._fetch_wikivoyage_page(
                                client,
                                lang=lang,
                                page_title=city_name,
                                timeout=req_timeout,
                                retry_on_failure=is_mock_transport,
                            )
                            if main_wikitext:
                                parsed = self.parse_wikivoyage_sleep_listings(
                                    main_wikitext,
                                    page_title=resolved_title or city_name,
                                    lang=lang,
                                    city_lat=city_lat,
                                    city_lon=city_lon,
                                )
                                candidates.extend(parsed)
                                if candidates or not is_mock_transport:
                                    break
                        except Exception:
                            continue
            except Exception:
                pass

        if not candidates:
            candidates = build_curated_or_fallback_world_accommodations(
                city_name=city_name,
                city_lat=city_lat,
                city_lon=city_lon,
            )

        deduped: list[NormalizedWorldAccommodation] = []
        seen_names: set[str] = set()
        for item in candidates:
            key = normalize_place_text(item.name)
            if not key or key in seen_names:
                continue
            seen_names.add(key)
            deduped.append(item)
            if len(deduped) >= 10:
                break
        return deduped


@dataclass
class NormalizedWorldAccommodation:
    name: str
    type: str
    accommodation_subtype: str
    neighborhood: str
    address: str
    latitude: float
    longitude: float
    price_per_night: float
    luxury_tier: str
    gamme_label: str
    rating: float
    has_precise_coords: bool = True
    photos: list[str] = field(default_factory=list)
    amenities: list[str] = field(default_factory=list)
    source_provider: str = "wikivoyage_fr"
    booking_redirect_url: str = ""
    booking_url: str = ""
    airbnb_url: str = ""
    is_illustration: bool = True
    illustration_label: str = "Illustration"
    price_label: str = "Prix indicatif"
    external_entity_id: str | None = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


def build_accommodation_booking_urls(
    *,
    name: str,
    city_name: str,
    latitude: float | None = None,
    longitude: float | None = None,
    is_generic: bool = False,
) -> tuple[str, str]:
    """Construit les liens de réservation externes Booking.com et Airbnb."""
    city_clean = city_name.strip()
    if is_generic or name.strip().startswith("Hôtel de gamme "):
        booking_url = f"https://www.booking.com/searchresults.fr.html?ss={quote(city_clean)}"
        airbnb_url = f"https://www.airbnb.fr/s/{quote(city_clean)}/homes"
        return booking_url, airbnb_url

    search_query = f"{name} {city_clean}".strip()
    if latitude is not None and longitude is not None:
        booking_url = (
            f"https://www.booking.com/searchresults.fr.html"
            f"?ss={quote(search_query)}&latitude={latitude:.5f}&longitude={longitude:.5f}"
        )
        airbnb_url = (
            f"https://www.airbnb.fr/s/{quote(city_clean)}/homes"
            f"?lat={latitude:.5f}&lng={longitude:.5f}&query={quote(search_query)}"
        )
    else:
        booking_url = f"https://www.booking.com/searchresults.fr.html?ss={quote(search_query)}"
        airbnb_url = f"https://www.airbnb.fr/s/{quote(city_clean)}/homes?query={quote(search_query)}"
    return booking_url, airbnb_url


def build_curated_or_fallback_world_accommodations(
    *,
    city_name: str,
    city_lat: float,
    city_lon: float,
) -> list[NormalizedWorldAccommodation]:
    """
    Repli quand Wikivoyage ne retourne aucun hébergement dans « Se loger » :
    aucun nom d'établissement, adresse ou coordonnées inventés — uniquement 3 cartes
    génériques (« Hôtel de gamme Économique/Standard/Luxe à <ville> »), sans marqueur
    précis sur la carte (`has_precise_coords=False`), étiquetées « Illustration »,
    avec les boutons Booking et Airbnb.
    """
    city_clean = city_name.strip() or "cette ville"
    generic_tiers = [
        (
            f"Hôtel de gamme Économique à {city_clean}",
            TravelStyle.ECONOMIC.value,
            "Économique",
            85.0,
        ),
        (
            f"Hôtel de gamme Standard à {city_clean}",
            TravelStyle.STANDARD.value,
            "Standard",
            150.0,
        ),
        (
            f"Hôtel de gamme Luxe à {city_clean}",
            TravelStyle.LUXURY.value,
            "Luxe",
            320.0,
        ),
    ]
    results: list[NormalizedWorldAccommodation] = []
    for name, tier_v, gamme_v, price_v in generic_tiers:
        b_url, a_url = build_accommodation_booking_urls(
            name=name,
            city_name=city_clean,
            is_generic=True,
        )
        results.append(
            NormalizedWorldAccommodation(
                name=name,
                type="HOTEL",
                accommodation_subtype="hôtel",
                neighborhood=city_clean,
                address="",
                latitude=city_lat,
                longitude=city_lon,
                has_precise_coords=False,
                price_per_night=price_v,
                luxury_tier=tier_v,
                gamme_label=gamme_v,
                rating=0.0,
                photos=[],
                amenities=[f"Gamme {gamme_v}", "Prix indicatif"],
                source_provider="generic_fallback",
                booking_redirect_url=b_url,
                booking_url=b_url,
                airbnb_url=a_url,
                is_illustration=True,
                illustration_label="Illustration",
                price_label="Prix indicatif",
            )
        )
    return results


world_places_service = WorldPlacesService()


def get_world_places_service() -> WorldPlacesService:
    return world_places_service


def parse_wikivoyage_sleep_listings(
    wikitext: str,
    *,
    page_title: str | None = None,
    city_name: str | None = None,
    country_name: str | None = None,
    lang: str = "fr",
    city_lat: float | None = None,
    city_lon: float | None = None,
    center_lat: float | None = None,
    center_lon: float | None = None,
) -> list[NormalizedWorldAccommodation]:
    effective_title = page_title or city_name or "Ville"
    effective_lat = city_lat if city_lat is not None else (center_lat if center_lat is not None else 48.8566)
    effective_lon = city_lon if city_lon is not None else (center_lon if center_lon is not None else 2.3522)
    return world_places_service.parse_wikivoyage_sleep_listings(
        wikitext,
        page_title=effective_title,
        lang=lang,
        city_lat=effective_lat,
        city_lon=effective_lon,
    )


async def fetch_city_accommodations(
    *,
    city_name: str,
    country_name: str | None = None,
    city_lat: float | None = None,
    city_lon: float | None = None,
    center_lat: float | None = None,
    center_lon: float | None = None,
    allow_network: bool = True,
) -> list[NormalizedWorldAccommodation]:
    effective_lat = city_lat if city_lat is not None else (center_lat if center_lat is not None else 48.8566)
    effective_lon = city_lon if city_lon is not None else (center_lon if center_lon is not None else 2.3522)
    return await world_places_service.fetch_city_accommodations(
        city_name=city_name,
        city_lat=effective_lat,
        city_lon=effective_lon,
        allow_network=allow_network,
    )



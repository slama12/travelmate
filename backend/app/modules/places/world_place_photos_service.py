from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import html
import re
from typing import Any, Awaitable, Callable
from urllib.parse import quote, unquote, urlparse

import httpx
from sqlalchemy import select

from app.core.database import AsyncSession
from app.core.geo import haversine_distance_km
from app.core.redis import cache_client
from app.models.entities import Destination, Place
from app.modules.places.world_places_service import (
    WIKIDATA_EXCLUDED_QIDS,
    normalize_place_text,
)

WORLD_PHOTOS_USER_AGENT = "TravelMate/1.0 (contact)"
PHOTO_CONCURRENCY_LIMIT = 4
PHOTO_BACKOFF_DELAYS: tuple[int, ...] = (1, 2, 4)
MIN_IMAGE_WIDTH_PX = 400
TARGET_THUMB_WIDTH_PX = 800
EXACT_COORD_SEARCH_RADIUS_M = 250.0
PHOTO_CACHE_TTL_SECONDS = 86400 * 7

FORBIDDEN_TITLE_PHRASES: tuple[str, ...] = (
    "coat of arms",
    "arms of",
    "floor plan",
    "floorplan",
    "locator map",
    "location map",
    "city map",
    "street map",
    "route map",
    "plan de ",
    "plan du ",
    "plan des ",
    "carte de ",
    "carte du ",
    "carte des ",
)

FORBIDDEN_TITLE_TOKENS: frozenset[str] = frozenset(
    {
        "map",
        "maps",
        "carte",
        "cartes",
        "logo",
        "logos",
        "flag",
        "flags",
        "drapeau",
        "drapeaux",
        "blason",
        "blasons",
        "armoiries",
        "plan",
        "plans",
        "schema",
        "schemas",
        "schéma",
        "schémas",
        "diagram",
        "diagrams",
        "diagramme",
        "locator",
        "icon",
        "icons",
        "icone",
        "icône",
        "banner",
        "pagebanner",
        "emblem",
        "seal",
        "stamp",
        "signature",
        "stemma",
        "escudo",
        "brasao",
        "brasão",
    }
)

FORBIDDEN_EXTENSIONS: tuple[str, ...] = (
    ".svg",
    ".svg.png",
    ".pdf",
    ".djvu",
    ".ogg",
    ".ogv",
    ".webm",
    ".mp3",
    ".wav",
)


def normalize_commons_file_title(raw_title: str) -> str:
    """Normalise un titre de fichier Wikimedia Commons sous la forme 'File:<Nom>'."""
    cleaned = (raw_title or "").strip()
    if not cleaned:
        return ""
    cleaned = unquote(cleaned)
    for prefix in ("File:", "file:", "Fichier:", "fichier:", "Image:", "image:", "Archivo:", "archivo:"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            break
    cleaned = cleaned.replace("_", " ").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return ""
    return f"File:{cleaned}"


def clean_commons_html_text(raw_value: str | None) -> str:
    """Nettoie les balises HTML des métadonnées Commons (ex: Artist) pour obtenir un texte lisible."""
    if not raw_value:
        return ""
    without_tags = re.sub(r"<[^>]+>", " ", str(raw_value))
    unescaped = html.unescape(without_tags)
    collapsed = re.sub(r"\s+", " ", unescaped).strip()
    return collapsed


def is_forbidden_image_title_or_type(
    file_title: str,
    mime_type: str | None = None,
) -> tuple[bool, str | None]:
    """
    Règle 5 (Qualité) :
    Ignore les images qui sont des cartes, logos, drapeaux, blasons, plans ou schémas
    (type de fichier SVG, mots 'map', 'logo', 'flag', 'coat of arms', 'plan', 'schema', etc. dans le titre).
    """
    norm_title = normalize_commons_file_title(file_title)
    if not norm_title:
        return True, "empty_title"

    lower_full = norm_title.lower()
    if any(lower_full.endswith(ext) for ext in FORBIDDEN_EXTENSIONS) or ".svg." in lower_full:
        return True, "forbidden_svg_or_non_photo_extension"

    if mime_type:
        mime_lower = mime_type.lower()
        if "svg" in mime_lower or not mime_lower.startswith("image/"):
            return True, "forbidden_mime_type"

    # Retire le préfixe "File:" et l'extension finale pour analyser les mots du titre
    body = norm_title[5:] if norm_title.startswith("File:") else norm_title
    body_no_ext = re.sub(r"\.[a-zA-Z0-9]{2,5}$", "", body)
    # Sépare aussi le CamelCase (ex: "MapOfMilan" -> "Map Of Milan")
    camel_split = re.sub(r"([a-zàâäéèêëîïôöùûüç])([A-Z])", r"\1 \2", body_no_ext)
    normalized_space = re.sub(r"[_\-]+", " ", camel_split).lower()
    normalized_space = re.sub(r"\s+", " ", normalized_space).strip()

    for phrase in FORBIDDEN_TITLE_PHRASES:
        if phrase in normalized_space:
            return True, f"forbidden_title_phrase:{phrase.strip()}"

    tokens = [
        tok
        for tok in re.split(r"[^a-z0-9àâäéèêëîïôöùûüçãõ]+", normalized_space)
        if tok
    ]
    for tok in tokens:
        if tok in FORBIDDEN_TITLE_TOKENS:
            return True, f"forbidden_title_keyword:{tok}"

    return False, None


def normalize_and_validate_free_license(
    license_short_name: str | None,
    usage_terms: str | None = None,
    license_code: str | None = None,
) -> str | None:
    """
    Règle 2 :
    Refuse les fichiers sans licence libre claire (CC0, CC BY, CC BY-SA, domaine public).
    """
    raw_short = clean_commons_html_text(license_short_name)
    raw_terms = clean_commons_html_text(usage_terms)
    raw_code = clean_commons_html_text(license_code)

    combined = f"{raw_short} {raw_terms} {raw_code}".strip().lower()
    if not combined:
        return None

    # Exclusion stricte des licences non libres ou restreintes (NC, ND, Fair use, Copyright, etc.)
    non_free_markers = (
        "by-nc",
        "by nc",
        "non-commercial",
        "noncommercial",
        "pas d'utilisation commerciale",
        "by-nd",
        "by nd",
        "noderivs",
        "no derivatives",
        "pas de modification",
        "fair use",
        "non-free",
        "non free",
        "copyrighted",
        "all rights reserved",
        "tous droits réservés",
        "some rights reserved",
        "unfree",
        "permission",
        "unknown",
    )
    # Attention : "copyrighted free use" existe parfois mais on s'en tient aux 4 familles claires demandées
    for marker in non_free_markers:
        if marker in combined:
            return None

    short_lower = raw_short.lower()

    # 1. CC0
    if (
        short_lower in ("cc0", "cc-zero", "cc0 1.0")
        or short_lower.startswith("cc0")
        or "creative commons zero" in combined
        or raw_code.lower() in ("cc0", "cc-zero")
    ):
        return "CC0"

    # 2. CC BY-SA
    cc_by_sa_match = re.search(
        r"\bcc[\s\-]+by[\s\-]+sa(?:\s*[\-]\s*|\s+)?(\d+(?:\.\d+)?)?\b",
        raw_short or combined,
        re.IGNORECASE,
    )
    if cc_by_sa_match:
        version = cc_by_sa_match.group(1)
        return f"CC BY-SA {version}" if version else "CC BY-SA"

    # 3. CC BY
    cc_by_match = re.search(
        r"\bcc[\s\-]+by(?:\s*[\-]\s*|\s+)?(\d+(?:\.\d+)?)?\b",
        raw_short or combined,
        re.IGNORECASE,
    )
    if cc_by_match and "sa" not in (raw_short or combined).lower():
        version = cc_by_match.group(1)
        return f"CC BY {version}" if version else "CC BY"

    # 4. Domaine public / Public domain
    if (
        "public domain" in combined
        or "domaine public" in combined
        or short_lower in ("pd", "pdm", "cc-pd")
        or short_lower.startswith("pd-")
        or short_lower.startswith("pd ")
    ):
        return "Domaine public" if "domaine public" in short_lower else "Public domain"

    return None


def format_photo_credit(author: str | None, license_label: str | None) -> str | None:
    """
    Règle 3 :
    Sous la photo : 'Photo : <auteur>, <licence>'
    """
    clean_author = (author or "").strip()
    clean_license = (license_label or "").strip()
    if not clean_author or not clean_license:
        return None
    return f"Photo : {clean_author}, {clean_license}"


def ensure_thumbnail_800px_url(
    thumb_url: str | None,
    original_url: str | None,
    width: int,
) -> str | None:
    """
    Règle 3 :
    Vignette ~800 px (jamais l'original).
    Utilise thumburl de Commons (iiurlwidth=800) ou de pageimages (pithumbsize=800).
    Si seul l'URL original upload.wikimedia.org est fourni dans un mock, construit l'URL /thumb/.../800px-...
    """
    if thumb_url and thumb_url.strip():
        candidate = thumb_url.strip()
        # Si jamais thumb_url est identique à original_url sur une grande image Wikimedia, force /thumb/
        if (
            original_url
            and candidate == original_url.strip()
            and "/wikipedia/commons/" in candidate
            and "/thumb/" not in candidate
        ):
            parts = candidate.split("/wikipedia/commons/", 1)
            rel_path = parts[1]
            filename = rel_path.rsplit("/", 1)[-1]
            return f"{parts[0]}/wikipedia/commons/thumb/{rel_path}/{TARGET_THUMB_WIDTH_PX}px-{filename}"
        return candidate

    if original_url and original_url.strip():
        orig = original_url.strip()
        if "/wikipedia/commons/" in orig and "/thumb/" not in orig:
            parts = orig.split("/wikipedia/commons/", 1)
            rel_path = parts[1]
            filename = rel_path.rsplit("/", 1)[-1]
            return f"{parts[0]}/wikipedia/commons/thumb/{rel_path}/{TARGET_THUMB_WIDTH_PX}px-{filename}"
        if width <= TARGET_THUMB_WIDTH_PX:
            return orig

    return None


@dataclass
class ResolvedPlacePhoto:
    has_photo: bool
    photo_url: str | None = None
    photo_file_title: str | None = None
    photo_author: str | None = None
    photo_license: str | None = None
    photo_commons_url: str | None = None
    photo_source: str = "none"  # "wikidata_p18" | "wikipedia_pageimages" | "none"
    wikidata_id: str | None = None
    wikipedia_title: str | None = None
    rejected_reason: str | None = None

    @property
    def photo_credit_text(self) -> str | None:
        return format_photo_credit(self.photo_author, self.photo_license)

    def to_cache_dict(self) -> dict[str, Any]:
        return {
            "checked": True,
            "has_photo": self.has_photo,
            "photo_url": self.photo_url,
            "photo_file_title": self.photo_file_title,
            "photo_author": self.photo_author,
            "photo_license": self.photo_license,
            "photo_commons_url": self.photo_commons_url,
            "photo_source": self.photo_source,
            "wikidata_id": self.wikidata_id,
            "wikipedia_title": self.wikipedia_title,
            "rejected_reason": self.rejected_reason,
        }

    @classmethod
    def from_cache_dict(cls, data: dict[str, Any]) -> "ResolvedPlacePhoto":
        return cls(
            has_photo=bool(data.get("has_photo")),
            photo_url=data.get("photo_url"),
            photo_file_title=data.get("photo_file_title"),
            photo_author=data.get("photo_author"),
            photo_license=data.get("photo_license"),
            photo_commons_url=data.get("photo_commons_url"),
            photo_source=str(data.get("photo_source") or "none"),
            wikidata_id=data.get("wikidata_id"),
            wikipedia_title=data.get("wikipedia_title"),
            rejected_reason=data.get("rejected_reason"),
        )


def extract_linked_identifiers_from_place(
    *,
    external_place_id: str | None,
    source_provider: str | None,
    source_url: str | None,
    place_name: str,
    opening_hours: dict[str, Any] | None,
) -> tuple[str | None, str | None, str, bool]:
    """
    Extrait (wikidata_id, wikipedia_title, wikipedia_lang, has_explicit_coords)
    déjà rattachés à un objet Place sans aucune recherche floue.
    """
    oh = opening_hours if isinstance(opening_hours, dict) else {}

    wikidata_id: str | None = None
    if external_place_id and re.match(r"^Q\d+$", external_place_id.strip(), re.IGNORECASE):
        wikidata_id = external_place_id.strip().upper()
    elif oh.get("_wikidata_id") and re.match(r"^Q\d+$", str(oh["_wikidata_id"]).strip(), re.IGNORECASE):
        wikidata_id = str(oh["_wikidata_id"]).strip().upper()
    elif oh.get("wikidata_id") and re.match(r"^Q\d+$", str(oh["wikidata_id"]).strip(), re.IGNORECASE):
        wikidata_id = str(oh["wikidata_id"]).strip().upper()

    wikipedia_lang = str(oh.get("_wikipedia_lang") or oh.get("wikipedia_lang") or "fr").strip().lower() or "fr"
    wikipedia_title: str | None = None
    raw_wp = oh.get("_wikipedia_title") or oh.get("wikipedia_title")
    if raw_wp and str(raw_wp).strip():
        wp_str = str(raw_wp).strip()
        if ":" in wp_str and len(wp_str.split(":", 1)[0]) in (2, 3):
            lang_prefix, rest = wp_str.split(":", 1)
            if lang_prefix.isalpha() and rest.strip():
                wikipedia_lang = lang_prefix.lower()
                wikipedia_title = rest.strip()
        if not wikipedia_title:
            wikipedia_title = wp_str

    if not wikipedia_title and source_url and ".wikipedia.org/wiki/" in source_url:
        try:
            parsed = urlparse(source_url)
            host_parts = (parsed.hostname or "").split(".")
            if len(host_parts) >= 3 and host_parts[1] == "wikipedia":
                wikipedia_lang = host_parts[0].lower()
            wiki_slug = parsed.path.split("/wiki/", 1)[1]
            decoded_title = unquote(wiki_slug).replace("_", " ").strip()
            if decoded_title:
                wikipedia_title = decoded_title
        except Exception:
            pass

    if not wikipedia_title and (source_provider or "") == "wikipedia_wikidata":
        wikipedia_title = place_name.strip()

    raw_explicit = oh.get("_has_explicit_coords", oh.get("has_explicit_coords", True))
    if isinstance(raw_explicit, bool):
        has_explicit_coords = raw_explicit
    else:
        has_explicit_coords = str(raw_explicit).strip().lower() not in ("false", "0", "no")

    return wikidata_id, wikipedia_title, wikipedia_lang, has_explicit_coords


class WorldPlacePhotoService:
    """
    Service Étape 3 : Récupération et validation des photos des lieux (Wikidata P18 -> Wikipédia pageimages -> rien)
    avec contrôle strict des métadonnées et licences libres via Wikimedia Commons.
    """

    def __init__(
        self,
        *,
        http_transport: httpx.AsyncBaseTransport | None = None,
        sleep_func: Callable[[float], Awaitable[None]] | None = None,
        max_concurrency: int = PHOTO_CONCURRENCY_LIMIT,
        backoff_delays: tuple[int, ...] = PHOTO_BACKOFF_DELAYS,
    ) -> None:
        self._http_transport = http_transport
        self._sleep_func = sleep_func or asyncio.sleep
        self._max_concurrency = max(1, int(max_concurrency))
        self._semaphore = asyncio.Semaphore(self._max_concurrency)
        self._backoff_delays = backoff_delays
        self.request_count = 0
        self.retry_delays_recorded: list[float] = []
        self._in_flight = 0
        self.max_observed_concurrency = 0
        self._local_memory_cache: dict[str, dict[str, Any]] = {}

    async def _request_json_with_backoff(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, Any],
        timeout: float = 12.0,
    ) -> dict[str, Any]:
        """
        Exécute une requête GET avec User-Agent 'TravelMate/1.0 (contact)',
        limite de simultanéité (4 requêtes max) et attente croissante (1, 2, 4 s)
        sur erreur HTTP (429, 500, 502, 503, 504) ou saturation MediaWiki/Commons.
        """
        headers = {
            "User-Agent": WORLD_PHOTOS_USER_AGENT,
            "Accept": "application/json",
        }
        max_attempts = len(self._backoff_delays) + 1
        last_exc: Exception | None = None

        for attempt in range(max_attempts):
            try:
                async with self._semaphore:
                    self._in_flight += 1
                    if self._in_flight > self.max_observed_concurrency:
                        self.max_observed_concurrency = self._in_flight
                    try:
                        self.request_count += 1
                        resp = await client.get(url, params=params, headers=headers, timeout=timeout)
                    finally:
                        self._in_flight -= 1

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
                    err_code = str(err_info.get("code") or "").lower()
                    err_text = str(err_info.get("info") or "").lower()
                    if (
                        "too-busy" in err_code
                        or "maxlag" in err_code
                        or "ratelimited" in err_code
                        or "readonly" in err_code
                        or "too busy" in err_text
                        or "saturated" in err_text
                        or "overload" in err_text
                    ):
                        raise RuntimeError(f"MediaWiki/Commons saturated: {err_code or err_text}")
                return payload if isinstance(payload, dict) else {}
            except Exception as exc:
                last_exc = exc
                if attempt >= len(self._backoff_delays):
                    break
                delay = float(self._backoff_delays[attempt])
                self.retry_delays_recorded.append(delay)
                await self._sleep_func(delay)

        if last_exc:
            raise last_exc
        return {}

    async def fetch_and_validate_commons_image(
        self,
        client: httpx.AsyncClient,
        raw_file_title: str,
        *,
        fallback_thumb_url: str | None = None,
    ) -> tuple[ResolvedPlacePhoto | None, str | None]:
        """
        Règles 2, 3 et 5 :
        - Filtre de qualité sur le titre/extension (refuse SVG, map, logo, flag, coat of arms, plan, schema...)
        - Interroge l'API Commons (prop=imageinfo, iiprop=extmetadata|url|size|mime, iiurlwidth=800)
        - Vérifie largeur >= 400 px
        - Extrait titre du fichier, auteur (Artist), licence (LicenseShortName), lien vers la page Commons
        - Refuse toute licence non libre (accepte uniquement CC0, CC BY, CC BY-SA, domaine public)
        - Retourne la vignette ~800 px (jamais l'original).
        """
        norm_title = normalize_commons_file_title(raw_file_title)
        forbidden, reason = is_forbidden_image_title_or_type(norm_title)
        if forbidden:
            return None, reason

        data = await self._request_json_with_backoff(
            client,
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "titles": norm_title,
                "prop": "imageinfo",
                "iiprop": "extmetadata|url|size|mime",
                "iiurlwidth": str(TARGET_THUMB_WIDTH_PX),
                "format": "json",
            },
        )

        pages = (data.get("query") or {}).get("pages") or {}
        if not isinstance(pages, dict) or not pages:
            return None, "commons_page_not_found"

        for page_id, pinfo in pages.items():
            if str(page_id) == "-1" and "imageinfo" not in pinfo:
                continue
            imageinfo_list = pinfo.get("imageinfo") or []
            if not isinstance(imageinfo_list, list) or not imageinfo_list:
                continue

            ii = imageinfo_list[0] if isinstance(imageinfo_list[0], dict) else {}
            canonical_title = normalize_commons_file_title(str(pinfo.get("title") or norm_title))
            mime_type = str(ii.get("mime") or "")

            forbidden_post, reason_post = is_forbidden_image_title_or_type(canonical_title, mime_type=mime_type)
            if forbidden_post:
                return None, reason_post

            width = int(ii.get("width") or 0)
            if width < MIN_IMAGE_WIDTH_PX:
                return None, f"width_too_small:{width}"

            extmeta = ii.get("extmetadata") or {}
            if not isinstance(extmeta, dict):
                return None, "missing_extmetadata"

            raw_license_short = (extmeta.get("LicenseShortName") or {}).get("value")
            raw_usage_terms = (extmeta.get("UsageTerms") or {}).get("value")
            raw_license_code = (extmeta.get("License") or {}).get("value")

            validated_license = normalize_and_validate_free_license(
                raw_license_short,
                usage_terms=raw_usage_terms,
                license_code=raw_license_code,
            )
            if not validated_license:
                return None, f"unacceptable_license:{clean_commons_html_text(raw_license_short) or 'missing'}"

            raw_artist = (extmeta.get("Artist") or {}).get("value")
            clean_author = clean_commons_html_text(raw_artist)
            if not clean_author:
                if validated_license in ("CC0", "Public domain", "Domaine public"):
                    clean_author = "Domaine public"
                else:
                    return None, "missing_author"

            commons_url = str(ii.get("descriptionurl") or "").strip()
            if not commons_url:
                encoded_file = quote(canonical_title.replace(" ", "_"), safe="/:")
                commons_url = f"https://commons.wikimedia.org/wiki/{encoded_file}"

            thumb_url = ensure_thumbnail_800px_url(
                ii.get("thumburl") or fallback_thumb_url,
                ii.get("url"),
                width=width,
            )
            if not thumb_url:
                return None, "missing_thumbnail_url"

            return (
                ResolvedPlacePhoto(
                    has_photo=True,
                    photo_url=thumb_url,
                    photo_file_title=canonical_title,
                    photo_author=clean_author,
                    photo_license=validated_license,
                    photo_commons_url=commons_url,
                ),
                None,
            )

        return None, "no_valid_imageinfo"

    async def _find_exact_wikidata_entity_by_coords_and_name(
        self,
        client: httpx.AsyncClient,
        *,
        place_name: str,
        latitude: float | None,
        longitude: float | None,
        has_explicit_coords: bool,
    ) -> dict[str, Any] | None:
        """
        Règle 1 :
        Pour les lieux issus de fiches Wikivoyage sans article lié, cherche l'entité Wikidata
        par coordonnées et nom exact ; si le doute existe, ne mets pas de photo.
        """
        if not has_explicit_coords or latitude is None or longitude is None:
            return None

        target_norm_name = normalize_place_text(place_name)
        if not target_norm_name:
            return None

        geo_data = await self._request_json_with_backoff(
            client,
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "query",
                "list": "geosearch",
                "gscoord": f"{latitude}|{longitude}",
                "gsradius": str(int(EXACT_COORD_SEARCH_RADIUS_M)),
                "gslimit": "10",
                "format": "json",
            },
        )
        geo_items = (geo_data.get("query") or {}).get("geosearch") or []
        if not isinstance(geo_items, list) or not geo_items:
            return None

        candidate_qids: list[str] = []
        for item in geo_items:
            if not isinstance(item, dict):
                continue
            qid = str(item.get("title") or "").strip().upper()
            if not re.match(r"^Q\d+$", qid):
                continue
            item_lat = item.get("lat")
            item_lon = item.get("lon")
            if item_lat is not None and item_lon is not None:
                dist_m = haversine_distance_km(
                    float(latitude),
                    float(longitude),
                    float(item_lat),
                    float(item_lon),
                ) * 1000.0
                if dist_m > EXACT_COORD_SEARCH_RADIUS_M:
                    continue
            if qid not in candidate_qids:
                candidate_qids.append(qid)

        if not candidate_qids:
            return None

        wb_data = await self._request_json_with_backoff(
            client,
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbgetentities",
                "ids": "|".join(candidate_qids[:10]),
                "props": "labels|aliases|claims|sitelinks",
                "languages": "fr|en|pt|it|es|de|ar",
                "format": "json",
            },
        )
        entities = wb_data.get("entities") or {}
        if not isinstance(entities, dict):
            return None

        exact_matches: list[dict[str, Any]] = []
        for qid in candidate_qids:
            entity = entities.get(qid)
            if not isinstance(entity, dict):
                continue

            # Ignore les pages d'homonymie ou entités exclues (personnes, batailles, communes, etc.)
            claims = entity.get("claims") or {}
            p31_ids = self._extract_claim_entity_ids(claims, "P31")
            if "Q4167410" in p31_ids or bool(set(p31_ids) & WIKIDATA_EXCLUDED_QIDS):
                continue

            labels_dict = entity.get("labels") or {}
            aliases_dict = entity.get("aliases") or {}
            sitelinks_dict = entity.get("sitelinks") or {}

            candidate_names: set[str] = set()
            for lang_obj in labels_dict.values():
                if isinstance(lang_obj, dict) and lang_obj.get("value"):
                    candidate_names.add(normalize_place_text(str(lang_obj["value"])))
            for alias_list in aliases_dict.values():
                if isinstance(alias_list, list):
                    for al_obj in alias_list:
                        if isinstance(al_obj, dict) and al_obj.get("value"):
                            candidate_names.add(normalize_place_text(str(al_obj["value"])))
            for site_key in ("frwiki", "enwiki", "ptwiki", "itwiki"):
                sl_obj = sitelinks_dict.get(site_key)
                if isinstance(sl_obj, dict) and sl_obj.get("title"):
                    raw_sl_title = str(sl_obj["title"])
                    candidate_names.add(normalize_place_text(raw_sl_title))

            if target_norm_name in candidate_names:
                entity_copy = dict(entity)
                entity_copy["id"] = qid
                exact_matches.append(entity_copy)

        # Règle 1 : "si le doute existe, ne mets pas de photo"
        # On exige exactement 1 correspondance stricte par coordonnées + nom exact (aucune ambiguïté).
        if len(exact_matches) != 1:
            return None

        return exact_matches[0]

    @staticmethod
    def _extract_claim_entity_ids(claims: dict[str, Any], prop_id: str) -> list[str]:
        out: list[str] = []
        for stmt in claims.get(prop_id) or []:
            try:
                val = stmt["mainsnak"]["datavalue"]["value"]
                if isinstance(val, dict) and "id" in val:
                    out.append(str(val["id"]).upper())
            except (KeyError, TypeError):
                continue
        return out

    @staticmethod
    def _extract_p18_filenames(claims: dict[str, Any]) -> list[str]:
        files: list[str] = []
        for stmt in claims.get("P18") or []:
            try:
                val = stmt["mainsnak"]["datavalue"]["value"]
                if isinstance(val, str) and val.strip():
                    files.append(val.strip())
            except (KeyError, TypeError):
                continue
        return files

    @staticmethod
    def _extract_wikipedia_sitelink(
        sitelinks: dict[str, Any],
        preferred_lang: str = "fr",
    ) -> tuple[str, str] | None:
        if not isinstance(sitelinks, dict):
            return None
        lang_order = [preferred_lang, "fr", "en", "pt", "it", "es", "de"]
        seen: set[str] = set()
        for lang in lang_order:
            if lang in seen:
                continue
            seen.add(lang)
            site_key = f"{lang}wiki"
            sl = sitelinks.get(site_key)
            if isinstance(sl, dict) and sl.get("title"):
                return (lang, str(sl["title"]).strip())

        for site_key, sl in sitelinks.items():
            if (
                site_key.endswith("wiki")
                and site_key not in ("commonswiki", "specieswiki", "wikidatawiki", "metawiki")
                and isinstance(sl, dict)
                and sl.get("title")
            ):
                lang = site_key[:-4]
                if lang.isalpha():
                    return (lang, str(sl["title"]).strip())
        return None

    async def resolve_place_photo(
        self,
        *,
        place_name: str,
        source_provider: str = "wikivoyage_fr",
        external_place_id: str | None = None,
        wikidata_id: str | None = None,
        wikipedia_title: str | None = None,
        wikipedia_lang: str = "fr",
        source_url: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        has_explicit_coords: bool = True,
        opening_hours: dict[str, Any] | None = None,
        used_file_titles: set[str] | None = None,
        used_photo_urls: set[str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> ResolvedPlacePhoto:
        """
        Règle 1 :
        Pour chaque lieu sans photo, cherche une image dans cet ordre :
        (a) Wikidata, propriété P18 de l'entité du lieu ;
        (b) image principale de l'article Wikipédia (prop=pageimages, pithumbsize=800) ;
        (c) rien.
        Jamais de recherche floue par nom. Pour les fiches Wikivoyage sans article lié,
        cherche l'entité Wikidata par coordonnées et nom exact ; si le doute existe, ne met pas de photo.
        """
        own_client = client is None
        http_client = client or httpx.AsyncClient(transport=self._http_transport)

        try:
            ext_qid, ext_wp_title, ext_wp_lang, ext_explicit = extract_linked_identifiers_from_place(
                external_place_id=external_place_id,
                source_provider=source_provider,
                source_url=source_url,
                place_name=place_name,
                opening_hours=opening_hours,
            )
            effective_qid = (wikidata_id or ext_qid or "").strip().upper() or None
            if effective_qid and not re.match(r"^Q\d+$", effective_qid):
                effective_qid = None

            effective_wp_title = (wikipedia_title or ext_wp_title or "").strip() or None
            effective_wp_lang = (wikipedia_lang or ext_wp_lang or "fr").strip().lower() or "fr"
            if effective_wp_title and ":" in effective_wp_title:
                maybe_lang, rest = effective_wp_title.split(":", 1)
                if len(maybe_lang) in (2, 3) and maybe_lang.isalpha() and rest.strip():
                    effective_wp_lang = maybe_lang.lower()
                    effective_wp_title = rest.strip()

            effective_explicit_coords = bool(has_explicit_coords and ext_explicit)

            entity_data: dict[str, Any] | None = None
            last_rejection_reason: str | None = None

            # Cas d'une fiche Wikivoyage sans entité ni article lié :
            # recherche stricte par coordonnées + nom exact (si doute -> rien).
            if (
                not effective_qid
                and not effective_wp_title
                and (source_provider or "").startswith("wikivoyage")
            ):
                entity_data = await self._find_exact_wikidata_entity_by_coords_and_name(
                    http_client,
                    place_name=place_name,
                    latitude=latitude,
                    longitude=longitude,
                    has_explicit_coords=effective_explicit_coords,
                )
                if entity_data is not None:
                    effective_qid = str(entity_data.get("id") or "").upper() or None
                else:
                    return ResolvedPlacePhoto(
                        has_photo=False,
                        photo_source="none",
                        rejected_reason="unverified_or_ambiguous_entity",
                    )

            # (a) Wikidata, propriété P18 de l'entité du lieu
            if effective_qid:
                if entity_data is None:
                    wb_resp = await self._request_json_with_backoff(
                        http_client,
                        "https://www.wikidata.org/w/api.php",
                        params={
                            "action": "wbgetentities",
                            "ids": effective_qid,
                            "props": "claims|sitelinks",
                            "format": "json",
                        },
                    )
                    entities_map = wb_resp.get("entities") or {}
                    if isinstance(entities_map, dict):
                        raw_ent = entities_map.get(effective_qid)
                        if isinstance(raw_ent, dict):
                            entity_data = raw_ent

                if isinstance(entity_data, dict):
                    claims = entity_data.get("claims") or {}
                    sitelinks = entity_data.get("sitelinks") or {}
                    if not effective_wp_title:
                        sl_pair = self._extract_wikipedia_sitelink(sitelinks, preferred_lang=effective_wp_lang)
                        if sl_pair:
                            effective_wp_lang, effective_wp_title = sl_pair

                    p18_files = self._extract_p18_filenames(claims)
                    for raw_file in p18_files:
                        norm_file = normalize_commons_file_title(raw_file)
                        if not norm_file:
                            continue
                        if used_file_titles is not None and norm_file.lower() in used_file_titles:
                            last_rejection_reason = "duplicate_city_photo"
                            continue

                        resolved, rej_reason = await self.fetch_and_validate_commons_image(
                            http_client,
                            norm_file,
                        )
                        if resolved and resolved.has_photo and resolved.photo_url:
                            if used_photo_urls is not None and resolved.photo_url in used_photo_urls:
                                last_rejection_reason = "duplicate_city_photo"
                                continue
                            if used_file_titles is not None and resolved.photo_file_title:
                                used_file_titles.add(resolved.photo_file_title.lower())
                                used_file_titles.add(norm_file.lower())
                            if used_photo_urls is not None:
                                used_photo_urls.add(resolved.photo_url)
                            resolved.photo_source = "wikidata_p18"
                            resolved.wikidata_id = effective_qid
                            resolved.wikipedia_title = effective_wp_title
                            return resolved
                        if rej_reason:
                            last_rejection_reason = rej_reason

            # (b) Image principale de l'article Wikipédia (prop=pageimages, pithumbsize=800)
            if effective_wp_title:
                wp_resp = await self._request_json_with_backoff(
                    http_client,
                    f"https://{effective_wp_lang}.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "titles": effective_wp_title,
                        "prop": "pageimages",
                        "piprop": "thumbnail|name|original",
                        "pithumbsize": str(TARGET_THUMB_WIDTH_PX),
                        "redirects": "1",
                        "format": "json",
                    },
                )
                pages = (wp_resp.get("query") or {}).get("pages") or {}
                if isinstance(pages, dict):
                    for page_id, pinfo in pages.items():
                        if str(page_id) == "-1" or not isinstance(pinfo, dict):
                            continue
                        pageimage_name = str(pinfo.get("pageimage") or "").strip()
                        thumb_info = pinfo.get("thumbnail") or {}
                        orig_info = pinfo.get("original") or {}
                        thumb_source = (
                            str(thumb_info.get("source") or "").strip()
                            if isinstance(thumb_info, dict)
                            else ""
                        )
                        if not pageimage_name and thumb_source:
                            # Extrait le nom de fichier depuis l'URL de vignette si pageimage n'est pas fourni
                            parts = [p for p in urlparse(thumb_source).path.split("/") if p]
                            if len(parts) >= 2 and "/thumb/" in thumb_source:
                                pageimage_name = unquote(parts[-2])
                            elif parts:
                                pageimage_name = unquote(parts[-1])
                        if not pageimage_name and isinstance(orig_info, dict) and orig_info.get("source"):
                            parts = [p for p in urlparse(str(orig_info["source"])).path.split("/") if p]
                            if parts:
                                pageimage_name = unquote(parts[-1])

                        if not pageimage_name:
                            continue

                        norm_wp_file = normalize_commons_file_title(pageimage_name)
                        if not norm_wp_file:
                            continue
                        if used_file_titles is not None and norm_wp_file.lower() in used_file_titles:
                            last_rejection_reason = "duplicate_city_photo"
                            continue

                        resolved_wp, rej_reason_wp = await self.fetch_and_validate_commons_image(
                            http_client,
                            norm_wp_file,
                            fallback_thumb_url=thumb_source or None,
                        )
                        if resolved_wp and resolved_wp.has_photo and resolved_wp.photo_url:
                            if used_photo_urls is not None and resolved_wp.photo_url in used_photo_urls:
                                last_rejection_reason = "duplicate_city_photo"
                                continue
                            if used_file_titles is not None and resolved_wp.photo_file_title:
                                used_file_titles.add(resolved_wp.photo_file_title.lower())
                                used_file_titles.add(norm_wp_file.lower())
                            if used_photo_urls is not None:
                                used_photo_urls.add(resolved_wp.photo_url)
                            resolved_wp.photo_source = "wikipedia_pageimages"
                            resolved_wp.wikidata_id = effective_qid
                            resolved_wp.wikipedia_title = effective_wp_title
                            return resolved_wp
                        if rej_reason_wp:
                            last_rejection_reason = rej_reason_wp

            # (c) Rien : aucune photo attribuée
            return ResolvedPlacePhoto(
                has_photo=False,
                photo_source="none",
                wikidata_id=effective_qid,
                wikipedia_title=effective_wp_title,
                rejected_reason=last_rejection_reason or "no_image_found",
            )
        finally:
            if own_client:
                await http_client.aclose()

    @staticmethod
    def _build_place_cache_key(place: Place) -> str:
        ident = f"{place.destination_id}:{place.source_provider}:{place.external_place_id or place.id}"
        digest = hashlib.sha1(ident.encode("utf-8")).hexdigest()[:20]
        return f"place:photo:v1:{digest}"

    async def enrich_places_photos(
        self,
        db: AsyncSession,
        places: list[Place],
        *,
        force_refresh: bool = False,
    ) -> dict[str, int]:
        """
        Règles 4, 5 et 6 :
        - Les 5 villes de démo (source_provider == 'simulated') gardent leurs photos actuelles.
        - Parallélisme borné à 4 requêtes simultanées.
        - Cache en base (Place.photo_checked_at + colonnes photo_*) et Redis (une seule recherche par lieu).
        - Une seule photo par lieu, aucun doublon entre lieux d'une même ville.
        """
        if not places:
            return {"checked_count": 0, "updated_count": 0, "cached_count": 0}

        used_file_titles_by_dest: dict[str, set[str]] = {}
        used_photo_urls_by_dest: dict[str, set[str]] = {}

        for p in places:
            dest_titles = used_file_titles_by_dest.setdefault(p.destination_id, set())
            dest_urls = used_photo_urls_by_dest.setdefault(p.destination_id, set())
            if p.photo_file_title:
                dest_titles.add(normalize_commons_file_title(p.photo_file_title).lower())
            if isinstance(p.hero_photos, list):
                for url in p.hero_photos:
                    if isinstance(url, str) and url.strip():
                        dest_urls.add(url.strip())

        to_resolve: list[Place] = []
        cached_count = 0

        for place in places:
            # Règle 6 : Les 5 villes de démo gardent leurs photos actuelles
            if place.source_provider == "simulated":
                continue

            has_existing_photo = bool(
                isinstance(place.hero_photos, list)
                and len(place.hero_photos) > 0
                and place.photo_author
                and place.photo_license
            )
            if not force_refresh and (place.photo_checked_at is not None or has_existing_photo):
                cached_count += 1
                continue

            # Vérifie le cache Redis / mémoire par lieu (une seule recherche par lieu)
            cache_key = self._build_place_cache_key(place)
            cached_payload: dict[str, Any] | None = None
            if not force_refresh:
                try:
                    raw_redis = await cache_client.get_json(cache_key)
                    if isinstance(raw_redis, dict) and raw_redis.get("checked"):
                        cached_payload = raw_redis
                except Exception:
                    cached_payload = None
                if cached_payload is None and cache_key in self._local_memory_cache:
                    cached_payload = self._local_memory_cache[cache_key]

            if cached_payload is not None:
                res = ResolvedPlacePhoto.from_cache_dict(cached_payload)
                dest_titles = used_file_titles_by_dest.setdefault(place.destination_id, set())
                dest_urls = used_photo_urls_by_dest.setdefault(place.destination_id, set())
                is_dup = bool(
                    (res.photo_file_title and res.photo_file_title.lower() in dest_titles)
                    or (res.photo_url and res.photo_url in dest_urls)
                )
                if res.has_photo and res.photo_url and not is_dup:
                    place.hero_photos = [res.photo_url]
                    place.photo_file_title = res.photo_file_title
                    place.photo_author = res.photo_author
                    place.photo_license = res.photo_license
                    place.photo_commons_url = res.photo_commons_url
                    place.photo_source = res.photo_source
                    if res.photo_file_title:
                        dest_titles.add(res.photo_file_title.lower())
                    dest_urls.add(res.photo_url)
                else:
                    place.hero_photos = []
                    place.photo_source = "none"
                place.photo_checked_at = datetime.now(timezone.utc)
                cached_count += 1
                continue

            to_resolve.append(place)

        if not to_resolve:
            if cached_count > 0:
                await db.commit()
            return {"checked_count": 0, "updated_count": 0, "cached_count": cached_count}

        # Récupération en parallèle avec limite de simultanéité (4 requêtes via self._semaphore)
        place_Batch_Concurrency = asyncio.Semaphore(self._max_concurrency)
        resolved_pairs: list[tuple[Place, ResolvedPlacePhoto | None]] = []

        async with httpx.AsyncClient(transport=self._http_transport) as http_client:

            async def _worker(p: Place) -> tuple[Place, ResolvedPlacePhoto | None]:
                async with place_Batch_Concurrency:
                    try:
                        res = await self.resolve_place_photo(
                            place_name=p.name,
                            source_provider=p.source_provider,
                            external_place_id=p.external_place_id,
                            source_url=p.source_url,
                            latitude=p.latitude,
                            longitude=p.longitude,
                            opening_hours=p.opening_hours if isinstance(p.opening_hours, dict) else {},
                            client=http_client,
                        )
                        return (p, res)
                    except Exception:
                        # En cas de saturation/panne persistante après backoff, on ne bloque pas
                        # et on ne marque pas photo_checked_at pour permettre à la tâche de rattrapage de réessayer.
                        return (p, None)

            resolved_pairs = list(await asyncio.gather(*(_worker(p) for p in to_resolve)))

        checked_count = 0
        updated_count = 0
        now_utc = datetime.now(timezone.utc)

        for place, res in resolved_pairs:
            if res is None:
                continue
            checked_count += 1
            dest_titles = used_file_titles_by_dest.setdefault(place.destination_id, set())
            dest_urls = used_photo_urls_by_dest.setdefault(place.destination_id, set())

            norm_file = normalize_commons_file_title(res.photo_file_title or "").lower()
            is_duplicate = bool(
                (norm_file and norm_file in dest_titles)
                or (res.photo_url and res.photo_url in dest_urls)
            )

            if res.has_photo and res.photo_url and not is_duplicate:
                place.hero_photos = [res.photo_url]
                place.photo_file_title = res.photo_file_title
                place.photo_author = res.photo_author
                place.photo_license = res.photo_license
                place.photo_commons_url = res.photo_commons_url
                place.photo_source = res.photo_source
                if norm_file:
                    dest_titles.add(norm_file)
                dest_urls.add(res.photo_url)
                updated_count += 1
            else:
                place.hero_photos = []
                place.photo_file_title = None
                place.photo_author = None
                place.photo_license = None
                place.photo_commons_url = None
                place.photo_source = "none"
                if is_duplicate:
                    res = ResolvedPlacePhoto(
                        has_photo=False,
                        photo_source="none",
                        wikidata_id=res.wikidata_id,
                        wikipedia_title=res.wikipedia_title,
                        rejected_reason="duplicate_city_photo",
                    )

            place.photo_checked_at = now_utc

            cache_key = self._build_place_cache_key(place)
            cache_dict = res.to_cache_dict()
            self._local_memory_cache[cache_key] = cache_dict
            try:
                await cache_client.set_json(cache_key, cache_dict, ttl_seconds=PHOTO_CACHE_TTL_SECONDS)
            except Exception:
                pass

        await db.commit()
        return {
            "checked_count": checked_count,
            "updated_count": updated_count,
            "cached_count": cached_count,
        }

    async def backfill_missing_place_photos(
        self,
        db: AsyncSession,
        *,
        destination_id: str | None = None,
        limit: int = 60,
    ) -> dict[str, int]:
        """
        Règle 4 :
        Tâche de rattrapage pour les lieux déjà enregistrés en base sans photo.
        """
        stmt = (
            select(Place)
            .where(Place.source_provider != "simulated")
            .order_by(Place.notoriety_score.desc(), Place.name.asc())
        )
        if destination_id:
            stmt = stmt.where(Place.destination_id == destination_id)

        all_places = list((await db.scalars(stmt)).all())
        if not all_places:
            return {"checked_count": 0, "updated_count": 0, "cached_count": 0}

        # Regroupe par destination pour garantir l'unicité des photos dans chaque ville
        places_by_dest: dict[str, list[Place]] = {}
        for p in all_places:
            places_by_dest.setdefault(p.destination_id, []).append(p)

        total_checked = 0
        total_updated = 0
        total_cached = 0
        remaining = max(1, int(limit))

        for _dest_id, dest_places in places_by_dest.items():
            unchecked = [
                p
                for p in dest_places
                if p.photo_checked_at is None
                and (not isinstance(p.hero_photos, list) or len(p.hero_photos) == 0)
            ]
            if not unchecked:
                continue
            stats = await self.enrich_places_photos(db, dest_places[: remaining + len(dest_places)])
            total_checked += stats["checked_count"]
            total_updated += stats["updated_count"]
            total_cached += stats["cached_count"]
            remaining -= stats["checked_count"]
            if remaining <= 0:
                break

        return {
            "checked_count": total_checked,
            "updated_count": total_updated,
            "cached_count": total_cached,
        }


_GENERIC_STOPWORDS_FOR_PHOTO_MATCH: set[str] = {
    "de", "du", "des", "la", "le", "les", "et", "en", "au", "aux", "sur", "dans", "par", "avec",
    "the", "of", "in", "on", "at", "and", "to", "for", "from", "by", "as", "seen",
    "musee", "museum", "museo", "musei", "jardin", "jardins", "garden", "gardens", "giardino",
    "parc", "park", "parco", "place", "piazza", "palais", "palace", "temple", "sanctuaire",
    "shrine", "tour", "tower", "chateau", "castle", "colline", "marche", "market", "pont", "bridge",
    "paris", "tokyo", "rome", "roma", "new", "york", "nyc", "marrakech", "marrakesh", "morocco", "morroco",
    "street", "view", "east", "west", "north", "south", "night", "inside", "outside", "building",
    "main", "large", "small", "court", "corner", "looking", "wikimedia", "commons", "crop", "cropped",
}


def _extract_distinctive_tokens(raw_text: str) -> set[str]:
    norm = normalize_place_text(raw_text)
    tokens: set[str] = set()
    for tok in norm.split():
        if len(tok) < 3 or tok.isdigit():
            continue
        if tok in _GENERIC_STOPWORDS_FOR_PHOTO_MATCH:
            continue
        tokens.add(tok)
    for hyph in re.findall(r"[A-Za-zÀ-ÿ0-9]+-[A-Za-zÀ-ÿ0-9\-]+", str(raw_text or "")):
        compact = normalize_place_text(hyph).replace(" ", "")
        if len(compact) >= 4 and not compact.isdigit() and compact not in _GENERIC_STOPWORDS_FOR_PHOTO_MATCH:
            tokens.add(compact)
    return tokens


def verify_place_photo_correspondence(
    *,
    place_name: str,
    photo_file_title: str | None,
    external_place_id: str | None = None,
    opening_hours: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Contrôle automatique (Point 3) :
    Pour chaque photo, le titre du fichier Commons ou l'entité Wikidata doit correspondre
    au lieu (nom normalisé ou alias).
    """
    oh = opening_hours if isinstance(opening_hours, dict) else {}
    raw_candidates: list[str] = [str(place_name or "").strip()]
    # Ajoute aussi le nom hors parenthèses et le contenu entre parenthèses comme variantes du nom
    base_no_paren = re.sub(r"\([^)]*\)", " ", str(place_name or "")).strip()
    if base_no_paren and base_no_paren not in raw_candidates:
        raw_candidates.append(base_no_paren)
    for paren_match in re.findall(r"\(([^)]+)\)", str(place_name or "")):
        if paren_match.strip():
            raw_candidates.append(paren_match.strip())

    wp_title = str(oh.get("_wikipedia_title") or "").strip()
    if wp_title:
        raw_candidates.append(wp_title)
        wp_no_paren = re.sub(r"\([^)]*\)", " ", wp_title).strip()
        if wp_no_paren:
            raw_candidates.append(wp_no_paren)

    aliases = oh.get("_aliases")
    if isinstance(aliases, list):
        for al in aliases:
            if isinstance(al, str) and al.strip():
                raw_candidates.append(al.strip())

    normalized_candidates = [
        normalize_place_text(c) for c in raw_candidates if normalize_place_text(c)
    ]
    candidate_tokens: set[str] = set()
    for c in raw_candidates:
        candidate_tokens |= _extract_distinctive_tokens(c)

    norm_file = normalize_commons_file_title(photo_file_title or "")
    file_body = re.sub(r"\.[a-z0-9]{2,5}$", "", norm_file[5:].strip(), flags=re.IGNORECASE) if norm_file else ""
    norm_file_text = normalize_place_text(file_body)
    file_tokens = _extract_distinctive_tokens(file_body)

    title_phrase_match = bool(
        norm_file_text
        and any(cand and (cand in norm_file_text or norm_file_text in cand) for cand in normalized_candidates)
    )
    shared_tokens = sorted(candidate_tokens & file_tokens)
    title_matches = bool(title_phrase_match or len(shared_tokens) >= 1)

    ext_qid = str(external_place_id or "").strip().upper()
    oh_qid = str(oh.get("_wikidata_id") or "").strip().upper()
    has_valid_qid = bool(re.match(r"^Q\d+$", ext_qid)) and (not oh_qid or ext_qid == oh_qid)
    # L'entité Wikidata correspond au lieu si l'identifiant QID est valide et rattaché au titre/alias normalisé du lieu
    entity_label_norms = [
        normalize_place_text(c)
        for c in ([wp_title] + (aliases if isinstance(aliases, list) else []))
        if isinstance(c, str) and normalize_place_text(c)
    ]
    place_name_norms = [
        normalize_place_text(c)
        for c in [place_name, base_no_paren] + re.findall(r"\(([^)]+)\)", str(place_name or ""))
        if normalize_place_text(c)
    ]
    place_tokens = _extract_distinctive_tokens(place_name)
    entity_tokens: set[str] = set()
    for c in ([wp_title] + (aliases if isinstance(aliases, list) else [])):
        if isinstance(c, str):
            entity_tokens |= _extract_distinctive_tokens(c)

    wikidata_matches = bool(
        has_valid_qid
        and (
            any(
                en in pn or pn in en
                for en in entity_label_norms
                for pn in place_name_norms
            )
            or bool(place_tokens & entity_tokens)
        )
    )

    return {
        "matches": bool(title_matches and wikidata_matches) if has_valid_qid else bool(title_matches),
        "title_matches": title_matches,
        "wikidata_matches": wikidata_matches,
        "shared_tokens": shared_tokens,
        "normalized_file_text": norm_file_text,
        "wikidata_id": ext_qid or None,
    }


def verify_seed_demo_photos_integrity(
    destinations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Contrôle automatique complet sur les 70 lieux des 5 villes de démo (Points 1, 2, 3, 4, 5) :
    - Aucune photo Unsplash restante.
    - Aucune URL d'image ni aucun titre de fichier Commons n'apparaît sur deux lieux (dans une ville ou globalement).
    - Pour chaque lieu avec photo :
      * source wikidata_p18 ou wikipedia_pageimages
      * titre Commons, auteur, licence libre valide et URL Commons présents
      * le titre du fichier Commons ou l'entité Wikidata correspond au lieu (nom normalisé ou alias).
    - Pour chaque lieu sans photo : illustration neutre (hero_photos == [], photo_source == 'none').
    """
    if destinations is None:
        from app.core.seed import SEED_DESTINATIONS
        destinations = SEED_DESTINATIONS

    seen_urls_global: dict[str, str] = {}
    seen_titles_global: dict[str, str] = {}
    duplicate_urls: list[dict[str, str]] = []
    duplicate_file_titles: list[dict[str, str]] = []
    unsplash_urls: list[dict[str, str]] = []
    mismatched_places: list[dict[str, Any]] = []
    missing_credits: list[dict[str, str]] = []

    total_places = 0
    places_with_photo = 0
    places_without_photo = 0

    for dest in destinations:
        city = str(dest.get("city_name") or "")
        seen_urls_city: dict[str, str] = {}
        for place in dest.get("places", []):
            total_places += 1
            name = str(place.get("name") or "")
            label = f"{city} :: {name}"
            photos = place.get("hero_photos") or []

            if not photos:
                places_without_photo += 1
                if place.get("photo_source") not in (None, "none"):
                    mismatched_places.append(
                        {"place": label, "reason": "lieu_sans_photo_avec_source_invalide"}
                    )
                continue

            places_with_photo += 1
            if len(photos) != 1:
                mismatched_places.append({"place": label, "reason": "multiple_hero_photos"})

            url = str(photos[0] or "").strip()
            file_title = str(place.get("photo_file_title") or "").strip()
            author = str(place.get("photo_author") or "").strip()
            lic = str(place.get("photo_license") or "").strip()
            commons_url = str(place.get("photo_commons_url") or "").strip()
            source = str(place.get("photo_source") or "").strip()

            if "unsplash.com" in url.lower():
                unsplash_urls.append({"place": label, "url": url})

            if url in seen_urls_city:
                duplicate_urls.append(
                    {"city": city, "url": url, "first_place": seen_urls_city[url], "second_place": label}
                )
            else:
                seen_urls_city[url] = label

            if url in seen_urls_global:
                duplicate_urls.append(
                    {"city": "global", "url": url, "first_place": seen_urls_global[url], "second_place": label}
                )
            else:
                seen_urls_global[url] = label

            norm_title_key = normalize_commons_file_title(file_title).lower() if file_title else ""
            if norm_title_key:
                if norm_title_key in seen_titles_global:
                    duplicate_file_titles.append(
                        {
                            "file_title": file_title,
                            "first_place": seen_titles_global[norm_title_key],
                            "second_place": label,
                        }
                    )
                else:
                    seen_titles_global[norm_title_key] = label

            if (
                not file_title
                or not author
                or not normalize_and_validate_free_license(lic)
                or not commons_url.startswith("https://commons.wikimedia.org/wiki/File:")
                or source not in ("wikidata_p18", "wikipedia_pageimages", "wikipedia_pageimage")
                or is_forbidden_image_title_or_type(file_title)[0]
            ):
                missing_credits.append(
                    {
                        "place": label,
                        "photo_file_title": file_title,
                        "photo_author": author,
                        "photo_license": lic,
                        "photo_commons_url": commons_url,
                        "photo_source": source,
                    }
                )

            correspondence = verify_place_photo_correspondence(
                place_name=name,
                photo_file_title=file_title,
                external_place_id=place.get("external_place_id"),
                opening_hours=place.get("opening_hours"),
            )
            if not correspondence["matches"]:
                mismatched_places.append(
                    {
                        "place": label,
                        "photo_file_title": file_title,
                        "external_place_id": place.get("external_place_id"),
                        "detail": correspondence,
                    }
                )

        for acc in dest.get("accommodations", []):
            acc_name = str(acc.get("name") or "")
            acc_label = f"{city} :: [ACC] {acc_name}"
            acc_photos = acc.get("photos") or []
            if not acc_photos:
                if not acc.get("is_illustration") or acc.get("illustration_label") != "Illustration":
                    mismatched_places.append(
                        {"place": acc_label, "reason": "hebergement_sans_photo_doit_etre_illustration"}
                    )
                continue

            if len(acc_photos) != 1:
                mismatched_places.append({"place": acc_label, "reason": "multiple_accommodation_photos"})

            acc_url = str(acc_photos[0] or "").strip()
            acc_file_title = str(acc.get("photo_file_title") or "").strip()
            acc_author = str(acc.get("photo_author") or "").strip()
            acc_lic = str(acc.get("photo_license") or "").strip()
            acc_commons_url = str(acc.get("photo_commons_url") or "").strip()
            acc_source = str(acc.get("photo_source") or "").strip()
            acc_qid = str(acc.get("external_entity_id") or "").strip()

            if "unsplash.com" in acc_url.lower():
                unsplash_urls.append({"place": acc_label, "url": acc_url})

            if acc_url in seen_urls_city:
                duplicate_urls.append(
                    {"city": city, "url": acc_url, "first_place": seen_urls_city[acc_url], "second_place": acc_label}
                )
            else:
                seen_urls_city[acc_url] = acc_label

            if acc_url in seen_urls_global:
                duplicate_urls.append(
                    {"city": "global", "url": acc_url, "first_place": seen_urls_global[acc_url], "second_place": acc_label}
                )
            else:
                seen_urls_global[acc_url] = acc_label

            norm_acc_title = normalize_commons_file_title(acc_file_title).lower() if acc_file_title else ""
            if norm_acc_title:
                if norm_acc_title in seen_titles_global:
                    duplicate_file_titles.append(
                        {
                            "file_title": acc_file_title,
                            "first_place": seen_titles_global[norm_acc_title],
                            "second_place": acc_label,
                        }
                    )
                else:
                    seen_titles_global[norm_acc_title] = acc_label

            if (
                not acc_file_title
                or not acc_author
                or not normalize_and_validate_free_license(acc_lic)
                or not acc_commons_url.startswith("https://commons.wikimedia.org/wiki/File:")
                or acc_source not in ("wikidata_p18", "wikipedia_pageimages", "wikipedia_pageimage")
                or is_forbidden_image_title_or_type(acc_file_title)[0]
            ):
                missing_credits.append(
                    {
                        "place": acc_label,
                        "photo_file_title": acc_file_title,
                        "photo_author": acc_author,
                        "photo_license": acc_lic,
                        "photo_commons_url": acc_commons_url,
                        "photo_source": acc_source,
                    }
                )

            acc_corr = verify_place_photo_correspondence(
                place_name=acc_name,
                photo_file_title=acc_file_title,
                external_place_id=acc_qid,
                opening_hours={"_wikidata_id": acc_qid, "_aliases": acc.get("_aliases", [])},
            )
            if not acc_corr["matches"]:
                mismatched_places.append(
                    {
                        "place": acc_label,
                        "photo_file_title": acc_file_title,
                        "external_place_id": acc_qid,
                        "detail": acc_corr,
                    }
                )

    is_valid = (
        len(unsplash_urls) == 0
        and len(duplicate_urls) == 0
        and len(duplicate_file_titles) == 0
        and len(mismatched_places) == 0
        and len(missing_credits) == 0
    )

    errors = (
        unsplash_urls
        + duplicate_urls
        + duplicate_file_titles
        + mismatched_places
        + missing_credits
    )
    return {
        "is_valid": is_valid,
        "valid": is_valid,
        "errors": errors,
        "unsplash_count": len(unsplash_urls),
        "duplicate_url_count": len(duplicate_urls),
        "duplicate_title_count": len(duplicate_file_titles),
        "demo_cities_count": len(destinations),
        "total_demo_places": total_places,
        "places_with_photo": places_with_photo,
        "places_without_photo": places_without_photo,
        "unsplash_urls": unsplash_urls,
        "duplicate_urls": duplicate_urls,
        "duplicate_file_titles": duplicate_file_titles,
        "mismatched_places": mismatched_places,
        "missing_credits": missing_credits,
    }


def audit_demo_cities_photos() -> dict[str, Any]:
    """
    Vérifie l'état des 70 lieux des 5 villes de démo après application du pipeline
    Wikidata P18 -> Wikipédia pageimages -> Commons imageinfo, ainsi que les 5 lieux témoins :
    Jardin Majorelle, Tour Eiffel, Colisée, Met, Senso-ji.
    """
    from app.core.seed import SEED_DESTINATIONS

    integrity = verify_seed_demo_photos_integrity(SEED_DESTINATIONS)

    focus_targets = {
        "Jardin Majorelle": ("Marrakech", "Jardin Majorelle & Musée Yves Saint Laurent"),
        "Tour Eiffel": ("Paris", "Le Jules Verne (Tour Eiffel)"),
        "Colisée": ("Rome", "Colisée & Forum Romain"),
        "Met": ("New York", "Metropolitan Museum of Art (The Met)"),
        "Senso-ji": ("Tokyo", "Temple Senso-ji (Asakusa)"),
    }

    places_index: dict[tuple[str, str], dict[str, Any]] = {}
    for dest in SEED_DESTINATIONS:
        city = str(dest.get("city_name") or "")
        for p in dest.get("places", []):
            places_index[(city, str(p.get("name") or ""))] = p

    focus_landmarks: dict[str, dict[str, Any]] = {}
    for short_label, (city, place_name) in focus_targets.items():
        p = places_index.get((city, place_name), {})
        photos = p.get("hero_photos") or []
        url = photos[0] if photos else None
        corr = verify_place_photo_correspondence(
            place_name=place_name,
            photo_file_title=p.get("photo_file_title"),
            external_place_id=p.get("external_place_id"),
            opening_hours=p.get("opening_hours"),
        )
        focus_landmarks[short_label] = {
            "city": city,
            "place_name": place_name,
            "wikidata_id": p.get("external_place_id"),
            "url": url,
            "photo_file_title": p.get("photo_file_title"),
            "photo_author": p.get("photo_author"),
            "photo_license": p.get("photo_license"),
            "photo_commons_url": p.get("photo_commons_url"),
            "photo_source": p.get("photo_source"),
            "credit_text": format_photo_credit(p.get("photo_author"), p.get("photo_license")),
            "matches_place": bool(url and corr["matches"]),
            "title_matches": corr["title_matches"],
            "wikidata_matches": corr["wikidata_matches"],
            "status": "correspond" if (url and corr["matches"]) else "ne_correspond_pas",
        }

    return {
        **integrity,
        "demo_photos_preserved": True,
        "focus_landmarks": focus_landmarks,
        "other_mismatches": integrity["mismatched_places"],
    }


world_place_photo_service = WorldPlacePhotoService()


def get_world_place_photo_service() -> WorldPlacePhotoService:
    return world_place_photo_service


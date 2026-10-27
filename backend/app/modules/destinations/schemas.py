from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DestinationResolveRequest(BaseModel):
    geoname_id: int | None = Field(default=None, description="Identifiant unique GeoNames (geonameId)")
    city_name: str = Field(..., min_length=2, max_length=120)
    country_name: str = Field(default="Monde", min_length=2, max_length=120)
    country_code_iso2: str = Field(default="XX", min_length=2, max_length=2)
    iata_code: str | None = Field(default=None, min_length=3, max_length=3)
    timezone: str = Field(default="UTC")
    latitude: float | None = None
    longitude: float | None = None
    population: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_geonames_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)

        # geonameId -> geoname_id
        if out.get("geoname_id") is None and out.get("geonameId") is not None:
            out["geoname_id"] = int(out["geonameId"])

        # nom / name -> city_name
        if not out.get("city_name"):
            for alias in ("nom", "name", "toponymName"):
                if out.get(alias):
                    out["city_name"] = str(out[alias]).strip()
                    break

        # pays / countryName / country -> country_name
        if not out.get("country_name"):
            for alias in ("pays", "countryName", "country"):
                if out.get(alias):
                    out["country_name"] = str(out[alias]).strip()
                    break

        # code_pays / countryCode -> country_code_iso2
        if not out.get("country_code_iso2"):
            for alias in ("code_pays", "countryCode", "country_code"):
                if out.get(alias):
                    out["country_code_iso2"] = str(out[alias]).strip().upper()[:2]
                    break

        # coordonnees / coordinates / lat / lng -> latitude, longitude
        coords = out.get("coordonnees") or out.get("coordinates")
        if isinstance(coords, dict):
            if out.get("latitude") is None:
                lat_val = coords.get("latitude", coords.get("lat"))
                if lat_val is not None:
                    out["latitude"] = float(lat_val)
            if out.get("longitude") is None:
                lng_val = coords.get("longitude", coords.get("lng"))
                if lng_val is not None:
                    out["longitude"] = float(lng_val)
        if out.get("latitude") is None and out.get("lat") is not None:
            out["latitude"] = float(out["lat"])
        if out.get("longitude") is None and out.get("lng") is not None:
            out["longitude"] = float(out["lng"])

        # fuseau_horaire / timezone (dict ou str) -> timezone
        tz_raw = out.get("fuseau_horaire") or out.get("timezone")
        if isinstance(tz_raw, dict):
            tz_id = tz_raw.get("timeZoneId") or tz_raw.get("timezone") or "UTC"
            out["timezone"] = str(tz_id).strip() or "UTC"
        elif isinstance(tz_raw, str) and tz_raw.strip():
            out["timezone"] = tz_raw.strip()

        return out


class GeoNamesCityResult(BaseModel):
    geonameId: int
    geoname_id: int
    nom: str
    name: str
    city_name: str
    pays: str
    country_name: str
    code_pays: str
    country_code_iso2: str
    coordonnees: dict[str, float]
    coordinates: dict[str, float]
    latitude: float
    longitude: float
    fuseau_horaire: str
    timezone: str
    population: int = 0
    iata_code: str = "XXX"
    is_seed: bool = False
    destination_id: str | None = None


class GeoNamesSearchResponse(BaseModel):
    query: str
    normalized_query: str
    available: bool = True
    fallback: bool = False
    cached: bool = False
    quota_exceeded: bool = False
    reason: str | None = None
    message: str | None = None
    results: list[GeoNamesCityResult]
    fallback_cities: list[GeoNamesCityResult]


class UsefulPhraseSchema(BaseModel):
    french: str
    local_translation: str
    pronunciation: str
    context_fr: str = "Vie courante"


class PracticalInfoResponse(BaseModel):
    destination_id: str
    city_name: str
    country_name: str
    target_language: str
    plugs: str
    tipping: str
    emergency: str
    dial_code: str
    currency: str
    source: str
    updated_at_fr: str
    useful_phrases: list[UsefulPhraseSchema]


class TranslateRequest(BaseModel):
    """Formulaire du traducteur (2 champs maximum <= 4 champs)."""

    text: str = Field(..., min_length=1, max_length=500)
    target_language: str | None = Field(default=None, max_length=80)


class TranslateResponse(BaseModel):
    destination_id: str
    city_name: str
    target_language: str
    source_text: str
    translated_text: str
    translation: str = ""
    pronunciation: str
    mode: str = "SIMULATED_DETERMINISTIC"
    provider_label_fr: str = "Traducteur de voyage déterministe"


class DestinationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    geoname_id: int | None = None
    geonameId: int | None = None
    city_name: str
    country_name: str
    country_code_iso2: str
    iata_code: str
    timezone: str
    latitude: float
    longitude: float
    population: int | None = None
    is_seed: bool = False
    hero_image_url: str
    description: str
    practical_info: dict[str, Any]
    useful_phrases: list[dict[str, Any]]

"""Catalogue d'aéroports réels issu de OurAirports (codes IATA officiels et coordonnées GPS).

Règle métier C.9 & Finition 5 :
- Le fichier OurAirports est inclus localement dans le projet (`backend/data/ourairports_iata.csv`)
  avec sa licence (`backend/data/OURAIRPORTS_LICENSE.txt`), jamais téléchargé au démarrage.
- Le code IATA d'une ville n'est JAMAIS déduit des lettres de son nom (ex: Monastir -> MIR, jamais MON ;
  Lisbonne -> LIS ; Séoul -> ICN).
- La sélection repose sur la distance Haversine depuis les coordonnées (latitude, longitude) de la ville.
- Si aucun aéroport n'est à moins de 100 km, on retourne l'aéroport le plus proche avec sa distance en km.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

OURAIRPORTS_DATA_DIR: Path = Path(__file__).resolve().parents[2] / "data"
OURAIRPORTS_CSV_PATH: Path = OURAIRPORTS_DATA_DIR / "ourairports_iata.csv"
OURAIRPORTS_LICENSE_PATH: Path = OURAIRPORTS_DATA_DIR / "OURAIRPORTS_LICENSE.txt"


@dataclass(frozen=True)
class AirportRecord:
    iata_code: str
    name: str
    municipality: str
    country_code: str
    latitude: float
    longitude: float
    is_major_hub: bool = False
    ident: str = ""
    airport_type: str = "medium_airport"


def load_ourairports_catalog(csv_path: Path = OURAIRPORTS_CSV_PATH) -> tuple[AirportRecord, ...]:
    """Charge le fichier OurAirports local (`backend/data/ourairports_iata.csv`)."""
    records: list[AirportRecord] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            iata = (row.get("iata_code") or "").strip().upper()
            if len(iata) != 3:
                continue
            if (row.get("scheduled_service") or "yes").strip().lower() != "yes":
                continue
            airport_type = (row.get("type") or "medium_airport").strip()
            records.append(
                AirportRecord(
                    iata_code=iata,
                    name=(row.get("name") or iata).strip(),
                    municipality=(row.get("municipality") or "").strip(),
                    country_code=(row.get("iso_country") or "").strip().upper(),
                    latitude=float(row["latitude_deg"]),
                    longitude=float(row["longitude_deg"]),
                    is_major_hub=(airport_type == "large_airport"),
                    ident=(row.get("ident") or "").strip().upper(),
                    airport_type=airport_type,
                )
            )
    return tuple(records)


# Catalogue chargé localement depuis backend/data/ourairports_iata.csv (aucun téléchargement réseau)
OURAIRPORTS_CATALOG: tuple[AirportRecord, ...] = load_ourairports_catalog()

AIRPORTS_BY_IATA: dict[str, AirportRecord] = {
    rec.iata_code.upper(): rec for rec in OURAIRPORTS_CATALOG
}

# Codes de ville multi-aéroports utilisés par les comparateurs (Google Flights, Kayak, Skyscanner)
METRO_CITY_CODES: dict[str, dict[str, object]] = {
    "MIL": {
        "city_name": "Milan",
        "primary_iata": "MXP",
        "airports": ("MXP", "LIN", "BGY"),
        "aliases": ("milan", "milano"),
        "country_code": "IT",
    },
    "LON": {
        "city_name": "Londres",
        "primary_iata": "LHR",
        "airports": ("LHR", "LGW", "STN", "LTN", "LCY"),
        "aliases": ("londres", "london"),
        "country_code": "GB",
    },
    "PAR": {
        "city_name": "Paris",
        "primary_iata": "CDG",
        "airports": ("CDG", "ORY", "BVA"),
        "aliases": ("paris",),
        "country_code": "FR",
    },
    "NYC": {
        "city_name": "New York",
        "primary_iata": "JFK",
        "airports": ("JFK", "EWR", "LGA"),
        "aliases": ("new york", "new york city"),
        "country_code": "US",
    },
    "TYO": {
        "city_name": "Tokyo",
        "primary_iata": "HND",
        "airports": ("HND", "NRT"),
        "aliases": ("tokyo",),
        "country_code": "JP",
    },
    "ROM": {
        "city_name": "Rome",
        "primary_iata": "FCO",
        "airports": ("FCO", "CIA"),
        "aliases": ("rome", "roma"),
        "country_code": "IT",
    },
}

AIRPORT_TO_METRO_CODE: dict[str, str] = {}
CITY_ALIAS_TO_METRO_CODE: dict[str, str] = {}
for _metro_code, _info in METRO_CITY_CODES.items():
    AIRPORT_TO_METRO_CODE[_metro_code] = _metro_code
    for _ap in _info["airports"]:  # type: ignore[attr-defined]
        AIRPORT_TO_METRO_CODE[str(_ap).upper()] = _metro_code
    for _alias in _info["aliases"]:  # type: ignore[attr-defined]
        CITY_ALIAS_TO_METRO_CODE[str(_alias).lower()] = _metro_code


def get_city_comparator_code(iata_or_code: str | None, city_name: str | None = None) -> str:
    """Retourne le code de ville normalisé pour les comparateurs (ex: MIL, LON, PAR, NYC)
    ou le code IATA de l'aéroport (ex: MIR, SYD, LYS, LIS)."""
    raw_code = (iata_or_code or "").strip().upper()
    raw_city = (city_name or "").strip().lower()
    if raw_city in CITY_ALIAS_TO_METRO_CODE:
        return CITY_ALIAS_TO_METRO_CODE[raw_city]
    if raw_code in AIRPORT_TO_METRO_CODE:
        return AIRPORT_TO_METRO_CODE[raw_code]
    return raw_code or "PAR"


def resolve_airport_record(code_or_city: str | None) -> AirportRecord | None:
    """Résout un code IATA d'aéroport (CDG, MIR, SYD, LYS), un code de ville (MIL, LON, PAR, NYC)
    ou un nom de ville depuis le catalogue OurAirports local."""
    raw = (code_or_city or "").strip()
    if not raw:
        return None
    up = raw.upper()
    if up in AIRPORTS_BY_IATA:
        return AIRPORTS_BY_IATA[up]
    if up in METRO_CITY_CODES:
        primary_iata = str(METRO_CITY_CODES[up]["primary_iata"])
        return AIRPORTS_BY_IATA.get(primary_iata)
    low = raw.lower()
    if low in CITY_ALIAS_TO_METRO_CODE:
        metro = CITY_ALIAS_TO_METRO_CODE[low]
        primary_iata = str(METRO_CITY_CODES[metro]["primary_iata"])
        return AIRPORTS_BY_IATA.get(primary_iata)
    for rec in OURAIRPORTS_CATALOG:
        if rec.municipality.strip().lower() == low:
            return rec
    return None


def are_airport_codes_equivalent(code_a: str | None, code_b: str | None) -> bool:
    """Vérifie si deux codes désignent le même aéroport ou la même agglomération (ex: MIL et MXP/LIN, PAR et CDG)."""
    a = (code_a or "").strip().upper()
    b = (code_b or "").strip().upper()
    if not a or not b:
        return False
    if a == b:
        return True
    metro_a = AIRPORT_TO_METRO_CODE.get(a, a)
    metro_b = AIRPORT_TO_METRO_CODE.get(b, b)
    return metro_a == metro_b


def build_flight_comparator_urls(
    origin_code: str,
    destination_code: str,
    departure_date: str,
    return_date: str,
    origin_city: str | None = None,
    destination_city: str | None = None,
) -> dict[str, str]:
    """Construit les URLs vers Google Flights, Kayak et Skyscanner avec les codes de ville (MIL, LON, PAR, NYC)."""
    orig_comp = get_city_comparator_code(origin_code, origin_city)
    dest_comp = get_city_comparator_code(destination_code, destination_city)
    dep_str = str(departure_date)[:10]
    ret_str = str(return_date)[:10]
    return {
        "origin_code": orig_comp,
        "destination_code": dest_comp,
        "origin_city_code": orig_comp,
        "destination_city_code": dest_comp,
        "google_flights": (
            f"https://www.google.com/travel/flights?hl=fr&curr=EUR"
            f"&q=Vols+{orig_comp}+{dest_comp}+{dep_str}+{ret_str}"
        ),
        "kayak": f"https://www.kayak.fr/flights/{orig_comp}-{dest_comp}/{dep_str}/{ret_str}",
        "skyscanner": (
            f"https://www.skyscanner.fr/transport/vols/"
            f"{orig_comp.lower()}/{dest_comp.lower()}/{dep_str}/{ret_str}/"
        ),
    }


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcule la distance orthodromique en kilomètres entre deux coordonnées GPS."""
    radius_earth_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return radius_earth_km * c


def find_nearest_airport(
    latitude: float,
    longitude: float,
    city_name: str | None = None,
    country_code: str | None = None,
) -> dict[str, object]:
    """Trouve l'aéroport officiel (OurAirports) le plus proche des coordonnées de la ville.

    - Ne déduit JAMAIS le code IATA à partir des lettres du nom de la ville.
    - Si au moins un aéroport est à <= 100 km :
      - S'il existe un hub international majeur à <= 35 km, on le privilégie (ex: CDG pour Paris,
        HND pour Tokyo, JFK pour New York, FCO pour Rome, ICN pour Séoul, GRU pour São Paulo).
      - Sinon on retourne l'aéroport strictement le plus proche (ex: MIR à 6,8 km pour Monastir).
    - Si aucun aéroport n'est à moins de 100 km, retourne le plus proche avec sa distance en km.
    """
    scored: list[tuple[float, AirportRecord]] = []
    for airport in OURAIRPORTS_CATALOG:
        dist = haversine_distance_km(latitude, longitude, airport.latitude, airport.longitude)
        scored.append((dist, airport))

    scored.sort(key=lambda pair: pair[0])
    closest_dist, closest_airport = scored[0]

    chosen_dist = closest_dist
    chosen_airport = closest_airport

    # Si plusieurs aéroports desservent la même agglomération,
    # privilégier le hub international principal (ex: CDG vs ORY, JFK vs LGA, ICN vs GMP, GRU vs CGH)
    if closest_dist <= 35.0 and not closest_airport.is_major_hub:
        for dist, airport in scored:
            if dist > 60.0:
                break
            same_metro = (
                dist <= 38.0
                or airport.municipality.strip().lower() == closest_airport.municipality.strip().lower()
            )
            if (
                airport.is_major_hub
                and airport.country_code == closest_airport.country_code
                and same_metro
            ):
                chosen_dist = dist
                chosen_airport = airport
                break

    rounded_km = round(chosen_dist, 1)
    within_100km = chosen_dist <= 100.0

    city_code = get_city_comparator_code(
        chosen_airport.iata_code,
        city_name or chosen_airport.municipality,
    )
    # Pour Milan (MXP/LIN/BGY), le code de ville attendu est MIL
    effective_iata = (
        "MIL"
        if chosen_airport.iata_code in {"MXP", "LIN", "BGY"}
        and (city_name or chosen_airport.municipality).strip().lower() in {"milan", "milano"}
        else chosen_airport.iata_code
    )

    if within_100km:
        display_label = f"{chosen_airport.municipality} ({effective_iata})"
    else:
        display_label = (
            f"{chosen_airport.municipality} ({effective_iata} — à {round(chosen_dist)} km)"
        )

    return {
        "iata_code": effective_iata,
        "city_code": city_code,
        "primary_airport_iata": chosen_airport.iata_code,
        "airport_name": chosen_airport.name,
        "municipality": chosen_airport.municipality,
        "country_code": chosen_airport.country_code,
        "distance_km": rounded_km,
        "within_100km": within_100km,
        "display_label": display_label,
    }

import math


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcule la distance orthodromique (Haversine) en kilomètres entre deux coordonnées GPS."""
    earth_radius_km = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return round(earth_radius_km * c, 3)


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Calcule la distance orthodromique en mètres."""
    return int(round(haversine_distance_km(lat1, lon1, lat2, lon2) * 1000))


def estimate_walking_minutes(distance_m: int) -> int:
    """Estime le temps de marche en minutes à une vitesse moyenne urbaine de 4.5 km/h (75 m/min)."""
    if distance_m <= 0:
        return 1
    return max(1, int(math.ceil(distance_m / 75.0)))


def normalize_transit_mode(mode: str | None) -> str:
    """Normalise le mode de transport vers WALKING, METRO ou CAR."""
    cleaned = (mode or "METRO").strip().upper()
    if cleaned in ("WALK", "WALKING"):
        return "WALKING"
    if cleaned == "CAR":
        return "CAR"
    return "METRO"


def estimate_transit_duration_min(distance_km: float, mode: str = "METRO") -> int:
    """
    Calcule le temps de trajet réaliste en minutes entre deux lieux selon le mode :
    - WALKING : ~4.5 km/h en milieu urbain (~13.33 min/km, min 5 min)
    - METRO   : 6 min d'accès/attente + ~28 km/h (~2.15 min/km, min 8 min)
    - CAR     : 4 min de prise en charge + ~32 km/h en ville (~1.88 min/km, min 6 min)
    """
    norm_mode = normalize_transit_mode(mode)
    if distance_km <= 0.03:
        return 5
    if norm_mode == "WALKING":
        return max(5, int(math.ceil(distance_km * 13.34)))
    if norm_mode == "CAR":
        return max(6, int(math.ceil(4.0 + distance_km * 1.88)))
    # METRO par défaut
    return max(8, int(math.ceil(6.0 + distance_km * 2.15)))


def recommend_transit_mode(distance_km: float) -> str:
    """Choisit automatiquement le mode de transport le plus pertinent selon la distance."""
    if distance_km <= 1.2:
        return "WALKING"
    if distance_km <= 8.5:
        return "METRO"
    return "CAR"

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings
from app.core.geo import (
    estimate_transit_duration_min,
    haversine_distance_km,
    haversine_distance_m,
    normalize_transit_mode,
)


class _DSTFallbackTz(tzinfo):
    """
    Fuseau horaire de repli avec calcul exact du changement d'heure (DST Europe / Amérique du Nord)
    utilisé uniquement si la base IANA système (tzdata) n'est pas installée sur l'hôte Windows.
    """

    def __init__(self, iana_name: str, std_offset_hours: int, dst_region: str | None = None) -> None:
        self.iana_name = iana_name
        self.std_offset = timedelta(hours=std_offset_hours)
        self.dst_region = dst_region

    def _is_dst(self, dt: datetime | None) -> bool:
        if dt is None or self.dst_region is None:
            return False
        year = dt.year
        naive = dt.replace(tzinfo=None)
        if self.dst_region == "EU":
            # Dernier dimanche de mars (02:00) -> Dernier dimanche d'octobre (03:00)
            march_last = date(year, 3, 31)
            march_sun = march_last - timedelta(days=(march_last.weekday() + 1) % 7)
            oct_last = date(year, 10, 31)
            oct_sun = oct_last - timedelta(days=(oct_last.weekday() + 1) % 7)
            start_dst = datetime.combine(march_sun, time(2, 0))
            end_dst = datetime.combine(oct_sun, time(3, 0))
            return start_dst <= naive < end_dst
        if self.dst_region == "US":
            # 2e dimanche de mars (02:00) -> 1er dimanche de novembre (02:00)
            march_first = date(year, 3, 1)
            first_sun_m = march_first + timedelta(days=(6 - march_first.weekday()) % 7)
            second_sun_m = first_sun_m + timedelta(days=7)
            nov_first = date(year, 11, 1)
            first_sun_n = nov_first + timedelta(days=(6 - nov_first.weekday()) % 7)
            start_dst = datetime.combine(second_sun_m, time(2, 0))
            end_dst = datetime.combine(first_sun_n, time(2, 0))
            return start_dst <= naive < end_dst
        return False

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return self.std_offset + self.dst(dt)

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=1) if self._is_dst(dt) else timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return self.iana_name


_FALLBACK_TIMEZONES: dict[str, _DSTFallbackTz] = {
    "UTC": _DSTFallbackTz("UTC", 0, None),
    "Europe/Paris": _DSTFallbackTz("Europe/Paris", 1, "EU"),
    "Europe/Rome": _DSTFallbackTz("Europe/Rome", 1, "EU"),
    "Europe/Madrid": _DSTFallbackTz("Europe/Madrid", 1, "EU"),
    "Europe/London": _DSTFallbackTz("Europe/London", 0, "EU"),
    "Asia/Tokyo": _DSTFallbackTz("Asia/Tokyo", 9, None),
    "America/New_York": _DSTFallbackTz("America/New_York", -5, "US"),
    "Africa/Casablanca": _DSTFallbackTz("Africa/Casablanca", 1, None),
}


def resolve_destination_tz(timezone_name: str | None) -> tzinfo:
    """Résout le fuseau horaire IANA de la destination (avec gestion DST)."""
    tz_key = (timezone_name or "UTC").strip()
    try:
        return ZoneInfo(tz_key)
    except ZoneInfoNotFoundError:
        return _FALLBACK_TIMEZONES.get(tz_key, timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    """Garantit qu'un datetime est stocké et manipulé en UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_destination_local(dt: datetime, timezone_name: str | None) -> datetime:
    """Convertit un datetime UTC dans le fuseau horaire local de la destination."""
    utc_dt = ensure_utc(dt)
    dest_tz = resolve_destination_tz(timezone_name)
    return utc_dt.astimezone(dest_tz)


def parse_local_slot_to_utc(
    visit_date: date,
    local_start_time_str: str,
    duration_minutes: int,
    timezone_name: str | None,
) -> tuple[datetime, datetime]:
    """
    Construit un créneau (start_at_utc, end_at_utc) à partir d'une date et d'une heure
    exprimées dans le fuseau horaire de la destination.
    """
    parts = local_start_time_str.strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    dest_tz = resolve_destination_tz(timezone_name)
    naive_local = datetime.combine(visit_date, time(hour=hour, minute=minute))
    if isinstance(dest_tz, _DSTFallbackTz):
        offset = dest_tz.utcoffset(naive_local)
        fixed = timezone(offset, name=dest_tz.iana_name)
        local_dt = naive_local.replace(tzinfo=fixed)
    else:
        local_dt = naive_local.replace(tzinfo=dest_tz)
    start_utc = local_dt.astimezone(timezone.utc)
    end_utc = start_utc + timedelta(minutes=duration_minutes)
    return start_utc, end_utc


@dataclass
class ScheduledVisitSnapshot:
    """Représentation légère d'une visite existante pour le moteur de validation."""

    item_id: str
    place_id: str
    place_name: str
    latitude: float
    longitude: float
    start_at_utc: datetime
    end_at_utc: datetime
    transit_mode_to_next: str = "METRO"


@dataclass
class SuggestedSlot:
    start_at_utc: datetime
    end_at_utc: datetime
    local_date: str
    local_start_time: str
    local_end_time: str
    timezone: str
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_at": self.start_at_utc.isoformat(),
            "end_at": self.end_at_utc.isoformat(),
            "local_date": self.local_date,
            "local_start_time": self.local_start_time,
            "local_end_time": self.local_end_time,
            "timezone": self.timezone,
            "label": self.label,
        }


@dataclass
class ValidationResult:
    valid: bool
    reason_code: str | None = None
    message: str = "Visite valide."
    conflict_details: dict[str, Any] = field(default_factory=dict)
    suggested_slots: list[SuggestedSlot] = field(default_factory=list)
    transit_from_previous_min: int = 0
    transit_from_previous_m: int = 0
    transit_to_next_min: int = 0
    transit_to_next_m: int = 0

    def to_error_payload(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "reason_code": self.reason_code,
            "message": self.message,
            "conflict_details": self.conflict_details,
            "suggested_slots": [s.to_dict() for s in self.suggested_slots],
        }


WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def get_opening_window_minutes(
    opening_hours: dict[str, Any] | None,
    local_dt: datetime,
) -> tuple[int, int, str] | None:
    """
    Extrait la plage d'ouverture (open_min, close_min, raw_str) pour le jour local donné.
    Retourne None si le lieu est fermé ce jour-là.
    """
    if not opening_hours:
        return (8 * 60, 22 * 60, "08:00-22:00")

    day_key = WEEKDAY_KEYS[local_dt.weekday()]
    raw_range = opening_hours.get(day_key) or opening_hours.get("daily")
    if not raw_range:
        return (8 * 60, 22 * 60, "08:00-22:00")

    cleaned = str(raw_range).strip().lower()
    if cleaned in ("closed", "fermé", "ferme"):
        return None

    try:
        open_str, close_str = cleaned.split("-")
        oh, om = [int(x) for x in open_str.strip().split(":")]
        ch, cm = [int(x) for x in close_str.strip().split(":")]
        open_min = oh * 60 + om
        close_min = ch * 60 + cm
        if close_min <= open_min:
            close_min = 23 * 60 + 59
        return (open_min, close_min, f"{oh:02d}:{om:02d}-{ch:02d}:{cm:02d}")
    except Exception:
        return (8 * 60, 22 * 60, "08:00-22:00")


class ItineraryValidationEngine:
    """
    Moteur de validation centralisé de TravelMate (réutilisable par l'itinéraire manuel,
    le glisser-déposer, l'optimiseur géographique, le planificateur IA, la météo et le chat).
    """

    @staticmethod
    def resolve_trip_window_buffers(
        arrival_buffer_hours: float | None = None,
        departure_buffer_hours: float | None = None,
    ) -> tuple[float, float]:
        settings = get_settings()
        arr_buf = (
            float(settings.TRIP_ARRIVAL_BUFFER_HOURS)
            if arrival_buffer_hours is None
            else float(arrival_buffer_hours)
        )
        dep_buf = (
            float(settings.TRIP_DEPARTURE_BUFFER_HOURS)
            if departure_buffer_hours is None
            else float(departure_buffer_hours)
        )
        return arr_buf, dep_buf

    @classmethod
    def _check_single_slot(
        cls,
        *,
        trip_arrival_utc: datetime | None,
        trip_departure_utc: datetime | None,
        destination_tz_name: str,
        place_id: str,
        place_name: str,
        place_lat: float,
        place_lng: float,
        place_opening_hours: dict[str, Any] | None,
        start_at_utc: datetime,
        end_at_utc: datetime,
        transit_mode: str,
        existing_visits: list[ScheduledVisitSnapshot],
        exclude_item_id: str | None = None,
        arrival_buffer_hours: float | None = None,
        departure_buffer_hours: float | None = None,
        allow_duplicate_place: bool = False,
    ) -> ValidationResult:
        start_utc = ensure_utc(start_at_utc)
        end_utc = ensure_utc(end_at_utc)
        norm_mode = normalize_transit_mode(transit_mode)

        if end_utc <= start_utc:
            return ValidationResult(
                valid=False,
                reason_code="INVALID_DURATION",
                message="L'heure de fin de la visite doit être strictement postérieure à l'heure de début.",
            )

        # Règle 1 : La visite doit rester dans la fenêtre utile du séjour
        # (début = arrivée aller + tampon d'arrivée, fin = départ retour - tampon de départ)
        if trip_arrival_utc is None or trip_departure_utc is None:
            return ValidationResult(
                valid=False,
                reason_code="OUTSIDE_TRIP_WINDOW",
                message=(
                    "Impossible de planifier une visite tant que les dates d'arrivée et de départ "
                    "du séjour ne sont pas définies (réservez d'abord votre billet d'avion)."
                ),
            )

        arr_buf_h, dep_buf_h = cls.resolve_trip_window_buffers(
            arrival_buffer_hours=arrival_buffer_hours,
            departure_buffer_hours=departure_buffer_hours,
        )
        raw_arr_utc = ensure_utc(trip_arrival_utc)
        raw_dep_utc = ensure_utc(trip_departure_utc)
        effective_arr_utc = raw_arr_utc + timedelta(hours=arr_buf_h)
        effective_dep_utc = raw_dep_utc - timedelta(hours=dep_buf_h)

        local_start = to_destination_local(start_utc, destination_tz_name)
        local_end = to_destination_local(end_utc, destination_tz_name)
        local_raw_arr = to_destination_local(raw_arr_utc, destination_tz_name)
        local_raw_dep = to_destination_local(raw_dep_utc, destination_tz_name)
        local_eff_arr = to_destination_local(effective_arr_utc, destination_tz_name)
        local_eff_dep = to_destination_local(effective_dep_utc, destination_tz_name)

        if start_utc < effective_arr_utc or end_utc > effective_dep_utc:
            if start_utc < raw_arr_utc:
                violation_phase = "BEFORE_ARRIVAL"
                phase_reason = (
                    f"avant l'atterrissage du vol aller ({local_raw_arr.strftime('%d/%m/%Y %H:%M')})"
                )
            elif start_utc < effective_arr_utc:
                violation_phase = "ARRIVAL_BUFFER"
                phase_reason = (
                    f"dans le tampon d'arrivée de {arr_buf_h:g} h après le vol aller "
                    f"(début des visites autorisé à partir de {local_eff_arr.strftime('%d/%m/%Y %H:%M')})"
                )
            elif end_utc > raw_dep_utc:
                violation_phase = "AFTER_DEPARTURE"
                phase_reason = (
                    f"après le décollage du vol retour ({local_raw_dep.strftime('%d/%m/%Y %H:%M')})"
                )
            else:
                violation_phase = "DEPARTURE_BUFFER"
                phase_reason = (
                    f"dans le tampon de départ de {dep_buf_h:g} h avant le vol retour "
                    f"(fin des visites exigée au plus tard à {local_eff_dep.strftime('%d/%m/%Y %H:%M')})"
                )

            return ValidationResult(
                valid=False,
                reason_code="OUTSIDE_TRIP_WINDOW",
                message=(
                    f"Visite refusée : le créneau demandé ({local_start.strftime('%d/%m/%Y %H:%M')} -> "
                    f"{local_end.strftime('%d/%m/%Y %H:%M')}) sort de la période "
                    f"du séjour ({local_eff_arr.strftime('%d/%m/%Y %H:%M')} -> {local_eff_dep.strftime('%d/%m/%Y %H:%M')}) : "
                    f"{phase_reason}."
                ),
                conflict_details={
                    "violation_phase": violation_phase,
                    "arrival_buffer_hours": arr_buf_h,
                    "departure_buffer_hours": dep_buf_h,
                    "trip_arrival_local": local_raw_arr.isoformat(),
                    "trip_departure_local": local_raw_dep.isoformat(),
                    "effective_window_start_local": local_eff_arr.isoformat(),
                    "effective_window_end_local": local_eff_dep.isoformat(),
                    "effective_window_start_utc": effective_arr_utc.isoformat(),
                    "effective_window_end_utc": effective_dep_utc.isoformat(),
                    "requested_start_local": local_start.isoformat(),
                    "requested_end_local": local_end.isoformat(),
                    "timezone": destination_tz_name,
                },
            )

        # Règle 2 : Respect des horaires d'ouverture du lieu dans le fuseau de la destination
        opening = get_opening_window_minutes(place_opening_hours, local_start)
        if opening is None:
            return ValidationResult(
                valid=False,
                reason_code="OUTSIDE_OPENING_HOURS",
                message=f"Visite refusée : « {place_name} » est fermé le {local_start.strftime('%d/%m/%Y')}.",
                conflict_details={"place_name": place_name, "opening_hours": "Fermé"},
            )

        open_min, close_min, hours_label = opening
        start_min_of_day = local_start.hour * 60 + local_start.minute
        end_min_of_day = local_end.hour * 60 + local_end.minute
        same_local_day = local_start.date() == local_end.date()

        if (not same_local_day) or start_min_of_day < open_min or end_min_of_day > close_min:
            return ValidationResult(
                valid=False,
                reason_code="OUTSIDE_OPENING_HOURS",
                message=(
                    f"Visite refusée : « {place_name} » est ouvert de {hours_label.replace('-', ' à ')}, "
                    f"alors que le créneau demandé est "
                    f"{local_start.strftime('%H:%M')} à {local_end.strftime('%H:%M')}."
                ),
                conflict_details={
                    "place_name": place_name,
                    "opening_hours": hours_label,
                    "requested_local": f"{local_start.strftime('%H:%M')}-{local_end.strftime('%H:%M')}",
                    "timezone": destination_tz_name,
                },
            )

        # Filtrage des autres visites (hors élément en cours de modification)
        others = [
            v
            for v in existing_visits
            if v.item_id != exclude_item_id
        ]
        others.sort(key=lambda x: ensure_utc(x.start_at_utc))

        # Règle 2b : Anti-doublon d'un même lieu dans le séjour (sauf demande explicite "ajoute-le une deuxième fois")
        duplicate_visit = next((v for v in others if v.place_id == place_id), None)
        if duplicate_visit is not None and not allow_duplicate_place:
            dup_local_s = to_destination_local(ensure_utc(duplicate_visit.start_at_utc), destination_tz_name)
            dup_local_e = to_destination_local(ensure_utc(duplicate_visit.end_at_utc), destination_tz_name)
            return ValidationResult(
                valid=False,
                reason_code="DUPLICATE_PLACE",
                message=(
                    f"« {place_name} » est déjà prévu dans votre programme "
                    f"({dup_local_s.strftime('%H:%M')}-{dup_local_e.strftime('%H:%M')}). "
                    "Un même lieu ne peut pas être planifié deux fois dans le séjour, "
                    "sauf demande explicite (« ajoute-le une deuxième fois »)."
                ),
                conflict_details={
                    "existing_item_id": duplicate_visit.item_id,
                    "existing_place_id": duplicate_visit.place_id,
                    "existing_place_name": duplicate_visit.place_name,
                    "existing_start_local": dup_local_s.isoformat(),
                    "existing_end_local": dup_local_e.isoformat(),
                },
            )

        # Règle 3 : Aucun chevauchement avec une autre visite
        for other in others:
            o_start = ensure_utc(other.start_at_utc)
            o_end = ensure_utc(other.end_at_utc)
            if start_utc < o_end and end_utc > o_start:
                o_local_s = to_destination_local(o_start, destination_tz_name)
                o_local_e = to_destination_local(o_end, destination_tz_name)
                return ValidationResult(
                    valid=False,
                    reason_code="OVERLAPPING_VISIT",
                    message=(
                        f"Visite refusée : chevauchement horaire avec la visite de « {other.place_name} » "
                        f"prévue de {o_local_s.strftime('%H:%M')} à {o_local_e.strftime('%H:%M')} "
                        f"le {o_local_s.strftime('%d/%m/%Y')}."
                    ),
                    conflict_details={
                        "conflicting_item_id": other.item_id,
                        "conflicting_place_name": other.place_name,
                        "conflicting_start_local": o_local_s.isoformat(),
                        "conflicting_end_local": o_local_e.isoformat(),
                    },
                )

        # Règle 4 : Temps de trajet réaliste avec la visite précédente et la visite suivante du même jour local
        same_day_others = [
            v
            for v in others
            if to_destination_local(v.start_at_utc, destination_tz_name).date() == local_start.date()
        ]
        prev_visits = [v for v in same_day_others if ensure_utc(v.end_at_utc) <= start_utc]
        next_visits = [v for v in same_day_others if ensure_utc(v.start_at_utc) >= end_utc]

        transit_from_prev_min = 0
        transit_from_prev_m = 0
        if prev_visits:
            prev_v = prev_visits[-1]
            dist_km = haversine_distance_km(prev_v.latitude, prev_v.longitude, place_lat, place_lng)
            transit_from_prev_m = haversine_distance_m(prev_v.latitude, prev_v.longitude, place_lat, place_lng)
            required_min = estimate_transit_duration_min(dist_km, norm_mode)
            transit_from_prev_min = required_min
            available_min = int((start_utc - ensure_utc(prev_v.end_at_utc)).total_seconds() // 60)
            if available_min < required_min:
                prev_end_local = to_destination_local(prev_v.end_at_utc, destination_tz_name)
                recommended_start_local = prev_end_local + timedelta(minutes=required_min)
                return ValidationResult(
                    valid=False,
                    reason_code="INSUFFICIENT_TRAVEL_TIME",
                    message=(
                        f"Visite refusée : temps de trajet insuffisant depuis « {prev_v.place_name} » "
                        f"({dist_km:.2f} km en mode {norm_mode}). Il faut au moins {required_min} min de trajet "
                        f"(arrivée au plus tôt à {recommended_start_local.strftime('%H:%M')}), "
                        f"mais seulement {available_min} min sont prévues."
                    ),
                    conflict_details={
                        "direction": "from_previous",
                        "from_place": prev_v.place_name,
                        "to_place": place_name,
                        "distance_km": dist_km,
                        "transit_mode": norm_mode,
                        "required_travel_minutes": required_min,
                        "available_gap_minutes": available_min,
                    },
                )

        transit_to_next_min = 0
        transit_to_next_m = 0
        if next_visits:
            next_v = next_visits[0]
            dist_km = haversine_distance_km(place_lat, place_lng, next_v.latitude, next_v.longitude)
            transit_to_next_m = haversine_distance_m(place_lat, place_lng, next_v.latitude, next_v.longitude)
            required_min = estimate_transit_duration_min(dist_km, norm_mode)
            transit_to_next_min = required_min
            available_min = int((ensure_utc(next_v.start_at_utc) - end_utc).total_seconds() // 60)
            if available_min < required_min:
                return ValidationResult(
                    valid=False,
                    reason_code="INSUFFICIENT_TRAVEL_TIME",
                    message=(
                        f"Visite refusée : temps de trajet insuffisant vers la visite suivante « {next_v.place_name} » "
                        f"({dist_km:.2f} km en mode {norm_mode}). Il faut au moins {required_min} min de trajet, "
                        f"mais seulement {available_min} min restent avant {to_destination_local(next_v.start_at_utc, destination_tz_name).strftime('%H:%M')}."
                    ),
                    conflict_details={
                        "direction": "to_next",
                        "from_place": place_name,
                        "to_place": next_v.place_name,
                        "distance_km": dist_km,
                        "transit_mode": norm_mode,
                        "required_travel_minutes": required_min,
                        "available_gap_minutes": available_min,
                    },
                )

        return ValidationResult(
            valid=True,
            reason_code=None,
            message="Créneau validé avec succès.",
            transit_from_previous_min=transit_from_prev_min,
            transit_from_previous_m=transit_from_prev_m,
            transit_to_next_min=transit_to_next_min,
            transit_to_next_m=transit_to_next_m,
        )

    @classmethod
    def suggest_free_slots(
        cls,
        *,
        trip_arrival_utc: datetime | None,
        trip_departure_utc: datetime | None,
        destination_tz_name: str,
        place_id: str,
        place_name: str,
        place_lat: float,
        place_lng: float,
        place_opening_hours: dict[str, Any] | None,
        duration_minutes: int,
        preferred_start_utc: datetime,
        transit_mode: str,
        existing_visits: list[ScheduledVisitSnapshot],
        exclude_item_id: str | None = None,
        max_suggestions: int = 3,
        arrival_buffer_hours: float | None = None,
        departure_buffer_hours: float | None = None,
    ) -> list[SuggestedSlot]:
        """
        Recherche et retourne 2 à 3 créneaux libres et 100 % valides dans la fenêtre utile du séjour
        (arrivée aller + tampon d'arrivée -> départ retour - tampon de départ),
        en priorisant la date souhaitée par l'utilisateur puis les autres jours du séjour.
        """
        if trip_arrival_utc is None or trip_departure_utc is None:
            return []

        arr_buf_h, dep_buf_h = cls.resolve_trip_window_buffers(
            arrival_buffer_hours=arrival_buffer_hours,
            departure_buffer_hours=departure_buffer_hours,
        )
        arr_utc = ensure_utc(trip_arrival_utc)
        dep_utc = ensure_utc(trip_departure_utc)
        effective_arr_utc = arr_utc + timedelta(hours=arr_buf_h)
        effective_dep_utc = dep_utc - timedelta(hours=dep_buf_h)
        if effective_dep_utc <= effective_arr_utc:
            return []

        local_arr = to_destination_local(effective_arr_utc, destination_tz_name)
        local_dep = to_destination_local(effective_dep_utc, destination_tz_name)
        local_pref = to_destination_local(ensure_utc(preferred_start_utc), destination_tz_name)

        # Liste ordonnée des dates locales du séjour en mettant la date préférée en tête
        all_days: list[date] = []
        cursor_day = local_arr.date()
        while cursor_day <= local_dep.date():
            all_days.append(cursor_day)
            cursor_day += timedelta(days=1)

        ordered_days = sorted(
            all_days,
            key=lambda d: (0 if d == local_pref.date() else 1, abs((d - local_pref.date()).days), d),
        )

        suggestions: list[SuggestedSlot] = []
        min_gap_between_suggestions = timedelta(minutes=60)

        for candidate_day in ordered_days:
            # Teste les créneaux toutes les 30 minutes de 06:00 à 22:30 heure locale
            for half_hour_idx in range(12, 46):
                h = half_hour_idx // 2
                m = (half_hour_idx % 2) * 30
                cand_start_utc, cand_end_utc = parse_local_slot_to_utc(
                    visit_date=candidate_day,
                    local_start_time_str=f"{h:02d}:{m:02d}",
                    duration_minutes=duration_minutes,
                    timezone_name=destination_tz_name,
                )
                if cand_start_utc < effective_arr_utc or cand_end_utc > effective_dep_utc:
                    continue
                if suggestions and any(
                    abs((cand_start_utc - s.start_at_utc).total_seconds())
                    < min_gap_between_suggestions.total_seconds()
                    for s in suggestions
                ):
                    continue

                check = cls._check_single_slot(
                    trip_arrival_utc=arr_utc,
                    trip_departure_utc=dep_utc,
                    destination_tz_name=destination_tz_name,
                    place_id=place_id,
                    place_name=place_name,
                    place_lat=place_lat,
                    place_lng=place_lng,
                    place_opening_hours=place_opening_hours,
                    start_at_utc=cand_start_utc,
                    end_at_utc=cand_end_utc,
                    transit_mode=transit_mode,
                    existing_visits=existing_visits,
                    exclude_item_id=exclude_item_id,
                    arrival_buffer_hours=arr_buf_h,
                    departure_buffer_hours=dep_buf_h,
                    allow_duplicate_place=True,
                )
                if check.valid:
                    loc_s = to_destination_local(cand_start_utc, destination_tz_name)
                    loc_e = to_destination_local(cand_end_utc, destination_tz_name)
                    suggestions.append(
                        SuggestedSlot(
                            start_at_utc=cand_start_utc,
                            end_at_utc=cand_end_utc,
                            local_date=loc_s.strftime("%Y-%m-%d"),
                            local_start_time=loc_s.strftime("%H:%M"),
                            local_end_time=loc_e.strftime("%H:%M"),
                            timezone=destination_tz_name,
                            label=(
                                f"{loc_s.strftime('%d/%m/%Y')} de {loc_s.strftime('%H:%M')} "
                                f"à {loc_e.strftime('%H:%M')}"
                            ),
                        )
                    )
                    if len(suggestions) >= max_suggestions:
                        return suggestions

        return suggestions

    @classmethod
    def validate_visit(
        cls,
        *,
        trip_arrival_utc: datetime | None,
        trip_departure_utc: datetime | None,
        destination_tz_name: str,
        place_id: str,
        place_name: str,
        place_lat: float,
        place_lng: float,
        place_opening_hours: dict[str, Any] | None,
        start_at_utc: datetime,
        duration_minutes: int,
        transit_mode: str = "METRO",
        existing_visits: list[ScheduledVisitSnapshot],
        exclude_item_id: str | None = None,
        arrival_buffer_hours: float | None = None,
        departure_buffer_hours: float | None = None,
        allow_duplicate_place: bool = False,
    ) -> ValidationResult:
        """
        Valide une visite et, en cas de refus (hors doublon de lieu), enrichit automatiquement
        le résultat avec 2 à 3 créneaux libres suggérés.
        """
        start_utc = ensure_utc(start_at_utc)
        end_utc = start_utc + timedelta(minutes=duration_minutes)

        result = cls._check_single_slot(
            trip_arrival_utc=trip_arrival_utc,
            trip_departure_utc=trip_departure_utc,
            destination_tz_name=destination_tz_name,
            place_id=place_id,
            place_name=place_name,
            place_lat=place_lat,
            place_lng=place_lng,
            place_opening_hours=place_opening_hours,
            start_at_utc=start_utc,
            end_at_utc=end_utc,
            transit_mode=transit_mode,
            existing_visits=existing_visits,
            exclude_item_id=exclude_item_id,
            arrival_buffer_hours=arrival_buffer_hours,
            departure_buffer_hours=departure_buffer_hours,
            allow_duplicate_place=allow_duplicate_place,
        )
        if not result.valid and result.reason_code != "DUPLICATE_PLACE":
            result.suggested_slots = cls.suggest_free_slots(
                trip_arrival_utc=trip_arrival_utc,
                trip_departure_utc=trip_departure_utc,
                destination_tz_name=destination_tz_name,
                place_id=place_id,
                place_name=place_name,
                place_lat=place_lat,
                place_lng=place_lng,
                place_opening_hours=place_opening_hours,
                duration_minutes=duration_minutes,
                preferred_start_utc=start_utc,
                transit_mode=transit_mode,
                existing_visits=existing_visits,
                exclude_item_id=exclude_item_id,
                max_suggestions=3,
                arrival_buffer_hours=arrival_buffer_hours,
                departure_buffer_hours=departure_buffer_hours,
            )
        return result

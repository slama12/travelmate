from dataclasses import dataclass
from datetime import date, datetime, timedelta
import math
from typing import Any

from app.core.geo import (
    estimate_transit_duration_min,
    haversine_distance_km,
    haversine_distance_m,
    normalize_transit_mode,
    recommend_transit_mode,
)
from app.core.itinerary_validator import (
    ItineraryValidationEngine,
    ScheduledVisitSnapshot,
    ensure_utc,
    get_opening_window_minutes,
    parse_local_slot_to_utc,
    to_destination_local,
)


@dataclass
class OptimizablePlaceItem:
    place_id: str
    place_name: str
    category: str
    latitude: float
    longitude: float
    duration_minutes: int
    opening_hours: dict[str, Any] | None
    preferred_transit_mode: str | None = None
    original_item_id: str | None = None


@dataclass
class ProposedVisitSlot:
    place_id: str
    place_name: str
    category: str
    latitude: float
    longitude: float
    visit_date: date
    local_start_time: str
    local_end_time: str
    start_at_utc: datetime
    end_at_utc: datetime
    duration_minutes: int
    day_cluster_index: int
    day_order_index: int
    transit_mode_from_prev: str
    transit_duration_from_prev_min: int
    transit_distance_from_prev_m: int
    transit_mode_to_next: str
    transit_duration_to_next_min: int
    transit_distance_to_next_m: int
    validated_by_engine: bool


class RouteOptimizer:
    """
    Service d'optimisation d'itinéraire :
    1. Regroupe les lieux proches le même jour (clustering géographique K-means équilibré).
    2. Ordonne les visites de chaque journée selon l'heuristique du Plus Proche Voisin (Nearest-Neighbor).
    3. Calcule les temps et modes de transport (WALKING, METRO, CAR) entre chaque étape.
    4. Fait repasser chaque créneau proposé par le moteur de validation centralisé (ItineraryValidationEngine).
    """

    @staticmethod
    def _usable_days(
        trip_arrival_utc: datetime,
        trip_departure_utc: datetime,
        destination_tz_name: str,
    ) -> list[tuple[date, int, int]]:
        """
        Retourne les jours du séjour disposant d'au moins 2h exploitables entre 09:00 et 21:00 locales,
        en respectant les tampons d'arrivée (+2h) et de départ (-3h).
        Chaque tuple : (local_date, earliest_start_min, latest_end_min).
        """
        arr_buf_h, dep_buf_h = ItineraryValidationEngine.resolve_trip_window_buffers()
        eff_arr_utc = ensure_utc(trip_arrival_utc) + timedelta(hours=arr_buf_h)
        eff_dep_utc = ensure_utc(trip_departure_utc) - timedelta(hours=dep_buf_h)
        if eff_dep_utc <= eff_arr_utc:
            return []

        arr_local = to_destination_local(eff_arr_utc, destination_tz_name)
        dep_local = to_destination_local(eff_dep_utc, destination_tz_name)

        days: list[tuple[date, int, int]] = []
        cursor = arr_local.date()
        while cursor <= dep_local.date():
            start_min = 9 * 60
            end_min = 21 * 60
            if cursor == arr_local.date():
                arr_min = arr_local.hour * 60 + arr_local.minute
                # Premier créneau possible dès la fin du tampon d'arrivée arrondie à la demi-heure supérieure
                rounded_arr = int(math.ceil(arr_min / 30.0) * 30)
                start_min = max(start_min, rounded_arr)
            if cursor == dep_local.date():
                dep_min = dep_local.hour * 60 + dep_local.minute
                end_min = min(end_min, dep_min)
            if end_min - start_min >= 90:
                days.append((cursor, start_min, end_min))
            cursor += timedelta(days=1)
        return days

    @staticmethod
    def _cluster_places_geographically(
        places: list[OptimizablePlaceItem],
        num_clusters: int,
    ) -> list[list[OptimizablePlaceItem]]:
        """
        Regroupe les lieux proches dans `num_clusters` groupes journaliers par K-means géographique
        avec équilibrage de la charge journalière.
        """
        if not places:
            return []
        k = max(1, min(num_clusters, len(places)))
        if k == 1:
            return [list(places)]

        # Tri spatial initial (projection sur l'axe principal latitude + longitude) pour initialiser les centroïdes de manière déterministe
        sorted_by_space = sorted(places, key=lambda p: (round(p.latitude, 5), round(p.longitude, 5), p.place_id))
        centroids: list[tuple[float, float]] = []
        for i in range(k):
            idx = min(len(sorted_by_space) - 1, int(round(i * (len(sorted_by_space) - 1) / max(1, k - 1))))
            centroids.append((sorted_by_space[idx].latitude, sorted_by_space[idx].longitude))

        max_per_cluster = max(2, int(math.ceil(len(places) / k)) + 1)
        clusters: list[list[OptimizablePlaceItem]] = [[] for _ in range(k)]

        for _iteration in range(8):
            clusters = [[] for _ in range(k)]
            for item in sorted_by_space:
                # Trie les centroïdes par distance Haversine croissante
                ranked_clusters = sorted(
                    range(k),
                    key=lambda cid: haversine_distance_km(
                        item.latitude, item.longitude, centroids[cid][0], centroids[cid][1]
                    ),
                )
                chosen = ranked_clusters[0]
                for cid in ranked_clusters:
                    if len(clusters[cid]) < max_per_cluster:
                        chosen = cid
                        break
                clusters[chosen].append(item)

            # Recalcul des centroïdes
            new_centroids: list[tuple[float, float]] = []
            for cid in range(k):
                if clusters[cid]:
                    avg_lat = sum(p.latitude for p in clusters[cid]) / len(clusters[cid])
                    avg_lng = sum(p.longitude for p in clusters[cid]) / len(clusters[cid])
                    new_centroids.append((avg_lat, avg_lng))
                else:
                    new_centroids.append(centroids[cid])
            centroids = new_centroids

        return [c for c in clusters if c]

    @staticmethod
    def _order_nearest_neighbor(cluster: list[OptimizablePlaceItem]) -> list[OptimizablePlaceItem]:
        """
        Ordonne les lieux d'une même journée par l'algorithme du Plus Proche Voisin (Nearest-Neighbor TSP).
        """
        if len(cluster) <= 1:
            return list(cluster)

        remaining = list(cluster)
        # Point de départ : le lieu le plus à l'ouest / nord (déterministe)
        remaining.sort(key=lambda p: (round(p.longitude, 5), -round(p.latitude, 5), p.place_id))
        ordered: list[OptimizablePlaceItem] = [remaining.pop(0)]

        while remaining:
            last = ordered[-1]
            nearest_idx = min(
                range(len(remaining)),
                key=lambda i: (
                    haversine_distance_km(
                        last.latitude, last.longitude, remaining[i].latitude, remaining[i].longitude
                    ),
                    remaining[i].place_id,
                ),
            )
            ordered.append(remaining.pop(nearest_idx))

        return ordered

    @classmethod
    def build_optimized_proposal(
        cls,
        *,
        trip_arrival_utc: datetime,
        trip_departure_utc: datetime,
        destination_tz_name: str,
        places: list[OptimizablePlaceItem],
        default_transit_mode: str | None = None,
    ) -> dict[str, Any]:
        """
        Construit une proposition complète d'itinéraire optimisé (regroupement par zone + plus proche voisin)
        et valide chaque créneau via ItineraryValidationEngine.
        Rien n'est enregistré en base de données par cette méthode.
        """
        arr_utc = ensure_utc(trip_arrival_utc)
        dep_utc = ensure_utc(trip_departure_utc)
        usable_days = cls._usable_days(arr_utc, dep_utc, destination_tz_name)
        if not usable_days:
            raise ValueError(
                "La fenêtre du séjour ne comporte aucun créneau exploitable en journée pour optimiser les visites."
            )

        # Nombre optimal de journées pour regrouper les lieux proches (max ~3 à 4 lieux par jour)
        ideal_days = max(1, min(len(usable_days), int(math.ceil(len(places) / 3.0))))
        raw_clusters = cls._cluster_places_geographically(places, ideal_days)

        scheduled_snapshots: list[ScheduledVisitSnapshot] = []
        proposed_slots: list[ProposedVisitSlot] = []
        unscheduled_places: list[str] = []

        for cluster_idx, cluster in enumerate(raw_clusters):
            ordered_cluster = cls._order_nearest_neighbor(cluster)
            target_day, earliest_min, latest_min = usable_days[min(cluster_idx, len(usable_days) - 1)]
            cursor_min = max(earliest_min, 9 * 60 + 30)

            for order_in_day, item in enumerate(ordered_cluster):
                placed = False
                # Détermine le mode de transport depuis la visite précédente du même jour
                same_day_prev = [
                    s for s in proposed_slots if s.visit_date == target_day
                ]
                if same_day_prev:
                    prev_slot = same_day_prev[-1]
                    dist_km = haversine_distance_km(
                        prev_slot.latitude, prev_slot.longitude, item.latitude, item.longitude
                    )
                    mode_from_prev = normalize_transit_mode(
                        default_transit_mode or item.preferred_transit_mode or recommend_transit_mode(dist_km)
                    )
                    travel_min = estimate_transit_duration_min(dist_km, mode_from_prev)
                    travel_m = haversine_distance_m(
                        prev_slot.latitude, prev_slot.longitude, item.latitude, item.longitude
                    )
                    prev_end_local = to_destination_local(prev_slot.end_at_utc, destination_tz_name)
                    min_after_prev = prev_end_local.hour * 60 + prev_end_local.minute + travel_min
                    # Arrondi au quart d'heure supérieur pour un agenda lisible
                    cursor_min = max(cursor_min, int(math.ceil(min_after_prev / 15.0) * 15))
                else:
                    mode_from_prev = normalize_transit_mode(
                        default_transit_mode or item.preferred_transit_mode or "METRO"
                    )
                    travel_min = 0
                    travel_m = 0

                # Cherche le premier créneau valide sur target_day à partir de cursor_min
                cand_min = cursor_min
                while cand_min + item.duration_minutes <= 22 * 60:
                    h = cand_min // 60
                    m = cand_min % 60
                    cand_start_utc, cand_end_utc = parse_local_slot_to_utc(
                        visit_date=target_day,
                        local_start_time_str=f"{h:02d}:{m:02d}",
                        duration_minutes=item.duration_minutes,
                        timezone_name=destination_tz_name,
                    )
                    # Adapte l'opening_hours si besoin pour vérifier par le moteur
                    val = ItineraryValidationEngine.validate_visit(
                        trip_arrival_utc=arr_utc,
                        trip_departure_utc=dep_utc,
                        destination_tz_name=destination_tz_name,
                        place_id=item.place_id,
                        place_name=item.place_name,
                        place_lat=item.latitude,
                        place_lng=item.longitude,
                        place_opening_hours=item.opening_hours,
                        start_at_utc=cand_start_utc,
                        duration_minutes=item.duration_minutes,
                        transit_mode=mode_from_prev,
                        existing_visits=scheduled_snapshots,
                    )
                    if val.valid:
                        loc_s = to_destination_local(cand_start_utc, destination_tz_name)
                        loc_e = to_destination_local(cand_end_utc, destination_tz_name)
                        slot = ProposedVisitSlot(
                            place_id=item.place_id,
                            place_name=item.place_name,
                            category=item.category,
                            latitude=item.latitude,
                            longitude=item.longitude,
                            visit_date=loc_s.date(),
                            local_start_time=loc_s.strftime("%H:%M"),
                            local_end_time=loc_e.strftime("%H:%M"),
                            start_at_utc=cand_start_utc,
                            end_at_utc=cand_end_utc,
                            duration_minutes=item.duration_minutes,
                            day_cluster_index=cluster_idx + 1,
                            day_order_index=order_in_day + 1,
                            transit_mode_from_prev=mode_from_prev,
                            transit_duration_from_prev_min=val.transit_from_previous_min,
                            transit_distance_from_prev_m=val.transit_from_previous_m,
                            transit_mode_to_next=mode_from_prev,
                            transit_duration_to_next_min=0,
                            transit_distance_to_next_m=0,
                            validated_by_engine=True,
                        )
                        proposed_slots.append(slot)
                        scheduled_snapshots.append(
                            ScheduledVisitSnapshot(
                                item_id=f"opt-{len(scheduled_snapshots) + 1}",
                                place_id=item.place_id,
                                place_name=item.place_name,
                                latitude=item.latitude,
                                longitude=item.longitude,
                                start_at_utc=cand_start_utc,
                                end_at_utc=cand_end_utc,
                                transit_mode_to_next=mode_from_prev,
                            )
                        )
                        cursor_min = loc_e.hour * 60 + loc_e.minute
                        placed = True
                        break
                    cand_min += 15

                # Si la journée cible est saturée, utilise les créneaux suggérés par le moteur sur les autres jours
                if not placed:
                    fallback_start, _ = parse_local_slot_to_utc(
                        visit_date=target_day,
                        local_start_time_str="10:00",
                        duration_minutes=item.duration_minutes,
                        timezone_name=destination_tz_name,
                    )
                    suggestions = ItineraryValidationEngine.suggest_free_slots(
                        trip_arrival_utc=arr_utc,
                        trip_departure_utc=dep_utc,
                        destination_tz_name=destination_tz_name,
                        place_id=item.place_id,
                        place_name=item.place_name,
                        place_lat=item.latitude,
                        place_lng=item.longitude,
                        place_opening_hours=item.opening_hours,
                        duration_minutes=item.duration_minutes,
                        preferred_start_utc=fallback_start,
                        transit_mode=mode_from_prev,
                        existing_visits=scheduled_snapshots,
                        max_suggestions=1,
                    )
                    if suggestions:
                        sug = suggestions[0]
                        recheck = ItineraryValidationEngine.validate_visit(
                            trip_arrival_utc=arr_utc,
                            trip_departure_utc=dep_utc,
                            destination_tz_name=destination_tz_name,
                            place_id=item.place_id,
                            place_name=item.place_name,
                            place_lat=item.latitude,
                            place_lng=item.longitude,
                            place_opening_hours=item.opening_hours,
                            start_at_utc=sug.start_at_utc,
                            duration_minutes=item.duration_minutes,
                            transit_mode=mode_from_prev,
                            existing_visits=scheduled_snapshots,
                        )
                        if recheck.valid:
                            loc_s = to_destination_local(sug.start_at_utc, destination_tz_name)
                            loc_e = to_destination_local(sug.end_at_utc, destination_tz_name)
                            slot = ProposedVisitSlot(
                                place_id=item.place_id,
                                place_name=item.place_name,
                                category=item.category,
                                latitude=item.latitude,
                                longitude=item.longitude,
                                visit_date=loc_s.date(),
                                local_start_time=loc_s.strftime("%H:%M"),
                                local_end_time=loc_e.strftime("%H:%M"),
                                start_at_utc=sug.start_at_utc,
                                end_at_utc=sug.end_at_utc,
                                duration_minutes=item.duration_minutes,
                                day_cluster_index=cluster_idx + 1,
                                day_order_index=order_in_day + 1,
                                transit_mode_from_prev=mode_from_prev,
                                transit_duration_from_prev_min=recheck.transit_from_previous_min,
                                transit_distance_from_prev_m=recheck.transit_from_previous_m,
                                transit_mode_to_next=mode_from_prev,
                                transit_duration_to_next_min=0,
                                transit_distance_to_next_m=0,
                                validated_by_engine=True,
                            )
                            proposed_slots.append(slot)
                            scheduled_snapshots.append(
                                ScheduledVisitSnapshot(
                                    item_id=f"opt-{len(scheduled_snapshots) + 1}",
                                    place_id=item.place_id,
                                    place_name=item.place_name,
                                    latitude=item.latitude,
                                    longitude=item.longitude,
                                    start_at_utc=sug.start_at_utc,
                                    end_at_utc=sug.end_at_utc,
                                    transit_mode_to_next=mode_from_prev,
                                )
                            )
                            placed = True

                if not placed:
                    unscheduled_places.append(item.place_name)

        # Trie les créneaux proposés chronologiquement et renseigne les trajets vers l'étape suivante du même jour
        proposed_slots.sort(key=lambda s: s.start_at_utc)
        by_day: dict[date, list[ProposedVisitSlot]] = {}
        for slot in proposed_slots:
            by_day.setdefault(slot.visit_date, []).append(slot)

        total_transit_min = 0
        total_distance_m = 0
        for day_date, day_slots in by_day.items():
            for idx, slot in enumerate(day_slots):
                slot.day_order_index = idx + 1
                if idx + 1 < len(day_slots):
                    nxt = day_slots[idx + 1]
                    dist_km = haversine_distance_km(
                        slot.latitude, slot.longitude, nxt.latitude, nxt.longitude
                    )
                    dist_m = haversine_distance_m(
                        slot.latitude, slot.longitude, nxt.latitude, nxt.longitude
                    )
                    mode_next = normalize_transit_mode(
                        default_transit_mode or recommend_transit_mode(dist_km)
                    )
                    dur_min = estimate_transit_duration_min(dist_km, mode_next)
                    slot.transit_mode_to_next = mode_next
                    slot.transit_duration_to_next_min = dur_min
                    slot.transit_distance_to_next_m = dist_m
                    nxt.transit_mode_from_prev = mode_next
                    nxt.transit_duration_from_prev_min = dur_min
                    nxt.transit_distance_from_prev_m = dist_m
                    total_transit_min += dur_min
                    total_distance_m += dist_m
                else:
                    slot.transit_duration_to_next_min = 0
                    slot.transit_distance_to_next_m = 0

        return {
            "persisted": False,
            "requires_user_confirmation": True,
            "all_validated_by_engine": True,
            "destination_timezone": destination_tz_name,
            "clusters_count": len(by_day),
            "total_places_scheduled": len(proposed_slots),
            "unscheduled_places": unscheduled_places,
            "total_transit_minutes": total_transit_min,
            "total_distance_meters": total_distance_m,
            "proposed_items": [
                {
                    "place_id": s.place_id,
                    "place_name": s.place_name,
                    "category": s.category,
                    "visit_date": s.visit_date.isoformat(),
                    "local_start_time": s.local_start_time,
                    "local_end_time": s.local_end_time,
                    "start_at": s.start_at_utc.isoformat(),
                    "end_at": s.end_at_utc.isoformat(),
                    "duration_minutes": s.duration_minutes,
                    "day_cluster_index": s.day_cluster_index,
                    "day_order_index": s.day_order_index,
                    "transit_mode_from_prev": s.transit_mode_from_prev,
                    "transit_duration_from_prev_min": s.transit_duration_from_prev_min,
                    "transit_distance_from_prev_m": s.transit_distance_from_prev_m,
                    "transit_mode_to_next": s.transit_mode_to_next,
                    "transit_duration_to_next_min": s.transit_duration_to_next_min,
                    "transit_distance_meters": s.transit_distance_to_next_m,
                    "validated_by_engine": s.validated_by_engine,
                }
                for s in proposed_slots
            ],
        }

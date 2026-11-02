from enum import Enum


class TravelStyle(str, Enum):
    ECONOMIC = "ECONOMIC"
    STANDARD = "STANDARD"
    LUXURY = "LUXURY"


class TripStatus(str, Enum):
    DRAFT = "DRAFT"
    BOOKED = "BOOKED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class MemberRole(str, Enum):
    OWNER = "OWNER"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"


class InviteStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"


class CabinClass(str, Enum):
    ECONOMY = "ECONOMY"
    BUSINESS = "BUSINESS"
    FIRST = "FIRST"


class FlightStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELAYED = "DELAYED"
    CANCELLED = "CANCELLED"


class AccommodationType(str, Enum):
    HOTEL = "HOTEL"
    AIRBNB = "AIRBNB"


class PlaceCategory(str, Enum):
    CULTURE = "CULTURE"
    NATURE = "NATURE"
    FOOD = "FOOD"
    NIGHTLIFE = "NIGHTLIFE"
    SHOPPING = "SHOPPING"
    RESTAURANT = "RESTAURANT"
    AUTRE = "AUTRE"


class TransitMode(str, Enum):
    WALKING = "WALKING"
    WALK = "WALK"
    METRO = "METRO"
    CAR = "CAR"


class BudgetCategory(str, Enum):
    FLIGHT = "FLIGHT"
    ACCOMMODATION = "ACCOMMODATION"
    ACTIVITY = "ACTIVITY"
    RESTAURANT = "RESTAURANT"
    MEAL = "MEAL"
    TRANSPORT = "TRANSPORT"
    OTHER = "OTHER"


class DocumentType(str, Enum):
    FLIGHT_TICKET = "FLIGHT_TICKET"
    HOTEL_VOUCHER = "HOTEL_VOUCHER"
    PASSPORT = "PASSPORT"
    VISA = "VISA"
    INSURANCE = "INSURANCE"
    OTHER = "OTHER"


class AlertType(str, Enum):
    FLIGHT_CHANGE = "FLIGHT_CHANGE"
    VISIT_REMINDER = "VISIT_REMINDER"
    PRICE_DROP = "PRICE_DROP"
    WEATHER_RAIN = "WEATHER_RAIN"


class StageArrivalTransportMode(str, Enum):
    VOL = "VOL"
    TRAIN = "TRAIN"
    BUS = "BUS"
    BATEAU = "BATEAU"
    VOITURE = "VOITURE"


STAGE_TRANSPORT_MODE_MAP: dict[str, str] = {
    "VOL": StageArrivalTransportMode.VOL.value,
    "VOLS": StageArrivalTransportMode.VOL.value,
    "AVION": StageArrivalTransportMode.VOL.value,
    "FLIGHT": StageArrivalTransportMode.VOL.value,
    "PLANE": StageArrivalTransportMode.VOL.value,
    "TRAIN": StageArrivalTransportMode.TRAIN.value,
    "TGV": StageArrivalTransportMode.TRAIN.value,
    "RAIL": StageArrivalTransportMode.TRAIN.value,
    "BUS": StageArrivalTransportMode.BUS.value,
    "CAR_BUS": StageArrivalTransportMode.BUS.value,
    "AUTOCAR": StageArrivalTransportMode.BUS.value,
    "COACH": StageArrivalTransportMode.BUS.value,
    "BATEAU": StageArrivalTransportMode.BATEAU.value,
    "FERRY": StageArrivalTransportMode.BATEAU.value,
    "BOAT": StageArrivalTransportMode.BATEAU.value,
    "SHIP": StageArrivalTransportMode.BATEAU.value,
    "VOITURE": StageArrivalTransportMode.VOITURE.value,
    "AUTO": StageArrivalTransportMode.VOITURE.value,
    "CAR": StageArrivalTransportMode.VOITURE.value,
}


def normalize_stage_transport_mode(raw: str | None) -> str:
    cleaned = (raw or "VOL").strip().upper()
    if cleaned not in STAGE_TRANSPORT_MODE_MAP:
        raise ValueError(
            f"Type de trajet d'arrivée invalide ({raw!r}). "
            "Valeurs autorisées : vol, train, bus, bateau, voiture."
        )
    return STAGE_TRANSPORT_MODE_MAP[cleaned]


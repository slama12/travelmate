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

import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { format, parseISO } from "date-fns";
import { fr } from "date-fns/locale";
import {
  ArrowRight,
  Building2,
  Bus,
  Calendar as CalendarIcon,
  Car,
  CheckCircle2,
  Cloud,
  CloudLightning,
  CloudRain,
  CloudSun,
  Clock,
  Compass,
  FileText,
  Footprints,
  GripVertical,
  MapPin,
  Maximize2,
  MessageCircle,
  Navigation,
  Plane,
  Plus,
  Send,
  SlidersHorizontal,
  Sparkles,
  Star,
  Sun,
  Train,
  Trash2,
  Utensils,
  Wand2,
  X,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  Input,
  Modal,
  Select,
  Skeleton,
  useToast,
} from "./components/ui";
import type { FlightBooking, UserProfile } from "./App";

declare global {
  interface Window {
    L?: any;
  }
}

export interface Destination {
  id: string;
  city_name: string;
  country_name: string;
  country_code_iso2: string;
  iata_code: string;
  timezone: string;
  latitude: number;
  longitude: number;
  hero_image_url: string;
  description: string;
  practical_info: Record<string, string>;
}

export interface Trip {
  id: string;
  destination_id: string;
  title: string;
  arrival_at: string | null;
  departure_at: string | null;
  travel_style: string;
  total_budget_planned: number;
  currency: string;
  selected_place_ids: string[];
  status: string;
}

export interface NearbyRestaurant {
  id: string;
  name: string;
  description: string;
  latitude: number;
  longitude: number;
  estimated_cost: string;
  price_tier: string;
  avg_rating: number;
  hero_photos: string[];
  distance_km: number;
  distance_m: number;
  walking_minutes: number;
}

export interface AccommodationItem {
  id: string;
  destination_id: string;
  type: "HOTEL" | "AIRBNB";
  source: "HOTEL" | "AIRBNB" | "SIMULATED";
  source_provider: string;
  source_label: string;
  provider_mode: string;
  is_simulated: boolean;
  name: string;
  neighborhood: string;
  address: string;
  latitude: number;
  longitude: number;
  distance_from_center_km: number;
  price_per_night: string;
  currency: string;
  luxury_tier: string;
  rating: number;
  photos: string[];
  amenities: string[];
  booking_redirect_url: string;
  nearby_restaurants: NearbyRestaurant[];
}

export interface PlaceItem {
  id: string;
  destination_id: string;
  city_name: string;
  name: string;
  description: string;
  category: string;
  is_outdoor: boolean;
  latitude: number;
  longitude: number;
  recommended_duration_min: number;
  estimated_cost: string;
  price_tier: string;
  avg_rating: number;
  opening_hours: Record<string, string>;
  hero_photos: string[];
  source_provider: string;
  is_wishlisted: boolean;
  is_selected_for_trip: boolean;
}

export interface TripGalleryPayload {
  trip_id: string;
  city_name: string;
  unlocked: boolean;
  unlock_message: string;
  provider_mode: string;
  cached_in_redis: boolean;
  selected_place_ids: string[];
  places: PlaceItem[];
}

export interface SuggestedSlot {
  start_at_utc: string;
  end_at_utc: string;
  local_date: string;
  local_start_time: string;
  local_end_time: string;
  timezone: string;
  label: string;
}

export interface ValidationFailureDetail {
  valid: boolean;
  reason_code: string;
  message: string;
  conflict_details: Record<string, any>;
  suggested_slots: SuggestedSlot[];
}

export interface ItineraryItemView {
  id: string;
  trip_id: string;
  place_id: string;
  place_name: string;
  place_category: string;
  is_outdoor?: boolean;
  place_is_outdoor?: boolean;
  day_number?: number;
  visit_date: string;
  start_at: string;
  end_at: string;
  local_visit_date: string;
  local_start_time: string;
  local_end_time: string;
  destination_timezone: string;
  duration_minutes: number;
  recommended_duration_min: number;
  transit_mode_to_next: "WALKING" | "METRO" | "CAR";
  transit_duration_to_next_min: number;
  transit_distance_meters: number;
  transit_time_source?: "REAL" | "ESTIMATED" | string;
  transit_is_estimated?: boolean;
  transit_source_label?: string;
  google_calendar_event_id: string | null;
  calendar_sync_status: string;
  calendar_sync_attempts: number;
  calendar_sync_error: string | null;
  is_ai_generated?: boolean;
  weather_warning?: boolean | string | null;
  weather_dismissed?: boolean;
  notes: string | null;
}

export interface ItineraryDayGroup {
  day_number: number;
  visit_date: string;
  items: ItineraryItemView[];
}

export interface TripItinerarySchedule {
  trip_id: string;
  city_name: string;
  destination_timezone: string;
  arrival_at_utc: string | null;
  departure_at_utc: string | null;
  local_arrival_at: string | null;
  local_departure_at: string | null;
  total_visits: number;
  routing_mode: string;
  routing_source_label: string;
  pending_calendar_sync_count: number;
  days: ItineraryDayGroup[];
  items: ItineraryItemView[];
}

export interface DailyWeatherForecast {
  date: string;
  available: boolean;
  condition_code: string;
  summary: string;
  precipitation_probability: number | null;
  is_rainy: boolean;
  temperature_celsius: number | null;
  badge_label: string;
}

export interface WeatherAdaptationOption {
  option_id: string;
  suggestion_type: "INDOOR_PLACE" | "ALTERNATE_SLOT";
  label_fr: string;
  replacement_place_id: string;
  replacement_place_name: string;
  replacement_place_category: string;
  is_outdoor: boolean;
  visit_date: string;
  local_start_time: string;
  local_end_time: string;
  duration_minutes: number;
  validated_by_engine: boolean;
}

export interface WeatherVisitAlert {
  item_id: string;
  place_id: string;
  place_name: string;
  visit_date: string;
  local_start_time: string;
  local_end_time: string;
  weather_condition_code: string;
  weather_summary: string;
  precipitation_probability: number | null;
  alert_message_fr: string;
  options: WeatherAdaptationOption[];
}

export interface TripWeatherPayload {
  trip_id: string;
  destination_city: string;
  destination_timezone: string;
  provider_mode: string;
  forecast_horizon_days: number;
  cache_hit: boolean;
  cache_backend: string;
  persisted_changes: boolean;
  days: DailyWeatherForecast[];
  alerts: WeatherVisitAlert[];
}

export interface AIDraftSlot {
  place_id: string;
  place_name: string;
  place_category: string;
  is_outdoor: boolean;
  visit_date: string;
  visit_date_label_fr?: string;
  local_start_time: string;
  local_end_time: string;
  duration_minutes: number;
  estimated_cost_eur: number;
  transit_mode: string;
  transit_from_prev_min: number;
  transit_distance_from_prev_m: number;
  transit_time_source: string;
  transit_source_label: string;
  transit_label_fr?: string | null;
  weather_summary: string;
  weather_adapted: boolean;
  validation_status: "VALID" | "CORRECTED";
  adjustment_note_fr: string | null;
  validated_by_engine: boolean;
}

export interface AIGenerateDraftPayload {
  trip_id: string;
  destination_city: string;
  destination_timezone: string;
  persisted: boolean;
  calendar_synced: boolean;
  requires_user_confirmation: boolean;
  attempts_used: number;
  summary_fr: string;
  pace: string;
  budget_eur: number;
  tastes: string[];
  total_estimated_cost_eur: number;
  total_transit_minutes: number;
  routing_source_label: string;
  limited_places_notice_fr?: string | null;
  adjustments_fr: string[];
  draft_items: AIDraftSlot[];
}

export interface ChatProposedAction {
  action_type: "ADD_VISIT" | "MOVE_VISIT" | "REMOVE_VISIT";
  item_id: string | null;
  place_id: string;
  place_name: string;
  visit_date: string;
  local_start_time: string;
  local_end_time: string | null;
  duration_minutes: number;
  transit_mode: string;
  validated_by_engine: boolean;
  validation_error_code: string | null;
  validation_message_fr: string | null;
  suggested_slots: SuggestedSlot[];
}

export interface ChatMessageItem {
  id: string;
  trip_id: string;
  role: "user" | "assistant";
  content: string;
  proposed_action: ChatProposedAction | null;
  action_status: "NONE" | "PENDING_CONFIRMATION" | "CONFIRMED" | "REJECTED";
  created_at: string;
}

export interface OptimizationProposedSlot {
  place_id: string;
  place_name: string;
  place_category: string;
  is_outdoor: boolean;
  latitude: number;
  longitude: number;
  cluster_day_index: number;
  day_number: number;
  visit_date: string;
  local_start_time: string;
  local_end_time: string;
  start_at_utc: string;
  end_at_utc: string;
  duration_minutes: number;
  transit_mode_from_prev: string;
  transit_duration_from_prev_min: number;
  transit_distance_from_prev_m: number;
  transit_mode_to_next: "WALKING" | "METRO" | "CAR";
  transit_duration_to_next_min: number;
  transit_distance_meters: number;
  validated_by_engine: boolean;
}

export interface OptimizationPreviewPayload {
  trip_id: string;
  city_name: string;
  destination_timezone: string;
  persisted: boolean;
  requires_user_confirmation: boolean;
  algorithm: string;
  total_places_requested: number;
  total_places_scheduled: number;
  all_validated_by_engine: boolean;
  proposed_items: OptimizationProposedSlot[];
  unscheduled_places: Array<{ place_id: string; place_name: string; reason: string }>;
  summary_message: string;
}

export interface LocalTransportOptionItem {
  id?: string;
  transport_type?: string;
  provider_name?: string;
  provider?: string;
  name?: string;
  description?: string;
  coverage?: string;
  estimated_price_eur?: number | string;
  price_eur?: number | string;
  estimated_base_fare_eur?: number | string;
  booking_url?: string;
}

export interface LocalTransportsPayload {
  city_name: string;
  country_name?: string;
  iata_code: string;
  taxi_vtc_links: LocalTransportOptionItem[];
  car_rental_links: LocalTransportOptionItem[];
  transit_passes: LocalTransportOptionItem[];
  airport_transfer: {
    airport_iata?: string;
    airport_name: string;
    accommodation_name: string;
    distance_km: number;
    recommended_mode?: string;
    options: Array<{
      mode: string;
      label: string;
      provider_name?: string;
      estimated_duration_min?: number;
      duration_minutes?: number;
      estimated_price_eur: number | string;
      notes: string;
    }>;
  } | null;
}

export interface TravelerPreferences {
  currency: "EUR" | "USD" | "MAD" | "JPY";
  language: "fr" | "en";
  travelStyle: "ECO" | "STANDARD" | "LUXURY";
}

const FALLBACK_HOTEL_IMAGE =
  "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=900&q=80";
const FALLBACK_PLACE_IMAGE =
  "https://images.unsplash.com/photo-1539020140153-e479b8c22e70?auto=format&fit=crop&w=900&q=80";

export function formatDayPillHuman(dateStr: string, index: number): string {
  try {
    const formatted = format(parseISO(dateStr), "EEE d MMM", { locale: fr }).toLowerCase();
    return `Jour ${index + 1} · ${formatted}`;
  } catch {
    return `Jour ${index + 1}`;
  }
}

export function formatFullDateHuman(dateStr: string): string {
  try {
    return format(parseISO(dateStr), "EEEE d MMMM", { locale: fr }).toLowerCase();
  } catch {
    return dateStr;
  }
}

export function categoryLabelFr(cat: string): string {
  const upper = (cat || "").toUpperCase();
  if (upper.includes("CULTUR") || upper.includes("MUSEUM") || upper.includes("HISTOR")) {
    return "Culture & Patrimoine";
  }
  if (upper.includes("NATUR") || upper.includes("PARK") || upper.includes("GARDEN")) {
    return "Parcs & Nature";
  }
  if (upper.includes("FOOD") || upper.includes("RESTAURANT") || upper.includes("GASTRO")) {
    return "Gastronomie";
  }
  if (upper.includes("NIGHT")) {
    return "Soirée & Détente";
  }
  return "Incontournable";
}

export function normalizeSchedulePayload(raw: any): TripItinerarySchedule {
  const rawDays = raw?.days || {};
  const normalizedDays: ItineraryDayGroup[] = Array.isArray(rawDays)
    ? rawDays
    : Object.entries(rawDays).map(([dateKey, dayItems], idx) => ({
        day_number: idx + 1,
        visit_date: dateKey,
        items: (dayItems as ItineraryItemView[]) || [],
      }));

  return {
    trip_id: raw?.trip_id || "",
    city_name: raw?.city_name || raw?.destination_city || "Destination",
    destination_timezone: raw?.destination_timezone || "Europe/Paris",
    arrival_at_utc: raw?.arrival_at_utc ?? raw?.trip_arrival_utc ?? null,
    departure_at_utc: raw?.departure_at_utc ?? raw?.trip_departure_utc ?? null,
    local_arrival_at: raw?.local_arrival_at ?? raw?.trip_arrival_local ?? null,
    local_departure_at: raw?.local_departure_at ?? raw?.trip_departure_local ?? null,
    total_visits: raw?.total_visits ?? 0,
    routing_mode: raw?.routing_mode || "simulated",
    routing_source_label: raw?.routing_source_label || "Temps estimé",
    pending_calendar_sync_count: raw?.pending_calendar_sync_count ?? 0,
    days: normalizedDays,
    items: raw?.items || [],
  };
}

export function buildTripDayDates(
  schedule: TripItinerarySchedule | null,
  fallbackStart: string = "2026-11-10",
  fallbackEnd: string = "2026-11-17",
  extraDates: string[] = []
): string[] {
  const startStr = schedule?.local_arrival_at
    ? schedule.local_arrival_at.slice(0, 10)
    : fallbackStart;
  const endStr = schedule?.local_departure_at
    ? schedule.local_departure_at.slice(0, 10)
    : fallbackEnd;

  const dates: string[] = [];
  const cur = new Date(`${startStr}T00:00:00Z`);
  const end = new Date(`${endStr}T00:00:00Z`);
  if (Number.isNaN(cur.getTime()) || Number.isNaN(end.getTime()) || cur > end) {
    return [fallbackStart];
  }
  while (cur <= end && dates.length < 16) {
    dates.push(cur.toISOString().slice(0, 10));
    cur.setUTCDate(cur.getUTCDate() + 1);
  }
  for (const d of schedule?.days || []) {
    if (d.visit_date && !dates.includes(d.visit_date)) {
      dates.push(d.visit_date);
    }
  }
  for (const extra of extraDates) {
    if (extra && !dates.includes(extra)) {
      dates.push(extra);
    }
  }
  return dates.sort();
}

/* ============================================================================
 * 1. ÉCRAN HÉBERGEMENT (/accommodations)
 *    - Liste de cartes avec photo à gauche + carte à droite (bascule Liste / Carte sur mobile)
 *    - Zone issue du voyage (aucune coordonnée à saisir)
 *    - Filtres repliables (budget, type)
 *    - Fiche avec restaurants proches
 * ========================================================================== */
export function AccommodationsScreen({
  apiBase,
  trip,
  destination,
  selectedAccommodation,
  onSelectAccommodation,
}: {
  apiBase: string;
  trip: Trip | null;
  destination: Destination | null;
  selectedAccommodation: AccommodationItem | null;
  onSelectAccommodation: (acc: AccommodationItem) => void;
}) {
  const navigate = useNavigate();
  const { notify } = useToast();

  const [filtersOpen, setFiltersOpen] = useState<boolean>(false);
  const [accTypeFilter, setAccTypeFilter] = useState<string>("ALL");
  const [maxBudget, setMaxBudget] = useState<string>("2000");
  const [mobileView, setMobileView] = useState<"list" | "map">("list");

  const [accommodations, setAccommodations] = useState<AccommodationItem[]>(
    selectedAccommodation ? [selectedAccommodation] : []
  );
  const [loading, setLoading] = useState<boolean>(!selectedAccommodation);
  const [errorMsg, setErrorMsg] = useState<string>("");
  const [focusedAccId, setFocusedAccId] = useState<string>(
    selectedAccommodation?.id || ""
  );
  const [detailModalAcc, setDetailModalAcc] = useState<AccommodationItem | null>(null);

  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const leafletMapRef = useRef<any>(null);
  const leafletLayerGroupRef = useRef<any>(null);

  const cityLabel = destination?.city_name || "votre destination";

  async function loadAccommodations() {
    setLoading(true);
    setErrorMsg("");
    try {
      const params = new URLSearchParams({
        radius_km: "12",
        restaurant_radius_km: "5",
      });
      if (trip?.id) {
        params.set("trip_id", trip.id);
      } else if (destination?.id) {
        params.set("destination_id", destination.id);
      }
      if (maxBudget && maxBudget !== "ALL") {
        params.set("max_price", maxBudget);
      }
      if (accTypeFilter === "HOTEL" || accTypeFilter === "AIRBNB") {
        params.set("accommodation_type", accTypeFilter);
      }

      const resp = await fetch(`${apiBase}/api/v1/accommodations/search?${params.toString()}`);
      if (!resp.ok) {
        const err = await resp.json().catch(() => null);
        setErrorMsg(
          typeof err?.detail === "string"
            ? err.detail
            : "Impossible de charger les hébergements pour cette destination."
        );
        setAccommodations([]);
        return;
      }
      const list: AccommodationItem[] = await resp.json();
      setAccommodations(list);
      if (list.length > 0) {
        setFocusedAccId((prev) =>
          list.some((item) => item.id === prev) ? prev : list[0].id
        );
      }
    } catch {
      setErrorMsg("Le service d'hébergements est momentanément indisponible.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAccommodations();
  }, [trip?.id, destination?.id, accTypeFilter, maxBudget]);

  const focusedAccommodation = useMemo(
    () =>
      accommodations.find((a) => a.id === focusedAccId) ||
      accommodations[0] ||
      null,
    [accommodations, focusedAccId]
  );

  // Carte interactive Leaflet synchronisée avec la destination et le logement actif
  useEffect(() => {
    const L = window.L;
    if (!L || !mapContainerRef.current) return;

    const centerLat =
      focusedAccommodation?.latitude ?? destination?.latitude ?? 31.6295;
    const centerLng =
      focusedAccommodation?.longitude ?? destination?.longitude ?? -7.9811;

    if (!leafletMapRef.current) {
      leafletMapRef.current = L.map(mapContainerRef.current).setView(
        [centerLat, centerLng],
        13
      );
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap",
      }).addTo(leafletMapRef.current);
      leafletLayerGroupRef.current = L.layerGroup().addTo(leafletMapRef.current);
    } else {
      leafletMapRef.current.setView([centerLat, centerLng], 13);
      setTimeout(() => leafletMapRef.current?.invalidateSize(), 150);
    }

    const layerGroup = leafletLayerGroupRef.current;
    if (!layerGroup) return;
    layerGroup.clearLayers();

    for (const acc of accommodations) {
      const isFocused = acc.id === focusedAccommodation?.id;
      const marker = L.circleMarker([acc.latitude, acc.longitude], {
        radius: isFocused ? 10 : 8,
        color: "#0F766E",
        weight: isFocused ? 3 : 2,
        fillColor: acc.type === "HOTEL" ? "#0F766E" : "#14B8A6",
        fillOpacity: 0.9,
      }).addTo(layerGroup);

      marker.bindPopup(
        `<strong>${acc.name}</strong><br/>${Math.round(Number(acc.price_per_night))} € / nuit`
      );
      marker.on("click", () => setFocusedAccId(acc.id));

      if (isFocused) {
        for (const rest of acc.nearby_restaurants) {
          L.circleMarker([rest.latitude, rest.longitude], {
            radius: 6,
            color: "#B45309",
            weight: 2,
            fillColor: "#F59E0B",
            fillOpacity: 0.9,
          })
            .addTo(layerGroup)
            .bindPopup(
              `<strong>${rest.name}</strong><br/>À ${rest.walking_minutes} min à pied`
            );
        }
      }
    }
  }, [accommodations, focusedAccommodation, destination, mobileView]);

  function handleChooseAccommodation(acc: AccommodationItem) {
    onSelectAccommodation(acc);
    notify({
      title: "Hébergement retenu pour votre séjour",
      description: `${acc.name} a été ajouté à votre récapitulatif de voyage.`,
      tone: "success",
    });
  }

  return (
    <div
      className="mx-auto max-w-6xl px-4 py-8 space-y-6"
      data-testid="accommodations-screen"
    >
      {/* En-tête de l'écran Hébergement */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div>
          <Badge variant="brand" className="mb-2">
            Séjour à {cityLabel}
          </Badge>
          <h1 className="text-h1 text-ink">Hébergements à {cityLabel}</h1>
          <p className="text-body text-ink-secondary mt-1">
            Hôtels et logements situés au cœur de {cityLabel}, avec les bonnes tables accessibles à pied.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Bascule Liste / Carte sur mobile */}
          <div
            className="inline-flex lg:hidden rounded-card border border-border bg-canvas-card p-1"
            role="group"
            aria-label="Affichage mobile"
          >
            <button
              type="button"
              data-testid="mobile-view-list-btn"
              onClick={() => setMobileView("list")}
              className={`px-3 py-1.5 rounded-md text-caption font-medium transition-colors ${
                mobileView === "list"
                  ? "bg-brand-700 text-white"
                  : "text-ink-secondary hover:text-ink"
              }`}
            >
              Liste
            </button>
            <button
              type="button"
              data-testid="mobile-view-map-btn"
              onClick={() => setMobileView("map")}
              className={`px-3 py-1.5 rounded-md text-caption font-medium transition-colors ${
                mobileView === "map"
                  ? "bg-brand-700 text-white"
                  : "text-ink-secondary hover:text-ink"
              }`}
            >
              Carte
            </button>
          </div>

          <Button
            type="button"
            variant="secondary"
            size="md"
            data-testid="toggle-acc-filters-btn"
            onClick={() => setFiltersOpen((prev) => !prev)}
          >
            <SlidersHorizontal className="h-4 w-4" />
            <span>Filtres</span>
          </Button>

          <Button
            type="button"
            size="md"
            data-testid="acc-go-to-activities-btn"
            onClick={() => navigate("/activities")}
          >
            <span>Choisir mes activités</span>
            <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Panneau de filtres repliable (2 champs : type et budget) */}
      {filtersOpen && (
        <Card className="p-4" data-testid="acc-filters-panel">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 items-end">
            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Type d'hébergement
              </label>
              <Select
                value={accTypeFilter}
                onValueChange={setAccTypeFilter}
                ariaLabel="Type d'hébergement"
                options={[
                  { value: "ALL", label: "Hôtels & Airbnb" },
                  { value: "HOTEL", label: "Hôtels uniquement" },
                  { value: "AIRBNB", label: "Appartements & Riads (Airbnb)" },
                ]}
              />
            </div>

            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Budget maximum par nuit
              </label>
              <Select
                value={maxBudget}
                onValueChange={setMaxBudget}
                ariaLabel="Budget maximum par nuit"
                options={[
                  { value: "2000", label: "Tous les budgets" },
                  { value: "180", label: "Jusqu'à 180 € / nuit" },
                  { value: "300", label: "Jusqu'à 300 € / nuit" },
                  { value: "500", label: "Jusqu'à 500 € / nuit" },
                ]}
              />
            </div>

            <div className="flex justify-end">
              <Button
                type="button"
                variant="secondary"
                size="md"
                onClick={() => {
                  setAccTypeFilter("ALL");
                  setMaxBudget("2000");
                }}
              >
                Réinitialiser
              </Button>
            </div>
          </div>
        </Card>
      )}

      {errorMsg && (
        <Card className="p-5 border-red-200 bg-feedback-dangerBg">
          <p className="text-body font-medium text-feedback-danger">{errorMsg}</p>
        </Card>
      )}

      {/* Disposition principale : Liste de cartes à gauche + Carte à droite */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Colonne gauche : Liste de cartes avec photo à gauche */}
        <div
          className={`lg:col-span-7 space-y-4 ${
            mobileView === "map" ? "hidden lg:block" : "block"
          }`}
          data-testid="accommodations-list-column"
        >
          {loading ? (
            <div className="space-y-4">
              {[1, 2, 3].map((i) => (
                <Card key={i} className="p-4 flex flex-col sm:flex-row gap-4">
                  <Skeleton className="h-44 sm:w-52 rounded-card" />
                  <div className="flex-1 space-y-3 py-1">
                    <Skeleton className="h-5 w-32" />
                    <Skeleton className="h-6 w-3/4" />
                    <Skeleton className="h-4 w-1/2" />
                    <Skeleton className="h-10 w-40 mt-4" />
                  </div>
                </Card>
              ))}
            </div>
          ) : accommodations.length === 0 ? (
            <Card className="p-8 text-center space-y-3">
              <Building2 className="h-8 w-8 text-brand-700 mx-auto" />
              <h2 className="text-h2 text-ink">
                Aucun hébergement pour ces critères
              </h2>
              <p className="text-body text-ink-secondary max-w-md mx-auto">
                Essayez d'élargir votre budget ou d'afficher à la fois les hôtels et les logements Airbnb.
              </p>
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setAccTypeFilter("ALL");
                  setMaxBudget("2000");
                }}
              >
                Afficher tous les hébergements
              </Button>
            </Card>
          ) : (
            accommodations.map((acc, idx) => {
              const isSelected = selectedAccommodation?.id === acc.id;
              const isFocused = focusedAccommodation?.id === acc.id;
              const coverPhoto =
                acc.photos?.[0] ||
                destination?.hero_image_url ||
                FALLBACK_HOTEL_IMAGE;

              return (
                <Card
                  key={acc.id}
                  data-testid={`accommodation-card-${idx}`}
                  onClick={() => setFocusedAccId(acc.id)}
                  className={`overflow-hidden transition-shadow cursor-pointer ${
                    isFocused
                      ? "ring-2 ring-brand-700 shadow-cardHover"
                      : "hover:shadow-cardHover"
                  }`}
                >
                  <div className="flex flex-col sm:flex-row">
                    {/* Photo à gauche */}
                    <div className="sm:w-56 shrink-0 aspect-[4/3] sm:aspect-auto bg-canvas-subtle relative overflow-hidden">
                      <img
                        src={coverPhoto}
                        alt={acc.name}
                        width={320}
                        height={240}
                        loading="eager"
                        referrerPolicy="no-referrer"
                        onError={(e) => {
                          e.currentTarget.src = FALLBACK_HOTEL_IMAGE;
                        }}
                        className="h-full w-full object-cover"
                      />
                      <div className="absolute top-3 left-3">
                        <Badge
                          variant={acc.type === "HOTEL" ? "brand" : "default"}
                          className="bg-white/95 text-ink shadow-sm"
                        >
                          {acc.type === "HOTEL" ? "Hôtel" : "Airbnb"}
                        </Badge>
                      </div>
                    </div>

                    {/* Détails à droite */}
                    <div className="flex-1 p-5 flex flex-col justify-between gap-4">
                      <div>
                        <div className="flex items-center justify-between gap-2 text-caption text-ink-muted">
                          <span className="inline-flex items-center gap-1">
                            <MapPin className="h-3.5 w-3.5 text-brand-700" />
                            {acc.neighborhood} • à {acc.distance_from_center_km} km du centre
                          </span>
                          <span className="inline-flex items-center gap-1 font-semibold text-ink">
                            <Star className="h-3.5 w-3.5 fill-amber-400 text-amber-500" />
                            {acc.rating.toFixed(1)}
                          </span>
                        </div>

                        <h2 className="text-h2 text-ink mt-1">{acc.name}</h2>
                        <p className="text-caption text-ink-secondary mt-0.5">
                          {acc.address}
                        </p>

                        {/* Aperçu des restaurants proches */}
                        {acc.nearby_restaurants.length > 0 && (
                          <div className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-canvas-subtle px-2.5 py-1 text-caption text-ink-secondary">
                            <Utensils className="h-3.5 w-3.5 text-brand-700" />
                            <span>
                              {acc.nearby_restaurants.length} restaurants proches (dès{" "}
                              {acc.nearby_restaurants[0].walking_minutes} min à pied)
                            </span>
                          </div>
                        )}
                      </div>

                      <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-border">
                        <div>
                          <span className="text-h2 font-bold text-ink">
                            {Math.round(Number(acc.price_per_night))} €
                          </span>
                          <span className="text-caption text-ink-muted"> / nuit</span>
                        </div>

                        <div className="flex items-center gap-2">
                          <Button
                            type="button"
                            variant="secondary"
                            size="sm"
                            data-testid={`acc-detail-btn-${idx}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              setDetailModalAcc(acc);
                            }}
                          >
                            Fiche & restaurants
                          </Button>

                          <Button
                            type="button"
                            variant={isSelected ? "secondary" : "primary"}
                            size="sm"
                            data-testid={`acc-choose-btn-${idx}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleChooseAccommodation(acc);
                            }}
                          >
                            {isSelected ? "Sélectionné ✓" : "Choisir"}
                          </Button>
                        </div>
                      </div>
                    </div>
                  </div>
                </Card>
              );
            })
          )}
        </div>

        {/* Colonne droite : Carte interactive */}
        <div
          className={`lg:col-span-5 lg:sticky lg:top-24 ${
            mobileView === "list" ? "hidden lg:block" : "block"
          }`}
          data-testid="accommodations-map-column"
        >
          <Card className="overflow-hidden">
            <div className="p-4 border-b border-border flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Navigation className="h-4 w-4 text-brand-700" />
                <span className="text-caption font-semibold text-ink">
                  Carte des hébergements et restaurants à {cityLabel}
                </span>
              </div>
              <Badge variant="brand">{accommodations.length} adresses</Badge>
            </div>

            <div
              ref={mapContainerRef}
              className="h-[420px] w-full bg-canvas-subtle"
              data-testid="accommodations-leaflet-map"
            />

            {focusedAccommodation && (
              <div className="p-4 bg-canvas-subtle border-t border-border flex items-center justify-between gap-3">
                <div>
                  <div className="text-caption font-semibold text-ink">
                    {focusedAccommodation.name}
                  </div>
                  <div className="text-caption text-ink-secondary">
                    {focusedAccommodation.neighborhood} •{" "}
                    {focusedAccommodation.nearby_restaurants.length} tables à proximité
                  </div>
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => setDetailModalAcc(focusedAccommodation)}
                >
                  Voir la fiche
                </Button>
              </div>
            )}
          </Card>
        </div>
      </div>

      {/* Modale Fiche hébergement + restaurants proches */}
      <Modal
        open={Boolean(detailModalAcc)}
        onOpenChange={(open) => {
          if (!open) setDetailModalAcc(null);
        }}
        title={detailModalAcc?.name || "Détails de l'hébergement"}
        description={
          detailModalAcc
            ? `${detailModalAcc.neighborhood} — ${detailModalAcc.address}`
            : undefined
        }
        maxWidthClass="max-w-2xl"
      >
        {detailModalAcc && (
          <div className="space-y-5" data-testid="accommodation-detail-modal">
            <div className="aspect-[16/9] w-full overflow-hidden rounded-card bg-canvas-subtle">
              <img
                src={
                  detailModalAcc.photos?.[0] ||
                  destination?.hero_image_url ||
                  FALLBACK_HOTEL_IMAGE
                }
                alt={detailModalAcc.name}
                width={640}
                height={360}
                referrerPolicy="no-referrer"
                onError={(e) => {
                  e.currentTarget.src = FALLBACK_HOTEL_IMAGE;
                }}
                className="h-full w-full object-cover"
              />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap gap-2">
                <Badge variant="brand">
                  {detailModalAcc.type === "HOTEL" ? "Hôtel" : "Airbnb"}
                </Badge>
                {detailModalAcc.amenities.map((am) => (
                  <Badge key={am}>{am}</Badge>
                ))}
              </div>
              <div className="text-h2 font-bold text-ink">
                {Math.round(Number(detailModalAcc.price_per_night))} €{" "}
                <span className="text-caption font-normal text-ink-muted">/ nuit</span>
              </div>
            </div>

            {/* Liste des restaurants proches */}
            <div className="space-y-3">
              <h3 className="text-body font-semibold text-ink flex items-center gap-2">
                <Utensils className="h-4 w-4 text-brand-700" />
                <span>
                  Restaurants proches accessibles à pied ({detailModalAcc.nearby_restaurants.length})
                </span>
              </h3>

              {detailModalAcc.nearby_restaurants.length === 0 ? (
                <p className="text-caption text-ink-secondary">
                  Aucun restaurant répertorié dans un rayon immédiat.
                </p>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {detailModalAcc.nearby_restaurants.map((rest) => (
                    <div
                      key={rest.id}
                      className="rounded-card border border-border bg-canvas-subtle p-3.5 space-y-1"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-caption font-semibold text-ink">
                          {rest.name}
                        </span>
                        <Badge variant="brand">{rest.walking_minutes} min à pied</Badge>
                      </div>
                      <p className="text-caption text-ink-secondary line-clamp-2">
                        {rest.description}
                      </p>
                      <div className="text-caption text-ink-muted pt-1">
                        À {rest.distance_m} m • ~{Math.round(Number(rest.estimated_cost))} € / pers.
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="flex flex-wrap items-center justify-end gap-3 pt-3 border-t border-border">
              <Button
                type="button"
                variant="secondary"
                onClick={() => setDetailModalAcc(null)}
              >
                Fermer
              </Button>
              <Button
                type="button"
                onClick={() => {
                  handleChooseAccommodation(detailModalAcc);
                  setDetailModalAcc(null);
                }}
              >
                Retenir cet hébergement
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

/* ============================================================================
 * 2. ÉCRAN À VISITER (/activities)
 *    - Grille de grandes photos
 *    - Bouton "Ajouter" qui ouvre un petit panneau (jour, heure, durée préremplie)
 *    - Aperçu plein écran
 * ========================================================================== */
export function ActivitiesScreen({
  apiBase,
  token,
  trip,
  destination,
  gallery,
  onRefreshGallery,
}: {
  apiBase: string;
  token: string;
  trip: Trip | null;
  destination: Destination | null;
  gallery: TripGalleryPayload | null;
  onRefreshGallery: () => Promise<void>;
}) {
  const navigate = useNavigate();
  const { notify } = useToast();

  const [categoryFilter, setCategoryFilter] = useState<string>("ALL");
  const [schedule, setSchedule] = useState<TripItinerarySchedule | null>(null);

  // Petit panneau d'ajout (3 champs : jour, heure, durée préremplie)
  const [addPanelPlace, setAddPanelPlace] = useState<PlaceItem | null>(null);
  const [visitDate, setVisitDate] = useState<string>("2026-11-11");
  const [startTime, setStartTime] = useState<string>("10:00");
  const [durationMin, setDurationMin] = useState<string>("120");
  const [submittingVisit, setSubmittingVisit] = useState<boolean>(false);
  const [panelValidationError, setPanelValidationError] =
    useState<ValidationFailureDetail | null>(null);

  // Modale Aperçu plein écran
  const [fullscreenPlace, setFullscreenPlace] = useState<PlaceItem | null>(null);

  const cityLabel = destination?.city_name || gallery?.city_name || "votre destination";

  useEffect(() => {
    if (!trip?.id || !token) return;
    onRefreshGallery();
    fetch(`${apiBase}/api/v1/itinerary/trip/${trip.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((raw) => {
        if (raw) {
          const norm = normalizeSchedulePayload(raw);
          setSchedule(norm);
          const days = buildTripDayDates(norm);
          if (days.length > 1) {
            setVisitDate(days[1]);
          } else if (days.length === 1) {
            setVisitDate(days[0]);
          }
        }
      })
      .catch(() => null);
  }, [trip?.id, token]);

  const tripDays = useMemo(() => buildTripDayDates(schedule), [schedule]);

  const filteredPlaces = useMemo(() => {
    const list = gallery?.places || [];
    if (categoryFilter === "ALL") return list;
    return list.filter((p) =>
      p.category.toUpperCase().includes(categoryFilter.toUpperCase())
    );
  }, [gallery, categoryFilter]);

  function openAddPanel(place: PlaceItem) {
    setAddPanelPlace(place);
    setDurationMin(String(place.recommended_duration_min || 90));
    setPanelValidationError(null);
  }

  async function handleAddVisitToItinerary(
    overrideDate?: string,
    overrideStartTime?: string
  ) {
    if (!addPanelPlace || !trip?.id) return;
    setSubmittingVisit(true);
    setPanelValidationError(null);

    try {
      await fetch(`${apiBase}/api/v1/places/trip/${trip.id}/select`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ place_id: addPanelPlace.id, selected: true }),
      }).catch(() => null);

      const resp = await fetch(`${apiBase}/api/v1/itinerary/items`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          trip_id: trip.id,
          place_id: addPanelPlace.id,
          visit_date: overrideDate || visitDate,
          local_start_time: overrideStartTime || startTime,
          duration_minutes: Math.max(30, Number(durationMin) || 90),
          transit_mode: "WALKING",
        }),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => null);
        if (err?.detail && typeof err.detail === "object" && err.detail.message) {
          setPanelValidationError(err.detail as ValidationFailureDetail);
        } else {
          setPanelValidationError({
            valid: false,
            reason_code: "VALIDATION_ERROR",
            message:
              typeof err?.detail === "string"
                ? err.detail
                : "Ce créneau ne respecte pas les horaires de votre séjour.",
            conflict_details: {},
            suggested_slots: [],
          });
        }
        return;
      }

      const created: ItineraryItemView = await resp.json();
      notify({
        title: "Visite ajoutée à votre programme",
        description: `${created.place_name} le ${formatFullDateHuman(created.local_visit_date)} à ${created.local_start_time}.`,
        tone: "success",
      });
      setAddPanelPlace(null);
      await onRefreshGallery();
    } finally {
      setSubmittingVisit(false);
    }
  }

  if (gallery && !gallery.unlocked) {
    return (
      <div
        className="mx-auto max-w-3xl px-4 py-12"
        data-testid="activities-locked-screen"
      >
        <Card className="p-8 text-center space-y-4">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-brand-50 text-brand-700">
            <Compass className="h-6 w-6" />
          </div>
          <h1 className="text-h1 text-ink">
            Réservez votre vol pour découvrir les activités à {cityLabel}
          </h1>
          <p className="text-body text-ink-secondary max-w-lg mx-auto">
            {gallery.unlock_message ||
              "Dès que votre billet d'avion est confirmé, les lieux à visiter s'ouvrent avec leurs horaires et durées conseillées."}
          </p>
          <div className="pt-2">
            <Button
              type="button"
              size="lg"
              data-testid="locked-go-to-flights-btn"
              onClick={() => navigate("/flights")}
            >
              <Plane className="h-4 w-4" />
              <span>Choisir mon vol</span>
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div
      className="mx-auto max-w-6xl px-4 py-8 space-y-6"
      data-testid="activities-screen"
    >
      {/* En-tête */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div>
          <Badge variant="brand" className="mb-2">
            Découvertes à {cityLabel}
          </Badge>
          <h1 className="text-h1 text-ink">Lieux à visiter à {cityLabel}</h1>
          <p className="text-body text-ink-secondary mt-1">
            Explorez les incontournables en grand format et composez votre programme à votre rythme.
          </p>
        </div>

        <Button
          type="button"
          size="md"
          data-testid="activities-go-to-itinerary-btn"
          onClick={() => navigate("/itinerary")}
        >
          <CalendarIcon className="h-4 w-4" />
          <span>Voir mon programme</span>
          <ArrowRight className="h-4 w-4" />
        </Button>
      </div>

      {/* Filtres sobres par catégorie */}
      <div className="flex items-center gap-2 overflow-x-auto no-scrollbar pb-1">
        {[
          { value: "ALL", label: "Tout voir" },
          { value: "CULTURE", label: "Culture & Patrimoine" },
          { value: "NATURE", label: "Parcs & Nature" },
          { value: "FOOD", label: "Gastronomie" },
        ].map((cat) => (
          <button
            key={cat.value}
            type="button"
            onClick={() => setCategoryFilter(cat.value)}
            className={`px-3.5 py-2 rounded-card text-caption font-medium whitespace-nowrap transition-colors ${
              categoryFilter === cat.value
                ? "bg-brand-700 text-white"
                : "bg-canvas-card border border-border text-ink-secondary hover:text-ink"
            }`}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* Grille de grandes photos */}
      {!gallery ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2, 3, 4, 5, 6].map((n) => (
            <Card key={n} className="overflow-hidden">
              <Skeleton className="aspect-[4/3] w-full rounded-none" />
              <div className="p-5 space-y-3">
                <Skeleton className="h-5 w-2/3" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-10 w-full mt-2" />
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <div
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6"
          data-testid="activities-photo-grid"
        >
          {filteredPlaces.map((place, idx) => {
            const photoUrl =
              place.hero_photos?.[0] ||
              destination?.hero_image_url ||
              FALLBACK_PLACE_IMAGE;

            return (
              <Card
                key={place.id}
                data-testid={`activity-card-${idx}`}
                className="overflow-hidden flex flex-col justify-between group hover:shadow-cardHover transition-shadow"
              >
                <div>
                  {/* Grande photo avec aperçu plein écran */}
                  <div className="relative aspect-[4/3] w-full overflow-hidden bg-canvas-subtle">
                    <img
                      src={photoUrl}
                      alt={place.name}
                      width={640}
                      height={480}
                      loading="eager"
                      referrerPolicy="no-referrer"
                      onError={(e) => {
                        e.currentTarget.src = FALLBACK_PLACE_IMAGE;
                      }}
                      onClick={() => setFullscreenPlace(place)}
                      className="h-full w-full object-cover cursor-pointer transition-transform duration-300 group-hover:scale-105"
                    />
                    <div className="absolute top-3 left-3 flex items-center gap-1.5">
                      <Badge className="bg-white/95 text-ink shadow-sm">
                        {categoryLabelFr(place.category)}
                      </Badge>
                    </div>
                    <button
                      type="button"
                      aria-label={`Aperçu plein écran de ${place.name}`}
                      data-testid={`fullscreen-place-btn-${idx}`}
                      onClick={() => setFullscreenPlace(place)}
                      className="absolute top-3 right-3 flex h-9 w-9 items-center justify-center rounded-full bg-ink/70 text-white hover:bg-ink transition-colors"
                    >
                      <Maximize2 className="h-4 w-4" />
                    </button>
                  </div>

                  <div className="p-5">
                    <div className="flex items-center justify-between gap-2 text-caption text-ink-muted">
                      <span className="inline-flex items-center gap-1">
                        <Clock className="h-3.5 w-3.5 text-brand-700" />
                        Durée conseillée : {place.recommended_duration_min} min
                      </span>
                      <span className="font-semibold text-ink">
                        ★ {place.avg_rating.toFixed(1)}
                      </span>
                    </div>

                    <h2 className="text-h2 text-ink mt-1.5">{place.name}</h2>
                    <p className="text-caption text-ink-secondary mt-1 line-clamp-2">
                      {place.description}
                    </p>
                  </div>
                </div>

                <div className="px-5 pb-5 pt-2 flex items-center justify-between gap-2 border-t border-border">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setFullscreenPlace(place)}
                  >
                    Aperçu photo
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    data-testid={`open-add-visit-panel-btn-${idx}`}
                    onClick={() => openAddPanel(place)}
                  >
                    <Plus className="h-4 w-4" />
                    <span>Ajouter</span>
                  </Button>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {/* Petit panneau d'ajout au programme (3 champs : Jour, Heure, Durée préremplie) */}
      <Modal
        open={Boolean(addPanelPlace)}
        onOpenChange={(open) => {
          if (!open) {
            setAddPanelPlace(null);
            setPanelValidationError(null);
          }
        }}
        title={
          addPanelPlace
            ? `Ajouter « ${addPanelPlace.name} »`
            : "Ajouter une visite"
        }
        description="Choisissez le jour et l'heure de début. La durée conseillée est préremplie."
        maxWidthClass="max-w-md"
      >
        {addPanelPlace && (
          <div className="space-y-4" data-testid="add-visit-panel">
            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Jour de la visite
              </label>
              <Input
                type="date"
                data-testid="add-visit-date-input"
                value={visitDate}
                onChange={(e) => setVisitDate(e.target.value)}
              />
              {tripDays.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {tripDays.map((d, i) => (
                    <button
                      key={d}
                      type="button"
                      onClick={() => setVisitDate(d)}
                      className={`px-2.5 py-1 rounded-md text-caption font-medium transition-colors ${
                        visitDate === d
                          ? "bg-brand-700 text-white"
                          : "bg-canvas-subtle text-ink-secondary hover:text-ink"
                      }`}
                    >
                      {formatDayPillHuman(d, i)}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Heure de début
              </label>
              <Input
                type="time"
                data-testid="add-visit-time-input"
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
              />
            </div>

            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Durée prévue (en minutes)
              </label>
              <Input
                type="number"
                min={30}
                max={360}
                step={15}
                data-testid="add-visit-duration-input"
                value={durationMin}
                onChange={(e) => setDurationMin(e.target.value)}
              />
            </div>

            {panelValidationError && (
              <div
                data-testid="panel-validation-error"
                className="rounded-card border border-amber-300 bg-feedback-warningBg p-3.5 space-y-2.5"
              >
                <p className="text-caption font-medium text-feedback-warning">
                  {panelValidationError.message}
                </p>
                {panelValidationError.suggested_slots?.length > 0 && (
                  <div className="space-y-1.5">
                    <div className="text-caption font-semibold text-ink">
                      Créneaux libres suggérés (cliquez pour choisir) :
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {panelValidationError.suggested_slots.map((slot, sIdx) => (
                        <button
                          key={`${slot.local_date}-${slot.local_start_time}`}
                          type="button"
                          data-testid={`panel-suggested-slot-${sIdx}`}
                          onClick={() => {
                            setVisitDate(slot.local_date);
                            setStartTime(slot.local_start_time);
                            handleAddVisitToItinerary(
                              slot.local_date,
                              slot.local_start_time
                            );
                          }}
                          className="rounded-md bg-white border border-brand-300 px-2.5 py-1.5 text-caption font-medium text-brand-800 hover:bg-brand-50 transition-colors"
                        >
                          {formatFullDateHuman(slot.local_date)} • {slot.local_start_time} →{" "}
                          {slot.local_end_time}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <Button
                type="button"
                variant="secondary"
                onClick={() => setAddPanelPlace(null)}
              >
                Annuler
              </Button>
              <Button
                type="button"
                disabled={submittingVisit}
                data-testid="confirm-add-visit-btn"
                onClick={() => handleAddVisitToItinerary()}
              >
                {submittingVisit ? "Ajout en cours..." : "Ajouter à mon programme"}
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Modale Aperçu plein écran */}
      <Modal
        open={Boolean(fullscreenPlace)}
        onOpenChange={(open) => {
          if (!open) setFullscreenPlace(null);
        }}
        title={fullscreenPlace?.name || "Aperçu du lieu"}
        description={
          fullscreenPlace ? categoryLabelFr(fullscreenPlace.category) : undefined
        }
        maxWidthClass="max-w-3xl"
      >
        {fullscreenPlace && (
          <div className="space-y-4" data-testid="fullscreen-place-modal">
            <div className="aspect-[16/10] w-full overflow-hidden rounded-card bg-canvas-subtle">
              <img
                src={
                  fullscreenPlace.hero_photos?.[0] ||
                  destination?.hero_image_url ||
                  FALLBACK_PLACE_IMAGE
                }
                alt={fullscreenPlace.name}
                width={960}
                height={600}
                referrerPolicy="no-referrer"
                onError={(e) => {
                  e.currentTarget.src = FALLBACK_PLACE_IMAGE;
                }}
                className="h-full w-full object-cover"
              />
            </div>

            <p className="text-body text-ink-secondary">
              {fullscreenPlace.description}
            </p>

            <div className="flex flex-wrap items-center justify-between gap-4 rounded-card bg-canvas-subtle p-4">
              <div className="space-y-0.5">
                <div className="text-caption text-ink-muted">Durée conseillée</div>
                <div className="text-body font-semibold text-ink">
                  {fullscreenPlace.recommended_duration_min} minutes
                </div>
              </div>
              <div className="space-y-0.5">
                <div className="text-caption text-ink-muted">Environnement</div>
                <div className="text-body font-semibold text-ink">
                  {fullscreenPlace.is_outdoor ? "En plein air" : "En intérieur"}
                </div>
              </div>
              <div className="space-y-0.5">
                <div className="text-caption text-ink-muted">Appréciation</div>
                <div className="text-body font-semibold text-ink">
                  ★ {fullscreenPlace.avg_rating.toFixed(1)} / 5
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <Button
                type="button"
                variant="secondary"
                onClick={() => setFullscreenPlace(null)}
              >
                Fermer
              </Button>
              <Button
                type="button"
                onClick={() => {
                  const p = fullscreenPlace;
                  setFullscreenPlace(null);
                  openAddPanel(p);
                }}
              >
                <Plus className="h-4 w-4" />
                <span>Ajouter à mon programme</span>
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

/* ============================================================================
 * 3. ÉCRAN MON PROGRAMME (/itinerary) — ÉTAPE 3 & ÉTAPE 4
 *    - UN JOUR à la fois
 *    - Puces horizontales des jours du séjour AVEC météo par jour
 *    - Alerte pluie/orage sur visite extérieure + suggestion intérieur / autre créneau (1 clic Accepter / Refuser)
 *    - Bouton "Génère mon programme" (Itinéraire IA en brouillon, 3 champs max)
 *    - Vue chronologique verticale du jour choisi avec indication Temps estimé / Temps réel
 *    - Bulle flottante Assistant de chat avec boutons de confirmation sur les actions proposées
 * ========================================================================== */
export function ItineraryScreen({
  apiBase,
  token,
  trip,
  destination,
  places,
  onUnauthorized,
}: {
  apiBase: string;
  token: string;
  trip: Trip | null;
  destination: Destination | null;
  places: PlaceItem[];
  onUnauthorized: () => void;
}) {
  const navigate = useNavigate();
  const { notify } = useToast();

  const [schedule, setSchedule] = useState<TripItinerarySchedule | null>(null);
  const [weatherData, setWeatherData] = useState<TripWeatherPayload | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [selectedDayDate, setSelectedDayDate] = useState<string>("");

  // Formulaire sobre d'ajout / test d'horaire (4 champs max : Lieu, Jour, Heure, Durée)
  const [addModalOpen, setAddModalOpen] = useState<boolean>(false);
  const [selectedPlaceId, setSelectedPlaceId] = useState<string>("");
  const [visitDate, setVisitDate] = useState<string>("");
  const [startTime, setStartTime] = useState<string>("10:00");
  const [durationMinutes, setDurationMinutes] = useState<string>("90");
  const [pendingContextPlaceId, setPendingContextPlaceId] = useState<string>("");
  const [pendingContextDuration, setPendingContextDuration] = useState<number>(90);

  // Erreur de validation métier en français simple + créneaux suggérés cliquables
  const [validationError, setValidationError] =
    useState<ValidationFailureDetail | null>(null);

  // Glisser-déposer
  const [draggedVisit, setDraggedVisit] = useState<ItineraryItemView | null>(null);

  // Aperçu avant validation de "Optimiser mon programme"
  const [optimizationPreview, setOptimizationPreview] =
    useState<OptimizationPreviewPayload | null>(null);
  const [optimizing, setOptimizing] = useState<boolean>(false);

  // Étape 4.2 — Itinéraire IA ("Génère mon programme" : 3 champs max : Budget, Rythme, Goûts)
  const [aiModalOpen, setAiModalOpen] = useState<boolean>(false);
  const [aiBudget, setAiBudget] = useState<string>(
    String(trip?.total_budget_planned || 1500)
  );
  const [aiPace, setAiPace] = useState<"RELAX" | "NORMAL" | "INTENSE">("NORMAL");
  const [aiTastes, setAiTastes] = useState<string[]>(["CULTURE", "NATURE", "FOOD"]);
  const [aiGenerating, setAiGenerating] = useState<boolean>(false);
  const [aiApplying, setAiApplying] = useState<boolean>(false);
  const [aiErrorMsg, setAiErrorMsg] = useState<string>("");
  const [aiDraft, setAiDraft] = useState<AIGenerateDraftPayload | null>(null);

  // Étape 4.1 — Adaptation météo en 1 clic
  const [weatherActionLoadingId, setWeatherActionLoadingId] = useState<string>("");

  // Étape 4.3 — Bulle flottante Assistant de chat
  const [chatOpen, setChatOpen] = useState<boolean>(false);
  const [chatMessages, setChatMessages] = useState<ChatMessageItem[]>([]);
  const [chatInput, setChatInput] = useState<string>("");
  const [chatSending, setChatSending] = useState<boolean>(false);
  const [chatConfirmingId, setChatConfirmingId] = useState<string>("");

  const cityLabel = destination?.city_name || schedule?.city_name || "votre destination";

  async function refreshWeather(tripId: string) {
    try {
      const wResp = await fetch(
        `${apiBase}/api/v1/itinerary/trip/${tripId}/weather?horizon_days=365`,
        {
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      if (wResp.ok) {
        const wJson: TripWeatherPayload = await wResp.json();
        setWeatherData(wJson);
      }
    } catch {
      // Ne bloque pas l'affichage de l'agenda si la météo échoue
    }
  }

  async function refreshChatHistory(tripId: string) {
    try {
      const cResp = await fetch(`${apiBase}/api/v1/itinerary/trip/${tripId}/chat`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (cResp.ok) {
        const cJson = await cResp.json();
        setChatMessages(cJson.messages || []);
      }
    } catch {
      // Historique optionnel au chargement
    }
  }

  async function refreshSchedule() {
    if (!trip?.id || !token) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const resp = await fetch(`${apiBase}/api/v1/itinerary/trip/${trip.id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (resp.status === 401) {
        onUnauthorized();
        return;
      }
      if (resp.ok) {
        const raw = await resp.json();
        const norm = normalizeSchedulePayload(raw);
        setSchedule(norm);

        const days = buildTripDayDates(norm);
        const dayWithVisits = norm.days.find((d) => d.items.length > 0)?.visit_date;
        const defaultDay = dayWithVisits || days[1] || days[0] || "2026-11-11";
        setSelectedDayDate((prev) =>
          prev && days.includes(prev) ? prev : defaultDay
        );
        setVisitDate((prev) => prev || defaultDay);
      }
      await refreshWeather(trip.id);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refreshSchedule();
    if (trip?.id && token) {
      refreshChatHistory(trip.id);
    }
  }, [trip?.id, token]);

  useEffect(() => {
    if (places.length > 0 && !selectedPlaceId) {
      setSelectedPlaceId(places[0].id);
      setDurationMinutes(String(places[0].recommended_duration_min || 90));
    }
  }, [places, selectedPlaceId]);

  const tripDays = useMemo(() => {
    const fallbackStart = trip?.arrival_at ? trip.arrival_at.slice(0, 10) : "2026-11-10";
    const fallbackEnd = trip?.departure_at ? trip.departure_at.slice(0, 10) : "2026-11-17";
    const extraDates = [
      ...(weatherData?.days?.map((d) => d.date) || []),
      ...(aiDraft?.draft_items?.map((s) => s.visit_date) || []),
    ];
    return buildTripDayDates(schedule, fallbackStart, fallbackEnd, extraDates);
  }, [schedule, trip?.arrival_at, trip?.departure_at, weatherData, aiDraft]);

  const weatherByDate = useMemo(() => {
    const map: Record<string, DailyWeatherForecast> = {};
    for (const d of weatherData?.days || []) {
      map[d.date] = d;
    }
    return map;
  }, [weatherData]);

  const selectedDayWeather = selectedDayDate ? weatherByDate[selectedDayDate] : undefined;

  const currentDayItems = useMemo(() => {
    if (!schedule || !selectedDayDate) return [];
    const group = schedule.days.find((d) => d.visit_date === selectedDayDate);
    if (group) return group.items;
    return schedule.items.filter((i) => i.local_visit_date === selectedDayDate);
  }, [schedule, selectedDayDate]);

  function renderWeatherIcon(conditionCode?: string, isSelected?: boolean) {
    const cls = `h-3.5 w-3.5 shrink-0 ${
      isSelected ? "text-white" : "text-brand-700"
    }`;
    if (!conditionCode || conditionCode === "UNAVAILABLE") {
      return <Cloud className={cls} />;
    }
    if (conditionCode === "STORM") {
      return <CloudLightning className={cls} />;
    }
    if (conditionCode === "RAIN") {
      return <CloudRain className={cls} />;
    }
    if (conditionCode === "PARTLY_CLOUDY" || conditionCode === "CLOUDY") {
      return <CloudSun className={cls} />;
    }
    return <Sun className={cls} />;
  }

  function handlePlaceChange(placeId: string) {
    setSelectedPlaceId(placeId);
    const p = places.find((item) => item.id === placeId);
    if (p) {
      setDurationMinutes(String(p.recommended_duration_min || 90));
    }
  }

  async function scheduleVisitRequest(
    placeId: string,
    targetDate: string,
    targetStartTime: string,
    durationMin: number
  ) {
    if (!trip?.id || !placeId) return false;
    setValidationError(null);
    setPendingContextPlaceId(placeId);
    setPendingContextDuration(durationMin);

    const resp = await fetch(`${apiBase}/api/v1/itinerary/items`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        trip_id: trip.id,
        place_id: placeId,
        visit_date: targetDate,
        local_start_time: targetStartTime,
        duration_minutes: durationMin,
        transit_mode: "WALKING",
      }),
    });

    if (resp.status === 401) {
      onUnauthorized();
      return false;
    }

    if (!resp.ok) {
      const err = await resp.json().catch(() => null);
      if (err?.detail && typeof err.detail === "object" && err.detail.message) {
        setValidationError(err.detail as ValidationFailureDetail);
      } else {
        setValidationError({
          valid: false,
          reason_code: "VALIDATION_REFUSED",
          message:
            typeof err?.detail === "string"
              ? err.detail
              : "Ce créneau ne peut pas être retenu.",
          conflict_details: {},
          suggested_slots: [],
        });
      }
      setAddModalOpen(false);
      return false;
    }

    const created: ItineraryItemView = await resp.json();
    setSelectedDayDate(created.local_visit_date);
    setAddModalOpen(false);
    await refreshSchedule();
    notify({
      title: "Visite planifiée",
      description: `${created.place_name} le ${formatFullDateHuman(created.local_visit_date)} à ${created.local_start_time}.`,
      tone: "success",
    });
    return true;
  }

  async function handleMoveOrUpdateVisit(
    item: ItineraryItemView,
    newDate: string,
    newStartTime: string
  ) {
    setValidationError(null);
    setPendingContextPlaceId(item.place_id);
    setPendingContextDuration(item.duration_minutes);

    const resp = await fetch(`${apiBase}/api/v1/itinerary/items/${item.id}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        visit_date: newDate,
        local_start_time: newStartTime,
        duration_minutes: item.duration_minutes,
        transit_mode: item.transit_mode_to_next || "WALKING",
      }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => null);
      if (err?.detail && typeof err.detail === "object" && err.detail.message) {
        setValidationError(err.detail as ValidationFailureDetail);
      }
      return;
    }

    setSelectedDayDate(newDate);
    await refreshSchedule();
    notify({
      title: "Horaire mis à jour",
      description: `${item.place_name} déplacé à ${newStartTime}.`,
      tone: "success",
    });
  }

  async function handleDeleteVisit(itemId: string) {
    const resp = await fetch(`${apiBase}/api/v1/itinerary/items/${itemId}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (resp.ok || resp.status === 204) {
      await refreshSchedule();
      notify({
        title: "Visite retirée",
        description: "Votre programme du jour a été mis à jour.",
        tone: "info",
      });
    }
  }

  // Étape 4.1 — Accepter ou refuser en 1 clic une suggestion météo
  async function handleAcceptWeatherOption(
    itemId: string,
    opt: WeatherAdaptationOption
  ) {
    if (!trip?.id) return;
    setWeatherActionLoadingId(itemId);
    try {
      const resp = await fetch(
        `${apiBase}/api/v1/itinerary/trip/${trip.id}/weather/alerts/${itemId}/accept`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            replacement_place_id: opt.replacement_place_id,
            visit_date: opt.visit_date,
            local_start_time: opt.local_start_time,
            duration_minutes: opt.duration_minutes,
            transit_mode: "WALKING",
          }),
        }
      );
      if (resp.ok) {
        setSelectedDayDate(opt.visit_date);
        await refreshSchedule();
        notify({
          title: "Visite adaptée à la météo",
          description: `${opt.replacement_place_name} planifié le ${formatFullDateHuman(opt.visit_date)} à ${opt.local_start_time}.`,
          tone: "success",
        });
      }
    } finally {
      setWeatherActionLoadingId("");
    }
  }

  async function handleRejectWeatherAlert(itemId: string) {
    if (!trip?.id) return;
    setWeatherActionLoadingId(itemId);
    try {
      const resp = await fetch(
        `${apiBase}/api/v1/itinerary/trip/${trip.id}/weather/alerts/${itemId}/reject`,
        {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      if (resp.ok) {
        await refreshSchedule();
        notify({
          title: "Visite conservée",
          description: "Votre visite en extérieur reste programmée telle quelle.",
          tone: "info",
        });
      }
    } finally {
      setWeatherActionLoadingId("");
    }
  }

  // Étape 4.2 — Générer un brouillon d'itinéraire IA (sans rien enregistrer)
  function toggleAiTaste(code: string) {
    setAiTastes((prev) => {
      if (prev.includes(code)) {
        return prev.length > 1 ? prev.filter((item) => item !== code) : prev;
      }
      return [...prev, code];
    });
  }

  async function handleGenerateAiDraft(e: React.FormEvent) {
    e.preventDefault();
    if (!trip?.id) return;
    setAiGenerating(true);
    setAiErrorMsg("");
    try {
      const resp = await fetch(
        `${apiBase}/api/v1/itinerary/trip/${trip.id}/ai-generate`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            budget_eur: Math.max(100, Number(aiBudget) || 1500),
            pace: aiPace,
            tastes: aiTastes,
          }),
        }
      );
      if (!resp.ok) {
        const err = await resp.json().catch(() => null);
        const msg =
          typeof err?.detail?.message === "string"
            ? err.detail.message
            : typeof err?.detail === "string"
            ? err.detail
            : "Impossible de générer le brouillon d'itinéraire pour le moment.";
        setAiErrorMsg(msg);
        return;
      }
      const draftPayload: AIGenerateDraftPayload = await resp.json();
      setAiDraft(draftPayload);
      setAiModalOpen(false);
    } finally {
      setAiGenerating(false);
    }
  }

  async function handleApplyAiDraft() {
    if (!trip?.id || !aiDraft) return;
    setAiApplying(true);
    try {
      const resp = await fetch(
        `${apiBase}/api/v1/itinerary/trip/${trip.id}/ai-apply`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            replace_existing: true,
            draft_items: aiDraft.draft_items.map((item) => ({
              place_id: item.place_id,
              visit_date: item.visit_date,
              local_start_time: item.local_start_time,
              duration_minutes: item.duration_minutes,
              transit_mode: item.transit_mode || "WALKING",
            })),
          }),
        }
      );
      if (resp.ok) {
        const firstDate = aiDraft.draft_items[0]?.visit_date;
        setAiDraft(null);
        if (firstDate) setSelectedDayDate(firstDate);
        await refreshSchedule();
        notify({
          title: "Programme IA enregistré",
          description:
            "Votre brouillon a été validé, enregistré et synchronisé avec Google Agenda.",
          tone: "success",
        });
      }
    } finally {
      setAiApplying(false);
    }
  }

  // Étape 4.3 — Envoyer un message au chat et confirmer / refuser une action proposée
  async function handleSendChatMessage(customText?: string) {
    const content = (customText ?? chatInput).trim();
    if (!trip?.id || !content || chatSending) return;
    if (!customText) setChatInput("");
    setChatSending(true);
    try {
      const resp = await fetch(`${apiBase}/api/v1/itinerary/trip/${trip.id}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ message: content }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setChatMessages(data.messages || []);
      }
    } finally {
      setChatSending(false);
    }
  }

  async function handleConfirmChatAction(
    messageId: string,
    overrideDate?: string,
    overrideStartTime?: string
  ) {
    if (!trip?.id) return;
    setChatConfirmingId(messageId);
    try {
      const qs = new URLSearchParams();
      if (overrideDate) qs.set("override_visit_date", overrideDate);
      if (overrideStartTime) qs.set("override_local_start_time", overrideStartTime);
      const querySuffix = qs.toString() ? `?${qs.toString()}` : "";
      const resp = await fetch(
        `${apiBase}/api/v1/itinerary/trip/${trip.id}/chat/${messageId}/confirm${querySuffix}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            visit_date: overrideDate || null,
            local_start_time: overrideStartTime || null,
          }),
        }
      );
      if (resp.ok) {
        await refreshChatHistory(trip.id);
        await refreshSchedule();
        notify({
          title: "Modification appliquée",
          description: "La proposition de l'assistant a été confirmée et enregistrée.",
          tone: "success",
        });
      } else {
        const err = await resp.json().catch(() => null);
        notify({
          title: "Créneau indisponible",
          description:
            err?.detail?.message ||
            "Choisissez l'un des créneaux libres suggérés pour confirmer.",
          tone: "warning",
        });
      }
    } finally {
      setChatConfirmingId("");
    }
  }

  async function handleRejectChatAction(messageId: string) {
    if (!trip?.id) return;
    setChatConfirmingId(messageId);
    try {
      const resp = await fetch(
        `${apiBase}/api/v1/itinerary/trip/${trip.id}/chat/${messageId}/reject`,
        {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      if (resp.ok) {
        await refreshChatHistory(trip.id);
        notify({
          title: "Proposition refusée",
          description: "Aucune modification n'a été apportée à votre programme.",
          tone: "info",
        });
      }
    } finally {
      setChatConfirmingId("");
    }
  }

  async function handleResetChatConversation() {
    if (!trip?.id) return;
    setChatSending(true);
    try {
      const resp = await fetch(
        `${apiBase}/api/v1/itinerary/trip/${trip.id}/chat`,
        {
          method: "DELETE",
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      if (resp.ok) {
        const data: ChatConversationPayload = await resp.json();
        setChatMessages(data.messages || []);
        setChatInput("");
        notify({
          title: "Nouvelle conversation",
          description: "L'historique de la discussion a été réinitialisé.",
          tone: "info",
        });
      }
    } finally {
      setChatSending(false);
    }
  }

  async function handlePreviewOptimization() {
    if (!trip?.id) return;
    setOptimizing(true);
    setValidationError(null);
    try {
      const placeIds =
        places.length > 0
          ? places.slice(0, 5).map((p) => p.id)
          : schedule?.items.map((i) => i.place_id) || [];

      const resp = await fetch(`${apiBase}/api/v1/itinerary/optimize/preview`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          trip_id: trip.id,
          place_ids: placeIds,
          preferred_start_hour: 9,
          max_visits_per_day: 3,
        }),
      });
      if (resp.ok) {
        const preview: OptimizationPreviewPayload = await resp.json();
        setOptimizationPreview(preview);
      } else {
        const err = await resp.json().catch(() => null);
        notify({
          title: "Optimisation indisponible",
          description:
            typeof err?.detail === "string"
              ? err.detail
              : "Sélectionnez d'abord des lieux à visiter.",
          tone: "warning",
        });
      }
    } finally {
      setOptimizing(false);
    }
  }

  async function handleApplyOptimization() {
    if (!trip?.id || !optimizationPreview) return;
    setOptimizing(true);
    try {
      const resp = await fetch(`${apiBase}/api/v1/itinerary/optimize/apply`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          trip_id: trip.id,
          replace_existing: true,
          proposed_items: optimizationPreview.proposed_items.map((p) => ({
            place_id: p.place_id,
            visit_date: p.visit_date,
            local_start_time: p.local_start_time,
            duration_minutes: p.duration_minutes,
            transit_mode: p.transit_mode_to_next || "WALKING",
          })),
        }),
      });
      if (resp.ok) {
        setOptimizationPreview(null);
        await refreshSchedule();
        notify({
          title: "Programme optimisé enregistré",
          description: "Vos visites ont été réorganisées pour limiter les temps de trajet.",
          tone: "success",
        });
      }
    } finally {
      setOptimizing(false);
    }
  }

  function shiftTimeMinutes(hhmm: string, deltaMinutes: number): string {
    const [hStr, mStr] = hhmm.split(":");
    const total = Math.max(
      8 * 60,
      Math.min(20 * 60, Number(hStr) * 60 + Number(mStr) + deltaMinutes)
    );
    const nh = String(Math.floor(total / 60)).padStart(2, "0");
    const nm = String(total % 60).padStart(2, "0");
    return `${nh}:${nm}`;
  }

  const routingSourceBadgeLabel =
    schedule?.routing_source_label || "Temps estimé";

  const lastAssistantMsg =
    [...chatMessages].reverse().find((m) => m.role !== "user") || null;

  const pendingChatProposalMsg =
    lastAssistantMsg &&
    lastAssistantMsg.proposed_action &&
    lastAssistantMsg.action_status === "PENDING_CONFIRMATION"
      ? lastAssistantMsg
      : null;

  return (
    <div
      className={`px-4 py-6 space-y-5 pb-24 transition-all ${
        chatOpen
          ? "mx-auto max-w-6xl xl:max-w-none xl:mx-0 xl:mr-[396px] xl:pl-6 xl:pr-4"
          : "mx-auto max-w-6xl"
      }`}
      data-testid="itinerary-screen"
    >
      {/* En-tête Mon programme :
          - En colonne (titre pleine largeur, boutons dessous alignés qui passent à la ligne proprement)
          - Badges sur une seule ligne, aucune coupure de mot dans les titres */}
      <div
        className="flex flex-col items-start gap-3.5 w-full"
        data-testid="itinerary-header"
      >
        <div className="w-full min-w-0">
          <div
            className="flex flex-nowrap items-center gap-1.5 sm:gap-2 mb-2"
            data-testid="itinerary-header-badges"
          >
            <Badge
              variant="brand"
              className="whitespace-nowrap shrink-0 px-2 py-0.5 text-[11px] sm:px-2.5 sm:text-caption"
            >
              Agenda jour par jour • {cityLabel}
            </Badge>
            <Badge
              data-testid="routing-mode-badge"
              className="whitespace-nowrap shrink-0 px-2 py-0.5 text-[11px] sm:px-2.5 sm:text-caption"
            >
              Trajets : {routingSourceBadgeLabel}
            </Badge>
          </div>
          <h1
            data-testid="itinerary-page-title"
            className="text-h1 text-ink w-full break-normal [word-break:normal] [overflow-wrap:normal] hyphens-none"
          >
            Mon programme à {cityLabel}
          </h1>
          <p className="text-body text-ink-secondary mt-1">
            Un jour à la fois, avec prévisions météo, itinéraire sur mesure et temps de déplacement.
          </p>
        </div>

        <div
          className="flex flex-wrap items-center gap-2"
          data-testid="itinerary-header-actions"
        >
          <Button
            type="button"
            variant="secondary"
            size="md"
            className="whitespace-nowrap shrink-0"
            data-testid="open-ai-generator-modal-btn"
            onClick={() => {
              setAiErrorMsg("");
              setAiModalOpen(true);
            }}
          >
            <Wand2 className="h-4 w-4 text-brand-700 shrink-0" />
            <span>Génère mon programme</span>
          </Button>

          <Button
            type="button"
            variant="secondary"
            size="md"
            className="whitespace-nowrap shrink-0"
            disabled={optimizing}
            data-testid="optimize-itinerary-btn"
            onClick={handlePreviewOptimization}
          >
            <Sparkles className="h-4 w-4 text-brand-700 shrink-0" />
            <span>
              {optimizing ? "Calcul en cours..." : "Optimiser mon programme"}
            </span>
          </Button>

          <Button
            type="button"
            variant="primary"
            size="md"
            className="whitespace-nowrap shrink-0"
            data-testid="open-schedule-visit-modal-btn"
            onClick={() => {
              setVisitDate(selectedDayDate || tripDays[0] || "2026-11-11");
              setAddModalOpen(true);
            }}
          >
            <Plus className="h-4 w-4 shrink-0" />
            <span>Planifier une visite</span>
          </Button>
        </div>
      </div>

      {/* Puces horizontales des jours du séjour AVEC météo par jour (bande défilante horizontale sans coupure) */}
      <div
        id="itinerary-day-pills"
        className="flex flex-nowrap items-stretch gap-2 overflow-x-auto no-scrollbar py-1 w-full max-w-full"
        role="tablist"
        aria-label="Jours du séjour"
        data-testid="itinerary-day-pills"
      >
        {tripDays.map((dayStr, index) => {
          const isSelected = dayStr === selectedDayDate;
          const countForDay =
            schedule?.days.find((d) => d.visit_date === dayStr)?.items.length || 0;
          const dayWeather = weatherByDate[dayStr];

          return (
            <button
              key={dayStr}
              type="button"
              role="tab"
              aria-selected={isSelected}
              data-testid={`day-pill-${index}`}
              onClick={() => setSelectedDayDate(dayStr)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                if (draggedVisit && draggedVisit.local_visit_date !== dayStr) {
                  handleMoveOrUpdateVisit(
                    draggedVisit,
                    dayStr,
                    draggedVisit.local_start_time
                  );
                  setDraggedVisit(null);
                }
              }}
              className={`flex shrink-0 flex-col items-start justify-between gap-1 rounded-card px-3.5 py-2 text-[12px] font-semibold whitespace-nowrap transition-all ${
                isSelected
                  ? "bg-brand-700 text-white shadow-soft"
                  : "bg-canvas-card border border-border text-ink-secondary hover:text-ink"
              }`}
            >
              <div className="flex items-center gap-1.5 whitespace-nowrap">
                <span>{formatDayPillHuman(dayStr, index)}</span>
                {countForDay > 0 && (
                  <span
                    className={`inline-flex h-4 min-w-[18px] items-center justify-center rounded-full px-1 text-[10px] font-bold shrink-0 ${
                      isSelected
                        ? "bg-white/20 text-white"
                        : "bg-brand-50 text-brand-800"
                    }`}
                  >
                    {countForDay}
                  </span>
                )}
              </div>

              <div
                className={`inline-flex items-center gap-1 text-[11px] font-medium whitespace-nowrap ${
                  isSelected ? "text-white/90" : "text-ink-muted"
                }`}
                data-testid={`day-pill-weather-${index}`}
              >
                {renderWeatherIcon(dayWeather?.condition_code, isSelected)}
                <span>
                  {dayWeather ? dayWeather.badge_label : "Prévision non disponible"}
                </span>
              </div>
            </button>
          );
        })}
      </div>

      {/* Étape 4.1 — Alerte Pluie / Orage sur visite extérieure avec suggestion validée en 1 clic */}
      {weatherData?.alerts && weatherData.alerts.length > 0 && (
        <div className="space-y-3" data-testid="weather-alerts-container">
          {weatherData.alerts.map((alert) => {
            const shortAlertTitle = `${
              alert.weather_condition_code === "STORM"
                ? "Orage prévu le"
                : "Pluie prévue le"
            } ${formatFullDateHuman(alert.visit_date)}`;

            return (
              <Card
                key={alert.item_id}
                data-testid="weather-visit-alert-card"
                className="p-3.5 border-amber-300 bg-feedback-warningBg space-y-2.5"
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div className="space-y-0.5">
                    <div
                      className="inline-flex items-center gap-1.5 text-body font-semibold text-ink"
                      data-testid="weather-alert-title"
                    >
                      <CloudRain className="h-4 w-4 text-feedback-warning shrink-0" />
                      <span>{shortAlertTitle}</span>
                    </div>
                    <p
                      className="text-caption text-ink-secondary"
                      data-testid="weather-alert-message"
                    >
                      {alert.alert_message_fr}
                    </p>
                  </div>

                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    className="shrink-0 whitespace-nowrap bg-white"
                    disabled={weatherActionLoadingId === alert.item_id}
                    data-testid="weather-reject-alert-btn"
                    onClick={() => handleRejectWeatherAlert(alert.item_id)}
                  >
                    Conserver ma visite
                  </Button>
                </div>

                {alert.options.length > 0 && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                    {alert.options.slice(0, 2).map((opt, optIdx) => (
                      <div
                        key={opt.option_id}
                        className="rounded-card bg-white border border-amber-200 p-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 shadow-soft"
                      >
                        <div className="space-y-0.5 min-w-0">
                          <div className="text-[11px] font-semibold text-brand-800">
                            {opt.suggestion_type === "INDOOR_PLACE"
                              ? "Option 1 • Lieu en intérieur"
                              : "Option 2 • Autre créneau"}
                          </div>
                          <div className="text-caption font-semibold text-ink truncate">
                            {opt.replacement_place_name}
                          </div>
                          <div className="text-[11px] text-ink-secondary">
                            {formatFullDateHuman(opt.visit_date)} à {opt.local_start_time}
                          </div>
                        </div>

                        <Button
                          type="button"
                          size="sm"
                          className="shrink-0 whitespace-nowrap"
                          title={opt.label_fr}
                          disabled={weatherActionLoadingId === alert.item_id}
                          data-testid={`weather-accept-option-btn-${optIdx}`}
                          onClick={() => handleAcceptWeatherOption(alert.item_id, opt)}
                        >
                          <CheckCircle2 className="h-4 w-4" />
                          <span>
                            {opt.suggestion_type === "INDOOR_PLACE"
                              ? "Remplacer par ce lieu"
                              : "Déplacer ma visite"}
                          </span>
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}

      {/* Étape 4.2 — Aperçu en brouillon de l'Itinéraire IA (non enregistré tant que non validé) */}
      {aiDraft && (
        <Card
          data-testid="ai-draft-preview-card"
          className="p-5 border-brand-300 bg-brand-50/40 space-y-3.5"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="warning" data-testid="ai-draft-unpersisted-badge">
                  Brouillon non enregistré
                </Badge>
                <Badge variant="brand">
                  Trajets : {aiDraft.routing_source_label}
                </Badge>
                <Badge>
                  {aiDraft.draft_items.length} visites sur {new Set(aiDraft.draft_items.map((s) => s.visit_date)).size} jours
                </Badge>
              </div>
              <h2 className="text-h2 text-ink">
                Proposition d'itinéraire sur mesure
              </h2>
              <p className="text-caption text-ink-secondary">
                {aiDraft.summary_fr} Rien n'est enregistré ni synchronisé avec votre agenda avant votre validation.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                data-testid="ai-discard-draft-btn"
                onClick={() => setAiDraft(null)}
              >
                Fermer le brouillon
              </Button>
              <Button
                type="button"
                size="sm"
                disabled={aiApplying}
                data-testid="ai-apply-draft-btn"
                onClick={handleApplyAiDraft}
              >
                {aiApplying
                  ? "Enregistrement..."
                  : "Valider et enregistrer ce programme"}
              </Button>
            </div>
          </div>

          {aiDraft.limited_places_notice_fr && (
            <div
              className="rounded-card bg-white border border-amber-300 px-3.5 py-2.5 text-caption font-medium text-ink"
              data-testid="ai-draft-limited-places-notice"
            >
              {aiDraft.limited_places_notice_fr}
            </div>
          )}

          {aiDraft.adjustments_fr?.length > 0 && (
            <div
              className="rounded-card bg-white border border-border p-3 space-y-0.5"
              data-testid="ai-draft-adjustments"
            >
              <div className="text-caption font-semibold text-ink">
                Ajustements pour votre confort :
              </div>
              {aiDraft.adjustments_fr.map((note, idx) => (
                <div key={idx} className="text-caption text-ink-secondary">
                  • {note}
                </div>
              ))}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
            {aiDraft.draft_items.map((slot, idx) => (
              <div
                key={`${slot.place_id}-${idx}`}
                data-testid={`ai-draft-slot-${idx}`}
                className="rounded-card bg-white border border-border p-3 space-y-1 shadow-soft"
              >
                <div className="flex items-center justify-between gap-1.5">
                  <span className="text-[11px] font-semibold text-brand-800">
                    {slot.visit_date_label_fr || formatFullDateHuman(slot.visit_date)} •{" "}
                    {slot.local_start_time} → {slot.local_end_time}
                  </span>
                  {slot.transit_from_prev_min > 0 && (
                    <Badge data-testid={`ai-draft-slot-transit-${idx}`}>
                      {slot.transit_label_fr ||
                        `Trajet : ~${slot.transit_from_prev_min} min`}
                    </Badge>
                  )}
                </div>
                <div className="text-caption font-semibold text-ink">
                  {slot.place_name}
                </div>
                <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-ink-secondary">
                  <span>{slot.is_outdoor ? "En plein air" : "En intérieur"}</span>
                  <span>•</span>
                  <span>Météo : {slot.weather_summary}</span>
                  {slot.weather_adapted && (
                    <Badge variant="success">Adapté à la météo</Badge>
                  )}
                </div>
                {slot.adjustment_note_fr && (
                  <div
                    className="text-[11px] font-medium text-brand-800 bg-brand-50 rounded-md px-2 py-0.5 border border-brand-200"
                    data-testid={`ai-draft-slot-adjustment-${idx}`}
                  >
                    {slot.adjustment_note_fr}
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Bandeau d'erreur en français simple avec créneaux suggérés cliquables */}
      {validationError && (
        <Card
          data-testid="itinerary-validation-alert"
          className="p-5 border-amber-300 bg-feedback-warningBg space-y-3"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1">
              <div className="text-caption font-bold uppercase tracking-wide text-feedback-warning">
                Créneau indisponible
              </div>
              <p
                className="text-body font-medium text-ink"
                data-testid="itinerary-validation-message"
              >
                {validationError.message}
              </p>
            </div>
            <button
              type="button"
              onClick={() => setValidationError(null)}
              className="text-caption text-ink-muted hover:text-ink"
            >
              Fermer
            </button>
          </div>

          {validationError.suggested_slots?.length > 0 && (
            <div className="space-y-2 pt-1">
              <div className="text-caption font-semibold text-ink-secondary">
                Créneaux libres suggérés (cliquez pour planifier directement) :
              </div>
              <div
                className="flex flex-wrap gap-2"
                data-testid="suggested-slots-list"
              >
                {validationError.suggested_slots.map((slot, idx) => (
                  <button
                    key={`${slot.local_date}-${slot.local_start_time}-${idx}`}
                    type="button"
                    data-testid={`suggested-slot-btn-${idx}`}
                    onClick={() =>
                      scheduleVisitRequest(
                        pendingContextPlaceId || selectedPlaceId || places[0]?.id,
                        slot.local_date,
                        slot.local_start_time,
                        pendingContextDuration || 90
                      )
                    }
                    className="inline-flex items-center gap-2 rounded-card bg-white border border-brand-300 px-3.5 py-2 text-caption font-semibold text-brand-800 shadow-soft hover:bg-brand-50 transition-colors"
                  >
                    <CalendarIcon className="h-3.5 w-3.5 text-brand-700" />
                    <span>
                      {formatFullDateHuman(slot.local_date)} • {slot.local_start_time} → {slot.local_end_time}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </Card>
      )}

      {/* Vue chronologique verticale du jour choisi */}
      <Card className="p-6 space-y-5" data-testid="single-day-timeline-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-4">
          <div className="min-w-0">
            <h2 className="text-h2 text-ink break-normal [word-break:normal] [overflow-wrap:normal] hyphens-none">
              {selectedDayDate ? formatFullDateHuman(selectedDayDate) : "Journée sélectionnée"}
            </h2>
            <p className="text-caption text-ink-secondary mt-0.5">
              Glissez une visite sur une autre heure ou sur la puce d'un autre jour pour la déplacer.
            </p>
          </div>
          <div className="flex flex-nowrap items-center gap-2 shrink-0">
            <Badge
              data-testid="selected-day-weather-badge"
              className="whitespace-nowrap shrink-0"
            >
              {selectedDayWeather
                ? selectedDayWeather.badge_label
                : "Prévision non disponible"}
            </Badge>
            <Badge variant="brand" className="whitespace-nowrap shrink-0">
              {currentDayItems.length}{" "}
              {currentDayItems.length > 1 ? "visites prévues" : "visite prévue"}
            </Badge>
          </div>
        </div>

        {loading ? (
          <div className="space-y-4">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : currentDayItems.length === 0 ? (
          <div
            className="py-10 text-center space-y-4"
            data-testid="empty-day-timeline"
          >
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-canvas-subtle text-brand-700">
              <CalendarIcon className="h-6 w-6" />
            </div>
            <div className="space-y-1">
              <h3 className="text-body font-semibold text-ink break-normal [word-break:normal] [overflow-wrap:normal] hyphens-none">
                Aucune visite prévue sur cette journée
              </h3>
              <p className="text-caption text-ink-secondary max-w-md mx-auto">
                Ajoutez une activité depuis la galerie, générez un programme sur mesure ou planifiez directement un créneau.
              </p>
            </div>
            <div className="flex flex-wrap justify-center gap-3">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => navigate("/activities")}
              >
                Explorer les lieux à visiter
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={() => {
                  setVisitDate(selectedDayDate);
                  setAddModalOpen(true);
                }}
              >
                <Plus className="h-4 w-4" />
                <span>Ajouter une visite ce jour</span>
              </Button>
            </div>
          </div>
        ) : (
          <div
            className="relative pl-6 border-l-2 border-brand-200 space-y-6"
            data-testid="vertical-day-timeline"
          >
            {currentDayItems.map((item, idx) => {
              const outdoorFlag = item.is_outdoor ?? item.place_is_outdoor ?? false;
              const transitLabel =
                item.transit_source_label || routingSourceBadgeLabel;

              return (
                <div key={item.id} className="space-y-3">
                  <div
                    draggable
                    onDragStart={() => setDraggedVisit(item)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => {
                      e.preventDefault();
                      if (draggedVisit && draggedVisit.id !== item.id) {
                        handleMoveOrUpdateVisit(
                          draggedVisit,
                          selectedDayDate,
                          item.local_start_time
                        );
                        setDraggedVisit(null);
                      }
                    }}
                    data-testid={`timeline-visit-card-${idx}`}
                    className="relative rounded-card border border-border bg-canvas-subtle p-4 shadow-soft hover:border-brand-600 transition-all cursor-grab active:cursor-grabbing"
                  >
                    {/* Point sur la ligne chronologique */}
                    <div className="absolute -left-[31px] top-6 h-3.5 w-3.5 rounded-full border-2 border-white bg-brand-700" />

                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                      <div className="space-y-1 min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="inline-flex items-center gap-1 rounded-md bg-brand-700 px-2.5 py-0.5 text-caption font-bold text-white whitespace-nowrap shrink-0">
                            <Clock className="h-3 w-3 shrink-0" />
                            {item.local_start_time} → {item.local_end_time}
                          </span>
                          <Badge className="whitespace-nowrap shrink-0">
                            {categoryLabelFr(item.place_category)}
                          </Badge>
                          <Badge variant="success" className="whitespace-nowrap shrink-0">
                            <CheckCircle2 className="h-3 w-3 mr-1 shrink-0" />
                            Ajouté à Google Agenda
                          </Badge>
                        </div>

                        <div className="flex items-center gap-2 pt-1">
                          <GripVertical className="h-4 w-4 text-ink-muted shrink-0" />
                          <h3 className="text-h2 text-ink break-normal [word-break:normal] [overflow-wrap:normal] hyphens-none">
                            {item.place_name}
                          </h3>
                        </div>

                        <div className="text-caption text-ink-secondary pl-6">
                          Durée prévue : {item.duration_minutes} minutes •{" "}
                          {outdoorFlag ? "En plein air" : "En intérieur"}
                        </div>
                      </div>

                      {/* Actions rapides de décalage horaire ou suppression */}
                      <div className="flex items-center gap-1.5 shrink-0 self-end sm:self-center">
                        <Button
                          type="button"
                          variant="secondary"
                          size="sm"
                          data-testid={`shift-earlier-btn-${idx}`}
                          onClick={() =>
                            handleMoveOrUpdateVisit(
                              item,
                              item.local_visit_date,
                              shiftTimeMinutes(item.local_start_time, -30)
                            )
                          }
                        >
                          -30 min
                        </Button>
                        <Button
                          type="button"
                          variant="secondary"
                          size="sm"
                          data-testid={`shift-later-btn-${idx}`}
                          onClick={() =>
                            handleMoveOrUpdateVisit(
                              item,
                              item.local_visit_date,
                              shiftTimeMinutes(item.local_start_time, 30)
                            )
                          }
                        >
                          +30 min
                        </Button>
                        <button
                          type="button"
                          aria-label={`Supprimer ${item.place_name}`}
                          data-testid={`delete-visit-btn-${idx}`}
                          onClick={() => handleDeleteVisit(item.id)}
                          className="rounded-md p-2 text-ink-muted hover:bg-feedback-dangerBg hover:text-feedback-danger transition-colors"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Temps de trajet vers la visite suivante (Temps réel ou Temps estimé) */}
                  {idx < currentDayItems.length - 1 && (
                    <div
                      className="inline-flex flex-wrap items-center gap-2 rounded-full bg-brand-50 border border-brand-200 px-3.5 py-1.5 text-caption font-medium text-brand-800"
                      data-testid={`transit-connector-${idx}`}
                    >
                      {item.transit_mode_to_next === "WALKING" ? (
                        <Footprints className="h-3.5 w-3.5" />
                      ) : item.transit_mode_to_next === "CAR" ? (
                        <Car className="h-3.5 w-3.5" />
                      ) : (
                        <Train className="h-3.5 w-3.5" />
                      )}
                      <span>
                        {item.transit_duration_to_next_min || 15} min de trajet jusqu'à
                        l'étape suivante
                      </span>
                      <span
                        className="rounded-full bg-white px-2 py-0.5 text-[11px] font-semibold text-brand-900 border border-brand-200"
                        data-testid={`transit-source-badge-${idx}`}
                      >
                        {transitLabel}
                      </span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* Continuer vers le récapitulatif Mon voyage */}
      <div className="flex justify-start">
        <Button
          type="button"
          size="lg"
          data-testid="itinerary-go-to-trip-summary-btn"
          onClick={() => navigate("/trip")}
        >
          <span>Voir le récapitulatif de mon voyage</span>
          <ArrowRight className="h-4 w-4" />
        </Button>
      </div>

      {/* Modale Étape 4.2 — Itinéraire IA ("Génère mon programme", 3 champs max <= 4) */}
      <Modal
        open={aiModalOpen}
        onOpenChange={setAiModalOpen}
        title="Génère mon programme"
        description="Indiquez votre budget, votre rythme et vos envies. Le programme s'affichera en brouillon avant tout enregistrement."
        maxWidthClass="max-w-md"
      >
        <form
          onSubmit={handleGenerateAiDraft}
          className="space-y-4"
          data-testid="ai-generator-form"
        >
          {/* Champ 1 : Budget */}
          <div>
            <label className="block text-caption font-medium text-ink-secondary mb-1">
              Budget des activités (€)
            </label>
            <Input
              type="number"
              min={100}
              max={20000}
              step={50}
              data-testid="ai-budget-input"
              value={aiBudget}
              onChange={(e) => setAiBudget(e.target.value)}
              required
            />
          </div>

          {/* Champ 2 : Rythme */}
          <div>
            <label className="block text-caption font-medium text-ink-secondary mb-1">
              Rythme souhaité
            </label>
            <Select
              value={aiPace}
              onValueChange={(v) => setAiPace(v as "RELAX" | "NORMAL" | "INTENSE")}
              ariaLabel="Rythme souhaité"
              options={[
                { value: "RELAX", label: "Relax (1 visite par jour)" },
                { value: "NORMAL", label: "Normal (2 visites par jour)" },
                { value: "INTENSE", label: "Intense (3 visites par jour)" },
              ]}
            />
          </div>

          {/* Champ 3 : Goûts */}
          <div>
            <label className="block text-caption font-medium text-ink-secondary mb-1.5">
              Vos envies
            </label>
            <div className="flex flex-wrap gap-2" data-testid="ai-tastes-group">
              {[
                { code: "CULTURE", label: "Culture" },
                { code: "NATURE", label: "Nature" },
                { code: "FOOD", label: "Food & Gastronomie" },
                { code: "NIGHT", label: "Nuit & Soirées" },
              ].map((taste) => {
                const active = aiTastes.includes(taste.code);
                return (
                  <button
                    key={taste.code}
                    type="button"
                    data-testid={`ai-taste-pill-${taste.code}`}
                    onClick={() => toggleAiTaste(taste.code)}
                    className={`rounded-card px-3.5 py-2 text-caption font-semibold transition-all ${
                      active
                        ? "bg-brand-700 text-white shadow-soft"
                        : "bg-canvas-subtle border border-border text-ink-secondary hover:text-ink"
                    }`}
                  >
                    {taste.label}
                  </button>
                );
              })}
            </div>
          </div>

          {aiErrorMsg && (
            <div
              className="rounded-card bg-feedback-dangerBg border border-red-200 p-3 text-caption text-feedback-danger"
              data-testid="ai-generator-error"
            >
              {aiErrorMsg}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setAiModalOpen(false)}
            >
              Annuler
            </Button>
            <Button
              type="submit"
              disabled={aiGenerating}
              data-testid="submit-ai-generator-btn"
            >
              {aiGenerating ? "Génération..." : "Voir mon brouillon"}
            </Button>
          </div>
        </form>
      </Modal>

      {/* Modale d'ajout / planification directe (4 champs max) */}
      <Modal
        open={addModalOpen}
        onOpenChange={setAddModalOpen}
        title="Planifier une visite"
        description="Choisissez un lieu, un jour et une heure. La durée recommandée est proposée automatiquement."
        maxWidthClass="max-w-md"
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            scheduleVisitRequest(
              selectedPlaceId,
              visitDate || selectedDayDate,
              startTime,
              Math.max(30, Number(durationMinutes) || 90)
            );
          }}
          className="space-y-4"
          data-testid="schedule-visit-form"
        >
          <div>
            <label className="block text-caption font-medium text-ink-secondary mb-1">
              Lieu à visiter
            </label>
            <Select
              value={selectedPlaceId}
              onValueChange={handlePlaceChange}
              ariaLabel="Lieu à visiter"
              options={places.map((p) => ({
                value: p.id,
                label: `${p.name} (${p.recommended_duration_min} min)`,
              }))}
            />
          </div>

          <div>
            <label className="block text-caption font-medium text-ink-secondary mb-1">
              Date de la visite
            </label>
            <Input
              type="date"
              data-testid="schedule-date-input"
              value={visitDate}
              onChange={(e) => setVisitDate(e.target.value)}
              required
            />
          </div>

          <div>
            <label className="block text-caption font-medium text-ink-secondary mb-1">
              Heure de début
            </label>
            <Input
              type="time"
              data-testid="schedule-time-input"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              required
            />
          </div>

          <div>
            <label className="block text-caption font-medium text-ink-secondary mb-1">
              Durée (minutes)
            </label>
            <Input
              type="number"
              min={30}
              max={360}
              step={15}
              data-testid="schedule-duration-input"
              value={durationMinutes}
              onChange={(e) => setDurationMinutes(e.target.value)}
              required
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setAddModalOpen(false)}
            >
              Annuler
            </Button>
            <Button type="submit" data-testid="submit-schedule-visit-btn">
              Valider ce créneau
            </Button>
          </div>
        </form>
      </Modal>

      {/* Modale d'aperçu avant validation ("Optimiser mon programme") */}
      <Modal
        open={Boolean(optimizationPreview)}
        onOpenChange={(open) => {
          if (!open) setOptimizationPreview(null);
        }}
        title="Aperçu de votre programme optimisé"
        description="Les visites proches sont regroupées sur la même journée pour réduire vos temps de trajet. Rien n'est enregistré tant que vous ne validez pas."
        maxWidthClass="max-w-2xl"
      >
        {optimizationPreview && (
          <div className="space-y-4" data-testid="optimization-preview-modal">
            <div className="rounded-card bg-brand-50 border border-brand-200 p-4 text-caption text-brand-900">
              {optimizationPreview.summary_message}
            </div>

            <div className="max-h-80 overflow-y-auto space-y-2.5 pr-1">
              {optimizationPreview.proposed_items.map((slot, idx) => (
                <div
                  key={`${slot.place_id}-${idx}`}
                  className="rounded-card border border-border bg-canvas-subtle p-3.5 flex items-center justify-between gap-3"
                >
                  <div>
                    <div className="text-caption font-semibold text-brand-800">
                      Jour {slot.day_number} ({formatFullDateHuman(slot.visit_date)}) •{" "}
                      {slot.local_start_time} → {slot.local_end_time}
                    </div>
                    <div className="text-body font-semibold text-ink">
                      {slot.place_name}
                    </div>
                  </div>
                  <Badge>
                    {slot.duration_minutes} min
                  </Badge>
                </div>
              ))}
            </div>

            <div className="flex justify-end gap-3 pt-3 border-t border-border">
              <Button
                type="button"
                variant="secondary"
                onClick={() => setOptimizationPreview(null)}
              >
                Conserver mon programme actuel
              </Button>
              <Button
                type="button"
                disabled={optimizing}
                data-testid="apply-optimization-btn"
                onClick={handleApplyOptimization}
              >
                Valider et appliquer ce programme
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Étape 4.3 — Assistant de chat :
          - Fermé : bulle flottante entièrement visible avec 16 px de marge
          - Ouvert : plein écran sur mobile (< lg), panneau latéral ancré à droite sous l'en-tête sur grand écran (lg:)
          - Boutons Confirmer / Refuser épinglés au-dessus du champ de saisie (hors zone défilante) */}
      {!chatOpen ? (
        <div
          className="fixed bottom-4 right-4 z-40 !mt-0"
          style={{ bottom: "16px", right: "16px", marginTop: 0 }}
        >
          <Button
            type="button"
            size="lg"
            data-testid="floating-chat-bubble-btn"
            onClick={() => setChatOpen(true)}
            className="rounded-full shadow-cardHover px-5 py-3"
          >
            <MessageCircle className="h-5 w-5" />
            <span>Assistant voyage</span>
          </Button>
        </div>
      ) : (
        <>
          <div
            data-testid="chat-drawer-backdrop"
            onClick={() => setChatOpen(false)}
            style={{ marginTop: 0 }}
            className="!mt-0 fixed inset-0 z-40 bg-ink/20 hidden md:block xl:hidden"
            aria-hidden="true"
          />
          <aside
            aria-label={`Assistant ${cityLabel}`}
            data-testid="floating-chat-panel"
            style={{ marginTop: 0 }}
            className="!mt-0 fixed inset-0 z-50 w-full h-full md:inset-y-0 md:left-auto md:right-0 md:w-[380px] md:border-l md:border-border xl:top-16 xl:bottom-0 xl:left-auto xl:right-0 xl:z-40 xl:w-[380px] xl:h-[calc(100vh-4rem)] flex flex-col bg-canvas-card shadow-cardHover overflow-hidden"
          >
          <div className="shrink-0 flex items-center justify-between gap-2 bg-brand-700 px-4 py-3 text-white">
            <div className="flex items-center gap-2 min-w-0">
              <MessageCircle className="h-4 w-4 shrink-0" />
              <div className="min-w-0">
                <div className="text-caption font-bold truncate">
                  Assistant {cityLabel}
                </div>
                <div className="text-[11px] text-white/80 truncate">
                  Programme, météo, budget • Confirmation requise
                </div>
              </div>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              <button
                type="button"
                data-testid="new-chat-conversation-btn"
                disabled={chatSending}
                onClick={handleResetChatConversation}
                className="rounded-md border border-white/25 bg-white/10 px-2 py-1 text-[11px] font-medium text-white hover:bg-white/20 disabled:opacity-50"
              >
                Nouvelle conversation
              </button>
              <button
                type="button"
                aria-label="Fermer l'assistant"
                data-testid="close-chat-panel-btn"
                onClick={() => setChatOpen(false)}
                className="rounded-md p-1 text-white/80 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Zone de messages défilante (les boutons Confirmer / Refuser n'y sont jamais enfermés) */}
          <div
            className="flex-1 overflow-y-auto p-4 space-y-3 bg-canvas"
            data-testid="chat-messages-list"
          >
            {chatMessages.length === 0 ? (
              <div className="space-y-2 text-caption text-ink-secondary">
                <p>
                  Bonjour ! Je connais votre vol, votre budget, la météo et votre programme à {cityLabel}.
                </p>
                <div className="flex flex-wrap gap-1.5 pt-1">
                  <button
                    type="button"
                    data-testid="chat-quick-weather-btn"
                    onClick={() =>
                      handleSendChatMessage("Quel est le point météo et budget de mon séjour ?")
                    }
                    className="rounded-card bg-white border border-border px-2.5 py-1.5 text-[11px] font-medium text-ink hover:border-brand-600"
                  >
                    Météo & budget du séjour
                  </button>
                  {places[0] && (
                    <button
                      type="button"
                      data-testid="chat-quick-add-btn"
                      onClick={() =>
                        handleSendChatMessage(
                          `Ajoute ${places[0].name} mercredi à 14h`
                        )
                      }
                      className="rounded-card bg-white border border-border px-2.5 py-1.5 text-[11px] font-medium text-ink hover:border-brand-600"
                    >
                      Proposer d'ajouter {places[0].name}
                    </button>
                  )}
                </div>
              </div>
            ) : (
              chatMessages.map((msg) => (
                <div
                  key={msg.id}
                  className={`space-y-1.5 ${
                    msg.role === "user" ? "text-right" : "text-left"
                  }`}
                >
                  <div
                    className={`inline-block rounded-card px-3.5 py-2.5 text-caption whitespace-pre-line ${
                      msg.role === "user"
                        ? "bg-brand-700 text-white"
                        : "bg-white border border-border text-ink"
                    }`}
                  >
                    {msg.content}
                  </div>

                  {msg.action_status === "CONFIRMED" && (
                    <div className="text-[11px] font-semibold text-feedback-success">
                      ✓ Modification confirmée et appliquée
                    </div>
                  )}
                  {msg.action_status === "REJECTED" && (
                    <div className="text-[11px] text-ink-muted">
                      Proposition refusée (programme inchangé)
                    </div>
                  )}
                </div>
              ))
            )}
          </div>

          {/* Zone épinglée au-dessus du champ de saisie : Confirmer / Refuser toujours visibles */}
          {pendingChatProposalMsg && pendingChatProposalMsg.proposed_action && (
            <div
              data-testid="chat-proposed-action-card"
              className="shrink-0 border-t border-brand-200 bg-brand-50 px-4 py-3 text-left space-y-2"
            >
              <div className="text-[11px] font-bold uppercase tracking-wide text-brand-800">
                Proposition en attente de votre accord
              </div>

              {pendingChatProposalMsg.proposed_action.validated_by_engine ? (
                <>
                  <div className="text-caption font-semibold text-ink">
                    {pendingChatProposalMsg.proposed_action.place_name} •{" "}
                    {formatFullDateHuman(
                      pendingChatProposalMsg.proposed_action.visit_date
                    )}{" "}
                    à {pendingChatProposalMsg.proposed_action.local_start_time}
                  </div>
                  <div className="flex items-center gap-2 pt-0.5">
                    <Button
                      type="button"
                      size="sm"
                      disabled={chatConfirmingId === pendingChatProposalMsg.id}
                      data-testid="chat-confirm-action-btn"
                      onClick={() =>
                        handleConfirmChatAction(pendingChatProposalMsg.id)
                      }
                    >
                      Confirmer
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      disabled={chatConfirmingId === pendingChatProposalMsg.id}
                      data-testid="chat-reject-action-btn"
                      onClick={() =>
                        handleRejectChatAction(pendingChatProposalMsg.id)
                      }
                    >
                      Refuser
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  {pendingChatProposalMsg.proposed_action.suggested_slots
                    ?.length > 0 && (
                    <div className="text-caption font-semibold text-ink">
                      {pendingChatProposalMsg.proposed_action.place_name} •{" "}
                      {formatFullDateHuman(
                        pendingChatProposalMsg.proposed_action.suggested_slots[0]
                          .local_date
                      )}{" "}
                      à{" "}
                      {
                        pendingChatProposalMsg.proposed_action.suggested_slots[0]
                          .local_start_time
                      }
                    </div>
                  )}
                  <div className="flex flex-wrap items-center gap-2 pt-0.5">
                    {pendingChatProposalMsg.proposed_action.suggested_slots
                      ?.length > 0 && (
                      <Button
                        type="button"
                        size="sm"
                        disabled={chatConfirmingId === pendingChatProposalMsg.id}
                        data-testid="chat-confirm-action-btn"
                        onClick={() => {
                          const firstSlot =
                            pendingChatProposalMsg.proposed_action!
                              .suggested_slots[0];
                          handleConfirmChatAction(
                            pendingChatProposalMsg.id,
                            firstSlot.local_date,
                            firstSlot.local_start_time
                          );
                        }}
                      >
                        Confirmer
                      </Button>
                    )}
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      disabled={chatConfirmingId === pendingChatProposalMsg.id}
                      data-testid="chat-reject-action-btn"
                      onClick={() =>
                        handleRejectChatAction(pendingChatProposalMsg.id)
                      }
                    >
                      Refuser
                    </Button>
                  </div>
                </>
              )}
            </div>
          )}

          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSendChatMessage();
            }}
            className="shrink-0 flex items-center gap-2 border-t border-border bg-white p-3"
          >
            <Input
              type="text"
              placeholder="Ex: Ajoute une visite mercredi à 10h..."
              data-testid="chat-message-input"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
            />
            <Button
              type="submit"
              size="sm"
              disabled={chatSending}
              data-testid="chat-send-btn"
            >
              <Send className="h-4 w-4" />
            </Button>
          </form>
          </aside>
        </>
      )}
    </div>
  );
}

/* ============================================================================
 * 4. ÉCRAN MON VOYAGE (/trip et /transports)
 *    - Page récapitulative : vol, hébergement, programme, transports sur place
 *      avec trajet aéroport -> hébergement, documents
 * ========================================================================== */
export function MyTripSummaryScreen({
  apiBase,
  token,
  trip,
  destination,
  latestBooking,
  selectedAccommodation,
  onOpenDocumentsModal,
}: {
  apiBase: string;
  token: string;
  trip: Trip | null;
  destination: Destination | null;
  latestBooking: FlightBooking | null;
  selectedAccommodation: AccommodationItem | null;
  onOpenDocumentsModal: () => void;
}) {
  const navigate = useNavigate();
  const [schedule, setSchedule] = useState<TripItinerarySchedule | null>(null);
  const [transports, setTransports] = useState<LocalTransportsPayload | null>(null);
  const [fallbackAcc, setFallbackAcc] = useState<AccommodationItem | null>(null);

  const cityLabel = destination?.city_name || "votre destination";

  useEffect(() => {
    if (!trip?.id || !token) return;

    fetch(`${apiBase}/api/v1/itinerary/trip/${trip.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((raw) => {
        if (raw) setSchedule(normalizeSchedulePayload(raw));
      })
      .catch(() => null);

    fetch(`${apiBase}/api/v1/transports/trip/${trip.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((raw) => {
        if (raw) setTransports(raw);
      })
      .catch(() => null);

    if (!selectedAccommodation) {
      fetch(`${apiBase}/api/v1/accommodations/search?trip_id=${trip.id}&radius_km=12`)
        .then((r) => (r.ok ? r.json() : []))
        .then((list: AccommodationItem[]) => {
          if (list.length > 0) setFallbackAcc(list[0]);
        })
        .catch(() => null);
    }
  }, [trip?.id, token, selectedAccommodation]);

  const activeAccommodation = selectedAccommodation || fallbackAcc;

  return (
    <div
      className="mx-auto max-w-6xl px-4 py-8 space-y-8"
      data-testid="my-trip-screen"
    >
      {/* En-tête récapitulatif */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div>
          <Badge variant="brand" className="mb-2">
            Carnet de voyage
          </Badge>
          <h1 className="text-h1 text-ink">Mon voyage à {cityLabel}</h1>
          <p className="text-body text-ink-secondary mt-1">
            Retrouvez au même endroit votre vol, votre hébergement, votre programme, vos transports sur place et vos documents.
          </p>
        </div>

        <Button
          type="button"
          variant="secondary"
          onClick={onOpenDocumentsModal}
          data-testid="trip-open-documents-btn"
        >
          <FileText className="h-4 w-4 text-brand-700" />
          <span>Mes documents</span>
        </Button>
      </div>

      {/* Grille 2 colonnes : Vol + Hébergement */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* 1. Mon vol */}
        <Card className="p-6 flex flex-col justify-between gap-4" data-testid="trip-flight-card">
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-2 text-h2 font-semibold text-ink">
                <Plane className="h-5 w-5 text-brand-700" />
                Mon vol aller-retour
              </span>
              {latestBooking ? (
                <Badge variant="success">Réservation confirmée</Badge>
              ) : (
                <Badge>À réserver</Badge>
              )}
            </div>

            {latestBooking ? (
              <div className="rounded-card bg-canvas-subtle p-4 space-y-2">
                <div className="flex items-center justify-between text-caption text-ink-muted">
                  <span>Compagnie : {latestBooking.airline}</span>
                  <span className="font-semibold text-brand-800">
                    Référence de réservation : {latestBooking.pnr_reference}
                  </span>
                </div>
                <div className="text-body font-semibold text-ink">
                  Aller-retour vers {cityLabel}
                </div>
                <div className="text-caption text-ink-secondary">
                  Tarif réglé : {Math.round(Number(latestBooking.price_amount))} €
                </div>
              </div>
            ) : (
              <p className="text-body text-ink-secondary">
                Aucun vol sélectionné pour le moment.
              </p>
            )}
          </div>

          <div className="flex justify-end">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => navigate("/flights")}
            >
              {latestBooking ? "Voir les détails du vol" : "Choisir mon vol"}
            </Button>
          </div>
        </Card>

        {/* 2. Mon hébergement */}
        <Card className="p-6 flex flex-col justify-between gap-4" data-testid="trip-accommodation-card">
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-2 text-h2 font-semibold text-ink">
                <Building2 className="h-5 w-5 text-brand-700" />
                Mon hébergement
              </span>
              {activeAccommodation && (
                <Badge variant="brand">
                  {activeAccommodation.type === "HOTEL" ? "Hôtel" : "Airbnb"}
                </Badge>
              )}
            </div>

            {activeAccommodation ? (
              <div className="rounded-card bg-canvas-subtle p-4 space-y-1.5">
                <div className="text-body font-semibold text-ink">
                  {activeAccommodation.name}
                </div>
                <div className="text-caption text-ink-secondary">
                  {activeAccommodation.neighborhood} •{" "}
                  {Math.round(Number(activeAccommodation.price_per_night))} € / nuit
                </div>
                <div className="text-caption text-brand-700 font-medium">
                  {activeAccommodation.nearby_restaurants.length} restaurants accessibles à pied
                </div>
              </div>
            ) : (
              <p className="text-body text-ink-secondary">
                Consultez les hôtels et Airbnb disponibles dans la zone de votre séjour.
              </p>
            )}
          </div>

          <div className="flex justify-end">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => navigate("/accommodations")}
            >
              Changer d'hébergement
            </Button>
          </div>
        </Card>
      </div>

      {/* 3. Trajet Aéroport -> Hébergement & Transports sur place */}
      <Card className="p-6 space-y-5" data-testid="trip-transports-section">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-h2 text-ink flex items-center gap-2">
              <Navigation className="h-5 w-5 text-brand-700" />
              <span>Transports sur place & Trajet aéroport → hébergement</span>
            </h2>
            <p className="text-caption text-ink-secondary mt-0.5">
              Options recommandées dès votre arrivée à l'aéroport de {cityLabel} jusqu'à votre hébergement.
            </p>
          </div>
          {transports?.airport_transfer && (
            <Badge variant="brand">
              Distance : {transports.airport_transfer.distance_km} km
            </Badge>
          )}
        </div>

        {transports?.airport_transfer ? (
          <div className="space-y-4">
            <div className="rounded-card bg-brand-50 border border-brand-200 p-4 flex flex-wrap items-center justify-between gap-2">
              <div className="text-body font-medium text-brand-900">
                De <strong>{transports.airport_transfer.airport_name}</strong> vers{" "}
                <strong>
                  {activeAccommodation?.name ||
                    transports.airport_transfer.accommodation_name}
                </strong>
              </div>
              <span className="text-caption font-semibold text-brand-800">
                Trajet direct à l'arrivée
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {transports.airport_transfer.options.map((opt) => {
                const durationMin =
                  opt.estimated_duration_min ?? opt.duration_minutes ?? 25;
                const priceEur = Math.round(Number(opt.estimated_price_eur || 0));
                return (
                  <div
                    key={opt.mode}
                    className="rounded-card border border-border bg-canvas-subtle p-4 space-y-2"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-body font-semibold text-ink">
                        {opt.label}
                      </span>
                      <Badge variant="brand">~{priceEur} €</Badge>
                    </div>
                    <div className="text-caption font-medium text-brand-800">
                      Durée estimée : {durationMin} min
                    </div>
                    <p className="text-caption text-ink-secondary">{opt.notes}</p>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Skeleton className="h-28 w-full" />
            <Skeleton className="h-28 w-full" />
            <Skeleton className="h-28 w-full" />
          </div>
        )}

        {/* Pass de transport & VTC locaux */}
        {transports && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-3 border-t border-border">
            <div className="space-y-2">
              <h3 className="text-caption font-semibold text-ink flex items-center gap-1.5">
                <Bus className="h-4 w-4 text-brand-700" />
                <span>Transports en commun & navettes</span>
              </h3>
              {(transports.transit_passes?.length > 0
                ? transports.transit_passes
                : transports.airport_transfer?.options?.slice(0, 1).map((o) => ({
                    name: o.provider_name || o.label,
                    provider_name: o.provider_name || o.label,
                    description: o.notes,
                    coverage: o.notes,
                    estimated_price_eur: o.estimated_price_eur,
                    price_eur: o.estimated_price_eur,
                  })) || []
              )
                .slice(0, 2)
                .map((pass, idx) => (
                  <div
                    key={`${pass.provider_name || pass.name}-${idx}`}
                    className="rounded-md bg-canvas-subtle p-3 flex items-center justify-between gap-3"
                  >
                    <div>
                      <div className="text-caption font-semibold text-ink">
                        {pass.provider_name || pass.name}
                      </div>
                      <div className="text-caption text-ink-secondary line-clamp-1">
                        {pass.description || pass.coverage}
                      </div>
                    </div>
                    <span className="text-caption font-bold text-brand-800 whitespace-nowrap">
                      {Math.round(Number(pass.estimated_price_eur ?? pass.price_eur ?? 3))} €
                    </span>
                  </div>
                ))}
            </div>

            <div className="space-y-2">
              <h3 className="text-caption font-semibold text-ink flex items-center gap-1.5">
                <Car className="h-4 w-4 text-brand-700" />
                <span>Taxis officiels & location à {cityLabel}</span>
              </h3>
              {(transports.taxi_vtc_links?.length > 0
                ? transports.taxi_vtc_links
                : transports.car_rental_links || []
              )
                .slice(0, 2)
                .map((vtc, idx) => (
                  <div
                    key={`${vtc.provider_name || vtc.provider}-${idx}`}
                    className="rounded-md bg-canvas-subtle p-3 flex items-center justify-between gap-3"
                  >
                    <div>
                      <div className="text-caption font-semibold text-ink">
                        {vtc.provider_name || vtc.provider}
                      </div>
                      <div className="text-caption text-ink-secondary line-clamp-1">
                        {vtc.description}
                      </div>
                    </div>
                    <span className="text-caption font-bold text-brand-800 whitespace-nowrap">
                      dès{" "}
                      {Math.round(
                        Number(
                          vtc.estimated_price_eur ??
                            vtc.estimated_base_fare_eur ??
                            15
                        )
                      )}{" "}
                      €
                    </span>
                  </div>
                ))}
            </div>
          </div>
        )}
      </Card>

      {/* 4. Mon programme & Mes documents */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card className="p-6 flex flex-col justify-between gap-4" data-testid="trip-itinerary-card">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h2 className="text-h2 text-ink flex items-center gap-2">
                <CalendarIcon className="h-5 w-5 text-brand-700" />
                <span>Mon programme sur place</span>
              </h2>
              <Badge variant="brand">
                {schedule?.total_visits || 0} visite(s)
              </Badge>
            </div>
            <p className="text-body text-ink-secondary">
              {schedule && schedule.total_visits > 0
                ? `${schedule.total_visits} activité(s) planifiée(s) et synchronisée(s) avec votre agenda.`
                : "Aucune activité planifiée pour l'instant."}
            </p>
          </div>
          <div className="flex justify-end">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => navigate("/itinerary")}
            >
              Ouvrir mon programme jour par jour
            </Button>
          </div>
        </Card>

        <Card className="p-6 flex flex-col justify-between gap-4" data-testid="trip-documents-card">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h2 className="text-h2 text-ink flex items-center gap-2">
                <FileText className="h-5 w-5 text-brand-700" />
                <span>Mes documents de voyage</span>
              </h2>
              <Badge variant="success">Prêts</Badge>
            </div>
            <p className="text-body text-ink-secondary">
              Billet d'avion aller-retour, confirmation de réservation et récapitulatif d'hébergement disponibles à tout moment.
            </p>
          </div>
          <div className="flex justify-end">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={onOpenDocumentsModal}
            >
              Consulter mes documents
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}

/* ============================================================================
 * 5. ÉCRAN PARAMÈTRES (/settings)
 *    - Devise, langue, style éco / standard / luxe (3 champs max)
 * ========================================================================== */
export function SettingsScreen({
  preferences,
  onSavePreferences,
  currentUser,
  onLogout,
}: {
  preferences: TravelerPreferences;
  onSavePreferences: (prefs: TravelerPreferences) => void;
  currentUser: UserProfile | null;
  onLogout: () => void;
}) {
  const { notify } = useToast();
  const [currency, setCurrency] = useState<TravelerPreferences["currency"]>(
    preferences.currency
  );
  const [language, setLanguage] = useState<TravelerPreferences["language"]>(
    preferences.language
  );
  const [travelStyle, setTravelStyle] = useState<
    TravelerPreferences["travelStyle"]
  >(preferences.travelStyle);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onSavePreferences({ currency, language, travelStyle });
    notify({
      title: "Préférences enregistrées",
      description: "Vos choix de devise, de langue et de style de voyage ont été mis à jour.",
      tone: "success",
    });
  }

  return (
    <div
      className="mx-auto max-w-xl px-4 py-10 space-y-6"
      data-testid="settings-screen"
    >
      <div>
        <Badge variant="brand" className="mb-2">
          Préférences voyageur
        </Badge>
        <h1 className="text-h1 text-ink">Paramètres</h1>
        <p className="text-body text-ink-secondary mt-1">
          Personnalisez votre devise, votre langue et votre confort de voyage.
        </p>
      </div>

      <Card className="p-6 sm:p-8">
        <form onSubmit={handleSubmit} className="space-y-5" data-testid="settings-form">
          {/* Champ 1 : Devise */}
          <div>
            <label className="block text-caption font-medium text-ink-secondary mb-1.5">
              Devise d'affichage
            </label>
            <Select
              value={currency}
              onValueChange={(val) =>
                setCurrency(val as TravelerPreferences["currency"])
              }
              ariaLabel="Devise d'affichage"
              options={[
                { value: "EUR", label: "Euro (€ — EUR)" },
                { value: "USD", label: "Dollar américain ($ — USD)" },
                { value: "MAD", label: "Dirham marocain (DH — MAD)" },
                { value: "JPY", label: "Yen japonais (¥ — JPY)" },
              ]}
            />
          </div>

          {/* Champ 2 : Langue */}
          <div>
            <label className="block text-caption font-medium text-ink-secondary mb-1.5">
              Langue de l'interface
            </label>
            <Select
              value={language}
              onValueChange={(val) =>
                setLanguage(val as TravelerPreferences["language"])
              }
              ariaLabel="Langue de l'interface"
              options={[
                { value: "fr", label: "Français" },
                { value: "en", label: "English" },
              ]}
            />
          </div>

          {/* Champ 3 : Style éco / standard / luxe */}
          <div>
            <label className="block text-caption font-medium text-ink-secondary mb-1.5">
              Style de voyage préféré
            </label>
            <Select
              value={travelStyle}
              onValueChange={(val) =>
                setTravelStyle(val as TravelerPreferences["travelStyle"])
              }
              ariaLabel="Style de voyage préféré"
              options={[
                { value: "ECO", label: "Éco — Essentiel et petits budgets" },
                { value: "STANDARD", label: "Standard — Équilibre confort et prix" },
                { value: "LUXURY", label: "Luxe — Hôtels 5★ et vols confort" },
              ]}
            />
          </div>

          <div className="pt-2 flex items-center justify-between gap-3">
            {currentUser && (
              <Button type="button" variant="ghost" size="sm" onClick={onLogout}>
                Se déconnecter ({currentUser.email})
              </Button>
            )}
            <Button
              type="submit"
              size="lg"
              data-testid="save-settings-btn"
              className="ml-auto"
            >
              Enregistrer mes préférences
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}

/* ============================================================================
 * 6. PAGE D'ADMINISTRATION TECHNIQUE SÉPARÉE (/admin)
 *    - Déplacée hors de l'interface voyageur
 * ========================================================================== */
export function AdminTechnicalStatusScreen({ apiBase }: { apiBase: string }) {
  const [health, setHealth] = useState<any>(null);

  useEffect(() => {
    fetch(`${apiBase}/health`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setHealth)
      .catch(() => null);
  }, [apiBase]);

  return (
    <div
      className="mx-auto max-w-4xl px-4 py-10 space-y-6"
      data-testid="admin-health-screen"
    >
      <Card className="p-6 space-y-4">
        <h1 className="text-h1 text-ink">Administration système (/admin)</h1>
        <p className="text-body text-ink-secondary">
          Supervision technique réservée à l'équipe d'exploitation.
        </p>
        {health && (
          <pre className="rounded-card bg-canvas-subtle p-4 text-caption overflow-x-auto">
            {JSON.stringify(health, null, 2)}
          </pre>
        )}
      </Card>
    </div>
  );
}

import React, { useEffect, useMemo, useRef, useState } from "react";
import ReactDOMServer from "react-dom/server";
import {
  BrowserRouter,
  Link,
  MemoryRouter,
  NavLink,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";
import {
  QueryClient,
  QueryClientProvider,
  useMutation,
  useQuery,
} from "@tanstack/react-query";
import * as Popover from "@radix-ui/react-popover";
import { DayPicker, type DateRange } from "react-day-picker";
import { format, parseISO } from "date-fns";
import { fr } from "date-fns/locale";
import {
  AlertCircle,
  ArrowRight,
  Calendar as CalendarIcon,
  CheckCircle2,
  ChevronRight,
  Clock,
  Compass,
  FileText,
  LogOut,
  Mail,
  MapPin,
  Plane,
  Search,
  Settings,
  Sparkles,
  User,
  Users,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  Input,
  Modal,
  Select,
  Skeleton,
  ToastProvider,
  useToast,
} from "./components/ui";
import {
  type AccommodationItem,
  AccommodationsScreen,
  ActivitiesScreen,
  AdminTechnicalStatusScreen,
  clearOfflineDocumentsCache,
  type Destination,
  ItineraryScreen,
  MyTripSummaryScreen,
  SettingsScreen,
  type TravelerPreferences,
  type Trip,
  TripBudgetScreen,
  TripDocumentsScreen,
  type TripGalleryPayload,
  TripPracticalInfoScreen,
} from "./EnvoiCScreens";
import {
  HomeMultiCityBuilder,
  validateDraftStagesNoOverlap,
  addDaysIso,
  diffDaysIso,
  type DraftStageFormItem,
} from "./MultiCityComponents";

const RAW_API_BASE = String(
  (import.meta as any).env?.VITE_API_BASE_URL || "http://localhost:8000"
);
export const API_BASE = RAW_API_BASE.replace(/\/api\/v1\/?$/i, "").replace(
  /\/+$/,
  ""
);

const TOKEN_STORAGE_KEY = "travelmate_jwt_token";
const USER_STORAGE_KEY = "travelmate_user_profile";
export const SESSION_COOKIE_MARKER = "cookie-session";

let inMemoryCsrfToken = "";

export function readCsrfCookie(): string {
  if (typeof document === "undefined" || !document.cookie) {
    return inMemoryCsrfToken;
  }
  const match = document.cookie.match(/(?:^|;\s*)tm_csrf_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : inMemoryCsrfToken;
}

export function setInMemoryCsrfToken(token?: string | null): void {
  if (token && typeof token === "string") {
    inMemoryCsrfToken = token;
  }
}

function installSecureCookieFetchInterceptor(): void {
  if (typeof window === "undefined" || typeof window.fetch !== "function") {
    return;
  }
  const w = window as any;
  if (w.__tmSecureFetchInstalled) return;
  w.__tmSecureFetchInstalled = true;

  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const urlStr =
      typeof input === "string"
        ? input
        : input instanceof URL
        ? input.toString()
        : input.url;

    const isBackendCall =
      urlStr.startsWith(API_BASE) ||
      urlStr.startsWith("/api/") ||
      urlStr.includes("/api/v1/") ||
      urlStr.endsWith("/health");

    if (!isBackendCall) {
      return nativeFetch(input, init);
    }

    const nextInit: RequestInit = { ...(init || {}) };
    nextInit.credentials = "include";

    const headers = new Headers(init?.headers || {});
    const authHeader = headers.get("Authorization") || "";
    if (
      authHeader === `Bearer ${SESSION_COOKIE_MARKER}` ||
      authHeader === "Bearer ssr-demo-token" ||
      authHeader === "Bearer "
    ) {
      headers.delete("Authorization");
    }

    const method = (nextInit.method || "GET").toUpperCase();
    if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
      const csrf = readCsrfCookie();
      if (csrf && !headers.has("X-CSRF-Token")) {
        headers.set("X-CSRF-Token", csrf);
      }
    }

    nextInit.headers = headers;
    const response = await nativeFetch(input, nextInit);
    return response;
  };
}

installSecureCookieFetchInterceptor();

export interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  preferred_style: string;
}

export interface FlightOffer {
  offer_id: string;
  airline_code: string;
  airline_name: string;
  flight_number_outbound: string;
  flight_number_inbound: string;
  origin_iata: string;
  destination_iata: string;
  origin_city_code?: string;
  destination_city_code?: string;
  destination_city: string;
  departure_outbound_at: string;
  arrival_outbound_at: string;
  departure_inbound_at: string;
  arrival_inbound_at: string;
  cabin_class: string;
  price_amount: string;
  price_eur: number;
  currency: string;
  mode: string;
  is_example_offer?: boolean;
  offer_badge?: string;
  price_label?: string;
  banner_text?: string;
  distance_km?: number;
  duration_outbound_minutes?: number;
  duration_inbound_minutes?: number;
  stops?: number;
  stopover_hub_iata?: string | null;
  stopover_hub_city?: string | null;
  stopover_label?: string;
  comparator_urls?: {
    origin_code?: string;
    destination_code?: string;
    google_flights?: string;
    kayak?: string;
    skyscanner?: string;
  };
}

export interface FlightBooking {
  id: string;
  trip_id: string;
  idempotency_key: string;
  idempotent_replay: boolean;
  pnr_reference: string;
  airline: string;
  flight_number_outbound: string;
  flight_number_inbound: string;
  origin_iata: string;
  destination_iata: string;
  departure_outbound_at: string;
  arrival_outbound_at: string;
  departure_inbound_at: string;
  arrival_inbound_at: string;
  price_amount: string;
  currency: string;
  cabin_class: string;
  flight_status: string;
  vault_document_id: string | null;
  budget_item_id: string | null;
  gmail_confirmation_sent: boolean;
  gmail_message_id: string | null;
  gmail_send_status?: string;
  trip_arrival_at: string;
  trip_departure_at: string;
}

const DEPARTURE_AIRPORTS = [
  { value: "CDG", label: "Paris (Charles de Gaulle)", city: "Paris" },
  { value: "ORY", label: "Paris (Orly)", city: "Paris" },
  { value: "LYS", label: "Lyon (Saint-Exupéry)", city: "Lyon" },
  { value: "MRS", label: "Marseille (Provence)", city: "Marseille" },
  { value: "BRU", label: "Bruxelles (Zaventem)", city: "Bruxelles" },
  { value: "GVA", label: "Genève (Cointrin)", city: "Genève" },
  { value: "LHR", label: "Londres (Heathrow)", city: "Londres" },
];

const AIRPORT_CITY_NAMES: Record<string, string> = {
  CDG: "Paris (Charles de Gaulle)",
  ORY: "Paris (Orly)",
  PAR: "Paris (PAR)",
  LYS: "Lyon (Saint-Exupéry)",
  MRS: "Marseille (Provence)",
  BRU: "Bruxelles",
  GVA: "Genève",
  LHR: "Londres (Heathrow)",
  LON: "Londres (LON)",
  HND: "Tokyo (Haneda)",
  TYO: "Tokyo (TYO)",
  FCO: "Rome (Fiumicino)",
  ROM: "Rome (ROM)",
  RAK: "Marrakech (Ménara)",
  JFK: "New York (JFK)",
  NYC: "New York (NYC)",
  MIL: "Milan (MIL)",
  MXP: "Milan (MIL)",
  LIN: "Milan (MIL)",
  BGY: "Milan (MIL)",
  MIR: "Monastir (MIR)",
  SYD: "Sydney (SYD)",
  LIS: "Lisbonne (LIS)",
};

const CITY_COMPARATOR_CODE_BY_IATA: Record<string, string> = {
  CDG: "PAR",
  ORY: "PAR",
  BVA: "PAR",
  PAR: "PAR",
  LHR: "LON",
  LGW: "LON",
  STN: "LON",
  LTN: "LON",
  LCY: "LON",
  LON: "LON",
  MXP: "MIL",
  LIN: "MIL",
  BGY: "MIL",
  MIL: "MIL",
  JFK: "NYC",
  EWR: "NYC",
  LGA: "NYC",
  NYC: "NYC",
  HND: "TYO",
  NRT: "TYO",
  TYO: "TYO",
  FCO: "ROM",
  CIA: "ROM",
  ROM: "ROM",
};

function toCityComparatorCode(code: string): string {
  const clean = (code || "").trim().toUpperCase();
  return CITY_COMPARATOR_CODE_BY_IATA[clean] || clean;
}

function formatTimeHuman(iso: string): string {
  try {
    return format(parseISO(iso), "HH:mm");
  } catch {
    return "--:--";
  }
}

function formatDateHuman(iso: string): string {
  try {
    return format(parseISO(iso), "EEEE d MMMM", { locale: fr }).toLowerCase();
  } catch {
    return "";
  }
}

function computeDurationMinutes(startIso: string, endIso: string): number {
  const start = new Date(startIso).getTime();
  const end = new Date(endIso).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end <= start) return 180;
  return Math.round((end - start) / 60000);
}

function formatDurationHuman(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m > 0 ? `${h} h ${String(m).padStart(2, "0")}` : `${h} h`;
}

function cabinLabelHuman(cabin: string): string {
  const upper = cabin.toUpperCase();
  if (upper.includes("FIRST") || upper.includes("BUSINESS") || upper.includes("LUX")) {
    return "Confort Première";
  }
  if (upper.includes("PREMIUM") || upper.includes("STANDARD")) {
    return "Confort Standard";
  }
  return "Classe Économique";
}

function humanErrorMessage(errPayload: any, fallback: string): string {
  const detail = errPayload?.detail ?? errPayload;
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (typeof detail?.message === "string" && detail.message.trim()) {
    return detail.message;
  }
  return fallback;
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

const SEED_POPULAR_CITY_NAMES = new Set([
  "paris",
  "marrakech",
  "tokyo",
  "new york",
  "rome",
]);

export interface GeoNamesCitySearchItem {
  geonameId: number;
  geoname_id?: number;
  nom: string;
  name?: string;
  city_name?: string;
  pays: string;
  country_name?: string;
  code_pays: string;
  country_code_iso2?: string;
  region?: string;
  region_name?: string;
  sous_titre?: string;
  feature_class?: string;
  feature_code?: string;
  is_region?: boolean;
  coordonnees: { latitude: number; longitude: number };
  fuseau_horaire: string;
  timezone?: string;
  population: number;
  iata_code?: string;
  airport_name?: string;
  nearest_airport_distance_km?: number;
  airport_within_100km?: boolean;
  airport_display_label?: string;
  is_seed?: boolean;
  destination_id?: string | null;
}

export function formatGeoCitySubtitle(item: GeoNamesCitySearchItem): string {
  if (item.sous_titre && item.sous_titre.trim()) {
    return item.sous_titre.trim();
  }
  const reg = (item.region || item.region_name || "").trim();
  const country = (item.pays || item.country_name || "").trim();
  if (reg && country && reg.toLowerCase() !== country.toLowerCase()) {
    return `${reg} • ${country}`;
  }
  return country || reg;
}

export function formatGeoAirportBadge(item: GeoNamesCitySearchItem): string {
  const iata = (item.iata_code || "").trim().toUpperCase();
  if (!iata) return "";
  if (
    item.airport_within_100km === false &&
    typeof item.nearest_airport_distance_km === "number"
  ) {
    return `${iata} • à ${Math.round(item.nearest_airport_distance_km)} km`;
  }
  return iata;
}

export interface RememberedDepartureOrigin {
  cityName: string;
  countryName: string;
  regionName?: string;
  iataCode: string;
  airportName?: string;
  distanceKm?: number;
  within100Km?: boolean;
  displayLabel: string;
}

const DEPARTURE_ORIGIN_STORAGE_KEY = "travelmate_departure_origin_v1";

const DEFAULT_DEPARTURE_ORIGIN: RememberedDepartureOrigin = {
  cityName: "Paris",
  countryName: "France",
  regionName: "Île-de-France",
  iataCode: "CDG",
  airportName: "Aéroport de Paris-Charles de Gaulle",
  distanceKm: 22.9,
  within100Km: true,
  displayLabel: "Paris (CDG)",
};

function loadRememberedDepartureOrigin(): RememberedDepartureOrigin {
  if (typeof window === "undefined" || typeof localStorage === "undefined") {
    return DEFAULT_DEPARTURE_ORIGIN;
  }
  try {
    const raw = localStorage.getItem(DEPARTURE_ORIGIN_STORAGE_KEY);
    if (!raw) return DEFAULT_DEPARTURE_ORIGIN;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.iataCode === "string" && parsed.iataCode.trim()) {
      return {
        cityName: String(parsed.cityName || "Paris"),
        countryName: String(parsed.countryName || "France"),
        regionName: parsed.regionName ? String(parsed.regionName) : undefined,
        iataCode: parsed.iataCode.trim().toUpperCase(),
        airportName: parsed.airportName ? String(parsed.airportName) : undefined,
        distanceKm:
          typeof parsed.distanceKm === "number" ? parsed.distanceKm : undefined,
        within100Km:
          typeof parsed.within100Km === "boolean" ? parsed.within100Km : true,
        displayLabel: String(
          parsed.displayLabel || `${parsed.cityName || "Paris"} (${parsed.iataCode})`
        ),
      };
    }
  } catch {
    // ignore storage errors
  }
  return DEFAULT_DEPARTURE_ORIGIN;
}

function saveRememberedDepartureOrigin(origin: RememberedDepartureOrigin): void {
  if (typeof window === "undefined" || typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(DEPARTURE_ORIGIN_STORAGE_KEY, JSON.stringify(origin));
  } catch {
    // ignore storage errors
  }
}

/**
 * Champ d'autocomplétion GeoNames réutilisable (Accueil, Écran Vols, Paramètres).
 * - Anti-rebond 300 ms, 3 lettres minimum
 * - Mention "Tapez au moins 3 lettres pour chercher dans le monde entier"
 * - Squelette de chargement
 * - "Aucune ville trouvée pour <texte>"
 * - 8 lignes maximum, navigation clavier (Flèches, Entrée, Échap) et souris
 * - Affiche "région • pays" (jamais de fuseau horaire) + code IATA OurAirports (et distance si > 100 km)
 */
function GeoNamesCityAutocompleteField({
  inputId,
  inputTestId,
  listTestId,
  ariaLabel,
  placeholder = "Ville ou pays",
  displayValue,
  popularDestinations,
  onSelectCityItem,
  showAirportBadge = true,
}: {
  inputId?: string;
  inputTestId: string;
  listTestId: string;
  ariaLabel: string;
  placeholder?: string;
  displayValue: string;
  popularDestinations: Destination[];
  onSelectCityItem: (item: GeoNamesCitySearchItem) => void;
  showAirportBadge?: boolean;
}) {
  const [query, setQuery] = useState<string>(displayValue);
  const [isEditing, setIsEditing] = useState<boolean>(false);
  const [open, setOpen] = useState<boolean>(false);
  const [results, setResults] = useState<GeoNamesCitySearchItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [unavailableMsg, setUnavailableMsg] = useState<string | null>(null);
  const [activeIndex, setActiveIndex] = useState<number>(-1);
  const boxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!isEditing) {
      setQuery(displayValue);
    }
  }, [displayValue, isEditing]);

  useEffect(() => {
    function handleOutside(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false);
        setIsEditing(false);
        setQuery(displayValue);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [displayValue]);

  useEffect(() => {
    if (!isEditing) return;
    const trimmed = query.trim();
    if (trimmed.length < 3) {
      setResults([]);
      setIsLoading(false);
      setUnavailableMsg(null);
      return;
    }

    let cancelled = false;
    setIsLoading(true);
    const timer = window.setTimeout(async () => {
      try {
        const resp = await fetch(
          `${API_BASE}/api/v1/destinations/search?q=${encodeURIComponent(trimmed)}`
        );
        if (cancelled) return;
        if (!resp.ok) {
          setUnavailableMsg(
            "Recherche de villes indisponible — repli sur les 5 destinations populaires."
          );
          setResults([]);
          setIsLoading(false);
          return;
        }
        const data = await resp.json();
        if (cancelled) return;
        if (data && data.available === false) {
          setUnavailableMsg(
            data.message ||
              "Recherche de villes indisponible — repli sur les 5 destinations populaires."
          );
          const fallbackItems = Array.isArray(data.fallback_cities) && data.fallback_cities.length > 0
            ? data.fallback_cities
            : Array.isArray(data.results)
            ? data.results
            : [];
          setResults(fallbackItems);
        } else {
          setUnavailableMsg(null);
          setResults(Array.isArray(data?.results) ? data.results : []);
        }
      } catch {
        if (!cancelled) {
          setUnavailableMsg(
            "Recherche de villes indisponible — repli sur les 5 destinations populaires."
          );
          setResults([]);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }, 300);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, isEditing]);

  const suggestions = useMemo((): GeoNamesCitySearchItem[] => {
    const seedItems: GeoNamesCitySearchItem[] = popularDestinations.map((d, idx) => ({
      geonameId: (d as any).geonameId || (d as any).geoname_id || 9000000 + idx,
      nom: d.city_name,
      pays: d.country_name,
      code_pays: d.country_code_iso2,
      region: d.region_name || d.city_name,
      sous_titre: d.sous_titre || `${d.region_name || d.city_name} • ${d.country_name}`,
      coordonnees: { latitude: d.latitude, longitude: d.longitude },
      fuseau_horaire: d.timezone,
      population: (d as any).population || 0,
      iata_code: d.iata_code,
      airport_name: d.airport_name || undefined,
      nearest_airport_distance_km:
        typeof d.nearest_airport_distance_km === "number"
          ? d.nearest_airport_distance_km
          : undefined,
      airport_within_100km:
        typeof d.airport_within_100km === "boolean" ? d.airport_within_100km : true,
      airport_display_label:
        d.airport_display_label || `${d.city_name} (${d.iata_code})`,
      is_seed: true,
      destination_id: d.id,
    }));

    if (unavailableMsg) {
      return (results.length > 0 ? results : seedItems).slice(0, 8);
    }
    if (query.trim().length < 3) {
      return [];
    }
    return results.slice(0, 8);
  }, [query, results, unavailableMsg, popularDestinations]);

  function handleSelect(item: GeoNamesCitySearchItem) {
    setIsEditing(false);
    setOpen(false);
    setActiveIndex(-1);
    onSelectCityItem(item);
  }

  return (
    <div ref={boxRef} className="relative overflow-visible" style={{ overflow: "visible" }}>
      <div className="relative">
        <MapPin className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-brand-700" />
        <Input
          id={inputId}
          data-testid={inputTestId}
          aria-label={ariaLabel}
          value={query}
          placeholder={placeholder}
          autoComplete="off"
          className="pl-9"
          onFocus={() => {
            setIsEditing(true);
            setQuery("");
            setOpen(true);
            setActiveIndex(-1);
          }}
          onChange={(e) => {
            setIsEditing(true);
            setQuery(e.target.value);
            setOpen(true);
            setActiveIndex(-1);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setOpen(false);
              setIsEditing(false);
              setQuery(displayValue);
              return;
            }
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setOpen(true);
              if (suggestions.length > 0) {
                setActiveIndex((prev) => (prev + 1) % suggestions.length);
              }
              return;
            }
            if (e.key === "ArrowUp") {
              e.preventDefault();
              setOpen(true);
              if (suggestions.length > 0) {
                setActiveIndex(
                  (prev) => (prev - 1 + suggestions.length) % suggestions.length
                );
              }
              return;
            }
            if (e.key === "Enter" && open && suggestions.length > 0) {
              e.preventDefault();
              const chosen =
                activeIndex >= 0 && activeIndex < suggestions.length
                  ? suggestions[activeIndex]
                  : suggestions[0];
              if (chosen) {
                handleSelect(chosen);
              }
            }
          }}
        />
      </div>

      {open && (
        <div
          role="listbox"
          aria-label={ariaLabel}
          data-testid={listTestId}
          style={{ zIndex: 100 }}
          className="absolute left-0 right-0 top-full z-[100] mt-1.5 rounded-card border border-border bg-canvas-card p-1.5 shadow-popover"
        >
          {unavailableMsg && (
            <div
              data-testid={`${listTestId}-unavailable`}
              className="mb-1.5 rounded-md bg-feedback-warningBg px-2.5 py-1.5 text-[12px] font-medium text-amber-900"
            >
              {unavailableMsg}
            </div>
          )}

          {!unavailableMsg && query.trim().length < 3 ? (
            <div
              data-testid={`${listTestId}-min-chars`}
              className="px-3 py-2 text-caption text-ink-muted"
            >
              Tapez au moins 3 lettres pour chercher dans le monde entier
            </div>
          ) : isLoading ? (
            <div
              data-testid={`${listTestId}-loading`}
              className="space-y-2 px-3 py-2"
            >
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          ) : suggestions.length === 0 ? (
            <div
              data-testid={`${listTestId}-empty`}
              className="px-3 py-2 text-caption text-ink-muted"
            >
              Aucune ville trouvée pour {query.trim()}
            </div>
          ) : (
            suggestions.map((item, idx) => {
              const subtitle = formatGeoCitySubtitle(item);
              const airportBadge = showAirportBadge ? formatGeoAirportBadge(item) : "";
              const isHighlighted = idx === activeIndex;
              const slug = item.nom
                .replace(/^Région\s*:\s*/i, "")
                .trim()
                .toLowerCase();
              return (
                <button
                  key={`${item.geonameId}-${item.nom}-${idx}`}
                  type="button"
                  role="option"
                  aria-selected={isHighlighted}
                  data-testid={
                    item.is_region
                      ? `autocomplete-region-${slug}`
                      : `autocomplete-city-${slug}`
                  }
                  onMouseEnter={() => setActiveIndex(idx)}
                  onClick={() => handleSelect(item)}
                  className={`flex w-full items-center justify-between gap-2 rounded-md px-3 py-1.5 text-left transition-colors focus:outline-none ${
                    isHighlighted
                      ? "bg-brand-50 text-brand-900"
                      : "hover:bg-brand-50"
                  }`}
                >
                  <div className="min-w-0">
                    <div className="text-body font-medium text-ink truncate">
                      {item.nom}
                    </div>
                    <div className="text-caption text-ink-muted truncate">
                      {subtitle}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {airportBadge && (
                      <Badge variant="neutral" className="text-[11px] px-1.5 py-0.5">
                        {airportBadge}
                      </Badge>
                    )}
                    <span className="text-caption text-brand-700 font-medium">
                      Choisir
                    </span>
                  </div>
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}

/* ============================================================================
 * 1. ÉCRAN ACCUEIL (/)
 * ========================================================================== */
function normalizeIsoDateInput(raw: string, fallbackIso: string): string {
  const trimmed = String(raw || "").trim();
  if (!trimmed) return fallbackIso;
  const isoMatch = trimmed.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (isoMatch) {
    return `${isoMatch[1]}-${isoMatch[2]}-${isoMatch[3]}`;
  }
  const frMatch = trimmed.match(/^(\d{2})[\/\-](\d{2})[\/\-](\d{4})$/);
  if (frMatch) {
    return `${frMatch[3]}-${frMatch[2]}-${frMatch[1]}`;
  }
  const parsed = new Date(trimmed);
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toISOString().slice(0, 10);
  }
  return fallbackIso;
}

function normalizeCityLookupText(raw: string): string {
  return String(raw || "")
    .replace(/^Région\s*:\s*/i, "")
    .split(/[,•\(\-]/)[0]
    .trim()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function HomeScreen({
  destinations,
  isLoadingDestinations,
  departureDate,
  returnDate,
  onChangeDates,
  travelers,
  onChangeTravelers,
  onSelectDestinationAndSearch,
  onRegisterCreatedDestination,
  initialUnavailableCity = null,
  onCreateMultiCityTrip,
}: {
  destinations: Destination[];
  isLoadingDestinations: boolean;
  departureDate: string;
  returnDate: string;
  onChangeDates: (dep: string, ret: string) => void;
  travelers: string;
  onChangeTravelers: (val: string) => void;
  onSelectDestinationAndSearch: (dest: Destination) => Promise<void>;
  onRegisterCreatedDestination?: (dest: Destination) => void;
  initialUnavailableCity?: string | null;
  onCreateMultiCityTrip?: (
    stages: DraftStageFormItem[],
    targetRoute?: "/flights" | "/trip"
  ) => Promise<void>;
}) {
  const [cityQuery, setCityQuery] = useState<string>("");
  const [autocompleteOpen, setAutocompleteOpen] = useState<boolean>(false);
  const [activeOptionIndex, setActiveOptionIndex] = useState<number>(-1);
  const [calendarOpen, setCalendarOpen] = useState<boolean>(false);
  const [unavailableCity, setUnavailableCity] = useState<string | null>(
    initialUnavailableCity
  );
  const [searchError, setSearchError] = useState<string | null>(null);
  const [geonamesResults, setGeonamesResults] = useState<GeoNamesCitySearchItem[]>([]);
  const [selectedGeoCity, setSelectedGeoCity] = useState<GeoNamesCitySearchItem | null>(
    null
  );
  const [isSearchingGeonames, setIsSearchingGeonames] = useState<boolean>(false);
  const [geonamesUnavailableMessage, setGeonamesUnavailableMessage] = useState<
    string | null
  >(null);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [multiCityEnabled, setMultiCityEnabled] = useState<boolean>(false);
  const [multiCitySubmitError, setMultiCitySubmitError] = useState<string>("");
  const searchBoxRef = useRef<HTMLDivElement | null>(null);

  const popularDestinations = useMemo(() => {
    const seedList = destinations.filter((d) =>
      SEED_POPULAR_CITY_NAMES.has(d.city_name.trim().toLowerCase())
    );
    return seedList.length > 0 ? seedList : destinations.slice(0, 5);
  }, [destinations]);

  const [draftStages, setDraftStages] = useState<DraftStageFormItem[]>([]);
  useEffect(() => {
    if (draftStages.length === 0 && popularDestinations.length > 0) {
      const firstDest =
        popularDestinations.find((d) => d.city_name === "Marrakech") ||
        popularDestinations[0];
      const secondDest =
        popularDestinations.find(
          (d) =>
            d.id !== firstDest.id &&
            d.city_name.toLowerCase() !== firstDest.city_name.toLowerCase()
        ) || null;
      const arr1 = normalizeIsoDateInput(departureDate, "2026-11-10");
      const dep1 = addDaysIso(arr1, 3);
      const normRet = normalizeIsoDateInput(returnDate, addDaysIso(dep1, 4));
      const dep2 = diffDaysIso(dep1, normRet) > 0 ? normRet : addDaysIso(dep1, 4);
      setDraftStages([
        {
          key: "stage-init-1",
          destination_id: firstDest.id,
          city_name: firstDest.city_name,
          country_name: firstDest.country_name || "Maroc",
          country_code_iso2: firstDest.country_code_iso2 || "MA",
          timezone: firstDest.timezone || "Africa/Casablanca",
          latitude: firstDest.latitude,
          longitude: firstDest.longitude,
          iata_code: firstDest.iata_code,
          arrival_date: arr1,
          departure_date: dep1,
          nights: Math.max(1, diffDaysIso(arr1, dep1)),
          arrival_transport_mode: "VOL",
        },
        {
          key: "stage-init-2",
          destination_id: secondDest ? secondDest.id : undefined,
          city_name: secondDest ? secondDest.city_name : "Rome",
          country_name: secondDest ? secondDest.country_name || "Italie" : "Italie",
          country_code_iso2: secondDest ? secondDest.country_code_iso2 || "IT" : "IT",
          timezone: secondDest ? secondDest.timezone || "Europe/Rome" : "Europe/Rome",
          latitude: secondDest ? secondDest.latitude : 41.9028,
          longitude: secondDest ? secondDest.longitude : 12.4964,
          iata_code: secondDest ? secondDest.iata_code : "FCO",
          arrival_date: dep1,
          departure_date: dep2,
          nights: Math.max(1, diffDaysIso(dep1, dep2)),
          arrival_transport_mode: "TRAIN",
        },
      ]);
    }
  }, [popularDestinations, departureDate, returnDate, draftStages.length]);

  const selectedRange: DateRange = useMemo(() => {
    const depIso = normalizeIsoDateInput(departureDate, "2026-11-10");
    const retIso = normalizeIsoDateInput(returnDate, "2026-11-17");
    return {
      from: parseISO(depIso),
      to: parseISO(retIso),
    };
  }, [departureDate, returnDate]);

  // Anti-rebond (debounce) de 300 ms à partir de 3 lettres minimum vers /api/v1/destinations/search
  useEffect(() => {
    const trimmed = cityQuery.trim();
    if (trimmed.length < 3) {
      setGeonamesResults([]);
      setIsSearchingGeonames(false);
      return;
    }

    let cancelled = false;
    setIsSearchingGeonames(true);
    const timer = window.setTimeout(async () => {
      try {
        const resp = await fetch(
          `${API_BASE}/api/v1/destinations/search?q=${encodeURIComponent(trimmed)}`
        );
        if (cancelled) return;
        if (!resp.ok) {
          setGeonamesUnavailableMessage(
            "Recherche de villes indisponible — repli sur les 5 destinations populaires."
          );
          setGeonamesResults([]);
          setIsSearchingGeonames(false);
          return;
        }
        const data = await resp.json();
        if (cancelled) return;
        if (data && data.available === false) {
          setGeonamesUnavailableMessage(
            data.message ||
              "Recherche de villes indisponible — repli sur les 5 destinations populaires."
          );
          const fallbackItems =
            Array.isArray(data.fallback_cities) && data.fallback_cities.length > 0
              ? data.fallback_cities
              : Array.isArray(data.results)
              ? data.results
              : [];
          setGeonamesResults(fallbackItems);
        } else {
          setGeonamesUnavailableMessage(null);
          setGeonamesResults(Array.isArray(data?.results) ? data.results : []);
        }
      } catch {
        if (!cancelled) {
          setGeonamesUnavailableMessage(
            "Recherche de villes indisponible — repli sur les 5 destinations populaires."
          );
          setGeonamesResults([]);
        }
      } finally {
        if (!cancelled) {
          setIsSearchingGeonames(false);
        }
      }
    }, 300);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [cityQuery]);

  // Règle A.3 & B.6 : 8 lignes maximum. Les 5 villes de démo n'apparaissent dans la liste
  // que si GeoNames les renvoie (correspondance au nom) ou en repli quand GeoNames est injoignable.
  const displaySuggestions = useMemo((): GeoNamesCitySearchItem[] => {
    const q = cityQuery.trim().toLowerCase();
    const seedAsGeoItems: GeoNamesCitySearchItem[] = popularDestinations.map(
      (d, idx) => ({
        geonameId: (d as any).geonameId || (d as any).geoname_id || 9000000 + idx,
        nom: d.city_name,
        pays: d.country_name,
        code_pays: d.country_code_iso2,
        region: d.region_name || d.city_name,
        sous_titre:
          d.sous_titre || `${d.region_name || d.city_name} • ${d.country_name}`,
        coordonnees: { latitude: d.latitude, longitude: d.longitude },
        fuseau_horaire: d.timezone,
        population: (d as any).population || 0,
        iata_code: d.iata_code,
        is_seed: true,
        destination_id: d.id,
      })
    );

    if (geonamesUnavailableMessage) {
      const filteredSeed = seedAsGeoItems.filter((item) =>
        item.nom.toLowerCase().includes(q)
      );
      return (filteredSeed.length > 0 ? filteredSeed : seedAsGeoItems).slice(0, 8);
    }

    if (q.length < 3) {
      return [];
    }

    return geonamesResults.slice(0, 8);
  }, [cityQuery, popularDestinations, geonamesResults, geonamesUnavailableMessage]);

  useEffect(() => {
    function handleOutsideClick(e: MouseEvent) {
      if (searchBoxRef.current && !searchBoxRef.current.contains(e.target as Node)) {
        setAutocompleteOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, []);

  async function resolveGeoCityToDestination(
    item: GeoNamesCitySearchItem
  ): Promise<Destination | null> {
    const rawName = String(item.nom || (item as any).city_name || "").trim();
    const cleanCityName = rawName.replace(/^Région\s*:\s*/i, "").trim();
    const cleanLookup = normalizeCityLookupText(cleanCityName);
    const existingSeed = destinations.find(
      (d) =>
        (item.destination_id && d.id === item.destination_id) ||
        normalizeCityLookupText(d.city_name) === cleanLookup
    );
    if (
      existingSeed &&
      SEED_POPULAR_CITY_NAMES.has(existingSeed.city_name.trim().toLowerCase())
    ) {
      return existingSeed;
    }

    const rawIata = String(
      item.iata_code || (item as any).nearest_airport_iata || ""
    ).trim();
    const validIata = rawIata.length === 3 ? rawIata.toUpperCase() : undefined;
    const rawCountryIso2 = String(
      item.code_pays || (item as any).country_code_iso2 || "XX"
    )
      .trim()
      .toUpperCase()
      .slice(0, 2);
    const rawCoords = item.coordonnees || {
      latitude: (item as any).latitude ?? 48.8566,
      longitude: (item as any).longitude ?? 2.3522,
    };

    try {
      const resp = await fetch(`${API_BASE}/api/v1/destinations/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          geonameId: item.geonameId ?? (item as any).geoname_id ?? null,
          nom: cleanCityName,
          pays: item.pays || (item as any).country_name || "Monde",
          code_pays: rawCountryIso2.length === 2 ? rawCountryIso2 : "XX",
          region: item.region || item.region_name || null,
          sous_titre: item.sous_titre || null,
          coordonnees: rawCoords,
          fuseau_horaire:
            item.fuseau_horaire || (item as any).timezone || "Europe/Paris",
          population: item.population || 0,
          ...(validIata ? { iata_code: validIata } : {}),
        }),
      });
      if (resp.ok) {
        const resolvedDest: Destination = await resp.json();
        onRegisterCreatedDestination?.(resolvedDest);
        return resolvedDest;
      }
      if (!existingSeed) {
        const errBody = await resp.json().catch(() => null);
        throw new Error(
          humanErrorMessage(
            errBody,
            `Impossible de préparer la destination « ${cleanCityName} ».`
          )
        );
      }
    } catch (err) {
      if (existingSeed) {
        return existingSeed;
      }
      throw err;
    }
    return existingSeed || null;
  }

  function handleSelectHomeSuggestion(item: GeoNamesCitySearchItem) {
    const cleanName = String(item.nom || (item as any).city_name || "")
      .replace(/^Région\s*:\s*/i, "")
      .trim();
    setSelectedGeoCity(item);
    setCityQuery(cleanName);
    setUnavailableCity(null);
    setSearchError(null);
    setAutocompleteOpen(false);
    setActiveOptionIndex(-1);
  }

  async function handleSubmitMultiCityStages(
    targetRoute: "/flights" | "/trip" = "/trip"
  ) {
    setMultiCitySubmitError("");
    setSearchError(null);
    const check = validateDraftStagesNoOverlap(draftStages);
    if (!check.valid) {
      const msg = check.error || "Dates des étapes invalides.";
      setMultiCitySubmitError(msg);
      setSearchError(msg);
      return;
    }
    if (onCreateMultiCityTrip) {
      setIsSubmitting(true);
      try {
        await onCreateMultiCityTrip(draftStages, targetRoute);
      } catch (err: any) {
        const msg =
          err instanceof Error
            ? err.message
            : "Impossible de créer le voyage multi-villes. Veuillez réessayer.";
        setMultiCitySubmitError(msg);
        setSearchError(msg);
      } finally {
        setIsSubmitting(false);
      }
    }
  }

  async function handleSubmitSearch(e: React.FormEvent) {
    e.preventDefault();
    setUnavailableCity(null);
    setMultiCitySubmitError("");
    setSearchError(null);

    // Validation souple et normalisation des dates avant soumission
    const normDep = normalizeIsoDateInput(departureDate, "");
    let normRet = normalizeIsoDateInput(returnDate, "");
    if (!normDep || !normRet) {
      setSearchError(
        "Veuillez sélectionner une date de départ et une date de retour valides."
      );
      return;
    }
    const nightsDiff = diffDaysIso(normDep, normRet);
    if (nightsDiff < 0) {
      setSearchError(
        `Dates de séjour invalides : la date de retour (${normRet}) doit être postérieure à la date de départ (${normDep}).`
      );
      return;
    }
    if (nightsDiff === 0) {
      normRet = addDaysIso(normDep, 7);
      onChangeDates(normDep, normRet);
    } else if (normDep !== departureDate || normRet !== returnDate) {
      onChangeDates(normDep, normRet);
    }

    const trimmed = cityQuery.trim();

    // Si le mode multi-villes est ouvert et qu'aucune destination simple n'a été saisie dans le champ principal
    if (multiCityEnabled && onCreateMultiCityTrip && !trimmed) {
      await handleSubmitMultiCityStages("/flights");
      return;
    }

    if (!trimmed) {
      const defaultDest =
        popularDestinations.find((d) => d.city_name === "Marrakech") ||
        popularDestinations[0] ||
        destinations[0];
      if (!defaultDest) {
        setSearchError(
          "Veuillez saisir une destination (ex. Marrakech, Rome, Lisbonne) pour lancer la recherche."
        );
        return;
      }
      setIsSubmitting(true);
      try {
        await onSelectDestinationAndSearch(defaultDest);
      } catch (err: any) {
        setSearchError(
          err instanceof Error
            ? err.message
            : "Impossible de créer le voyage pour cette destination."
        );
      } finally {
        setIsSubmitting(false);
      }
      return;
    }

    const cleanLookup = normalizeCityLookupText(trimmed);
    const strippedQuery = trimmed
      .replace(/^Région\s*:\s*/i, "")
      .split(/[,•\(]/)[0]
      .trim();

    setIsSubmitting(true);
    try {
      // 1. Si l'utilisateur a choisi une suggestion GeoNames explicite correspondant au champ
      if (
        selectedGeoCity &&
        normalizeCityLookupText(
          selectedGeoCity.nom || (selectedGeoCity as any).city_name || ""
        ) === cleanLookup
      ) {
        const resolved = await resolveGeoCityToDestination(selectedGeoCity);
        if (resolved) {
          await onSelectDestinationAndSearch(resolved);
          return;
        }
      }

      // 2. Si la ville fait partie des destinations déjà chargées (ex: les 5 villes du seed)
      const directSeedMatch = destinations.find(
        (d) =>
          d.city_name.trim().toLowerCase() === trimmed.toLowerCase() ||
          normalizeCityLookupText(d.city_name) === cleanLookup
      );
      if (directSeedMatch) {
        await onSelectDestinationAndSearch(directSeedMatch);
        return;
      }

      // 3. Si des résultats GeoNames sont déjà présents pour cette saisie
      const geoMatch =
        geonamesResults.find(
          (g) =>
            normalizeCityLookupText(g.nom || (g as any).city_name || "") ===
            cleanLookup
        ) || geonamesResults[0];
      if (geoMatch) {
        const resolved = await resolveGeoCityToDestination(geoMatch);
        if (resolved) {
          await onSelectDestinationAndSearch(resolved);
          return;
        }
      }

      // 4. Sinon, interroge immédiatement /api/v1/destinations/search?q=... (si l'utilisateur a validé avant les 300 ms)
      const queryForApi = strippedQuery.length >= 2 ? strippedQuery : trimmed;
      if (queryForApi.length >= 2) {
        try {
          const searchResp = await fetch(
            `${API_BASE}/api/v1/destinations/search?q=${encodeURIComponent(
              queryForApi
            )}`
          );
          if (searchResp.ok) {
            const searchData = await searchResp.json();
            if (searchData?.available === false) {
              setGeonamesUnavailableMessage(
                searchData.message ||
                  "Recherche de villes indisponible — repli sur les 5 destinations populaires."
              );
            }
            const apiResults: GeoNamesCitySearchItem[] =
              Array.isArray(searchData?.results) && searchData.results.length > 0
                ? searchData.results
                : Array.isArray(searchData) && searchData.length > 0
                ? searchData
                : [];
            if (apiResults.length > 0) {
              const bestCandidate =
                apiResults.find(
                  (item) =>
                    normalizeCityLookupText(
                      item.nom || (item as any).city_name || ""
                    ) === cleanLookup
                ) || apiResults[0];
              const resolved = await resolveGeoCityToDestination(bestCandidate);
              if (resolved) {
                await onSelectDestinationAndSearch(resolved);
                return;
              }
            }
          }
        } catch (searchErr: any) {
          setGeonamesUnavailableMessage(
            "Recherche de villes indisponible — repli sur les 5 destinations populaires."
          );
        }
      }

      // 5. Dernier repli partiel sur les villes populaires ou affichage d'erreur + carte de repli
      const partialSeedMatch = popularDestinations.find(
        (d) =>
          normalizeCityLookupText(d.city_name).includes(cleanLookup) ||
          cleanLookup.includes(normalizeCityLookupText(d.city_name))
      );
      if (partialSeedMatch) {
        await onSelectDestinationAndSearch(partialSeedMatch);
        return;
      }

      setUnavailableCity(trimmed);
      setSearchError(
        `La destination « ${trimmed} » est introuvable ou indisponible. Veuillez vérifier l'orthographe ou choisir l'une des destinations ci-dessous.`
      );
      setAutocompleteOpen(false);
    } catch (err: any) {
      setSearchError(
        err instanceof Error
          ? err.message
          : "Une erreur est survenue lors de la création du voyage. Veuillez réessayer."
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handlePickAvailableDestination(dest: Destination) {
    setUnavailableCity(null);
    setSearchError(null);
    setSelectedGeoCity(null);
    setCityQuery(dest.city_name);
    setAutocompleteOpen(false);
    setIsSubmitting(true);
    try {
      await onSelectDestinationAndSearch(dest);
    } catch (err: any) {
      setSearchError(
        err instanceof Error
          ? err.message
          : "Impossible de créer le voyage pour cette destination."
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  const formattedDateRange = useMemo(() => {
    try {
      const f = format(parseISO(departureDate), "d MMM", { locale: fr }).toLowerCase();
      const t = format(parseISO(returnDate), "d MMM", { locale: fr }).toLowerCase();
      return `${f} – ${t}`;
    } catch {
      return "10 nov. – 17 nov.";
    }
  }, [departureDate, returnDate]);

  return (
    <div className="pb-16" data-testid="home-screen">
      {/* Bandeau Hero : overflow-visible sur le bandeau et tous ses parents pour que la liste passe par-dessus */}
      <section
        className="relative z-30 mx-auto max-w-6xl px-4 pt-6 sm:pt-8 overflow-visible"
        style={{ overflow: "visible" }}
      >
        <div
          data-testid="home-hero-banner"
          className="relative overflow-visible rounded-card bg-slate-900 shadow-card min-h-[420px] sm:min-h-[460px] flex flex-col justify-end"
          style={{ overflow: "visible" }}
        >
          {/* Fond photo isolé avec coins arrondis pour ne jamais rogner la liste d'autocomplétion */}
          <div className="pointer-events-none absolute inset-0 overflow-hidden rounded-card">
            <img
              src={
                popularDestinations[0]?.hero_image_url ||
                "https://images.unsplash.com/photo-1597212618440-806262de4f6b?auto=format&fit=crop&w=1400&q=80"
              }
              alt="Destination de voyage ensoleillée"
              width={1440}
              height={560}
              loading="eager"
              className="absolute inset-0 h-full w-full object-cover object-center opacity-80"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-slate-950/85 via-slate-950/45 to-slate-950/15" />
          </div>

          <div
            className="relative z-20 p-6 sm:p-10 md:p-12 w-full max-w-5xl overflow-visible"
            style={{ overflow: "visible" }}
          >
            <Badge variant="brand" className="mb-3 bg-white/95 text-brand-800 border-0">
              Voyages organisés sereinement
            </Badge>
            <h1 className="text-h1 sm:text-display text-white tracking-tight">
              Où commence votre prochain voyage ?
            </h1>
            <p className="mt-2 text-body text-slate-100 max-w-2xl">
              Choisissez votre destination, réservez votre vol et composez vos visites jour par jour à votre rythme.
            </p>

            {/* Formulaire de recherche sobre : overflow-visible + z-index élevé */}
            <form
              onSubmit={handleSubmitSearch}
              data-testid="home-search-form"
              style={{ overflow: "visible" }}
              className="relative z-30 mt-6 grid grid-cols-1 md:grid-cols-12 gap-3 rounded-card bg-canvas-card p-3.5 shadow-popover border border-border overflow-visible"
            >
              {/* Champ 1 : Où allez-vous ? avec autocomplétion GeoNames (3 lettres min, 300 ms, 8 lignes max) */}
              <div
                ref={searchBoxRef}
                style={{ overflow: "visible" }}
                className="relative z-50 md:col-span-4 overflow-visible"
              >
                <label
                  htmlFor="home-destination-input"
                  className="flex items-baseline justify-between text-caption font-medium text-ink-secondary mb-1 pl-1"
                >
                  <span>Où allez-vous ?</span>
                  <span
                    data-testid="home-destination-helper"
                    className="text-[11px] font-normal text-ink-muted"
                  >
                    Ville ou pays
                  </span>
                </label>
                <div className="relative">
                  <MapPin className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-brand-700" />
                  <Input
                    id="home-destination-input"
                    data-testid="home-destination-input"
                    value={cityQuery}
                    onFocus={() => setAutocompleteOpen(true)}
                    onChange={(e) => {
                      setCityQuery(e.target.value);
                      setSelectedGeoCity(null);
                      setUnavailableCity(null);
                      setSearchError(null);
                      setAutocompleteOpen(true);
                      setActiveOptionIndex(-1);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Escape") {
                        setAutocompleteOpen(false);
                        setActiveOptionIndex(-1);
                        return;
                      }
                      if (e.key === "ArrowDown") {
                        e.preventDefault();
                        setAutocompleteOpen(true);
                        if (displaySuggestions.length > 0) {
                          setActiveOptionIndex(
                            (prev) => (prev + 1) % displaySuggestions.length
                          );
                        }
                        return;
                      }
                      if (e.key === "ArrowUp") {
                        e.preventDefault();
                        setAutocompleteOpen(true);
                        if (displaySuggestions.length > 0) {
                          setActiveOptionIndex(
                            (prev) =>
                              (prev - 1 + displaySuggestions.length) %
                              displaySuggestions.length
                          );
                        }
                        return;
                      }
                      if (
                        e.key === "Enter" &&
                        autocompleteOpen &&
                        activeOptionIndex >= 0 &&
                        activeOptionIndex < displaySuggestions.length
                      ) {
                        e.preventDefault();
                        handleSelectHomeSuggestion(
                          displaySuggestions[activeOptionIndex]
                        );
                      }
                    }}
                    placeholder="Ville ou pays"
                    autoComplete="off"
                    className="pl-9"
                  />
                </div>

                {/* Menu d'autocomplétion passant par-dessus le bandeau photo (z-[100], 8 lignes max) */}
                {autocompleteOpen && (
                  <div
                    role="listbox"
                    aria-label="Suggestions de villes"
                    data-testid="home-autocomplete-list"
                    style={{ zIndex: 100 }}
                    className="absolute left-0 right-0 top-full z-[100] mt-1.5 rounded-card border border-border bg-canvas-card p-1.5 shadow-popover"
                  >
                    {geonamesUnavailableMessage && (
                      <div
                        data-testid="autocomplete-unavailable-notice"
                        className="mb-1.5 rounded-md bg-feedback-warningBg px-2.5 py-1.5 text-[12px] font-medium text-amber-900"
                      >
                        {geonamesUnavailableMessage}
                      </div>
                    )}

                    {!geonamesUnavailableMessage && cityQuery.trim().length < 3 ? (
                      <div
                        data-testid="autocomplete-min-chars-hint"
                        className="px-3 py-2 text-caption text-ink-muted"
                      >
                        Tapez au moins 3 lettres pour chercher dans le monde entier
                      </div>
                    ) : isSearchingGeonames ? (
                      <div
                        data-testid="autocomplete-loading"
                        className="space-y-2 px-3 py-2"
                      >
                        <Skeleton className="h-4 w-2/3" />
                        <Skeleton className="h-3 w-1/2" />
                        <div className="text-[11px] text-ink-muted">
                          Recherche des villes du monde...
                        </div>
                      </div>
                    ) : displaySuggestions.length === 0 ? (
                      <div
                        data-testid="autocomplete-empty"
                        className="px-3 py-2 text-caption text-ink-muted"
                      >
                        Aucune ville trouvée pour {cityQuery.trim()}
                      </div>
                    ) : (
                      displaySuggestions.slice(0, 8).map((item, idx) => {
                        const subtitle = formatGeoCitySubtitle(item);
                        const airportBadge = formatGeoAirportBadge(item);
                        const isHighlighted = idx === activeOptionIndex;
                        const slug = item.nom
                          .replace(/^Région\s*:\s*/i, "")
                          .trim()
                          .toLowerCase();
                        return (
                          <button
                            key={`${item.geonameId}-${item.nom}-${idx}`}
                            type="button"
                            role="option"
                            aria-selected={isHighlighted || cityQuery === item.nom}
                            data-testid={
                              item.is_region
                                ? `autocomplete-region-${slug}`
                                : `autocomplete-city-${slug}`
                            }
                            onMouseEnter={() => setActiveOptionIndex(idx)}
                            onClick={() => handleSelectHomeSuggestion(item)}
                            className={`flex w-full items-center justify-between gap-2 rounded-md px-3 py-1 leading-tight text-left transition-colors focus:outline-none ${
                              isHighlighted
                                ? "bg-brand-50 text-brand-900"
                                : "hover:bg-brand-50 focus:bg-brand-50"
                            }`}
                          >
                            <div className="min-w-0">
                              <div className="text-[13px] font-medium text-ink truncate leading-tight">
                                {item.nom}
                              </div>
                              <div className="text-[11px] text-ink-muted truncate leading-tight">
                                {subtitle}
                              </div>
                            </div>
                            <div className="flex items-center gap-1.5 shrink-0">
                              {airportBadge && (
                                <Badge
                                  variant="neutral"
                                  className="text-[11px] px-1.5 py-0.5"
                                >
                                  {airportBadge}
                                </Badge>
                              )}
                              <span className="text-caption text-brand-700 font-medium">
                                Choisir
                              </span>
                            </div>
                          </button>
                        );
                      })
                    )}
                  </div>
                )}
              </div>

              {/* Champ 2 : Dates (Calendrier react-day-picker + saisie directe) */}
              <div className="md:col-span-3">
                <label className="block text-caption font-medium text-ink-secondary mb-1 pl-1">
                  Dates du séjour
                </label>
                <Popover.Root open={calendarOpen} onOpenChange={setCalendarOpen}>
                  <Popover.Trigger asChild>
                    <button
                      type="button"
                      data-testid="home-dates-trigger"
                      className="flex h-11 w-full items-center gap-2 rounded-card border border-border bg-canvas-card px-3 text-left text-body text-ink hover:bg-canvas-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700"
                    >
                      <CalendarIcon className="h-4 w-4 text-brand-700 shrink-0" />
                      <span className="truncate">{formattedDateRange}</span>
                    </button>
                  </Popover.Trigger>
                  <Popover.Portal>
                    <Popover.Content
                      align="start"
                      sideOffset={8}
                      className="z-50 rounded-card border border-border bg-canvas-card p-4 shadow-popover"
                    >
                      <div className="mb-3 grid grid-cols-2 gap-2 border-b border-border pb-3">
                        <div>
                          <label
                            htmlFor="home-departure-date-input"
                            className="block text-[11px] font-semibold text-ink-secondary mb-1"
                          >
                            Départ
                          </label>
                          <input
                            id="home-departure-date-input"
                            data-testid="home-departure-date-input"
                            type="date"
                            value={normalizeIsoDateInput(departureDate, "2026-11-10")}
                            onChange={(e) => {
                              const nextDep = e.target.value;
                              if (!nextDep) return;
                              setSearchError(null);
                              onChangeDates(nextDep, returnDate);
                            }}
                            className="h-9 w-full rounded-md border border-border bg-canvas-card px-2 text-caption text-ink"
                          />
                        </div>
                        <div>
                          <label
                            htmlFor="home-return-date-input"
                            className="block text-[11px] font-semibold text-ink-secondary mb-1"
                          >
                            Retour
                          </label>
                          <input
                            id="home-return-date-input"
                            data-testid="home-return-date-input"
                            type="date"
                            value={normalizeIsoDateInput(returnDate, "2026-11-17")}
                            onChange={(e) => {
                              const nextRet = e.target.value;
                              if (!nextRet) return;
                              setSearchError(null);
                              onChangeDates(departureDate, nextRet);
                            }}
                            className="h-9 w-full rounded-md border border-border bg-canvas-card px-2 text-caption text-ink"
                          />
                        </div>
                      </div>
                      <DayPicker
                        mode="range"
                        locale={fr}
                        selected={selectedRange}
                        defaultMonth={selectedRange.from}
                        onSelect={(range) => {
                          if (range?.from) {
                            const dep = format(range.from, "yyyy-MM-dd");
                            const rawRet = range.to
                              ? format(range.to, "yyyy-MM-dd")
                              : "";
                            const ret =
                              rawRet && rawRet > dep ? rawRet : addDaysIso(dep, 7);
                            setSearchError(null);
                            onChangeDates(dep, ret);
                          }
                        }}
                      />
                      <div className="mt-3 flex justify-end border-t border-border pt-3">
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => setCalendarOpen(false)}
                        >
                          Valider ces dates
                        </Button>
                      </div>
                    </Popover.Content>
                  </Popover.Portal>
                </Popover.Root>
              </div>

              {/* Champ 3 : Voyageurs */}
              <div className="md:col-span-3">
                <label className="block text-caption font-medium text-ink-secondary mb-1 pl-1">
                  Voyageurs
                </label>
                <Select
                  value={travelers}
                  onValueChange={onChangeTravelers}
                  ariaLabel="Nombre de voyageurs"
                  options={[
                    { value: "1", label: "1 voyageur" },
                    { value: "2", label: "2 voyageurs" },
                    { value: "3", label: "3 voyageurs" },
                    { value: "4", label: "4 voyageurs" },
                  ]}
                />
              </div>

              {/* Action principale : Bouton Rechercher */}
              <div className="md:col-span-2 flex items-end">
                <Button
                  type="submit"
                  size="md"
                  disabled={isSubmitting}
                  data-testid="home-search-btn"
                  className="w-full h-11 font-semibold"
                >
                  <Search className="h-4 w-4" />
                  <span>{isSubmitting ? "Recherche..." : "Rechercher"}</span>
                </Button>
              </div>
            </form>

            {/* Message d'erreur visible en cas d'échec API ou de blocage de validation front-end */}
            {searchError && (
              <div
                role="alert"
                data-testid="home-search-error"
                className="mt-3 flex items-center justify-between gap-3 rounded-card border border-red-300 bg-red-50 px-4 py-3 text-caption font-semibold text-red-900 shadow-sm"
              >
                <div className="flex items-center gap-2">
                  <AlertCircle className="h-4 w-4 text-red-700 shrink-0" />
                  <span>{searchError}</span>
                </div>
                <button
                  type="button"
                  onClick={() => setSearchError(null)}
                  className="text-[12px] font-medium text-red-700 underline hover:text-red-900 shrink-0"
                >
                  Fermer
                </button>
              </div>
            )}

            {/* Constructeur d'itinéraire multi-villes (destinations multiples sans chevauchement de dates) */}
            <div className="mx-auto max-w-4xl">
              <HomeMultiCityBuilder
                destinationsCatalog={
                  popularDestinations.length > 0 ? popularDestinations : destinations
                }
                apiBase={API_BASE}
                enabled={multiCityEnabled}
                onToggleEnabled={(next: boolean) => {
                  setMultiCityEnabled(next);
                  setMultiCitySubmitError("");
                  setSearchError(null);
                }}
                stages={draftStages}
                onChangeStages={(nextStages: DraftStageFormItem[]) => {
                  setDraftStages(nextStages);
                  setMultiCitySubmitError("");
                  setSearchError(null);
                  if (nextStages.length > 0) {
                    const firstArr = nextStages[0].arrival_date;
                    const lastDep = nextStages[nextStages.length - 1].departure_date;
                    if (firstArr && lastDep) {
                      onChangeDates(firstArr, lastDep);
                    }
                  }
                }}
              />
              {multiCityEnabled && (
                <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                  {multiCitySubmitError ? (
                    <span
                      className="text-caption font-semibold text-red-700 bg-white/95 px-3 py-1.5 rounded-md border border-red-200"
                      data-testid="home-multi-city-submit-error"
                    >
                      {multiCitySubmitError}
                    </span>
                  ) : (
                    <span className="text-caption text-white/90 font-medium">
                      Chaque étape suit immédiatement la précédente sans chevauchement.
                    </span>
                  )}
                  <Button
                    type="button"
                    size="md"
                    disabled={isSubmitting || !validateDraftStagesNoOverlap(draftStages).valid}
                    data-testid="create-multi-city-trip-btn"
                    onClick={() => handleSubmitMultiCityStages("/trip")}
                  >
                    <span>
                      {isSubmitting
                        ? "Création..."
                        : `Créer ce voyage multi-villes (${draftStages.length} étapes)`}
                    </span>
                  </Button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Bandeau de repli si GeoNames est injoignable, quota atteint ou clé absente */}
        {geonamesUnavailableMessage && (
          <Card
            data-testid="geonames-unavailable-banner"
            className="mt-4 border-amber-200 bg-feedback-warningBg p-4"
          >
            <p className="text-body font-semibold text-ink">
              {geonamesUnavailableMessage}
            </p>
            <div className="mt-2.5 flex flex-wrap gap-2">
              {popularDestinations.map((dest) => (
                <Button
                  key={dest.id}
                  type="button"
                  variant="secondary"
                  size="sm"
                  data-testid={`geonames-fallback-dest-${dest.city_name.toLowerCase()}`}
                  onClick={() => handlePickAvailableDestination(dest)}
                >
                  <MapPin className="h-3.5 w-3.5 text-brand-700" />
                  <span>
                    {dest.city_name} ({dest.country_name})
                  </span>
                </Button>
              ))}
            </div>
          </Card>
        )}

        {/* Message contextuel sobre si la ville saisie est introuvable */}
        {unavailableCity && (
          <Card
            data-testid="unavailable-demo-city-card"
            className="mt-4 border-amber-200 bg-feedback-warningBg p-5"
          >
            <p className="text-body font-semibold text-ink">
              Cette destination n'est pas encore disponible en démonstration
            </p>
            <p className="mt-1 text-caption text-ink-secondary">
              Vous avez recherché « {unavailableCity} ». Choisissez l'une des 5 destinations populaires ci-dessous :
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {popularDestinations.map((dest) => (
                <Button
                  key={dest.id}
                  type="button"
                  variant="secondary"
                  size="sm"
                  data-testid={`fallback-dest-${dest.city_name.toLowerCase()}`}
                  onClick={() => handlePickAvailableDestination(dest)}
                >
                  <MapPin className="h-3.5 w-3.5 text-brand-700" />
                  <span>
                    {dest.city_name} ({dest.country_name})
                  </span>
                </Button>
              ))}
            </div>
          </Card>
        )}
      </section>

      {/* Dessous : Les 5 villes du seed restent proposées en destinations populaires */}
      <section className="mx-auto max-w-6xl px-4 mt-12">
        <div className="flex flex-wrap items-end justify-between gap-4 mb-6">
          <div>
            <h2 className="text-h1 text-ink">Destinations populaires</h2>
            <p className="mt-1 text-body text-ink-muted">
              Sélectionnez une ville pour consulter les vols disponibles et préparer votre séjour.
            </p>
          </div>
        </div>

        {isLoadingDestinations ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[1, 2, 3].map((n) => (
              <Card key={n} className="overflow-hidden">
                <Skeleton className="aspect-[4/3] w-full rounded-none" />
                <div className="p-5 space-y-3">
                  <Skeleton className="h-6 w-1/2" />
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-2/3" />
                </div>
              </Card>
            ))}
          </div>
        ) : (
          <div
            className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"
            data-testid="popular-destinations-grid"
          >
            {popularDestinations.map((dest) => (
              <Card
                key={dest.id}
                data-testid={`destination-card-${dest.city_name.toLowerCase()}`}
                onClick={() => handlePickAvailableDestination(dest)}
                className="group cursor-pointer overflow-hidden transition-all hover:shadow-card hover:border-brand-600/40 flex flex-col"
              >
                <div className="relative aspect-[4/3] w-full overflow-hidden bg-canvas-subtle">
                  <img
                    src={dest.hero_image_url}
                    alt={`${dest.city_name}, ${dest.country_name}`}
                    width={640}
                    height={480}
                    loading="eager"
                    referrerPolicy="no-referrer"
                    className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
                  />
                  <div className="absolute top-3 left-3">
                    <Badge className="bg-white/95 text-ink border-0 shadow-sm">
                      {dest.country_name}
                    </Badge>
                  </div>
                </div>
                <div className="p-5 flex-1 flex flex-col justify-between">
                  <div>
                    <h3 className="text-h2 text-ink group-hover:text-brand-700 transition-colors">
                      {dest.city_name}
                    </h3>
                    <p className="mt-1.5 text-caption text-ink-secondary line-clamp-2">
                      {dest.description}
                    </p>
                  </div>
                  <div className="mt-4 pt-3 border-t border-border flex items-center justify-between text-caption font-medium text-brand-700">
                    <span>Voir les vols pour {dest.city_name}</span>
                    <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                  </div>
                </div>
              </Card>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

/* ============================================================================
 * 2. ÉCRAN VOLS (/flights)
 * ========================================================================== */
function FlightsScreen({
  activeTrip,
  activeDestination,
  destinations,
  originIata,
  onChangeOriginIata,
  departureOrigin,
  onChangeDepartureOrigin,
  departureDate,
  returnDate,
  travelers,
  onSelectDestination,
  onRegisterCreatedDestination,
  onBookSuccess,
  token,
}: {
  activeTrip: Trip | null;
  activeDestination: Destination | null;
  destinations: Destination[];
  originIata: string;
  onChangeOriginIata: (val: string) => void;
  departureOrigin: RememberedDepartureOrigin;
  onChangeDepartureOrigin: (origin: RememberedDepartureOrigin) => void;
  departureDate: string;
  returnDate: string;
  travelers: string;
  onSelectDestination: (dest: Destination) => Promise<void>;
  onRegisterCreatedDestination?: (dest: Destination) => void;
  onBookSuccess: (booking: FlightBooking) => void;
  token: string;
}) {
  const navigate = useNavigate();
  const { notify } = useToast();
  const [sortBy, setSortBy] = useState<"cheapest" | "fastest">("cheapest");
  const [bookingError, setBookingError] = useState<string>("");
  const [bookingOfferId, setBookingOfferId] = useState<string | null>(null);

  const popularDestinations = useMemo(() => {
    const seedList = destinations.filter((d) =>
      SEED_POPULAR_CITY_NAMES.has(d.city_name.trim().toLowerCase())
    );
    return seedList.length > 0 ? seedList : destinations.slice(0, 5);
  }, [destinations]);

  const destinationCity = activeDestination?.city_name || "Marrakech";
  const destinationIata = activeDestination?.iata_code || "RAK";
  const effectiveOrigin =
    toCityComparatorCode(originIata) === toCityComparatorCode(destinationIata)
      ? "LHR"
      : originIata;

  const {
    data: offers = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery<FlightOffer[]>({
    queryKey: [
      "flights-search",
      activeTrip?.id || null,
      effectiveOrigin,
      destinationIata,
      departureDate,
      returnDate,
    ],
    queryFn: async () => {
      const params = new URLSearchParams({
        origin_iata: effectiveOrigin,
        departure_date: departureDate,
        return_date: returnDate,
        travel_style: activeTrip?.travel_style || "STANDARD",
      });
      if (activeTrip?.id) {
        params.set("trip_id", activeTrip.id);
      } else {
        params.set("destination_iata", destinationIata);
      }
      const resp = await fetch(`${API_BASE}/api/v1/flights/search?${params.toString()}`);
      if (!resp.ok) {
        const err = await resp.json().catch(() => null);
        throw new Error(
          humanErrorMessage(
            err,
            "Impossible de charger les vols pour ces dates. Veuillez vérifier votre sélection."
          )
        );
      }
      return resp.json();
    },
  });

  const sortedOffers = useMemo(() => {
    const copy = [...offers];
    if (sortBy === "cheapest") {
      copy.sort((a, b) => Number(a.price_amount) - Number(b.price_amount));
    } else {
      copy.sort((a, b) => {
        const durA =
          (a.duration_outbound_minutes ||
            computeDurationMinutes(a.departure_outbound_at, a.arrival_outbound_at)) +
          (a.duration_inbound_minutes ||
            computeDurationMinutes(a.departure_inbound_at, a.arrival_inbound_at));
        const durB =
          (b.duration_outbound_minutes ||
            computeDurationMinutes(b.departure_outbound_at, b.arrival_outbound_at)) +
          (b.duration_inbound_minutes ||
            computeDurationMinutes(b.departure_inbound_at, b.arrival_inbound_at));
        return durA - durB;
      });
    }
    return copy;
  }, [offers, sortBy]);

  const depDateIso = (
    departureDate ||
    (activeTrip?.arrival_at ? activeTrip.arrival_at.slice(0, 10) : "2026-11-10")
  ).slice(0, 10);
  const retDateIso = (
    returnDate ||
    (activeTrip?.departure_at ? activeTrip.departure_at.slice(0, 10) : "2026-11-17")
  ).slice(0, 10);

  const comparatorLinks = useMemo(() => {
    const firstUrls = sortedOffers[0]?.comparator_urls;
    const origCityCode =
      firstUrls?.origin_code ||
      sortedOffers[0]?.origin_city_code ||
      toCityComparatorCode(effectiveOrigin);
    const destCityCode =
      firstUrls?.destination_code ||
      sortedOffers[0]?.destination_city_code ||
      toCityComparatorCode(destinationIata);

    const googleUrl =
      firstUrls?.google_flights ||
      `https://www.google.com/travel/flights?hl=fr&curr=EUR&q=${encodeURIComponent(
        `Vols ${origCityCode} ${destCityCode} ${depDateIso} ${retDateIso}`
      )}`;
    const kayakUrl =
      firstUrls?.kayak ||
      `https://www.kayak.fr/flights/${encodeURIComponent(
        origCityCode
      )}-${encodeURIComponent(destCityCode)}/${encodeURIComponent(
        depDateIso
      )}/${encodeURIComponent(retDateIso)}`;
    const skyscannerUrl =
      firstUrls?.skyscanner ||
      `https://www.skyscanner.fr/transport/vols/${encodeURIComponent(
        origCityCode.toLowerCase()
      )}/${encodeURIComponent(destCityCode.toLowerCase())}/${encodeURIComponent(
        depDateIso
      )}/${encodeURIComponent(retDateIso)}/`;

    return {
      originCode: origCityCode,
      destinationCode: destCityCode,
      google: googleUrl,
      kayak: kayakUrl,
      skyscanner: skyscannerUrl,
    };
  }, [sortedOffers, effectiveOrigin, destinationIata, depDateIso, retDateIso]);

  const bookMutation = useMutation({
    mutationFn: async (offer: FlightOffer) => {
      if (!token) {
        navigate("/login");
        throw new Error("Veuillez vous connecter pour confirmer votre réservation.");
      }
      if (!activeTrip?.id) {
        throw new Error("Sélectionnez une destination avant de réserver votre vol.");
      }
      setBookingOfferId(offer.offer_id);
      setBookingError("");

      const idemKey = `res-${activeTrip.id.slice(0, 8)}-${offer.offer_id}`;
      const resp = await fetch(`${API_BASE}/api/v1/flights/book`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          trip_id: activeTrip.id,
          idempotency_key: idemKey,
          airline: offer.airline_name,
          flight_number_outbound: offer.flight_number_outbound,
          flight_number_inbound: offer.flight_number_inbound,
          origin_iata: offer.origin_iata,
          destination_iata: offer.destination_iata,
          departure_outbound_at: offer.departure_outbound_at,
          arrival_outbound_at: offer.arrival_outbound_at,
          departure_inbound_at: offer.departure_inbound_at,
          arrival_inbound_at: offer.arrival_inbound_at,
          price_amount: String(offer.price_amount),
          currency: offer.currency,
          cabin_class: offer.cabin_class,
        }),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => null);
        throw new Error(
          humanErrorMessage(
            err,
            "La réservation n'a pas pu être finalisée. Merci de réessayer."
          )
        );
      }
      return (await resp.json()) as FlightBooking;
    },
    onSuccess: (booking) => {
      setBookingOfferId(null);
      notify({
        title: "Réservation confirmée",
        description: `Votre vol pour ${destinationCity} est confirmé.`,
        tone: "success",
      });
      onBookSuccess(booking);
      navigate("/flights/confirmation");
    },
    onError: (err: any) => {
      setBookingOfferId(null);
      setBookingError(err?.message || "Impossible de réserver ce vol pour le moment.");
    },
  });

  const arrivalAirportLabel = useMemo(() => {
    if (activeDestination?.airport_display_label) {
      return activeDestination.airport_display_label;
    }
    if (
      activeDestination?.airport_within_100km === false &&
      typeof activeDestination?.nearest_airport_distance_km === "number"
    ) {
      return `${destinationCity} (${destinationIata} — à ${Math.round(
        activeDestination.nearest_airport_distance_km
      )} km)`;
    }
    return (
      AIRPORT_CITY_NAMES[destinationIata] || `${destinationCity} (${destinationIata})`
    );
  }, [activeDestination, destinationCity, destinationIata]);

  const originAirportLabel = useMemo(() => {
    if (
      departureOrigin &&
      departureOrigin.iataCode.toUpperCase() === effectiveOrigin.toUpperCase() &&
      departureOrigin.displayLabel
    ) {
      return departureOrigin.displayLabel;
    }
    return AIRPORT_CITY_NAMES[effectiveOrigin] || `${effectiveOrigin}`;
  }, [departureOrigin, effectiveOrigin]);

  function handleSelectDepartureCity(item: GeoNamesCitySearchItem) {
    const cleanCity = item.nom.replace(/^Région\s*:\s*/i, "").trim();
    const iata = (item.iata_code || "CDG").trim().toUpperCase();
    const within100 =
      typeof item.airport_within_100km === "boolean"
        ? item.airport_within_100km
        : true;
    const dist =
      typeof item.nearest_airport_distance_km === "number"
        ? item.nearest_airport_distance_km
        : undefined;
    const label =
      item.airport_display_label ||
      (!within100 && dist != null
        ? `${cleanCity} (${iata} — à ${Math.round(dist)} km)`
        : `${cleanCity} (${iata})`);
    const nextOrigin: RememberedDepartureOrigin = {
      cityName: cleanCity,
      countryName: item.pays,
      regionName: item.region || item.region_name,
      iataCode: iata,
      airportName: item.airport_name,
      distanceKm: dist,
      within100Km: within100,
      displayLabel: label,
    };
    onChangeOriginIata(iata);
    onChangeDepartureOrigin(nextOrigin);
  }

  async function handleSelectArrivalCity(item: GeoNamesCitySearchItem) {
    const cleanCityName = item.nom.replace(/^Région\s*:\s*/i, "").trim();
    const existingSeed = destinations.find(
      (d) =>
        (item.destination_id && d.id === item.destination_id) ||
        d.city_name.trim().toLowerCase() === cleanCityName.toLowerCase()
    );
    if (
      existingSeed &&
      SEED_POPULAR_CITY_NAMES.has(existingSeed.city_name.trim().toLowerCase())
    ) {
      await onSelectDestination(existingSeed);
      return;
    }

    try {
      const resp = await fetch(`${API_BASE}/api/v1/destinations/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          geonameId: item.geonameId,
          nom: cleanCityName,
          pays: item.pays,
          code_pays: item.code_pays,
          region: item.region || item.region_name || null,
          sous_titre: item.sous_titre || null,
          coordonnees: item.coordonnees,
          fuseau_horaire: item.fuseau_horaire,
          population: item.population,
          iata_code: item.iata_code,
        }),
      });
      if (resp.ok) {
        const resolvedDest: Destination = await resp.json();
        onRegisterCreatedDestination?.(resolvedDest);
        await onSelectDestination(resolvedDest);
        return;
      }
    } catch {
      // Fallback
    }
    if (existingSeed) {
      await onSelectDestination(existingSeed);
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:py-10" data-testid="flights-screen">
      {/* En-tête sobre : aéroport d'arrivée OurAirports issu de la destination, départ mémorisé et modifiable */}
      <div className="mb-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <Badge variant="brand" className="mb-2">
              Aller-retour • {travelers} {Number(travelers) > 1 ? "voyageurs" : "voyageur"}
            </Badge>
            <h1 className="text-h1 text-ink" data-testid="flights-heading">
              Vols vers {destinationCity}
            </h1>
            <p
              className="mt-1 text-body text-ink-muted"
              data-testid="flights-route-subtitle"
            >
              Départ de {originAirportLabel} → Arrivée à {arrivalAirportLabel}
            </p>
          </div>
          <Link
            to="/"
            className="text-caption font-medium text-brand-700 hover:text-brand-800 underline underline-offset-4"
          >
            Changer de destination ou de dates
          </Link>
        </div>

        {/* Barre sobre de paramètres : autocomplétion GeoNames pour départ + destination + tri */}
        <Card
          className="mt-5 p-4 relative z-20 overflow-visible"
          style={{ overflow: "visible" }}
        >
          <div
            className="grid grid-cols-1 sm:grid-cols-3 gap-4 items-end overflow-visible"
            style={{ overflow: "visible" }}
          >
            <div className="overflow-visible" style={{ overflow: "visible" }}>
              <label
                htmlFor="flights-origin-input"
                className="block text-caption font-medium text-ink-secondary mb-1"
              >
                Aéroport de départ
              </label>
              <GeoNamesCityAutocompleteField
                inputId="flights-origin-input"
                inputTestId="flights-origin-input"
                listTestId="flights-origin-autocomplete-list"
                ariaLabel="Aéroport de départ"
                placeholder="Ville ou pays"
                displayValue={originAirportLabel}
                popularDestinations={popularDestinations}
                onSelectCityItem={handleSelectDepartureCity}
              />
            </div>

            <div className="overflow-visible" style={{ overflow: "visible" }}>
              <label
                htmlFor="flights-destination-input"
                className="block text-caption font-medium text-ink-secondary mb-1"
              >
                Destination du séjour
              </label>
              <GeoNamesCityAutocompleteField
                inputId="flights-destination-input"
                inputTestId="flights-destination-input"
                listTestId="flights-destination-autocomplete-list"
                ariaLabel="Destination du séjour"
                placeholder="Ville ou pays"
                displayValue={arrivalAirportLabel}
                popularDestinations={popularDestinations}
                onSelectCityItem={handleSelectArrivalCity}
              />
            </div>

            <div>
              <span className="block text-caption font-medium text-ink-secondary mb-1">
                Trier les vols par
              </span>
              <div
                role="group"
                aria-label="Trier les vols"
                className="grid grid-cols-2 gap-2"
              >
                <Button
                  type="button"
                  size="sm"
                  variant={sortBy === "cheapest" ? "primary" : "secondary"}
                  data-testid="sort-cheapest-btn"
                  onClick={() => setSortBy("cheapest")}
                  className="h-11"
                >
                  Moins cher
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={sortBy === "fastest" ? "primary" : "secondary"}
                  data-testid="sort-fastest-btn"
                  onClick={() => setSortBy("fastest")}
                  className="h-11"
                >
                  Plus rapide
                </Button>
              </div>
            </div>
          </div>
        </Card>

        {/* Bandeau Offres d'exemple, prix indicatifs + bouton Voir les vrais prix (Google Flights, Kayak, Skyscanner) */}
        <div
          data-testid="flights-example-offers-banner"
          className="mt-4 rounded-card border border-brand-200 bg-brand-50/70 px-4 py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
        >
          <div className="space-y-0.5">
            <div className="text-caption font-semibold text-brand-900">
              {sortedOffers[0]?.banner_text || "Offres d'exemple, prix indicatifs"}
            </div>
            <p className="text-caption text-ink-secondary">
              Ces horaires et tarifs sont proposés à titre indicatif pour organiser votre séjour ({comparatorLinks.originCode} → {comparatorLinks.destinationCode}).
            </p>
          </div>

          <div
            className="flex flex-wrap items-center gap-2"
            data-testid="flights-real-prices-bar"
          >
            <a
              href={comparatorLinks.google}
              target="_blank"
              rel="noopener noreferrer"
              data-testid="flights-real-prices-btn"
              className="inline-flex items-center justify-center gap-1.5 rounded-control px-3.5 py-2 text-xs font-semibold bg-accent text-white hover:bg-accent-hover shadow-subtle transition-colors"
            >
              <span>Voir les vrais prix</span>
              <span aria-hidden="true">↗</span>
            </a>

            <div
              className="inline-flex flex-wrap items-center gap-1.5 rounded-control border border-border bg-white px-2.5 py-1.5 text-xs"
              role="group"
              aria-label="Choisir un comparateur de vols"
              data-testid="flights-compare-menu"
            >
              <a
                href={comparatorLinks.google}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="flights-compare-google"
                className="inline-flex items-center gap-1 rounded px-2 py-0.5 font-semibold text-accent hover:bg-canvas-subtle transition-colors"
              >
                Google Flights ↗
              </a>
              <span className="text-border" aria-hidden="true">
                •
              </span>
              <a
                href={comparatorLinks.kayak}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="flights-compare-kayak"
                className="inline-flex items-center gap-1 rounded px-2 py-0.5 font-semibold text-accent hover:bg-canvas-subtle transition-colors"
              >
                Kayak ↗
              </a>
              <span className="text-border" aria-hidden="true">
                •
              </span>
              <a
                href={comparatorLinks.skyscanner}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="flights-compare-skyscanner"
                className="inline-flex items-center gap-1 rounded px-2 py-0.5 font-semibold text-accent hover:bg-canvas-subtle transition-colors"
              >
                Skyscanner ↗
              </a>
            </div>
          </div>
        </div>
      </div>

      {/* Message d'erreur humain contextuel le cas échéant */}
      {bookingError && (
        <Card
          data-testid="flights-context-error"
          className="mb-6 border-red-200 bg-feedback-dangerBg p-4 text-feedback-danger"
        >
          <p className="text-body font-medium">{bookingError}</p>
        </Card>
      )}

      {/* État 1 : Chargement en squelettes */}
      {isLoading ? (
        <div className="space-y-4" data-testid="flights-skeleton-list">
          {[1, 2, 3].map((n) => (
            <Card key={n} className="p-6">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="space-y-3 flex-1">
                  <Skeleton className="h-5 w-40" />
                  <Skeleton className="h-6 w-3/4" />
                  <Skeleton className="h-6 w-3/4" />
                </div>
                <div className="sm:w-40 space-y-2">
                  <Skeleton className="h-8 w-24 sm:ml-auto" />
                  <Skeleton className="h-11 w-full" />
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : isError ? (
        /* État 2 : Erreur humaine dans le contexte */
        <Card className="p-8 text-center" data-testid="flights-error-state">
          <h2 className="text-h2 text-ink">
            Impossible d'afficher les vols pour le moment
          </h2>
          <p className="mt-2 text-body text-ink-muted max-w-md mx-auto">
            {(error as Error)?.message ||
              "Une difficulté temporaire empêche le chargement des horaires. Vous pouvez réessayer immédiatement."}
          </p>
          <div className="mt-5">
            <Button type="button" onClick={() => refetch()}>
              Actualiser les offres
            </Button>
          </div>
        </Card>
      ) : sortedOffers.length === 0 ? (
        /* État 3 : Liste vide */
        <Card className="p-8 text-center" data-testid="flights-empty-state">
          <h2 className="text-h2 text-ink" data-testid="flights-empty-title">
            Aucun vol trouvé pour ces critères
          </h2>
          <p className="mt-2 text-body text-ink-muted max-w-xl mx-auto">
            Essayez un autre aéroport de départ ou modifiez vos dates de voyage sur l'accueil.
          </p>
          <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
            <Button
              type="button"
              variant="primary"
              data-testid="flights-continue-accommodations-btn"
              onClick={() => navigate("/accommodations")}
            >
              Continuer vers l'hébergement
            </Button>
            <Button
              type="button"
              variant="secondary"
              data-testid="flights-continue-activities-btn"
              onClick={() => navigate("/activities")}
            >
              Voir les lieux de la ville
            </Button>
            <Button
              type="button"
              variant="secondary"
              data-testid="flights-modify-search-btn"
              onClick={() => navigate("/")}
            >
              Modifier ma recherche
            </Button>
          </div>
        </Card>
      ) : (
        /* Liste des offres en cartes sobres */
        <div className="space-y-4" data-testid="flights-offers-list">
          {sortedOffers.map((offer, idx) => {
            const outDuration =
              offer.duration_outbound_minutes ||
              computeDurationMinutes(
                offer.departure_outbound_at,
                offer.arrival_outbound_at
              );
            const inDuration =
              offer.duration_inbound_minutes ||
              computeDurationMinutes(
                offer.departure_inbound_at,
                offer.arrival_inbound_at
              );
            const stopoverText = offer.stopover_label || "Direct";
            const badgeText = offer.offer_badge || "Offre d'exemple";
            const priceLabelText = offer.price_label || "Prix indicatif";
            const isBookingThis = bookingOfferId === offer.offer_id;

            return (
              <Card
                key={offer.offer_id}
                data-testid={`flight-offer-card-${idx}`}
                className="p-5 sm:p-6 transition-shadow hover:shadow-card"
              >
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
                  <div className="flex-1 space-y-4">
                    {/* Compagnie ou liaison & étiquette Offre d'exemple */}
                    <div className="flex flex-wrap items-center gap-2.5">
                      <span
                        className="text-h2 font-semibold text-ink"
                        data-testid={`flight-offer-title-${idx}`}
                      >
                        {offer.airline_name}
                      </span>
                      <Badge
                        variant="brand"
                        data-testid={`flight-offer-badge-${idx}`}
                      >
                        {badgeText}
                      </Badge>
                      <Badge variant="neutral">
                        {cabinLabelHuman(offer.cabin_class)}
                      </Badge>
                      {idx === 0 && sortBy === "cheapest" && (
                        <Badge variant="brand">Meilleur tarif</Badge>
                      )}
                      {idx === 0 && sortBy === "fastest" && (
                        <Badge variant="brand">Le plus rapide</Badge>
                      )}
                    </div>

                    {/* Trajet Aller */}
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 items-center rounded-md bg-canvas-subtle px-4 py-3">
                      <div>
                        <div className="text-caption font-medium text-ink-muted">
                          Aller • {formatDateHuman(offer.departure_outbound_at)}
                        </div>
                        <div className="text-body font-semibold text-ink mt-0.5">
                          {formatTimeHuman(offer.departure_outbound_at)} →{" "}
                          {formatTimeHuman(offer.arrival_outbound_at)}
                        </div>
                      </div>
                      <div className="text-caption text-ink-secondary flex items-center gap-1.5">
                        <Clock className="h-3.5 w-3.5 text-brand-700" />
                        <span data-testid={`flight-stopover-label-${idx}`}>
                          Durée : {formatDurationHuman(outDuration)} • {stopoverText}
                        </span>
                      </div>
                      <div className="text-caption text-ink-secondary sm:text-right">
                        {originAirportLabel.split(" (")[0]} → {destinationCity}
                      </div>
                    </div>

                    {/* Trajet Retour */}
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 items-center rounded-md bg-canvas-subtle px-4 py-3">
                      <div>
                        <div className="text-caption font-medium text-ink-muted">
                          Retour • {formatDateHuman(offer.departure_inbound_at)}
                        </div>
                        <div className="text-body font-semibold text-ink mt-0.5">
                          {formatTimeHuman(offer.departure_inbound_at)} →{" "}
                          {formatTimeHuman(offer.arrival_inbound_at)}
                        </div>
                      </div>
                      <div className="text-caption text-ink-secondary flex items-center gap-1.5">
                        <Clock className="h-3.5 w-3.5 text-brand-700" />
                        <span>
                          Durée : {formatDurationHuman(inDuration)} • {stopoverText}
                        </span>
                      </div>
                      <div className="text-caption text-ink-secondary sm:text-right">
                        {destinationCity} → {originAirportLabel.split(" (")[0]}
                      </div>
                    </div>
                  </div>

                  {/* Prix indicatif & bouton Réserver */}
                  <div className="flex flex-row md:flex-col items-center md:items-end justify-between gap-3 pt-4 md:pt-0 border-t md:border-t-0 md:border-l border-border md:pl-6 min-w-[180px]">
                    <div className="md:text-right">
                      <div
                        className="text-caption font-semibold text-brand-800"
                        data-testid={`flight-price-label-${idx}`}
                      >
                        {priceLabelText}
                      </div>
                      <div
                        className="text-h1 font-bold text-ink"
                        data-testid={`flight-offer-price-${idx}`}
                      >
                        ~{Math.round(Number(offer.price_amount))} €
                      </div>
                      <div className="text-caption text-ink-muted">
                        Aller-retour compris
                      </div>
                    </div>
                    <Button
                      type="button"
                      size="md"
                      disabled={bookMutation.isPending}
                      data-testid={`book-flight-btn-${idx}`}
                      onClick={() => bookMutation.mutate(offer)}
                      className="w-auto md:w-full"
                    >
                      {isBookingThis ? "Confirmation..." : "Réserver"}
                    </Button>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ============================================================================
 * 2b. ÉCRAN CONFIRMATION DE VOL (/flights/confirmation)
 * ========================================================================== */
function FlightConfirmationScreen({
  booking,
  destination,
}: {
  booking: FlightBooking | null;
  destination: Destination | null;
}) {
  const navigate = useNavigate();

  if (!booking) {
    return (
      <div className="mx-auto max-w-xl px-4 py-16 text-center">
        <Card className="p-8">
          <h1 className="text-h1 text-ink">Aucune réservation récente</h1>
          <p className="mt-2 text-body text-ink-muted">
            Recherchez et choisissez un vol pour afficher votre confirmation de voyage.
          </p>
          <div className="mt-6">
            <Button type="button" onClick={() => navigate("/flights")}>
              Voir les vols disponibles
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  const cityLabel =
    destination?.city_name ||
    AIRPORT_CITY_NAMES[booking.destination_iata]?.split(" (")[0] ||
    "Votre destination";
  const originLabel =
    AIRPORT_CITY_NAMES[booking.origin_iata] || "Paris (Charles de Gaulle)";

  return (
    <div
      className="mx-auto max-w-2xl px-4 py-10 sm:py-12"
      data-testid="flight-confirmation-screen"
    >
      <Card className="p-6 sm:p-8">
        <div className="flex items-center gap-3 text-feedback-success mb-4">
          <CheckCircle2 className="h-8 w-8 shrink-0" />
          <div>
            <Badge variant="success">Vol réservé</Badge>
            <h1 className="text-h1 text-ink mt-1">Réservation confirmée</h1>
          </div>
        </div>

        <p className="text-body text-ink-secondary">
          Votre billet aller-retour pour <strong>{cityLabel}</strong> est enregistré.
          Un e-mail de confirmation vous a été envoyé et votre billet est conservé dans{" "}
          <strong>Mes documents</strong>.
        </p>

        {/* Référence de réservation */}
        <div className="mt-6 rounded-card bg-brand-50 border border-brand-200 p-4 flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-caption font-medium text-brand-800">
              Référence de réservation
            </div>
            <div
              className="text-h1 font-bold tracking-wide text-brand-900 mt-0.5"
              data-testid="booking-reference-code"
            >
              {booking.pnr_reference}
            </div>
          </div>
          <div className="text-right">
            <div className="text-caption text-brand-800">Montant réglé</div>
            <div className="text-h2 font-semibold text-ink">
              {Math.round(Number(booking.price_amount))} €
            </div>
          </div>
        </div>

        {/* Récapitulatif clair du vol */}
        <div className="mt-6 space-y-3 border-t border-border pt-5">
          <h2 className="text-h2 text-ink">Récapitulatif de votre vol</h2>

          <div className="rounded-md bg-canvas-subtle p-4 space-y-2">
            <div className="flex items-center justify-between text-caption text-ink-muted">
              <span>Compagnie : {booking.airline}</span>
              <span>{cabinLabelHuman(booking.cabin_class)}</span>
            </div>
            <div className="text-body font-medium text-ink">
              Aller : {originLabel} → {cityLabel}
            </div>
            <div className="text-caption text-ink-secondary">
              {formatDateHuman(booking.departure_outbound_at)} •{" "}
              {formatTimeHuman(booking.departure_outbound_at)} →{" "}
              {formatTimeHuman(booking.arrival_outbound_at)}
            </div>
          </div>

          <div className="rounded-md bg-canvas-subtle p-4 space-y-2">
            <div className="text-body font-medium text-ink">
              Retour : {cityLabel} → {originLabel}
            </div>
            <div className="text-caption text-ink-secondary">
              {formatDateHuman(booking.departure_inbound_at)} •{" "}
              {formatTimeHuman(booking.departure_inbound_at)} →{" "}
              {formatTimeHuman(booking.arrival_inbound_at)}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-4 pt-2 text-caption text-ink-muted">
            <span className="inline-flex items-center gap-1.5">
              <Mail className="h-4 w-4 text-brand-700" />
              Confirmation envoyée par e-mail
            </span>
            <span className="inline-flex items-center gap-1.5">
              <FileText className="h-4 w-4 text-brand-700" />
              Billet disponible dans Mes documents
            </span>
          </div>
        </div>

        {/* Actions principales : Choisir mon hébergement / Choisir mes activités */}
        <div className="mt-8 flex flex-col sm:flex-row items-center gap-3">
          <Button
            type="button"
            size="lg"
            data-testid="confirm-choose-accommodation-btn"
            onClick={() => navigate("/accommodations")}
            className="w-full sm:flex-1"
          >
            <span>Choisir mon hébergement</span>
            <ArrowRight className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="lg"
            data-testid="confirm-choose-activities-btn"
            onClick={() => navigate("/activities")}
            className="w-full sm:flex-1"
          >
            <Sparkles className="h-4 w-4 text-brand-700" />
            <span>Choisir mes activités</span>
          </Button>
        </div>
      </Card>
    </div>
  );
}

/* ============================================================================
 * 3. ÉCRAN CONNEXION / INSCRIPTION (/login)
 * ========================================================================== */
function AuthScreen({
  onAuthSuccess,
}: {
  onAuthSuccess: (token: string, user: UserProfile) => Promise<void>;
}) {
  const navigate = useNavigate();
  const { notify } = useToast();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState<string>("");
  const [password, setPassword] = useState<string>("");
  const [fullName, setFullName] = useState<string>("");
  const [errorMsg, setErrorMsg] = useState<string>("");
  const [submitting, setSubmitting] = useState<boolean>(false);

  const isDevMode = Boolean((import.meta as any).env?.DEV);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErrorMsg("");
    setSubmitting(true);
    try {
      const endpoint =
        mode === "login" ? "/api/v1/auth/login" : "/api/v1/auth/register";
      const body =
        mode === "login"
          ? { email: email.trim(), password }
          : {
              email: email.trim(),
              password,
              full_name: fullName.trim() || "Voyageur TravelMate",
              preferred_style: "STANDARD",
            };

      const resp = await fetch(`${API_BASE}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => null);
        setErrorMsg(
          humanErrorMessage(
            err,
            mode === "login"
              ? "Identifiants incorrects. Vérifiez votre adresse e-mail et votre mot de passe."
              : "Impossible de créer le compte avec ces informations."
          )
        );
        return;
      }

      const data = await resp.json();
      setInMemoryCsrfToken(data.csrf_token);
      await onAuthSuccess(SESSION_COOKIE_MARKER, data.user);
      notify({
        title: mode === "login" ? "Bon retour parmi nous" : "Bienvenue sur TravelMate",
        description: `Connecté en tant que ${data.user.full_name}`,
        tone: "success",
      });
      navigate("/");
    } catch {
      setErrorMsg("Le service d'authentification est momentanément indisponible.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleQuickDemoLogin() {
    setEmail("demo@travelmate.app");
    setPassword("TravelMate2026!");
    setErrorMsg("");
    setSubmitting(true);
    try {
      const resp = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: "demo@travelmate.app",
          password: "TravelMate2026!",
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setInMemoryCsrfToken(data.csrf_token);
        await onAuthSuccess(SESSION_COOKIE_MARKER, data.user);
        navigate("/");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="min-h-[calc(100vh-72px)] flex items-center justify-center px-4 py-12"
      data-testid="auth-screen"
    >
      <Card className="w-full max-w-md p-6 sm:p-8">
        <div className="text-center mb-6">
          <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-card bg-brand-50 text-brand-700">
            <Compass className="h-6 w-6" />
          </div>
          <h1 className="text-h1 text-ink">
            {mode === "login" ? "Connexion" : "Créer un compte"}
          </h1>
          <p className="mt-1 text-caption text-ink-muted">
            {mode === "login"
              ? "Retrouvez vos voyages et vos réservations en un instant."
              : "Inscrivez-vous pour organiser et sauvegarder vos prochains séjours."}
          </p>
        </div>

        {errorMsg && (
          <div
            data-testid="auth-error-message"
            className="mb-4 rounded-card border border-red-200 bg-feedback-dangerBg p-3 text-caption text-feedback-danger"
          >
            {errorMsg}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4" data-testid="auth-form">
          {mode === "register" && (
            <div>
              <label
                htmlFor="auth-fullname"
                className="block text-caption font-medium text-ink-secondary mb-1"
              >
                Nom complet
              </label>
              <Input
                id="auth-fullname"
                data-testid="register-fullname-input"
                type="text"
                required
                minLength={2}
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Camille Martin"
              />
            </div>
          )}

          <div>
            <label
              htmlFor="auth-email"
              className="block text-caption font-medium text-ink-secondary mb-1"
            >
              Adresse e-mail
            </label>
            <Input
              id="auth-email"
              data-testid="login-email-input"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="camille@exemple.fr"
            />
          </div>

          <div>
            <label
              htmlFor="auth-password"
              className="block text-caption font-medium text-ink-secondary mb-1"
            >
              Mot de passe
            </label>
            <Input
              id="auth-password"
              data-testid="login-password-input"
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
            />
          </div>

          <Button
            type="submit"
            size="lg"
            disabled={submitting}
            data-testid="auth-submit-btn"
            className="w-full mt-2"
          >
            {submitting
              ? "Chargement..."
              : mode === "login"
              ? "Se connecter"
              : "Créer mon compte"}
          </Button>
        </form>

        <div className="mt-6 text-center border-t border-border pt-4">
          <button
            type="button"
            data-testid="toggle-auth-mode-btn"
            onClick={() => {
              setErrorMsg("");
              setMode(mode === "login" ? "register" : "login");
            }}
            className="text-caption font-medium text-brand-700 hover:text-brand-800"
          >
            {mode === "login"
              ? "Pas encore de compte ? Créer un compte"
              : "Déjà inscrit ? Se connecter"}
          </button>
        </div>

        {/* Compte démo visible uniquement en mode développement */}
        {isDevMode && (
          <div
            data-testid="dev-demo-account-box"
            className="mt-5 rounded-md bg-canvas-subtle border border-border p-3 text-center"
          >
            <p className="text-caption text-ink-muted mb-2">
              Accès rapide (environnement de développement)
            </p>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              data-testid="dev-demo-login-btn"
              onClick={handleQuickDemoLogin}
              className="w-full"
            >
              Utiliser le compte de démonstration
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}

export interface TravelMateSsrState {
  destinations?: Destination[];
  trips?: Trip[];
  activeTripId?: string;
  latestBooking?: FlightBooking | null;
  selectedAccommodation?: AccommodationItem | null;
  gallery?: TripGalleryPayload | null;
  initialUnavailableCity?: string | null;
  documentsModalOpen?: boolean;
}

export function TravelMateShell({
  ssrState,
}: {
  ssrState?: TravelMateSsrState;
} = {}) {
  const navigate = useNavigate();
  const [token, setToken] = useState<string>(() => {
    if (typeof localStorage === "undefined") return "ssr-demo-token";
    // Aucun jeton de session n'est conservé dans localStorage (cookie HttpOnly tm_access_token)
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    return SESSION_COOKIE_MARKER;
  });
  const [currentUser, setCurrentUser] = useState<UserProfile | null>(() => {
    if (typeof localStorage === "undefined") {
      return {
        id: "user-ssr-1",
        email: "demo.traveler@travelmate.local",
        full_name: "Camille Martin",
        preferred_style: "STANDARD",
      };
    }
    try {
      const raw = localStorage.getItem(USER_STORAGE_KEY);
      return raw ? (JSON.parse(raw) as UserProfile) : null;
    } catch {
      return null;
    }
  });

  const [destinations, setDestinations] = useState<Destination[]>(
    ssrState?.destinations || []
  );
  const [isLoadingDestinations, setIsLoadingDestinations] = useState<boolean>(
    !ssrState?.destinations
  );
  const [trips, setTrips] = useState<Trip[]>(ssrState?.trips || []);
  const [activeTripId, setActiveTripId] = useState<string>(
    ssrState?.activeTripId || ""
  );
  const [departureOrigin, setDepartureOrigin] =
    useState<RememberedDepartureOrigin>(() => loadRememberedDepartureOrigin());
  const [originIata, setOriginIata] = useState<string>(
    () => loadRememberedDepartureOrigin().iataCode
  );
  const [departureDate, setDepartureDate] = useState<string>("2026-11-10");
  const [returnDate, setReturnDate] = useState<string>("2026-11-17");
  const [travelers, setTravelers] = useState<string>("2");
  const [latestBooking, setLatestBooking] = useState<FlightBooking | null>(
    ssrState?.latestBooking ?? null
  );
  const [selectedAccommodation, setSelectedAccommodation] =
    useState<AccommodationItem | null>(
      ssrState?.selectedAccommodation ?? null
    );
  const [gallery, setGallery] = useState<TripGalleryPayload | null>(
    ssrState?.gallery ?? null
  );
  const [documentsModalOpen, setDocumentsModalOpen] = useState<boolean>(
    ssrState?.documentsModalOpen ?? false
  );
  const [preferences, setPreferences] = useState<TravelerPreferences>(() => {
    const initialOrigin = loadRememberedDepartureOrigin();
    return {
      currency: "EUR",
      language: "fr",
      travelStyle: "STANDARD",
      departureCity: initialOrigin.cityName,
      departureIata: initialOrigin.iataCode,
      departureAirportLabel: initialOrigin.displayLabel,
    };
  });

  function handleChangeDepartureOrigin(nextOrigin: RememberedDepartureOrigin) {
    setDepartureOrigin(nextOrigin);
    setOriginIata(nextOrigin.iataCode);
    saveRememberedDepartureOrigin(nextOrigin);
    setPreferences((prev) => ({
      ...prev,
      departureCity: nextOrigin.cityName,
      departureIata: nextOrigin.iataCode,
      departureAirportLabel: nextOrigin.displayLabel,
    }));
  }

  function persistSession(_sessionMarker: string, user: UserProfile) {
    // Le jeton de session est stocké exclusivement dans le cookie HttpOnly tm_access_token
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user));
    setToken(SESSION_COOKIE_MARKER);
    setCurrentUser(user);
  }

  function handleLogout() {
    fetch(`${API_BASE}/api/v1/auth/logout`, {
      method: "POST",
      credentials: "include",
    }).catch(() => null);
    clearOfflineDocumentsCache();
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    localStorage.removeItem(USER_STORAGE_KEY);
    setToken("");
    setCurrentUser(null);
    setTrips([]);
    setActiveTripId("");
    setLatestBooking(null);
    setSelectedAccommodation(null);
    setGallery(null);
    navigate("/login");
  }

  async function loadUserTripsAndEnsureActive(
    authToken: string,
    destList: Destination[]
  ): Promise<Trip[]> {
    const tResp = await fetch(`${API_BASE}/api/v1/trips`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
    if (tResp.status === 401) {
      handleLogout();
      return [];
    }
    if (!tResp.ok) return [];
    const loadedTrips: Trip[] = await tResp.json();
    if (loadedTrips.length > 0) {
      const storedTripId =
        typeof localStorage !== "undefined"
          ? localStorage.getItem("travelmate_active_trip_id") || ""
          : "";
      const preferred =
        loadedTrips.find((t) => t.id === storedTripId) || loadedTrips[0];
      setTrips(loadedTrips);
      setActiveTripId(preferred.id);
      return loadedTrips;
    }
    if (destList.length > 0) {
      const defaultDest =
        destList.find((d) => d.city_name === "Marrakech") || destList[0];
      const createResp = await fetch(`${API_BASE}/api/v1/trips`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({
          destination_id: defaultDest.id,
          title: `Séjour à ${defaultDest.city_name}`,
          travel_style: "STANDARD",
          total_budget_planned: 2000,
          currency: "EUR",
          arrival_at: `${departureDate}T10:30:00Z`,
          departure_at: `${returnDate}T18:00:00Z`,
        }),
      });
      if (createResp.ok) {
        const created: Trip = await createResp.json();
        setTrips([created]);
        setActiveTripId(created.id);
        return [created];
      }
    }
    return [];
  }

  useEffect(() => {
    async function bootstrap() {
      setIsLoadingDestinations(true);
      try {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
        const dResp = await fetch(`${API_BASE}/api/v1/destinations`);
        let destList: Destination[] = [];
        if (dResp.ok) {
          destList = await dResp.json();
          setDestinations(destList);
        }

        // 1. Vérification d'une session active par cookie HttpOnly (tm_access_token)
        const meResp = await fetch(`${API_BASE}/api/v1/auth/me`);
        if (meResp.ok) {
          const meData: UserProfile = await meResp.json();
          const csrfResp = await fetch(`${API_BASE}/api/v1/auth/csrf`).catch(
            () => null
          );
          if (csrfResp && csrfResp.ok) {
            const csrfJson = await csrfResp.json();
            setInMemoryCsrfToken(csrfJson.csrf_token);
          }
          persistSession(SESSION_COOKIE_MARKER, meData);
          await loadUserTripsAndEnsureActive(SESSION_COOKIE_MARKER, destList);
          return;
        }

        // 2. Connexion automatique de démonstration via cookie HttpOnly + jeton CSRF
        const loginResp = await fetch(`${API_BASE}/api/v1/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email: "demo@travelmate.app",
            password: "TravelMate2026!",
          }),
        });
        if (loginResp.ok) {
          const authData = await loginResp.json();
          setInMemoryCsrfToken(authData.csrf_token);
          persistSession(SESSION_COOKIE_MARKER, authData.user);
          await loadUserTripsAndEnsureActive(SESSION_COOKIE_MARKER, destList);
        }
      } finally {
        setIsLoadingDestinations(false);
      }
    }
    bootstrap();
  }, []);

  const activeTrip = useMemo(
    () => trips.find((t) => t.id === activeTripId) || trips[0] || null,
    [trips, activeTripId]
  );

  const activeDestination = useMemo(() => {
    if (activeTrip) {
      return (
        destinations.find((d) => d.id === activeTrip.destination_id) || null
      );
    }
    if (isLoadingDestinations) {
      return null;
    }
    return (
      destinations.find((d) => d.city_name === "Marrakech") ||
      destinations[0] ||
      null
    );
  }, [destinations, activeTrip, isLoadingDestinations]);

  async function refreshGallery(category: string = "", radiusKm?: number) {
    if (!activeTrip?.id || !token) return;
    const url = new URL(`${API_BASE}/api/v1/places/trip/${activeTrip.id}/gallery`);
    if (category) url.searchParams.set("category", category);
    if (radiusKm && radiusKm > 0) url.searchParams.set("radius_km", String(radiusKm));
    const resp = await fetch(url.toString(), {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (resp.ok) {
      setGallery(await resp.json());
    }
  }

  useEffect(() => {
    if (!activeTrip?.id || !token) return;
    refreshGallery();
    fetch(`${API_BASE}/api/v1/flights/trip/${activeTrip.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => (r.ok ? r.json() : []))
      .then((list: FlightBooking[]) => {
        if (list.length > 0 && !latestBooking) {
          setLatestBooking(list[list.length - 1]);
        }
      })
      .catch(() => null);
  }, [activeTrip?.id, token]);

  /**
   * Sélectionne automatiquement ou crée le voyage en cours pour la destination choisie
   * (sans menu déroulant "Séjour actif").
   */
  function registerCreatedDestination(dest: Destination) {
    setDestinations((prev) => {
      if (prev.some((d) => d.id === dest.id)) {
        return prev.map((d) => (d.id === dest.id ? dest : d));
      }
      return [...prev, dest];
    });
  }

  async function refreshDemoSession(): Promise<string> {
    try {
      const meResp = await fetch(`${API_BASE}/api/v1/auth/me`);
      if (meResp.ok) {
        const meData: UserProfile = await meResp.json();
        const csrfResp = await fetch(`${API_BASE}/api/v1/auth/csrf`).catch(
          () => null
        );
        if (csrfResp && csrfResp.ok) {
          const csrfJson = await csrfResp.json();
          setInMemoryCsrfToken(csrfJson.csrf_token);
        }
        persistSession(SESSION_COOKIE_MARKER, meData);
        return SESSION_COOKIE_MARKER;
      }
      const loginResp = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: "demo@travelmate.app",
          password: "TravelMate2026!",
        }),
      });
      if (loginResp.ok) {
        const authData = await loginResp.json();
        setInMemoryCsrfToken(authData.csrf_token);
        persistSession(SESSION_COOKIE_MARKER, authData.user);
        return SESSION_COOKIE_MARKER;
      }
    } catch {
      // Ignorer et laisser l'appelant gérer l'erreur
    }
    return token || "";
  }

  async function ensureTripForDestination(
    dest: Destination,
    options?: { forceMatchDates?: boolean; throwOnError?: boolean }
  ): Promise<Trip | null> {
    registerCreatedDestination(dest);
    const depIso = normalizeIsoDateInput(departureDate, "2026-11-10");
    let retIso = normalizeIsoDateInput(returnDate, addDaysIso(depIso, 7));
    const nights = diffDaysIso(depIso, retIso);
    if (nights < 0) {
      if (options?.throwOnError) {
        throw new Error(
          `Dates de séjour invalides : la date de retour (${retIso}) doit être postérieure à la date de départ (${depIso}).`
        );
      }
      retIso = addDaysIso(depIso, 7);
    } else if (nights === 0) {
      retIso = addDaysIso(depIso, 7);
    }

    const existing = trips.find((t) => {
      if (t.destination_id !== dest.id) return false;
      if (!options?.forceMatchDates) return true;
      const tArr = String(t.arrival_at || "").slice(0, 10);
      const tDep = String(t.departure_at || "").slice(0, 10);
      return tArr === depIso && tDep === retIso;
    });
    if (existing) {
      setActiveTripId(existing.id);
      if (typeof localStorage !== "undefined") {
        localStorage.setItem("travelmate_active_trip_id", existing.id);
      }
      return existing;
    }

    let activeToken = token || (await refreshDemoSession());
    if (!activeToken) {
      if (options?.throwOnError) {
        throw new Error(
          "Session expirée ou non authentifiée. Veuillez vous reconnecter."
        );
      }
      return null;
    }

    const payload = {
      destination_id: dest.id,
      title: `Voyage à ${dest.city_name}`,
      travel_style: preferences.travelStyle || "STANDARD",
      total_budget_planned: 2200,
      currency: preferences.currency || "EUR",
      arrival_at: `${depIso}T10:30:00Z`,
      departure_at: `${retIso}T18:00:00Z`,
    };

    let resp = await fetch(`${API_BASE}/api/v1/trips`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${activeToken}`,
      },
      body: JSON.stringify(payload),
    });

    if (resp.status === 401 || resp.status === 403) {
      activeToken = await refreshDemoSession();
      if (activeToken) {
        resp = await fetch(`${API_BASE}/api/v1/trips`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${activeToken}`,
          },
          body: JSON.stringify(payload),
        });
      }
    }

    if (resp.ok) {
      const created: Trip = await resp.json();
      setTrips((prev) => [created, ...prev.filter((t) => t.id !== created.id)]);
      setActiveTripId(created.id);
      if (typeof localStorage !== "undefined") {
        localStorage.setItem("travelmate_active_trip_id", created.id);
      }
      return created;
    }

    if (options?.throwOnError) {
      const errBody = await resp.json().catch(() => null);
      throw new Error(
        humanErrorMessage(
          errBody,
          `Impossible de créer le voyage pour ${dest.city_name} (code ${resp.status}).`
        )
      );
    }
    return null;
  }

  async function handleSelectDestinationAndGoToFlights(dest: Destination) {
    registerCreatedDestination(dest);
    const destIata = String(dest.iata_code || "").toUpperCase();
    if (destIata && destIata === String(originIata || "").toUpperCase()) {
      setOriginIata("LHR");
    }
    await ensureTripForDestination(dest, {
      forceMatchDates: true,
      throwOnError: true,
    });
    navigate("/flights");
  }

  async function handleCreateMultiCityTrip(
    draftStages: DraftStageFormItem[],
    targetRoute: "/flights" | "/trip" = "/trip"
  ) {
    if (!draftStages || draftStages.length === 0) {
      throw new Error("Veuillez ajouter au moins une étape à votre itinéraire.");
    }
    const validation = validateDraftStagesNoOverlap(draftStages);
    if (!validation.valid) {
      throw new Error(validation.error || "Les dates des étapes sont invalides.");
    }

    let activeToken = token || (await refreshDemoSession());
    if (!activeToken) {
      throw new Error(
        "Session expirée ou non authentifiée. Veuillez vous reconnecter."
      );
    }

    const firstStage = draftStages[0];
    const lastStage = draftStages[draftStages.length - 1];
    const cityNames = draftStages.map((s) => s.city_name).join(" → ");
    const payload = {
      destination_id: firstStage.destination_id,
      title: `Voyage ${cityNames}`,
      travel_style: preferences.travelStyle || "STANDARD",
      total_budget_planned: 2800,
      currency: preferences.currency || "EUR",
      arrival_at: `${firstStage.arrival_date}T10:30:00Z`,
      departure_at: `${lastStage.departure_date}T18:00:00Z`,
      stages: draftStages.map((s) => ({
        destination_id: s.destination_id,
        geoname_id: s.geoname_id ?? undefined,
        city_name: s.city_name,
        country_name: s.country_name || "Monde",
        country_code_iso2: s.country_code_iso2 || "XX",
        timezone: s.timezone || "UTC",
        latitude: s.latitude ?? undefined,
        longitude: s.longitude ?? undefined,
        arrival_date: s.arrival_date,
        departure_date: s.departure_date,
        nights: Math.max(1, diffDaysIso(s.arrival_date, s.departure_date)),
        arrival_transport_mode: s.arrival_transport_mode || "VOL",
      })),
    };

    let resp = await fetch(`${API_BASE}/api/v1/trips`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${activeToken}`,
      },
      body: JSON.stringify(payload),
    });

    if (resp.status === 401 || resp.status === 403) {
      activeToken = await refreshDemoSession();
      if (activeToken) {
        resp = await fetch(`${API_BASE}/api/v1/trips`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${activeToken}`,
          },
          body: JSON.stringify(payload),
        });
      }
    }

    if (!resp.ok) {
      const errBody = await resp.json().catch(() => null);
      throw new Error(
        humanErrorMessage(
          errBody,
          `Impossible de créer le voyage multi-villes (code ${resp.status}).`
        )
      );
    }

    const created: Trip = await resp.json();
    setTrips((prev) => [created, ...prev.filter((t) => t.id !== created.id)]);
    setActiveTripId(created.id);
    if (typeof localStorage !== "undefined") {
      localStorage.setItem("travelmate_active_trip_id", created.id);
    }
    navigate(targetRoute);
  }

  const progressSteps = [
    { to: "/", label: "Destination", end: true },
    { to: "/flights", label: "Vol", end: false },
    { to: "/accommodations", label: "Hébergement", end: false },
    { to: "/activities", label: "Activités", end: false },
    { to: "/itinerary", label: "Programme", end: false },
  ];

  return (
    <div className="min-h-screen flex flex-col bg-canvas text-ink overflow-x-hidden">
      {/* Navigation finale : barre de progression Destination > Vol > Hébergement > Activités > Programme */}
      <header className="sticky top-0 z-30 border-b border-border bg-canvas-card/95 backdrop-blur">
        <div
          className="mx-auto max-w-[1440px] px-3 h-16 flex items-center justify-between gap-2 flex-nowrap"
          data-testid="desktop-top-header-row"
        >
          <div className="flex items-center gap-2 flex-nowrap shrink-0">
            <Link
              to="/"
              data-testid="header-brand-link"
              style={{ whiteSpace: "nowrap" }}
              className="flex items-center gap-1.5 text-ink font-semibold text-h2 tracking-tight whitespace-nowrap shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700 rounded-md"
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-card bg-brand-700 text-white shrink-0">
                <Plane className="h-4 w-4" />
              </span>
              <span style={{ whiteSpace: "nowrap" }}>TravelMate</span>
            </Link>

            {/* Barre de progression sur ordinateur (>= 1280px) */}
            <nav
              aria-label="Étapes de votre voyage"
              data-testid="step-progress-bar"
              className="hidden xl:flex items-center gap-0.5 flex-nowrap shrink-0"
            >
              {progressSteps.map((step, index) => (
                <React.Fragment key={step.to}>
                  <NavLink
                    to={step.to}
                    end={step.end}
                    style={{ whiteSpace: "nowrap" }}
                    className={({ isActive }) =>
                      `inline-flex items-center gap-1 px-2 py-1 rounded-card text-[12px] leading-none font-semibold whitespace-nowrap shrink-0 transition-colors ${
                        isActive
                          ? "bg-brand-700 text-white shadow-sm"
                          : "text-ink-secondary hover:text-ink hover:bg-canvas-subtle"
                      }`
                    }
                  >
                    <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-black/10 text-[10px] font-bold shrink-0">
                      {index + 1}
                    </span>
                    <span style={{ whiteSpace: "nowrap" }}>{step.label}</span>
                  </NavLink>
                  {index < progressSteps.length - 1 && (
                    <ChevronRight
                      className="h-3 w-3 text-ink-muted shrink-0"
                      aria-hidden="true"
                    />
                  )}
                </React.Fragment>
              ))}
            </nav>
          </div>

          <div className="flex items-center gap-1.5 flex-nowrap shrink-0">
            {activeDestination && (
              <Badge
                variant="brand"
                className="hidden sm:inline-flex whitespace-nowrap shrink-0 px-2 py-0.5 text-[12px] leading-none"
                data-testid="active-destination-pill"
              >
                <MapPin className="h-3 w-3 shrink-0" />
                <span style={{ whiteSpace: "nowrap" }}>
                  {activeDestination.city_name}
                </span>
              </Badge>
            )}

            <NavLink
              to="/trip"
              data-testid="nav-my-trip-link"
              style={{ whiteSpace: "nowrap" }}
              className={({ isActive }) =>
                `inline-flex items-center gap-1 px-2 py-1 rounded-card text-[12px] leading-none font-semibold whitespace-nowrap shrink-0 transition-colors ${
                  isActive
                    ? "bg-brand-50 text-brand-800 border border-brand-200"
                    : "text-ink-secondary hover:text-ink hover:bg-canvas-subtle"
                }`
              }
            >
              <Compass className="h-3.5 w-3.5 text-brand-700 shrink-0" />
              <span className="hidden sm:inline" style={{ whiteSpace: "nowrap" }}>
                Mon voyage
              </span>
            </NavLink>

            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="whitespace-nowrap shrink-0 px-2 py-1 text-[12px] leading-none"
              data-testid="open-documents-btn"
              onClick={() => navigate("/trip/documents")}
            >
              <FileText className="h-3.5 w-3.5 text-brand-700 shrink-0" />
              <span className="hidden md:inline" style={{ whiteSpace: "nowrap" }}>
                Mes documents
              </span>
            </Button>

            <NavLink
              to="/settings"
              aria-label="Paramètres"
              data-testid="nav-settings-link"
              className={({ isActive }) =>
                `rounded-md p-1.5 shrink-0 transition-colors ${
                  isActive
                    ? "bg-brand-50 text-brand-800"
                    : "text-ink-muted hover:bg-canvas-subtle hover:text-ink"
                }`
              }
            >
              <Settings className="h-4 w-4" />
            </NavLink>

            {token && currentUser ? (
              <div className="flex items-center gap-1 flex-nowrap shrink-0">
                <Link
                  to="/login"
                  data-testid="header-user-link"
                  style={{ whiteSpace: "nowrap" }}
                  className="inline-flex items-center gap-1 rounded-card border border-border bg-canvas-subtle px-2 py-1 text-[12px] leading-none font-medium text-ink whitespace-nowrap shrink-0 hover:bg-border/40"
                >
                  <User className="h-3.5 w-3.5 text-brand-700 shrink-0" />
                  <span
                    className="hidden sm:inline whitespace-nowrap"
                    style={{ whiteSpace: "nowrap" }}
                  >
                    {currentUser.full_name}
                  </span>
                </Link>
                <button
                  type="button"
                  onClick={handleLogout}
                  aria-label="Se déconnecter"
                  data-testid="logout-btn"
                  className="rounded-md p-1.5 text-ink-muted hover:bg-canvas-subtle hover:text-ink shrink-0"
                >
                  <LogOut className="h-4 w-4" />
                </button>
              </div>
            ) : (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="whitespace-nowrap shrink-0"
                data-testid="header-login-btn"
                onClick={() => navigate("/login")}
              >
                Connexion
              </Button>
            )}
          </div>
        </div>

        {/* Barre de progression mobile / tablette (< 1280px) */}
        <nav
          aria-label="Étapes de votre voyage sur mobile"
          data-testid="mobile-step-progress-bar"
          className="flex xl:hidden items-center gap-1 overflow-x-auto no-scrollbar px-4 py-2 border-t border-border bg-canvas-card"
        >
          {progressSteps.map((step, index) => (
            <React.Fragment key={step.to}>
              <NavLink
                to={step.to}
                end={step.end}
                className={({ isActive }) =>
                  `inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-caption font-semibold whitespace-nowrap ${
                    isActive
                      ? "bg-brand-700 text-white"
                      : "text-ink-secondary hover:text-ink"
                  }`
                }
              >
                <span>{index + 1}.</span>
                <span>{step.label}</span>
              </NavLink>
              {index < progressSteps.length - 1 && (
                <ChevronRight
                  className="h-3 w-3 text-ink-muted shrink-0"
                  aria-hidden="true"
                />
              )}
            </React.Fragment>
          ))}
        </nav>
      </header>

      {/* Contenu de chaque route */}
      <main className="flex-1">
        <Routes>
          <Route
            path="/"
            element={
              <HomeScreen
                destinations={destinations}
                isLoadingDestinations={isLoadingDestinations}
                departureDate={departureDate}
                returnDate={returnDate}
                onChangeDates={(dep, ret) => {
                  setDepartureDate(dep);
                  setReturnDate(ret);
                }}
                travelers={travelers}
                onChangeTravelers={setTravelers}
                onSelectDestinationAndSearch={handleSelectDestinationAndGoToFlights}
                onRegisterCreatedDestination={registerCreatedDestination}
                initialUnavailableCity={ssrState?.initialUnavailableCity ?? null}
                onCreateMultiCityTrip={handleCreateMultiCityTrip}
              />
            }
          />
          <Route
            path="/flights"
            element={
              <FlightsScreen
                activeTrip={activeTrip}
                activeDestination={activeDestination}
                destinations={destinations}
                originIata={originIata}
                onChangeOriginIata={setOriginIata}
                departureOrigin={departureOrigin}
                onChangeDepartureOrigin={handleChangeDepartureOrigin}
                departureDate={departureDate}
                returnDate={returnDate}
                travelers={travelers}
                onSelectDestination={async (dest) => {
                  await ensureTripForDestination(dest);
                }}
                onRegisterCreatedDestination={registerCreatedDestination}
                onBookSuccess={(booking) => {
                  setLatestBooking(booking);
                  setTrips((prev) =>
                    prev.map((t) =>
                      t.id === booking.trip_id
                        ? {
                            ...t,
                            arrival_at: booking.arrival_outbound_at,
                            departure_at: booking.departure_inbound_at,
                          }
                        : t
                    )
                  );
                  refreshGallery();
                }}
                token={token}
              />
            }
          />
          <Route
            path="/flights/confirmation"
            element={
              <FlightConfirmationScreen
                booking={latestBooking}
                destination={activeDestination}
              />
            }
          />
          <Route
            path="/accommodations"
            element={
              <AccommodationsScreen
                apiBase={API_BASE}
                trip={activeTrip}
                destination={activeDestination}
                selectedAccommodation={selectedAccommodation}
                onSelectAccommodation={setSelectedAccommodation}
                departureDate={departureDate}
                returnDate={returnDate}
                travelers={travelers}
              />
            }
          />
          <Route
            path="/activities"
            element={
              <ActivitiesScreen
                apiBase={API_BASE}
                token={token}
                trip={activeTrip}
                destination={activeDestination}
                gallery={gallery}
                onRefreshGallery={refreshGallery}
              />
            }
          />
          <Route
            path="/itinerary"
            element={
              <ItineraryScreen
                apiBase={API_BASE}
                token={token}
                trip={activeTrip}
                destination={activeDestination}
                places={gallery?.places || []}
                onUnauthorized={handleLogout}
              />
            }
          />
          <Route
            path="/trip"
            element={
              <MyTripSummaryScreen
                apiBase={API_BASE}
                token={token}
                trip={activeTrip}
                destination={activeDestination}
                latestBooking={latestBooking}
                selectedAccommodation={selectedAccommodation}
                onOpenDocumentsModal={() => navigate("/trip/documents")}
                destinations={destinations}
                onTripUpdated={(updatedTrip) => {
                  setTrips((prev) =>
                    prev.map((t) => (t.id === updatedTrip.id ? updatedTrip : t))
                  );
                }}
              />
            }
          />
          <Route
            path="/trip/budget"
            element={
              <TripBudgetScreen
                apiBase={API_BASE}
                token={token}
                trip={activeTrip}
                destination={activeDestination}
              />
            }
          />
          <Route
            path="/trip/documents"
            element={
              <TripDocumentsScreen
                apiBase={API_BASE}
                token={token}
                trip={activeTrip}
                destination={activeDestination}
              />
            }
          />
          <Route
            path="/trip/infos"
            element={
              <TripPracticalInfoScreen
                apiBase={API_BASE}
                trip={activeTrip}
                destination={activeDestination}
              />
            }
          />
          <Route
            path="/transports"
            element={
              <MyTripSummaryScreen
                apiBase={API_BASE}
                token={token}
                trip={activeTrip}
                destination={activeDestination}
                latestBooking={latestBooking}
                selectedAccommodation={selectedAccommodation}
                onOpenDocumentsModal={() => navigate("/trip/documents")}
              />
            }
          />
          <Route
            path="/settings"
            element={
              <SettingsScreen
                preferences={preferences}
                onSavePreferences={setPreferences}
                currentUser={currentUser}
                onLogout={handleLogout}
                departureCityNode={
                  <div>
                    <label
                      htmlFor="settings-departure-input"
                      className="block text-caption font-medium text-ink-secondary mb-1.5"
                    >
                      Ville et aéroport de départ mémorisés
                    </label>
                    <GeoNamesCityAutocompleteField
                      inputId="settings-departure-input"
                      inputTestId="settings-departure-input"
                      listTestId="settings-departure-autocomplete-list"
                      ariaLabel="Ville et aéroport de départ mémorisés"
                      placeholder="Ville ou pays"
                      displayValue={departureOrigin.displayLabel}
                      popularDestinations={destinations.filter((d) =>
                        SEED_POPULAR_CITY_NAMES.has(d.city_name.trim().toLowerCase())
                      )}
                      onSelectCityItem={(item) => {
                        const cleanCity = item.nom
                          .replace(/^Région\s*:\s*/i, "")
                          .trim();
                        const iata = (item.iata_code || "CDG")
                          .trim()
                          .toUpperCase();
                        const within100 =
                          typeof item.airport_within_100km === "boolean"
                            ? item.airport_within_100km
                            : true;
                        const dist =
                          typeof item.nearest_airport_distance_km === "number"
                            ? item.nearest_airport_distance_km
                            : undefined;
                        const label =
                          item.airport_display_label ||
                          (!within100 && dist != null
                            ? `${cleanCity} (${iata} — à ${Math.round(dist)} km)`
                            : `${cleanCity} (${iata})`);
                        handleChangeDepartureOrigin({
                          cityName: cleanCity,
                          countryName: item.pays,
                          regionName: item.region || item.region_name,
                          iataCode: iata,
                          airportName: item.airport_name,
                          distanceKm: dist,
                          within100Km: within100,
                          displayLabel: label,
                        });
                      }}
                    />
                  </div>
                }
              />
            }
          />
          <Route
            path="/login"
            element={
              <AuthScreen
                onAuthSuccess={async (newToken, user) => {
                  persistSession(newToken, user);
                  await loadUserTripsAndEnsureActive(newToken, destinations);
                }}
              />
            }
          />

          {/* Page d'administration technique séparée (/admin) */}
          <Route
            path="/admin"
            element={<AdminTechnicalStatusScreen apiBase={API_BASE} />}
          />
        </Routes>
      </main>

      {/* Modale Mes documents */}
      <Modal
        open={documentsModalOpen}
        onOpenChange={setDocumentsModalOpen}
        title="Mes documents"
        description="Retrouvez vos confirmations et billets enregistrés pour votre séjour."
      >
        {latestBooking ? (
          <div className="space-y-3">
            <div className="rounded-card border border-border bg-canvas-subtle p-4">
              <div className="flex items-center justify-between">
                <span className="text-caption font-medium text-brand-700">
                  Billet d'avion aller-retour
                </span>
                <Badge variant="success">Réservation confirmée</Badge>
              </div>
              <div className="mt-1 text-body font-semibold text-ink">
                {latestBooking.airline} • Référence de réservation{" "}
                {latestBooking.pnr_reference}
              </div>
              <div className="mt-1 text-caption text-ink-secondary">
                Aller le {formatDateHuman(latestBooking.departure_outbound_at)} •
                Retour le {formatDateHuman(latestBooking.departure_inbound_at)}
              </div>
            </div>
          </div>
        ) : (
          <p className="text-body text-ink-muted">
            Aucun billet enregistré pour le moment. Vos confirmations apparaîtront automatiquement ici dès votre réservation.
          </p>
        )}
      </Modal>
    </div>
  );
}

function stripHtmlToVisibleText(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;|&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();
}

export function renderTravelerPagesForInspection() {
  const sampleDestinations: Destination[] = [
    {
      id: "dest-rak",
      city_name: "Marrakech",
      country_name: "Maroc",
      country_code_iso2: "MA",
      iata_code: "RAK",
      timezone: "Africa/Casablanca",
      latitude: 31.6295,
      longitude: -7.9811,
      hero_image_url:
        "https://upload.wikimedia.org/wikipedia/commons/thumb/4/45/Koutoubia_Mosque%2C_Marrakesh%2C_Morocco.jpg/960px-Koutoubia_Mosque%2C_Marrakesh%2C_Morocco.jpg",
      description: "Médina ocre, jardins paisibles et palais historiques.",
      practical_info: { currency: "MAD", language: "Arabe / Français" },
    },
    {
      id: "dest-tyo",
      city_name: "Tokyo",
      country_name: "Japon",
      country_code_iso2: "JP",
      iata_code: "HND",
      timezone: "Asia/Tokyo",
      latitude: 35.6762,
      longitude: 139.6503,
      hero_image_url:
        "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b2/Skyscrapers_of_Shinjuku_2009_January.jpg/960px-Skyscrapers_of_Shinjuku_2009_January.jpg",
      description: "Sanctuaires paisibles, quartiers créatifs et haute gastronomie.",
      practical_info: { currency: "JPY", language: "Japonais" },
    },
    {
      id: "dest-rom",
      city_name: "Rome",
      country_name: "Italie",
      country_code_iso2: "IT",
      iata_code: "FCO",
      timezone: "Europe/Rome",
      latitude: 41.9028,
      longitude: 12.4964,
      hero_image_url:
        "https://upload.wikimedia.org/wikipedia/commons/thumb/d/de/Colosseo_2020.jpg/960px-Colosseo_2020.jpg",
      description: "Vestiges antiques, places baroques et trattorias authentiques.",
      practical_info: { currency: "EUR", language: "Italien" },
    },
  ];

  const sampleTrip: Trip = {
    id: "trip-ssr-1",
    destination_id: "dest-rak",
    title: "Séjour à Marrakech",
    arrival_at: "2026-11-10T10:30:00Z",
    departure_at: "2026-11-17T18:00:00Z",
    travel_style: "STANDARD",
    total_budget_planned: 1600,
    currency: "EUR",
    selected_place_ids: ["place-majorelle"],
    status: "PLANNING",
  };

  const sampleBooking: FlightBooking = {
    id: "booking-ssr-1",
    trip_id: "trip-ssr-1",
    idempotency_key: "idem-ssr-1",
    idempotent_replay: false,
    airline: "Air France",
    flight_number_outbound: "AF1562",
    flight_number_inbound: "AF1563",
    origin_iata: "CDG",
    destination_iata: "RAK",
    departure_outbound_at: "2026-11-10T07:15:00Z",
    arrival_outbound_at: "2026-11-10T10:30:00Z",
    departure_inbound_at: "2026-11-17T15:00:00Z",
    arrival_inbound_at: "2026-11-17T18:20:00Z",
    price_amount: "295.00",
    currency: "EUR",
    cabin_class: "ECONOMY",
    pnr_reference: "TM8K4M",
    flight_status: "CONFIRMED",
    vault_document_id: "doc-ssr-1",
    budget_item_id: "bud-ssr-1",
    gmail_confirmation_sent: true,
    gmail_message_id: "msg-ssr-1",
    trip_arrival_at: "2026-11-10T10:30:00Z",
    trip_departure_at: "2026-11-17T18:00:00Z",
  };

  const sampleAccommodation: AccommodationItem = {
    id: "acc-ssr-1",
    destination_id: "dest-rak",
    name: "La Mamounia Marrakech",
    type: "HOTEL",
    source: "HOTEL",
    source_provider: "Wikidata / Wikimedia Commons",
    source_label: "Sélection vérifiée",
    provider_mode: "LIVE",
    is_simulated: false,
    luxury_tier: "LUXURY",
    booking_redirect_url: "https://www.booking.com/searchresults.fr.html?ss=La+Mamounia+Marrakech",
    booking_url: "https://www.booking.com/searchresults.fr.html?ss=La+Mamounia+Marrakech",
    airbnb_url: "https://www.airbnb.fr/s/Marrakech/homes",
    neighborhood: "Bab Jdid — Hivernage",
    address: "Avenue Bab Jdid, Marrakech",
    latitude: 31.6226,
    longitude: -7.9977,
    price_per_night: "460.00",
    price_label: "Prix indicatif",
    gamme_label: "Luxe",
    currency: "EUR",
    rating: 4.9,
    amenities: ["Jardins historiques", "Spa & hammam", "Piscine extérieure", "Petit-déjeuner"],
    photos: [
      "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3c/La_Mamounia_Hotel%2C_Marrakesh%2C_Morocco_-_20080520.jpg/960px-La_Mamounia_Hotel%2C_Marrakesh%2C_Morocco_-_20080520.jpg",
    ],
    photo_status: "commons_verified",
    photo_file_title: "File:La Mamounia Hotel, Marrakesh, Morocco - 20080520.jpg",
    photo_author: "Elya",
    photo_license: "CC BY-SA 3.0",
    photo_commons_url: "https://commons.wikimedia.org/wiki/File:La_Mamounia_Hotel,_Marrakesh,_Morocco_-_20080520.jpg",
    photo_credit_text: "Photo : Elya — CC BY-SA 3.0 — Wikimedia Commons",
    wikidata_id: "Q3210501",
    accommodation_subtype: "hotel",
    is_illustration: false,
    distance_from_center_km: 1.1,
    nearby_restaurants: [
      {
        id: "rest-ssr-1",
        name: "La Table de la Kasbah",
        description: "Cuisine marocaine traditionnelle et terrasse ombragée.",
        latitude: 31.6262,
        longitude: -7.9885,
        estimated_cost: "24.00",
        price_tier: "STANDARD",
        avg_rating: 4.7,
        hero_photos: [],
        distance_km: 0.25,
        distance_m: 250,
        walking_minutes: 4,
      },
    ],
  };

  const sampleGallery: TripGalleryPayload = {
    trip_id: "trip-ssr-1",
    city_name: "Marrakech",
    unlocked: true,
    unlock_message: "Activités disponibles pour votre séjour à Marrakech.",
    provider_mode: "LIVE",
    cached_in_redis: true,
    selected_place_ids: ["place-majorelle"],
    places: [
      {
        id: "place-majorelle",
        destination_id: "dest-rak",
        city_name: "Marrakech",
        name: "Jardin Majorelle",
        description: "Jardin botanique emblématique aux façades bleu cobalt.",
        category: "CULTURE",
        latitude: 31.6417,
        longitude: -8.0033,
        is_outdoor: true,
        recommended_duration_min: 90,
        estimated_cost: "15.00",
        price_tier: "STANDARD",
        avg_rating: 4.9,
        opening_hours: { mon: "08:00-18:00" },
        hero_photos: [
          "https://upload.wikimedia.org/wikipedia/commons/thumb/5/59/Jardin_Majorelle_in_Marrakesh%2C_Morocco.jpg/960px-Jardin_Majorelle_in_Marrakesh%2C_Morocco.jpg",
        ],
        source_provider: "TravelMate",
        is_wishlisted: false,
        is_selected_for_trip: true,
      },
    ],
  };

  const baseSsrState: TravelMateSsrState = {
    destinations: sampleDestinations,
    trips: [sampleTrip],
    activeTripId: sampleTrip.id,
    latestBooking: sampleBooking,
    selectedAccommodation: sampleAccommodation,
    gallery: sampleGallery,
  };

  const ssrQueryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
    },
  });
  ssrQueryClient.setQueryData(
    ["flights-search", "trip-ssr-1", "CDG", "RAK", "2026-11-10", "2026-11-17"],
    [
      {
        offer_id: "offer-ssr-1",
        airline_code: "AF",
        airline_name: "Air France",
        flight_number_outbound: "AF1562",
        flight_number_inbound: "AF1563",
        origin_iata: "CDG",
        destination_iata: "RAK",
        destination_city: "Marrakech",
        departure_outbound_at: "2026-11-10T07:15:00Z",
        arrival_outbound_at: "2026-11-10T10:30:00Z",
        departure_inbound_at: "2026-11-17T15:00:00Z",
        arrival_inbound_at: "2026-11-17T18:20:00Z",
        price_amount: "295.00",
        price_eur: 295,
        currency: "EUR",
        cabin_class: "ECONOMY",
        mode: "STANDARD",
      },
    ] satisfies FlightOffer[]
  );

  const routeConfigs: Array<{
    key: string;
    path: string;
    state: TravelMateSsrState;
  }> = [
    { key: "/", path: "/", state: baseSsrState },
    {
      key: "/?unavailable=Séoul",
      path: "/",
      state: { ...baseSsrState, initialUnavailableCity: "Séoul" },
    },
    { key: "/flights", path: "/flights", state: baseSsrState },
    {
      key: "/flights/confirmation",
      path: "/flights/confirmation",
      state: baseSsrState,
    },
    { key: "/login", path: "/login", state: baseSsrState },
    { key: "/accommodations", path: "/accommodations", state: baseSsrState },
    { key: "/activities", path: "/activities", state: baseSsrState },
    { key: "/itinerary", path: "/itinerary", state: baseSsrState },
    { key: "/trip", path: "/trip", state: baseSsrState },
    { key: "/trip/budget", path: "/trip/budget", state: baseSsrState },
    { key: "/trip/documents", path: "/trip/documents", state: baseSsrState },
    { key: "/trip/infos", path: "/trip/infos", state: baseSsrState },
    { key: "/settings", path: "/settings", state: baseSsrState },
  ];

  const pages: Record<string, { html: string; visible_text: string }> = {};
  for (const rc of routeConfigs) {
    const html = ReactDOMServer.renderToStaticMarkup(
      <QueryClientProvider client={ssrQueryClient}>
        <ToastProvider>
          <MemoryRouter initialEntries={[rc.path]}>
            <TravelMateShell ssrState={rc.state} />
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );
    pages[rc.key] = {
      html,
      visible_text: stripHtmlToVisibleText(html),
    };
  }

  const allVisibleText = Object.values(pages)
    .map((p) => p.visible_text)
    .join("\n---\n");

  return {
    pages,
    all_visible_text: allVisibleText,
  };
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <TravelMateShell />
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

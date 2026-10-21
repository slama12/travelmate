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
  LYS: "Lyon (Saint-Exupéry)",
  MRS: "Marseille (Provence)",
  BRU: "Bruxelles",
  GVA: "Genève",
  LHR: "Londres (Heathrow)",
  HND: "Tokyo (Haneda)",
  FCO: "Rome (Fiumicino)",
  RAK: "Marrakech (Ménara)",
  JFK: "New York (JFK)",
};

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

/* ============================================================================
 * 1. ÉCRAN ACCUEIL (/)
 * ========================================================================== */
function HomeScreen({
  destinations,
  isLoadingDestinations,
  departureDate,
  returnDate,
  onChangeDates,
  travelers,
  onChangeTravelers,
  onSelectDestinationAndSearch,
  initialUnavailableCity = null,
}: {
  destinations: Destination[];
  isLoadingDestinations: boolean;
  departureDate: string;
  returnDate: string;
  onChangeDates: (dep: string, ret: string) => void;
  travelers: string;
  onChangeTravelers: (val: string) => void;
  onSelectDestinationAndSearch: (dest: Destination) => Promise<void>;
  initialUnavailableCity?: string | null;
}) {
  const [cityQuery, setCityQuery] = useState<string>("");
  const [autocompleteOpen, setAutocompleteOpen] = useState<boolean>(false);
  const [calendarOpen, setCalendarOpen] = useState<boolean>(false);
  const [unavailableCity, setUnavailableCity] = useState<string | null>(
    initialUnavailableCity
  );
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const searchBoxRef = useRef<HTMLDivElement | null>(null);

  const selectedRange: DateRange = useMemo(() => {
    return {
      from: departureDate ? parseISO(departureDate) : parseISO("2026-11-10"),
      to: returnDate ? parseISO(returnDate) : parseISO("2026-11-17"),
    };
  }, [departureDate, returnDate]);

  const filteredSuggestions = useMemo(() => {
    const q = cityQuery.trim().toLowerCase();
    if (!q) return destinations;
    return destinations.filter(
      (d) =>
        d.city_name.toLowerCase().includes(q) ||
        d.country_name.toLowerCase().includes(q)
    );
  }, [cityQuery, destinations]);

  useEffect(() => {
    function handleOutsideClick(e: MouseEvent) {
      if (searchBoxRef.current && !searchBoxRef.current.contains(e.target as Node)) {
        setAutocompleteOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, []);

  async function handleSubmitSearch(e: React.FormEvent) {
    e.preventDefault();
    setUnavailableCity(null);
    const trimmed = cityQuery.trim();

    if (!trimmed) {
      const defaultDest =
        destinations.find((d) => d.city_name === "Marrakech") || destinations[0];
      if (defaultDest) {
        setIsSubmitting(true);
        await onSelectDestinationAndSearch(defaultDest);
        setIsSubmitting(false);
      }
      return;
    }

    const match = destinations.find(
      (d) =>
        d.city_name.toLowerCase() === trimmed.toLowerCase() ||
        d.city_name.toLowerCase().includes(trimmed.toLowerCase())
    );

    if (!match) {
      setUnavailableCity(trimmed);
      setAutocompleteOpen(false);
      return;
    }

    setIsSubmitting(true);
    await onSelectDestinationAndSearch(match);
    setIsSubmitting(false);
  }

  async function handlePickAvailableDestination(dest: Destination) {
    setUnavailableCity(null);
    setCityQuery(dest.city_name);
    setAutocompleteOpen(false);
    setIsSubmitting(true);
    await onSelectDestinationAndSearch(dest);
    setIsSubmitting(false);
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
      {/* Bandeau Hero avec grande photo aux dimensions réservées */}
      <section className="relative mx-auto max-w-6xl px-4 pt-6 sm:pt-8">
        <div className="relative overflow-hidden rounded-card bg-slate-900 shadow-card min-h-[420px] sm:min-h-[460px] flex flex-col justify-end">
          <img
            src={
              destinations[0]?.hero_image_url ||
              "https://images.unsplash.com/photo-1597212618440-806262de4f6b?auto=format&fit=crop&w=1400&q=80"
            }
            alt="Destination de voyage ensoleillée"
            width={1440}
            height={560}
            loading="eager"
            className="absolute inset-0 h-full w-full object-cover object-center opacity-80"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-slate-950/85 via-slate-950/45 to-slate-950/15" />

          <div className="relative z-10 p-6 sm:p-10 md:p-12 w-full max-w-5xl">
            <Badge variant="brand" className="mb-3 bg-white/95 text-brand-800 border-0">
              Voyages organisés sereinement
            </Badge>
            <h1 className="text-h1 sm:text-display text-white tracking-tight">
              Où commence votre prochain voyage ?
            </h1>
            <p className="mt-2 text-body text-slate-100 max-w-2xl">
              Choisissez votre destination, réservez votre vol et composez vos visites jour par jour à votre rythme.
            </p>

            {/* Formulaire de recherche sobre : 4 éléments visibles max */}
            <form
              onSubmit={handleSubmitSearch}
              data-testid="home-search-form"
              className="mt-6 grid grid-cols-1 md:grid-cols-12 gap-3 rounded-card bg-canvas-card p-3.5 shadow-popover border border-border"
            >
              {/* Champ 1 : Où allez-vous ? avec autocomplétion par nom de ville */}
              <div ref={searchBoxRef} className="relative md:col-span-4">
                <label
                  htmlFor="home-destination-input"
                  className="block text-caption font-medium text-ink-secondary mb-1 pl-1"
                >
                  Où allez-vous ?
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
                      setUnavailableCity(null);
                      setAutocompleteOpen(true);
                    }}
                    placeholder="Marrakech, Tokyo, Rome..."
                    autoComplete="off"
                    className="pl-9"
                  />
                </div>

                {/* Menu d'autocomplétion par nom de ville */}
                {autocompleteOpen && filteredSuggestions.length > 0 && (
                  <div
                    role="listbox"
                    aria-label="Suggestions de villes"
                    data-testid="home-autocomplete-list"
                    className="absolute left-0 right-0 top-full z-40 mt-1.5 max-h-64 overflow-auto rounded-card border border-border bg-canvas-card p-1.5 shadow-popover"
                  >
                    {filteredSuggestions.map((dest) => (
                      <button
                        key={dest.id}
                        type="button"
                        role="option"
                        aria-selected={cityQuery === dest.city_name}
                        data-testid={`autocomplete-city-${dest.city_name.toLowerCase()}`}
                        onClick={() => {
                          setCityQuery(dest.city_name);
                          setUnavailableCity(null);
                          setAutocompleteOpen(false);
                        }}
                        className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left hover:bg-brand-50 focus:bg-brand-50 focus:outline-none"
                      >
                        <div>
                          <div className="text-body font-medium text-ink">
                            {dest.city_name}
                          </div>
                          <div className="text-caption text-ink-muted">
                            {dest.country_name}
                          </div>
                        </div>
                        <span className="text-caption text-brand-700 font-medium">
                          Choisir
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Champ 2 : Dates (Calendrier react-day-picker) */}
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
                      <DayPicker
                        mode="range"
                        locale={fr}
                        selected={selectedRange}
                        defaultMonth={selectedRange.from}
                        onSelect={(range) => {
                          if (range?.from) {
                            const dep = format(range.from, "yyyy-MM-dd");
                            const ret = range.to
                              ? format(range.to, "yyyy-MM-dd")
                              : format(
                                  new Date(range.from.getTime() + 7 * 86400000),
                                  "yyyy-MM-dd"
                                );
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
          </div>
        </div>

        {/* Message contextuel sobre si la ville saisie est hors démonstration */}
        {unavailableCity && (
          <Card
            data-testid="unavailable-demo-city-card"
            className="mt-4 border-amber-200 bg-feedback-warningBg p-5"
          >
            <p className="text-body font-semibold text-ink">
              Cette destination n'est pas encore disponible en démonstration
            </p>
            <p className="mt-1 text-caption text-ink-secondary">
              Vous avez recherché « {unavailableCity} ». Choisissez l'une des destinations disponibles ci-dessous pour découvrir les vols et activités :
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {destinations.map((dest) => (
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

      {/* Dessous : Destinations populaires en grandes cartes photo */}
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
            {destinations.map((dest) => (
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
  departureDate,
  returnDate,
  travelers,
  onSelectDestination,
  onBookSuccess,
  token,
}: {
  activeTrip: Trip | null;
  activeDestination: Destination | null;
  destinations: Destination[];
  originIata: string;
  onChangeOriginIata: (val: string) => void;
  departureDate: string;
  returnDate: string;
  travelers: string;
  onSelectDestination: (dest: Destination) => Promise<void>;
  onBookSuccess: (booking: FlightBooking) => void;
  token: string;
}) {
  const navigate = useNavigate();
  const { notify } = useToast();
  const [sortBy, setSortBy] = useState<"cheapest" | "fastest">("cheapest");
  const [bookingError, setBookingError] = useState<string>("");
  const [bookingOfferId, setBookingOfferId] = useState<string | null>(null);

  const destinationCity = activeDestination?.city_name || "Marrakech";
  const destinationIata = activeDestination?.iata_code || "RAK";
  const effectiveOrigin =
    originIata.toUpperCase() === destinationIata.toUpperCase() ? "LHR" : originIata;

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
          computeDurationMinutes(a.departure_outbound_at, a.arrival_outbound_at) +
          computeDurationMinutes(a.departure_inbound_at, a.arrival_inbound_at);
        const durB =
          computeDurationMinutes(b.departure_outbound_at, b.arrival_outbound_at) +
          computeDurationMinutes(b.departure_inbound_at, b.arrival_inbound_at);
        return durA - durB;
      });
    }
    return copy;
  }, [offers, sortBy]);

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

  const departureOptions = useMemo(() => {
    return DEPARTURE_AIRPORTS.filter(
      (a) => a.value.toUpperCase() !== destinationIata.toUpperCase()
    ).map((a) => ({ value: a.value, label: a.label }));
  }, [destinationIata]);

  const arrivalAirportLabel =
    AIRPORT_CITY_NAMES[destinationIata] || `${destinationCity} (Aéroport principal)`;
  const originAirportLabel =
    AIRPORT_CITY_NAMES[effectiveOrigin] || "Paris (Charles de Gaulle)";

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:py-10" data-testid="flights-screen">
      {/* En-tête sobre : aéroport d'arrivée issu de la destination, départ déduit et modifiable */}
      <div className="mb-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <Badge variant="brand" className="mb-2">
              Aller-retour • {travelers} {Number(travelers) > 1 ? "voyageurs" : "voyageur"}
            </Badge>
            <h1 className="text-h1 text-ink" data-testid="flights-heading">
              Vols vers {destinationCity}
            </h1>
            <p className="mt-1 text-body text-ink-muted">
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

        {/* Barre sobre de paramètres : Ville de départ modifiable + destination affichée + tri */}
        <Card className="mt-5 p-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 items-end">
            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Aéroport de départ
              </label>
              <Select
                value={effectiveOrigin}
                onValueChange={onChangeOriginIata}
                ariaLabel="Aéroport de départ"
                options={departureOptions}
              />
            </div>

            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Destination du séjour
              </label>
              <Select
                value={activeDestination?.id || destinations[0]?.id || ""}
                onValueChange={(destId) => {
                  const found = destinations.find((d) => d.id === destId);
                  if (found) onSelectDestination(found);
                }}
                ariaLabel="Destination du séjour"
                options={destinations.map((d) => ({
                  value: d.id,
                  label: `${d.city_name} (${d.country_name})`,
                }))}
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
        /* État 3 : Liste vide avec message utile et action */
        <Card className="p-8 text-center" data-testid="flights-empty-state">
          <h2 className="text-h2 text-ink">
            Aucun vol trouvé pour ces critères
          </h2>
          <p className="mt-2 text-body text-ink-muted max-w-md mx-auto">
            Essayez un autre aéroport de départ ou modifiez vos dates de voyage sur l'accueil.
          </p>
          <div className="mt-5">
            <Button type="button" variant="secondary" onClick={() => navigate("/")}>
              Modifier ma recherche
            </Button>
          </div>
        </Card>
      ) : (
        /* Liste des offres en cartes sobres */
        <div className="space-y-4" data-testid="flights-offers-list">
          {sortedOffers.map((offer, idx) => {
            const outDuration = computeDurationMinutes(
              offer.departure_outbound_at,
              offer.arrival_outbound_at
            );
            const inDuration = computeDurationMinutes(
              offer.departure_inbound_at,
              offer.arrival_inbound_at
            );
            const isBookingThis = bookingOfferId === offer.offer_id;

            return (
              <Card
                key={offer.offer_id}
                data-testid={`flight-offer-card-${idx}`}
                className="p-5 sm:p-6 transition-shadow hover:shadow-card"
              >
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
                  <div className="flex-1 space-y-4">
                    {/* Compagnie & confort */}
                    <div className="flex flex-wrap items-center gap-2.5">
                      <span className="text-h2 font-semibold text-ink">
                        {offer.airline_name}
                      </span>
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
                        <span>Durée : {formatDurationHuman(outDuration)} • Direct</span>
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
                        <span>Durée : {formatDurationHuman(inDuration)} • Direct</span>
                      </div>
                      <div className="text-caption text-ink-secondary sm:text-right">
                        {destinationCity} → {originAirportLabel.split(" (")[0]}
                      </div>
                    </div>
                  </div>

                  {/* Prix & bouton Réserver */}
                  <div className="flex flex-row md:flex-col items-center md:items-end justify-between gap-3 pt-4 md:pt-0 border-t md:border-t-0 md:border-l border-border md:pl-6 min-w-[170px]">
                    <div className="md:text-right">
                      <div
                        className="text-h1 font-bold text-ink"
                        data-testid={`flight-offer-price-${idx}`}
                      >
                        {Math.round(Number(offer.price_amount))} €
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
  const [originIata, setOriginIata] = useState<string>("CDG");
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
  const [preferences, setPreferences] = useState<TravelerPreferences>({
    currency: "EUR",
    language: "fr",
    travelStyle: "STANDARD",
  });

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
      setTrips(loadedTrips);
      setActiveTripId(loadedTrips[0].id);
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

  const activeDestination = useMemo(
    () =>
      destinations.find((d) => d.id === activeTrip?.destination_id) ||
      destinations.find((d) => d.city_name === "Marrakech") ||
      destinations[0] ||
      null,
    [destinations, activeTrip]
  );

  async function refreshGallery(category: string = "") {
    if (!activeTrip?.id || !token) return;
    const url = new URL(`${API_BASE}/api/v1/places/trip/${activeTrip.id}/gallery`);
    if (category) url.searchParams.set("category", category);
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
  async function ensureTripForDestination(dest: Destination): Promise<Trip | null> {
    const existing = trips.find((t) => t.destination_id === dest.id);
    if (existing) {
      setActiveTripId(existing.id);
      return existing;
    }
    if (!token) return null;
    const resp = await fetch(`${API_BASE}/api/v1/trips`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        destination_id: dest.id,
        title: `Voyage à ${dest.city_name}`,
        travel_style: preferences.travelStyle,
        total_budget_planned: 2200,
        currency: preferences.currency,
        arrival_at: `${departureDate}T10:30:00Z`,
        departure_at: `${returnDate}T18:00:00Z`,
      }),
    });
    if (resp.ok) {
      const created: Trip = await resp.json();
      setTrips((prev) => [created, ...prev]);
      setActiveTripId(created.id);
      return created;
    }
    return null;
  }

  async function handleSelectDestinationAndGoToFlights(dest: Destination) {
    if (dest.iata_code.toUpperCase() === originIata.toUpperCase()) {
      setOriginIata("LHR");
    }
    await ensureTripForDestination(dest);
    navigate("/flights");
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
                initialUnavailableCity={ssrState?.initialUnavailableCity ?? null}
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
                departureDate={departureDate}
                returnDate={returnDate}
                travelers={travelers}
                onSelectDestination={async (dest) => {
                  await ensureTripForDestination(dest);
                }}
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
        "https://images.unsplash.com/photo-1597212618440-806262de4f6b?auto=format&fit=crop&w=1400&q=80",
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
        "https://images.unsplash.com/photo-1540959733332-eab4deabeeaf?auto=format&fit=crop&w=1400&q=80",
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
        "https://images.unsplash.com/photo-1552832230-c0197dd311b5?auto=format&fit=crop&w=1400&q=80",
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
    name: "Riad Jardin des Orangers",
    type: "HOTEL",
    source: "HOTEL",
    source_provider: "TravelMate",
    source_label: "Sélection vérifiée",
    provider_mode: "LIVE",
    is_simulated: false,
    luxury_tier: "STANDARD",
    booking_redirect_url: "https://example.com/riad",
    neighborhood: "Médina — Kasbah",
    address: "18 Derb Sidi Bouloukat, Marrakech",
    latitude: 31.6258,
    longitude: -7.9891,
    price_per_night: "145.00",
    currency: "EUR",
    rating: 4.8,
    amenities: ["Petit-déjeuner inclus", "Patio arboré", "Wi-Fi"],
    photos: [
      "https://images.unsplash.com/photo-1582719508461-905c673771fd?auto=format&fit=crop&w=900&q=80",
    ],
    distance_from_center_km: 0.8,
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
          "https://images.unsplash.com/photo-1564507592333-c60657eea523?auto=format&fit=crop&w=1000&q=80",
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

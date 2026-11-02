import React, { useEffect, useMemo, useState } from "react";
import L from "leaflet";
import {
  MapContainer,
  Marker,
  Polyline,
  Popup,
  TileLayer,
  Tooltip,
  useMap,
} from "react-leaflet";

export interface TripStageItem {
  id: string;
  trip_id: string;
  order_index: number;
  destination_id: string;
  geoname_id?: number | null;
  city_name: string;
  country_name: string;
  country_code_iso2: string;
  latitude: number;
  longitude: number;
  iata_code?: string | null;
  hero_image_url?: string | null;
  arrival_date: string;
  nights: number;
  departure_date: string;
  arrival_at: string;
  departure_at: string;
  timezone: string;
  arrival_transport_mode: string;
  departure_transport_mode?: string | null;
  arrival_buffer_hours?: number;
  departure_buffer_hours?: number;
  visit_window_start_local?: string | null;
  visit_window_end_local?: string | null;
  transport_unlocked?: boolean;
  gallery_unlocked?: boolean;
  transport_booking_ref?: string | null;
  selected_place_ids?: string[];
  planned_budget?: number | null;
}

export interface DraftStageFormItem {
  key: string;
  id?: string;
  destination_id?: string;
  geoname_id?: number | null;
  city_name: string;
  country_name: string;
  country_code_iso2: string;
  timezone: string;
  latitude?: number | null;
  longitude?: number | null;
  iata_code?: string | null;
  arrival_date: string;
  departure_date: string;
  nights: number;
  arrival_transport_mode: string;
}

export interface MapValidatedVisitItem {
  id: string;
  place_id: string;
  place_name: string;
  place_category?: string;
  stage_id?: string | null;
  stage_order_index?: number | null;
  stage_city_name?: string | null;
  latitude: number;
  longitude: number;
  local_visit_date: string;
  local_start_time: string;
  local_end_time: string;
  duration_minutes: number;
}

export interface StageValidationOutcome {
  valid: boolean;
  error: string | null;
  reasonCode: string | null;
}

export function addDaysIso(isoDate: string, days: number): string {
  const clean = String(isoDate || "").slice(0, 10);
  const parts = clean.split("-").map((n) => parseInt(n, 10));
  if (parts.length !== 3 || parts.some((n) => Number.isNaN(n))) {
    return clean;
  }
  const dt = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2] + days));
  return dt.toISOString().slice(0, 10);
}

export function diffDaysIso(startIso: string, endIso: string): number {
  const s = String(startIso || "").slice(0, 10).split("-").map((n) => parseInt(n, 10));
  const e = String(endIso || "").slice(0, 10).split("-").map((n) => parseInt(n, 10));
  if (s.length !== 3 || e.length !== 3 || s.some(Number.isNaN) || e.some(Number.isNaN)) {
    return 0;
  }
  const msStart = Date.UTC(s[0], s[1] - 1, s[2]);
  const msEnd = Date.UTC(e[0], e[1] - 1, e[2]);
  return Math.round((msEnd - msStart) / 86400000);
}

export function validateDraftStagesNoOverlap(
  stages: DraftStageFormItem[]
): StageValidationOutcome {
  if (!stages || stages.length < 1 || stages.length > 10) {
    return {
      valid: false,
      reasonCode: "INVALID_STAGE_COUNT",
      error: "Un voyage doit comprendre entre 1 et 10 étapes.",
    };
  }

  for (let idx = 0; idx < stages.length; idx += 1) {
    const st = stages[idx];
    const stepNum = idx + 1;
    const cityLabel = (st.city_name || "").trim() || `Étape ${stepNum}`;
    if (!(st.city_name || "").trim()) {
      return {
        valid: false,
        reasonCode: "MISSING_STAGE_CITY",
        error: `Veuillez renseigner une ville pour l'étape ${stepNum}.`,
      };
    }
    if (!st.arrival_date || !st.departure_date) {
      return {
        valid: false,
        reasonCode: "INVALID_STAGE_DATE",
        error: `Veuillez renseigner les dates d'arrivée et de départ de l'étape ${stepNum} (${cityLabel}).`,
      };
    }
    const nights = diffDaysIso(st.arrival_date, st.departure_date);
    if (nights < 1) {
      return {
        valid: false,
        reasonCode: "INCONSISTENT_STAGE_DATES",
        error: `Les dates de l'étape ${stepNum} (${cityLabel}) sont incohérentes : la date de départ (${st.departure_date}) doit être postérieure à la date d'arrivée (${st.arrival_date}, au moins 1 nuit sur place).`,
      };
    }

    if (idx > 0) {
      const prev = stages[idx - 1];
      const prevCity = (prev.city_name || "").trim() || `Étape ${idx}`;
      if (st.arrival_date < prev.departure_date) {
        return {
          valid: false,
          reasonCode: "STAGE_DATE_OVERLAP",
          error: `Les dates des étapes se chevauchent : l'étape ${stepNum} (${cityLabel}) commence le ${st.arrival_date} alors que l'étape ${idx} (${prevCity}) se termine le ${prev.departure_date}.`,
        };
      }
      if (st.arrival_date > prev.departure_date) {
        return {
          valid: false,
          reasonCode: "STAGE_DATE_GAP",
          error: `Les étapes doivent se suivre sans trou : l'étape ${stepNum} (${cityLabel}) doit commencer le ${prev.departure_date} (date de départ de l'étape ${idx} à ${prevCity}).`,
        };
      }
      const prevKey =
        prev.destination_id ||
        (prev.geoname_id ? `geo:${prev.geoname_id}` : prevCity.toLowerCase());
      const curKey =
        st.destination_id ||
        (st.geoname_id ? `geo:${st.geoname_id}` : cityLabel.toLowerCase());
      if (prevKey && curKey && prevKey === curKey) {
        return {
          valid: false,
          reasonCode: "CONSECUTIVE_DUPLICATE_CITY",
          error: `Vous ne pouvez pas mettre deux fois la même ville à la suite (${cityLabel} aux étapes ${idx} et ${stepNum}).`,
        };
      }
    }
  }

  return { valid: true, error: null, reasonCode: null };
}

export function autoChainDraftStagesDates(
  stages: DraftStageFormItem[]
): DraftStageFormItem[] {
  if (!stages.length) return [];
  const next: DraftStageFormItem[] = [];
  let cursorDate = stages[0].arrival_date || "2026-06-15";
  for (let i = 0; i < stages.length; i += 1) {
    const st = stages[i];
    const arr = i === 0 ? cursorDate : cursorDate;
    const rawNights = diffDaysIso(st.arrival_date, st.departure_date);
    const nights = Math.max(1, st.nights >= 1 ? st.nights : rawNights >= 1 ? rawNights : 2);
    const dep = addDaysIso(arr, nights);
    cursorDate = dep;
    next.push({
      ...st,
      arrival_date: arr,
      departure_date: dep,
      nights,
    });
  }
  return next;
}

const TRANSPORT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "VOL", label: "✈️ Vol (avion)" },
  { value: "TRAIN", label: "🚆 Train" },
  { value: "BUS", label: "🚌 Bus / autocar" },
  { value: "BATEAU", label: "⛴️ Bateau / ferry" },
  { value: "VOITURE", label: "🚗 Voiture" },
];

function createStageDivIcon(orderIndex: number, cityName: string): L.DivIcon {
  const safeCity = String(cityName || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return L.divIcon({
    className: "tm-leaflet-stage-icon",
    html: `<div class="tm-stage-marker-pin" data-testid="map-stage-marker-${orderIndex}" data-stage-order="${orderIndex}" data-city="${safeCity}" style="display:inline-flex;align-items:center;gap:6px;background:#0F766E;color:#FFFFFF;border:2px solid #FFFFFF;border-radius:999px;padding:4px 10px 4px 6px;font-weight:800;font-size:12px;box-shadow:0 4px 12px rgba(15,118,110,0.38);white-space:nowrap;">
      <span style="display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;border-radius:50%;background:#FFFFFF;color:#0F766E;font-size:11px;font-weight:900;">${orderIndex}</span>
      <span>${safeCity}</span>
    </div>`,
    iconSize: [120, 30],
    iconAnchor: [20, 15],
    popupAnchor: [0, -14],
  });
}

function createVisitDivIcon(placeName: string, visitId: string): L.DivIcon {
  const safePlace = String(placeName || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return L.divIcon({
    className: "tm-leaflet-visit-icon",
    html: `<div class="tm-visit-marker-pin" data-testid="map-visit-marker-${visitId}" data-place-name="${safePlace}" style="display:inline-flex;align-items:center;gap:4px;background:#FFFBEB;color:#92400E;border:2px solid #D97706;border-radius:999px;padding:2px 8px;font-weight:700;font-size:11px;box-shadow:0 2px 8px rgba(217,119,6,0.28);white-space:nowrap;">
      <span style="color:#D97706;font-size:12px;">★</span>
      <span style="max-width:130px;overflow:hidden;text-overflow:ellipsis;">${safePlace}</span>
    </div>`,
    iconSize: [130, 24],
    iconAnchor: [16, 12],
    popupAnchor: [0, -10],
  });
}

function MapBoundsController({ points }: { points: Array<[number, number]> }) {
  const map = useMap();
  const pointsSignature = points.map((p) => `${p[0].toFixed(4)},${p[1].toFixed(4)}`).join("|");

  useEffect(() => {
    if (!map || points.length === 0) return;
    const timer = window.setTimeout(() => {
      try {
        map.invalidateSize();
        if (points.length === 1) {
          map.setView(points[0], 11, { animate: false });
        } else {
          const bounds = L.latLngBounds(points);
          if (bounds.isValid()) {
            map.fitBounds(bounds, { padding: [38, 38], maxZoom: 12, animate: false });
          }
        }
      } catch {
        // Ignore transient Leaflet layout resize errors
      }
    }, 60);
    return () => window.clearTimeout(timer);
  }, [map, pointsSignature]);

  return null;
}

export interface TripMultiCityMapProps {
  stages: TripStageItem[];
  visits: MapValidatedVisitItem[];
  fallbackDestination?: {
    id: string;
    city_name: string;
    country_name: string;
    latitude: number;
    longitude: number;
  } | null;
  destinationsCatalog?: Array<{
    id: string;
    city_name: string;
    country_name: string;
    latitude: number;
    longitude: number;
  }>;
  height?: number;
}

export function TripMultiCityMap({
  stages,
  visits,
  fallbackDestination,
  destinationsCatalog = [],
  height = 340,
}: TripMultiCityMapProps) {
  const resolvedStages = useMemo(() => {
    const sorted = [...(stages || [])].sort((a, b) => a.order_index - b.order_index);
    if (sorted.length === 0 && fallbackDestination) {
      return [
        {
          id: "fallback-stage-1",
          trip_id: "",
          order_index: 1,
          destination_id: fallbackDestination.id,
          city_name: fallbackDestination.city_name,
          country_name: fallbackDestination.country_name,
          country_code_iso2: "XX",
          latitude: fallbackDestination.latitude,
          longitude: fallbackDestination.longitude,
          arrival_date: "",
          nights: 1,
          departure_date: "",
          arrival_at: "",
          departure_at: "",
          timezone: "UTC",
          arrival_transport_mode: "VOL",
        } as TripStageItem,
      ];
    }

    return sorted.map((st) => {
      let lat = Number(st.latitude || 0);
      let lng = Number(st.longitude || 0);
      if (Math.abs(lat) < 0.0001 && Math.abs(lng) < 0.0001) {
        const match =
          destinationsCatalog.find((d) => d.id === st.destination_id) ||
          destinationsCatalog.find(
            (d) => d.city_name.toLowerCase() === (st.city_name || "").toLowerCase()
          ) ||
          (fallbackDestination &&
          fallbackDestination.city_name.toLowerCase() === (st.city_name || "").toLowerCase()
            ? fallbackDestination
            : null);
        if (match) {
          lat = Number(match.latitude);
          lng = Number(match.longitude);
        }
      }
      return {
        ...st,
        latitude: lat,
        longitude: lng,
      };
    });
  }, [stages, fallbackDestination, destinationsCatalog]);

  const validStageMarkers = useMemo(
    () =>
      resolvedStages.filter(
        (st) =>
          Number.isFinite(st.latitude) &&
          Number.isFinite(st.longitude) &&
          !(Math.abs(st.latitude) < 0.0001 && Math.abs(st.longitude) < 0.0001)
      ),
    [resolvedStages]
  );

  const validVisitMarkers = useMemo(
    () =>
      (visits || []).filter(
        (v) =>
          Number.isFinite(v.latitude) &&
          Number.isFinite(v.longitude) &&
          !(Math.abs(v.latitude) < 0.0001 && Math.abs(v.longitude) < 0.0001)
      ),
    [visits]
  );

  const stagePolylinePositions = useMemo<Array<[number, number]>>(
    () => validStageMarkers.map((st) => [st.latitude, st.longitude]),
    [validStageMarkers]
  );

  const allMapPoints = useMemo<Array<[number, number]>>(
    () => [
      ...validStageMarkers.map((st) => [st.latitude, st.longitude] as [number, number]),
      ...validVisitMarkers.map((v) => [v.latitude, v.longitude] as [number, number]),
    ],
    [validStageMarkers, validVisitMarkers]
  );

  const initialCenter: [number, number] =
    allMapPoints.length > 0 ? allMapPoints[0] : [48.8566, 2.3522];

  const isBrowser =
    typeof window !== "undefined" &&
    typeof document !== "undefined" &&
    !(window as any).__SSR_SHIM__ &&
    typeof window.addEventListener === "function";

  return (
    <section
      className="card"
      data-testid="trip-multi-city-map-card"
      style={{
        padding: "16px 18px",
        marginBottom: 18,
        border: "1px solid var(--border)",
        borderRadius: 16,
        background: "#FFFFFF",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 10,
          marginBottom: 12,
        }}
      >
        <div>
          <span
            className="badge badge-teal"
            style={{ marginBottom: 4, display: "inline-block" }}
          >
            CARTE INTERACTIVE DE L&apos;ITINÉRAIRE
          </span>
          <h3 style={{ fontSize: "1.08rem", margin: 0 }}>
            Tracé chronologique des étapes ({resolvedStages.length}{" "}
            {resolvedStages.length > 1 ? "villes" : "ville"}) &amp; lieux visités (
            {validVisitMarkers.length})
          </h3>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            fontSize: "0.8rem",
            color: "var(--text-muted)",
            flexWrap: "wrap",
          }}
        >
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span
              style={{
                width: 12,
                height: 12,
                borderRadius: "50%",
                background: "#0F766E",
                display: "inline-block",
              }}
            />
            Étapes du voyage ({validStageMarkers.length})
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span
              style={{
                width: 18,
                height: 3,
                background: "#0F766E",
                display: "inline-block",
              }}
            />
            Polyligne chronologique
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span
              style={{
                width: 12,
                height: 12,
                borderRadius: "50%",
                background: "#FEF3C7",
                border: "2px solid #D97706",
                display: "inline-block",
              }}
            />
            Lieux validés ({validVisitMarkers.length})
          </span>
        </div>
      </div>

      <div
        data-testid="trip-multi-city-map-leaflet"
        style={{
          width: "100%",
          height,
          borderRadius: 12,
          overflow: "hidden",
          border: "1px solid var(--border)",
          position: "relative",
          background: "#E2E8F0",
        }}
      >
        {isBrowser ? (
          <MapContainer
            center={initialCenter}
            zoom={validStageMarkers.length > 1 ? 5 : 11}
            scrollWheelZoom={false}
            style={{ width: "100%", height: "100%" }}
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <MapBoundsController points={allMapPoints} />

            {stagePolylinePositions.length >= 2 && (
              <Polyline
                positions={stagePolylinePositions}
                pathOptions={{
                  color: "#0F766E",
                  weight: 4,
                  opacity: 0.88,
                  dashArray: "8 6",
                  className: "tm-itinerary-stage-polyline",
                }}
              />
            )}

            {validStageMarkers.map((st) => (
              <Marker
                key={`stage-marker-${st.id || st.order_index}`}
                position={[st.latitude, st.longitude]}
                icon={createStageDivIcon(st.order_index, st.city_name)}
              >
                <Tooltip direction="top" offset={[0, -10]}>
                  <span>
                    Étape {st.order_index} : {st.city_name}
                  </span>
                </Tooltip>
                <Popup>
                  <div style={{ minWidth: 170 }}>
                    <strong>
                      Étape {st.order_index} · {st.city_name}
                    </strong>
                    <div style={{ fontSize: "0.8rem", color: "#475569", marginTop: 2 }}>
                      {st.country_name}
                    </div>
                    {st.arrival_date && st.departure_date && (
                      <div style={{ fontSize: "0.78rem", marginTop: 4 }}>
                        Du <strong>{st.arrival_date}</strong> au{" "}
                        <strong>{st.departure_date}</strong> ({st.nights} nuit
                        {st.nights > 1 ? "s" : ""})
                      </div>
                    )}
                    <div style={{ fontSize: "0.74rem", color: "#64748B", marginTop: 4 }}>
                      GPS : {st.latitude.toFixed(4)}, {st.longitude.toFixed(4)}
                    </div>
                  </div>
                </Popup>
              </Marker>
            ))}

            {validVisitMarkers.map((visit) => (
              <Marker
                key={`visit-marker-${visit.id}`}
                position={[visit.latitude, visit.longitude]}
                icon={createVisitDivIcon(visit.place_name, visit.id)}
              >
                <Tooltip direction="top" offset={[0, -8]}>
                  <span>
                    Visite validée : {visit.place_name} ({visit.local_start_time})
                  </span>
                </Tooltip>
                <Popup>
                  <div style={{ minWidth: 170 }}>
                    <strong style={{ color: "#92400E" }}>★ {visit.place_name}</strong>
                    {visit.stage_city_name && (
                      <div style={{ fontSize: "0.78rem", color: "#0F766E", fontWeight: 600 }}>
                        Ville : {visit.stage_city_name}
                      </div>
                    )}
                    <div style={{ fontSize: "0.78rem", marginTop: 4 }}>
                      {visit.local_visit_date} · {visit.local_start_time} →{" "}
                      {visit.local_end_time} ({visit.duration_minutes} min)
                    </div>
                  </div>
                </Popup>
              </Marker>
            ))}
          </MapContainer>
        ) : (
          <div style={{ padding: 16 }}>
            Carte interactive de l&apos;itinéraire ({validStageMarkers.length} étapes,{" "}
            {validVisitMarkers.length} visites validées)
          </div>
        )}
      </div>

      {/* Légende chronologique des étapes et visites validées */}
      <div
        data-testid="trip-map-stages-legend"
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: 8,
          marginTop: 12,
        }}
      >
        {resolvedStages.map((st, idx) => (
          <React.Fragment key={st.id || `legend-stage-${idx}`}>
            <div
              data-testid={`trip-map-stage-chip-${st.order_index}`}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "5px 10px",
                borderRadius: 999,
                background: "#F0FDFA",
                border: "1px solid #99F6E4",
                fontSize: "0.8rem",
                color: "#0F766E",
                fontWeight: 700,
              }}
            >
              <span
                style={{
                  width: 18,
                  height: 18,
                  borderRadius: "50%",
                  background: "#0F766E",
                  color: "#FFF",
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "0.72rem",
                }}
              >
                {st.order_index}
              </span>
              <span>{st.city_name}</span>
              {st.arrival_date && st.departure_date && (
                <span style={{ fontWeight: 500, color: "#475569", fontSize: "0.75rem" }}>
                  ({st.arrival_date} → {st.departure_date})
                </span>
              )}
            </div>
            {idx < resolvedStages.length - 1 && (
              <span style={{ color: "#0F766E", fontWeight: 800, fontSize: "0.9rem" }}>
                →
              </span>
            )}
          </React.Fragment>
        ))}
      </div>
    </section>
  );
}

export interface HomeMultiCityBuilderProps {
  enabled: boolean;
  onToggleEnabled: (enabled: boolean) => void;
  stages: DraftStageFormItem[];
  onChangeStages: (nextStages: DraftStageFormItem[]) => void;
  destinationsCatalog: Array<{
    id: string;
    city_name: string;
    country_name: string;
    country_code_iso2: string;
    timezone: string;
    latitude: number;
    longitude: number;
    iata_code?: string;
  }>;
  apiBase: string;
}

export function HomeMultiCityBuilder({
  enabled,
  onToggleEnabled,
  stages,
  onChangeStages,
  destinationsCatalog,
  apiBase,
}: HomeMultiCityBuilderProps) {
  const [citySearchQueries, setCitySearchQueries] = useState<Record<string, string>>({});
  const [citySuggestions, setCitySuggestions] = useState<Record<string, any[]>>({});

  const validation = useMemo(() => validateDraftStagesNoOverlap(stages), [stages]);

  const handleSearchStageCity = async (stageKey: string, query: string) => {
    setCitySearchQueries((prev) => ({ ...prev, [stageKey]: query }));
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setCitySuggestions((prev) => ({ ...prev, [stageKey]: [] }));
      return;
    }
    try {
      const res = await fetch(
        `${apiBase}/api/v1/destinations/search?q=${encodeURIComponent(trimmed)}&limit=6`
      );
      if (res.ok) {
        const data = await res.json();
        const items = Array.isArray(data)
          ? data
          : Array.isArray(data?.results) && data.results.length > 0
          ? data.results
          : Array.isArray(data?.fallback_cities)
          ? data.fallback_cities
          : [];
        setCitySuggestions((prev) => ({
          ...prev,
          [stageKey]: items,
        }));
      }
    } catch {
      // Fallback silencieux sur le catalogue local
    }
  };

  const handleSelectCatalogDestination = (idx: number, destId: string) => {
    const dest = destinationsCatalog.find((d) => d.id === destId);
    if (!dest) return;
    const next = stages.map((st, i) =>
      i === idx
        ? {
            ...st,
            destination_id: dest.id,
            geoname_id: null,
            city_name: dest.city_name,
            country_name: dest.country_name,
            country_code_iso2: dest.country_code_iso2,
            timezone: dest.timezone || "UTC",
            latitude: dest.latitude,
            longitude: dest.longitude,
            iata_code: dest.iata_code || null,
          }
        : st
    );
    onChangeStages(next);
  };

  const handleSelectSearchSuggestion = (idx: number, stageKey: string, item: any) => {
    const rawCityName = String(item.city_name || item.nom || item.name || "").trim();
    const rawCountryName = String(item.country_name || item.pays || "Monde").trim();
    const rawCountryIso2 = String(item.country_code_iso2 || item.code_pays || "XX").trim();
    const existingDest = destinationsCatalog.find(
      (d) =>
        (item.destination_id && d.id === item.destination_id) ||
        d.city_name.toLowerCase() === rawCityName.toLowerCase()
    );
    const next = stages.map((st, i) =>
      i === idx
        ? {
            ...st,
            destination_id: existingDest?.id || item.destination_id || undefined,
            geoname_id: item.geoname_id ?? item.geonameId ?? null,
            city_name: rawCityName || st.city_name,
            country_name: rawCountryName || st.country_name || "Monde",
            country_code_iso2: rawCountryIso2 || st.country_code_iso2 || "XX",
            timezone:
              item.timezone ||
              item.fuseau_horaire ||
              existingDest?.timezone ||
              st.timezone ||
              "UTC",
            latitude:
              item.latitude ??
              item.coordonnees?.latitude ??
              existingDest?.latitude ??
              st.latitude ??
              null,
            longitude:
              item.longitude ??
              item.coordonnees?.longitude ??
              existingDest?.longitude ??
              st.longitude ??
              null,
            iata_code:
              item.iata_code ||
              item.nearest_airport_iata ||
              existingDest?.iata_code ||
              null,
          }
        : st
    );
    setCitySuggestions((prev) => ({ ...prev, [stageKey]: [] }));
    setCitySearchQueries((prev) => ({ ...prev, [stageKey]: "" }));
    onChangeStages(next);
  };

  const handleAddStage = () => {
    if (stages.length >= 10) return;
    const lastStage = stages[stages.length - 1];
    const usedCityNames = new Set(
      stages.map((s) => (s.city_name || "").trim().toLowerCase())
    );
    const candidateDest =
      destinationsCatalog.find(
        (d) =>
          !usedCityNames.has(d.city_name.toLowerCase()) &&
          d.city_name.toLowerCase() !== (lastStage?.city_name || "").toLowerCase()
      ) ||
      destinationsCatalog.find(
        (d) => d.city_name.toLowerCase() !== (lastStage?.city_name || "").toLowerCase()
      ) ||
      destinationsCatalog[0];

    const nextArr = lastStage?.departure_date || "2026-06-18";
    const nextDep = addDaysIso(nextArr, 3);
    const newStage: DraftStageFormItem = {
      key: `draft-stage-${Date.now()}-${stages.length + 1}`,
      destination_id: candidateDest?.id,
      city_name: candidateDest?.city_name || "Rome",
      country_name: candidateDest?.country_name || "Italie",
      country_code_iso2: candidateDest?.country_code_iso2 || "IT",
      timezone: candidateDest?.timezone || "Europe/Rome",
      latitude: candidateDest?.latitude ?? 41.9028,
      longitude: candidateDest?.longitude ?? 12.4964,
      iata_code: candidateDest?.iata_code ?? "FCO",
      arrival_date: nextArr,
      departure_date: nextDep,
      nights: 3,
      arrival_transport_mode: stages.length === 0 ? "VOL" : "TRAIN",
    };
    onChangeStages([...stages, newStage]);
    if (!enabled) {
      onToggleEnabled(true);
    }
  };

  const handleRemoveStage = (idx: number) => {
    if (stages.length <= 1) return;
    const remaining = stages.filter((_, i) => i !== idx);
    onChangeStages(remaining);
  };

  const handleMoveStage = (idx: number, direction: -1 | 1) => {
    const targetIdx = idx + direction;
    if (targetIdx < 0 || targetIdx >= stages.length) return;
    const copy = [...stages];
    const [moved] = copy.splice(idx, 1);
    copy.splice(targetIdx, 0, moved);
    onChangeStages(autoChainDraftStagesDates(copy));
  };

  const handleDateChange = (
    idx: number,
    field: "arrival_date" | "departure_date",
    value: string
  ) => {
    const cleanVal = String(value || "").slice(0, 10);
    const next = stages.map((st, i) => {
      if (i !== idx) return st;
      const updated = { ...st, [field]: cleanVal };
      const n = diffDaysIso(updated.arrival_date, updated.departure_date);
      updated.nights = Math.max(0, n);
      return updated;
    });
    onChangeStages(next);
  };

  return (
    <div
      data-testid="home-multi-city-builder"
      style={{
        marginTop: 14,
        marginBottom: 18,
        padding: "16px 18px",
        borderRadius: 14,
        border: enabled ? "2px solid var(--primary)" : "1px solid var(--border)",
        background: enabled ? "#F0FDFA" : "#F8FAFC",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 10,
        }}
      >
        <div>
          <strong style={{ fontSize: "0.96rem", color: "#0F172A" }}>
            Itinéraire multi-villes ({stages.length}{" "}
            {stages.length > 1 ? "étapes" : "étape"})
          </strong>
          <p
            style={{
              margin: "2px 0 0 0",
              fontSize: "0.82rem",
              color: "var(--text-muted)",
            }}
          >
            Ajoutez plusieurs destinations consécutives avec leurs dates d&apos;arrivée et
            de départ (sans chevauchement).
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button
            type="button"
            className="btn btn-secondary"
            data-testid="toggle-multi-city-mode-btn"
            onClick={() => onToggleEnabled(!enabled)}
            style={{ padding: "7px 12px", fontSize: "0.82rem" }}
          >
            {enabled
              ? "Masquer le détail des étapes"
              : `Configurer les étapes (${stages.length})`}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            data-testid="add-multi-city-stage-btn"
            onClick={handleAddStage}
            disabled={stages.length >= 10}
            style={{ padding: "7px 14px", fontSize: "0.82rem" }}
          >
            + Ajouter une étape
          </button>
        </div>
      </div>

      {enabled && (
        <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 12 }}>
          {stages.map((st, idx) => {
            const suggestions = citySuggestions[st.key] || [];
            const nights = diffDaysIso(st.arrival_date, st.departure_date);
            return (
              <div
                key={st.key}
                data-testid={`multi-city-stage-row-${idx + 1}`}
                style={{
                  background: "#FFFFFF",
                  border: "1px solid var(--border)",
                  borderRadius: 12,
                  padding: "12px 14px",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: 10,
                    gap: 8,
                    flexWrap: "wrap",
                  }}
                >
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 8,
                      fontWeight: 800,
                      color: "#0F766E",
                      fontSize: "0.9rem",
                    }}
                  >
                    <span
                      style={{
                        width: 24,
                        height: 24,
                        borderRadius: "50%",
                        background: "#0F766E",
                        color: "#FFFFFF",
                        display: "inline-flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: "0.78rem",
                      }}
                    >
                      {idx + 1}
                    </span>
                    Étape {idx + 1} : {st.city_name || "Choisir une ville"} (
                    {nights > 0 ? `${nights} nuit${nights > 1 ? "s" : ""}` : "dates à corriger"}
                    )
                  </span>

                  <div style={{ display: "flex", gap: 6 }}>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      data-testid={`stage-move-up-${idx + 1}`}
                      disabled={idx === 0}
                      onClick={() => handleMoveStage(idx, -1)}
                      style={{ padding: "4px 8px", fontSize: "0.78rem" }}
                      title="Monter cette étape"
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      data-testid={`stage-move-down-${idx + 1}`}
                      disabled={idx === stages.length - 1}
                      onClick={() => handleMoveStage(idx, 1)}
                      style={{ padding: "4px 8px", fontSize: "0.78rem" }}
                      title="Descendre cette étape"
                    >
                      ↓
                    </button>
                    {stages.length > 1 && (
                      <button
                        type="button"
                        className="btn btn-ghost"
                        data-testid={`stage-remove-${idx + 1}`}
                        onClick={() => handleRemoveStage(idx)}
                        style={{
                          padding: "4px 10px",
                          fontSize: "0.78rem",
                          color: "#B91C1C",
                        }}
                      >
                        Supprimer
                      </button>
                    )}
                  </div>
                </div>

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(175px, 1fr))",
                    gap: 10,
                  }}
                >
                  <div>
                    <label
                      style={{
                        display: "block",
                        fontSize: "0.76rem",
                        fontWeight: 700,
                        marginBottom: 4,
                      }}
                    >
                      Destination (catalogue ou recherche)
                    </label>
                    <select
                      className="input"
                      data-testid={`stage-destination-select-${idx + 1}`}
                      value={st.destination_id || ""}
                      onChange={(e) => {
                        if (e.target.value) {
                          handleSelectCatalogDestination(idx, e.target.value);
                        }
                      }}
                      style={{ marginBottom: 6 }}
                    >
                      <option value="">-- Ville personnalisée / GeoNames --</option>
                      {destinationsCatalog.map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.city_name} ({d.country_name})
                        </option>
                      ))}
                    </select>
                    <input
                      type="text"
                      className="input"
                      data-testid={`stage-city-input-${idx + 1}`}
                      placeholder="Ou saisir une ville (ex. Lyon, Milan...)"
                      value={
                        citySearchQueries[st.key] !== undefined &&
                        citySearchQueries[st.key] !== ""
                          ? citySearchQueries[st.key]
                          : st.city_name
                      }
                      onChange={(e) => {
                        const val = e.target.value;
                        const next = stages.map((item, i) =>
                          i === idx
                            ? {
                                ...item,
                                destination_id: undefined,
                                city_name: val,
                              }
                            : item
                        );
                        onChangeStages(next);
                        void handleSearchStageCity(st.key, val);
                      }}
                    />
                    {suggestions.length > 0 && (
                      <div
                        style={{
                          marginTop: 4,
                          border: "1px solid var(--border)",
                          borderRadius: 8,
                          background: "#FFF",
                          maxHeight: 150,
                          overflowY: "auto",
                        }}
                      >
                        {suggestions.map((sug, sIdx) => (
                          <button
                            key={`${st.key}-sug-${sIdx}`}
                            type="button"
                            onClick={() => handleSelectSearchSuggestion(idx, st.key, sug)}
                            style={{
                              display: "block",
                              width: "100%",
                              textAlign: "left",
                              padding: "6px 10px",
                              border: "none",
                              background: "transparent",
                              cursor: "pointer",
                              fontSize: "0.8rem",
                            }}
                          >
                            <strong>{sug.city_name || sug.nom}</strong> (
                            {sug.country_name || sug.pays})
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  <div>
                    <label
                      style={{
                        display: "block",
                        fontSize: "0.76rem",
                        fontWeight: 700,
                        marginBottom: 4,
                      }}
                    >
                      Date d&apos;arrivée (étape {idx + 1})
                    </label>
                    <input
                      type="date"
                      className="input"
                      data-testid={`stage-arrival-date-${idx + 1}`}
                      value={st.arrival_date}
                      onChange={(e) =>
                        handleDateChange(idx, "arrival_date", e.target.value)
                      }
                    />
                  </div>

                  <div>
                    <label
                      style={{
                        display: "block",
                        fontSize: "0.76rem",
                        fontWeight: 700,
                        marginBottom: 4,
                      }}
                    >
                      Date de départ (étape {idx + 1})
                    </label>
                    <input
                      type="date"
                      className="input"
                      data-testid={`stage-departure-date-${idx + 1}`}
                      value={st.departure_date}
                      onChange={(e) =>
                        handleDateChange(idx, "departure_date", e.target.value)
                      }
                    />
                  </div>

                  <div>
                    <label
                      style={{
                        display: "block",
                        fontSize: "0.76rem",
                        fontWeight: 700,
                        marginBottom: 4,
                      }}
                    >
                      Transport d&apos;arrivée
                    </label>
                    <select
                      className="input"
                      data-testid={`stage-transport-mode-${idx + 1}`}
                      value={st.arrival_transport_mode || "VOL"}
                      onChange={(e) => {
                        const next = stages.map((item, i) =>
                          i === idx
                            ? { ...item, arrival_transport_mode: e.target.value }
                            : item
                        );
                        onChangeStages(next);
                      }}
                    >
                      {TRANSPORT_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>
            );
          })}

          {!validation.valid && validation.error && (
            <div
              className="alert alert-danger"
              data-testid="multi-city-date-error"
              role="alert"
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: 10,
              }}
            >
              <span>{validation.error}</span>
              {(validation.reasonCode === "STAGE_DATE_OVERLAP" ||
                validation.reasonCode === "STAGE_DATE_GAP" ||
                validation.reasonCode === "INCONSISTENT_STAGE_DATES") && (
                <button
                  type="button"
                  className="btn btn-secondary"
                  data-testid="multi-city-auto-chain-btn"
                  onClick={() => onChangeStages(autoChainDraftStagesDates(stages))}
                  style={{ padding: "5px 10px", fontSize: "0.78rem" }}
                >
                  Ajuster les dates sans chevauchement
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export interface TripStagesManagerCardProps {
  tripId: string;
  stages: TripStageItem[];
  canWrite: boolean;
  apiBase: string;
  jwtToken: string;
  destinationsCatalog: Array<{
    id: string;
    city_name: string;
    country_name: string;
    country_code_iso2: string;
    timezone: string;
    latitude: number;
    longitude: number;
    iata_code?: string;
  }>;
  onStagesUpdated: (updatedStages: TripStageItem[]) => void;
}

export function TripStagesManagerCard({
  tripId,
  stages,
  canWrite,
  apiBase,
  jwtToken,
  destinationsCatalog,
  onStagesUpdated,
}: TripStagesManagerCardProps) {
  const [editingStageId, setEditingStageId] = useState<string | null>(null);
  const [editCityName, setEditCityName] = useState("");
  const [editDestId, setEditDestId] = useState("");
  const [editArrivalDate, setEditArrivalDate] = useState("");
  const [editDepartureDate, setEditDepartureDate] = useState("");
  const [editTransportMode, setEditTransportMode] = useState("TRAIN");

  const [showAddForm, setShowAddForm] = useState(false);
  const [newDestId, setNewDestId] = useState("");
  const [newCityName, setNewCityName] = useState("");
  const [newArrivalDate, setNewArrivalDate] = useState("");
  const [newDepartureDate, setNewDepartureDate] = useState("");
  const [newTransportMode, setNewTransportMode] = useState("TRAIN");

  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const orderedStages = useMemo(
    () => [...(stages || [])].sort((a, b) => a.order_index - b.order_index),
    [stages]
  );

  const openAddStageForm = () => {
    setErrorMsg(null);
    setSuccessMsg(null);
    const lastStage = orderedStages[orderedStages.length - 1];
    const defaultArr = lastStage?.departure_date || "2026-06-20";
    const defaultDep = addDaysIso(defaultArr, 2);
    const candidate =
      destinationsCatalog.find(
        (d) => d.city_name.toLowerCase() !== (lastStage?.city_name || "").toLowerCase()
      ) || destinationsCatalog[0];
    setNewDestId(candidate?.id || "");
    setNewCityName(candidate?.city_name || "Rome");
    setNewArrivalDate(defaultArr);
    setNewDepartureDate(defaultDep);
    setNewTransportMode("TRAIN");
    setShowAddForm(true);
  };

  const startEditingStage = (st: TripStageItem) => {
    setErrorMsg(null);
    setSuccessMsg(null);
    setEditingStageId(st.id);
    setEditDestId(st.destination_id || "");
    setEditCityName(st.city_name || "");
    setEditArrivalDate(st.arrival_date);
    setEditDepartureDate(st.departure_date);
    setEditTransportMode(st.arrival_transport_mode || "VOL");
  };

  const handleCreateStageSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    setSuccessMsg(null);

    const lastStage = orderedStages[orderedStages.length - 1];
    const nights = diffDaysIso(newArrivalDate, newDepartureDate);
    if (nights < 1) {
      setErrorMsg(
        "La date de départ de la nouvelle étape doit être postérieure à sa date d'arrivée (au moins 1 nuit)."
      );
      return;
    }
    if (lastStage && newArrivalDate < lastStage.departure_date) {
      setErrorMsg(
        `Les dates des étapes se chevauchent : la nouvelle étape (${newCityName}) commence le ${newArrivalDate} alors que l'étape précédente (${lastStage.city_name}) se termine le ${lastStage.departure_date}.`
      );
      return;
    }
    if (lastStage && newArrivalDate > lastStage.departure_date) {
      setErrorMsg(
        `Les étapes doivent se suivre sans trou : la nouvelle étape (${newCityName}) doit commencer le ${lastStage.departure_date}.`
      );
      return;
    }

    setBusy(true);
    try {
      const selectedDest = destinationsCatalog.find((d) => d.id === newDestId);
      const res = await fetch(`${apiBase}/api/v1/trips/${tripId}/stages`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${jwtToken}`,
        },
        body: JSON.stringify({
          destination_id: selectedDest ? selectedDest.id : undefined,
          city_name: selectedDest ? selectedDest.city_name : newCityName.trim(),
          country_name: selectedDest?.country_name || "Monde",
          country_code_iso2: selectedDest?.country_code_iso2 || "XX",
          timezone: selectedDest?.timezone || undefined,
          latitude: selectedDest?.latitude,
          longitude: selectedDest?.longitude,
          arrival_date: newArrivalDate,
          departure_date: newDepartureDate,
          nights,
          arrival_transport_mode: newTransportMode,
        }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        const msg =
          body?.detail?.message ||
          (typeof body?.detail === "string" ? body.detail : null) ||
          "Impossible d'ajouter cette étape.";
        setErrorMsg(msg);
        return;
      }
      const nextStages = Array.isArray(body) ? body : body?.stages;
      if (Array.isArray(nextStages)) {
        onStagesUpdated(nextStages);
      }
      setShowAddForm(false);
      setSuccessMsg("Étape ajoutée à l'itinéraire.");
    } catch (err: any) {
      setErrorMsg(err?.message || "Erreur réseau lors de l'ajout de l'étape.");
    } finally {
      setBusy(false);
    }
  };

  const handleSaveStageEdit = async (stageId: string) => {
    setErrorMsg(null);
    setSuccessMsg(null);
    const nights = diffDaysIso(editArrivalDate, editDepartureDate);
    if (nights < 1) {
      setErrorMsg(
        "La date de départ doit être postérieure à la date d'arrivée (au moins 1 nuit sur place)."
      );
      return;
    }
    const targetIdx = orderedStages.findIndex((s) => s.id === stageId);
    if (targetIdx > 0) {
      const prev = orderedStages[targetIdx - 1];
      if (editArrivalDate < prev.departure_date) {
        setErrorMsg(
          `Les dates des étapes se chevauchent : l'étape ${targetIdx + 1} commence le ${editArrivalDate} alors que l'étape ${targetIdx} (${prev.city_name}) se termine le ${prev.departure_date}.`
        );
        return;
      }
      if (editArrivalDate > prev.departure_date) {
        setErrorMsg(
          `Les étapes doivent se suivre sans trou : l'étape ${targetIdx + 1} doit commencer le ${prev.departure_date}.`
        );
        return;
      }
    }

    setBusy(true);
    try {
      const selectedDest = destinationsCatalog.find((d) => d.id === editDestId);
      const res = await fetch(`${apiBase}/api/v1/trips/${tripId}/stages/${stageId}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${jwtToken}`,
        },
        body: JSON.stringify({
          destination_id: selectedDest ? selectedDest.id : undefined,
          city_name: selectedDest ? selectedDest.city_name : editCityName.trim(),
          country_name: selectedDest?.country_name,
          country_code_iso2: selectedDest?.country_code_iso2,
          timezone: selectedDest?.timezone,
          latitude: selectedDest?.latitude,
          longitude: selectedDest?.longitude,
          arrival_date: editArrivalDate,
          departure_date: editDepartureDate,
          nights,
          arrival_transport_mode: editTransportMode,
          recalculate_dates: true,
        }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        const msg =
          body?.detail?.message ||
          (typeof body?.detail === "string" ? body.detail : null) ||
          "Impossible de modifier cette étape.";
        setErrorMsg(msg);
        return;
      }
      const nextStages = Array.isArray(body) ? body : body?.stages;
      if (Array.isArray(nextStages)) {
        onStagesUpdated(nextStages);
      }
      setEditingStageId(null);
      setSuccessMsg("Étape mise à jour.");
    } catch (err: any) {
      setErrorMsg(err?.message || "Erreur lors de la modification de l'étape.");
    } finally {
      setBusy(false);
    }
  };

  const handleReorderStage = async (idx: number, direction: -1 | 1) => {
    const targetIdx = idx + direction;
    if (targetIdx < 0 || targetIdx >= orderedStages.length) return;
    setErrorMsg(null);
    setSuccessMsg(null);
    const reordered = [...orderedStages];
    const [moved] = reordered.splice(idx, 1);
    reordered.splice(targetIdx, 0, moved);

    setBusy(true);
    try {
      const res = await fetch(`${apiBase}/api/v1/trips/${tripId}/stages/reorder`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${jwtToken}`,
        },
        body: JSON.stringify({
          stage_ids: reordered.map((s) => s.id),
          recalculate_dates: true,
        }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        const msg =
          body?.detail?.message ||
          (typeof body?.detail === "string" ? body.detail : null) ||
          "Impossible de réordonner les étapes.";
        setErrorMsg(msg);
        return;
      }
      const nextStages = Array.isArray(body) ? body : body?.stages;
      if (Array.isArray(nextStages)) {
        onStagesUpdated(nextStages);
      }
      setSuccessMsg("Ordre des étapes mis à jour.");
    } catch (err: any) {
      setErrorMsg(err?.message || "Erreur lors du réordonnancement.");
    } finally {
      setBusy(false);
    }
  };

  const handleDeleteStage = async (stageId: string) => {
    if (orderedStages.length <= 1) {
      setErrorMsg("Un voyage doit conserver au moins une étape.");
      return;
    }
    setErrorMsg(null);
    setSuccessMsg(null);
    setBusy(true);
    try {
      const res = await fetch(`${apiBase}/api/v1/trips/${tripId}/stages/${stageId}`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${jwtToken}`,
        },
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        const msg =
          body?.detail?.message ||
          (typeof body?.detail === "string" ? body.detail : null) ||
          "Impossible de supprimer cette étape.";
        setErrorMsg(msg);
        return;
      }
      const nextStages = Array.isArray(body) ? body : body?.stages;
      if (Array.isArray(nextStages)) {
        onStagesUpdated(nextStages);
      }
      setSuccessMsg("Étape supprimée et dates ajustées.");
    } catch (err: any) {
      setErrorMsg(err?.message || "Erreur lors de la suppression de l'étape.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className="card"
      data-testid="trip-stages-manager-card"
      style={{
        padding: "16px 18px",
        marginBottom: 18,
        border: "1px solid var(--border)",
        borderRadius: 16,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 10,
          marginBottom: 12,
        }}
      >
        <div>
          <span
            className="badge badge-teal"
            style={{ marginBottom: 4, display: "inline-block" }}
          >
            ÉTAPES DU VOYAGE MULTI-VILLES
          </span>
          <h3 style={{ fontSize: "1.05rem", margin: 0 }}>
            Destinations &amp; calendrier par étape ({orderedStages.length}{" "}
            {orderedStages.length > 1 ? "étapes" : "étape"})
          </h3>
        </div>
        {canWrite && (
          <button
            type="button"
            className="btn btn-primary"
            data-testid="trip-add-stage-open-btn"
            onClick={openAddStageForm}
            disabled={busy || orderedStages.length >= 10}
            style={{ padding: "8px 14px", fontSize: "0.84rem" }}
          >
            + Ajouter une étape
          </button>
        )}
      </div>

      {errorMsg && (
        <div
          className="alert alert-danger"
          data-testid="stage-manager-error"
          role="alert"
          style={{ marginBottom: 12 }}
        >
          {errorMsg}
        </div>
      )}
      {successMsg && (
        <div
          className="alert alert-success"
          data-testid="stage-manager-success"
          style={{ marginBottom: 12 }}
        >
          {successMsg}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {orderedStages.map((st, idx) => {
          const isEditing = editingStageId === st.id;
          return (
            <div
              key={st.id}
              data-testid={`trip-stage-item-${st.order_index}`}
              style={{
                padding: "12px 14px",
                borderRadius: 12,
                border: "1px solid var(--border)",
                background: "#F8FAFC",
              }}
            >
              {!isEditing ? (
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    flexWrap: "wrap",
                    gap: 10,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span
                      style={{
                        width: 28,
                        height: 28,
                        borderRadius: "50%",
                        background: "#0F766E",
                        color: "#FFFFFF",
                        display: "inline-flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontWeight: 800,
                        fontSize: "0.84rem",
                      }}
                    >
                      {st.order_index}
                    </span>
                    <div>
                      <strong style={{ fontSize: "0.95rem" }}>
                        {st.city_name}{" "}
                        <span
                          style={{
                            fontWeight: 500,
                            color: "var(--text-muted)",
                            fontSize: "0.84rem",
                          }}
                        >
                          ({st.country_name})
                        </span>
                      </strong>
                      <div style={{ fontSize: "0.82rem", color: "#334155", marginTop: 2 }}>
                        Du <strong>{st.arrival_date}</strong> au{" "}
                        <strong>{st.departure_date}</strong> · {st.nights} nuit
                        {st.nights > 1 ? "s" : ""} · Trajet :{" "}
                        <strong>{st.arrival_transport_mode}</strong>
                      </div>
                    </div>
                  </div>

                  {canWrite && (
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      <button
                        type="button"
                        className="btn btn-ghost"
                        data-testid={`trip-stage-up-${st.order_index}`}
                        disabled={busy || idx === 0}
                        onClick={() => void handleReorderStage(idx, -1)}
                        style={{ padding: "5px 9px", fontSize: "0.78rem" }}
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost"
                        data-testid={`trip-stage-down-${st.order_index}`}
                        disabled={busy || idx === orderedStages.length - 1}
                        onClick={() => void handleReorderStage(idx, 1)}
                        style={{ padding: "5px 9px", fontSize: "0.78rem" }}
                      >
                        ↓
                      </button>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        data-testid={`trip-stage-edit-btn-${st.order_index}`}
                        disabled={busy}
                        onClick={() => startEditingStage(st)}
                        style={{ padding: "5px 10px", fontSize: "0.78rem" }}
                      >
                        Modifier
                      </button>
                      {orderedStages.length > 1 && (
                        <button
                          type="button"
                          className="btn btn-ghost"
                          data-testid={`trip-stage-delete-btn-${st.order_index}`}
                          disabled={busy}
                          onClick={() => void handleDeleteStage(st.id)}
                          style={{
                            padding: "5px 10px",
                            fontSize: "0.78rem",
                            color: "#B91C1C",
                          }}
                        >
                          Supprimer
                        </button>
                      )}
                    </div>
                  )}
                </div>
              ) : (
                <div data-testid={`trip-stage-edit-form-${st.order_index}`}>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
                      gap: 10,
                      marginBottom: 10,
                    }}
                  >
                    <div>
                      <label style={{ fontSize: "0.76rem", fontWeight: 700 }}>
                        Destination
                      </label>
                      <select
                        className="input"
                        data-testid={`edit-stage-dest-select-${st.order_index}`}
                        value={editDestId}
                        onChange={(e) => {
                          const d = destinationsCatalog.find(
                            (item) => item.id === e.target.value
                          );
                          setEditDestId(e.target.value);
                          if (d) setEditCityName(d.city_name);
                        }}
                      >
                        <option value="">-- Ville personnalisée --</option>
                        {destinationsCatalog.map((d) => (
                          <option key={d.id} value={d.id}>
                            {d.city_name} ({d.country_name})
                          </option>
                        ))}
                      </select>
                      <input
                        type="text"
                        className="input"
                        data-testid={`edit-stage-city-input-${st.order_index}`}
                        value={editCityName}
                        onChange={(e) => {
                          setEditDestId("");
                          setEditCityName(e.target.value);
                        }}
                        style={{ marginTop: 4 }}
                      />
                    </div>
                    <div>
                      <label style={{ fontSize: "0.76rem", fontWeight: 700 }}>
                        Date d&apos;arrivée
                      </label>
                      <input
                        type="date"
                        className="input"
                        data-testid={`edit-stage-arrival-${st.order_index}`}
                        value={editArrivalDate}
                        onChange={(e) => setEditArrivalDate(e.target.value)}
                      />
                    </div>
                    <div>
                      <label style={{ fontSize: "0.76rem", fontWeight: 700 }}>
                        Date de départ
                      </label>
                      <input
                        type="date"
                        className="input"
                        data-testid={`edit-stage-departure-${st.order_index}`}
                        value={editDepartureDate}
                        onChange={(e) => setEditDepartureDate(e.target.value)}
                      />
                    </div>
                    <div>
                      <label style={{ fontSize: "0.76rem", fontWeight: 700 }}>
                        Transport
                      </label>
                      <select
                        className="input"
                        value={editTransportMode}
                        onChange={(e) => setEditTransportMode(e.target.value)}
                      >
                        {TRANSPORT_OPTIONS.map((opt) => (
                          <option key={opt.value} value={opt.value}>
                            {opt.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      type="button"
                      className="btn btn-primary"
                      data-testid={`edit-stage-save-btn-${st.order_index}`}
                      disabled={busy}
                      onClick={() => void handleSaveStageEdit(st.id)}
                      style={{ padding: "6px 12px", fontSize: "0.8rem" }}
                    >
                      Enregistrer l&apos;étape
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={() => setEditingStageId(null)}
                      style={{ padding: "6px 12px", fontSize: "0.8rem" }}
                    >
                      Annuler
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {showAddForm && (
        <form
          onSubmit={handleCreateStageSubmit}
          data-testid="trip-add-stage-form"
          style={{
            marginTop: 12,
            padding: 14,
            borderRadius: 12,
            border: "1px dashed var(--primary)",
            background: "#F0FDFA",
          }}
        >
          <strong style={{ display: "block", marginBottom: 8, fontSize: "0.9rem" }}>
            Nouvelle étape (étape {orderedStages.length + 1})
          </strong>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
              gap: 10,
              marginBottom: 10,
            }}
          >
            <div>
              <label style={{ fontSize: "0.76rem", fontWeight: 700 }}>Ville</label>
              <select
                className="input"
                data-testid="new-stage-dest-select"
                value={newDestId}
                onChange={(e) => {
                  const d = destinationsCatalog.find(
                    (item) => item.id === e.target.value
                  );
                  setNewDestId(e.target.value);
                  if (d) setNewCityName(d.city_name);
                }}
              >
                <option value="">-- Ville personnalisée --</option>
                {destinationsCatalog.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.city_name} ({d.country_name})
                  </option>
                ))}
              </select>
              <input
                type="text"
                className="input"
                data-testid="new-stage-city-input"
                placeholder="Nom de la ville"
                value={newCityName}
                onChange={(e) => {
                  setNewDestId("");
                  setNewCityName(e.target.value);
                }}
                style={{ marginTop: 4 }}
              />
            </div>
            <div>
              <label style={{ fontSize: "0.76rem", fontWeight: 700 }}>
                Date d&apos;arrivée
              </label>
              <input
                type="date"
                className="input"
                data-testid="new-stage-arrival-date"
                value={newArrivalDate}
                onChange={(e) => setNewArrivalDate(e.target.value)}
              />
            </div>
            <div>
              <label style={{ fontSize: "0.76rem", fontWeight: 700 }}>
                Date de départ
              </label>
              <input
                type="date"
                className="input"
                data-testid="new-stage-departure-date"
                value={newDepartureDate}
                onChange={(e) => setNewDepartureDate(e.target.value)}
              />
            </div>
            <div>
              <label style={{ fontSize: "0.76rem", fontWeight: 700 }}>
                Mode de transport
              </label>
              <select
                className="input"
                data-testid="new-stage-transport-mode"
                value={newTransportMode}
                onChange={(e) => setNewTransportMode(e.target.value)}
              >
                {TRANSPORT_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="submit"
              className="btn btn-primary"
              data-testid="new-stage-submit-btn"
              disabled={busy}
              style={{ padding: "7px 14px", fontSize: "0.82rem" }}
            >
              Valider la nouvelle étape
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setShowAddForm(false)}
              style={{ padding: "7px 12px", fontSize: "0.82rem" }}
            >
              Annuler
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

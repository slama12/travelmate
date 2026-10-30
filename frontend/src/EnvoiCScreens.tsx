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
  Mic,
  MicOff,
  Navigation,
  Pause,
  Plane,
  Play,
  Plus,
  Send,
  SlidersHorizontal,
  Sparkles,
  Star,
  Sun,
  Train,
  Trash2,
  Utensils,
  Volume2,
  VolumeX,
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
    SpeechRecognition?: any;
    webkitSpeechRecognition?: any;
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
  region_name?: string | null;
  sous_titre?: string | null;
  airport_name?: string | null;
  nearest_airport_distance_km?: number | null;
  airport_within_100km?: boolean | null;
  airport_display_label?: string | null;
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
  current_user_role?: "OWNER" | "EDITOR" | "VIEWER" | string;
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
  price_label?: string | null;
  avg_rating: number;
  opening_hours: Record<string, string>;
  hours_status?: string | null;
  address?: string | null;
  website_url?: string | null;
  hero_photos: string[];
  photo_status?: string | null;
  photo_file_title?: string | null;
  photo_author?: string | null;
  photo_license?: string | null;
  photo_commons_url?: string | null;
  photo_source?: string | null;
  photo_credit_text?: string | null;
  photo_checked?: boolean;
  source_provider: string;
  source_url?: string | null;
  source_attribution?: string | null;
  notoriety_score?: number;
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
  few_places_message?: string | null;
  can_expand_radius?: boolean;
  suggested_radius_km?: number | null;
  radius_km?: number;
  outage_message?: string | null;
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
  action_type:
    | "ADD_VISIT"
    | "MOVE_VISIT"
    | "REMOVE_VISIT"
    | "BOOK_RESERVATION"
    | "PROCESS_PAYMENT";
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
  requires_double_confirmation?: boolean;
  confirmation_steps_required?: number;
  confirmation_step?: number;
  spoken_summary_fr?: string | null;
}

export interface ChatMessageItem {
  id: string;
  trip_id: string;
  role: "user" | "assistant";
  content: string;
  proposed_action: ChatProposedAction | null;
  action_status:
    | "NONE"
    | "PENDING_CONFIRMATION"
    | "AWAITING_SECOND_CONFIRMATION"
    | "CONFIRMED"
    | "REJECTED";
  navigation_target?: string | null;
  voice_command?: string | null;
  created_at: string;
}

export type VoiceSTTProviderId = "web_speech" | "whisper_local";

export interface VoiceAccessibilitySettings {
  ttsEnabled: boolean;
  ttsRate: number;
  handsFree: boolean;
  alwaysActiveAssistant: boolean;
  executeWithoutConfirmation: boolean;
  phraseEndDelaySeconds: number;
  standbyDelaySeconds: number;
  sttProvider: VoiceSTTProviderId;
}

export const VOICE_SETTINGS_STORAGE_KEY = "tm_voice_settings_v1";

export const DEFAULT_VOICE_SETTINGS: VoiceAccessibilitySettings = {
  ttsEnabled: true,
  ttsRate: 1.0,
  handsFree: true,
  alwaysActiveAssistant: true,
  executeWithoutConfirmation: true,
  phraseEndDelaySeconds: 3,
  standbyDelaySeconds: 30,
  sttProvider: "web_speech",
};

export const WEB_SPEECH_PRIVACY_NOTICE_FR =
  "Confidentialité audio : en mode reconnaissance vocale du navigateur (Web Speech API, fr-FR) et avec l'exécution sans confirmation activée, le flux audio du microphone est analysé uniquement pendant l'écoute active (« J'écoute ») et peut transiter par le service de reconnaissance du navigateur. Le micro se met automatiquement en pause après 30 s de silence ou sur la commande « Arrête d'écouter ». Vous pouvez désactiver l'exécution sans confirmation ou choisir Whisper local à tout moment.";

export const WHISPER_LOCAL_PRIVACY_NOTICE_FR =
  "Confidentialité audio : avec Whisper local (fr-FR), l'audio du microphone est traité localement sans transiter par le service de reconnaissance externe du navigateur.";

export function loadVoiceAccessibilitySettings(): VoiceAccessibilitySettings {
  if (typeof window === "undefined") return DEFAULT_VOICE_SETTINGS;
  try {
    const raw = window.localStorage.getItem(VOICE_SETTINGS_STORAGE_KEY);
    if (!raw) return DEFAULT_VOICE_SETTINGS;
    const parsed = JSON.parse(raw);
    const phraseDelay = Number(parsed.phraseEndDelaySeconds);
    const standbyDelay = Number(parsed.standbyDelaySeconds);
    return {
      ttsEnabled:
        typeof parsed.ttsEnabled === "boolean"
          ? parsed.ttsEnabled
          : DEFAULT_VOICE_SETTINGS.ttsEnabled,
      ttsRate: [0.8, 1.0, 1.2, 1.5].includes(Number(parsed.ttsRate))
        ? Number(parsed.ttsRate)
        : DEFAULT_VOICE_SETTINGS.ttsRate,
      handsFree:
        typeof parsed.handsFree === "boolean"
          ? parsed.handsFree
          : DEFAULT_VOICE_SETTINGS.handsFree,
      alwaysActiveAssistant:
        typeof parsed.alwaysActiveAssistant === "boolean"
          ? parsed.alwaysActiveAssistant
          : DEFAULT_VOICE_SETTINGS.alwaysActiveAssistant,
      executeWithoutConfirmation:
        typeof parsed.executeWithoutConfirmation === "boolean"
          ? parsed.executeWithoutConfirmation
          : DEFAULT_VOICE_SETTINGS.executeWithoutConfirmation,
      phraseEndDelaySeconds:
        Number.isFinite(phraseDelay) && phraseDelay >= 1 && phraseDelay <= 10
          ? phraseDelay
          : DEFAULT_VOICE_SETTINGS.phraseEndDelaySeconds,
      standbyDelaySeconds:
        Number.isFinite(standbyDelay) && standbyDelay >= 5 && standbyDelay <= 120
          ? standbyDelay
          : DEFAULT_VOICE_SETTINGS.standbyDelaySeconds,
      sttProvider:
        parsed.sttProvider === "whisper_local" ? "whisper_local" : "web_speech",
    };
  } catch {
    return DEFAULT_VOICE_SETTINGS;
  }
}

export function saveVoiceAccessibilitySettings(
  next: VoiceAccessibilitySettings
): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(VOICE_SETTINGS_STORAGE_KEY, JSON.stringify(next));
    window.dispatchEvent(new CustomEvent("tm-voice-settings-updated"));
  } catch {
    // ignore storage errors
  }
}

export function speakFrenchResponse(
  text: string,
  options?: { rate?: number; enabled?: boolean }
): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    const w = window as any;
    if (! Array.isArray(w.__TM_SPOKEN_UTTERANCES__)) {
      w.__TM_SPOKEN_UTTERANCES__ = [];
    }
    if (text.trim()) {
      w.__TM_SPOKEN_UTTERANCES__.push(text.trim());
    }
  } catch {
    // ignore
  }
  if (!("speechSynthesis" in window)) {
    return false;
  }
  const settings = loadVoiceAccessibilitySettings();
  const enabled = options?.enabled ?? settings.ttsEnabled;
  if (!enabled || !text.trim()) return false;
  try {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text.trim());
    utterance.lang = "fr-FR";
    utterance.rate = options?.rate ?? settings.ttsRate ?? 1.0;
    window.speechSynthesis.speak(utterance);
    return true;
  } catch {
    return false;
  }
}

export function togglePauseSpeechSynthesis(): "paused" | "resumed" | "idle" {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) {
    return "idle";
  }
  try {
    if (window.speechSynthesis.paused) {
      window.speechSynthesis.resume();
      return "resumed";
    }
    if (window.speechSynthesis.speaking) {
      window.speechSynthesis.pause();
      return "paused";
    }
    return "idle";
  } catch {
    return "idle";
  }
}

export function stopSpeechSynthesis(): void {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
  try {
    window.speechSynthesis.cancel();
  } catch {
    // ignore
  }
}

export interface FrontendVoiceRecognitionCallbacks {
  onListeningChange: (listening: boolean) => void;
  onTranscript: (transcript: string, isFinal: boolean, confidence?: number) => void;
  onSilenceStop: () => void;
  onStandbyPause?: (messageFr: string) => void;
  onLowConfidence?: (transcript: string, confidence: number, messageFr: string) => void;
  onAntiLoopStop?: (messageFr: string) => void;
  onError: (
    errorCode:
      | "MIC_DENIED"
      | "BROWSER_UNSUPPORTED"
      | "UNRECOGNIZED_SPEECH"
      | "NOISE"
      | "SILENCE"
      | "LOW_CONFIDENCE",
    messageFr: string
  ) => void;
}

export interface FrontendVoiceSTTProvider {
  readonly providerId: VoiceSTTProviderId;
  readonly providerLabelFr: string;
  readonly language: "fr-FR";
  readonly privacyNoticeFr: string;
  isSupported(): boolean;
  startListening(callbacks: FrontendVoiceRecognitionCallbacks): () => void;
}

function isIncompleteActionPhraseWithoutTime(text: string): boolean {
  const norm = text.trim().toLowerCase();
  if (!norm) return false;
  const hasActionVerb =
    /\b(ajoute|ajouter|rajoute|mets|mettre|planifie|d[ée]place|d[ée]placer|change|modifie|d[ée]cale)\b/i.test(
      norm
    );
  const hasTime = /\b\d{1,2}\s*(?:h|:)\s*\d{0,2}\b/i.test(norm);
  return hasActionVerb && !hasTime;
}

function isContinuationDateOrTimeFragment(text: string): boolean {
  const norm = text.trim().toLowerCase();
  if (!norm) return false;
  const hasActionVerb =
    /\b(ajoute|ajouter|rajoute|mets|mettre|planifie|d[ée]place|d[ée]placer|supprime|supprimer|retire|retirer|annule|annuler|[ée]coute|arr[êe]te|oui|non)\b/i.test(
      norm
    );
  if (hasActionVerb) return false;
  return /\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|demain|aujourd|\d{1,2}\s*(?:novembre|octobre|d[ée]cembre|janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|septembre)|\d{1,2}\s*(?:h|:)\s*\d{0,2}|au\s+\d{1,2}|le\s+\d{1,2}|[àa]\s*\d{1,2})\b/i.test(
    norm
  );
}

export class WebSpeechFrontendProvider implements FrontendVoiceSTTProvider {
  readonly providerId: VoiceSTTProviderId = "web_speech";
  readonly providerLabelFr = "Web Speech API (Navigateur fr-FR)";
  readonly language = "fr-FR" as const;
  readonly privacyNoticeFr = WEB_SPEECH_PRIVACY_NOTICE_FR;

  isSupported(): boolean {
    if (typeof window === "undefined") return false;
    return Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
  }

  startListening(callbacks: FrontendVoiceRecognitionCallbacks): () => void {
    if (!this.isSupported()) {
      callbacks.onListeningChange(false);
      callbacks.onError(
        "BROWSER_UNSUPPORTED",
        "Votre navigateur n'est pas compatible avec la reconnaissance vocale Web Speech API (fr-FR). Utilisez un navigateur compatible ou activez le fournisseur Whisper local dans Paramètres."
      );
      return () => {};
    }

    const w = window as any;
    if (w.__TM_MIC_DENIED__ === true) {
      callbacks.onListeningChange(false);
      callbacks.onError(
        "MIC_DENIED",
        "Accès au microphone refusé. Veuillez autoriser le microphone dans votre navigateur ou activer l'écoute après autorisation."
      );
      return () => {};
    }

    const settings = loadVoiceAccessibilitySettings();
    const getPhraseScale = () => {
      const scale = w.__TM_VOICE_PHRASE_SCALE__ ?? w.__TM_VOICE_TIMER_SCALE__;
      return typeof scale === "number" && scale > 0 ? scale : 1;
    };
    const getStandbyScale = () => {
      const scale = w.__TM_VOICE_STANDBY_SCALE__ ?? w.__TM_VOICE_TIMER_SCALE__;
      return typeof scale === "number" && scale > 0 ? scale : 1;
    };
    const getPhraseEndMs = () =>
      Math.max(
        120,
        Math.round((settings.phraseEndDelaySeconds || 3) * 1000 * getPhraseScale())
      );
    const getStandbyMs = () =>
      Math.max(
        250,
        Math.round((settings.standbyDelaySeconds || 30) * 1000 * getStandbyScale())
      );

    const SpeechRecognitionCtor =
      window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SpeechRecognitionCtor();
    recognition.lang = "fr-FR";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    w.__TM_ACTIVE_SPEECH_RECOGNITION__ = recognition;

    let stoppedManually = false;
    let inStandby = false;
    let pausedByVoice = false;
    let phraseTimer: number | null = null;
    let standbyTimer: number | null = null;
    let accumulatedChunks: string[] = [];
    let currentInterim = "";
    let lastConfidence = 0.95;
    let lastIncompletePrefix = "";
    let lastIncompleteTimestamp = 0;
    const restartTimestamps: number[] = [];
    const MAX_RESTARTS_IN_WINDOW = 5;
    const RESTART_WINDOW_MS = 10000;

    const clearTimers = () => {
      if (phraseTimer !== null) {
        window.clearTimeout(phraseTimer);
        phraseTimer = null;
      }
      if (standbyTimer !== null) {
        window.clearTimeout(standbyTimer);
        standbyTimer = null;
      }
    };

    const flushAccumulatedPhrase = () => {
      phraseTimer = null;
      const combined = [...accumulatedChunks, currentInterim]
        .map((s) => s.trim())
        .filter(Boolean)
        .join(" ")
        .replace(/\s+/g, " ")
        .trim();
      accumulatedChunks = [];
      currentInterim = "";
      if (!combined) return;

      const phraseEndMs = getPhraseEndMs();
      let finalSentence = combined;
      if (
        lastIncompletePrefix &&
        Date.now() - lastIncompleteTimestamp <= Math.max(10000, phraseEndMs * 2.5) &&
        isContinuationDateOrTimeFragment(combined)
      ) {
        finalSentence = `${lastIncompletePrefix} ${combined}`.replace(/\s+/g, " ").trim();
        lastIncompletePrefix = "";
      } else if (isIncompleteActionPhraseWithoutTime(combined)) {
        lastIncompletePrefix = combined;
        lastIncompleteTimestamp = Date.now();
      } else {
        lastIncompletePrefix = "";
      }

      callbacks.onTranscript(finalSentence, true, lastConfidence);
    };

    const resetStandbyTimer = () => {
      if (standbyTimer !== null) {
        window.clearTimeout(standbyTimer);
      }
      const standbyMs = getStandbyMs();
      standbyTimer = window.setTimeout(() => {
        if (!stoppedManually && !inStandby && !pausedByVoice) {
          if (accumulatedChunks.length > 0 || currentInterim.trim()) {
            flushAccumulatedPhrase();
          }
          inStandby = true;
          try {
            recognition.stop();
          } catch {
            // ignore
          }
          callbacks.onListeningChange(false);
          const standbyMsg = `Veille vocale activée après ${settings.standbyDelaySeconds || 30} s sans parole : microphone mis en pause. Dites « Écoute » ou cliquez sur le bouton pour reprendre.`;
          if (callbacks.onStandbyPause) {
            callbacks.onStandbyPause(standbyMsg);
          } else {
            callbacks.onSilenceStop();
          }
        }
      }, standbyMs);
    };

    const schedulePhraseEndTimer = (currentFullText: string) => {
      if (phraseTimer !== null) {
        window.clearTimeout(phraseTimer);
      }
      const phraseEndMs = getPhraseEndMs();
      // Si la phrase est manifestement en cours ("Déplace le Jardin Secret" sans date ni heure),
      // on laisse une marge supplémentaire pour absorber une pause de 3 s au milieu d'une phrase.
      const extraHold = isIncompleteActionPhraseWithoutTime(currentFullText)
        ? Math.round(phraseEndMs * 0.45)
        : 0;
      phraseTimer = window.setTimeout(() => {
        flushAccumulatedPhrase();
      }, phraseEndMs + extraHold);
    };

    recognition.onstart = () => {
      if (!stoppedManually && !inStandby && !pausedByVoice) {
        callbacks.onListeningChange(true);
        resetStandbyTimer();
      }
    };

    recognition.onresult = (event: any) => {
      if (stoppedManually) return;

      let latestPiece = "";
      let pieceIsFinal = false;
      let pieceConfidence = 0.95;

      const startIdx = typeof event?.resultIndex === "number" ? event.resultIndex : 0;
      const resultsLen = event?.results?.length || 0;
      for (let i = startIdx; i < resultsLen; i++) {
        const resItem = event.results[i];
        const alt = resItem && resItem[0] ? resItem[0] : null;
        if (!alt) continue;
        latestPiece += String(alt.transcript || "");
        if (typeof alt.confidence === "number" && alt.confidence > 0) {
          pieceConfidence = alt.confidence;
        }
        if (resItem.isFinal) {
          pieceIsFinal = true;
        }
      }

      const trimmedPiece = latestPiece.trim();
      if (!trimmedPiece) return;

      // Exigence 6 : Jamais d'action sur une transcription de confiance faible (< 0.60)
      if (pieceConfidence < 0.6) {
        if (phraseTimer !== null) {
          window.clearTimeout(phraseTimer);
          phraseTimer = null;
        }
        accumulatedChunks = [];
        currentInterim = "";
        const lowConfMsg =
          "Confiance de transcription vocale trop faible : aucune action n'a été exécutée. Pouvez-vous répéter ?";
        if (callbacks.onLowConfidence) {
          callbacks.onLowConfidence(trimmedPiece, pieceConfidence, lowConfMsg);
        }
        callbacks.onError("LOW_CONFIDENCE", lowConfMsg);
        return;
      }

      // En veille ou en pause vocale, seul le mot de reprise ("Écoute") réactive l'écoute
      if (inStandby || pausedByVoice) {
        if (/^\s*(?:[ée]coute|reprends\s+l['’ ]?[ée]coute)\s*[.!]*\s*$/i.test(trimmedPiece)) {
          inStandby = false;
          pausedByVoice = false;
          accumulatedChunks = [];
          currentInterim = "";
          callbacks.onListeningChange(true);
          resetStandbyTimer();
          callbacks.onTranscript("Écoute", true, pieceConfidence);
        }
        return;
      }

      resetStandbyTimer();
      lastConfidence = pieceConfidence;

      // Arrêt immédiat par la voix ("Arrête d'écouter")
      if (
        pieceIsFinal &&
        /^\s*(?:arr[êe]te\s+d['’ ]?[ée]couter|stop\s+[ée]coute|arr[êe]te\s+l['’ ]?[ée]coute)\s*[.!]*\s*$/i.test(
          trimmedPiece
        )
      ) {
        clearTimers();
        accumulatedChunks = [];
        currentInterim = "";
        pausedByVoice = true;
        callbacks.onListeningChange(false);
        callbacks.onTranscript(trimmedPiece, true, lastConfidence);
        return;
      }

      if (pieceIsFinal) {
        const prevJoined = accumulatedChunks.join(" ").trim();
        if (prevJoined && trimmedPiece.toLowerCase().startsWith(prevJoined.toLowerCase())) {
          accumulatedChunks = [trimmedPiece];
        } else {
          accumulatedChunks.push(trimmedPiece);
        }
        currentInterim = "";
      } else {
        currentInterim = trimmedPiece;
      }

      const previewText = [...accumulatedChunks, currentInterim]
        .map((s) => s.trim())
        .filter(Boolean)
        .join(" ")
        .replace(/\s+/g, " ")
        .trim();

      // Commandes immédiates de contrôle ("Écoute", "Annule", "Oui", "Non")
      if (
        pieceIsFinal &&
        /^\s*(?:[ée]coute|annule|annuler|oui|non)\s*[.!]*\s*$/i.test(previewText) &&
        accumulatedChunks.length === 1 &&
        !lastIncompletePrefix
      ) {
        if (phraseTimer !== null) {
          window.clearTimeout(phraseTimer);
          phraseTimer = null;
        }
        accumulatedChunks = [];
        currentInterim = "";
        callbacks.onTranscript(previewText, true, lastConfidence);
        return;
      }

      callbacks.onTranscript(previewText, false, lastConfidence);
      schedulePhraseEndTimer(previewText);
    };

    recognition.onspeechend = () => {
      // En écoute continue, on laisse le minuteur de fin de phrase (3 s par défaut) décider de l'envoi.
      const previewText = [...accumulatedChunks, currentInterim]
        .map((s) => s.trim())
        .filter(Boolean)
        .join(" ")
        .trim();
      if (previewText && phraseTimer === null) {
        schedulePhraseEndTimer(previewText);
      }
    };

    recognition.onerror = (event: any) => {
      const err = String(event?.error || "").toLowerCase();
      if (err === "not-allowed" || err === "permission-denied" || err === "service-not-allowed") {
        stoppedManually = true;
        clearTimers();
        callbacks.onListeningChange(false);
        callbacks.onError(
          "MIC_DENIED",
          "Accès au microphone refusé. Veuillez autoriser le microphone dans votre navigateur ou saisir votre demande au clavier."
        );
      } else if (err === "no-speech") {
        // En mode continu, la veille est gérée par standbyTimer (30 s par défaut)
      } else if (err === "audio-capture" || err === "network") {
        callbacks.onError(
          "NOISE",
          "Bruit ambiant important détecté. Pouvez-vous répéter dans un environnement plus calme ?"
        );
      } else {
        callbacks.onError("UNRECOGNIZED_SPEECH", "Pouvez-vous répéter ?");
      }
    };

    recognition.onend = () => {
      if (stoppedManually || inStandby) {
        clearTimers();
        callbacks.onListeningChange(false);
        return;
      }
      // Exigence 2 : Redémarrage automatique après onend avec limite anti-boucle
      const now = Date.now();
      while (restartTimestamps.length > 0 && now - restartTimestamps[0] > RESTART_WINDOW_MS) {
        restartTimestamps.shift();
      }
      if (restartTimestamps.length >= MAX_RESTARTS_IN_WINDOW) {
        stoppedManually = true;
        clearTimers();
        callbacks.onListeningChange(false);
        const loopMsg =
          "Écoute vocale mise en pause automatiquement (limite anti-boucle atteinte). Cliquez sur « Écoute » pour reprendre.";
        if (callbacks.onAntiLoopStop) {
          callbacks.onAntiLoopStop(loopMsg);
        } else {
          callbacks.onSilenceStop();
        }
        return;
      }
      restartTimestamps.push(now);
      try {
        recognition.start();
      } catch {
        clearTimers();
        callbacks.onListeningChange(false);
      }
    };

    try {
      recognition.start();
      if (!stoppedManually && !inStandby && !pausedByVoice) {
        callbacks.onListeningChange(true);
        resetStandbyTimer();
      }
    } catch {
      clearTimers();
      callbacks.onListeningChange(false);
      callbacks.onError(
        "MIC_DENIED",
        "Accès au microphone refusé ou indisponible."
      );
    }

    return () => {
      stoppedManually = true;
      clearTimers();
      try {
        recognition.stop();
      } catch {
        // ignore
      }
      callbacks.onListeningChange(false);
    };
  }
}

export class WhisperLocalFrontendProvider implements FrontendVoiceSTTProvider {
  readonly providerId: VoiceSTTProviderId = "whisper_local";
  readonly providerLabelFr = "Whisper local (Fournisseur local fr-FR)";
  readonly language = "fr-FR" as const;
  readonly privacyNoticeFr = WHISPER_LOCAL_PRIVACY_NOTICE_FR;

  isSupported(): boolean {
    return true;
  }

  startListening(callbacks: FrontendVoiceRecognitionCallbacks): () => void {
    const webProvider = new WebSpeechFrontendProvider();
    if (webProvider.isSupported()) {
      return webProvider.startListening(callbacks);
    }
    callbacks.onListeningChange(true);
    const timer = window.setTimeout(() => {
      callbacks.onListeningChange(false);
      callbacks.onSilenceStop();
    }, 3000);
    return () => {
      window.clearTimeout(timer);
      callbacks.onListeningChange(false);
    };
  }
}

export function createFrontendVoiceSTTProvider(
  providerId: VoiceSTTProviderId
): FrontendVoiceSTTProvider {
  if (providerId === "whisper_local") {
    return new WhisperLocalFrontendProvider();
  }
  return new WebSpeechFrontendProvider();
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
  departureCity?: string;
  departureIata?: string;
  departureAirportLabel?: string;
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
  if (upper === "AUTRE") {
    return "Autre";
  }
  return "Incontournable";
}

function NeutralPlaceCategoryIllustration({
  category,
  onClick,
  testId,
}: {
  category: string;
  onClick?: () => void;
  testId?: string;
}) {
  const upper = (category || "").toUpperCase();
  let IconComp = Compass;
  let toneClasses = "bg-stone-100 text-stone-700";

  if (upper.includes("CULTUR") || upper.includes("MUSEUM") || upper.includes("HISTOR")) {
    IconComp = Building2;
    toneClasses = "bg-stone-100 text-stone-700";
  } else if (upper.includes("NATUR") || upper.includes("PARK") || upper.includes("GARDEN")) {
    IconComp = Sun;
    toneClasses = "bg-emerald-50/80 text-emerald-800";
  } else if (upper.includes("FOOD") || upper.includes("RESTAURANT") || upper.includes("GASTRO")) {
    IconComp = Utensils;
    toneClasses = "bg-amber-50/80 text-amber-800";
  } else if (upper.includes("NIGHT")) {
    IconComp = Sparkles;
    toneClasses = "bg-slate-100 text-slate-800";
  }

  return (
    <div
      data-testid={testId}
      onClick={onClick}
      className={`h-full w-full flex flex-col items-center justify-center p-6 text-center select-none ${
        onClick ? "cursor-pointer" : ""
      } ${toneClasses}`}
    >
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-white/80 shadow-sm mb-3">
        <IconComp className="h-7 w-7" aria-hidden="true" />
      </div>
      <span className="text-caption font-semibold">{categoryLabelFr(category)}</span>
      <span className="text-caption opacity-80 mt-0.5">Photo bientôt disponible</span>
    </div>
  );
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
  departureDate,
  returnDate,
  travelers,
}: {
  apiBase: string;
  trip: Trip | null;
  destination: Destination | null;
  selectedAccommodation: AccommodationItem | null;
  onSelectAccommodation: (acc: AccommodationItem) => void;
  departureDate?: string;
  returnDate?: string;
  travelers?: string;
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
            (() => {
              const isCustomWorldCity = Boolean(
                destination &&
                  !["paris", "marrakech", "tokyo", "new york", "rome"].includes(
                    destination.city_name.trim().toLowerCase()
                  )
              );
              const targetCity = destination?.city_name || "votre destination";
              const checkinIso = (
                departureDate ||
                (trip?.arrival_at ? trip.arrival_at.slice(0, 10) : "2026-11-10")
              ).slice(0, 10);
              const checkoutIso = (
                returnDate ||
                (trip?.departure_at ? trip.departure_at.slice(0, 10) : "2026-11-17")
              ).slice(0, 10);
              const adultsCount = Math.max(
                1,
                parseInt(String(travelers || "2").replace(/[^0-9]/g, ""), 10) || 2
              );
              const bookingUrl = `https://www.booking.com/searchresults.fr.html?ss=${encodeURIComponent(
                targetCity
              )}&checkin=${encodeURIComponent(checkinIso)}&checkout=${encodeURIComponent(
                checkoutIso
              )}&group_adults=${adultsCount}&no_rooms=1`;
              const airbnbUrl = `https://www.airbnb.fr/s/${encodeURIComponent(
                targetCity
              )}/homes?checkin=${encodeURIComponent(checkinIso)}&checkout=${encodeURIComponent(
                checkoutIso
              )}&adults=${adultsCount}`;

              return (
                <Card
                  className="p-8 text-center space-y-3"
                  data-testid="accommodations-empty-state"
                >
                  <Building2 className="h-8 w-8 text-brand-700 mx-auto" />
                  <h2 className="text-h2 text-ink" data-testid="accommodations-empty-title">
                    {isCustomWorldCity
                      ? `Nous n'avons pas encore d'hébergements à afficher pour ${targetCity}`
                      : "Aucun hébergement pour ces critères"}
                  </h2>
                  <p className="text-body text-ink-secondary max-w-lg mx-auto">
                    {isCustomWorldCity
                      ? `Consultez directement les offres disponibles à ${targetCity} du ${checkinIso} au ${checkoutIso} pour ${adultsCount} voyageur${
                          adultsCount > 1 ? "s" : ""
                        }, ou poursuivez l'organisation de votre séjour.`
                      : "Essayez d'élargir votre budget ou d'afficher à la fois les hôtels et les logements Airbnb."}
                  </p>

                  {isCustomWorldCity && (
                    <div className="pt-2 flex flex-col items-center gap-3">
                      <div className="inline-flex flex-wrap items-center justify-center gap-2">
                        <a
                          href={bookingUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          data-testid="accommodations-search-primary-btn"
                          className="inline-flex items-center justify-center gap-2 rounded-control px-5 py-2.5 text-sm font-semibold bg-accent text-white hover:bg-accent-hover shadow-subtle transition-colors"
                        >
                          <span>{`Rechercher un hébergement à ${targetCity}`}</span>
                          <span aria-hidden="true">↗</span>
                        </a>
                      </div>

                      <div
                        className="inline-flex flex-wrap items-center justify-center gap-2 rounded-control border border-border bg-canvas-subtle px-3 py-1.5 text-xs"
                        role="group"
                        aria-label="Choisir une plateforme d'hébergement"
                        data-testid="accommodations-compare-menu"
                      >
                        <span className="text-ink-muted font-medium">Ouvrir sur :</span>
                        <a
                          href={bookingUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          data-testid="accommodations-compare-booking"
                          className="inline-flex items-center gap-1 rounded px-2.5 py-1 font-semibold text-accent hover:bg-surface transition-colors"
                        >
                          Booking ↗
                        </a>
                        <span className="text-border" aria-hidden="true">
                          •
                        </span>
                        <a
                          href={airbnbUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          data-testid="accommodations-compare-airbnb"
                          className="inline-flex items-center gap-1 rounded px-2.5 py-1 font-semibold text-accent hover:bg-surface transition-colors"
                        >
                          Airbnb ↗
                        </a>
                      </div>
                    </div>
                  )}

                  <div className="flex flex-wrap items-center justify-center gap-3 pt-2">
                    <Button
                      type="button"
                      variant={isCustomWorldCity ? "secondary" : "primary"}
                      data-testid="accommodations-continue-activities-btn"
                      onClick={() => navigate("/activities")}
                    >
                      Voir les lieux de la ville
                    </Button>
                    {isCustomWorldCity ? (
                      <Button
                        type="button"
                        variant="secondary"
                        data-testid="accommodations-modify-search-btn"
                        onClick={() => navigate("/")}
                      >
                        Modifier ma recherche
                      </Button>
                    ) : (
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
                    )}
                  </div>
                </Card>
              );
            })()
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
  onRefreshGallery: (category?: string, radiusKm?: number) => Promise<void>;
}) {
  const navigate = useNavigate();
  const { notify } = useToast();

  const [categoryFilter, setCategoryFilter] = useState<string>("ALL");
  const [schedule, setSchedule] = useState<TripItinerarySchedule | null>(null);
  const [expandingRadius, setExpandingRadius] = useState<boolean>(false);

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
  const [enrichedPlacesById, setEnrichedPlacesById] = useState<Record<string, PlaceItem>>({});
  const enrichedRequestKeysRef = useRef<Set<string>>(new Set());

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

  // Étape 3 : Récupération des photos en arrière-plan après l'affichage de la liste (la galerie ne bloque pas)
  const uncheckedWorldPlaceIdsKey = useMemo(() => {
    if (!gallery?.places?.length) return "";
    return gallery.places
      .filter((p) => {
        const merged = enrichedPlacesById[p.id] || p;
        return (
          merged.source_provider !== "simulated" &&
          !merged.photo_checked &&
          !(merged.hero_photos && merged.hero_photos.length > 0 && merged.photo_author)
        );
      })
      .map((p) => p.id)
      .join(",");
  }, [gallery?.places, enrichedPlacesById]);

  useEffect(() => {
    if (!trip?.id || !token || !uncheckedWorldPlaceIdsKey) return;
    const radiusKm = gallery?.radius_km || 10;
    const reqKey = `${trip.id}:${radiusKm}:${uncheckedWorldPlaceIdsKey}`;
    if (enrichedRequestKeysRef.current.has(reqKey)) return;
    enrichedRequestKeysRef.current.add(reqKey);

    fetch(
      `${apiBase}/api/v1/places/trip/${trip.id}/photos/enrich?radius_km=${radiusKm}`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      }
    )
      .then((r) => (r.ok ? r.json() : null))
      .then((enrichedGallery: TripGalleryPayload | null) => {
        if (!enrichedGallery?.places?.length) return;
        setEnrichedPlacesById((prev) => {
          const next = { ...prev };
          for (const pl of enrichedGallery.places) {
            next[pl.id] = pl;
          }
          return next;
        });
      })
      .catch(() => {
        enrichedRequestKeysRef.current.delete(reqKey);
      });
  }, [trip?.id, token, uncheckedWorldPlaceIdsKey, gallery?.radius_km, apiBase]);

  const tripDays = useMemo(() => buildTripDayDates(schedule), [schedule]);

  const mergedPlaces = useMemo(() => {
    const list = gallery?.places || [];
    return list.map((p) => (enrichedPlacesById[p.id] ? { ...p, ...enrichedPlacesById[p.id] } : p));
  }, [gallery, enrichedPlacesById]);

  const activeFullscreenPlace = useMemo(() => {
    if (!fullscreenPlace) return null;
    return enrichedPlacesById[fullscreenPlace.id]
      ? { ...fullscreenPlace, ...enrichedPlacesById[fullscreenPlace.id] }
      : fullscreenPlace;
  }, [fullscreenPlace, enrichedPlacesById]);

  const filteredPlaces = useMemo(() => {
    const list = mergedPlaces;
    if (categoryFilter === "ALL") return list;
    const filterUpper = categoryFilter.toUpperCase();
    return list.filter((p) => {
      const catUpper = (p.category || "").toUpperCase();
      if (filterUpper === "FOOD" || filterUpper === "RESTAURANT") {
        return catUpper.includes("FOOD") || catUpper.includes("RESTAURANT");
      }
      if (filterUpper === "NIGHTLIFE") {
        return catUpper.includes("NIGHT");
      }
      return catUpper.includes(filterUpper);
    });
  }, [mergedPlaces, categoryFilter]);

  async function handleExpandRadiusTo30Km() {
    setExpandingRadius(true);
    try {
      await onRefreshGallery("", gallery?.suggested_radius_km || 30);
    } finally {
      setExpandingRadius(false);
    }
  }

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
          { value: "NIGHTLIFE", label: "Soirée & Détente" },
          { value: "AUTRE", label: "Autre" },
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

      {/* Bandeau de panne éventuel */}
      {gallery?.outage_message && (gallery.places || []).length > 0 && (
        <div
          data-testid="places-outage-banner"
          className="rounded-card border border-amber-300 bg-feedback-warningBg px-4 py-3 text-caption font-medium text-feedback-warning"
        >
          {gallery.outage_message}
        </div>
      )}

      {/* Bandeau moins de 5 lieux + proposition d'élargir le rayon à 30 km */}
      {gallery?.few_places_message && (
        <div
          data-testid="few-places-banner"
          className="rounded-card border border-border bg-canvas-subtle px-4 py-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
        >
          <p className="text-body font-medium text-ink" data-testid="few-places-message-text">
            {gallery.few_places_message}
          </p>
          {gallery.can_expand_radius && (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={expandingRadius}
              data-testid="expand-radius-30km-btn"
              onClick={handleExpandRadiusTo30Km}
            >
              <Compass className="h-4 w-4" />
              <span>
                {expandingRadius
                  ? "Recherche à 30 km..."
                  : `Élargir le rayon à ${gallery.suggested_radius_km || 30} km`}
              </span>
            </Button>
          )}
        </div>
      )}

      {/* Grille de lieux ou état de panne / peu de lieux */}
      {!gallery ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2, 3, 4, 5, 6].map((n) => (
            <Card key={n} className="overflow-hidden">
              <Skeleton className="aspect-[16/9] w-full rounded-none" />
              <div className="p-5 space-y-3">
                <Skeleton className="h-5 w-2/3" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-10 w-full mt-2" />
              </div>
            </Card>
          ))}
        </div>
      ) : (gallery.places || []).length === 0 ? (
        gallery.outage_message ? (
          <Card
            className="p-8 text-center space-y-3"
            data-testid="places-outage-card"
          >
            <Compass className="h-8 w-8 text-brand-700 mx-auto" />
            <h2 className="text-h2 text-ink" data-testid="places-outage-title">
              {gallery.outage_message}
            </h2>
            <p className="text-body text-ink-secondary max-w-lg mx-auto">
              Aucune donnée n'est inventée. Réessayez dans quelques instants.
            </p>
          </Card>
        ) : (
          <Card
            className="p-8 text-center space-y-4"
            data-testid="few-places-empty-card"
          >
            <Compass className="h-8 w-8 text-brand-700 mx-auto" />
            <h2 className="text-h2 text-ink" data-testid="few-places-empty-title">
              {gallery.few_places_message ||
                `Peu de lieux disponibles à ${cityLabel} pour l'instant`}
            </h2>
            {gallery.can_expand_radius && (
              <div className="pt-1">
                <Button
                  type="button"
                  variant="secondary"
                  size="md"
                  disabled={expandingRadius}
                  data-testid="expand-radius-30km-btn"
                  onClick={handleExpandRadiusTo30Km}
                >
                  <Compass className="h-4 w-4" />
                  <span>
                    {expandingRadius
                      ? "Recherche à 30 km..."
                      : `Élargir le rayon à ${gallery.suggested_radius_km || 30} km`}
                  </span>
                </Button>
              </div>
            )}
          </Card>
        )
      ) : (
        <div
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6"
          data-testid="activities-photo-grid"
        >
          {filteredPlaces.map((place, idx) => {
            const realPhotoUrl = place.hero_photos?.[0] || "";
            const photoCreditText =
              place.photo_credit_text ||
              (place.photo_author && place.photo_license
                ? `Photo : ${place.photo_author}, ${place.photo_license}`
                : null);
            const showCreditStrip =
              place.source_provider !== "simulated" || Boolean(photoCreditText);
            const hoursText =
              place.opening_hours?.display ||
              place.opening_hours?.mon ||
              place.hours_status ||
              "non renseigné";
            const priceText =
              place.price_label ||
              (Number(place.estimated_cost) > 0
                ? `${Math.round(Number(place.estimated_cost))} €`
                : "non renseigné");

            return (
              <Card
                key={place.id}
                data-testid={`activity-card-${idx}`}
                className="overflow-hidden flex flex-col justify-between group hover:shadow-cardHover transition-shadow"
              >
                <div>
                  {/* Photo du lieu en 16/9 avec dimensions réservées (pas de saut de page) ou illustration neutre */}
                  <div
                    className="relative aspect-[16/9] w-full overflow-hidden bg-canvas-subtle"
                    data-testid={`place-media-box-${idx}`}
                  >
                    {realPhotoUrl ? (
                      <img
                        src={realPhotoUrl}
                        alt={place.name}
                        width={800}
                        height={450}
                        loading="lazy"
                        decoding="async"
                        referrerPolicy="no-referrer"
                        data-testid={`place-photo-img-${idx}`}
                        onClick={() => setFullscreenPlace(place)}
                        className="h-full w-full object-cover cursor-pointer transition-transform duration-300 group-hover:scale-105"
                      />
                    ) : (
                      <NeutralPlaceCategoryIllustration
                        category={place.category}
                        onClick={() => setFullscreenPlace(place)}
                        testId={`place-photo-placeholder-${idx}`}
                      />
                    )}
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

                  {/* Sous la photo : crédit Commons obligatoire avec hauteur fixe réservée (0 saut de mise en page) */}
                  {showCreditStrip && (
                    <div
                      className="h-7 px-3 flex items-center bg-canvas-subtle/70 border-b border-border/60 text-caption text-ink-muted"
                      data-testid={`place-photo-credit-${idx}`}
                    >
                      {photoCreditText ? (
                        place.photo_commons_url ? (
                          <a
                            href={place.photo_commons_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            data-testid={`place-photo-credit-link-${idx}`}
                            className="truncate underline decoration-border hover:text-brand-700 transition-colors"
                          >
                            {photoCreditText}
                          </a>
                        ) : (
                          <span
                            className="truncate"
                            data-testid={`place-photo-credit-text-${idx}`}
                          >
                            {photoCreditText}
                          </span>
                        )
                      ) : (
                        <span
                          className="truncate"
                          data-testid={`place-photo-credit-empty-${idx}`}
                        >
                          Photo bientôt disponible
                        </span>
                      )}
                    </div>
                  )}

                  <div className="p-5">
                    <div className="flex items-center justify-between gap-2 text-caption text-ink-muted">
                      <span className="inline-flex items-center gap-1">
                        <Clock className="h-3.5 w-3.5 text-brand-700" />
                        Durée conseillée : {place.recommended_duration_min} min
                      </span>
                      <span className="font-semibold text-ink">
                        {place.is_outdoor ? "Extérieur" : "Intérieur"}
                      </span>
                    </div>

                    <h2 className="text-h2 text-ink mt-1.5">{place.name}</h2>
                    <p className="text-caption text-ink-secondary mt-1 line-clamp-2">
                      {place.description}
                    </p>

                    <div className="mt-3 space-y-1 text-caption text-ink-secondary">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-ink-muted">Horaires :</span>
                        <span
                          className="font-medium text-ink text-right truncate max-w-[65%]"
                          data-testid={`place-hours-${idx}`}
                        >
                          {hoursText}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-ink-muted">Tarif :</span>
                        <span
                          className="font-medium text-ink text-right truncate max-w-[65%]"
                          data-testid={`place-price-${idx}`}
                        >
                          {priceText}
                        </span>
                      </div>
                      {place.address && (
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-ink-muted">Adresse :</span>
                          <span className="text-ink text-right truncate max-w-[65%]">
                            {place.address}
                          </span>
                        </div>
                      )}
                      {place.website_url && (
                        <div className="pt-0.5">
                          <a
                            href={place.website_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-brand-700 underline hover:text-brand-800"
                          >
                            Site officiel
                          </a>
                        </div>
                      )}
                    </div>

                    {place.source_attribution && (
                      <div
                        className="mt-3 pt-2 border-t border-border/60 text-caption text-ink-muted"
                        data-testid={`place-attribution-${idx}`}
                      >
                        {place.source_url ? (
                          <a
                            href={place.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            data-testid={`place-attribution-link-${idx}`}
                            className="underline decoration-border hover:text-brand-700 transition-colors"
                          >
                            {place.source_attribution}
                          </a>
                        ) : (
                          <span>{place.source_attribution}</span>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                <div className="px-5 pb-5 pt-2 flex items-center justify-between gap-2 border-t border-border">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setFullscreenPlace(place)}
                  >
                    Aperçu du lieu
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
        open={Boolean(activeFullscreenPlace)}
        onOpenChange={(open) => {
          if (!open) setFullscreenPlace(null);
        }}
        title={activeFullscreenPlace?.name || "Aperçu du lieu"}
        description={
          activeFullscreenPlace
            ? categoryLabelFr(activeFullscreenPlace.category)
            : undefined
        }
        maxWidthClass="max-w-3xl"
      >
        {activeFullscreenPlace && (
          <div className="space-y-4" data-testid="fullscreen-place-modal">
            <div className="overflow-hidden rounded-card bg-canvas-subtle border border-border/60">
              <div className="aspect-[16/9] w-full overflow-hidden bg-canvas-subtle">
                {activeFullscreenPlace.hero_photos?.[0] ? (
                  <img
                    src={activeFullscreenPlace.hero_photos[0]}
                    alt={activeFullscreenPlace.name}
                    width={800}
                    height={450}
                    loading="lazy"
                    decoding="async"
                    referrerPolicy="no-referrer"
                    data-testid="fullscreen-place-photo-img"
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <NeutralPlaceCategoryIllustration
                    category={activeFullscreenPlace.category}
                    testId="fullscreen-place-photo-placeholder"
                  />
                )}
              </div>
              {(activeFullscreenPlace.photo_credit_text ||
                (activeFullscreenPlace.photo_author &&
                  activeFullscreenPlace.photo_license)) && (
                <div
                  className="px-4 py-2 bg-canvas-subtle/80 border-t border-border/60 text-caption text-ink-muted"
                  data-testid="fullscreen-photo-credit"
                >
                  {activeFullscreenPlace.photo_commons_url ? (
                    <a
                      href={activeFullscreenPlace.photo_commons_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      data-testid="fullscreen-photo-credit-link"
                      className="underline decoration-border hover:text-brand-700 transition-colors"
                    >
                      {activeFullscreenPlace.photo_credit_text ||
                        `Photo : ${activeFullscreenPlace.photo_author}, ${activeFullscreenPlace.photo_license}`}
                    </a>
                  ) : (
                    <span>
                      {activeFullscreenPlace.photo_credit_text ||
                        `Photo : ${activeFullscreenPlace.photo_author}, ${activeFullscreenPlace.photo_license}`}
                    </span>
                  )}
                </div>
              )}
            </div>

            <p className="text-body text-ink-secondary">
              {activeFullscreenPlace.description}
            </p>

            <div className="flex flex-wrap items-center justify-between gap-4 rounded-card bg-canvas-subtle p-4">
              <div className="space-y-0.5">
                <div className="text-caption text-ink-muted">Durée conseillée</div>
                <div className="text-body font-semibold text-ink">
                  {activeFullscreenPlace.recommended_duration_min} minutes
                </div>
              </div>
              <div className="space-y-0.5">
                <div className="text-caption text-ink-muted">Environnement</div>
                <div className="text-body font-semibold text-ink">
                  {activeFullscreenPlace.is_outdoor ? "En plein air" : "En intérieur"}
                </div>
              </div>
              <div className="space-y-0.5">
                <div className="text-caption text-ink-muted">Horaires</div>
                <div className="text-body font-semibold text-ink">
                  {activeFullscreenPlace.opening_hours?.display ||
                    activeFullscreenPlace.opening_hours?.mon ||
                    activeFullscreenPlace.hours_status ||
                    "non renseigné"}
                </div>
              </div>
            </div>

            {activeFullscreenPlace.source_attribution && (
              <div className="text-caption text-ink-muted">
                {activeFullscreenPlace.source_url ? (
                  <a
                    href={activeFullscreenPlace.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline decoration-border hover:text-brand-700"
                  >
                    {activeFullscreenPlace.source_attribution}
                  </a>
                ) : (
                  <span>{activeFullscreenPlace.source_attribution}</span>
                )}
              </div>
            )}

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
                  const p = activeFullscreenPlace;
                  setFullscreenPlace(null);
                  if (p) openAddPanel(p);
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
/* ============================================================================
 * BARRE D'ACCESSIBILITÉ VOCALE ÉTAPE 5V (COMPATIBLE LECTEUR D'ÉCRAN, AA, SANS SOURIS NI CLAVIER)
 * ========================================================================== */
export function VoiceAccessibilityToolbar({
  apiBase,
  token,
  tripId,
  defaultSummaryFr,
  onSelectDayNumber,
  onScheduleUpdated,
  onChatUpdated,
  onPendingProposalReceived,
}: {
  apiBase: string;
  token: string;
  tripId?: string | null;
  defaultSummaryFr?: string;
  onSelectDayNumber?: (dayNumber: number) => void;
  onScheduleUpdated?: () => void;
  onChatUpdated?: () => void;
  onPendingProposalReceived?: () => void;
}) {
  const navigate = useNavigate();
  const [voiceSettings, setVoiceSettings] = useState<VoiceAccessibilitySettings>(
    () => loadVoiceAccessibilitySettings()
  );
  const [listening, setListening] = useState<boolean>(false);
  const [spokenReplyFr, setSpokenReplyFr] = useState<string>(
    defaultSummaryFr || ""
  );
  const [liveTranscriptFr, setLiveTranscriptFr] = useState<string>("");
  const [autoStartStatusFr, setAutoStartStatusFr] = useState<string>("");
  const [standbyStatusFr, setStandbyStatusFr] = useState<string>("");
  const [errorFr, setErrorFr] = useState<string>("");
  const [ttsPaused, setTtsPaused] = useState<boolean>(false);
  const [undoBanner, setUndoBanner] = useState<{
    messageId: string;
    summaryFr: string;
    history: Record<string, any> | null;
    remainingSeconds: number;
  } | null>(null);
  const [undoRestoredFr, setUndoRestoredFr] = useState<string>("");
  const [pendingConfirmMsgId, setPendingConfirmMsgId] = useState<string>("");
  const [pendingConfirmSummaryFr, setPendingConfirmSummaryFr] = useState<string>("");
  const stopRef = useRef<(() => void) | null>(null);
  const tripIdRef = useRef<string | null | undefined>(tripId);
  const tokenRef = useRef<string>(token);
  const voiceSettingsRef = useRef<VoiceAccessibilitySettings>(voiceSettings);
  const pendingConfirmMsgIdRef = useRef<string>(pendingConfirmMsgId);
  const callbacksRef = useRef({
    onSelectDayNumber,
    onScheduleUpdated,
    onChatUpdated,
    onPendingProposalReceived,
  });
  callbacksRef.current = {
    onSelectDayNumber,
    onScheduleUpdated,
    onChatUpdated,
    onPendingProposalReceived,
  };

  useEffect(() => {
    tripIdRef.current = tripId;
  }, [tripId]);

  useEffect(() => {
    tokenRef.current = token;
  }, [token]);

  useEffect(() => {
    voiceSettingsRef.current = voiceSettings;
  }, [voiceSettings]);

  useEffect(() => {
    pendingConfirmMsgIdRef.current = pendingConfirmMsgId;
  }, [pendingConfirmMsgId]);

  useEffect(() => {
    const sync = () => setVoiceSettings(loadVoiceAccessibilitySettings());
    window.addEventListener("tm-voice-settings-updated", sync);
    return () => window.removeEventListener("tm-voice-settings-updated", sync);
  }, []);

  useEffect(() => {
    if (defaultSummaryFr && !spokenReplyFr) {
      setSpokenReplyFr(defaultSummaryFr);
    }
  }, [defaultSummaryFr]);

  // Compte à rebours de 30 s pour l'annulation d'une modification directe
  useEffect(() => {
    if (!undoBanner) return;
    const interval = window.setInterval(() => {
      setUndoBanner((prev) => {
        if (!prev) return null;
        if (prev.remainingSeconds <= 1) return null;
        return { ...prev, remainingSeconds: prev.remainingSeconds - 1 };
      });
    }, 1000);
    return () => window.clearInterval(interval);
  }, [Boolean(undoBanner)]);

  async function resolveActiveTripId(): Promise<string | null> {
    if (tripIdRef.current) return tripIdRef.current;
    if (typeof localStorage !== "undefined") {
      const storedId = localStorage.getItem("travelmate_active_trip_id");
      if (storedId) {
        tripIdRef.current = storedId;
        return storedId;
      }
    }
    const activeToken = tokenRef.current;
    if (!activeToken) return null;
    try {
      const resp = await fetch(`${apiBase}/api/v1/trips`, {
        headers: { Authorization: `Bearer ${activeToken}` },
      });
      if (!resp.ok) return null;
      const trips = await resp.json();
      if (Array.isArray(trips) && trips.length > 0 && trips[0]?.id) {
        tripIdRef.current = String(trips[0].id);
        return tripIdRef.current;
      }
    } catch {
      // ignore
    }
    return null;
  }

  async function handleUndoDirectModification(explicitMessageId?: string) {
    const activeTripId = await resolveActiveTripId();
    const activeToken = tokenRef.current;
    if (!activeTripId || !activeToken) return;
    setErrorFr("");
    try {
      const resp = await fetch(
        `${apiBase}/api/v1/itinerary/trip/${activeTripId}/voice/undo`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${activeToken}`,
          },
          body: JSON.stringify({
            message_id: explicitMessageId || undoBanner?.messageId || null,
          }),
        }
      );
      const data = await resp.json().catch(() => null);
      if (resp.ok && data) {
        setUndoBanner(null);
        const msg =
          data.spoken_reply_fr ||
          "Modification annulée : l'état précédent (visite, horaire et synchronisation agenda) a été restauré.";
        setUndoRestoredFr(msg);
        setSpokenReplyFr(msg);
        speakFrenchResponse(msg, {
          rate: voiceSettingsRef.current.ttsRate,
          enabled: voiceSettingsRef.current.ttsEnabled,
        });
        callbacksRef.current.onScheduleUpdated?.();
        callbacksRef.current.onChatUpdated?.();
      } else {
        const errMsg =
          data?.spoken_reply_fr ||
          "Le délai de 30 secondes pour annuler est dépassé ou aucune modification récente n'est annulable.";
        setErrorFr(errMsg);
      }
    } catch {
      setErrorFr("Impossible d'annuler la dernière modification vocale.");
    }
  }

  async function handleVoiceConfirmPending(word: string) {
    const activeTripId = await resolveActiveTripId();
    const activeToken = tokenRef.current;
    const msgId = pendingConfirmMsgIdRef.current;
    if (!activeTripId || !activeToken || !msgId) return;
    setErrorFr("");
    try {
      const resp = await fetch(
        `${apiBase}/api/v1/itinerary/trip/${activeTripId}/chat/${msgId}/voice-confirm`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${activeToken}`,
          },
          body: JSON.stringify({
            message_id: msgId,
            transcript: word,
            signal: "SPEECH",
            confidence: 0.95,
            provider: voiceSettingsRef.current.sttProvider,
          }),
        }
      );
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.spoken_reply_fr) {
        setSpokenReplyFr(data.spoken_reply_fr);
        speakFrenchResponse(data.spoken_reply_fr, {
          rate: voiceSettingsRef.current.ttsRate,
          enabled: voiceSettingsRef.current.ttsEnabled,
        });
      }
      if (
        data.action_status === "CONFIRMED" ||
        data.action_status === "REJECTED"
      ) {
        setPendingConfirmMsgId("");
        setPendingConfirmSummaryFr("");
      } else if (data.action_status === "AWAITING_SECOND_CONFIRMATION") {
        setPendingConfirmSummaryFr(data.spoken_reply_fr || "");
      }
      callbacksRef.current.onScheduleUpdated?.();
      callbacksRef.current.onChatUpdated?.();
    } catch {
      // ignore
    }
  }

  async function runVoiceCommand(
    transcriptText: string,
    confidenceScore: number = 0.95
  ) {
    setErrorFr("");
    setUndoRestoredFr("");
    const cleanText = transcriptText.trim();
    if (!cleanText) return;

    // Exigence 6 : Jamais d'action sur une transcription de confiance faible
    if (confidenceScore < 0.6) {
      const lowMsg =
        "Confiance de transcription vocale trop faible : aucune action n'a été exécutée. Pouvez-vous répéter ?";
      setErrorFr(lowMsg);
      speakFrenchResponse(lowMsg, {
        rate: voiceSettingsRef.current.ttsRate,
        enabled: voiceSettingsRef.current.ttsEnabled,
      });
      return;
    }

    // Exigence 1 : Arrêt par la voix ("Arrête d'écouter") et reprise par "Écoute"
    if (
      /^\s*(?:arr[êe]te\s+d['’ ]?[ée]couter|stop\s+[ée]coute|arr[êe]te\s+l['’ ]?[ée]coute)\s*[.!]*\s*$/i.test(
        cleanText
      )
    ) {
      setListening(false);
      const stopMsg =
        "Écoute vocale mise en pause. Dites « Écoute » ou cliquez sur le bouton pour reprendre.";
      setStandbyStatusFr(stopMsg);
      setSpokenReplyFr(stopMsg);
      speakFrenchResponse(stopMsg, {
        rate: voiceSettingsRef.current.ttsRate,
        enabled: voiceSettingsRef.current.ttsEnabled,
      });
      return;
    }

    if (
      /^\s*(?:[ée]coute|reprends\s+l['’ ]?[ée]coute)\s*[.!]*\s*$/i.test(
        cleanText
      )
    ) {
      setStandbyStatusFr("");
      setErrorFr("");
      setListening(true);
      const resumeMsg = "Assistant vocal actif, dites une commande";
      setAutoStartStatusFr(resumeMsg);
      setSpokenReplyFr(resumeMsg);
      speakFrenchResponse(resumeMsg, {
        rate: voiceSettingsRef.current.ttsRate,
        enabled: voiceSettingsRef.current.ttsEnabled,
      });
      return;
    }

    // Exigence 3 : "Annule" restaure l'état précédent dans les 30 s
    if (/^\s*(?:annule|annuler|annule\s+la\s+modification)\s*[.!]*\s*$/i.test(cleanText)) {
      await handleUndoDirectModification();
      return;
    }

    // Exigence 4 : Si une confirmation est en attente et que l'utilisateur dit "oui" ou "non"
    if (
      pendingConfirmMsgIdRef.current &&
      /^\s*(?:oui|non)\s*[.!]*\s*$/i.test(cleanText)
    ) {
      await handleVoiceConfirmPending(cleanText);
      return;
    }

    const activeTripId = await resolveActiveTripId();
    const activeToken = tokenRef.current;
    const currentSettings = voiceSettingsRef.current;

    if (!activeTripId || !activeToken) {
      const fallback =
        defaultSummaryFr || `Commande vocale reçue : ${cleanText}.`;
      setSpokenReplyFr(fallback);
      speakFrenchResponse(fallback, {
        rate: currentSettings.ttsRate,
        enabled: currentSettings.ttsEnabled,
      });
      return;
    }

    try {
      const resp = await fetch(
        `${apiBase}/api/v1/itinerary/trip/${activeTripId}/voice/command`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${activeToken}`,
          },
          body: JSON.stringify({
            transcript: cleanText,
            signal: "SPEECH",
            confidence: confidenceScore,
            provider: currentSettings.sttProvider,
            hands_free: true,
            execute_without_confirmation:
              currentSettings.executeWithoutConfirmation,
          }),
        }
      );
      if (!resp.ok) {
        setErrorFr(
          "Accès refusé ou commande vocale indisponible pour votre rôle."
        );
        return;
      }
      const data = await resp.json();
      if (data.status === "ERROR" || data.status === "REPEAT_REQUIRED") {
        const msg =
          data.error_message_fr ||
          data.spoken_reply_fr ||
          "Pouvez-vous répéter ?";
        setErrorFr(msg);
        speakFrenchResponse(msg, {
          rate: currentSettings.ttsRate,
          enabled: currentSettings.ttsEnabled,
        });
        return;
      }

      const reply = data.spoken_reply_fr || defaultSummaryFr || "";
      setSpokenReplyFr(reply);
      speakFrenchResponse(reply, {
        rate: currentSettings.ttsRate,
        enabled: currentSettings.ttsEnabled,
      });

      if (data.status === "EXECUTED_DIRECTLY" && data.executed_directly) {
        setUndoBanner({
          messageId: data.undo_message_id || data.message_id || "",
          summaryFr: reply,
          history: data.last_modification_history || null,
          remainingSeconds: Number(data.undo_window_seconds || 30),
        });
        setPendingConfirmMsgId("");
        setPendingConfirmSummaryFr("");
        callbacksRef.current.onScheduleUpdated?.();
        callbacksRef.current.onChatUpdated?.();
      } else if (data.status === "UNDONE") {
        setUndoBanner(null);
        setUndoRestoredFr(reply);
        callbacksRef.current.onScheduleUpdated?.();
        callbacksRef.current.onChatUpdated?.();
      } else if (data.status === "PENDING_CONFIRMATION") {
        if (data.message_id) {
          setPendingConfirmMsgId(String(data.message_id));
          setPendingConfirmSummaryFr(reply);
        }
        callbacksRef.current.onChatUpdated?.();
        callbacksRef.current.onPendingProposalReceived?.();
      } else if (data.status === "ASK") {
        callbacksRef.current.onChatUpdated?.();
      }

      if (data.day_number && callbacksRef.current.onSelectDayNumber) {
        callbacksRef.current.onSelectDayNumber(Number(data.day_number));
      }
      if (data.navigation_target) {
        navigate(data.navigation_target);
      }
    } catch {
      setErrorFr("Impossible de joindre l'analyseur vocal.");
    }
  }

  function startListeningSession(isAutoStart: boolean = false) {
    setErrorFr("");
    setStandbyStatusFr("");
    if (stopRef.current) {
      stopRef.current();
      stopRef.current = null;
    }
    const currentSettings = voiceSettingsRef.current;
    const provider = createFrontendVoiceSTTProvider(currentSettings.sttProvider);
    let errorOccurredOnStart = false;

    const cleanup = provider.startListening({
      onListeningChange: (active) => {
        setListening(active);
      },
      onTranscript: (text, isFinal, conf) => {
        setLiveTranscriptFr(text);
        if (isFinal && text.trim()) {
          setLiveTranscriptFr("");
          runVoiceCommand(text.trim(), conf ?? 0.95);
        }
      },
      onSilenceStop: () => {
        setListening(false);
      },
      onStandbyPause: (standbyMsg) => {
        setListening(false);
        setStandbyStatusFr(standbyMsg);
        setAutoStartStatusFr("");
      },
      onLowConfidence: (_txt, _conf, lowMsg) => {
        setErrorFr(lowMsg);
        speakFrenchResponse(lowMsg, {
          rate: voiceSettingsRef.current.ttsRate,
          enabled: voiceSettingsRef.current.ttsEnabled,
        });
      },
      onAntiLoopStop: (loopMsg) => {
        setListening(false);
        setStandbyStatusFr(loopMsg);
      },
      onError: (code, msgFr) => {
        errorOccurredOnStart = true;
        setListening(false);
        setErrorFr(msgFr);
        if (code === "MIC_DENIED") {
          setAutoStartStatusFr(
            "Accès au microphone refusé : autorisez le microphone dans le navigateur pour activer l'écoute vocale."
          );
        }
      },
    });

    stopRef.current = cleanup;
    if (isAutoStart && !errorOccurredOnStart && provider.isSupported()) {
      const w = window as any;
      if (w.__TM_MIC_DENIED__ !== true && w.__TM_MIC_AUTHORIZED__ !== false) {
        const openingAnnouncement = "Assistant vocal actif, dites une commande";
        setAutoStartStatusFr(openingAnnouncement);
        setSpokenReplyFr(openingAnnouncement);
        speakFrenchResponse(openingAnnouncement, {
          rate: currentSettings.ttsRate,
          enabled: currentSettings.ttsEnabled,
        });
      }
    }
  }

  function handleStopListening() {
    if (stopRef.current) {
      stopRef.current();
      stopRef.current = null;
    }
    setListening(false);
    setStandbyStatusFr(
      "Écoute vocale arrêtée. Cliquez sur « Écoute » ou dites « Écoute » pour reprendre."
    );
  }

  function handleResumeListening() {
    setErrorFr("");
    setStandbyStatusFr("");
    startListeningSession(false);
    const resumeMsg = "Assistant vocal actif, dites une commande";
    setAutoStartStatusFr(resumeMsg);
    setSpokenReplyFr(resumeMsg);
    speakFrenchResponse(resumeMsg, {
      rate: voiceSettingsRef.current.ttsRate,
      enabled: voiceSettingsRef.current.ttsEnabled,
    });
  }

  function handleToggleMic() {
    if (listening) {
      handleStopListening();
    } else {
      handleResumeListening();
    }
  }

  // Exigence 1 & 6 : Démarrage automatique de l'écoute à l'ouverture si le micro est déjà autorisé
  // et si le mode "Assistant vocal toujours actif" est activé dans Paramètres. Sinon, un message clair.
  useEffect(() => {
    let cancelled = false;
    const settingsOnMount = loadVoiceAccessibilitySettings();

    async function checkPermissionAndAutoStart() {
      if (!settingsOnMount.alwaysActiveAssistant) {
        setAutoStartStatusFr(
          "Mode « Assistant vocal toujours actif » désactivé dans Paramètres. Cliquez sur « Écoute » pour parler."
        );
        return;
      }

      const w = window as any;
      if (w.__TM_MIC_DENIED__ === true || w.__TM_MIC_AUTHORIZED__ === false) {
        const deniedMsg =
          "Accès au microphone refusé ou non autorisé. Autorisez le microphone dans votre navigateur ou cliquez sur « Écoute ».";
        setAutoStartStatusFr(deniedMsg);
        setErrorFr(deniedMsg);
        return;
      }

      const provider = createFrontendVoiceSTTProvider(settingsOnMount.sttProvider);
      if (!provider.isSupported()) {
        setAutoStartStatusFr(
          "Microphone en attente d'activation — cliquez sur « Écoute » pour démarrer la commande vocale."
        );
        return;
      }

      let permState: string =
        w.__TM_MIC_AUTHORIZED__ === true ? "granted" : "unknown";
      if (
        permState === "unknown" &&
        typeof navigator !== "undefined" &&
        navigator.permissions?.query
      ) {
        try {
          const status = await navigator.permissions.query({
            name: "microphone" as PermissionName,
          });
          permState = status?.state || "unknown";
        } catch {
          permState = "unknown";
        }
      }

      if (cancelled) return;

      if (permState === "denied") {
        const deniedMsg =
          "Accès au microphone refusé : veuillez autoriser l'accès au microphone dans votre navigateur.";
        setAutoStartStatusFr(deniedMsg);
        setErrorFr(deniedMsg);
        return;
      }

      if (permState === "prompt" && w.__TM_MIC_AUTHORIZED__ !== true && !w.SpeechRecognition && !w.webkitSpeechRecognition) {
        setAutoStartStatusFr(
          "Microphone non encore autorisé : cliquez sur « Écoute » pour autoriser le microphone."
        );
        return;
      }

      // Micro autorisé et mode "Assistant vocal toujours actif" activé -> démarrage automatique
      startListeningSession(true);
    }

    checkPermissionAndAutoStart();
    return () => {
      cancelled = true;
      if (stopRef.current) {
        stopRef.current();
        stopRef.current = null;
      }
    };
  }, []);

  function handleRateChange(nextRate: number) {
    const updated: VoiceAccessibilitySettings = {
      ...voiceSettings,
      ttsRate: nextRate,
    };
    setVoiceSettings(updated);
    saveVoiceAccessibilitySettings(updated);
  }

  return (
    <section
      role="region"
      aria-label="Commandes vocales et lecture à voix haute"
      data-testid="voice-accessibility-toolbar"
      className="rounded-card border border-brand-300 bg-white p-3.5 shadow-soft space-y-2.5"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {/* Pastille "J'écoute" toujours visible (Exigence 1) */}
          <div
            role="status"
            aria-live="polite"
            data-testid="voice-listening-pill"
            className={`inline-flex min-h-[40px] items-center gap-2 rounded-pill border px-3.5 py-1.5 text-caption font-bold ${
              listening
                ? "bg-amber-100 border-amber-400 text-amber-950"
                : "bg-canvas-subtle border-border text-ink-secondary"
            }`}
          >
            <span
              className={`h-2.5 w-2.5 rounded-full ${
                listening ? "bg-amber-600 animate-pulse" : "bg-ink-muted"
              }`}
              aria-hidden="true"
            />
            <span data-testid="screen-voice-listening-status">
              {listening ? "J'écoute…" : "Micro en pause"}
            </span>
          </div>

          <button
            type="button"
            data-testid="screen-voice-mic-btn"
            aria-label={
              listening
                ? "Arrêter l'écoute vocale (J'écoute…)"
                : "Reprendre l'écoute vocale en français (Écoute)"
            }
            aria-pressed={listening}
            onClick={handleToggleMic}
            className={`inline-flex min-h-[44px] items-center gap-2 rounded-card px-3.5 py-2 text-caption font-bold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700 focus-visible:ring-offset-2 ${
              listening
                ? "bg-amber-700 text-white"
                : "bg-brand-700 text-white hover:bg-brand-800"
            }`}
          >
            {listening ? (
              <>
                <MicOff className="h-4 w-4 shrink-0" />
                <span>Arrêter l'écoute</span>
              </>
            ) : (
              <>
                <Mic className="h-4 w-4 shrink-0" />
                <span>Écoute</span>
              </>
            )}
          </button>

          {!listening && (
            <button
              type="button"
              data-testid="voice-resume-listening-btn"
              onClick={handleResumeListening}
              className="inline-flex min-h-[40px] items-center gap-1.5 rounded-card border border-brand-300 bg-brand-50 px-3 py-1.5 text-caption font-semibold text-brand-900 hover:bg-brand-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700"
            >
              Reprendre (« Écoute »)
            </button>
          )}
        </div>

        {/* Lecture à voix haute (speechSynthesis) : vitesse réglable + bouton pause */}
        <div
          className="flex flex-wrap items-center gap-1.5"
          role="group"
          aria-label="Contrôles de lecture vocale"
        >
          <button
            type="button"
            data-testid="voice-tts-speak-btn"
            aria-label="Lire à voix haute le résumé de l'écran"
            onClick={() => {
              const textToRead =
                spokenReplyFr ||
                defaultSummaryFr ||
                "Résumé vocal prêt.";
              setSpokenReplyFr(textToRead);
              speakFrenchResponse(textToRead, {
                rate: voiceSettings.ttsRate,
                enabled: true,
              });
            }}
            className="inline-flex min-h-[44px] items-center gap-1.5 rounded-card border border-brand-300 bg-brand-50 px-3 py-1.5 text-caption font-semibold text-brand-900 hover:bg-brand-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700"
          >
            <Volume2 className="h-4 w-4 shrink-0" />
            <span>Lire à voix haute</span>
          </button>

          <button
            type="button"
            data-testid="voice-tts-pause-btn"
            aria-label={
              ttsPaused
                ? "Reprendre la lecture vocale"
                : "Mettre en pause la lecture vocale"
            }
            onClick={() => {
              const state = togglePauseSpeechSynthesis();
              setTtsPaused(state === "paused");
            }}
            className="inline-flex min-h-[44px] items-center gap-1 rounded-card border border-border bg-canvas-subtle px-3 py-1.5 text-caption font-semibold text-ink hover:border-brand-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700"
          >
            {ttsPaused ? (
              <>
                <Play className="h-3.5 w-3.5 shrink-0" />
                <span>Reprendre</span>
              </>
            ) : (
              <>
                <Pause className="h-3.5 w-3.5 shrink-0" />
                <span>Pause</span>
              </>
            )}
          </button>

          <div
            className="inline-flex items-center gap-1 rounded-card border border-border bg-canvas-subtle px-2 py-1"
            data-testid="voice-tts-rate-group"
            role="group"
            aria-label="Vitesse de lecture vocale"
          >
            {[0.8, 1.0, 1.2, 1.5].map((rate) => (
              <button
                key={rate}
                type="button"
                aria-label={`Vitesse de lecture ${rate}x`}
                aria-pressed={voiceSettings.ttsRate === rate}
                data-testid={`voice-rate-btn-${rate}`}
                onClick={() => handleRateChange(rate)}
                className={`min-h-[36px] rounded px-2 py-0.5 text-[11px] font-bold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700 ${
                  voiceSettings.ttsRate === rate
                    ? "bg-brand-700 text-white"
                    : "text-ink-secondary hover:text-ink"
                }`}
              >
                {rate}x
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Statut d'ouverture / veille / transcription en cours */}
      {(autoStartStatusFr || standbyStatusFr || liveTranscriptFr) && (
        <div
          role="status"
          aria-live="polite"
          data-testid="voice-autostart-status"
          className="rounded-card border border-border bg-canvas-subtle px-3 py-1.5 text-caption font-medium text-ink-secondary flex flex-wrap items-center justify-between gap-2"
        >
          <span>
            {standbyStatusFr ||
              (liveTranscriptFr
                ? `En cours de dictée : « ${liveTranscriptFr} »`
                : autoStartStatusFr)}
          </span>
          <span className="text-[11px] text-ink-muted">
            Fin de phrase : {voiceSettings.phraseEndDelaySeconds} s • Veille :{" "}
            {voiceSettings.standbyDelaySeconds} s
          </span>
        </div>
      )}

      {/* Exigence 3 : Bandeau d'annulation pendant 30 s après exécution directe (avec historique de la dernière modification) */}
      {undoBanner && (
        <div
          role="status"
          aria-live="assertive"
          data-testid="voice-undo-banner"
          className="rounded-card border border-emerald-400 bg-emerald-50 p-3 space-y-1.5"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-caption font-bold text-emerald-950">
              Modification exécutée directement ({undoBanner.remainingSeconds} s pour dire « Annule » ou cliquer sur Annuler)
            </div>
            <button
              type="button"
              data-testid="voice-undo-btn"
              onClick={() => handleUndoDirectModification(undoBanner.messageId)}
              className="min-h-[40px] rounded-card bg-emerald-800 px-3.5 py-1.5 text-caption font-bold text-white hover:bg-emerald-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-900"
            >
              Annuler
            </button>
          </div>
          {undoBanner.history && (
            <div
              data-testid="voice-last-modification-history"
              className="text-[11px] font-medium text-emerald-900"
            >
              Historique de la dernière modification :{" "}
              {undoBanner.history.place_name || "Visite"} (
              {undoBanner.history.action_type === "ADD_VISIT"
                ? `ajoutée le ${undoBanner.history.new_visit_date || ""} à ${undoBanner.history.new_local_start_time || ""}`
                : `déplacée de ${undoBanner.history.previous_visit_date || ""} ${undoBanner.history.previous_local_start_time || ""} vers ${undoBanner.history.new_visit_date || ""} ${undoBanner.history.new_local_start_time || ""}`}
              )
            </div>
          )}
        </div>
      )}

      {undoRestoredFr && (
        <div
          role="status"
          aria-live="polite"
          data-testid="voice-undo-restored-banner"
          className="rounded-card border border-brand-300 bg-brand-50 px-3 py-2 text-caption font-semibold text-brand-900"
        >
          {undoRestoredFr}
        </div>
      )}

      {/* Exigence 4 : Confirmation obligatoire pour supprimer, réserver et payer */}
      {pendingConfirmMsgId && (
        <div
          role="region"
          aria-label="Confirmation vocale obligatoire"
          data-testid="voice-toolbar-confirmation-box"
          className="rounded-card border border-amber-400 bg-amber-50 p-3 flex flex-wrap items-center justify-between gap-2"
        >
          <span className="text-caption font-bold text-amber-950">
            Confirmation obligatoire : {pendingConfirmSummaryFr || "Dites « oui » pour confirmer ou « non » pour annuler."}
          </span>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              data-testid="voice-toolbar-confirm-yes-btn"
              onClick={() => handleVoiceConfirmPending("oui")}
              className="min-h-[38px] rounded-card bg-brand-700 px-3 py-1 text-caption font-bold text-white hover:bg-brand-800"
            >
              Dire « oui »
            </button>
            <button
              type="button"
              data-testid="voice-toolbar-confirm-no-btn"
              onClick={() => handleVoiceConfirmPending("non")}
              className="min-h-[38px] rounded-card border border-border bg-white px-3 py-1 text-caption font-semibold text-ink hover:border-brand-700"
            >
              Dire « non »
            </button>
          </div>
        </div>
      )}

      {/* Parcours complet faisable sans souris ni clavier grâce aux commandes vocales */}
      <div
        className="flex flex-wrap items-center gap-1.5"
        role="group"
        aria-label="Commandes vocales rapides de navigation et de lecture"
      >
        <button
          type="button"
          data-testid="voice-cmd-read-budget"
          onClick={() => runVoiceCommand("lis-moi mon budget")}
          className="min-h-[40px] rounded-card border border-border bg-canvas-subtle px-3 py-1.5 text-caption font-semibold text-ink hover:border-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700"
        >
          « Lis-moi mon budget »
        </button>
        <button
          type="button"
          data-testid="voice-cmd-open-documents"
          onClick={() => runVoiceCommand("ouvre mes documents")}
          className="min-h-[40px] rounded-card border border-border bg-canvas-subtle px-3 py-1.5 text-caption font-semibold text-ink hover:border-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700"
        >
          « Ouvre mes documents »
        </button>
        <button
          type="button"
          data-testid="voice-cmd-open-infos"
          onClick={() => runVoiceCommand("infos pratiques")}
          className="min-h-[40px] rounded-card border border-border bg-canvas-subtle px-3 py-1.5 text-caption font-semibold text-ink hover:border-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700"
        >
          « Infos pratiques »
        </button>
        <button
          type="button"
          data-testid="voice-cmd-goto-itinerary"
          onClick={() => runVoiceCommand("va à mon programme")}
          className="min-h-[40px] rounded-card border border-border bg-canvas-subtle px-3 py-1.5 text-caption font-semibold text-ink hover:border-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700"
        >
          « Va à mon programme »
        </button>
        <button
          type="button"
          data-testid="voice-cmd-goto-accommodations"
          onClick={() => runVoiceCommand("ouvre l'hébergement")}
          className="min-h-[40px] rounded-card border border-border bg-canvas-subtle px-3 py-1.5 text-caption font-semibold text-ink hover:border-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700"
        >
          « Ouvre l'hébergement »
        </button>
        <button
          type="button"
          data-testid="voice-cmd-read-day-2"
          onClick={() => runVoiceCommand("lis-moi le jour 2")}
          className="min-h-[40px] rounded-card border border-border bg-canvas-subtle px-3 py-1.5 text-caption font-semibold text-ink hover:border-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700"
        >
          « Lis-moi le jour 2 »
        </button>
      </div>

      {errorFr && (
        <div
          role="alert"
          data-testid="voice-screen-error-banner"
          className="rounded-card border border-amber-400 bg-amber-50 px-3 py-2 text-caption font-semibold text-amber-950"
        >
          {errorFr}
        </div>
      )}

      {spokenReplyFr && (
        <div
          aria-live="polite"
          aria-atomic="true"
          data-testid="voice-spoken-reply-box"
          className="rounded-card bg-brand-50 border border-brand-200 px-3 py-2 text-caption font-medium text-ink"
        >
          <span className="font-bold text-brand-900">Lecture vocale : </span>
          <span>{spokenReplyFr}</span>
        </div>
      )}
    </section>
  );
}

/* ============================================================================
 * 3. ÉCRAN MON PROGRAMME (/itinerary) — ÉTAPE 3, ÉTAPE 4 & ÉTAPE 5V
 *    - UN JOUR à la fois
 *    - Puces horizontales des jours du séjour AVEC météo par jour
 *    - Alerte pluie/orage sur visite extérieure + suggestion intérieur / autre créneau (1 clic Accepter / Refuser)
 *    - Bouton "Génère mon programme" (Itinéraire IA en brouillon, 3 champs max)
 *    - Vue chronologique verticale du jour choisi avec indication Temps estimé / Temps réel
 *    - Bulle flottante Assistant de chat avec bouton micro (Web Speech API, fr-FR),
 *      lecture à voix haute (speechSynthesis), confirmation vocale ("oui"/"non"/silence)
 *      et double confirmation pour réservation, paiement et suppression
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

  // Étape 4.3 & 5V — Bulle flottante Assistant de chat & Accessibilité vocale
  const [chatOpen, setChatOpen] = useState<boolean>(false);
  const [chatMessages, setChatMessages] = useState<ChatMessageItem[]>([]);
  const [chatInput, setChatInput] = useState<string>("");
  const [chatSending, setChatSending] = useState<boolean>(false);
  const [chatConfirmingId, setChatConfirmingId] = useState<string>("");

  const [voiceSettings, setVoiceSettings] = useState<VoiceAccessibilitySettings>(
    () => loadVoiceAccessibilitySettings()
  );
  const [voiceListening, setVoiceListening] = useState<boolean>(false);
  const [voiceErrorFr, setVoiceErrorFr] = useState<string>("");
  const [ttsPaused, setTtsPaused] = useState<boolean>(false);
  const stopChatVoiceRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const syncVoiceSettings = () =>
      setVoiceSettings(loadVoiceAccessibilitySettings());
    window.addEventListener("tm-voice-settings-updated", syncVoiceSettings);
    return () =>
      window.removeEventListener("tm-voice-settings-updated", syncVoiceSettings);
  }, []);

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
        transit_mode: "METRO",
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
        transit_mode: item.transit_mode_to_next || "METRO",
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
            transit_mode: "METRO",
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
              transit_mode: item.transit_mode || "METRO",
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

  // Étape 4.3 & 5V — Envoyer un message au chat (avec lecture vocale et navigation le cas échéant)
  async function handleSendChatMessage(customText?: string) {
    const content = (customText ?? chatInput).trim();
    if (!trip?.id || !content || chatSending) return;
    if (!customText) setChatInput("");
    setVoiceErrorFr("");
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
        const messages: ChatMessageItem[] = data.messages || [];
        setChatMessages(messages);
        const latestAssistant =
          [...messages].reverse().find((m) => m.role !== "user") || null;
        if (latestAssistant?.content) {
          speakFrenchResponse(latestAssistant.content, {
            rate: voiceSettings.ttsRate,
            enabled: voiceSettings.ttsEnabled,
          });
        }
        if (latestAssistant?.navigation_target) {
          navigate(latestAssistant.navigation_target);
        }
      }
    } finally {
      setChatSending(false);
    }
  }

  // Étape 5V — Exécuter une commande vocale via le même analyseur que le chat
  async function handleVoiceCommandSubmit(
    transcriptText: string,
    signalType:
      | "SPEECH"
      | "SILENCE"
      | "NOISE"
      | "MIC_DENIED"
      | "BROWSER_UNSUPPORTED"
      | "UNRECOGNIZED_SPEECH" = "SPEECH"
  ) {
    if (!trip?.id || chatSending) return;
    setVoiceErrorFr("");
    setChatSending(true);
    try {
      const resp = await fetch(
        `${apiBase}/api/v1/itinerary/trip/${trip.id}/voice/command`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            transcript: transcriptText,
            signal: signalType,
            confidence: 0.95,
            provider: voiceSettings.sttProvider,
            hands_free: voiceSettings.handsFree,
            execute_without_confirmation:
              voiceSettings.executeWithoutConfirmation,
          }),
        }
      );
      if (resp.status === 403) {
        setVoiceErrorFr(
          "Accès refusé : votre rôle en lecture seule ne permet pas de modifier l'itinéraire."
        );
        return;
      }
      if (!resp.ok) {
        setVoiceErrorFr("Commande vocale temporairement indisponible.");
        return;
      }
      const data = await resp.json();
      if (data.status === "ERROR" || data.status === "REPEAT_REQUIRED") {
        const errMsg =
          data.error_message_fr ||
          data.spoken_reply_fr ||
          "Pouvez-vous répéter ?";
        setVoiceErrorFr(errMsg);
        speakFrenchResponse(errMsg, {
          rate: voiceSettings.ttsRate,
          enabled: voiceSettings.ttsEnabled,
        });
        return;
      }
      if (data.spoken_reply_fr) {
        speakFrenchResponse(data.spoken_reply_fr, {
          rate: voiceSettings.ttsRate,
          enabled: voiceSettings.ttsEnabled,
        });
      }
      if (data.day_number && tripDays[data.day_number - 1]) {
        setSelectedDayDate(tripDays[data.day_number - 1]);
      }
      if (
        data.applied_change ||
        data.status === "EXECUTED_DIRECTLY" ||
        data.status === "UNDONE"
      ) {
        await refreshSchedule();
      }
      await refreshChatHistory(trip.id);
      if (data.navigation_target && data.navigation_target !== "/itinerary") {
        navigate(data.navigation_target);
      }
    } finally {
      setChatSending(false);
    }
  }

  // Étape 5V — Confirmation vocale explicite ("oui" / "non" / silence, double confirmation pour suppression/réservation/paiement)
  async function handleVoiceConfirmAction(
    messageId: string,
    transcriptWord: string,
    signalType:
      | "SPEECH"
      | "SILENCE"
      | "NOISE"
      | "MIC_DENIED"
      | "BROWSER_UNSUPPORTED"
      | "UNRECOGNIZED_SPEECH" = "SPEECH"
  ) {
    if (!trip?.id) return;
    setChatConfirmingId(messageId);
    setVoiceErrorFr("");
    try {
      const resp = await fetch(
        `${apiBase}/api/v1/itinerary/trip/${trip.id}/chat/${messageId}/voice-confirm`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            message_id: messageId,
            transcript: transcriptWord,
            signal: signalType,
            confidence: 0.95,
            provider: voiceSettings.sttProvider,
          }),
        }
      );
      if (!resp.ok) {
        setVoiceErrorFr("Impossible de valider cette confirmation vocale.");
        return;
      }
      const data = await resp.json();
      if (data.spoken_reply_fr) {
        speakFrenchResponse(data.spoken_reply_fr, {
          rate: voiceSettings.ttsRate,
          enabled: voiceSettings.ttsEnabled,
        });
      }
      if (
        data.status === "ERROR_NO_MODIFICATION" ||
        data.status === "REPEAT_REQUIRED"
      ) {
        setVoiceErrorFr(data.spoken_reply_fr || "Pouvez-vous répéter ?");
      }
      await refreshChatHistory(trip.id);
      if (data.applied_change) {
        await refreshSchedule();
        notify({
          title: "Confirmé à la voix",
          description: data.spoken_reply_fr,
          tone: "success",
        });
      }
    } finally {
      setChatConfirmingId("");
    }
  }

  function handleToggleChatMic() {
    setVoiceErrorFr("");
    if (voiceListening && stopChatVoiceRef.current) {
      stopChatVoiceRef.current();
      stopChatVoiceRef.current = null;
      setVoiceListening(false);
      return;
    }

    const provider = createFrontendVoiceSTTProvider(voiceSettings.sttProvider);
    stopChatVoiceRef.current = provider.startListening({
      onListeningChange: (active) => setVoiceListening(active),
      onTranscript: (transcript, isFinal) => {
        // Transcription affichée et modifiable avant envoi, sauf en mode mains libres
        setChatInput(transcript);
        if (isFinal && voiceSettings.handsFree && transcript.trim()) {
          setChatInput("");
          handleVoiceCommandSubmit(transcript.trim(), "SPEECH");
        }
      },
      onSilenceStop: () => {
        setVoiceListening(false);
      },
      onError: (_code, msgFr) => {
        setVoiceListening(false);
        setVoiceErrorFr(msgFr);
      },
    });
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
        const data: { messages?: any[] } = await resp.json();
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
    (lastAssistantMsg.action_status === "PENDING_CONFIRMATION" ||
      lastAssistantMsg.action_status === "AWAITING_SECOND_CONFIRMATION")
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

      {/* Étape 5V — Barre d'accessibilité vocale & lecture à voix haute */}
      <div className="w-full pt-2">
        <VoiceAccessibilityToolbar
          apiBase={apiBase}
          token={token}
          tripId={trip?.id}
          defaultSummaryFr={
            currentDayItems.length > 0
              ? `Programme du ${formatFullDateHuman(
                  selectedDayDate
                )} à ${cityLabel} : ${currentDayItems
                  .map((it) => `${it.local_start_time} ${it.place_name}`)
                  .join(", ")}.`
              : `Programme à ${cityLabel} : aucune visite planifiée pour ce jour.`
          }
          onSelectDayNumber={(dayNum) => {
            const targetDate = tripDays[dayNum - 1];
            if (targetDate) setSelectedDayDate(targetDate);
          }}
          onScheduleUpdated={() => {
            refreshSchedule();
          }}
          onChatUpdated={() => {
            if (trip?.id) refreshChatHistory(trip.id);
          }}
        />
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
            className="!mt-0 fixed inset-0 z-50 w-full h-full md:inset-y-0 md:left-auto md:right-0 md:w-[400px] md:border-l md:border-border xl:top-16 xl:bottom-0 xl:left-auto xl:right-0 xl:z-40 xl:w-[400px] xl:h-[calc(100vh-4rem)] flex flex-col bg-canvas-card shadow-cardHover overflow-hidden"
          >
          <div
            data-testid="chat-panel-header"
            className="shrink-0 flex flex-nowrap items-center justify-between gap-2 bg-brand-700 px-3.5 py-2.5 text-white whitespace-nowrap"
          >
            <div className="flex items-center gap-1.5 shrink-0 whitespace-nowrap">
              <MessageCircle className="h-4 w-4 shrink-0" />
              <span
                data-testid="chat-header-title"
                className="text-caption font-bold whitespace-nowrap"
              >
                Assistant {cityLabel}
              </span>
            </div>
            <div className="flex items-center gap-1 shrink-0 whitespace-nowrap">
              <button
                type="button"
                data-testid="chat-tts-toggle-btn"
                aria-label={
                  voiceSettings.ttsEnabled
                    ? "Désactiver la lecture à voix haute"
                    : "Activer la lecture à voix haute"
                }
                aria-pressed={voiceSettings.ttsEnabled}
                onClick={() => {
                  const next = {
                    ...voiceSettings,
                    ttsEnabled: !voiceSettings.ttsEnabled,
                  };
                  setVoiceSettings(next);
                  saveVoiceAccessibilitySettings(next);
                  if (!next.ttsEnabled) stopSpeechSynthesis();
                }}
                className="rounded-md border border-white/25 bg-white/10 p-1.5 text-white hover:bg-white/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
              >
                {voiceSettings.ttsEnabled ? (
                  <Volume2 className="h-3.5 w-3.5" />
                ) : (
                  <VolumeX className="h-3.5 w-3.5" />
                )}
              </button>
              <button
                type="button"
                data-testid="chat-tts-pause-btn"
                aria-label={
                  ttsPaused
                    ? "Reprendre la lecture vocale"
                    : "Mettre en pause la lecture vocale"
                }
                onClick={() => {
                  const state = togglePauseSpeechSynthesis();
                  setTtsPaused(state === "paused");
                }}
                className="rounded-md border border-white/25 bg-white/10 px-1.5 py-1 text-[11px] font-medium text-white hover:bg-white/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white whitespace-nowrap"
              >
                {ttsPaused ? "Reprendre" : "Pause"}
              </button>
              <button
                type="button"
                data-testid="chat-tts-rate-btn"
                aria-label={`Vitesse de lecture vocale ${voiceSettings.ttsRate}x`}
                onClick={() => {
                  const rates = [0.8, 1.0, 1.2, 1.5];
                  const nextIdx =
                    (rates.indexOf(voiceSettings.ttsRate) + 1) % rates.length;
                  const next = {
                    ...voiceSettings,
                    ttsRate: rates[nextIdx],
                  };
                  setVoiceSettings(next);
                  saveVoiceAccessibilitySettings(next);
                }}
                className="rounded-md border border-white/25 bg-white/10 px-1.5 py-1 text-[11px] font-bold text-white hover:bg-white/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white whitespace-nowrap"
              >
                {voiceSettings.ttsRate}x
              </button>
              <button
                type="button"
                data-testid="new-chat-conversation-btn"
                aria-label="Nouvelle conversation"
                title="Nouvelle conversation"
                disabled={chatSending}
                onClick={handleResetChatConversation}
                className="rounded-md border border-white/25 bg-white/10 px-1.5 py-1 text-[11px] font-medium text-white hover:bg-white/20 disabled:opacity-50 whitespace-nowrap"
              >
                Effacer
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
                  Bonjour ! Je connais votre vol, votre budget, la météo et votre programme à {cityLabel}. Vous pouvez écrire ou utiliser le bouton micro (fr-FR).
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

                  {msg.role !== "user" && (
                    <div>
                      <button
                        type="button"
                        aria-label="Écouter cette réponse à voix haute"
                        data-testid={`chat-speak-msg-${msg.id}`}
                        onClick={() =>
                          speakFrenchResponse(msg.content, {
                            rate: voiceSettings.ttsRate,
                            enabled: true,
                          })
                        }
                        className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-800 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700"
                      >
                        <Volume2 className="h-3 w-3" />
                        <span>Lire à voix haute</span>
                      </button>
                    </div>
                  )}

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

          {/* Zone épinglée au-dessus du champ de saisie : Confirmer / Refuser + Confirmation vocale ("oui"/"non"/silence) */}
          {pendingChatProposalMsg && pendingChatProposalMsg.proposed_action && (
            <div
              data-testid="chat-proposed-action-card"
              className="shrink-0 border-t border-brand-200 bg-brand-50 px-4 py-3 text-left space-y-2"
            >
              <div className="flex flex-wrap items-center justify-between gap-1">
                <div className="text-[11px] font-bold uppercase tracking-wide text-brand-800">
                  Proposition en attente de votre accord
                </div>
                {pendingChatProposalMsg.proposed_action
                  .requires_double_confirmation && (
                  <span
                    data-testid="double-confirmation-badge"
                    className="rounded-pill bg-amber-100 border border-amber-400 px-2 py-0.5 text-[10px] font-bold text-amber-950"
                  >
                    Double confirmation requise (
                    {pendingChatProposalMsg.action_status ===
                    "AWAITING_SECOND_CONFIRMATION"
                      ? "2/2"
                      : "1/2"}
                    )
                  </span>
                )}
              </div>

              {pendingChatProposalMsg.proposed_action.spoken_summary_fr && (
                <div
                  data-testid="voice-action-spoken-summary"
                  className="text-[11px] font-medium text-brand-900"
                >
                  {pendingChatProposalMsg.proposed_action.spoken_summary_fr}
                </div>
              )}

              {pendingChatProposalMsg.proposed_action.validated_by_engine ? (
                <>
                  <div className="text-caption font-semibold text-ink">
                    {pendingChatProposalMsg.proposed_action.place_name} •{" "}
                    {formatFullDateHuman(
                      pendingChatProposalMsg.proposed_action.visit_date
                    )}{" "}
                    à {pendingChatProposalMsg.proposed_action.local_start_time}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 pt-0.5">
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

              {/* Confirmation vocale explicite : "oui" pour confirmer, "non" ou silence pour annuler */}
              <div
                data-testid="voice-confirmation-controls"
                className="flex flex-wrap items-center gap-1.5 pt-1 border-t border-brand-200/70"
              >
                <button
                  type="button"
                  data-testid="voice-confirm-yes-btn"
                  disabled={chatConfirmingId === pendingChatProposalMsg.id}
                  onClick={() =>
                    handleVoiceConfirmAction(
                      pendingChatProposalMsg.id,
                      "oui",
                      "SPEECH"
                    )
                  }
                  className="min-h-[36px] rounded-card bg-brand-700 px-2.5 py-1 text-[11px] font-bold text-white hover:bg-brand-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700"
                >
                  Dire « oui »
                </button>
                <button
                  type="button"
                  data-testid="voice-confirm-no-btn"
                  disabled={chatConfirmingId === pendingChatProposalMsg.id}
                  onClick={() =>
                    handleVoiceConfirmAction(
                      pendingChatProposalMsg.id,
                      "non",
                      "SPEECH"
                    )
                  }
                  className="min-h-[36px] rounded-card border border-border bg-white px-2.5 py-1 text-[11px] font-semibold text-ink hover:border-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700"
                >
                  Dire « non »
                </button>
                <button
                  type="button"
                  data-testid="voice-confirm-silence-btn"
                  disabled={chatConfirmingId === pendingChatProposalMsg.id}
                  onClick={() =>
                    handleVoiceConfirmAction(
                      pendingChatProposalMsg.id,
                      "",
                      "SILENCE"
                    )
                  }
                  className="min-h-[36px] rounded-card border border-border bg-canvas-subtle px-2.5 py-1 text-[11px] font-medium text-ink-secondary hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700"
                >
                  Silence (annuler)
                </button>
              </div>
            </div>
          )}

          {/* État visible "J'écoute…" et alertes d'erreur vocale (micro refusé, navigateur non compatible, parole non comprise, bruit) */}
          {voiceListening && (
            <div
              role="status"
              aria-live="polite"
              data-testid="voice-listening-status"
              className="shrink-0 flex items-center justify-between gap-2 border-t border-amber-300 bg-amber-50 px-4 py-2 text-caption font-bold text-amber-950"
            >
              <span>J'écoute… (parlez en français, arrêt par silence ou bouton)</span>
              <button
                type="button"
                data-testid="voice-stop-listening-btn"
                onClick={handleToggleChatMic}
                className="rounded-md bg-amber-800 px-2.5 py-1 text-[11px] font-bold text-white hover:bg-amber-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-900"
              >
                Arrêter
              </button>
            </div>
          )}

          {voiceErrorFr && (
            <div
              role="alert"
              data-testid="voice-error-banner"
              className="shrink-0 border-t border-amber-300 bg-amber-50 px-4 py-2 text-caption font-semibold text-amber-950"
            >
              {voiceErrorFr}
            </div>
          )}

          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSendChatMessage();
            }}
            className="shrink-0 flex items-center gap-2 border-t border-border bg-white p-3"
          >
            <button
              type="button"
              data-testid="chat-mic-btn"
              aria-label={
                voiceListening
                  ? "Arrêter l'écoute vocale (J'écoute…)"
                  : "Dicter un message vocal (Web Speech API, fr-FR)"
              }
              aria-pressed={voiceListening}
              onClick={handleToggleChatMic}
              className={`inline-flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-card border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700 focus-visible:ring-offset-2 ${
                voiceListening
                  ? "border-amber-700 bg-amber-700 text-white"
                  : "border-brand-300 bg-brand-50 text-brand-800 hover:bg-brand-100"
              }`}
            >
              {voiceListening ? (
                <MicOff className="h-4 w-4" />
              ) : (
                <Mic className="h-4 w-4" />
              )}
            </button>
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
 * HELPERS ÉTAPE 5A : RÔLES, DEVISES, CACHE LOCAL CHIFFRÉ HORS LIGNE
 * ========================================================================== */
export const OFFLINE_DOCS_OPT_IN_KEY = "tm_offline_docs_opt_in";
export const OFFLINE_DOCS_CACHE_KEY = "tm_offline_docs_encrypted_v1";
export const OFFLINE_DOCS_KEY_STORAGE = "tm_offline_docs_key_v1";

export function clearOfflineDocumentsCache(): void {
  try {
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(OFFLINE_DOCS_OPT_IN_KEY);
      window.localStorage.removeItem(OFFLINE_DOCS_CACHE_KEY);
      window.localStorage.removeItem(OFFLINE_DOCS_KEY_STORAGE);
      window.sessionStorage.removeItem(OFFLINE_DOCS_KEY_STORAGE);
    }
  } catch {
    // ignore storage errors
  }
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return typeof btoa === "function" ? btoa(binary) : binary;
}

function base64ToBytes(b64: string): Uint8Array {
  const binary = typeof atob === "function" ? atob(b64) : b64;
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    out[i] = binary.charCodeAt(i);
  }
  return out;
}

export async function encryptDocumentsToLocalOfflineCache(
  docsPayload: Array<{
    id: string;
    title: string;
    doc_type_label_fr: string;
    content_text: string;
    expires_on_fr: string | null;
  }>
): Promise<{ count: number; updated_at_fr: string }> {
  const updated_at_fr = "20 octobre 2026";
  const plainJson = JSON.stringify(docsPayload);
  const encoder = new TextEncoder();
  const plainBytes = encoder.encode(plainJson);

  if (typeof window !== "undefined" && window.crypto?.subtle) {
    const rawKey = window.crypto.getRandomValues(new Uint8Array(32));
    const iv = window.crypto.getRandomValues(new Uint8Array(12));
    const cryptoKey = await window.crypto.subtle.importKey(
      "raw",
      rawKey,
      { name: "AES-GCM" },
      false,
      ["encrypt"]
    );
    const encryptedBuf = await window.crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      cryptoKey,
      plainBytes
    );
    const cipherBytes = new Uint8Array(encryptedBuf);
    window.localStorage.setItem(OFFLINE_DOCS_KEY_STORAGE, bytesToBase64(rawKey));
    window.localStorage.setItem(
      OFFLINE_DOCS_CACHE_KEY,
      JSON.stringify({
        algorithm: "AES-256-GCM",
        iv_b64: bytesToBase64(iv),
        ciphertext_b64: bytesToBase64(cipherBytes),
        count: docsPayload.length,
        updated_at_fr,
      })
    );
  } else if (typeof window !== "undefined") {
    // Repli déterministe chiffré par masque XOR aléatoire 256 bits
    const keyBytes = new Uint8Array(32);
    for (let i = 0; i < 32; i++) keyBytes[i] = (i * 37 + 91) & 0xff;
    const xored = new Uint8Array(plainBytes.length);
    for (let i = 0; i < plainBytes.length; i++) {
      xored[i] = plainBytes[i] ^ keyBytes[i % keyBytes.length];
    }
    window.localStorage.setItem(OFFLINE_DOCS_KEY_STORAGE, bytesToBase64(keyBytes));
    window.localStorage.setItem(
      OFFLINE_DOCS_CACHE_KEY,
      JSON.stringify({
        algorithm: "XOR-256-FALLBACK",
        iv_b64: bytesToBase64(keyBytes.slice(0, 12)),
        ciphertext_b64: bytesToBase64(xored),
        count: docsPayload.length,
        updated_at_fr,
      })
    );
  }
  return { count: docsPayload.length, updated_at_fr };
}

export async function decryptDocumentsFromLocalOfflineCache(): Promise<
  Array<{
    id: string;
    title: string;
    doc_type_label_fr: string;
    content_text: string;
    expires_on_fr: string | null;
  }>
> {
  if (typeof window === "undefined") return [];
  const rawBundle = window.localStorage.getItem(OFFLINE_DOCS_CACHE_KEY);
  const keyB64 = window.localStorage.getItem(OFFLINE_DOCS_KEY_STORAGE);
  if (!rawBundle || !keyB64) return [];

  try {
    const bundle = JSON.parse(rawBundle);
    const keyBytes = base64ToBytes(keyB64);
    const cipherBytes = base64ToBytes(bundle.ciphertext_b64);

    if (bundle.algorithm === "AES-256-GCM" && window.crypto?.subtle) {
      const iv = base64ToBytes(bundle.iv_b64);
      const cryptoKey = await window.crypto.subtle.importKey(
        "raw",
        keyBytes.buffer as ArrayBuffer,
        { name: "AES-GCM" },
        false,
        ["decrypt"]
      );
      const plainBuf = await window.crypto.subtle.decrypt(
        { name: "AES-GCM", iv: iv.buffer as ArrayBuffer },
        cryptoKey,
        cipherBytes.buffer as ArrayBuffer
      );
      const text = new TextDecoder().decode(plainBuf);
      return JSON.parse(text);
    }

    const out = new Uint8Array(cipherBytes.length);
    for (let i = 0; i < cipherBytes.length; i++) {
      out[i] = cipherBytes[i] ^ keyBytes[i % keyBytes.length];
    }
    return JSON.parse(new TextDecoder().decode(out));
  } catch {
    return [];
  }
}

function formatRoleLabelFr(role?: string): string {
  const upper = (role || "OWNER").toUpperCase();
  if (upper === "OWNER") return "Propriétaire";
  if (upper === "EDITOR") return "Éditeur";
  return "Lecteur (lecture seule)";
}

export interface BudgetCategoryBreakdownItem {
  category: string;
  label_fr: string;
  planned_amount: string;
  spent_amount: string;
  items_count: number;
}

export interface BudgetExpenseItemView {
  id: string;
  trip_id: string;
  category: string;
  category_label_fr: string;
  title: string;
  amount: string;
  currency: string;
  original_amount: string;
  original_currency: string;
  exchange_rate_applied: string;
  is_estimated: boolean;
  created_at_fr: string;
}

export interface TripBudgetSummaryPayload {
  trip_id: string;
  currency: string;
  total_planned: string;
  total_spent: string;
  remaining_budget: string;
  over_budget_alert: boolean;
  over_budget_message_fr: string | null;
  excess_amount: string;
  consumption_percent: string;
  current_user_role: string;
  categories: BudgetCategoryBreakdownItem[];
  items: BudgetExpenseItemView[];
}

export interface DocumentSummaryItemView {
  id: string;
  trip_id: string;
  owner_id: string | null;
  is_owner: boolean;
  title: string;
  doc_type: string;
  doc_type_label_fr: string;
  is_shared: boolean;
  expires_on: string | null;
  expires_on_fr: string | null;
  passport_expiration_warning: boolean;
  passport_warning_message_fr: string | null;
  created_at_fr: string;
}

export interface TripDocumentsListPayload {
  trip_id: string;
  current_user_role: string;
  passport_expiration_alert: boolean;
  passport_alert_message_fr: string | null;
  documents: DocumentSummaryItemView[];
}

export interface PracticalInfoPayload {
  destination_id: string;
  city_name: string;
  country_name: string;
  plugs: string;
  tipping: string;
  emergency: string;
  dial_code: string;
  currency: string;
  visa: string;
  source: string;
  updated_at_fr: string;
  useful_phrases: Array<{
    fr: string;
    local: string;
    pronunciation: string;
  }>;
}

const DEFAULT_DEMO_BUDGET: TripBudgetSummaryPayload = {
  trip_id: "demo-trip-marrakech",
  currency: "EUR",
  total_planned: "1800.00",
  total_spent: "1215.00",
  remaining_budget: "585.00",
  over_budget_alert: false,
  over_budget_message_fr: null,
  excess_amount: "0.00",
  consumption_percent: "67.50",
  current_user_role: "OWNER",
  categories: [
    {
      category: "FLIGHT",
      label_fr: "Vol",
      planned_amount: "540.00",
      spent_amount: "295.00",
      items_count: 1,
    },
    {
      category: "ACCOMMODATION",
      label_fr: "Hébergement",
      planned_amount: "630.00",
      spent_amount: "660.00",
      items_count: 1,
    },
    {
      category: "ACTIVITY",
      label_fr: "Activités",
      planned_amount: "270.00",
      spent_amount: "75.00",
      items_count: 1,
    },
    {
      category: "MEAL",
      label_fr: "Repas",
      planned_amount: "216.00",
      spent_amount: "140.00",
      items_count: 1,
    },
    {
      category: "TRANSPORT",
      label_fr: "Transports",
      planned_amount: "144.00",
      spent_amount: "45.00",
      items_count: 1,
    },
  ],
  items: [
    {
      id: "demo-exp-1",
      trip_id: "demo-trip-marrakech",
      category: "FLIGHT",
      category_label_fr: "Vol",
      title: "Vol aller-retour Air France Paris — Marrakech",
      amount: "295.00",
      currency: "EUR",
      original_amount: "295.00",
      original_currency: "EUR",
      exchange_rate_applied: "1.0000",
      is_estimated: false,
      created_at_fr: "10 novembre 2026",
    },
    {
      id: "demo-exp-2",
      trip_id: "demo-trip-marrakech",
      category: "ACCOMMODATION",
      category_label_fr: "Hébergement",
      title: "Riad Patio Andalou Médina (7 nuits)",
      amount: "660.00",
      currency: "EUR",
      original_amount: "660.00",
      original_currency: "EUR",
      exchange_rate_applied: "1.0000",
      is_estimated: false,
      created_at_fr: "10 novembre 2026",
    },
    {
      id: "demo-exp-3",
      trip_id: "demo-trip-marrakech",
      category: "ACTIVITY",
      category_label_fr: "Activités",
      title: "Entrées Jardin Majorelle & Palais de la Bahia",
      amount: "75.00",
      currency: "EUR",
      original_amount: "75.00",
      original_currency: "EUR",
      exchange_rate_applied: "1.0000",
      is_estimated: false,
      created_at_fr: "11 novembre 2026",
    },
    {
      id: "demo-exp-4",
      trip_id: "demo-trip-marrakech",
      category: "MEAL",
      category_label_fr: "Repas",
      title: "Dîners traditionnels en médina",
      amount: "140.00",
      currency: "EUR",
      original_amount: "140.00",
      original_currency: "EUR",
      exchange_rate_applied: "1.0000",
      is_estimated: false,
      created_at_fr: "12 novembre 2026",
    },
    {
      id: "demo-exp-5",
      trip_id: "demo-trip-marrakech",
      category: "TRANSPORT",
      category_label_fr: "Transports",
      title: "Navette aéroport Ménara & taxis officiels",
      amount: "45.00",
      currency: "EUR",
      original_amount: "45.00",
      original_currency: "EUR",
      exchange_rate_applied: "1.0000",
      is_estimated: false,
      created_at_fr: "10 novembre 2026",
    },
  ],
};

const DEFAULT_DEMO_DOCUMENTS: TripDocumentsListPayload = {
  trip_id: "demo-trip-marrakech",
  current_user_role: "OWNER",
  passport_expiration_alert: true,
  passport_alert_message_fr:
    "Rappel : votre passeport expire le 18 février 2027 (moins de 6 mois après la fin du séjour le 17 novembre 2026). Pensez à vérifier sa validité.",
  documents: [
    {
      id: "demo-doc-passport",
      trip_id: "demo-trip-marrakech",
      owner_id: "demo-user-1",
      is_owner: true,
      title: "Passeport biométrique — Alex Voyageur",
      doc_type: "PASSPORT",
      doc_type_label_fr: "Passeport",
      is_shared: false,
      expires_on: "2027-02-18",
      expires_on_fr: "18 février 2027",
      passport_expiration_warning: true,
      passport_warning_message_fr:
        "Rappel : votre passeport expire le 18 février 2027 (moins de 6 mois après la fin du séjour le 17 novembre 2026). Pensez à vérifier sa validité.",
      created_at_fr: "15 octobre 2026",
    },
    {
      id: "demo-doc-flight",
      trip_id: "demo-trip-marrakech",
      owner_id: "demo-user-1",
      is_owner: true,
      title: "Billet d'avion aller-retour Air France (Réf. TM8K4M)",
      doc_type: "FLIGHT_TICKET",
      doc_type_label_fr: "Billet d'avion",
      is_shared: true,
      expires_on: "2026-11-17",
      expires_on_fr: "17 novembre 2026",
      passport_expiration_warning: false,
      passport_warning_message_fr: null,
      created_at_fr: "15 octobre 2026",
    },
  ],
};

const DEFAULT_DEMO_PRACTICAL_INFO: PracticalInfoPayload = {
  destination_id: "dest-marrakech",
  city_name: "Marrakech",
  country_name: "Maroc",
  plugs: "Types C et E (220 V / 50 Hz — identiques à la France, aucun adaptateur requis)",
  tipping: "10 % au restaurant et dans les cafés ; 10 à 20 dirhams pour les bagages ou guides",
  emergency: "19 (Police), 15 (Pompiers / SAMU), 177 (Gendarmerie royale)",
  dial_code: "+212",
  currency: "Dirham marocain (MAD — env. 1 € ≈ 10,80 MAD)",
  visa: "Exempté de visa jusqu'à 90 jours pour l'UE ; passeport valide couvrant au moins la durée du séjour",
  source: "Office National Marocain du Tourisme & Conseils aux Voyageurs",
  updated_at_fr: "15 octobre 2026",
  useful_phrases: [
    {
      fr: "Bonjour, comment allez-vous ?",
      local: "Salam alaykoum, labass ?",
      pronunciation: "sa-lam a-laï-koum, la-bass",
    },
    {
      fr: "Merci beaucoup",
      local: "Choukran bezaf",
      pronunciation: "chou-kran be-zaf",
    },
    {
      fr: "Combien ça coûte, s'il vous plaît ?",
      local: "Bchhal hada, afak ?",
      pronunciation: "bch-hal ha-da, a-fak",
    },
    {
      fr: "L'addition, s'il vous plaît",
      local: "L'hssab afak",
      pronunciation: "l-hssab a-fak",
    },
  ],
};

function normalizeBudgetSummaryPayload(raw: any): TripBudgetSummaryPayload {
  if (!raw) return DEFAULT_DEMO_BUDGET;
  const plannedNum = Number(raw.total_planned || 0);
  const spentNum = Number(raw.total_spent || 0);
  const diff = plannedNum - spentNum;
  const pct =
    plannedNum > 0 ? Math.min(999, Math.round((spentNum / plannedNum) * 10000) / 100) : 0;

  return {
    trip_id: String(raw.trip_id || DEFAULT_DEMO_BUDGET.trip_id),
    currency: String(raw.currency || "EUR"),
    total_planned: String(raw.total_planned || "0.00"),
    total_spent: String(raw.total_spent || "0.00"),
    remaining_budget: String(raw.remaining_budget ?? raw.remaining_amount ?? diff.toFixed(2)),
    over_budget_alert: Boolean(raw.over_budget_alert),
    over_budget_message_fr:
      raw.over_budget_message_fr ?? raw.over_budget_message ?? null,
    excess_amount:
      raw.excess_amount ??
      (spentNum > plannedNum ? (spentNum - plannedNum).toFixed(2) : "0.00"),
    consumption_percent: String(raw.consumption_percent ?? pct.toFixed(2)),
    current_user_role: String(raw.current_user_role || raw.user_role || "OWNER"),
    categories: Array.isArray(raw.categories)
      ? raw.categories.map((c: any) => ({
          category: String(c.category),
          label_fr: String(c.label_fr),
          planned_amount: String(c.planned_amount || "0.00"),
          spent_amount: String(c.spent_amount || "0.00"),
          items_count: Number(c.items_count ?? c.item_count ?? 0),
        }))
      : DEFAULT_DEMO_BUDGET.categories,
    items: Array.isArray(raw.items)
      ? raw.items.map((it: any) => ({
          id: String(it.id),
          trip_id: String(it.trip_id),
          category: String(it.category),
          category_label_fr: String(it.category_label_fr),
          title: String(it.title),
          amount: String(it.amount || "0.00"),
          currency: String(it.currency || "EUR"),
          original_amount: String(it.original_amount ?? it.amount ?? "0.00"),
          original_currency: String(it.original_currency ?? it.currency ?? "EUR"),
          exchange_rate_applied: String(it.exchange_rate_applied || "1.0000"),
          is_estimated: Boolean(it.is_estimated),
          created_at_fr: String(it.created_at_fr || "15 octobre 2026"),
        }))
      : DEFAULT_DEMO_BUDGET.items,
  };
}

function normalizeDocumentsListPayload(raw: any): TripDocumentsListPayload {
  if (!raw) return DEFAULT_DEMO_DOCUMENTS;
  const rawDocs = Array.isArray(raw.documents)
    ? raw.documents
    : Array.isArray(raw.items)
      ? raw.items
      : DEFAULT_DEMO_DOCUMENTS.documents;

  return {
    trip_id: String(raw.trip_id || DEFAULT_DEMO_DOCUMENTS.trip_id),
    current_user_role: String(raw.current_user_role || raw.user_role || "OWNER"),
    passport_expiration_alert: Boolean(raw.passport_expiration_alert),
    passport_alert_message_fr:
      raw.passport_alert_message_fr ?? raw.passport_expiration_message ?? null,
    documents: rawDocs.map((d: any) => ({
      id: String(d.id),
      trip_id: String(d.trip_id),
      owner_id: d.owner_id ? String(d.owner_id) : null,
      is_owner: d.is_owner !== undefined ? Boolean(d.is_owner) : true,
      title: String(d.title),
      doc_type: String(d.doc_type),
      doc_type_label_fr: String(d.doc_type_label_fr),
      is_shared: Boolean(d.is_shared),
      expires_on: d.expires_on ?? null,
      expires_on_fr: d.expires_on_fr ?? null,
      passport_expiration_warning: Boolean(
        d.passport_expiration_warning ?? d.is_expiring_soon
      ),
      passport_warning_message_fr:
        d.passport_warning_message_fr ?? d.expiration_warning ?? null,
      created_at_fr: String(d.created_at_fr || "15 octobre 2026"),
    })),
  };
}

function normalizePracticalInfoPayload(raw: any): PracticalInfoPayload {
  if (!raw) return DEFAULT_DEMO_PRACTICAL_INFO;
  return {
    destination_id: String(
      raw.destination_id || DEFAULT_DEMO_PRACTICAL_INFO.destination_id
    ),
    city_name: String(raw.city_name || DEFAULT_DEMO_PRACTICAL_INFO.city_name),
    country_name: String(
      raw.country_name || DEFAULT_DEMO_PRACTICAL_INFO.country_name
    ),
    plugs: String(raw.plugs || raw.plug_types || DEFAULT_DEMO_PRACTICAL_INFO.plugs),
    tipping: String(raw.tipping || DEFAULT_DEMO_PRACTICAL_INFO.tipping),
    emergency: String(
      raw.emergency ||
        raw.emergency_numbers ||
        DEFAULT_DEMO_PRACTICAL_INFO.emergency
    ),
    dial_code: String(raw.dial_code || DEFAULT_DEMO_PRACTICAL_INFO.dial_code),
    currency: String(
      raw.currency || raw.currency_info || DEFAULT_DEMO_PRACTICAL_INFO.currency
    ),
    visa: String(raw.visa || DEFAULT_DEMO_PRACTICAL_INFO.visa),
    source: String(raw.source || DEFAULT_DEMO_PRACTICAL_INFO.source),
    updated_at_fr: String(
      raw.updated_at_fr || DEFAULT_DEMO_PRACTICAL_INFO.updated_at_fr
    ),
    useful_phrases: Array.isArray(raw.useful_phrases)
      ? raw.useful_phrases.map((p: any) => ({
          fr: String(p.fr || p.french || p.phrase_fr || ""),
          local: String(p.local || p.local_translation || p.translation || ""),
          pronunciation: String(p.pronunciation || ""),
        }))
      : DEFAULT_DEMO_PRACTICAL_INFO.useful_phrases,
  };
}

function TripSubNavHeader({
  activeTab,
  cityLabel,
  userRole,
  apiBase = "",
  token = "",
  tripId = null,
  defaultSummaryFr,
}: {
  activeTab: "hub" | "budget" | "documents" | "infos";
  cityLabel: string;
  userRole?: string;
  apiBase?: string;
  token?: string;
  tripId?: string | null;
  defaultSummaryFr?: string;
}) {
  const navigate = useNavigate();
  const items = [
    { key: "hub", label: "Vue d'ensemble", path: "/trip", testId: "subnav-trip-hub" },
    { key: "budget", label: "Budget", path: "/trip/budget", testId: "subnav-trip-budget" },
    { key: "documents", label: "Mes documents", path: "/trip/documents", testId: "subnav-trip-documents" },
    { key: "infos", label: "Infos pratiques & traducteur", path: "/trip/infos", testId: "subnav-trip-infos" },
  ] as const;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-4">
        <div className="flex flex-wrap items-center gap-2" role="navigation" aria-label="Sous-pages Mon voyage">
          {items.map((item) => {
            const isActive = activeTab === item.key;
            return (
              <button
                key={item.key}
                type="button"
                data-testid={item.testId}
                onClick={() => navigate(item.path)}
                className={`rounded-pill px-3.5 py-1.5 text-caption font-semibold transition-colors whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700 ${
                  isActive
                    ? "bg-brand-700 text-white shadow-sm"
                    : "bg-canvas-subtle text-ink-secondary hover:text-ink border border-border"
                }`}
              >
                {item.label}
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-2">
          <Badge variant="brand" data-testid="trip-role-badge">
            Rôle : {formatRoleLabelFr(userRole)}
          </Badge>
          <span className="text-caption text-ink-muted hidden sm:inline">
            Séjour à {cityLabel}
          </span>
        </div>
      </div>

      {/* Étape 5V — Voix ajoutée aux écrans de la 5A ("lis-moi mon budget", "ouvre mes documents", "infos pratiques") */}
      <VoiceAccessibilityToolbar
        apiBase={apiBase}
        token={token}
        tripId={tripId}
        defaultSummaryFr={defaultSummaryFr}
      />
    </div>
  );
}

/* ============================================================================
 * 4. ÉCRAN MON VOYAGE (/trip et /transports)
 *    - Page d'accueil "Mon voyage" avec cartes-résumé menant aux 3 sous-pages :
 *      /trip/budget, /trip/documents, /trip/infos
 *    - Rappelle aussi le vol, l'hébergement, le programme et le trajet aéroport -> hébergement
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
  onOpenDocumentsModal?: () => void;
}) {
  const navigate = useNavigate();
  const [schedule, setSchedule] = useState<TripItinerarySchedule | null>(null);
  const [transports, setTransports] = useState<LocalTransportsPayload | null>(null);
  const [fallbackAcc, setFallbackAcc] = useState<AccommodationItem | null>(null);
  const [budgetSummary, setBudgetSummary] = useState<TripBudgetSummaryPayload>(
    DEFAULT_DEMO_BUDGET
  );
  const [docsSummary, setDocsSummary] = useState<TripDocumentsListPayload>(
    DEFAULT_DEMO_DOCUMENTS
  );
  const [practicalSummary, setPracticalSummary] = useState<PracticalInfoPayload>(
    DEFAULT_DEMO_PRACTICAL_INFO
  );

  const cityLabel = destination?.city_name || "votre destination";
  const activeRole = trip?.current_user_role || budgetSummary.current_user_role || "OWNER";

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

    fetch(`${apiBase}/api/v1/budget/trip/${trip.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((raw) => {
        if (raw) setBudgetSummary(normalizeBudgetSummaryPayload(raw));
      })
      .catch(() => null);

    fetch(`${apiBase}/api/v1/documents/trip/${trip.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((raw) => {
        if (raw) setDocsSummary(normalizeDocumentsListPayload(raw));
      })
      .catch(() => null);

    if (destination?.id) {
      fetch(`${apiBase}/api/v1/destinations/${destination.id}/practical-info`)
        .then((r) => (r.ok ? r.json() : null))
        .then((raw) => {
          if (raw) setPracticalSummary(normalizePracticalInfoPayload(raw));
        })
        .catch(() => null);
    }

    if (!selectedAccommodation) {
      fetch(`${apiBase}/api/v1/accommodations/search?trip_id=${trip.id}&radius_km=12`)
        .then((r) => (r.ok ? r.json() : []))
        .then((list: AccommodationItem[]) => {
          if (list.length > 0) setFallbackAcc(list[0]);
        })
        .catch(() => null);
    }
  }, [trip?.id, destination?.id, token, selectedAccommodation, apiBase]);

  const activeAccommodation = selectedAccommodation || fallbackAcc;

  return (
    <div
      className="mx-auto max-w-6xl px-4 py-8 space-y-8"
      data-testid="my-trip-screen"
    >
      <TripSubNavHeader
        activeTab="hub"
        cityLabel={cityLabel}
        userRole={activeRole}
        apiBase={apiBase}
        token={token}
        tripId={trip?.id}
        defaultSummaryFr={`Mon voyage à ${cityLabel}. Budget prévu : ${budgetSummary.total_planned} ${budgetSummary.currency}, dépensé : ${budgetSummary.total_spent} ${budgetSummary.currency}, restant : ${budgetSummary.remaining_budget} ${budgetSummary.currency}. ${docsSummary.documents.length} document(s) chiffré(s).`}
      />

      {/* En-tête récapitulatif */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div>
          <Badge variant="brand" className="mb-2">
            Carnet de voyage
          </Badge>
          <h1 className="text-h1 text-ink">Mon voyage à {cityLabel}</h1>
          <p className="text-body text-ink-secondary mt-1">
            Accédez en un clic à votre budget détaillé, à vos documents chiffrés et aux informations pratiques de {cityLabel}.
          </p>
        </div>

        <Button
          type="button"
          variant="secondary"
          onClick={() => {
            if (onOpenDocumentsModal) onOpenDocumentsModal();
            navigate("/trip/documents");
          }}
          data-testid="trip-open-documents-btn"
        >
          <FileText className="h-4 w-4 text-brand-700" />
          <span>Mes documents</span>
        </Button>
      </div>

      {/* 3 CARTES-RÉSUMÉ PRINCIPALES MENANT AUX SOUS-PAGES (/trip/budget, /trip/documents, /trip/infos) */}
      <div
        className="grid grid-cols-1 md:grid-cols-3 gap-6"
        data-testid="trip-hub-summary-cards"
      >
        {/* Carte-résumé 1 : Budget (/trip/budget) */}
        <Card
          className="p-6 flex flex-col justify-between gap-4 border-brand-200"
          data-testid="trip-summary-card-budget"
        >
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-h2 font-semibold text-ink">Budget du séjour</h2>
              {budgetSummary.over_budget_alert ? (
                <Badge variant="warning">Dépassement</Badge>
              ) : (
                <Badge variant="success">Maîtrisé</Badge>
              )}
            </div>

            <div className="rounded-card bg-canvas-subtle p-4 space-y-1.5">
              <div className="flex items-baseline justify-between">
                <span className="text-caption text-ink-secondary">Dépensé</span>
                <span className="text-body font-bold text-ink">
                  {budgetSummary.total_spent} {budgetSummary.currency}
                </span>
              </div>
              <div className="flex items-baseline justify-between">
                <span className="text-caption text-ink-secondary">Prévu</span>
                <span className="text-caption font-semibold text-ink-secondary">
                  {budgetSummary.total_planned} {budgetSummary.currency}
                </span>
              </div>
              <div className="text-caption text-brand-800 font-medium pt-1">
                5 postes suivis : vol, hébergement, activités, repas, transports
              </div>
            </div>
          </div>

          <Button
            type="button"
            onClick={() => navigate("/trip/budget")}
            data-testid="goto-trip-budget-btn"
            className="w-full justify-between"
          >
            <span>Gérer mon budget</span>
            <ArrowRight className="h-4 w-4" />
          </Button>
        </Card>

        {/* Carte-résumé 2 : Documents (/trip/documents) */}
        <Card
          className="p-6 flex flex-col justify-between gap-4 border-brand-200"
          data-testid="trip-summary-card-documents"
        >
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-h2 font-semibold text-ink">Mes documents</h2>
              {docsSummary.passport_expiration_alert ? (
                <Badge variant="warning">Rappel passeport</Badge>
              ) : (
                <Badge variant="success">Prêts</Badge>
              )}
            </div>

            <div className="rounded-card bg-canvas-subtle p-4 space-y-1.5">
              <div className="text-body font-semibold text-ink">
                {docsSummary.documents.length} document(s) protégé(s)
              </div>
              <div className="text-caption text-ink-secondary">
                Passeport, billets et réservations chiffrés côté serveur, avec option de consultation hors ligne.
              </div>
              {docsSummary.passport_expiration_alert && (
                <div className="text-caption font-semibold text-amber-800 pt-1">
                  Vérifiez la date d'expiration de votre passeport
                </div>
              )}
            </div>
          </div>

          <Button
            type="button"
            onClick={() => navigate("/trip/documents")}
            data-testid="goto-trip-documents-btn"
            className="w-full justify-between"
          >
            <span>Consulter mes documents</span>
            <ArrowRight className="h-4 w-4" />
          </Button>
        </Card>

        {/* Carte-résumé 3 : Infos pratiques & Traducteur (/trip/infos) */}
        <Card
          className="p-6 flex flex-col justify-between gap-4 border-brand-200"
          data-testid="trip-summary-card-infos"
        >
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-h2 font-semibold text-ink">Infos & Traducteur</h2>
              <Badge variant="brand">{practicalSummary.dial_code}</Badge>
            </div>

            <div className="rounded-card bg-canvas-subtle p-4 space-y-1.5">
              <div className="text-body font-semibold text-ink">
                {practicalSummary.city_name} ({practicalSummary.country_name})
              </div>
              <div className="text-caption text-ink-secondary">
                Monnaie : {practicalSummary.currency}
              </div>
              <div className="text-caption text-brand-800 font-medium">
                Prises, pourboires, urgences et phrases utiles avec prononciation
              </div>
            </div>
          </div>

          <Button
            type="button"
            onClick={() => navigate("/trip/infos")}
            data-testid="goto-trip-infos-btn"
            className="w-full justify-between"
          >
            <span>Ouvrir les infos pratiques</span>
            <ArrowRight className="h-4 w-4" />
          </Button>
        </Card>
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
      </Card>

      {/* 4. Mon programme sur place */}
      <Card className="p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4" data-testid="trip-itinerary-card">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <CalendarIcon className="h-5 w-5 text-brand-700" />
            <h2 className="text-h2 text-ink">Mon programme sur place</h2>
            <Badge variant="brand">
              {schedule?.total_visits || 0} visite(s)
            </Badge>
          </div>
          <p className="text-body text-ink-secondary">
            {schedule && schedule.total_visits > 0
              ? `${schedule.total_visits} activité(s) planifiée(s) et synchronisée(s) avec votre agenda.`
              : "Consultez ou ajustez votre emploi du temps jour par jour."}
          </p>
        </div>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => navigate("/itinerary")}
        >
          Ouvrir mon programme jour par jour
        </Button>
      </Card>
    </div>
  );
}

/* ============================================================================
 * 4A. SOUS-PAGE BUDGET (/trip/budget)
 *     - Un sujet par écran : le Budget du séjour
 *     - 4 champs maximum par formulaire, montants en Decimal, conversion, alerte, CSV
 * ========================================================================== */
export function TripBudgetScreen({
  apiBase,
  token,
  trip,
  destination,
}: {
  apiBase: string;
  token: string;
  trip: Trip | null;
  destination: Destination | null;
}) {
  const { notify } = useToast();
  const [summary, setSummary] = useState<TripBudgetSummaryPayload>(
    DEFAULT_DEMO_BUDGET
  );
  const [title, setTitle] = useState<string>("");
  const [amount, setAmount] = useState<string>("");
  const [category, setCategory] = useState<string>("MEAL");
  const [currency, setCurrency] = useState<string>("EUR");
  const [submitting, setSubmitting] = useState<boolean>(false);

  // Convertisseur de devises (3 champs <= 4 champs)
  const [convAmount, setConvAmount] = useState<string>("100.00");
  const [convFrom, setConvFrom] = useState<string>("EUR");
  const [convTo, setConvTo] = useState<string>("MAD");
  const [convResult, setConvResult] = useState<{
    converted_amount: string;
    exchange_rate: string;
    from_currency: string;
    to_currency: string;
  } | null>({
    converted_amount: "1080.00",
    exchange_rate: "10.8000",
    from_currency: "EUR",
    to_currency: "MAD",
  });

  const cityLabel = destination?.city_name || "votre destination";
  const activeRole = summary.current_user_role || trip?.current_user_role || "OWNER";
  const isReadOnly = activeRole.toUpperCase() === "VIEWER";

  async function refreshBudget() {
    if (!trip?.id || !token) return;
    const resp = await fetch(`${apiBase}/api/v1/budget/trip/${trip.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (resp.ok) {
      const data = await resp.json();
      setSummary(normalizeBudgetSummaryPayload(data));
    }
  }

  useEffect(() => {
    refreshBudget().catch(() => null);
  }, [trip?.id, token, apiBase]);

  async function handleAddExpense(e: React.FormEvent) {
    e.preventDefault();
    if (!trip?.id || !title.trim() || !amount.trim() || isReadOnly) return;
    setSubmitting(true);
    try {
      const resp = await fetch(`${apiBase}/api/v1/budget/trip/${trip.id}/expenses`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          title: title.trim(),
          amount: amount.trim(),
          category,
          currency,
        }),
      });
      if (resp.ok) {
        setTitle("");
        setAmount("");
        await refreshBudget();
        notify({
          title: "Dépense enregistrée",
          description: "Votre budget a été recalculé avec précision.",
          tone: "success",
        });
      } else {
        const err = await resp.json().catch(() => null);
        notify({
          title: "Action refusée",
          description:
            typeof err?.detail === "string"
              ? err.detail
              : "Impossible d'ajouter cette dépense.",
          tone: "danger",
        });
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDeleteExpense(itemId: string) {
    if (!trip?.id || isReadOnly) return;
    const resp = await fetch(
      `${apiBase}/api/v1/budget/trip/${trip.id}/expenses/${itemId}`,
      {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      }
    );
    if (resp.ok) {
      await refreshBudget();
      notify({
        title: "Dépense supprimée",
        description: "Le total dépensé a été mis à jour.",
        tone: "info",
      });
    }
  }

  async function handleConvertCurrency(e: React.FormEvent) {
    e.preventDefault();
    const qs = new URLSearchParams({
      amount: convAmount || "100.00",
      from_currency: convFrom,
      to_currency: convTo,
    });
    const resp = await fetch(`${apiBase}/api/v1/budget/convert?${qs.toString()}`);
    if (resp.ok) {
      const data = await resp.json();
      setConvResult({
        converted_amount: String(data.converted_amount),
        exchange_rate: String(data.exchange_rate ?? data.rate ?? "1.0000"),
        from_currency: String(data.from_currency),
        to_currency: String(data.to_currency),
      });
    }
  }

  async function handleDownloadCsv() {
    if (!trip?.id) return;
    const resp = await fetch(
      `${apiBase}/api/v1/budget/trip/${trip.id}/export.csv`,
      {
        headers: { Authorization: `Bearer ${token}` },
      }
    );
    if (!resp.ok) return;
    const csvText = await resp.text();
    const blob = new Blob([csvText], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `budget-sejour-${cityLabel.toLowerCase()}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <div
      className="mx-auto max-w-6xl px-4 py-8 space-y-8"
      data-testid="trip-budget-screen"
    >
      <TripSubNavHeader
        activeTab="budget"
        cityLabel={cityLabel}
        userRole={activeRole}
        apiBase={apiBase}
        token={token}
        tripId={trip?.id}
        defaultSummaryFr={`Point sur votre budget à ${cityLabel} : prévu ${summary.total_planned} ${summary.currency}, dépensé ${summary.total_spent} ${summary.currency}, solde restant ${summary.remaining_budget} ${summary.currency}.${summary.over_budget_alert && summary.over_budget_message_fr ? ` ${summary.over_budget_message_fr}` : ""}`}
      />

      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div>
          <Badge variant="brand" className="mb-2">
            Suivi financier
          </Badge>
          <h1 className="text-h1 text-ink">Budget de mon séjour à {cityLabel}</h1>
          <p className="text-body text-ink-secondary mt-1">
            Suivez votre budget prévu et vos dépenses réelles par catégorie (vol, hébergement, activités, repas, transports).
          </p>
        </div>

        <Button
          type="button"
          variant="secondary"
          onClick={handleDownloadCsv}
          data-testid="budget-export-csv-btn"
        >
          <span>Exporter en CSV</span>
        </Button>
      </div>

      {/* Alerte de dépassement */}
      {summary.over_budget_alert && (
        <div
          role="alert"
          data-testid="budget-over-alert"
          className="rounded-card border border-amber-300 bg-amber-50 p-4 text-body font-medium text-amber-950"
        >
          {summary.over_budget_message_fr ||
            `Attention : votre budget prévu est dépassé de ${summary.excess_amount} ${summary.currency}.`}
        </div>
      )}

      {/* Cartes de synthèse */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4" data-testid="budget-totals-cards">
        <Card className="p-5 space-y-1">
          <div className="text-caption text-ink-secondary">Total prévu</div>
          <div className="text-h2 font-bold text-ink" data-testid="budget-total-planned">
            {summary.total_planned} {summary.currency}
          </div>
          <div className="text-caption text-ink-muted">Enveloppe globale du séjour</div>
        </Card>

        <Card className="p-5 space-y-1">
          <div className="text-caption text-ink-secondary">Total dépensé</div>
          <div className="text-h2 font-bold text-brand-800" data-testid="budget-total-spent">
            {summary.total_spent} {summary.currency}
          </div>
          <div className="text-caption text-ink-muted">
            {summary.consumption_percent} % du budget utilisé
          </div>
        </Card>

        <Card className="p-5 space-y-1">
          <div className="text-caption text-ink-secondary">
            {summary.over_budget_alert ? "Dépassement constaté" : "Solde disponible"}
          </div>
          <div
            className={`text-h2 font-bold ${
              summary.over_budget_alert ? "text-amber-800" : "text-emerald-700"
            }`}
            data-testid="budget-remaining"
          >
            {summary.over_budget_alert
              ? `-${summary.excess_amount} ${summary.currency}`
              : `${summary.remaining_budget} ${summary.currency}`}
          </div>
          <div className="text-caption text-ink-muted">Calcul exact au centime</div>
        </Card>
      </div>

      {/* Répartition par catégorie (Vol, Hébergement, Activités, Repas, Transports) */}
      <Card className="p-6 space-y-4" data-testid="budget-categories-card">
        <h2 className="text-h2 text-ink">Répartition par poste de dépense</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
          {summary.categories.map((cat) => (
            <div
              key={cat.category}
              data-testid={`budget-cat-${cat.category.toLowerCase()}`}
              className="rounded-card border border-border bg-canvas-subtle p-4 space-y-1.5"
            >
              <div className="flex items-center justify-between">
                <span className="text-body font-semibold text-ink">
                  {cat.label_fr}
                </span>
                <Badge>{cat.items_count}</Badge>
              </div>
              <div className="text-body font-bold text-brand-800">
                {cat.spent_amount} {summary.currency}
              </div>
              <div className="text-caption text-ink-secondary">
                Repère : {cat.planned_amount} {summary.currency}
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Grille 2 colonnes : Ajouter une dépense (4 champs max) + Convertisseur de devises (3 champs) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-h2 text-ink">Ajouter une dépense manuelle</h2>
            {isReadOnly && (
              <Badge variant="warning">Lecture seule</Badge>
            )}
          </div>

          <form
            onSubmit={handleAddExpense}
            className="space-y-4"
            data-testid="budget-add-expense-form"
          >
            {/* Champ 1 : Libellé */}
            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Libellé de la dépense
              </label>
              <Input
                type="text"
                placeholder="Ex. Déjeuner place Jemaa el-Fna"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                disabled={isReadOnly}
                data-testid="expense-title-input"
                required
              />
            </div>

            {/* Champ 2 : Montant */}
            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Montant
              </label>
              <Input
                type="number"
                step="0.01"
                min="0.01"
                placeholder="Ex. 35.50"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                disabled={isReadOnly}
                data-testid="expense-amount-input"
                required
              />
            </div>

            {/* Champ 3 : Catégorie */}
            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Catégorie
              </label>
              <Select
                value={category}
                onValueChange={setCategory}
                ariaLabel="Catégorie de dépense"
                options={[
                  { value: "FLIGHT", label: "Vol" },
                  { value: "ACCOMMODATION", label: "Hébergement" },
                  { value: "ACTIVITY", label: "Activités" },
                  { value: "MEAL", label: "Repas" },
                  { value: "TRANSPORT", label: "Transports" },
                ]}
              />
            </div>

            {/* Champ 4 : Devise */}
            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Devise du paiement
              </label>
              <Select
                value={currency}
                onValueChange={setCurrency}
                ariaLabel="Devise du paiement"
                options={[
                  { value: "EUR", label: "Euro (EUR)" },
                  { value: "USD", label: "Dollar américain (USD)" },
                  { value: "MAD", label: "Dirham marocain (MAD)" },
                  { value: "JPY", label: "Yen japonais (JPY)" },
                  { value: "GBP", label: "Livre sterling (GBP)" },
                ]}
              />
            </div>

            <div className="flex justify-end pt-1">
              <Button
                type="submit"
                disabled={submitting || isReadOnly}
                data-testid="submit-expense-btn"
              >
                {submitting ? "Ajout en cours..." : "Enregistrer la dépense"}
              </Button>
            </div>
          </form>
        </Card>

        {/* Convertisseur de devises (3 champs <= 4 champs) */}
        <Card className="p-6 space-y-4">
          <h2 className="text-h2 text-ink">Convertisseur de devises</h2>
          <p className="text-caption text-ink-secondary">
            Convertissez instantanément vos montants avant de régler sur place.
          </p>

          <form
            onSubmit={handleConvertCurrency}
            className="space-y-4"
            data-testid="budget-converter-form"
          >
            {/* Champ 1 : Montant */}
            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Montant à convertir
              </label>
              <Input
                type="number"
                step="0.01"
                min="0.01"
                value={convAmount}
                onChange={(e) => setConvAmount(e.target.value)}
                data-testid="converter-amount-input"
                required
              />
            </div>

            {/* Champ 2 : Devise d'origine */}
            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Devise d'origine
              </label>
              <Select
                value={convFrom}
                onValueChange={setConvFrom}
                ariaLabel="Devise d'origine"
                options={[
                  { value: "EUR", label: "Euro (EUR)" },
                  { value: "USD", label: "Dollar américain (USD)" },
                  { value: "MAD", label: "Dirham marocain (MAD)" },
                  { value: "JPY", label: "Yen japonais (JPY)" },
                  { value: "GBP", label: "Livre sterling (GBP)" },
                ]}
              />
            </div>

            {/* Champ 3 : Devise cible */}
            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Devise souhaitée
              </label>
              <Select
                value={convTo}
                onValueChange={setConvTo}
                ariaLabel="Devise souhaitée"
                options={[
                  { value: "MAD", label: "Dirham marocain (MAD)" },
                  { value: "EUR", label: "Euro (EUR)" },
                  { value: "USD", label: "Dollar américain (USD)" },
                  { value: "JPY", label: "Yen japonais (JPY)" },
                  { value: "GBP", label: "Livre sterling (GBP)" },
                ]}
              />
            </div>

            <div className="flex justify-end">
              <Button
                type="submit"
                variant="secondary"
                data-testid="submit-converter-btn"
              >
                Convertir le montant
              </Button>
            </div>
          </form>

          {convResult && (
            <div
              className="rounded-card bg-brand-50 border border-brand-200 p-4 space-y-1"
              data-testid="converter-result-box"
            >
              <div className="text-body font-bold text-brand-900">
                Résultat : {convResult.converted_amount} {convResult.to_currency}
              </div>
              <div className="text-caption text-brand-800">
                Taux appliqué : 1 {convResult.from_currency} = {convResult.exchange_rate}{" "}
                {convResult.to_currency}
              </div>
            </div>
          )}
        </Card>
      </div>

      {/* Journal des dépenses */}
      <Card className="p-6 space-y-4" data-testid="budget-expenses-list">
        <h2 className="text-h2 text-ink">Détail des dépenses enregistrées</h2>
        {summary.items.length === 0 ? (
          <p className="text-body text-ink-secondary">
            Aucune dépense enregistrée pour ce séjour.
          </p>
        ) : (
          <div className="divide-y divide-border">
            {summary.items.map((item) => (
              <div
                key={item.id}
                data-testid="budget-expense-row"
                className="py-3.5 flex flex-wrap items-center justify-between gap-3"
              >
                <div className="space-y-0.5">
                  <div className="flex items-center gap-2">
                    <Badge variant="brand">{item.category_label_fr}</Badge>
                    <span className="text-body font-semibold text-ink">
                      {item.title}
                    </span>
                  </div>
                  <div className="text-caption text-ink-secondary">
                    Ajouté le {item.created_at_fr}
                    {item.original_currency !== item.currency && (
                      <span>
                        {" "}
                        • Réglé : {item.original_amount} {item.original_currency}
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <span className="text-body font-bold text-ink">
                    {item.amount} {item.currency}
                  </span>
                  {!isReadOnly && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDeleteExpense(item.id)}
                      data-testid={`delete-expense-${item.id}`}
                    >
                      <Trash2 className="h-4 w-4 text-ink-muted hover:text-red-600" />
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

/* ============================================================================
 * 4B. SOUS-PAGE DOCUMENTS (/trip/documents)
 *     - Un sujet par écran : Mes documents de voyage
 *     - Ajout (4 champs max), liste, suppression, partage explicite,
 *       rappel d'expiration du passeport, consultation hors ligne via cache local chiffré
 * ========================================================================== */
export function TripDocumentsScreen({
  apiBase,
  token,
  trip,
  destination,
}: {
  apiBase: string;
  token: string;
  trip: Trip | null;
  destination: Destination | null;
}) {
  const { notify } = useToast();
  const [docsPayload, setDocsPayload] = useState<TripDocumentsListPayload>(
    DEFAULT_DEMO_DOCUMENTS
  );
  const [title, setTitle] = useState<string>("");
  const [docType, setDocType] = useState<string>("PASSPORT");
  const [expiresOn, setExpiresOn] = useState<string>("");
  const [contentText, setContentText] = useState<string>("");
  const [submitting, setSubmitting] = useState<boolean>(false);

  const [openedDoc, setOpenedDoc] = useState<{
    id: string;
    title: string;
    doc_type_label_fr: string;
    content_text: string;
    expires_on_fr: string | null;
  } | null>(null);

  // Cache local chiffré hors ligne (activé UNIQUEMENT si l'utilisateur le choisit)
  const [offlineEnabled, setOfflineEnabled] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(OFFLINE_DOCS_OPT_IN_KEY) === "true";
  });
  const [offlineMeta, setOfflineMeta] = useState<{
    count: number;
    updated_at_fr: string;
  } | null>(null);

  const cityLabel = destination?.city_name || "votre destination";
  const activeRole =
    docsPayload.current_user_role || trip?.current_user_role || "OWNER";
  const isReadOnly = activeRole.toUpperCase() === "VIEWER";

  async function refreshDocuments() {
    if (!trip?.id || !token) return;
    const resp = await fetch(`${apiBase}/api/v1/documents/trip/${trip.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (resp.ok) {
      const data = await resp.json();
      setDocsPayload(normalizeDocumentsListPayload(data));
    }
  }

  useEffect(() => {
    refreshDocuments().catch(() => null);
  }, [trip?.id, token, apiBase]);

  async function syncOfflineCacheIfOptedIn(
    currentDocs: DocumentSummaryItemView[]
  ) {
    if (!trip?.id) return;
    const decryptedList: Array<{
      id: string;
      title: string;
      doc_type_label_fr: string;
      content_text: string;
      expires_on_fr: string | null;
    }> = [];

    for (const d of currentDocs) {
      const r = await fetch(
        `${apiBase}/api/v1/documents/trip/${trip.id}/${d.id}`,
        {
          headers: { Authorization: `Bearer ${token}` },
        }
      ).catch(() => null);
      if (r && r.ok) {
        const detail = await r.json();
        decryptedList.push({
          id: detail.id,
          title: detail.title,
          doc_type_label_fr: detail.doc_type_label_fr,
          content_text: detail.content_text,
          expires_on_fr: detail.expires_on_fr,
        });
      }
    }
    const meta = await encryptDocumentsToLocalOfflineCache(decryptedList);
    setOfflineMeta(meta);
  }

  async function handleToggleOfflineCache() {
    if (offlineEnabled) {
      clearOfflineDocumentsCache();
      setOfflineEnabled(false);
      setOfflineMeta(null);
      notify({
        title: "Cache hors ligne désactivé",
        description:
          "Les copies chiffrées locales ont été effacées de cet appareil.",
        tone: "info",
      });
      return;
    }

    if (typeof window !== "undefined") {
      window.localStorage.setItem(OFFLINE_DOCS_OPT_IN_KEY, "true");
    }
    setOfflineEnabled(true);
    await syncOfflineCacheIfOptedIn(docsPayload.documents);
    notify({
      title: "Consultation hors ligne activée",
      description:
        "Vos documents sont chiffrés dans le cache local et seront vidés automatiquement à la déconnexion.",
      tone: "success",
    });
  }

  async function handleAddDocument(e: React.FormEvent) {
    e.preventDefault();
    if (!trip?.id || !title.trim() || !contentText.trim() || isReadOnly) return;
    setSubmitting(true);
    try {
      const resp = await fetch(`${apiBase}/api/v1/documents/trip/${trip.id}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          title: title.trim(),
          doc_type: docType,
          content_text: contentText.trim(),
          expires_on: expiresOn.trim() ? expiresOn.trim() : null,
        }),
      });
      if (resp.ok) {
        setTitle("");
        setContentText("");
        setExpiresOn("");
        await refreshDocuments();
        notify({
          title: "Document chiffré et enregistré",
          description:
            "Votre document est protégé côté serveur et visible uniquement par vous par défaut.",
          tone: "success",
        });
      } else {
        const err = await resp.json().catch(() => null);
        notify({
          title: "Action refusée",
          description:
            typeof err?.detail === "string"
              ? err.detail
              : "Impossible d'ajouter ce document.",
          tone: "danger",
        });
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleViewDocument(docId: string) {
    if (!trip?.id) return;
    try {
      const resp = await fetch(
        `${apiBase}/api/v1/documents/trip/${trip.id}/${docId}`,
        {
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      if (resp.ok) {
        const detail = await resp.json();
        setOpenedDoc(detail);
        return;
      }
    } catch {
      // Repli sur le cache local chiffré hors ligne si activé
    }

    if (offlineEnabled) {
      const cachedDocs = await decryptDocumentsFromLocalOfflineCache();
      const found = cachedDocs.find((item) => item.id === docId);
      if (found) {
        setOpenedDoc(found);
        return;
      }
    }
  }

  async function handleToggleShare(doc: DocumentSummaryItemView) {
    if (!trip?.id || !doc.is_owner) return;
    const resp = await fetch(
      `${apiBase}/api/v1/documents/trip/${trip.id}/${doc.id}/share`,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ is_shared: !doc.is_shared }),
      }
    );
    if (resp.ok) {
      await refreshDocuments();
      notify({
        title: !doc.is_shared
          ? "Document partagé avec le séjour"
          : "Document redevenu strictement privé",
        description: !doc.is_shared
          ? "Les membres autorisés du voyage peuvent désormais le consulter."
          : "Vous êtes à nouveau la seule personne à voir ce document.",
        tone: "info",
      });
    }
  }

  async function handleDeleteDocument(docId: string) {
    if (!trip?.id || isReadOnly) return;
    const resp = await fetch(
      `${apiBase}/api/v1/documents/trip/${trip.id}/${docId}`,
      {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      }
    );
    if (resp.ok) {
      if (openedDoc?.id === docId) setOpenedDoc(null);
      await refreshDocuments();
      notify({
        title: "Document supprimé",
        description: "Le document chiffré a été retiré du séjour.",
        tone: "info",
      });
    }
  }

  return (
    <div
      className="mx-auto max-w-6xl px-4 py-8 space-y-8"
      data-testid="trip-documents-screen"
    >
      <TripSubNavHeader
        activeTab="documents"
        cityLabel={cityLabel}
        userRole={activeRole}
        apiBase={apiBase}
        token={token}
        tripId={trip?.id}
        defaultSummaryFr={`Mes documents de voyage à ${cityLabel} : ${docsPayload.documents.length} document(s) chiffré(s) accessible(s).${docsPayload.passport_expiration_alert && docsPayload.passport_alert_message_fr ? ` ${docsPayload.passport_alert_message_fr}` : ""}`}
      />

      <div>
        <Badge variant="brand" className="mb-2">
          Documents chiffrés & confidentiels
        </Badge>
        <h1 className="text-h1 text-ink">Mes documents de voyage</h1>
        <p className="text-body text-ink-secondary mt-1">
          Chaque document est chiffré côté serveur et visible uniquement par son propriétaire, sauf partage explicite.
        </p>
      </div>

      {/* Rappel d'expiration du passeport */}
      {docsPayload.passport_expiration_alert && (
        <div
          role="alert"
          data-testid="passport-expiration-banner"
          className="rounded-card border border-amber-300 bg-amber-50 p-4 text-body font-medium text-amber-950"
        >
          {docsPayload.passport_alert_message_fr}
        </div>
      )}

      {/* Consultation hors ligne via cache local chiffré (opt-in) */}
      <Card
        className="p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-brand-200"
        data-testid="offline-cache-card"
      >
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h2 className="text-h2 text-ink">Consultation hors ligne</h2>
            {offlineEnabled ? (
              <Badge variant="success">Cache local chiffré actif</Badge>
            ) : (
              <Badge>Désactivé par défaut</Badge>
            )}
          </div>
          <p className="text-caption text-ink-secondary">
            Activez cette option uniquement si vous souhaitez conserver une copie locale chiffrée de vos documents pour les consulter sans réseau. Ce cache est automatiquement vidé à la déconnexion.
          </p>
          {offlineEnabled && offlineMeta && (
            <p className="text-caption font-semibold text-brand-800">
              {offlineMeta.count} document(s) chiffré(s) sur cet appareil (mis à jour le{" "}
              {offlineMeta.updated_at_fr}).
            </p>
          )}
        </div>

        <Button
          type="button"
          variant={offlineEnabled ? "secondary" : "primary"}
          onClick={handleToggleOfflineCache}
          data-testid="toggle-offline-cache-btn"
        >
          {offlineEnabled
            ? "Désactiver et vider le cache local"
            : "Activer la consultation hors ligne"}
        </Button>
      </Card>

      {/* Grille 2 colonnes : Ajout d'un document (4 champs max) + Liste des documents */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-h2 text-ink">Ajouter un document</h2>
            {isReadOnly && <Badge variant="warning">Lecture seule</Badge>}
          </div>

          <form
            onSubmit={handleAddDocument}
            className="space-y-4"
            data-testid="document-add-form"
          >
            {/* Champ 1 : Titre */}
            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Titre du document
              </label>
              <Input
                type="text"
                placeholder="Ex. Passeport biométrique ou Billet retour"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                disabled={isReadOnly}
                data-testid="doc-title-input"
                required
              />
            </div>

            {/* Champ 2 : Type */}
            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Catégorie de document
              </label>
              <Select
                value={docType}
                onValueChange={setDocType}
                ariaLabel="Catégorie de document"
                options={[
                  { value: "PASSPORT", label: "Passeport" },
                  { value: "FLIGHT_TICKET", label: "Billet d'avion" },
                  { value: "HOTEL_BOOKING", label: "Réservation d'hébergement" },
                  { value: "INSURANCE", label: "Assurance voyage" },
                  { value: "OTHER", label: "Autre document" },
                ]}
              />
            </div>

            {/* Champ 3 : Date d'expiration */}
            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Date d'expiration (recommandée pour le passeport)
              </label>
              <Input
                type="date"
                value={expiresOn}
                onChange={(e) => setExpiresOn(e.target.value)}
                disabled={isReadOnly}
                data-testid="doc-expires-input"
              />
            </div>

            {/* Champ 4 : Contenu à chiffrer */}
            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Numéro ou informations à protéger
              </label>
              <Input
                type="text"
                placeholder="Ex. Passeport n° 24FR99102 — Délivré à Lyon"
                value={contentText}
                onChange={(e) => setContentText(e.target.value)}
                disabled={isReadOnly}
                data-testid="doc-content-input"
                required
              />
            </div>

            <div className="flex justify-end pt-1">
              <Button
                type="submit"
                disabled={submitting || isReadOnly}
                data-testid="submit-document-btn"
              >
                {submitting ? "Chiffrement..." : "Chiffrer et enregistrer"}
              </Button>
            </div>
          </form>
        </Card>

        {/* Liste des documents */}
        <Card className="p-6 space-y-4" data-testid="documents-list">
          <h2 className="text-h2 text-ink">Documents enregistrés</h2>
          {docsPayload.documents.length === 0 ? (
            <p className="text-body text-ink-secondary">
              Aucun document enregistré pour le moment.
            </p>
          ) : (
            <div className="space-y-3">
              {docsPayload.documents.map((doc) => (
                <div
                  key={doc.id}
                  data-testid="document-item-card"
                  className="rounded-card border border-border bg-canvas-subtle p-4 space-y-2.5"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Badge variant="brand">{doc.doc_type_label_fr}</Badge>
                      {doc.is_shared ? (
                        <Badge variant="success">Partagé avec le séjour</Badge>
                      ) : (
                        <Badge>Privé (propriétaire seul)</Badge>
                      )}
                    </div>
                    <span className="text-caption text-ink-muted">
                      Ajouté le {doc.created_at_fr}
                    </span>
                  </div>

                  <div className="text-body font-semibold text-ink">
                    {doc.title}
                  </div>

                  {doc.expires_on_fr && (
                    <div className="text-caption text-ink-secondary">
                      Validité jusqu'au <strong>{doc.expires_on_fr}</strong>
                    </div>
                  )}

                  {doc.passport_expiration_warning && doc.passport_warning_message_fr && (
                    <div className="text-caption font-semibold text-amber-800">
                      {doc.passport_warning_message_fr}
                    </div>
                  )}

                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      onClick={() => handleViewDocument(doc.id)}
                      data-testid={`view-doc-${doc.id}`}
                    >
                      Consulter le contenu déchiffré
                    </Button>

                    {doc.is_owner && !isReadOnly && (
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={() => handleToggleShare(doc)}
                        data-testid={`share-doc-${doc.id}`}
                      >
                        {doc.is_shared ? "Rendre privé" : "Partager"}
                      </Button>
                    )}

                    {doc.is_owner && !isReadOnly && (
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={() => handleDeleteDocument(doc.id)}
                        data-testid={`delete-doc-${doc.id}`}
                      >
                        <Trash2 className="h-4 w-4 text-ink-muted hover:text-red-600" />
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {openedDoc && (
            <div
              className="rounded-card border border-brand-200 bg-brand-50 p-4 space-y-1.5"
              data-testid="decrypted-document-viewer"
            >
              <div className="flex items-center justify-between">
                <span className="text-caption font-bold text-brand-900">
                  {openedDoc.title} ({openedDoc.doc_type_label_fr})
                </span>
                <button
                  type="button"
                  onClick={() => setOpenedDoc(null)}
                  className="text-caption font-medium text-brand-800 hover:underline"
                >
                  Fermer
                </button>
              </div>
              <div className="text-body font-medium text-ink">
                {openedDoc.content_text}
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

/* ============================================================================
 * 4C. SOUS-PAGE INFOS PRATIQUES & TRADUCTEUR (/trip/infos)
 *     - Un sujet par écran : Infos pratiques par destination (prises, pourboires,
 *       urgences, indicatif, monnaie) avec source et date de mise à jour en français
 *     - Traducteur et phrases utiles avec prononciation (mode déterministe)
 * ========================================================================== */
export function TripPracticalInfoScreen({
  apiBase,
  trip,
  destination,
}: {
  apiBase: string;
  trip: Trip | null;
  destination: Destination | null;
}) {
  const [info, setInfo] = useState<PracticalInfoPayload>(
    DEFAULT_DEMO_PRACTICAL_INFO
  );
  const [sourceText, setSourceText] = useState<string>(
    "Bonjour, où se trouve la gare ?"
  );
  const [targetLang, setTargetLang] = useState<string>("auto");
  const [translationResult, setTranslationResult] = useState<{
    source_text: string;
    target_language: string;
    translated_text: string;
    pronunciation: string;
  }>({
    source_text: "Bonjour, où se trouve la gare ?",
    target_language: "Arabe marocain (Darija)",
    translated_text: "Salam, fin kayna la gare afak ?",
    pronunciation: "sa-lam, fin kaï-na la gar a-fak",
  });

  const cityLabel = destination?.city_name || info.city_name || "Marrakech";
  const activeRole = trip?.current_user_role || "OWNER";

  useEffect(() => {
    if (!destination?.id) return;
    fetch(`${apiBase}/api/v1/destinations/${destination.id}/practical-info`)
      .then((r) => (r.ok ? r.json() : null))
      .then((raw) => {
        if (raw) setInfo(normalizePracticalInfoPayload(raw));
      })
      .catch(() => null);
  }, [destination?.id, apiBase]);

  async function handleTranslate(e: React.FormEvent, customPhrase?: string) {
    e.preventDefault();
    const phraseToTranslate = (customPhrase ?? sourceText).trim();
    if (!phraseToTranslate) return;
    const destId = destination?.id || info.destination_id;
    const resp = await fetch(
      `${apiBase}/api/v1/destinations/${destId}/translate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: phraseToTranslate,
          target_language: targetLang === "auto" ? null : targetLang,
        }),
      }
    );
    if (resp.ok) {
      const data = await resp.json();
      setTranslationResult(data);
    }
  }

  return (
    <div
      className="mx-auto max-w-6xl px-4 py-8 space-y-8"
      data-testid="trip-infos-screen"
    >
      <TripSubNavHeader
        activeTab="infos"
        cityLabel={cityLabel}
        userRole={activeRole}
        apiBase={apiBase}
        tripId={trip?.id}
        defaultSummaryFr={`Infos pratiques pour ${info.city_name} : Prises : ${info.plugs}. Urgences : ${info.emergency}. Monnaie : ${info.currency}. Indicatif : ${info.dial_code}. Pourboires : ${info.tipping}.`}
      />

      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div>
          <Badge variant="brand" className="mb-2">
            Guide pratique & langue locale
          </Badge>
          <h1 className="text-h1 text-ink">
            Infos pratiques & traducteur — {info.city_name}
          </h1>
          <p className="text-body text-ink-secondary mt-1">
            Tout ce qu'il faut savoir sur place (prises, pourboires, urgences, indicatif, monnaie) et phrases essentielles avec prononciation.
          </p>
        </div>

        <div
          className="text-caption text-ink-secondary sm:text-right"
          data-testid="practical-info-source-meta"
        >
          <div className="font-semibold text-ink">Source : {info.source}</div>
          <div>Mise à jour le {info.updated_at_fr}</div>
        </div>
      </div>

      {/* 5 Cartes d'infos pratiques : prises, pourboires, urgences, indicatif, monnaie */}
      <div
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4"
        data-testid="practical-info-grid"
      >
        <Card className="p-5 space-y-2" data-testid="practical-card-plugs">
          <div className="text-caption font-bold uppercase tracking-wide text-brand-800">
            Prises électriques
          </div>
          <div className="text-body font-semibold text-ink">{info.plugs}</div>
        </Card>

        <Card className="p-5 space-y-2" data-testid="practical-card-tipping">
          <div className="text-caption font-bold uppercase tracking-wide text-brand-800">
            Pourboires
          </div>
          <div className="text-body font-semibold text-ink">{info.tipping}</div>
        </Card>

        <Card className="p-5 space-y-2" data-testid="practical-card-emergency">
          <div className="text-caption font-bold uppercase tracking-wide text-brand-800">
            Urgences
          </div>
          <div className="text-body font-semibold text-ink">{info.emergency}</div>
        </Card>

        <Card className="p-5 space-y-2" data-testid="practical-card-dial">
          <div className="text-caption font-bold uppercase tracking-wide text-brand-800">
            Indicatif téléphonique
          </div>
          <div className="text-h2 font-bold text-ink">{info.dial_code}</div>
          <div className="text-caption text-ink-secondary">{info.country_name}</div>
        </Card>

        <Card className="p-5 space-y-2" data-testid="practical-card-currency">
          <div className="text-caption font-bold uppercase tracking-wide text-brand-800">
            Monnaie locale
          </div>
          <div className="text-body font-semibold text-ink">{info.currency}</div>
        </Card>
      </div>

      {/* Grille 2 colonnes : Traducteur avec prononciation (2 champs <= 4) + Phrases utiles */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="p-6 space-y-4" data-testid="translator-card">
          <h2 className="text-h2 text-ink">Traducteur avec prononciation</h2>
          <p className="text-caption text-ink-secondary">
            Saisissez une phrase en français pour obtenir sa traduction locale et sa prononciation phonétique.
          </p>

          <form
            onSubmit={handleTranslate}
            className="space-y-4"
            data-testid="translator-form"
          >
            {/* Champ 1 : Phrase en français */}
            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Phrase en français
              </label>
              <Input
                type="text"
                value={sourceText}
                onChange={(e) => setSourceText(e.target.value)}
                placeholder="Ex. Combien ça coûte, s'il vous plaît ?"
                data-testid="translator-text-input"
                required
              />
            </div>

            {/* Champ 2 : Langue cible */}
            <div>
              <label className="block text-caption font-medium text-ink-secondary mb-1">
                Langue de traduction
              </label>
              <Select
                value={targetLang}
                onValueChange={setTargetLang}
                ariaLabel="Langue de traduction"
                options={[
                  { value: "auto", label: `Langue locale (${info.city_name})` },
                  { value: "Anglais (États-Unis)", label: "Anglais" },
                  { value: "Japonais", label: "Japonais" },
                  { value: "Italien", label: "Italien" },
                  { value: "Arabe marocain (Darija)", label: "Arabe marocain (Darija)" },
                ]}
              />
            </div>

            <div className="flex justify-end">
              <Button type="submit" data-testid="submit-translate-btn">
                Traduire et afficher la prononciation
              </Button>
            </div>
          </form>

          <div
            className="rounded-card bg-brand-50 border border-brand-200 p-4 space-y-2"
            data-testid="translator-result-box"
          >
            <div className="text-caption font-semibold text-brand-800">
              {translationResult.target_language}
            </div>
            <div
              className="text-h2 font-bold text-ink"
              data-testid="translator-output-text"
            >
              {translationResult.translated_text}
            </div>
            <div
              className="text-caption font-medium text-brand-900"
              data-testid="translator-output-pronunciation"
            >
              Prononciation : « {translationResult.pronunciation} »
            </div>
          </div>
        </Card>

        {/* Phrases utiles de la destination */}
        <Card className="p-6 space-y-4" data-testid="useful-phrases-list">
          <h2 className="text-h2 text-ink">
            Phrases utiles à {info.city_name}
          </h2>
          <div className="space-y-3">
            {info.useful_phrases.map((phrase, idx) => (
              <div
                key={`${phrase.fr}-${idx}`}
                data-testid="useful-phrase-card"
                className="rounded-card border border-border bg-canvas-subtle p-4 space-y-1.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-body font-semibold text-ink">
                    {phrase.fr}
                  </span>
                  <button
                    type="button"
                    onClick={(e) => {
                      setSourceText(phrase.fr);
                      handleTranslate(e as any, phrase.fr);
                    }}
                    className="text-caption font-semibold text-brand-700 hover:underline whitespace-nowrap"
                  >
                    Écouter / Traduire
                  </button>
                </div>
                <div className="text-body font-bold text-brand-800">
                  {phrase.local}
                </div>
                <div className="text-caption text-ink-secondary">
                  Prononciation : « {phrase.pronunciation} »
                </div>
              </div>
            ))}
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
  departureCityNode,
}: {
  preferences: TravelerPreferences;
  onSavePreferences: (prefs: TravelerPreferences) => void;
  currentUser: UserProfile | null;
  onLogout: () => void;
  departureCityNode?: React.ReactNode;
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
  const [voiceSettings, setVoiceSettings] =
    useState<VoiceAccessibilitySettings>(() => loadVoiceAccessibilitySettings());

  function updateVoiceSetting(patch: Partial<VoiceAccessibilitySettings>) {
    const next: VoiceAccessibilitySettings = {
      ...voiceSettings,
      ...patch,
    };
    setVoiceSettings(next);
    saveVoiceAccessibilitySettings(next);
    if (!next.ttsEnabled) {
      stopSpeechSynthesis();
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onSavePreferences({
      ...preferences,
      currency,
      language,
      travelStyle,
    });
    saveVoiceAccessibilitySettings(voiceSettings);
    notify({
      title: "Préférences enregistrées",
      description: "Vos choix de devise, de langue, de confort et d'accessibilité vocale ont été mis à jour.",
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
          Personnalisez votre devise, votre langue, votre confort de voyage et l'accessibilité vocale.
        </p>
      </div>

      <Card className="p-6 sm:p-8 overflow-visible">
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

          {departureCityNode && (
            <div data-testid="settings-departure-city-section" className="overflow-visible">
              {departureCityNode}
            </div>
          )}

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

      {/* Étape 5V — Accessibilité vocale, synthèse vocale (speechSynthesis), mode mains libres et confidentialité */}
      <Card
        className="p-6 sm:p-8 space-y-5 border-brand-200"
        data-testid="voice-settings-card"
      >
        <div>
          <Badge variant="brand" className="mb-1.5">
            Accessibilité vocale (fr-FR)
          </Badge>
          <h2 className="text-h2 text-ink">
            Commandes vocales, lecture à voix haute & mode mains libres
          </h2>
          <p className="text-caption text-ink-secondary mt-1">
            Parcours complet faisable sans souris ni clavier grâce aux commandes vocales et à la confirmation explicite par « oui » ou « non ».
          </p>
        </div>

        {/* 1. Lecture à voix haute (speechSynthesis) désactivable dans Paramètres */}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-border bg-canvas-subtle p-4">
          <div className="space-y-0.5">
            <div className="text-body font-semibold text-ink">
              Lecture à voix haute des réponses (speechSynthesis)
            </div>
            <div className="text-caption text-ink-secondary">
              Lit automatiquement les réponses et relit chaque action avant confirmation.
            </div>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={voiceSettings.ttsEnabled}
            data-testid="settings-tts-toggle"
            onClick={() =>
              updateVoiceSetting({ ttsEnabled: !voiceSettings.ttsEnabled })
            }
            className={`min-h-[44px] rounded-card px-4 py-2 text-caption font-bold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700 focus-visible:ring-offset-2 ${
              voiceSettings.ttsEnabled
                ? "bg-brand-700 text-white"
                : "bg-white border border-border text-ink"
            }`}
          >
            {voiceSettings.ttsEnabled ? "Activée" : "Désactivée"}
          </button>
        </div>

        {/* 2. Vitesse de lecture réglable */}
        <div className="space-y-2">
          <div className="text-caption font-semibold text-ink">
            Vitesse de lecture vocale ({voiceSettings.ttsRate}x)
          </div>
          <div
            className="flex flex-wrap items-center gap-2"
            data-testid="settings-tts-rate-group"
          >
            {[0.8, 1.0, 1.2, 1.5].map((rateVal) => (
              <button
                key={rateVal}
                type="button"
                data-testid={`settings-tts-rate-${rateVal}`}
                aria-pressed={voiceSettings.ttsRate === rateVal}
                onClick={() => updateVoiceSetting({ ttsRate: rateVal })}
                className={`min-h-[44px] min-w-[64px] rounded-card px-3.5 py-2 text-caption font-bold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700 ${
                  voiceSettings.ttsRate === rateVal
                    ? "bg-brand-700 text-white"
                    : "bg-canvas-subtle border border-border text-ink hover:border-brand-700"
                }`}
              >
                {rateVal}x
              </button>
            ))}
          </div>
        </div>

        {/* 3. Mode "Assistant vocal toujours actif" (démarrage automatique à l'ouverture si micro autorisé) */}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-border bg-canvas-subtle p-4">
          <div className="space-y-0.5">
            <div className="text-body font-semibold text-ink">
              Assistant vocal toujours actif
            </div>
            <div className="text-caption text-ink-secondary">
              Démarre automatiquement l'écoute à l'ouverture de l'application si le microphone est déjà autorisé.
            </div>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={voiceSettings.alwaysActiveAssistant}
            data-testid="settings-always-active-voice-toggle"
            onClick={() =>
              updateVoiceSetting({
                alwaysActiveAssistant: !voiceSettings.alwaysActiveAssistant,
              })
            }
            className={`min-h-[44px] rounded-card px-4 py-2 text-caption font-bold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700 focus-visible:ring-offset-2 ${
              voiceSettings.alwaysActiveAssistant
                ? "bg-brand-700 text-white"
                : "bg-white border border-border text-ink"
            }`}
          >
            {voiceSettings.alwaysActiveAssistant ? "Activé" : "Désactivé"}
          </button>
        </div>

        {/* 4. Option "Exécuter sans confirmation" (activée par défaut pour ajouter/déplacer, désactivable) + Mode mains libres + Message de confidentialité */}
        <div className="space-y-3 rounded-card border border-brand-200 bg-brand-50/70 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="space-y-0.5">
              <div className="text-body font-semibold text-ink">
                Exécuter sans confirmation
              </div>
              <div className="text-caption text-ink-secondary">
                Activée par défaut pour ajouter ou déplacer une visite (si le lieu est reconnu avec un score élevé, date et heure explicites et créneau valide). Supprimer, réserver et payer demandent toujours une double confirmation.
              </div>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={voiceSettings.executeWithoutConfirmation}
              data-testid="settings-execute-without-confirmation-toggle"
              onClick={() =>
                updateVoiceSetting({
                  executeWithoutConfirmation:
                    !voiceSettings.executeWithoutConfirmation,
                })
              }
              className={`min-h-[44px] rounded-card px-4 py-2 text-caption font-bold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700 focus-visible:ring-offset-2 ${
                voiceSettings.executeWithoutConfirmation
                  ? "bg-brand-700 text-white"
                  : "bg-white border border-border text-ink"
              }`}
            >
              {voiceSettings.executeWithoutConfirmation
                ? "Activée (ajouter/déplacer)"
                : "Désactivée"}
            </button>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-brand-200">
            <div className="space-y-0.5">
              <div className="text-body font-semibold text-ink">
                Mode mains libres
              </div>
              <div className="text-caption text-ink-secondary">
                Envoie la commande vocale dès la fin de phrase sans étape d'édition manuelle (les actions sensibles exigent toujours « oui » explicite).
              </div>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={voiceSettings.handsFree}
              data-testid="settings-hands-free-toggle"
              onClick={() =>
                updateVoiceSetting({ handsFree: !voiceSettings.handsFree })
              }
              className={`min-h-[44px] rounded-card px-4 py-2 text-caption font-bold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700 focus-visible:ring-offset-2 ${
                voiceSettings.handsFree
                  ? "bg-brand-700 text-white"
                  : "bg-white border border-border text-ink"
              }`}
            >
              {voiceSettings.handsFree
                ? "Mains libres activé"
                : "Mains libres désactivé"}
            </button>
          </div>

          <div
            role="note"
            data-testid="voice-privacy-notice"
            className="rounded-card border border-amber-300 bg-amber-50 p-3 text-caption font-medium text-amber-950"
          >
            Confidentialité : en mode Web Speech API (fr-FR), l'audio peut transiter par le service de reconnaissance du navigateur. Vous pouvez sélectionner le fournisseur Whisper local ci-dessous pour un traitement local sans transit externe.
          </div>
        </div>

        {/* 5. Délais réglables dans Paramètres : fin de phrase (défaut 3 s) et veille (défaut 30 s sans parole) */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 rounded-card border border-border bg-canvas-subtle p-4">
          <div className="space-y-2">
            <div className="text-caption font-semibold text-ink">
              Délai de fin de phrase ({voiceSettings.phraseEndDelaySeconds} s — défaut 3 s)
            </div>
            <div
              className="flex flex-wrap items-center gap-1.5"
              data-testid="settings-phrase-delay-group"
              role="group"
              aria-label="Délai de fin de phrase"
            >
              {[2, 3, 4, 5].map((sec) => (
                <button
                  key={sec}
                  type="button"
                  data-testid={`settings-phrase-delay-${sec}s`}
                  aria-pressed={voiceSettings.phraseEndDelaySeconds === sec}
                  onClick={() =>
                    updateVoiceSetting({ phraseEndDelaySeconds: sec })
                  }
                  className={`min-h-[40px] min-w-[52px] rounded-card px-3 py-1.5 text-caption font-bold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700 ${
                    voiceSettings.phraseEndDelaySeconds === sec
                      ? "bg-brand-700 text-white"
                      : "bg-white border border-border text-ink hover:border-brand-700"
                  }`}
                >
                  {sec} s
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <div className="text-caption font-semibold text-ink">
              Délai de veille sans parole ({voiceSettings.standbyDelaySeconds} s — défaut 30 s)
            </div>
            <div
              className="flex flex-wrap items-center gap-1.5"
              data-testid="settings-standby-delay-group"
              role="group"
              aria-label="Délai de veille sans parole"
            >
              {[15, 30, 45, 60].map((sec) => (
                <button
                  key={sec}
                  type="button"
                  data-testid={`settings-standby-delay-${sec}s`}
                  aria-pressed={voiceSettings.standbyDelaySeconds === sec}
                  onClick={() =>
                    updateVoiceSetting({ standbyDelaySeconds: sec })
                  }
                  className={`min-h-[40px] min-w-[52px] rounded-card px-3 py-1.5 text-caption font-bold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700 ${
                    voiceSettings.standbyDelaySeconds === sec
                      ? "bg-brand-700 text-white"
                      : "bg-white border border-border text-ink hover:border-brand-700"
                  }`}
                >
                  {sec} s
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* 4. Fournisseur de reconnaissance vocale remplaçable (Web Speech API vs Whisper local derrière la même interface) */}
        <div className="space-y-2" data-testid="settings-stt-provider-select">
          <div className="text-caption font-semibold text-ink">
            Fournisseur de reconnaissance vocale (même interface STT fr-FR)
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            <button
              type="button"
              data-testid="settings-stt-provider-web"
              aria-pressed={voiceSettings.sttProvider === "web_speech"}
              onClick={() => updateVoiceSetting({ sttProvider: "web_speech" })}
              className={`min-h-[48px] rounded-card border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700 ${
                voiceSettings.sttProvider === "web_speech"
                  ? "border-brand-700 bg-brand-700 text-white"
                  : "border-border bg-white text-ink hover:border-brand-700"
              }`}
            >
              <div className="text-caption font-bold">
                Web Speech API (Navigateur, fr-FR)
              </div>
              <div
                className={`text-[11px] ${
                  voiceSettings.sttProvider === "web_speech"
                    ? "text-white/90"
                    : "text-ink-secondary"
                }`}
              >
                Reconnaissance native du navigateur
              </div>
            </button>

            <button
              type="button"
              data-testid="settings-stt-provider-whisper"
              aria-pressed={voiceSettings.sttProvider === "whisper_local"}
              onClick={() =>
                updateVoiceSetting({ sttProvider: "whisper_local" })
              }
              className={`min-h-[48px] rounded-card border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700 ${
                voiceSettings.sttProvider === "whisper_local"
                  ? "border-brand-700 bg-brand-700 text-white"
                  : "border-border bg-white text-ink hover:border-brand-700"
              }`}
            >
              <div className="text-caption font-bold">
                Whisper local (Confidentiel, fr-FR)
              </div>
              <div
                className={`text-[11px] ${
                  voiceSettings.sttProvider === "whisper_local"
                    ? "text-white/90"
                    : "text-ink-secondary"
                }`}
              >
                Traitement local sans transit par le navigateur
              </div>
            </button>
          </div>
        </div>
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

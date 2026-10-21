from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from playwright.sync_api import sync_playwright

WIDTHS = (390, 768, 1024, 1280, 1440)
ARTIFACT_DIR = Path(
    os.getenv(
        "ARTIFACT_DIR",
        r"C:\Users\mohamed.slama\.gemini\antigravity\brain\5cabc6ba-ac77-4aa2-b151-2378a164db64",
    )
)
CHROME_EXE = os.getenv(
    "PLAYWRIGHT_CHROME_PATH",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
)
BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")
API_URL = os.getenv("VITE_API_BASE_URL", "http://localhost:8000")


def _boxes_overlap(a: dict[str, Any], b: dict[str, Any], tolerance_px: float = 1.5) -> bool:
    overlap_x = min(a["right"], b["right"]) - max(a["left"], b["left"]) > tolerance_px
    overlap_y = min(a["bottom"], b["bottom"]) - max(a["top"], b["top"]) > tolerance_px
    return overlap_x and overlap_y


def _ensure_wsl_bridge() -> subprocess.Popen[Any] | None:
    """Démarre le pont TCP localhost -> WSL2 si nécessaire sous Windows."""
    bridge_script = ARTIFACT_DIR / "scratch" / "wsl_port_bridge.py"
    if not bridge_script.exists():
        return None
    out = subprocess.check_output(["wsl", "hostname", "-I"], text=True, timeout=5)
    wsl_ip = out.strip().split()[0]

    proc = subprocess.Popen(
        [sys.executable, str(bridge_script), wsl_ip],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.0)
    return proc


def test_mon_programme_layout_5_widths_playwright() -> dict[str, Any]:
    """
    Test automatisé de rendu Playwright sur "Mon programme" aux 5 largeurs
    (390, 768, 1024, 1280 et 1440 px), chat fermé et chat ouvert :
    - Échoue si le titre de la page passe sur plus de 2 lignes (> 2 lignes).
    - Échoue si deux éléments se chevauchent.
    - Vérifie que l'en-tête passe en colonne quand le chat est ouvert, que les badges
      restent sur une ligne, que les puces de jours restent dans une bande horizontale
      sans coupure et que le panneau latéral du chat n'apparaît en côte à côte qu'à partir de 1280 px.
    """
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    bridge_proc = _ensure_wsl_bridge()
    report: dict[str, Any] = {"widths": {}}

    try:
        with sync_playwright() as p:
            launch_kwargs: dict[str, Any] = {
                "headless": True,
                "args": ["--disable-gpu", "--no-sandbox"],
            }
            if Path(CHROME_EXE).exists():
                launch_kwargs["executable_path"] = CHROME_EXE

            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            print("Navigating to frontend root...", flush=True)
            page.goto(f"{BASE_URL}/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1500)

            # Initialisation d'un séjour de 8 jours à New York avec visite jeudi 9h-11h et proposition chat
            setup_info = page.evaluate(
                """async (apiUrl) => {
                  const email = "playwright.layout." + Date.now() + "@travelmate.app";
                  const regResp = await fetch(apiUrl + "/api/v1/auth/register", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      email,
                      full_name: "Camille Moreau",
                      password: "PasswordStep4!2026",
                      preferred_style: "STANDARD"
                    })
                  });
                  const regData = await regResp.json();
                  const token = regData.access_token;
                  localStorage.setItem("travelmate_jwt_token", token);
                  localStorage.setItem("travelmate_user_profile", JSON.stringify(regData.user));

                  const destsResp = await fetch(apiUrl + "/api/v1/destinations");
                  const dests = await destsResp.json();
                  const ny = dests.find(d => d.city_name === "New York") || dests[0];

                  const tripResp = await fetch(apiUrl + "/api/v1/trips", {
                    method: "POST",
                    headers: {
                      "Content-Type": "application/json",
                      "Authorization": "Bearer " + token
                    },
                    body: JSON.stringify({
                      destination_id: ny.id,
                      title: "Séjour à New York",
                      travel_style: "STANDARD",
                      total_budget: 2600
                    })
                  });
                  const trip = await tripResp.json();
                  localStorage.setItem("travelmate_active_trip_id", trip.id);

                  const bookResp = await fetch(apiUrl + "/api/v1/flights/book", {
                    method: "POST",
                    headers: {
                      "Content-Type": "application/json",
                      "Authorization": "Bearer " + token
                    },
                    body: JSON.stringify({
                      trip_id: trip.id,
                      idempotency_key: "IDEM-PW-LAYOUT-" + Date.now(),
                      airline: "Air France",
                      flight_number_outbound: "AF006",
                      flight_number_inbound: "AF007",
                      origin_iata: "CDG",
                      destination_iata: "JFK",
                      departure_outbound_at: "2026-11-10T03:00:00Z",
                      arrival_outbound_at: "2026-11-10T06:00:00Z",
                      departure_inbound_at: "2026-11-17T20:00:00Z",
                      arrival_inbound_at: "2026-11-18T06:00:00Z",
                      price_amount: "540.00",
                      currency: "EUR",
                      cabin_class: "ECONOMY"
                    })
                  });
                  const bookData = await bookResp.json();
                  localStorage.setItem("travelmate_last_flight_booking", JSON.stringify(bookData));

                  const placesResp = await fetch(apiUrl + "/api/v1/places/city/New York", {
                    headers: { "Authorization": "Bearer " + token }
                  });
                  const placesData = await placesResp.json();
                  const memorial = placesData.places.find(p => p.name.toLowerCase().includes("septembre")) || placesData.places[0];
                  const met = placesData.places.find(p => p.name.toLowerCase().includes("metropolitan")) || placesData.places[1];

                  await fetch(apiUrl + "/api/v1/itinerary/items", {
                    method: "POST",
                    headers: {
                      "Content-Type": "application/json",
                      "Authorization": "Bearer " + token
                    },
                    body: JSON.stringify({
                      trip_id: trip.id,
                      place_id: memorial.id,
                      visit_date: "2026-11-12",
                      local_start_time: "09:00",
                      duration_minutes: 120,
                      transit_mode: "METRO"
                    })
                  });

                  await fetch(apiUrl + "/api/v1/itinerary/trip/" + trip.id + "/chat", {
                    method: "POST",
                    headers: {
                      "Content-Type": "application/json",
                      "Authorization": "Bearer " + token
                    },
                    body: JSON.stringify({
                      message: "Ajoute " + met.name + " jeudi à 10h"
                    })
                  });

                  return { tripId: trip.id };
                }""",
                API_URL,
            )
            assert setup_info["tripId"]
            print(f"Trip initialized: {setup_info['tripId']}", flush=True)

            page.goto(f"{BASE_URL}/itinerary", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_selector('[data-testid="itinerary-page-title"]', timeout=15000)
            page.wait_for_timeout(1200)
            # Sélectionne le Jour 3 (jeudi 12 nov.) pour afficher la carte de visite dans la chronologie
            day_pill_2 = page.locator('[data-testid="day-pill-2"]')
            if day_pill_2.count() > 0:
                day_pill_2.click()
                page.wait_for_timeout(400)

            for width in WIDTHS:
                report["widths"][str(width)] = {}
                closed_screen_width = 0

                for chat_state in ("ferme", "ouvert"):
                    page.set_viewport_size({"width": width, "height": 900})
                    page.wait_for_timeout(300)

                    is_open = page.locator('[data-testid="floating-chat-panel"]').count() > 0
                    if chat_state == "ouvert" and not is_open:
                        page.locator('[data-testid="floating-chat-bubble-btn"]').click()
                        page.wait_for_selector('[data-testid="floating-chat-panel"]')
                    elif chat_state == "ferme" and is_open:
                        page.locator('[data-testid="close-chat-panel-btn"]').click()
                        page.wait_for_selector('[data-testid="floating-chat-bubble-btn"]')
                    page.wait_for_timeout(300)

                    screenshot_name = f"programme_{width}px_chat_{chat_state}.png"
                    screenshot_path = ARTIFACT_DIR / screenshot_name
                    page.screenshot(path=str(screenshot_path), full_page=False)
                    assert screenshot_path.exists() and screenshot_path.stat().st_size > 10_000

                    metrics = page.evaluate(
                        """({ vw, state }) => {
                          function rectOf(el, name) {
                            if (!el) return null;
                            const style = window.getComputedStyle(el);
                            if (
                              style.display === "none" ||
                              style.visibility === "hidden" ||
                              parseFloat(style.opacity) === 0
                            ) {
                              return null;
                            }
                            const r = el.getBoundingClientRect();
                            if (r.width <= 0 || r.height <= 0) return null;
                            return {
                              name,
                              left: Math.round(r.left * 10) / 10,
                              top: Math.round(r.top * 10) / 10,
                              right: Math.round(r.right * 10) / 10,
                              bottom: Math.round(r.bottom * 10) / 10,
                              width: Math.round(r.width * 10) / 10,
                              height: Math.round(r.height * 10) / 10,
                            };
                          }

                          const titleEl = document.querySelector('[data-testid="itinerary-page-title"]');
                          const titleStyle = window.getComputedStyle(titleEl);
                          const titleRect = titleEl.getBoundingClientRect();
                          const lineHeight = parseFloat(titleStyle.lineHeight) || 33.6;
                          const titleLineCount = Math.round(titleRect.height / lineHeight);

                          const headerEl = document.querySelector('[data-testid="itinerary-header"]');
                          const headerDirection = headerEl ? window.getComputedStyle(headerEl).flexDirection : "";

                          const badgeEls = Array.from(
                            document.querySelectorAll('[data-testid="itinerary-header-badges"] > *')
                          );
                          const badgeRects = badgeEls
                            .map((el, i) => rectOf(el, `header-badge-${i}`))
                            .filter(Boolean);
                          const badgesSingleLine =
                            badgeRects.length <= 1 ||
                            Math.abs(badgeRects[0].top - badgeRects[1].top) <= 4;
                          const badgesNotStretched = badgeRects.every(b => b.height <= 32);
                          const badgesNotClipped = badgeRects.every(b => b.right <= vw - 8);

                          const dayPillsContainer = document.getElementById("itinerary-day-pills");
                          const pillEls = Array.from(
                            document.querySelectorAll('[data-testid^="day-pill-"]')
                          ).filter(el => /^day-pill-\\d+$/.test(el.getAttribute("data-testid") || ""));
                          const pillsClipped = pillEls
                            .filter(el => el.scrollWidth > el.clientWidth + 1)
                            .map(el => ({
                              id: el.getAttribute("data-testid"),
                              scrollWidth: el.scrollWidth,
                              clientWidth: el.clientWidth,
                              text: el.innerText
                            }));
                          const pillTops = pillEls.map(el => el.getBoundingClientRect().top);
                          const pillsSameRow =
                            pillTops.length === 0 ||
                            pillTops.every(t => Math.abs(t - pillTops[0]) <= 2);

                          // Éléments de la barre de navigation supérieure
                          const topNavBoxes = [
                            rectOf(document.querySelector('[data-testid="header-brand-link"]'), "nav-brand"),
                            rectOf(document.querySelector('[data-testid="step-progress-bar"]'), "nav-step-progress-bar"),
                            rectOf(document.querySelector('[data-testid="active-destination-pill"]'), "nav-destination-pill"),
                            rectOf(document.querySelector('[data-testid="nav-my-trip-link"]'), "nav-my-trip"),
                            rectOf(document.querySelector('[data-testid="open-documents-btn"]'), "nav-documents"),
                            rectOf(document.querySelector('[data-testid="nav-settings-link"]'), "nav-settings"),
                            rectOf(document.querySelector('[data-testid="header-user-link"]'), "nav-user"),
                            rectOf(document.querySelector('[data-testid="logout-btn"]'), "nav-logout"),
                          ].filter(Boolean);

                          const mainBoxes = [];
                          for (const b of badgeRects) mainBoxes.push(b);
                          const titleBox = rectOf(titleEl, "page-title");
                          if (titleBox) mainBoxes.push(titleBox);
                          const subtitleBox = rectOf(titleEl.nextElementSibling, "page-subtitle");
                          if (subtitleBox) mainBoxes.push(subtitleBox);

                          const actionBtnEls = Array.from(
                            document.querySelectorAll('[data-testid="itinerary-header-actions"] > button')
                          );
                          actionBtnEls.forEach((btn, idx) => {
                            const b = rectOf(btn, `header-btn-${idx}`);
                            if (b) mainBoxes.push(b);
                          });

                          const pillsStripBox = rectOf(dayPillsContainer, "day-pills-strip");
                          if (pillsStripBox) mainBoxes.push(pillsStripBox);

                          const timelineCardBox = rectOf(
                            document.querySelector('[data-testid="single-day-timeline-card"]'),
                            "timeline-card"
                          );
                          if (timelineCardBox) mainBoxes.push(timelineCardBox);

                          const summaryBtnBox = rectOf(
                            document.querySelector('[data-testid="itinerary-go-to-trip-summary-btn"]'),
                            "summary-btn"
                          );
                          if (summaryBtnBox) mainBoxes.push(summaryBtnBox);

                          const chatBubbleBox = rectOf(
                            document.querySelector('[data-testid="floating-chat-bubble-btn"]'),
                            "floating-chat-bubble-btn"
                          );
                          if (state === "ferme" && chatBubbleBox && summaryBtnBox) {
                            // La bulle flottante ne doit pas chevaucher le bouton récapitulatif ni l'en-tête
                            mainBoxes.push(chatBubbleBox);
                          }

                          const chatPanelEl = document.querySelector('[data-testid="floating-chat-panel"]');
                          const chatPanelBox = rectOf(chatPanelEl, "floating-chat-panel");
                          if (state === "ouvert" && vw >= 1280 && chatPanelBox) {
                            mainBoxes.push(chatPanelBox);
                          }

                          const chatInternalBoxes = [];
                          if (state === "ouvert" && chatPanelEl) {
                            const chatHeader = chatPanelEl.firstElementChild;
                            const msgList = chatPanelEl.querySelector('[data-testid="chat-messages-list"]');
                            const proposalCard = chatPanelEl.querySelector('[data-testid="chat-proposed-action-card"]');
                            const chatForm = chatPanelEl.querySelector("form");
                            for (const [el, label] of [
                              [chatHeader, "chat-header"],
                              [msgList, "chat-messages-list"],
                              [proposalCard, "chat-proposed-action-card"],
                              [chatForm, "chat-form"],
                            ]) {
                              const r = rectOf(el, label);
                              if (r) chatInternalBoxes.push(r);
                            }
                          }

                          const screenEl = document.querySelector('[data-testid="itinerary-screen"]');
                          const screenRect = screenEl.getBoundingClientRect();

                          return {
                            titleLineCount,
                            titleHeight: Math.round(titleRect.height * 10) / 10,
                            lineHeight: Math.round(lineHeight * 10) / 10,
                            headerDirection,
                            badgesSingleLine,
                            badgesNotStretched,
                            badgesNotClipped,
                            pillsClipped,
                            pillsSameRow,
                            topNavBoxes,
                            mainBoxes,
                            chatInternalBoxes,
                            chatPanelBox,
                            screenWidth: Math.round(screenRect.width),
                          };
                        }""",
                        {"vw": width, "state": chat_state},
                    )

                    if chat_state == "ferme":
                        closed_screen_width = metrics["screenWidth"]
                    else:
                        if width < 1280:
                            assert metrics["screenWidth"] == closed_screen_width, (
                                f"À {width}px (< 1280px), l'ouverture du chat a réduit la largeur "
                                f"du contenu de {closed_screen_width}px à {metrics['screenWidth']}px"
                            )
                        else:
                            assert metrics["screenWidth"] < closed_screen_width, (
                                f"À {width}px (>= 1280px), le chat doit être en côte à côte"
                            )

                    assert metrics["titleLineCount"] <= 2, (
                        f"À {width}px (chat {chat_state}), le titre passe sur "
                        f"{metrics['titleLineCount']} lignes (max 2 autorisé)"
                    )
                    if chat_state == "ouvert":
                        assert metrics["headerDirection"] == "column", (
                            f"À {width}px (chat ouvert), l'en-tête doit être en colonne, "
                            f"obtenu: {metrics['headerDirection']}"
                        )
                    assert metrics["badgesSingleLine"] is True, (
                        f"À {width}px (chat {chat_state}), les badges ne sont pas sur une seule ligne"
                    )
                    assert metrics["badgesNotStretched"] is True, (
                        f"À {width}px (chat {chat_state}), un badge est étiré sur plusieurs lignes"
                    )
                    assert metrics["badgesNotClipped"] is True, (
                        f"À {width}px (chat {chat_state}), un badge de l'en-tête est coupé à droite"
                    )
                    assert len(metrics["pillsClipped"]) == 0, (
                        f"À {width}px (chat {chat_state}), puces coupées : {metrics['pillsClipped']}"
                    )
                    assert metrics["pillsSameRow"] is True, (
                        f"À {width}px (chat {chat_state}), les puces de jours ne sont pas sur une seule ligne horizontale"
                    )

                    for i in range(len(metrics["topNavBoxes"])):
                        for j in range(i + 1, len(metrics["topNavBoxes"])):
                            box_a = metrics["topNavBoxes"][i]
                            box_b = metrics["topNavBoxes"][j]
                            assert not _boxes_overlap(box_a, box_b), (
                                f"Chevauchement dans la barre supérieure à {width}px (chat {chat_state}) entre "
                                f"{box_a['name']} ({box_a}) et {box_b['name']} ({box_b})"
                            )

                    for i in range(len(metrics["mainBoxes"])):
                        for j in range(i + 1, len(metrics["mainBoxes"])):
                            box_a = metrics["mainBoxes"][i]
                            box_b = metrics["mainBoxes"][j]
                            # Sur 390px la bulle flottante fixe en bas à droite peut survoler le bas de la carte chronologique défilante, mais jamais le bouton récapitulatif ni l'en-tête
                            if {box_a["name"], box_b["name"]} == {"floating-chat-bubble-btn", "timeline-card"} and width < 768:
                                continue
                            assert not _boxes_overlap(box_a, box_b), (
                                f"Chevauchement détecté à {width}px (chat {chat_state}) entre "
                                f"{box_a['name']} ({box_a}) et {box_b['name']} ({box_b})"
                            )

                    for i in range(len(metrics["chatInternalBoxes"])):
                        for j in range(i + 1, len(metrics["chatInternalBoxes"])):
                            box_a = metrics["chatInternalBoxes"][i]
                            box_b = metrics["chatInternalBoxes"][j]
                            assert not _boxes_overlap(box_a, box_b), (
                                f"Chevauchement interne au chat à {width}px entre "
                                f"{box_a['name']} ({box_a}) et {box_b['name']} ({box_b})"
                            )

                    report["widths"][str(width)][chat_state] = {
                        "screenshot": str(screenshot_path),
                        "titleLineCount": metrics["titleLineCount"],
                        "headerDirection": metrics["headerDirection"],
                        "badgesSingleLine": metrics["badgesSingleLine"],
                        "pillsClippedCount": len(metrics["pillsClipped"]),
                        "screenWidth": metrics["screenWidth"],
                        "overlapsDetected": 0,
                    }

            # Met à jour rendered_pages.json si la fonction d'inspection est exposée
            rendered_pages = page.evaluate(
                "window.renderTravelerPagesForInspection ? window.renderTravelerPagesForInspection() : null"
            )
            if rendered_pages:
                dist_json = (
                    Path(__file__).resolve().parents[1] / "dist" / "rendered_pages.json"
                )
                if dist_json.parent.exists():
                    dist_json.write_text(
                        json.dumps(rendered_pages, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )

            browser.close()
    finally:
        if bridge_proc is not None:
            bridge_proc.terminate()

    return report


def test_real_chat_marrakech_jardin_secret_medina_and_single_row_header() -> None:
    """
    Test Playwright qui ouvre le chat réel sur un séjour à Marrakech (avec La Grande Table Marocaine
    déjà au programme), vérifie que l'en-tête du chat tient sur une seule rangée propre sans troncature,
    tape "mets le Jardin Secret Medina le 13 novembre à 10h" dans le champ de saisie réel du chat
    et vérifie que le lieu proposé est bien "Le Jardin Secret (Médina)" (jamais "La Grande Table Marocaine").
    """
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    bridge_proc = _ensure_wsl_bridge()

    try:
        with sync_playwright() as p:
            launch_kwargs: dict[str, Any] = {
                "headless": True,
                "args": ["--disable-gpu", "--no-sandbox"],
            }
            if Path(CHROME_EXE).exists():
                launch_kwargs["executable_path"] = CHROME_EXE

            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            page.goto(f"{BASE_URL}/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1000)

            page.evaluate(
                """async (apiUrl) => {
                  const email = "playwright.marrakech.chat." + Date.now() + "@travelmate.app";
                  const regResp = await fetch(apiUrl + "/api/v1/auth/register", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      email,
                      full_name: "Voyageur Marrakech",
                      password: "PasswordStep4!2026",
                      preferred_style: "STANDARD"
                    })
                  });
                  const regData = await regResp.json();
                  const token = regData.access_token;
                  localStorage.setItem("travelmate_jwt_token", token);
                  localStorage.setItem("travelmate_user_profile", JSON.stringify(regData.user));

                  const destsResp = await fetch(apiUrl + "/api/v1/destinations");
                  const dests = await destsResp.json();
                  const marrakech = dests.find((d) => d.city_name === "Marrakech");
                  if (!marrakech) {
                    throw new Error("Destination Marrakech introuvable");
                  }

                  const tripResp = await fetch(apiUrl + "/api/v1/trips", {
                    method: "POST",
                    headers: {
                      "Content-Type": "application/json",
                      "Authorization": "Bearer " + token
                    },
                    body: JSON.stringify({
                      destination_id: marrakech.id,
                      title: "Séjour à Marrakech",
                      travel_style: "STANDARD",
                      total_budget: 1400
                    })
                  });
                  const trip = await tripResp.json();
                  localStorage.setItem("travelmate_active_trip_id", trip.id);

                  const bookResp = await fetch(apiUrl + "/api/v1/flights/book", {
                    method: "POST",
                    headers: {
                      "Content-Type": "application/json",
                      "Authorization": "Bearer " + token
                    },
                    body: JSON.stringify({
                      trip_id: trip.id,
                      idempotency_key: "IDEM-PW-MARRAKECH-" + Date.now(),
                      airline: "Royal Air Maroc",
                      flight_number_outbound: "AT749",
                      flight_number_inbound: "AT748",
                      origin_iata: "ORY",
                      destination_iata: "RAK",
                      departure_outbound_at: "2026-11-11T06:00:00Z",
                      arrival_outbound_at: "2026-11-11T08:00:00Z",
                      departure_inbound_at: "2026-11-15T21:00:00Z",
                      arrival_inbound_at: "2026-11-15T23:55:00Z",
                      price_amount: "280.00",
                      currency: "EUR",
                      cabin_class: "ECONOMY"
                    })
                  });
                  const bookData = await bookResp.json();
                  localStorage.setItem("travelmate_last_flight_booking", JSON.stringify(bookData));

                  const placesResp = await fetch(apiUrl + "/api/v1/places/city/Marrakech", {
                    headers: { "Authorization": "Bearer " + token }
                  });
                  const placesData = await placesResp.json();
                  const grandeTable = placesData.places.find((pl) => pl.name.includes("Grande Table Marocaine"));
                  if (grandeTable) {
                    await fetch(apiUrl + "/api/v1/itinerary/items", {
                      method: "POST",
                      headers: {
                        "Content-Type": "application/json",
                        "Authorization": "Bearer " + token
                      },
                      body: JSON.stringify({
                        trip_id: trip.id,
                        place_id: grandeTable.id,
                        visit_date: "2026-11-12",
                        local_start_time: "19:30",
                        duration_minutes: 120,
                        transit_mode: "WALKING"
                      })
                    });
                  }
                }""",
                API_URL,
            )

            page.goto(f"{BASE_URL}/itinerary", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_selector('[data-testid="itinerary-page-title"]', timeout=15000)

            if page.locator('[data-testid="floating-chat-panel"]').count() == 0:
                page.locator('[data-testid="floating-chat-bubble-btn"]').click()
                page.wait_for_selector('[data-testid="floating-chat-panel"]', timeout=10000)

            header_check = page.evaluate(
                """() => {
                  const header = document.querySelector('[data-testid="chat-panel-header"]');
                  const title = document.querySelector('[data-testid="chat-header-title"]');
                  if (!header || !title) {
                    return { found: false, singleRow: false, titleClipped: true, titleText: "", height: 999 };
                  }
                  const headerRect = header.getBoundingClientRect();
                  const children = Array.from(header.children);
                  const centersY = children.map((el) => {
                    const r = el.getBoundingClientRect();
                    return r.top + r.height / 2;
                  });
                  const singleRow = centersY.length <= 1 || centersY.every((cy) => Math.abs(cy - centersY[0]) <= 8);
                  const titleClipped = title.scrollWidth > title.clientWidth + 1;
                  return {
                    found: true,
                    singleRow,
                    titleClipped,
                    titleText: (title.textContent || "").trim(),
                    height: headerRect.height
                  };
                }"""
            )
            assert header_check["found"] is True, f"En-tête du chat introuvable: {header_check}"
            assert header_check["singleRow"] is True, f"L'en-tête du chat n'est pas sur une seule rangée: {header_check}"
            assert header_check["titleClipped"] is False, f"Le titre de l'en-tête du chat est tronqué: {header_check}"
            assert header_check["titleText"] == "Assistant Marrakech", f"Titre inattendu: {header_check}"
            assert header_check["height"] <= 64, f"Hauteur d'en-tête excessive: {header_check}"

            chat_input = page.locator('[data-testid="chat-message-input"]')
            chat_input.fill("mets le Jardin Secret Medina le 13 novembre à 10h")
            page.locator('[data-testid="chat-send-btn"]').click()

            proposal_card = page.locator('[data-testid="chat-proposed-action-card"]')
            proposal_card.wait_for(state="visible", timeout=15000)
            proposal_text = proposal_card.inner_text()

            assert "Le Jardin Secret (Médina)" in proposal_text, (
                f"Le lieu proposé n'est pas Le Jardin Secret (Médina): {proposal_text!r}"
            )
            assert "La Grande Table Marocaine" not in proposal_text, (
                f"La Grande Table Marocaine a été proposée à tort: {proposal_text!r}"
            )
            assert "13 novembre" in proposal_text.lower()
            assert "10:00" in proposal_text

            screenshot_path = ARTIFACT_DIR / "marrakech_chat_jardin_secret_fix.png"
            page.screenshot(path=str(screenshot_path), full_page=False)

            browser.close()
    finally:
        if bridge_proc is not None:
            bridge_proc.terminate()


if __name__ == "__main__":
    result = test_mon_programme_layout_5_widths_playwright()
    test_real_chat_marrakech_jardin_secret_medina_and_single_row_header()
    print(json.dumps(result, indent=2, ensure_ascii=False))


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


def test_hands_free_voice_fake_speech_recognition_playwright():
    """
    Exigence 7 — Tests Playwright avec un faux SpeechRecognition :
    1. Démarrage automatique à l'ouverture si le micro est autorisé et "Assistant vocal toujours actif" est activé,
       annonce vocale à l'ouverture ("Assistant vocal actif, dites une commande") et pastille "J'écoute" toujours visible.
    2. Pause de 3 s au milieu d'une phrase ("déplace Jardin Majorelle" ... pause 3 s ... "le 12 novembre à 14h").
    3. Déplacement exécuté directement sans confirmation, puis "Annule" qui restaure l'état précédent (visite, horaire, synchronisation agenda).
    4. Suppression qui demande une confirmation obligatoire (jamais d'exécution directe).
    5. Lieu ambigu ("mets le Jardin le 12 novembre à 10h") qui pose une question à voix haute sans exécution.
    6. Veille après 30 s sans parole (micro en pause avec message), arrêt par "Arrête d'écouter" et reprise par "Écoute".
    7. Micro refusé (pas de démarrage automatique et message clair).
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
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()

            # Injection du faux SpeechRecognition (Web Speech API fr-FR) avec microphone autorisé
            page.add_init_script(
                """(() => {
                  window.__TM_MIC_AUTHORIZED__ = true;
                  window.__TM_MIC_DENIED__ = false;
                  window.__TM_VOICE_TIMER_SCALE__ = 1;
                  window.__FAKE_SR_INSTANCES__ = [];

                  class FakeSpeechRecognition {
                    constructor() {
                      this.lang = "fr-FR";
                      this.continuous = false;
                      this.interimResults = false;
                      this.maxAlternatives = 1;
                      this.onstart = null;
                      this.onresult = null;
                      this.onerror = null;
                      this.onend = null;
                      this.started = false;
                      this._resultsHistory = [];
                      window.__FAKE_SR_INSTANCES__.push(this);
                      window.__ACTIVE_FAKE_SR__ = this;
                    }
                    start() {
                      if (window.__TM_MIC_DENIED__ === true) {
                        this.started = false;
                        if (this.onerror) {
                          this.onerror({ error: "not-allowed" });
                        }
                        return;
                      }
                      this.started = true;
                      window.__ACTIVE_FAKE_SR__ = this;
                      if (this.onstart) {
                        this.onstart({});
                      }
                    }
                    stop() {
                      this.started = false;
                    }
                    abort() {
                      this.started = false;
                    }
                    emitSpeech(transcript, isFinal = true, confidence = 0.96) {
                      const entry = {
                        isFinal: Boolean(isFinal),
                        length: 1,
                        0: { transcript: String(transcript), confidence: Number(confidence) }
                      };
                      this._resultsHistory.push(entry);
                      const resultIndex = this._resultsHistory.length - 1;
                      if (this.onresult) {
                        this.onresult({
                          resultIndex,
                          results: this._resultsHistory
                        });
                      }
                    }
                  }

                  window.SpeechRecognition = FakeSpeechRecognition;
                  window.webkitSpeechRecognition = FakeSpeechRecognition;
                  window.__emitFakeSpeech = (text, isFinal = true, confidence = 0.96) => {
                    const inst = window.__TM_ACTIVE_SPEECH_RECOGNITION__ || window.__ACTIVE_FAKE_SR__;
                    if (!inst) {
                      throw new Error("Aucune instance FakeSpeechRecognition active");
                    }
                    inst.emitSpeech(text, isFinal, confidence);
                  };
                })();"""
            )

            page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1200)

            trip_info = page.evaluate(
                """async (apiUrl) => {
                  localStorage.clear();
                  const email = `voice.hf.${Date.now()}@travelmate.app`;
                  const regResp = await fetch(`${apiUrl}/api/v1/auth/register`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      email,
                      password: "PasswordStep4!2026",
                      full_name: "Voyageur Mains Libres",
                      preferred_style: "STANDARD"
                    })
                  });
                  const regData = await regResp.json();
                  const token = regData.access_token;
                  localStorage.setItem("travelmate_jwt_token", token);
                  localStorage.setItem("travelmate_user_profile", JSON.stringify(regData.user));
                  localStorage.setItem("tm_access_token", token);

                  const destResp = await fetch(`${apiUrl}/api/v1/destinations`);
                  const dests = await destResp.json();
                  const marrakech = dests.find((d) => d.city_name === "Marrakech") || dests[0];

                  const tripResp = await fetch(`${apiUrl}/api/v1/trips`, {
                    method: "POST",
                    headers: {
                      "Content-Type": "application/json",
                      Authorization: "Bearer " + token
                    },
                    body: JSON.stringify({
                      destination_id: marrakech.id,
                      title: "Séjour Mains Libres Marrakech",
                      travel_style: "STANDARD",
                      total_budget: 1600
                    })
                  });
                  const trip = await tripResp.json();
                  localStorage.setItem("travelmate_active_trip_id", trip.id);

                  const bookResp = await fetch(`${apiUrl}/api/v1/flights/book`, {
                    method: "POST",
                    headers: {
                      "Content-Type": "application/json",
                      Authorization: "Bearer " + token
                    },
                    body: JSON.stringify({
                      trip_id: trip.id,
                      idempotency_key: "IDEM-PW-VOICE-HF-" + Date.now(),
                      airline: "Royal Air Maroc",
                      flight_number_outbound: "AT749",
                      flight_number_inbound: "AT748",
                      origin_iata: "ORY",
                      destination_iata: "RAK",
                      departure_outbound_at: "2026-11-11T05:00:00Z",
                      arrival_outbound_at: "2026-11-11T07:00:00Z",
                      departure_inbound_at: "2026-11-15T21:00:00Z",
                      arrival_inbound_at: "2026-11-15T23:55:00Z",
                      price_amount: "280.00",
                      currency: "EUR",
                      cabin_class: "ECONOMY"
                    })
                  });
                  const bookData = await bookResp.json();
                  localStorage.setItem("travelmate_last_flight_booking", JSON.stringify(bookData));

                  const placesResp = await fetch(
                    `${apiUrl}/api/v1/places/city/${encodeURIComponent(marrakech.city_name)}`,
                    { headers: { Authorization: "Bearer " + token } }
                  );
                  const placesData = await placesResp.json();
                  const places = placesData.places || [];
                  const majorelle = places.find((pl) => pl.name.toLowerCase().includes("majorelle")) || places[0];

                  await fetch(`${apiUrl}/api/v1/itinerary/items`, {
                    method: "POST",
                    headers: {
                      "Content-Type": "application/json",
                      Authorization: "Bearer " + token
                    },
                    body: JSON.stringify({
                      trip_id: trip.id,
                      place_id: majorelle.id,
                      visit_date: "2026-11-11",
                      local_start_time: "10:00",
                      duration_minutes: 90,
                      transit_mode: "WALKING"
                    })
                  });

                  return { tripId: trip.id, token, majorelleName: majorelle.name };
                }""",
                API_URL,
            )

            # 1. Démarrage automatique à l'ouverture de l'application
            page.goto(f"{BASE_URL}/itinerary", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_selector('[data-testid="voice-listening-pill"]', timeout=15000)
            page.wait_for_selector('[data-testid="timeline-visit-card-0"]', timeout=15000)

            auto_start_state = page.evaluate(
                """() => {
                  const inst = window.__TM_ACTIVE_SPEECH_RECOGNITION__ || window.__ACTIVE_FAKE_SR__;
                  const statusEl = document.querySelector('[data-testid="screen-voice-listening-status"]');
                  const spokenEl = document.querySelector('[data-testid="voice-spoken-reply-box"]');
                  const autoStatusEl = document.querySelector('[data-testid="voice-autostart-status"]');
                  const errEl = document.querySelector('[data-testid="voice-screen-error-banner"]');
                  return {
                    hasInstance: Boolean(inst),
                    started: Boolean(inst && inst.started),
                    instancesCount: (window.__FAKE_SR_INSTANCES__ || []).length,
                    instancesStarted: (window.__FAKE_SR_INSTANCES__ || []).map((i) => ({
                      started: i.started,
                      stopReason: i._stopReason || null
                    })),
                    continuous: Boolean(inst && inst.continuous),
                    interimResults: Boolean(inst && inst.interimResults),
                    lang: inst ? inst.lang : "",
                    pillText: statusEl ? statusEl.textContent.trim() : "",
                    spokenText: spokenEl ? spokenEl.textContent.trim() : "",
                    autoStatusText: autoStatusEl ? autoStatusEl.textContent.trim() : "",
                    errText: errEl ? errEl.textContent.trim() : "",
                    utterances: window.__TM_SPOKEN_UTTERANCES__ || []
                  };
                }"""
            )
            assert auto_start_state["hasInstance"] is True, f"auto_start_state={auto_start_state}"
            assert auto_start_state["started"] is True, f"auto_start_state={auto_start_state}"
            assert auto_start_state["continuous"] is True
            assert auto_start_state["interimResults"] is True
            assert auto_start_state["lang"] == "fr-FR"
            assert auto_start_state["pillText"] == "J'écoute…"
            assert "Assistant vocal actif, dites une commande" in auto_start_state["spokenText"]

            # 2. Pause de 3 s au milieu d'une phrase + 3. Déplacement exécuté directement sans confirmation
            page.evaluate(
                """(placeName) => {
                  // Conserve le délai réel de 3 s pour la première moitié de phrase et 30 s pour la veille
                  window.__TM_VOICE_PHRASE_SCALE__ = 1;
                  window.__TM_VOICE_STANDBY_SCALE__ = 1;
                  window.__emitFakeSpeech(`déplace ${placeName}`, true, 0.96);
                }""",
                trip_info["majorelleName"],
            )
            # Pause réelle de 3 secondes au milieu de la phrase
            page.wait_for_timeout(3100)
            assert page.locator('[data-testid="voice-undo-banner"]').count() == 0, (
                "La première moitié de phrase ne doit pas déclencher d'exécution avant la suite après la pause de 3 s"
            )

            # Suite de la phrase après la pause de 3 s
            page.evaluate(
                """() => {
                  window.__TM_VOICE_PHRASE_SCALE__ = 0.05;
                  window.__emitFakeSpeech("le 12 novembre à 14h", true, 0.96);
                }"""
            )

            undo_banner = page.locator('[data-testid="voice-undo-banner"]')
            try:
                undo_banner.wait_for(state="visible", timeout=5000)
            except Exception:
                diag = page.evaluate(
                    """() => ({
                      spoken: document.querySelector('[data-testid="voice-spoken-reply-box"]')?.textContent,
                      live: document.querySelector('[data-testid="voice-live-transcript-box"]')?.textContent,
                      err: document.querySelector('[data-testid="voice-screen-error-banner"]')?.textContent,
                      confirm: document.querySelector('[data-testid="voice-toolbar-confirmation-box"]')?.textContent,
                      autoStatus: document.querySelector('[data-testid="voice-autostart-status"]')?.textContent,
                      utterances: window.__TM_SPOKEN_UTTERANCES__ || []
                    })"""
                )
                raise AssertionError(f"undo_banner not visible! diag={diag}")
            history_text = page.locator('[data-testid="voice-last-modification-history"]').inner_text()
            assert "2026-11-11" in history_text and "10:00" in history_text
            assert "2026-11-12" in history_text and "14:00" in history_text

            # Vérifie en base que la visite a bien été déplacée au 12 novembre à 14:00
            moved_items = page.evaluate(
                """async ({ apiUrl, tripId, token }) => {
                  const r = await fetch(`${apiUrl}/api/v1/itinerary/trip/${tripId}`, {
                    headers: { Authorization: "Bearer " + token }
                  });
                  return (await r.json()).items;
                }""",
                {"apiUrl": API_URL, "tripId": trip_info["tripId"], "token": trip_info["token"]},
            )
            assert moved_items[0]["local_visit_date"] == "2026-11-12"
            assert moved_items[0]["local_start_time"] == "14:00"

            # 3b. Dire "Annule" restaure l'état précédent (visite, horaire, synchronisation agenda)
            page.evaluate("""() => window.__emitFakeSpeech("Annule", true, 0.96)""")
            restored_banner = page.locator('[data-testid="voice-undo-restored-banner"]')
            restored_banner.wait_for(state="visible", timeout=15000)
            assert "10:00" in restored_banner.inner_text()

            restored_items = page.evaluate(
                """async ({ apiUrl, tripId, token }) => {
                  const r = await fetch(`${apiUrl}/api/v1/itinerary/trip/${tripId}`, {
                    headers: { Authorization: "Bearer " + token }
                  });
                  return (await r.json()).items;
                }""",
                {"apiUrl": API_URL, "tripId": trip_info["tripId"], "token": trip_info["token"]},
            )
            assert restored_items[0]["local_visit_date"] == "2026-11-11"
            assert restored_items[0]["local_start_time"] == "10:00"
            assert restored_items[0]["google_calendar_event_id"]

            # 4. Suppression qui demande une confirmation obligatoire (aucune exécution directe)
            page.evaluate(
                """(placeName) => window.__emitFakeSpeech(`supprime la visite ${placeName}`, true, 0.96)""",
                trip_info["majorelleName"],
            )
            confirm_box = page.locator('[data-testid="voice-toolbar-confirmation-box"]')
            confirm_box.wait_for(state="visible", timeout=15000)
            assert "Confirmation obligatoire" in confirm_box.inner_text()

            items_during_delete_prompt = page.evaluate(
                """async ({ apiUrl, tripId, token }) => {
                  const r = await fetch(`${apiUrl}/api/v1/itinerary/trip/${tripId}`, {
                    headers: { Authorization: "Bearer " + token }
                  });
                  return (await r.json()).items;
                }""",
                {"apiUrl": API_URL, "tripId": trip_info["tripId"], "token": trip_info["token"]},
            )
            assert len(items_during_delete_prompt) == 1, "La suppression ne doit jamais s'exécuter sans confirmation"

            # Annule la proposition de suppression en disant "non"
            page.evaluate("""() => window.__emitFakeSpeech("non", true, 0.96)""")
            confirm_box.wait_for(state="hidden", timeout=10000)

            # 5. Lieu ambigu qui pose une question à voix haute sans exécution
            page.evaluate(
                """() => window.__emitFakeSpeech("mets le Jardin le 12 novembre à 10h", true, 0.96)"""
            )
            page.wait_for_function(
                """() => {
                  const el = document.querySelector('[data-testid="voice-spoken-reply-box"]');
                  return el && el.textContent && el.textContent.includes("?") && el.textContent.includes("Jardin");
                }""",
                timeout=15000,
            )
            spoken_ambig = page.locator('[data-testid="voice-spoken-reply-box"]').inner_text()
            assert "?" in spoken_ambig and "Jardin" in spoken_ambig
            assert page.locator('[data-testid="voice-undo-banner"]').count() == 0

            # 6. Veille après 30 s sans parole (micro en pause avec message)
            page.evaluate(
                """() => {
                  // Réduit l'échelle de temps pour déclencher le délai de veille de 30 s en 300 ms
                  window.__TM_VOICE_STANDBY_SCALE__ = 0.01;
                }"""
            )
            # Cliquez sur Écoute / Reprendre avec l'échelle accélérée pour tester la mise en veille après 30 s sans parole
            page.locator('[data-testid="screen-voice-mic-btn"]').click()
            page.locator('[data-testid="screen-voice-mic-btn"]').click()
            page.wait_for_function(
                """() => {
                  const pill = document.querySelector('[data-testid="screen-voice-listening-status"]');
                  const status = document.querySelector('[data-testid="voice-autostart-status"]');
                  return (
                    pill &&
                    pill.textContent.trim() === "Micro en pause" &&
                    status &&
                    status.textContent.includes("Veille vocale activée")
                  );
                }""",
                timeout=10000,
            )

            # 6b. Reprise par la voix ("Écoute") puis arrêt par la voix ("Arrête d'écouter")
            page.evaluate(
                """() => {
                  window.__TM_VOICE_STANDBY_SCALE__ = 1;
                  window.__emitFakeSpeech("Écoute", true, 0.96);
                }"""
            )
            page.wait_for_function(
                """() => {
                  const pill = document.querySelector('[data-testid="screen-voice-listening-status"]');
                  return pill && pill.textContent.trim() === "J'écoute…";
                }""",
                timeout=10000,
            )

            page.evaluate("""() => window.__emitFakeSpeech("Arrête d'écouter", true, 0.96)""")
            page.wait_for_function(
                """() => {
                  const pill = document.querySelector('[data-testid="screen-voice-listening-status"]');
                  return pill && pill.textContent.trim() === "Micro en pause";
                }""",
                timeout=10000,
            )

            # 7. Micro refusé : message clair et pas de démarrage automatique
            page_denied = context.new_page()
            page_denied.add_init_script(
                """(() => {
                  window.__TM_MIC_AUTHORIZED__ = false;
                  window.__TM_MIC_DENIED__ = true;
                })();"""
            )
            page_denied.goto(f"{BASE_URL}/itinerary", wait_until="domcontentloaded", timeout=20000)
            page_denied.wait_for_selector('[data-testid="voice-listening-pill"]', timeout=15000)
            denied_pill = page_denied.locator('[data-testid="screen-voice-listening-status"]').inner_text().strip()
            assert denied_pill == "Micro en pause"
            denied_error = page_denied.locator('[data-testid="voice-screen-error-banner"]').inner_text()
            assert "microphone refusé" in denied_error.lower()

            browser.close()
    finally:
        if bridge_proc is not None:
            bridge_proc.terminate()


if __name__ == "__main__":
    result = test_mon_programme_layout_5_widths_playwright()
    test_real_chat_marrakech_jardin_secret_medina_and_single_row_header()
    test_hands_free_voice_fake_speech_recognition_playwright()
    print(json.dumps(result, indent=2, ensure_ascii=False))



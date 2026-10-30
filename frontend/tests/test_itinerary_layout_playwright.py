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
        r"C:\Users\mohamed.slama\.gemini\antigravity\brain\5cabc6ba-ac77-4aa2-b151-2378a164db64"
        if os.name == "nt"
        else "/tmp/travelmate_artifacts",
    )
)
CHROME_EXE = os.getenv(
    "PLAYWRIGHT_CHROME_PATH",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if os.name == "nt"
    else "/usr/bin/chromium",
)
BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")
API_URL = os.getenv("VITE_API_BASE_URL", "http://localhost:8000")


def _boxes_overlap(a: dict[str, Any], b: dict[str, Any], tolerance_px: float = 1.5) -> bool:
    overlap_x = min(a["right"], b["right"]) - max(a["left"], b["left"]) > tolerance_px
    overlap_y = min(a["bottom"], b["bottom"]) - max(a["top"], b["top"]) > tolerance_px
    return overlap_x and overlap_y


def _ensure_wsl_bridge() -> subprocess.Popen[Any] | None:
    """
    Sous Docker (Linux), redirige 127.0.0.1:5173 vers frontend:5173 pour que Chromium
    accède au frontend et au backend sur la même origine localhost.
    """
    if os.name != "nt":
        forwarder_code = (
            "import asyncio\n"
            "async def pipe(r, w):\n"
            "    try:\n"
            "        while d := await r.read(65536):\n"
            "            w.write(d); await w.drain()\n"
            "    except Exception: pass\n"
            "    finally:\n"
            "        try: w.close()\n"
            "        except Exception: pass\n"
            "async def handle(cr, cw):\n"
            "    try:\n"
            "        sr, sw = await asyncio.open_connection('frontend', 5173)\n"
            "        await asyncio.gather(pipe(cr, sw), pipe(sr, cw))\n"
            "    except Exception:\n"
            "        try: cw.close()\n"
            "        except Exception: pass\n"
            "async def main():\n"
            "    srv = await asyncio.start_server(handle, '127.0.0.1', 5173)\n"
            "    async with srv: await srv.serve_forever()\n"
            "asyncio.run(main())\n"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", forwarder_code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5)
        return proc

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


def test_mon_programme_layout_5_widths_playwright() -> None:
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

    assert "widths" in report
    assert set(report["widths"].keys()) == {"390", "768", "1024", "1280", "1440"}
    for w_key, w_metrics in report["widths"].items():
        assert "ferme" in w_metrics and "ouvert" in w_metrics, f"Largeur {w_key} incomplète : {w_metrics}"
        assert w_metrics["ferme"]["overlapsDetected"] == 0
        assert w_metrics["ouvert"]["overlapsDetected"] == 0
        assert w_metrics["ferme"]["pillsClippedCount"] == 0
        assert w_metrics["ouvert"]["pillsClippedCount"] == 0
        assert w_metrics["ferme"]["titleLineCount"] <= 2
        assert w_metrics["ouvert"]["titleLineCount"] <= 2


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
            page.wait_for_selector('[data-testid="popular-destinations-grid"]', timeout=15000)
            page.wait_for_timeout(500)

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
            page.wait_for_selector('[data-testid="timeline-visit-card-0"]', timeout=15000)

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


def test_world_cities_step1_geonames_search_create_and_fallback_playwright() -> None:
    """
    Vérifie dans Chromium (Docker) l'étape 1 des villes du monde :
    1. Le champ "Où allez-vous ?" de l'accueil utilise la recherche GeoNames après 300 ms et >= 3 lettres.
    2. Les 5 villes du seed restent proposées en destinations populaires.
    3. Une ville hors seed (ex: Lisbonne, geonameId=2267057, Europe/Lisbon) est créable sans doublon.
    4. Vols et hébergements restent simulés avec un message clair indiquant que la ville n'est pas couverte.
    5. La galerie de lieux affiche "Les lieux de cette ville arrivent bientôt" (aucune donnée inventée).
    6. Si GeoNames est injoignable / quota atteint / clé absente : message "Recherche de villes indisponible" et repli sur les 5 villes.
    """
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

            search_requests: list[str] = []
            simulate_unavailable = {"active": False}

            def handle_destinations_search(route: Any, request: Any) -> None:
                url = request.url
                search_requests.append(url)
                if simulate_unavailable["active"]:
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(
                            {
                                "query": "madrid",
                                "normalized_query": "madrid",
                                "available": False,
                                "fallback": True,
                                "quota_exceeded": True,
                                "reason": "hourly_quota_exceeded",
                                "message": "Recherche de villes indisponible : quota horaire GeoNames atteint (1000 requêtes/heure).",
                                "results": [],
                                "fallback_cities": [],
                            }
                        ),
                    )
                    return

                if "zzzinconnu" in url.lower():
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(
                            {
                                "query": "zzzinconnu",
                                "normalized_query": "zzzinconnu",
                                "available": True,
                                "fallback": False,
                                "cached": False,
                                "quota_exceeded": False,
                                "message": None,
                                "results": [],
                                "fallback_cities": [],
                            }
                        ),
                    )
                    return

                if "monastir" in url.lower():
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(
                            {
                                "query": "monastir",
                                "normalized_query": "monastir",
                                "available": True,
                                "fallback": False,
                                "cached": False,
                                "quota_exceeded": False,
                                "message": None,
                                "results": [
                                    {
                                        "geonameId": 2473493,
                                        "geoname_id": 2473493,
                                        "nom": "Monastir",
                                        "name": "Monastir",
                                        "city_name": "Monastir",
                                        "pays": "Tunisie",
                                        "country_name": "Tunisie",
                                        "code_pays": "TN",
                                        "country_code_iso2": "TN",
                                        "region": "Monastir",
                                        "region_name": "Monastir",
                                        "sous_titre": "Monastir • Tunisie",
                                        "coordonnees": {"latitude": 35.77799, "longitude": 10.82617},
                                        "fuseau_horaire": "Africa/Tunis",
                                        "timezone": "Africa/Tunis",
                                        "population": 104535,
                                        "iata_code": "MIR",
                                        "airport_within_100km": True,
                                        "airport_display_label": "Monastir (MIR)",
                                        "is_seed": False,
                                    }
                                ],
                                "fallback_cities": [],
                            }
                        ),
                    )
                    return

                if "springfield" in url.lower():
                    # 8 lignes pour vérifier que la liste (8 lignes max) passe par-dessus le bandeau photo
                    # et est entièrement visible et cliquable
                    eight_rows = [
                        {
                            "geonameId": 4409896 + idx,
                            "geoname_id": 4409896 + idx,
                            "nom": "Springfield",
                            "name": "Springfield",
                            "city_name": "Springfield",
                            "pays": "États-Unis" if idx < 7 else "Australie",
                            "country_name": "États-Unis" if idx < 7 else "Australie",
                            "code_pays": "US" if idx < 7 else "AU",
                            "country_code_iso2": "US" if idx < 7 else "AU",
                            "region": state_name,
                            "region_name": state_name,
                            "sous_titre": f"{state_name} • {'États-Unis' if idx < 7 else 'Australie'}",
                            "coordonnees": {"latitude": 37.2153, "longitude": -93.2982},
                            "fuseau_horaire": "America/Chicago",
                            "timezone": "America/Chicago",
                            "population": 170000 - idx * 15000,
                            "iata_code": "SGF",
                            "airport_within_100km": True,
                            "airport_display_label": "Springfield (SGF)",
                            "is_seed": False,
                        }
                        for idx, state_name in enumerate(
                            [
                                "Missouri",
                                "Massachusetts",
                                "Illinois",
                                "Ohio",
                                "Oregon",
                                "Virginie",
                                "Floride",
                                "Queensland",
                            ]
                        )
                    ]
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(
                            {
                                "query": "springfield",
                                "normalized_query": "springfield",
                                "available": True,
                                "fallback": False,
                                "cached": False,
                                "quota_exceeded": False,
                                "message": None,
                                "results": eight_rows,
                                "fallback_cities": [],
                            }
                        ),
                    )
                    return

                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "query": "lisbonne",
                            "normalized_query": "lisbonne",
                            "available": True,
                            "fallback": False,
                            "cached": False,
                            "quota_exceeded": False,
                            "message": None,
                            "results": [
                                {
                                    "geonameId": 2267057,
                                    "geoname_id": 2267057,
                                    "nom": "Lisbonne",
                                    "name": "Lisbonne",
                                    "city_name": "Lisbonne",
                                    "pays": "Portugal",
                                    "country_name": "Portugal",
                                    "code_pays": "PT",
                                    "country_code_iso2": "PT",
                                    "region": "Lisbonne",
                                    "region_name": "Lisbonne",
                                    "sous_titre": "Lisbonne • Portugal",
                                    "coordonnees": {"latitude": 38.71667, "longitude": -9.13333},
                                    "fuseau_horaire": "Europe/Lisbon",
                                    "timezone": "Europe/Lisbon",
                                    "population": 517802,
                                    "iata_code": "LIS",
                                    "airport_within_100km": True,
                                    "airport_display_label": "Lisbonne (LIS)",
                                    "is_seed": False,
                                }
                            ],
                            "fallback_cities": [],
                        }
                    ),
                )

            page.route("**/api/v1/destinations/search*", handle_destinations_search)

            page.goto(f"{BASE_URL}/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_selector('[data-testid="home-destination-input"]', timeout=15000)

            # Authentification pour permettre la création du séjour sur la ville hors seed
            page.evaluate(
                """async (apiUrl) => {
                  const email = "playwright.geonames." + Date.now() + "@travelmate.app";
                  const regResp = await fetch(apiUrl + "/api/v1/auth/register", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      email,
                      full_name: "Voyageur Monde",
                      password: "PasswordStep4!2026",
                      preferred_style: "STANDARD"
                    })
                  });
                  const regData = await regResp.json();
                  localStorage.setItem("travelmate_jwt_token", regData.access_token);
                  localStorage.setItem("travelmate_user_profile", JSON.stringify(regData.user));
                }""",
                API_URL,
            )
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector('[data-testid="popular-destinations-grid"]', timeout=15000)

            # 1. Vérifie que les 5 villes du seed sont proposées en destinations populaires
            popular_cards = page.locator('[data-testid="popular-destinations-grid"] > div').count()
            assert popular_cards == 5, f"Attendu 5 villes populaires du seed, obtenu {popular_cards}"

            # 2. Placeholder "Ville ou pays" et moins de 3 lettres ('li') -> mention d'aide, pas d'appel GeoNames
            dest_input = page.locator('[data-testid="home-destination-input"]')
            assert dest_input.get_attribute("placeholder") == "Ville ou pays"
            dest_input.fill("li")
            page.wait_for_selector('[data-testid="autocomplete-min-chars-hint"]', timeout=5000)
            hint_text = page.locator('[data-testid="autocomplete-min-chars-hint"]').inner_text()
            assert "Tapez au moins 3 lettres pour chercher dans le monde entier" in hint_text
            page.wait_for_timeout(380)
            assert len(search_requests) == 0

            # 2b. Aucune ville trouvée -> message "Aucune ville trouvée pour « zzzinconnu »"
            dest_input.fill("zzzinconnu")
            page.wait_for_selector('[data-testid="autocomplete-empty"]', timeout=10000)
            empty_msg = page.locator('[data-testid="autocomplete-empty"]').inner_text()
            assert "Aucune ville trouvée pour" in empty_msg
            assert "zzzinconnu" in empty_msg

            # 2c. Liste de 8 lignes ('springfield') : passe par-dessus le bandeau photo (overflow visible, z-index élevé),
            #     entièrement visible et cliquable
            dest_input.fill("springfield")
            page.wait_for_selector('[data-testid="home-autocomplete-list"] [role="option"]', timeout=10000)
            options_loc = page.locator('[data-testid="home-autocomplete-list"] [role="option"]')
            assert options_loc.count() == 8

            assert options_loc.nth(7).is_visible()
            visibility_check = page.evaluate(
                """() => {
                  const banner = document.querySelector('[data-testid="home-hero-banner"]');
                  const list = document.querySelector('[data-testid="home-autocomplete-list"]');
                  const options = Array.from(document.querySelectorAll('[data-testid="home-autocomplete-list"] [role="option"]'));
                  if (!banner || !list || options.length !== 8) return { ok: false, reason: "missing_elements" };
                  const bannerStyle = window.getComputedStyle(banner);
                  const listStyle = window.getComputedStyle(list);
                  const lastOpt = options[options.length - 1];
                  lastOpt.scrollIntoView({ block: "nearest" });
                  const rect = lastOpt.getBoundingClientRect();
                  const centerX = rect.left + rect.width / 2;
                  const centerY = rect.top + rect.height / 2;
                  const hitEl = document.elementFromPoint(centerX, centerY);
                  const hitInsideLastOpt = hitEl ? (lastOpt === hitEl || lastOpt.contains(hitEl)) : false;
                  return {
                    ok: true,
                    bannerOverflowX: bannerStyle.overflowX,
                    bannerOverflowY: bannerStyle.overflowY,
                    listZIndex: Number(listStyle.zIndex || 0),
                    lastOptHeight: rect.height,
                    hitInsideLastOpt,
                    listText: list.innerText,
                  };
                }"""
            )
            assert visibility_check["ok"] is True
            assert visibility_check["bannerOverflowX"] == "visible"
            assert visibility_check["bannerOverflowY"] == "visible"
            assert visibility_check["listZIndex"] >= 100
            assert visibility_check["lastOptHeight"] > 20
            assert visibility_check["hitInsideLastOpt"] is True, (
                f"La 8e ligne de la liste est rognée ou masquée : {visibility_check}"
            )
            assert "Missouri • États-Unis" in visibility_check["listText"]
            assert "Queensland • Australie" in visibility_check["listText"]
            assert "America/Chicago" not in visibility_check["listText"]

            # 3. Saisie >= 3 lettres ('lisbonne') -> affiche 'Lisbonne • Portugal' sans fuseau horaire
            dest_input.fill("lisbonne")
            page.wait_for_selector('[data-testid="autocomplete-city-lisbonne"]', timeout=10000)
            option_text = page.locator('[data-testid="autocomplete-city-lisbonne"]').inner_text()
            assert "Lisbonne" in option_text
            assert "Lisbonne • Portugal" in option_text
            assert "Europe/Lisbon" not in option_text
            assert "Africa/Casablanca" not in option_text
            assert "Asia/Makassar" not in option_text

            # 4. Sélection de Lisbonne et validation -> création de la destination et navigation vers /flights
            page.locator('[data-testid="autocomplete-city-lisbonne"]').click()
            page.locator('[data-testid="home-search-btn"]').click()

            # 5. Sur /flights : message "Nous n'avons pas encore de vols à afficher pour Lisbonne"
            #    (sans les mots "simulé", "simulation", "démonstration"), bouton principal
            #    "Comparer les vols <départ> → Lisbonne" + petit menu Google Flights / Kayak / Skyscanner
            #    avec codes aéroport et dates préremplis sans donnée personnelle, et actions secondaires.
            page.wait_for_selector('[data-testid="flights-empty-state"]', timeout=15000)
            flights_empty_text = page.locator('[data-testid="flights-empty-state"]').inner_text()
            assert "Nous n'avons pas encore de vols à afficher pour Lisbonne" in flights_empty_text
            for banned_word in ("simulé", "simulés", "simulation", "démonstration"):
                assert banned_word not in flights_empty_text.lower(), (
                    f"Mot interdit '{banned_word}' trouvé dans l'écran Vols : {flights_empty_text!r}"
                )

            primary_compare_btn = page.locator('[data-testid="flights-compare-primary-btn"]')
            assert primary_compare_btn.is_visible()
            assert "Comparer les vols Paris → Lisbonne" in primary_compare_btn.inner_text()
            assert primary_compare_btn.get_attribute("target") == "_blank"
            assert primary_compare_btn.get_attribute("rel") == "noopener noreferrer"

            origin_input = page.locator('[data-testid="flights-origin-input"]')
            dest_flight_input = page.locator('[data-testid="flights-destination-input"]')
            assert origin_input.is_visible()
            assert dest_flight_input.is_visible()

            origin_input.fill("monastir")
            page.wait_for_selector(
                '[data-testid="flights-origin-autocomplete-list"] [data-testid="autocomplete-city-monastir"]',
                timeout=10000,
            )
            monastir_opt_text = page.locator(
                '[data-testid="flights-origin-autocomplete-list"] [data-testid="autocomplete-city-monastir"]'
            ).inner_text()
            assert "Monastir • Tunisie" in monastir_opt_text
            assert "MIR" in monastir_opt_text
            assert "MON" not in monastir_opt_text
            assert "Africa/Tunis" not in monastir_opt_text
            page.locator(
                '[data-testid="flights-origin-autocomplete-list"] [data-testid="autocomplete-city-monastir"]'
            ).click()
            route_sub = page.locator('[data-testid="flights-route-subtitle"]').inner_text()
            assert "Monastir (MIR)" in route_sub

            # Après sélection de Monastir (MIR), le bouton principal et les 3 comparateurs utilisent MIR -> LIS
            assert "Comparer les vols Monastir → Lisbonne" in primary_compare_btn.inner_text()
            for comp_testid, expected_domain in (
                ("flights-compare-google", "google.com/travel/flights"),
                ("flights-compare-kayak", "kayak.fr/flights"),
                ("flights-compare-skyscanner", "skyscanner.fr/transport/vols"),
            ):
                comp_link = page.locator(f'[data-testid="{comp_testid}"]')
                assert comp_link.is_visible()
                assert comp_link.get_attribute("target") == "_blank"
                assert comp_link.get_attribute("rel") == "noopener noreferrer"
                href = comp_link.get_attribute("href") or ""
                assert expected_domain in href
                assert "mir" in href.lower()
                assert "lis" in href.lower()
                assert "2026-11-10" in href
                assert "2026-11-17" in href
                assert "playwright.geonames" not in href.lower()
                assert "voyageur" not in href.lower()

            # Actions secondaires de l'écran Vols
            assert "Continuer vers l'hébergement" in page.locator(
                '[data-testid="flights-continue-accommodations-btn"]'
            ).inner_text()
            assert "Voir les lieux de la ville" in page.locator(
                '[data-testid="flights-continue-activities-btn"]'
            ).inner_text()
            assert "Modifier ma recherche" in page.locator(
                '[data-testid="flights-modify-search-btn"]'
            ).inner_text()

            # 6. Navigation vers /accommodations : "Rechercher un hébergement à Lisbonne" avec Booking et Airbnb préremplis
            page.locator('[data-testid="flights-continue-accommodations-btn"]').click()
            page.wait_for_selector('[data-testid="accommodations-empty-state"]', timeout=15000)
            acc_empty_text = page.locator('[data-testid="accommodations-empty-state"]').inner_text()
            assert "Nous n'avons pas encore d'hébergements à afficher pour Lisbonne" in acc_empty_text
            for banned_word in ("simulé", "simulés", "simulation", "démonstration"):
                assert banned_word not in acc_empty_text.lower(), (
                    f"Mot interdit '{banned_word}' trouvé dans l'écran Hébergements : {acc_empty_text!r}"
                )

            acc_primary_btn = page.locator('[data-testid="accommodations-search-primary-btn"]')
            assert acc_primary_btn.is_visible()
            assert "Rechercher un hébergement à Lisbonne" in acc_primary_btn.inner_text()
            assert acc_primary_btn.get_attribute("target") == "_blank"
            assert acc_primary_btn.get_attribute("rel") == "noopener noreferrer"

            for acc_testid, expected_domain in (
                ("accommodations-compare-booking", "booking.com"),
                ("accommodations-compare-airbnb", "airbnb.fr"),
            ):
                acc_link = page.locator(f'[data-testid="{acc_testid}"]')
                assert acc_link.is_visible()
                assert acc_link.get_attribute("target") == "_blank"
                assert acc_link.get_attribute("rel") == "noopener noreferrer"
                href = acc_link.get_attribute("href") or ""
                assert expected_domain in href
                assert "lisbonne" in href.lower()
                assert "2026-11-10" in href
                assert "2026-11-17" in href
                assert "2" in href
                assert "playwright.geonames" not in href.lower()

            # 7. Navigation vers /activities (Étape 2) : vraie galerie Wikivoyage/Wikipédia avec
            #    illustration neutre par catégorie, "Photo bientôt disponible", attribution CC BY-SA 4.0
            #    cliquable et bandeau "Peu de lieux disponibles à Lisbonne pour l'instant" (< 5 lieux) + bouton 30 km
            def _handle_lisbonne_gallery(route: Any) -> None:
                url = route.request.url
                is_expanded = "radius_km=30" in url
                places_list = [
                    {
                        "id": "place-lis-belem",
                        "name": "Tour de Belém",
                        "category": "CULTURE",
                        "category_label": "Culture & Musées",
                        "description": "Tour fortifiée manuéline emblématique au bord du Tage.",
                        "latitude": 38.6916,
                        "longitude": -9.2160,
                        "is_outdoor": False,
                        "recommended_duration_min": 60,
                        "estimated_cost": 8.0,
                        "price_tier": "ECONOMIC",
                        "price_label": "8 €",
                        "avg_rating": 4.8,
                        "notoriety_score": 195.0,
                        "opening_hours": {"status": "confirmé", "display": "10:00-17:30", "mon": "10:00-17:30"},
                        "hours_status": "confirmé",
                        "hero_photos": [],
                        "photo_status": "Photo bientôt disponible",
                        "photo_checked": True,
                        "source_provider": "Wikivoyage",
                        "external_place_id": "wv:fr:Lisbonne:tour-de-belem",
                        "source_url": "https://fr.wikivoyage.org/wiki/Lisbonne",
                        "source_attribution": "Données Wikivoyage / Wikipédia (CC BY-SA 4.0)",
                        "already_in_itinerary": False,
                        "scheduled_slots": [],
                    },
                    {
                        "id": "place-lis-timeout",
                        "name": "Time Out Market Lisboa",
                        "category": "RESTAURANT",
                        "category_label": "Gastronomie",
                        "description": "Grand marché gourmand réunissant les chefs lisboètes.",
                        "latitude": 38.7072,
                        "longitude": -9.1459,
                        "is_outdoor": False,
                        "recommended_duration_min": 90,
                        "estimated_cost": 20.0,
                        "price_tier": "STANDARD",
                        "price_label": "non renseigné",
                        "avg_rating": 4.6,
                        "notoriety_score": 170.0,
                        "opening_hours": {"status": "horaires non confirmés", "display": "Tous les jours de 10h à minuit"},
                        "hours_status": "horaires non confirmés",
                        "hero_photos": [],
                        "photo_status": "Photo bientôt disponible",
                        "photo_checked": True,
                        "source_provider": "Wikivoyage",
                        "external_place_id": "wv:fr:Lisbonne:time-out-market",
                        "source_url": "https://fr.wikivoyage.org/wiki/Lisbonne",
                        "source_attribution": "Données Wikivoyage / Wikipédia (CC BY-SA 4.0)",
                        "already_in_itinerary": False,
                        "scheduled_slots": [],
                    },
                ]
                if is_expanded:
                    places_list.extend(
                        [
                            {
                                "id": f"place-lis-extra-{idx}",
                                "name": f"Palais de Sintra {idx}",
                                "category": "CULTURE",
                                "category_label": "Culture & Musées",
                                "description": "Palais historique dans la région de Lisbonne.",
                                "latitude": 38.7876,
                                "longitude": -9.3906,
                                "is_outdoor": False,
                                "recommended_duration_min": 120,
                                "estimated_cost": 14.0,
                                "price_tier": "STANDARD",
                                "price_label": "14 €",
                                "avg_rating": 4.7,
                                "notoriety_score": 160.0 - idx,
                                "opening_hours": {"status": "non renseigné", "display": "non renseigné"},
                                "hours_status": "non renseigné",
                                "hero_photos": [],
                                "photo_status": "Photo bientôt disponible",
                                "photo_checked": True,
                                "source_provider": "Wikipedia",
                                "external_place_id": f"wp:fr:sintra-{idx}",
                                "source_url": "https://fr.wikipedia.org/wiki/Palais_national_de_Sintra",
                                "source_attribution": "Données Wikivoyage / Wikipédia (CC BY-SA 4.0)",
                                "already_in_itinerary": False,
                                "scheduled_slots": [],
                            }
                            for idx in range(1, 5)
                        ]
                    )
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "trip_id": "trip-lisbonne",
                            "destination_id": "dest-lisbonne",
                            "city_name": "Lisbonne",
                            "country_name": "Portugal",
                            "destination_timezone": "Europe/Lisbon",
                            "currency": "EUR",
                            "unlocked": True,
                            "unlock_message": "Galerie déverrouillée",
                            "provider_mode": "wikivoyage_wikipedia",
                            "cached_in_redis": True,
                            "selected_place_ids": [],
                            "total_places": len(places_list),
                            "places_coming_soon": False,
                            "places_unavailable": False,
                            "places_message": None,
                            "few_places_message": (
                                None
                                if len(places_list) >= 5
                                else "Peu de lieux disponibles à Lisbonne pour l'instant"
                            ),
                            "can_expand_radius": len(places_list) < 5,
                            "current_radius_km": 30 if is_expanded else 10,
                            "suggested_radius_km": 30,
                            "categories_available": ["ALL", "CULTURE", "RESTAURANT"],
                            "places": places_list,
                        }
                    ),
                )

            page.route("**/api/v1/places/trip/*/gallery*", _handle_lisbonne_gallery)
            page.locator('[data-testid="accommodations-continue-activities-btn"]').click()
            page.wait_for_selector('[data-testid="activities-photo-grid"]', timeout=15000)
            page.wait_for_selector('[data-testid="place-photo-placeholder-0"]', timeout=15000)
            assert page.locator('[data-testid="places-coming-soon-card"]').count() == 0
            assert page.locator('[data-testid^="place-photo-placeholder-"]').count() == 2

            placeholder_0 = page.locator('[data-testid="place-photo-placeholder-0"]')
            assert placeholder_0.is_visible()
            assert "Photo bientôt disponible" in placeholder_0.inner_text()

            attr_link_0 = page.locator('[data-testid="place-attribution-link-0"]')
            assert attr_link_0.is_visible()
            assert "Données Wikivoyage / Wikipédia (CC BY-SA 4.0)" in attr_link_0.inner_text()
            assert attr_link_0.get_attribute("href") == "https://fr.wikivoyage.org/wiki/Lisbonne"

            few_banner = page.locator('[data-testid="few-places-banner"]')
            assert few_banner.is_visible()
            assert "Peu de lieux disponibles à Lisbonne pour l'instant" in few_banner.inner_text()
            expand_btn = page.locator('[data-testid="expand-radius-30km-btn"]')
            assert expand_btn.is_visible()
            expand_btn.click()
            page.wait_for_function(
                "() => document.querySelectorAll('[data-testid^=\"place-photo-placeholder-\"]').length === 6",
                timeout=10000,
            )

            # 8. Retour à l'accueil : les 5 villes du seed restent seules dans les destinations populaires,
            #    et si GeoNames est indisponible / quota atteint, message "Recherche de villes indisponible" + repli
            simulate_unavailable["active"] = True
            page.goto(f"{BASE_URL}/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_selector('[data-testid="popular-destinations-grid"]', timeout=15000)
            assert page.locator('[data-testid="popular-destinations-grid"] > div').count() == 5

            page.locator('[data-testid="home-destination-input"]').fill("madrid")
            page.wait_for_selector('[data-testid="geonames-unavailable-banner"]', timeout=10000)
            banner_text = page.locator('[data-testid="geonames-unavailable-banner"]').inner_text()
            assert "Recherche de villes indisponible" in banner_text
            assert page.locator('[data-testid^="geonames-fallback-dest-"]').count() == 5

            browser.close()
    finally:
        if bridge_proc is not None:
            bridge_proc.terminate()


def test_home_barcelone_geonames_autocomplete_visible_clickable_no_timezone_playwright() -> None:
    """
    Point 3 — Test Playwright dédié de l'accueil :
    Saisie de "barcelone" (fausse réponse GeoNames), liste entièrement visible au-dessus du bandeau photo,
    cliquable, sans aucun fuseau horaire affiché.
    """
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

            def handle_barcelone_search(route: Any, request: Any) -> None:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "query": "barcelone",
                            "normalized_query": "barcelone",
                            "available": True,
                            "fallback": False,
                            "cached": False,
                            "quota_exceeded": False,
                            "message": None,
                            "results": [
                                {
                                    "geonameId": 3128760,
                                    "geoname_id": 3128760,
                                    "nom": "Barcelone",
                                    "name": "Barcelone",
                                    "city_name": "Barcelone",
                                    "pays": "Espagne",
                                    "country_name": "Espagne",
                                    "code_pays": "ES",
                                    "country_code_iso2": "ES",
                                    "region": "Catalogne",
                                    "region_name": "Catalogne",
                                    "sous_titre": "Catalogne • Espagne",
                                    "coordonnees": {"latitude": 41.38879, "longitude": 2.15899},
                                    "fuseau_horaire": "Europe/Madrid",
                                    "timezone": "Europe/Madrid",
                                    "population": 1620343,
                                    "iata_code": "BCN",
                                    "airport_within_100km": True,
                                    "airport_display_label": "Barcelone (BCN)",
                                    "is_seed": False,
                                },
                                {
                                    "geonameId": 3648559,
                                    "geoname_id": 3648559,
                                    "nom": "Barcelona",
                                    "name": "Barcelona",
                                    "city_name": "Barcelona",
                                    "pays": "Venezuela",
                                    "country_name": "Venezuela",
                                    "code_pays": "VE",
                                    "country_code_iso2": "VE",
                                    "region": "Anzoátegui",
                                    "region_name": "Anzoátegui",
                                    "sous_titre": "Anzoátegui • Venezuela",
                                    "coordonnees": {"latitude": 10.13625, "longitude": -64.68618},
                                    "fuseau_horaire": "America/Caracas",
                                    "timezone": "America/Caracas",
                                    "population": 424795,
                                    "iata_code": "BLA",
                                    "airport_within_100km": True,
                                    "airport_display_label": "Barcelona (BLA)",
                                    "is_seed": False,
                                },
                                {
                                    "geonameId": 2525362,
                                    "geoname_id": 2525362,
                                    "nom": "Barcellona Pozzo di Gotto",
                                    "name": "Barcellona Pozzo di Gotto",
                                    "city_name": "Barcellona Pozzo di Gotto",
                                    "pays": "Italie",
                                    "country_name": "Italie",
                                    "code_pays": "IT",
                                    "country_code_iso2": "IT",
                                    "region": "Sicile",
                                    "region_name": "Sicile",
                                    "sous_titre": "Sicile • Italie",
                                    "coordonnees": {"latitude": 38.1481, "longitude": 15.2148},
                                    "fuseau_horaire": "Europe/Rome",
                                    "timezone": "Europe/Rome",
                                    "population": 41569,
                                    "iata_code": "CTA",
                                    "airport_within_100km": True,
                                    "airport_display_label": "Catane (CTA)",
                                    "is_seed": False,
                                },
                            ],
                            "fallback_cities": [],
                        }
                    ),
                )

            page.route("**/api/v1/destinations/search*", handle_barcelone_search)

            page.goto(f"{BASE_URL}/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_selector('[data-testid="home-destination-input"]', timeout=15000)

            dest_input = page.locator('[data-testid="home-destination-input"]')
            dest_input.fill("barcelone")

            page.wait_for_selector('[data-testid="home-autocomplete-list"] [role="option"]', timeout=10000)
            options = page.locator('[data-testid="home-autocomplete-list"] [role="option"]')
            assert options.count() == 3

            # Vérifie que toute la liste est entièrement visible au-dessus du bandeau photo et non rognée
            barcelone_layout = page.evaluate(
                """() => {
                  const banner = document.querySelector('[data-testid="home-hero-banner"]');
                  const list = document.querySelector('[data-testid="home-autocomplete-list"]');
                  const opts = Array.from(document.querySelectorAll('[data-testid="home-autocomplete-list"] [role="option"]'));
                  if (!banner || !list || opts.length === 0) {
                    return { ok: false, reason: "missing_dom" };
                  }
                  const bannerStyle = window.getComputedStyle(banner);
                  const listStyle = window.getComputedStyle(list);
                  const listRect = list.getBoundingClientRect();
                  const bannerRect = banner.getBoundingClientRect();
                  const allClickable = opts.every((opt) => {
                    const r = opt.getBoundingClientRect();
                    const cx = r.left + r.width / 2;
                    const cy = r.top + r.height / 2;
                    const hit = document.elementFromPoint(cx, cy);
                    return r.width > 100 && r.height > 24 && Boolean(hit && (hit === opt || opt.contains(hit)));
                  });
                  return {
                    ok: true,
                    bannerOverflowX: bannerStyle.overflowX,
                    bannerOverflowY: bannerStyle.overflowY,
                    listZIndex: Number(listStyle.zIndex || 0),
                    allClickable,
                    extendsBelowBannerOrVisible: listRect.bottom > bannerRect.top && listRect.height > 100,
                    listText: list.innerText,
                    pageText: document.body.innerText,
                  };
                }"""
            )
            assert barcelone_layout["ok"] is True
            assert barcelone_layout["bannerOverflowX"] == "visible"
            assert barcelone_layout["bannerOverflowY"] == "visible"
            assert barcelone_layout["listZIndex"] >= 100
            assert barcelone_layout["allClickable"] is True, (
                f"Les options d'autocomplétion de 'barcelone' ne sont pas toutes visibles/cliquables : {barcelone_layout}"
            )
            assert "Barcelone" in barcelone_layout["listText"]
            assert "Catalogne • Espagne" in barcelone_layout["listText"]
            assert "BCN" in barcelone_layout["listText"]

            # Aucun fuseau horaire affiché dans la liste ni sur l'écran d'accueil
            for tz in ("Europe/Madrid", "America/Caracas", "Europe/Rome", "Africa/Casablanca", "Asia/Makassar"):
                assert tz not in barcelone_layout["listText"], f"Fuseau horaire {tz} affiché dans la liste !"
                assert tz not in barcelone_layout["pageText"], f"Fuseau horaire {tz} affiché sur la page !"

            # Cliquable : le clic sur Barcelone remplit le champ avec "Barcelone"
            page.locator('[data-testid="autocomplete-city-barcelone"]').click()
            assert dest_input.input_value() == "Barcelone"

            browser.close()
    finally:
        if bridge_proc is not None:
            bridge_proc.terminate()


def test_world_places_step3_photos_visible_credit_and_no_layout_shift_playwright() -> None:
    """
    Étape 3 — Test Playwright dans Docker :
    - Affichage initial non bloquant de la galerie avec illustration neutre et dimensions 16/9 réservées
    - Enrichissement asynchrone en arrière-plan (POST /api/v1/places/trip/{id}/photos/enrich)
    - Image 16/9 visible (vignette ~800 px, lazy loading), crédit 'Photo : <auteur>, <licence>'
      affiché sous la photo avec lien vers la page Commons
    - Aucun saut de mise en page (dimensions de la boîte média, de la bande de crédit et de la carte
      strictement identiques avant et après le chargement de la photo)
    - Aperçu plein écran avec les mêmes crédits Commons
    - Lieu sans photo : illustration neutre existante et 'Photo bientôt disponible', jamais la photo d'un autre lieu.
    """
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

            # Image 800x450 encodée en SVG data URI pour un rendu instantané et déterministe dans Chromium sans dépendance réseau externe
            svg_800x450 = (
                "data:image/svg+xml;utf8,"
                "<svg xmlns='http://www.w3.org/2000/svg' width='800' height='450' viewBox='0 0 800 450'>"
                "<rect width='800' height='450' fill='%232c5e4f'/>"
                "<text x='400' y='225' fill='white' font-size='28' text-anchor='middle'>Castelo de Sao Jorge 800x450</text>"
                "</svg>"
            )

            base_places = [
                {
                    "id": "place-step3-castelo",
                    "destination_id": "dest-lisbonne-step3",
                    "city_name": "Lisbonne",
                    "name": "Castelo de São Jorge",
                    "description": "Château historique surplombant les toits de l'Alfama à Lisbonne.",
                    "category": "CULTURE",
                    "is_outdoor": True,
                    "latitude": 38.7139,
                    "longitude": -9.1334,
                    "recommended_duration_min": 90,
                    "estimated_cost": "15.00",
                    "price_tier": "STANDARD",
                    "avg_rating": 4.8,
                    "opening_hours": {"status": "confirmé", "display": "09:00-21:00"},
                    "hero_photos": [],
                    "photo_status": "Photo bientôt disponible",
                    "photo_file_title": None,
                    "photo_author": None,
                    "photo_license": None,
                    "photo_commons_url": None,
                    "photo_source": None,
                    "photo_credit_text": None,
                    "photo_checked": False,
                    "source_provider": "wikivoyage",
                    "external_place_id": "wikivoyage:fr:lisbonne:castelo",
                    "price_label": "15 €",
                    "hours_status": "confirmé",
                    "source_url": "https://fr.wikivoyage.org/wiki/Lisbonne",
                    "source_attribution": "Données Wikivoyage / Wikipédia (CC BY-SA 4.0)",
                    "notoriety_score": 195,
                    "is_wishlisted": False,
                    "is_selected_for_trip": False,
                },
                {
                    "id": "place-step3-no-photo",
                    "destination_id": "dest-lisbonne-step3",
                    "city_name": "Lisbonne",
                    "name": "Belvédère Secret de l'Alfama",
                    "description": "Petite terrasse calme sans photo sur Wikimedia.",
                    "category": "NATURE",
                    "is_outdoor": True,
                    "latitude": 38.7120,
                    "longitude": -9.1300,
                    "recommended_duration_min": 60,
                    "estimated_cost": "0.00",
                    "price_tier": "ECONOMIC",
                    "avg_rating": 4.6,
                    "opening_hours": {"status": "horaires non renseignés", "display": "non renseigné"},
                    "hero_photos": [],
                    "photo_status": "Photo bientôt disponible",
                    "photo_file_title": None,
                    "photo_author": None,
                    "photo_license": None,
                    "photo_commons_url": None,
                    "photo_source": None,
                    "photo_credit_text": None,
                    "photo_checked": False,
                    "source_provider": "wikivoyage",
                    "external_place_id": "wikivoyage:fr:lisbonne:belvedere",
                    "price_label": "non renseigné",
                    "hours_status": "horaires non renseignés",
                    "source_url": "https://fr.wikivoyage.org/wiki/Lisbonne",
                    "source_attribution": "Données Wikivoyage / Wikipédia (CC BY-SA 4.0)",
                    "notoriety_score": 120,
                    "is_wishlisted": False,
                    "is_selected_for_trip": False,
                },
            ]

            enrich_gate = {"allow": False}

            def _handle_gallery(route: Any) -> None:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "trip_id": "trip-lisbonne-step3",
                            "city_name": "Lisbonne",
                            "unlocked": True,
                            "unlock_message": "Découvrez les lieux incontournables à visiter à Lisbonne.",
                            "provider_mode": "wikivoyage_wikipedia",
                            "cached_in_redis": True,
                            "few_places_message": None,
                            "can_expand_radius": False,
                            "suggested_radius_km": None,
                            "radius_km": 10,
                            "outage_message": None,
                            "selected_place_ids": [],
                            "places": base_places,
                        }
                    ),
                )

            def _handle_enrich(route: Any) -> None:
                enriched_places = [
                    {
                        **base_places[0],
                        "hero_photos": [svg_800x450],
                        "photo_status": "Photo disponible",
                        "photo_file_title": "File:Castelo_Sao_Jorge_Lisboa.jpg",
                        "photo_author": "Alves Gaspar",
                        "photo_license": "CC BY-SA 4.0",
                        "photo_commons_url": "https://commons.wikimedia.org/wiki/File:Castelo_Sao_Jorge_Lisboa.jpg",
                        "photo_source": "wikidata_p18",
                        "photo_credit_text": "Photo : Alves Gaspar, CC BY-SA 4.0",
                        "photo_checked": True,
                    },
                    {
                        **base_places[1],
                        "hero_photos": [],
                        "photo_status": "Photo bientôt disponible",
                        "photo_source": "none",
                        "photo_checked": True,
                    },
                ]
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "trip_id": "trip-lisbonne-step3",
                            "city_name": "Lisbonne",
                            "unlocked": True,
                            "unlock_message": "Découvrez les lieux incontournables à visiter à Lisbonne.",
                            "provider_mode": "wikivoyage_wikipedia",
                            "cached_in_redis": True,
                            "few_places_message": None,
                            "can_expand_radius": False,
                            "suggested_radius_km": None,
                            "radius_km": 10,
                            "outage_message": None,
                            "selected_place_ids": [],
                            "places": enriched_places,
                        }
                    ),
                )

            page.add_init_script(
                """
                window.__TM_ALLOW_PHOTO_ENRICH__ = false;
                const origFetch = window.fetch.bind(window);
                window.fetch = async (...args) => {
                  const url = String(args[0] || "");
                  if (url.includes("/photos/enrich")) {
                    while (!window.__TM_ALLOW_PHOTO_ENRICH__) {
                      await new Promise((r) => setTimeout(r, 25));
                    }
                  }
                  return origFetch(...args);
                };
                """
            )
            page.route("**/api/v1/places/trip/*/gallery*", _handle_gallery)
            page.route("**/api/v1/places/trip/*/photos/enrich*", _handle_enrich)

            page.goto(f"{BASE_URL}/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_selector('[data-testid="popular-destinations-grid"]', timeout=15000)

            # Création d'un compte et d'un voyage vers Lisbonne
            page.evaluate(
                """async (apiUrl) => {
                  const email = "playwright.step3.photos." + Date.now() + "@travelmate.app";
                  const regResp = await fetch(apiUrl + "/api/v1/auth/register", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      email,
                      full_name: "Voyageur Photos Step3",
                      password: "PasswordStep3!2026",
                      preferred_style: "STANDARD"
                    })
                  });
                  const regData = await regResp.json();
                  const token = regData.access_token;
                  localStorage.setItem("travelmate_jwt_token", token);
                  localStorage.setItem("travelmate_user_profile", JSON.stringify(regData.user));

                  const tripResp = await fetch(apiUrl + "/api/v1/trips", {
                    method: "POST",
                    headers: {
                      "Content-Type": "application/json",
                      "Authorization": "Bearer " + token
                    },
                    body: JSON.stringify({
                      destination_city: "Lisbonne",
                      destination_country: "Portugal",
                      country_code_iso2: "PT",
                      latitude: 38.71667,
                      longitude: -9.13333,
                      timezone: "Europe/Lisbon",
                      geoname_id: 2267057,
                      population: 517802,
                      iata_code: "LIS",
                      title: "Séjour Lisbonne Photos",
                      travel_style: "STANDARD",
                      total_budget: 1400,
                      start_date: "2026-11-10",
                      end_date: "2026-11-15"
                    })
                  });
                  const trip = await tripResp.json();
                  localStorage.setItem("travelmate_active_trip_id", trip.id);
                }""",
                API_URL,
            )

            page.goto(f"{BASE_URL}/activities", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_selector('[data-testid="activity-card-0"]', timeout=15000)
            page.wait_for_selector('[data-testid="place-photo-placeholder-0"]', timeout=10000)

            # Mesure géométrique AVANT l'arrivée de la photo (pendant l'illustration neutre)
            before_metrics = page.evaluate(
                """() => {
                  const card0 = document.querySelector('[data-testid="activity-card-0"]');
                  const media0 = document.querySelector('[data-testid="place-media-box-0"]');
                  const credit0 = document.querySelector('[data-testid="place-photo-credit-0"]');
                  const card1 = document.querySelector('[data-testid="activity-card-1"]');
                  if (!card0 || !media0 || !credit0 || !card1) return null;
                  const rCard0 = card0.getBoundingClientRect();
                  const rMedia0 = media0.getBoundingClientRect();
                  const rCredit0 = credit0.getBoundingClientRect();
                  const rCard1 = card1.getBoundingClientRect();
                  return {
                    card0Height: rCard0.height,
                    card0Top: rCard0.top,
                    media0Width: rMedia0.width,
                    media0Height: rMedia0.height,
                    credit0Height: rCredit0.height,
                    card1Top: rCard1.top,
                    card1Left: rCard1.left,
                  };
                }"""
            )
            assert before_metrics is not None
            # Ratio 16/9 réservé dès le départ
            assert abs((before_metrics["media0Width"] / before_metrics["media0Height"]) - (16.0 / 9.0)) < 0.05

            # Débloque la réponse d'enrichissement des photos en arrière-plan
            page.evaluate("window.__TM_ALLOW_PHOTO_ENRICH__ = true")

            # Attend que la photo de Castelo de São Jorge s'affiche
            page.wait_for_selector('[data-testid="place-photo-img-0"]', timeout=10000)

            after_metrics = page.evaluate(
                """() => {
                  const card0 = document.querySelector('[data-testid="activity-card-0"]');
                  const media0 = document.querySelector('[data-testid="place-media-box-0"]');
                  const credit0 = document.querySelector('[data-testid="place-photo-credit-0"]');
                  const img0 = document.querySelector('[data-testid="place-photo-img-0"]');
                  const link0 = document.querySelector('[data-testid="place-photo-credit-link-0"]');
                  const card1 = document.querySelector('[data-testid="activity-card-1"]');
                  const placeholder1 = document.querySelector('[data-testid="place-photo-placeholder-1"]');
                  if (!card0 || !media0 || !credit0 || !img0 || !link0 || !card1 || !placeholder1) return null;
                  const rCard0 = card0.getBoundingClientRect();
                  const rMedia0 = media0.getBoundingClientRect();
                  const rCredit0 = credit0.getBoundingClientRect();
                  const rCard1 = card1.getBoundingClientRect();
                  return {
                    card0Height: rCard0.height,
                    card0Top: rCard0.top,
                    media0Width: rMedia0.width,
                    media0Height: rMedia0.height,
                    credit0Height: rCredit0.height,
                    card1Top: rCard1.top,
                    card1Left: rCard1.left,
                    imgVisible: img0.offsetWidth > 200 && img0.offsetHeight > 100,
                    imgLoadingAttr: img0.getAttribute("loading"),
                    imgWidthAttr: img0.getAttribute("width"),
                    imgHeightAttr: img0.getAttribute("height"),
                    creditText: (link0.textContent || "").trim(),
                    creditHref: link0.getAttribute("href"),
                    placeholder1Text: (placeholder1.textContent || "").trim(),
                  };
                }"""
            )
            assert after_metrics is not None
            assert after_metrics["imgVisible"] is True
            assert after_metrics["imgLoadingAttr"] == "lazy"
            assert after_metrics["imgWidthAttr"] == "800"
            assert after_metrics["imgHeightAttr"] == "450"
            assert after_metrics["creditText"] == "Photo : Alves Gaspar, CC BY-SA 4.0"
            assert (
                after_metrics["creditHref"]
                == "https://commons.wikimedia.org/wiki/File:Castelo_Sao_Jorge_Lisboa.jpg"
            )

            # Aucun saut de mise en page (CLS = 0 : hauteurs et positions strictement conservées)
            assert abs(after_metrics["media0Width"] - before_metrics["media0Width"]) <= 1.0
            assert abs(after_metrics["media0Height"] - before_metrics["media0Height"]) <= 1.0
            assert abs(after_metrics["credit0Height"] - before_metrics["credit0Height"]) <= 1.0
            assert abs(after_metrics["card0Height"] - before_metrics["card0Height"]) <= 1.0
            assert abs(after_metrics["card1Top"] - before_metrics["card1Top"]) <= 1.0
            assert abs(after_metrics["card1Left"] - before_metrics["card1Left"]) <= 1.0

            # Lieu sans photo : garde l'illustration neutre et "Photo bientôt disponible"
            assert "Photo bientôt disponible" in after_metrics["placeholder1Text"]
            assert page.locator('[data-testid="place-photo-img-1"]').count() == 0

            # Aperçu plein écran avec les mêmes crédits Commons
            page.locator('[data-testid="fullscreen-place-btn-0"]').click()
            page.wait_for_selector('[data-testid="fullscreen-place-modal"]', timeout=10000)
            modal_img = page.locator('[data-testid="fullscreen-place-photo-img"]')
            assert modal_img.is_visible()
            modal_credit_link = page.locator('[data-testid="fullscreen-photo-credit-link"]')
            assert modal_credit_link.is_visible()
            assert modal_credit_link.inner_text().strip() == "Photo : Alves Gaspar, CC BY-SA 4.0"
            assert (
                modal_credit_link.get_attribute("href")
                == "https://commons.wikimedia.org/wiki/File:Castelo_Sao_Jorge_Lisboa.jpg"
            )

            # Vérification Playwright sur une ville de démo réelle (Paris) depuis le backend PostgreSQL seedé :
            # aucun doublon d'URL, aucune photo Unsplash, crédit Commons sur Tour Eiffel et illustration neutre sur Le Comptoir du Relais
            page.unroute("**/api/v1/places/trip/*/gallery*")
            page.unroute("**/api/v1/places/trip/*/photos/enrich*")
            svg_demo_body = (
                "<svg xmlns='http://www.w3.org/2000/svg' width='800' height='450' viewBox='0 0 800 450'>"
                "<rect width='800' height='450' fill='%23335c67'/></svg>"
            )
            page.route(
                "**/*.wikimedia.org/**",
                lambda route: route.fulfill(
                    status=200,
                    content_type="image/svg+xml",
                    body=svg_demo_body,
                ),
            )
            page.evaluate(
                """async (apiUrl) => {
                  const email = "playwright.paris.commons." + Date.now() + "@travelmate.app";
                  const regResp = await fetch(apiUrl + "/api/v1/auth/register", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      email,
                      full_name: "Voyageur Paris Commons",
                      password: "PasswordStep3!2026",
                      preferred_style: "STANDARD"
                    })
                  });
                  const regData = await regResp.json();
                  const token = regData.access_token;
                  localStorage.setItem("travelmate_user_profile", JSON.stringify(regData.user));
                  const destsResp = await fetch(apiUrl + "/api/v1/destinations");
                  const dests = await destsResp.json();
                  const paris = dests.find((d) => d.city_name === "Paris");
                  const tripResp = await fetch(apiUrl + "/api/v1/trips", {
                    method: "POST",
                    headers: {
                      "Content-Type": "application/json",
                      "Authorization": "Bearer " + token
                    },
                    body: JSON.stringify({
                      destination_id: paris.id,
                      title: "Séjour Paris Photos Commons",
                      travel_style: "STANDARD",
                      total_budget: 1500
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
                      idempotency_key: "IDEM-PW-PARIS-" + Date.now(),
                      airline: "Air France",
                      flight_number_outbound: "AF101",
                      flight_number_inbound: "AF102",
                      origin_iata: "LYS",
                      destination_iata: "CDG",
                      departure_outbound_at: "2026-11-11T07:00:00Z",
                      arrival_outbound_at: "2026-11-11T08:15:00Z",
                      departure_inbound_at: "2026-11-15T19:00:00Z",
                      arrival_inbound_at: "2026-11-15T20:15:00Z",
                      price_amount: "160.00",
                      currency: "EUR",
                      cabin_class: "ECONOMY"
                    })
                  });
                  const bookData = await bookResp.json();
                  localStorage.setItem("travelmate_last_flight_booking", JSON.stringify(bookData));
                }""",
                API_URL,
            )
            page.goto(f"{BASE_URL}/activities", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_selector('[data-testid="activity-card-0"]', timeout=15000)
            paris_dom = page.evaluate(
                """() => {
                  const imgs = Array.from(document.querySelectorAll('[data-testid^="place-photo-img-"]'));
                  const srcs = imgs.map((el) => el.getAttribute("src") || "");
                  const links = Array.from(document.querySelectorAll('[data-testid^="place-photo-credit-link-"]')).map((el) => ({
                    text: (el.textContent || "").trim(),
                    href: el.getAttribute("href") || ""
                  }));
                  const placeholders = Array.from(document.querySelectorAll('[data-testid^="place-photo-placeholder-"]')).map(
                    (el) => (el.textContent || "").trim()
                  );
                  return { srcs, links, placeholders };
                }"""
            )
            assert len(paris_dom["srcs"]) == 12
            assert len(set(paris_dom["srcs"])) == len(paris_dom["srcs"]), f"Doublons d'images DOM détectés: {paris_dom['srcs']}"
            assert all("unsplash.com" not in s.lower() for s in paris_dom["srcs"])
            assert any(
                l["text"] == "Photo : Benh LIEU SONG, Public domain"
                and l["href"] == "https://commons.wikimedia.org/wiki/File:Tour_Eiffel_Wikimedia_Commons.jpg"
                for l in paris_dom["links"]
            ), f"Crédit Tour Eiffel introuvable dans le DOM: {paris_dom['links']}"
            assert len(paris_dom["placeholders"]) == 2
            assert all("Photo bientôt disponible" in p for p in paris_dom["placeholders"])

            browser.close()
    finally:
        if bridge_proc is not None:
            bridge_proc.terminate()


if __name__ == "__main__":
    test_mon_programme_layout_5_widths_playwright()
    test_real_chat_marrakech_jardin_secret_medina_and_single_row_header()
    test_hands_free_voice_fake_speech_recognition_playwright()
    test_world_cities_step1_geonames_search_create_and_fallback_playwright()
    test_home_barcelone_geonames_autocomplete_visible_clickable_no_timezone_playwright()
    test_world_places_step3_photos_visible_credit_and_no_layout_shift_playwright()





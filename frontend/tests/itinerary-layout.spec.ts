import { test, expect } from "@playwright/test";
import path from "path";

const WIDTHS = [390, 768, 1024, 1280, 1440] as const;
const ARTIFACT_DIR =
  process.env.ARTIFACT_DIR ||
  "C:\\Users\\mohamed.slama\\.gemini\\antigravity\\brain\\5cabc6ba-ac77-4aa2-b151-2378a164db64";
const API_URL = process.env.VITE_API_BASE_URL || "http://localhost:8000";

interface BoxInfo {
  name: string;
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

function boxesOverlap(a: BoxInfo, b: BoxInfo, tolerancePx = 1.5): boolean {
  const overlapX =
    Math.min(a.right, b.right) - Math.max(a.left, b.left) > tolerancePx;
  const overlapY =
    Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > tolerancePx;
  return overlapX && overlapY;
}

test.describe("Mon programme — Vérification de mise en page aux 5 largeurs (390, 768, 1024, 1280, 1440 px)", () => {
  test("Le titre ne dépasse jamais 2 lignes, aucune coupure de mot, badges sur 1 ligne, puces non coupées et zéro chevauchement (chat fermé et ouvert)", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");

    // Prépare un séjour de 8 jours à New York avec une visite le jeudi (09:00-11:00) et une proposition dans le chat
    await page.evaluate(async (apiUrl: string) => {
      const email = `playwright.layout.${Date.now()}@travelmate.app`;
      const regResp = await fetch(`${apiUrl}/api/v1/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          full_name: "Camille Moreau",
          password: "PasswordStep4!2026",
          preferred_style: "STANDARD",
        }),
      });
      const regData = await regResp.json();
      const token = regData.access_token;
      localStorage.setItem("travelmate_jwt_token", token);
      localStorage.setItem(
        "travelmate_user_profile",
        JSON.stringify(regData.user)
      );

      const destsResp = await fetch(`${apiUrl}/api/v1/destinations`);
      const dests = await destsResp.json();
      const ny =
        dests.find((d: { city_name: string }) => d.city_name === "New York") ||
        dests[0];

      const tripResp = await fetch(`${apiUrl}/api/v1/trips`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          destination_id: ny.id,
          title: "Séjour à New York",
          travel_style: "STANDARD",
          total_budget: 2600,
        }),
      });
      const trip = await tripResp.json();
      localStorage.setItem("travelmate_active_trip_id", trip.id);

      const bookResp = await fetch(`${apiUrl}/api/v1/flights/book`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          trip_id: trip.id,
          idempotency_key: `IDEM-PW-LAYOUT-${Date.now()}`,
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
          cabin_class: "ECONOMY",
        }),
      });
      const bookData = await bookResp.json();
      localStorage.setItem(
        "travelmate_last_flight_booking",
        JSON.stringify(bookData)
      );

      const placesResp = await fetch(
        `${apiUrl}/api/v1/places/city/New York`,
        {
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      const placesData = await placesResp.json();
      const memorial =
        placesData.places.find((p: { name: string }) =>
          p.name.toLowerCase().includes("septembre")
        ) || placesData.places[0];
      const met =
        placesData.places.find((p: { name: string }) =>
          p.name.toLowerCase().includes("metropolitan")
        ) || placesData.places[1];

      await fetch(`${apiUrl}/api/v1/itinerary/items`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          trip_id: trip.id,
          place_id: memorial.id,
          visit_date: "2026-11-12",
          local_start_time: "09:00",
          duration_minutes: 120,
          transit_mode: "METRO",
        }),
      });

      await fetch(`${apiUrl}/api/v1/itinerary/trip/${trip.id}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          message: `Ajoute ${met.name} jeudi à 10h`,
        }),
      });
    }, API_URL);

    await page.goto("/itinerary");
    await page.waitForSelector('[data-testid="itinerary-page-title"]');
    // Sélectionne le jeudi 12 novembre (Jour 3, index 2) pour afficher la carte de visite
    const dayPill2 = page.locator('[data-testid="day-pill-2"]');
    if ((await dayPill2.count()) > 0) {
      await dayPill2.click();
    }

    for (const width of WIDTHS) {
      for (const chatState of ["ferme", "ouvert"] as const) {
        await page.setViewportSize({ width, height: 900 });
        await page.waitForTimeout(250);

        const isChatCurrentlyOpen =
          (await page.locator('[data-testid="floating-chat-panel"]').count()) >
          0;
        if (chatState === "ouvert" && !isChatCurrentlyOpen) {
          await page.locator('[data-testid="floating-chat-bubble-btn"]').click();
          await page.waitForSelector('[data-testid="floating-chat-panel"]');
        } else if (chatState === "ferme" && isChatCurrentlyOpen) {
          await page.locator('[data-testid="close-chat-panel-btn"]').click();
          await page.waitForSelector('[data-testid="floating-chat-bubble-btn"]');
        }
        await page.waitForTimeout(250);

        const screenshotPath = path.join(
          ARTIFACT_DIR,
          `programme_${width}px_chat_${chatState}.png`
        );
        await page.screenshot({ path: screenshotPath, fullPage: false });

        const metrics = await page.evaluate(
          ({ vw, state }: { vw: number; state: string }) => {
            function rectOf(el: Element | null, name: string): BoxInfo | null {
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
                left: r.left,
                top: r.top,
                right: r.right,
                bottom: r.bottom,
                width: r.width,
                height: r.height,
              };
            }

            const titleEl = document.querySelector(
              '[data-testid="itinerary-page-title"]'
            ) as HTMLElement | null;
            if (!titleEl) {
              throw new Error("Titre de page introuvable");
            }
            const titleStyle = window.getComputedStyle(titleEl);
            const titleRect = titleEl.getBoundingClientRect();
            const lineHeight = parseFloat(titleStyle.lineHeight) || 33.6;
            const titleLineCount = Math.round(titleRect.height / lineHeight);

            const headerEl = document.querySelector(
              '[data-testid="itinerary-header"]'
            ) as HTMLElement | null;
            const headerDirection = headerEl
              ? window.getComputedStyle(headerEl).flexDirection
              : "";

            // Badges sur une seule ligne
            const badgeEls = Array.from(
              document.querySelectorAll(
                '[data-testid="itinerary-header-badges"] > *'
              )
            );
            const badgeRects = badgeEls
              .map((el, i) => rectOf(el, `header-badge-${i}`))
              .filter((b): b is BoxInfo => b !== null);
            const badgesSingleLine =
              badgeRects.length <= 1 ||
              Math.abs(badgeRects[0].top - badgeRects[1].top) <= 4;
            const badgesNotStretched = badgeRects.every((b) => b.height <= 32);
            const badgesNotClipped = badgeRects.every((b) => b.right <= vw - 8);

            // Puces de jours dans une bande défilante horizontale sans coupure
            const dayPillsContainer = document.getElementById(
              "itinerary-day-pills"
            );
            const pillEls = Array.from(
              document.querySelectorAll('[data-testid^="day-pill-"]')
            ).filter((el) =>
              /^day-pill-\d+$/.test(el.getAttribute("data-testid") || "")
            ) as HTMLElement[];
            const pillsClipped = pillEls.filter(
              (el) => el.scrollWidth > el.clientWidth + 1
            );
            const pillTops = pillEls.map(
              (el) => el.getBoundingClientRect().top
            );
            const pillsSameRow =
              pillTops.length === 0 ||
              pillTops.every((t) => Math.abs(t - pillTops[0]) <= 2);

            const topNavBoxes = [
              rectOf(document.querySelector('[data-testid="header-brand-link"]'), "nav-brand"),
              rectOf(document.querySelector('[data-testid="step-progress-bar"]'), "nav-step-progress-bar"),
              rectOf(document.querySelector('[data-testid="active-destination-pill"]'), "nav-destination-pill"),
              rectOf(document.querySelector('[data-testid="nav-my-trip-link"]'), "nav-my-trip"),
              rectOf(document.querySelector('[data-testid="open-documents-btn"]'), "nav-documents"),
              rectOf(document.querySelector('[data-testid="nav-settings-link"]'), "nav-settings"),
              rectOf(document.querySelector('[data-testid="header-user-link"]'), "nav-user"),
              rectOf(document.querySelector('[data-testid="logout-btn"]'), "nav-logout"),
            ].filter((b): b is BoxInfo => b !== null);

            // Collecte des éléments visibles du flux principal pour détecter tout chevauchement
            const mainBoxes: BoxInfo[] = [];
            for (const b of badgeRects) mainBoxes.push(b);
            const titleBox = rectOf(titleEl, "page-title");
            if (titleBox) mainBoxes.push(titleBox);
            const subtitleEl = titleEl.nextElementSibling;
            const subtitleBox = rectOf(subtitleEl, "page-subtitle");
            if (subtitleBox) mainBoxes.push(subtitleBox);

            const actionBtnEls = Array.from(
              document.querySelectorAll(
                '[data-testid="itinerary-header-actions"] > button'
              )
            );
            actionBtnEls.forEach((btn, idx) => {
              const b = rectOf(btn, `header-btn-${idx}`);
              if (b) mainBoxes.push(b);
            });

            const pillsStripBox = rectOf(dayPillsContainer, "day-pills-strip");
            if (pillsStripBox) mainBoxes.push(pillsStripBox);

            const timelineCardBox = rectOf(
              document.querySelector(
                '[data-testid="single-day-timeline-card"]'
              ),
              "timeline-card"
            );
            if (timelineCardBox) mainBoxes.push(timelineCardBox);

            const summaryBtnBox = rectOf(
              document.querySelector(
                '[data-testid="itinerary-go-to-trip-summary-btn"]'
              ),
              "summary-btn"
            );
            if (summaryBtnBox) mainBoxes.push(summaryBtnBox);

            const chatBubbleBox = rectOf(
              document.querySelector('[data-testid="floating-chat-bubble-btn"]'),
              "floating-chat-bubble-btn"
            );
            if (state === "ferme" && chatBubbleBox && summaryBtnBox) {
              mainBoxes.push(chatBubbleBox);
            }

            // À partir de 1280 px, le panneau latéral du chat est en côte à côte et ne doit chevaucher aucun élément principal
            const chatPanelEl = document.querySelector(
              '[data-testid="floating-chat-panel"]'
            );
            const chatPanelBox = rectOf(chatPanelEl, "floating-chat-panel");
            if (state === "ouvert" && vw >= 1280 && chatPanelBox) {
              mainBoxes.push(chatPanelBox);
            }

            // Vérification des chevauchements internes au panneau de chat quand il est ouvert
            const chatInternalBoxes: BoxInfo[] = [];
            if (state === "ouvert" && chatPanelEl) {
              const chatHeader = chatPanelEl.firstElementChild;
              const msgList = chatPanelEl.querySelector(
                '[data-testid="chat-messages-list"]'
              );
              const proposalCard = chatPanelEl.querySelector(
                '[data-testid="chat-proposed-action-card"]'
              );
              const chatForm = chatPanelEl.querySelector("form");
              for (const [el, label] of [
                [chatHeader, "chat-header"],
                [msgList, "chat-messages-list"],
                [proposalCard, "chat-proposed-action-card"],
                [chatForm, "chat-form"],
              ] as const) {
                const r = rectOf(el, label);
                if (r) chatInternalBoxes.push(r);
              }
            }

            const screenEl = document.querySelector(
              '[data-testid="itinerary-screen"]'
            );
            const screenRect = screenEl?.getBoundingClientRect();

            return {
              titleLineCount,
              titleHeight: titleRect.height,
              lineHeight,
              headerDirection,
              badgesSingleLine,
              badgesNotStretched,
              pillsClippedCount: pillsClipped.length,
              pillsSameRow,
              mainBoxes,
              chatInternalBoxes,
              chatPanelBox,
              screenWidth: screenRect ? Math.round(screenRect.width) : 0,
            };
          },
          { vw: width, state: chatState }
        );

        // 1. Le titre de la page ne passe jamais sur plus de 2 lignes
        expect(
          metrics.titleLineCount,
          `À ${width}px (chat ${chatState}), le titre fait ${metrics.titleLineCount} lignes (max 2 autorisé)`
        ).toBeLessThanOrEqual(2);

        // 2. Quand le chat est ouvert, l'en-tête passe en colonne
        if (chatState === "ouvert") {
          expect(metrics.headerDirection).toBe("column");
        }

        // 3. Badges sur une ligne, non étirés
        expect(
          metrics.badgesSingleLine,
          `À ${width}px (chat ${chatState}), les badges ne sont pas sur une seule ligne`
        ).toBe(true);
        expect(
          metrics.badgesNotStretched,
          `À ${width}px (chat ${chatState}), un badge est étiré sur plusieurs lignes`
        ).toBe(true);

        // 4. Puces de jours dans une bande horizontale sans coupure
        expect(
          metrics.pillsClippedCount,
          `À ${width}px (chat ${chatState}), ${metrics.pillsClippedCount} puce(s) de jour sont coupées`
        ).toBe(0);
        expect(metrics.pillsSameRow).toBe(true);

        // 5. Aucun chevauchement entre éléments de la page
        for (let i = 0; i < metrics.mainBoxes.length; i++) {
          for (let j = i + 1; j < metrics.mainBoxes.length; j++) {
            const a = metrics.mainBoxes[i];
            const b = metrics.mainBoxes[j];
            expect(
              boxesOverlap(a, b),
              `Chevauchement détecté à ${width}px (chat ${chatState}) entre '${a.name}' (${JSON.stringify(
                a
              )}) et '${b.name}' (${JSON.stringify(b)})`
            ).toBe(false);
          }
        }

        // 6. Aucun chevauchement interne dans le chat
        for (let i = 0; i < metrics.chatInternalBoxes.length; i++) {
          for (let j = i + 1; j < metrics.chatInternalBoxes.length; j++) {
            const a = metrics.chatInternalBoxes[i];
            const b = metrics.chatInternalBoxes[j];
            expect(
              boxesOverlap(a, b),
              `Chevauchement interne au chat à ${width}px entre '${a.name}' et '${b.name}'`
            ).toBe(false);
          }
        }
      }
    }
  });
});

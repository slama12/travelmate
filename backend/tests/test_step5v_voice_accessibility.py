from pathlib import Path
import re
import uuid

import httpx
import pytest

from app.core.database import AsyncSessionLocal
from app.core.providers import (
    BaseVoiceSTTProvider,
    LocalWhisperSTTProvider,
    WebSpeechSTTProvider,
    get_provider_registry,
    get_voice_stt_provider,
)
from app.main import app
from app.models.entities import TripMember
from app.models.enums import InviteStatus, MemberRole


async def _register_test_user(
    client: httpx.AsyncClient,
    prefix: str,
) -> tuple[dict, str, str]:
    email = f"{prefix}.{uuid.uuid4().hex[:8]}@travelmate.app"
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Password123!",
            "full_name": f"Test {prefix.capitalize()}",
            "preferred_style": "STANDARD",
        },
    )
    assert res.status_code == 201, res.text
    payload = res.json()
    csrf = payload.get("csrf_token") or client.cookies.get("tm_csrf_token") or ""
    return payload["user"], payload["access_token"], csrf


async def _create_trip_for_user(
    client: httpx.AsyncClient,
    token: str,
    city_name: str = "Marrakech",
    budget_planned: str = "1200.00",
) -> tuple[dict, dict, list[dict]]:
    dests = (await client.get("/api/v1/destinations")).json()
    dest = next(d for d in dests if d["city_name"].lower() == city_name.lower())
    places = (
        await client.get(
            f"/api/v1/places/city/{dest['city_name']}",
            headers={"Authorization": f"Bearer {token}"},
        )
    ).json()["places"]
    place_ids = [p["id"] for p in places[:2]]
    res = await client.post(
        "/api/v1/trips",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "destination_id": dest["id"],
            "title": f"Séjour vocal {city_name}",
            "travel_style": "STANDARD",
            "total_budget_planned": budget_planned,
            "currency": "EUR",
            "arrival_at": "2026-11-10T10:00:00Z",
            "departure_at": "2026-11-14T18:00:00Z",
            "selected_place_ids": place_ids,
        },
    )
    assert res.status_code == 201, res.text
    trip_data = res.json()
    if places:
        it_res = await client.post(
            "/api/v1/itinerary/items",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "trip_id": trip_data["id"],
                "place_id": places[0]["id"],
                "visit_date": "2026-11-11",
                "local_start_time": "10:00",
            },
        )
        assert it_res.status_code == 201, it_res.text
    return trip_data, dest, places


async def _add_trip_member_in_db(trip_id: str, user_id: str, role: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            TripMember(
                trip_id=trip_id,
                user_id=user_id,
                role=role,
                invite_status=InviteStatus.ACCEPTED.value,
            )
        )
        await db.commit()


@pytest.mark.anyio
async def test_step5v_simulated_transcriptions_navigation_and_5a_screens_via_shared_chat_analyzer():
    """
    Exigences 1, 4 & 5A :
    - Transcriptions simulées pour chaque commande vocale :
      * "va à mon programme" -> /itinerary
      * "ouvre l'hébergement" -> /accommodations
      * "lis-moi le jour 2" -> /itinerary (day_number=2 + lecture vocale du jour 2)
      * "lis-moi mon budget" -> /trip/budget + lecture vocale du budget (prévu, dépensé, restant)
      * "ouvre mes documents" -> /trip/documents + lecture vocale du nombre et des titres des documents
      * "infos pratiques" -> /trip/infos + lecture vocale prises, urgences, monnaie, indicatif, pourboires
    - Même analyseur que le chat (/chat et /voice/command produisent la même cible et la même réponse).
    - Transcription affichée et modifiable avant envoi (editable_before_send=True, auto_submitted=False)
      sauf en mode mains libres (hands_free=True -> editable_before_send=False, auto_submitted=True).
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        _user, token, _csrf = await _register_test_user(client, "voicenav")
        headers = {"Authorization": f"Bearer {token}"}
        trip, _dest, _places = await _create_trip_for_user(client, token, "Marrakech", "1500.00")
        trip_id = trip["id"]

        # Ajoute une dépense et un document chiffré pour vérifier la lecture vocale 5A
        exp_res = await client.post(
            f"/api/v1/budget/trip/{trip_id}/expenses",
            headers=headers,
            json={
                "category": "MEAL",
                "title": "Dîner place Jemaa el-Fna",
                "amount": "45.00",
                "currency": "EUR",
            },
        )
        assert exp_res.status_code == 201, exp_res.text

        doc_res = await client.post(
            f"/api/v1/documents/trip/{trip_id}",
            headers=headers,
            json={
                "title": "Passeport biométrique Mohamed",
                "doc_type": "PASSPORT",
                "content_text": "SECRET-PASSPORT-998877",
                "is_shared": True,
                "expires_on": "2027-01-15",
            },
        )
        assert doc_res.status_code == 201, doc_res.text

        # 1. Mode standard (hands_free=False) : transcription modifiable avant envoi
        cmd_prog = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers=headers,
            json={
                "transcript": "va à mon programme",
                "signal": "SPEECH",
                "confidence": 0.96,
                "provider": "web_speech",
                "hands_free": False,
            },
        )
        assert cmd_prog.status_code == 200, cmd_prog.text
        prog_data = cmd_prog.json()
        assert prog_data["status"] == "TRANSCRIBED_EDITABLE"
        assert prog_data["editable_before_send"] is True
        assert prog_data["auto_submitted"] is False
        assert prog_data["navigation_target"] == "/itinerary"
        assert prog_data["voice_command"] == "NAVIGATE_ITINERARY"
        assert prog_data["requires_confirmation"] is False

        # Vérifie que le chat texte utilise exactement le même analyseur
        chat_prog = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/chat",
            headers=headers,
            json={"message": "va à mon programme"},
        )
        assert chat_prog.status_code == 200
        last_chat_msg = chat_prog.json()["messages"][-1]
        assert last_chat_msg["navigation_target"] == "/itinerary"
        assert last_chat_msg["voice_command"] == "NAVIGATE_ITINERARY"

        # 2. "ouvre l'hébergement" en mode mains libres (hands_free=True)
        cmd_acc = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers=headers,
            json={
                "transcript": "ouvre l'hébergement",
                "signal": "SPEECH",
                "confidence": 0.95,
                "provider": "web_speech",
                "hands_free": True,
            },
        )
        assert cmd_acc.status_code == 200
        acc_data = cmd_acc.json()
        assert acc_data["status"] == "OK"
        assert acc_data["editable_before_send"] is False
        assert acc_data["auto_submitted"] is True
        assert acc_data["navigation_target"] == "/accommodations"
        assert acc_data["voice_command"] == "NAVIGATE_ACCOMMODATIONS"

        # 3. "lis-moi le jour 2"
        cmd_day2 = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers=headers,
            json={
                "transcript": "lis-moi le jour 2",
                "signal": "SPEECH",
                "confidence": 0.94,
                "provider": "web_speech",
                "hands_free": True,
            },
        )
        assert cmd_day2.status_code == 200
        day2_data = cmd_day2.json()
        assert day2_data["navigation_target"] == "/itinerary"
        assert day2_data["voice_command"] == "READ_DAY"
        assert day2_data["day_number"] == 2
        assert "jour 2" in day2_data["spoken_reply_fr"].lower()

        # 4. Écran 5A : "lis-moi mon budget"
        cmd_budget = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers=headers,
            json={
                "transcript": "lis-moi mon budget",
                "signal": "SPEECH",
                "confidence": 0.97,
                "provider": "web_speech",
                "hands_free": True,
            },
        )
        assert cmd_budget.status_code == 200
        budget_data = cmd_budget.json()
        assert budget_data["navigation_target"] == "/trip/budget"
        assert budget_data["voice_command"] == "READ_BUDGET"
        assert "1500.00" in budget_data["spoken_reply_fr"]
        assert "budget" in budget_data["spoken_reply_fr"].lower()

        # 5. Écran 5A : "ouvre mes documents" (sans jamais exposer le contenu déchiffré au LLM/voix)
        cmd_docs = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers=headers,
            json={
                "transcript": "ouvre mes documents",
                "signal": "SPEECH",
                "confidence": 0.95,
                "provider": "web_speech",
                "hands_free": True,
            },
        )
        assert cmd_docs.status_code == 200
        docs_data = cmd_docs.json()
        assert docs_data["navigation_target"] == "/trip/documents"
        assert docs_data["voice_command"] == "OPEN_DOCUMENTS"
        assert "Passeport biométrique Mohamed" in docs_data["spoken_reply_fr"]
        assert "SECRET-PASSPORT-998877" not in docs_data["spoken_reply_fr"]

        # 6. Écran 5A : "infos pratiques"
        cmd_infos = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers=headers,
            json={
                "transcript": "infos pratiques",
                "signal": "SPEECH",
                "confidence": 0.96,
                "provider": "web_speech",
                "hands_free": True,
            },
        )
        assert cmd_infos.status_code == 200
        infos_data = cmd_infos.json()
        assert infos_data["navigation_target"] == "/trip/infos"
        assert infos_data["voice_command"] == "OPEN_PRACTICAL_INFO"
        assert "prises" in infos_data["spoken_reply_fr"].lower()
        assert "urgences" in infos_data["spoken_reply_fr"].lower()


@pytest.mark.anyio
async def test_step5v_voice_confirmation_yes_no_silence_and_never_auto_validates():
    """
    Exigence 3 :
    - L'assistant relit l'action comprise (spoken_reply_fr + proposed_action.spoken_summary_fr).
    - Jamais de validation automatique (même en mode mains libres, l'itinéraire n'est pas modifié sans confirmation).
    - Exige "oui" explicite pour confirmer.
    - "non" ou silence ("SILENCE") annule sans modifier l'itinéraire.
    - Parole non comprise lors de la confirmation demande "Pouvez-vous répéter ?" en conservant la proposition.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        _user, token, _csrf = await _register_test_user(client, "voiceconf")
        headers = {"Authorization": f"Bearer {token}"}
        trip, _dest, places = await _create_trip_for_user(client, token, "Marrakech")
        trip_id = trip["id"]
        target_place = places[2]  # Lieu non encore planifié

        initial_sched = (
            await client.get(f"/api/v1/itinerary/trip/{trip_id}", headers=headers)
        ).json()
        initial_count = len(initial_sched["items"])

        # 1. Proposition d'ajout via commande vocale -> jamais d'application automatique
        propose_1 = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers=headers,
            json={
                "transcript": f"Ajoute {target_place['name']} mercredi à 14h",
                "signal": "SPEECH",
                "confidence": 0.95,
                "provider": "web_speech",
                "hands_free": True,
            },
        )
        assert propose_1.status_code == 200, propose_1.text
        p1_data = propose_1.json()
        assert p1_data["status"] == "PENDING_CONFIRMATION"
        assert p1_data["requires_confirmation"] is True
        assert p1_data["proposed_action"] is not None
        assert p1_data["proposed_action"]["spoken_summary_fr"] is not None
        assert "oui" in p1_data["spoken_reply_fr"].lower()

        sched_after_propose = (
            await client.get(f"/api/v1/itinerary/trip/{trip_id}", headers=headers)
        ).json()
        assert len(sched_after_propose["items"]) == initial_count

        # 2. Réponse "non" -> annule la proposition, itinéraire inchangé
        reject_res = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/confirm",
            headers=headers,
            json={
                "message_id": p1_data["message_id"],
                "transcript": "non",
                "signal": "SPEECH",
                "confidence": 0.98,
                "provider": "web_speech",
            },
        )
        assert reject_res.status_code == 200
        r_data = reject_res.json()
        assert r_data["status"] == "REJECTED"
        assert r_data["applied_change"] is False
        assert r_data["pending_action_preserved"] is False

        # 3. Nouvelle proposition puis SILENCE -> annule la proposition, itinéraire inchangé
        propose_2 = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers=headers,
            json={
                "transcript": f"Ajoute {target_place['name']} mercredi à 14h",
                "signal": "SPEECH",
                "confidence": 0.95,
                "provider": "web_speech",
                "hands_free": True,
            },
        )
        p2_data = propose_2.json()
        assert p2_data["status"] == "PENDING_CONFIRMATION"

        silence_res = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/confirm",
            headers=headers,
            json={
                "message_id": p2_data["message_id"],
                "transcript": "",
                "signal": "SILENCE",
                "confidence": 0.0,
                "provider": "web_speech",
            },
        )
        assert silence_res.status_code == 200
        s_data = silence_res.json()
        assert s_data["status"] == "CANCELLED_BY_SILENCE"
        assert s_data["applied_change"] is False
        assert s_data["pending_action_preserved"] is False

        # 4. Nouvelle proposition : parole ambiguë ("peut-être") -> "Pouvez-vous répéter ?", puis "oui" explicite -> confirmé
        propose_3 = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers=headers,
            json={
                "transcript": f"Ajoute {target_place['name']} mercredi à 14h",
                "signal": "SPEECH",
                "confidence": 0.95,
                "provider": "web_speech",
                "hands_free": True,
            },
        )
        p3_data = propose_3.json()
        assert p3_data["status"] == "PENDING_CONFIRMATION"

        ambiguous_res = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/confirm",
            headers=headers,
            json={
                "message_id": p3_data["message_id"],
                "transcript": "peut-être plus tard",
                "signal": "SPEECH",
                "confidence": 0.85,
                "provider": "web_speech",
            },
        )
        assert ambiguous_res.status_code == 200
        amb_data = ambiguous_res.json()
        assert amb_data["status"] == "REPEAT_REQUIRED"
        assert "Pouvez-vous répéter ?" in amb_data["spoken_reply_fr"]
        assert amb_data["applied_change"] is False
        assert amb_data["pending_action_preserved"] is True

        yes_res = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/confirm",
            headers=headers,
            json={
                "message_id": p3_data["message_id"],
                "transcript": "oui",
                "signal": "SPEECH",
                "confidence": 0.99,
                "provider": "web_speech",
            },
        )
        assert yes_res.status_code == 200
        y_data = yes_res.json()
        assert y_data["status"] == "CONFIRMED"
        assert y_data["applied_change"] is True

        sched_after_yes = (
            await client.get(f"/api/v1/itinerary/trip/{trip_id}", headers=headers)
        ).json()
        assert len(sched_after_yes["items"]) == initial_count + 1


@pytest.mark.anyio
async def test_step5v_double_confirmation_for_reservation_payment_and_deletion():
    """
    Exigence 3 :
    - Double confirmation obligatoire pour :
      1. Suppression d'une visite (REMOVE_VISIT)
      2. Réservation (BOOK_RESERVATION)
      3. Paiement (PROCESS_PAYMENT)
    - Le premier "oui" passe à AWAITING_SECOND_CONFIRMATION (étape 2/2) sans appliquer l'action.
    - Le second "oui" explicite applique l'action (CONFIRMED).
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        _user, token, _csrf = await _register_test_user(client, "voicedouble")
        headers = {"Authorization": f"Bearer {token}"}
        trip, _dest, _places = await _create_trip_for_user(client, token, "Marrakech")
        trip_id = trip["id"]

        sched_before = (
            await client.get(f"/api/v1/itinerary/trip/{trip_id}", headers=headers)
        ).json()
        assert len(sched_before["items"]) >= 1
        first_visit_name = sched_before["items"][0]["place_name"]
        initial_count = len(sched_before["items"])

        # A. SUPPRESSION (REMOVE_VISIT) : double confirmation
        del_cmd = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers=headers,
            json={
                "transcript": f"Supprime la visite de {first_visit_name}",
                "signal": "SPEECH",
                "confidence": 0.96,
                "provider": "web_speech",
                "hands_free": True,
            },
        )
        assert del_cmd.status_code == 200
        del_data = del_cmd.json()
        assert del_data["requires_confirmation"] is True
        assert del_data["requires_double_confirmation"] is True
        assert del_data["proposed_action"]["action_type"] == "REMOVE_VISIT"
        assert del_data["proposed_action"]["requires_double_confirmation"] is True

        # 1er "oui" -> AWAITING_SECOND_CONFIRMATION, la visite n'est PAS encore supprimée
        del_yes_1 = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/confirm",
            headers=headers,
            json={
                "message_id": del_data["message_id"],
                "transcript": "oui",
                "signal": "SPEECH",
                "confidence": 0.98,
                "provider": "web_speech",
            },
        )
        assert del_yes_1.status_code == 200
        dy1 = del_yes_1.json()
        assert dy1["status"] == "AWAITING_SECOND_CONFIRMATION"
        assert dy1["applied_change"] is False
        assert dy1["requires_double_confirmation"] is True
        assert dy1["confirmation_step"] == 2

        sched_mid = (
            await client.get(f"/api/v1/itinerary/trip/{trip_id}", headers=headers)
        ).json()
        assert len(sched_mid["items"]) == initial_count

        # 2nd "oui" -> CONFIRMED, la visite est maintenant supprimée
        del_yes_2 = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/confirm",
            headers=headers,
            json={
                "message_id": del_data["message_id"],
                "transcript": "oui",
                "signal": "SPEECH",
                "confidence": 0.99,
                "provider": "web_speech",
            },
        )
        assert del_yes_2.status_code == 200
        dy2 = del_yes_2.json()
        assert dy2["status"] == "CONFIRMED"
        assert dy2["applied_change"] is True

        sched_after_del = (
            await client.get(f"/api/v1/itinerary/trip/{trip_id}", headers=headers)
        ).json()
        assert len(sched_after_del["items"]) == initial_count - 1

        # B. RÉSERVATION (BOOK_RESERVATION) : double confirmation
        res_cmd = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers=headers,
            json={
                "transcript": "Réserve l'hébergement Riad Marrakech",
                "signal": "SPEECH",
                "confidence": 0.95,
                "provider": "web_speech",
                "hands_free": True,
            },
        )
        assert res_cmd.status_code == 200
        res_data = res_cmd.json()
        assert res_data["requires_double_confirmation"] is True
        assert res_data["proposed_action"]["action_type"] == "BOOK_RESERVATION"

        res_yes_1 = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/confirm",
            headers=headers,
            json={
                "message_id": res_data["message_id"],
                "transcript": "oui",
                "signal": "SPEECH",
            },
        )
        assert res_yes_1.json()["status"] == "AWAITING_SECOND_CONFIRMATION"
        assert res_yes_1.json()["applied_change"] is False

        res_yes_2 = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/confirm",
            headers=headers,
            json={
                "message_id": res_data["message_id"],
                "transcript": "oui",
                "signal": "SPEECH",
            },
        )
        assert res_yes_2.json()["status"] == "CONFIRMED"
        assert res_yes_2.json()["applied_change"] is True

        # C. PAIEMENT (PROCESS_PAYMENT) : double confirmation
        pay_cmd = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers=headers,
            json={
                "transcript": "Paie la réservation de 180 euros",
                "signal": "SPEECH",
                "confidence": 0.95,
                "provider": "web_speech",
                "hands_free": True,
            },
        )
        assert pay_cmd.status_code == 200
        pay_data = pay_cmd.json()
        assert pay_data["requires_double_confirmation"] is True
        assert pay_data["proposed_action"]["action_type"] == "PROCESS_PAYMENT"

        pay_yes_1 = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/confirm",
            headers=headers,
            json={
                "message_id": pay_data["message_id"],
                "transcript": "oui",
                "signal": "SPEECH",
            },
        )
        assert pay_yes_1.json()["status"] == "AWAITING_SECOND_CONFIRMATION"
        assert pay_yes_1.json()["applied_change"] is False

        pay_yes_2 = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/confirm",
            headers=headers,
            json={
                "message_id": pay_data["message_id"],
                "transcript": "oui",
                "signal": "SPEECH",
            },
        )
        assert pay_yes_2.json()["status"] == "CONFIRMED"
        assert pay_yes_2.json()["applied_change"] is True


@pytest.mark.anyio
async def test_step5v_errors_mic_denied_browser_unsupported_noise_and_unrecognized_without_modification():
    """
    Exigences 7 & 8 :
    - Micro refusé (MIC_DENIED)
    - Navigateur non compatible (BROWSER_UNSUPPORTED)
    - Parole non comprise -> "Pouvez-vous répéter ?" (UNRECOGNIZED_SPEECH)
    - Bruit ambiant (NOISE)
    - Aucune de ces erreurs ne modifie l'itinéraire ni ne valide une action en attente.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        _user, token, _csrf = await _register_test_user(client, "voiceerr")
        headers = {"Authorization": f"Bearer {token}"}
        trip, _dest, places = await _create_trip_for_user(client, token, "Marrakech")
        trip_id = trip["id"]

        before_items = (
            await client.get(f"/api/v1/itinerary/trip/{trip_id}", headers=headers)
        ).json()["items"]

        # 1. Micro refusé (MIC_DENIED)
        mic_res = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers=headers,
            json={
                "transcript": "",
                "signal": "MIC_DENIED",
                "confidence": 0.0,
                "provider": "web_speech",
            },
        )
        assert mic_res.status_code == 200
        mic_data = mic_res.json()
        assert mic_data["status"] == "ERROR"
        assert mic_data["error_code"] == "MIC_DENIED"
        assert "microphone" in (mic_data["error_message_fr"] or "").lower()

        # 2. Navigateur non compatible (BROWSER_UNSUPPORTED)
        unsup_res = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers=headers,
            json={
                "transcript": "",
                "signal": "BROWSER_UNSUPPORTED",
                "confidence": 0.0,
                "provider": "web_speech",
            },
        )
        assert unsup_res.status_code == 200
        unsup_data = unsup_res.json()
        assert unsup_data["status"] == "ERROR"
        assert unsup_data["error_code"] == "BROWSER_UNSUPPORTED"
        assert "navigateur" in (unsup_data["error_message_fr"] or "").lower()

        # 3. Bruit ambiant (NOISE)
        noise_res = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers=headers,
            json={
                "transcript": "bruit de rue indistinct",
                "signal": "NOISE",
                "confidence": 0.12,
                "provider": "web_speech",
            },
        )
        assert noise_res.status_code == 200
        noise_data = noise_res.json()
        assert noise_data["status"] == "REPEAT_REQUIRED"
        assert noise_data["error_code"] == "NOISE_DETECTED"
        assert "Pouvez-vous répéter ?" in noise_data["spoken_reply_fr"]

        # 4. Parole non comprise (UNRECOGNIZED_SPEECH / syllabes incompréhensibles)
        unrec_res = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers=headers,
            json={
                "transcript": "zzzz xxxx kkkk",
                "signal": "SPEECH",
                "confidence": 0.90,
                "provider": "web_speech",
            },
        )
        assert unrec_res.status_code == 200
        unrec_data = unrec_res.json()
        assert unrec_data["status"] == "REPEAT_REQUIRED"
        assert "Pouvez-vous répéter ?" in unrec_data["spoken_reply_fr"]

        # 5. Erreur de reconnaissance pendant qu'une proposition est en attente -> zéro modification
        prop_res = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers=headers,
            json={
                "transcript": f"Ajoute {places[2]['name']} jeudi à 10h",
                "signal": "SPEECH",
                "confidence": 0.95,
                "provider": "web_speech",
                "hands_free": True,
            },
        )
        msg_id = prop_res.json()["message_id"]

        for err_signal in ("MIC_DENIED", "NOISE", "UNRECOGNIZED_SPEECH"):
            err_conf = await client.post(
                f"/api/v1/itinerary/trip/{trip_id}/voice/confirm",
                headers=headers,
                json={
                    "message_id": msg_id,
                    "transcript": "bruit inaudible",
                    "signal": err_signal,
                    "confidence": 0.1,
                    "provider": "web_speech",
                },
            )
            assert err_conf.status_code == 200
            ec_data = err_conf.json()
            assert ec_data["applied_change"] is False
            assert ec_data["pending_action_preserved"] is True

        after_items = (
            await client.get(f"/api/v1/itinerary/trip/{trip_id}", headers=headers)
        ).json()["items"]
        assert [it["id"] for it in after_items] == [it["id"] for it in before_items]


@pytest.mark.anyio
async def test_step5v_replaceable_stt_provider_web_speech_and_whisper_local_and_privacy_notice():
    """
    Exigence 5 :
    - Mode mains libres avec message de confidentialité (l'audio peut transiter par le service de reconnaissance du navigateur).
    - Fournisseur remplaçable par Whisper local derrière la même interface (BaseVoiceSTTProvider).
    """
    web_provider = get_voice_stt_provider("web_speech")
    whisper_provider = get_voice_stt_provider("whisper_local")

    assert isinstance(web_provider, BaseVoiceSTTProvider)
    assert isinstance(web_provider, WebSpeechSTTProvider)
    assert isinstance(whisper_provider, BaseVoiceSTTProvider)
    assert isinstance(whisper_provider, LocalWhisperSTTProvider)

    assert web_provider.language == "fr-FR"
    assert whisper_provider.language == "fr-FR"
    assert web_provider.transits_browser_service is True
    assert whisper_provider.transits_browser_service is False
    assert (
        "service de reconnaissance du navigateur"
        in web_provider.privacy_notice_fr.lower()
    )

    registry = get_provider_registry()
    assert registry.resolve_voice_stt_provider("whisper_local").provider_id == "whisper_local"
    assert registry.resolve_voice_stt_provider("web_speech").provider_id == "web_speech"

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        _user, token, _csrf = await _register_test_user(client, "whisperstt")
        headers = {"Authorization": f"Bearer {token}"}
        trip, _dest, _places = await _create_trip_for_user(client, token, "Marrakech")

        cfg_res = await client.get("/api/v1/itinerary/voice/providers")
        assert cfg_res.status_code == 200
        cfg = cfg_res.json()
        assert cfg["language"] == "fr-FR"
        assert "service de reconnaissance du navigateur" in cfg["hands_free_privacy_notice_fr"].lower()
        provider_ids = {p["provider_id"] for p in cfg["available_providers"]}
        assert provider_ids == {"web_speech", "whisper_local"}

        # Même commande exécutée avec le fournisseur Whisper local derrière la même interface
        whisper_cmd = await client.post(
            f"/api/v1/itinerary/trip/{trip['id']}/voice/command",
            headers=headers,
            json={
                "transcript": "lis-moi mon budget",
                "signal": "SPEECH",
                "confidence": 0.96,
                "provider": "whisper_local",
                "hands_free": True,
            },
        )
        assert whisper_cmd.status_code == 200
        w_data = whisper_cmd.json()
        assert w_data["provider_used"] == "whisper_local"
        assert w_data["navigation_target"] == "/trip/budget"
        assert w_data["voice_command"] == "READ_BUDGET"


@pytest.mark.anyio
async def test_step5v_access_control_httponly_cookie_csrf_and_roles():
    """
    Exigence Sécurité :
    - Les commandes vocales et la confirmation s'appuient sur le contrôle d'accès existant
      (cookie HttpOnly tm_access_token + CSRF X-CSRF-Token, et rôles OWNER / EDITOR / VIEWER).
    - Un lecteur (VIEWER) peut utiliser les commandes vocales de lecture et navigation
      ("lis-moi mon budget", "ouvre mes documents", "infos pratiques"), mais reçoit 403
      sur toute commande vocale de modification ou de confirmation.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as owner_client, \
               httpx.AsyncClient(transport=transport, base_url="http://testserver") as viewer_client, \
               httpx.AsyncClient(transport=transport, base_url="http://testserver") as outsider_client:
        _owner, owner_token, owner_csrf = await _register_test_user(owner_client, "vowner")
        viewer, _viewer_token, viewer_csrf = await _register_test_user(viewer_client, "vviewer")
        _outsider, _outsider_token, outsider_csrf = await _register_test_user(outsider_client, "vout")

        trip, _dest, places = await _create_trip_for_user(owner_client, owner_token, "Marrakech")
        trip_id = trip["id"]
        await _add_trip_member_in_db(trip_id, viewer["id"], MemberRole.VIEWER.value)

        # 1. Authentification par cookie HttpOnly seul SANS en-tête X-CSRF-Token -> 403 CSRF
        no_csrf = await owner_client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            json={"transcript": "lis-moi mon budget", "signal": "SPEECH"},
        )
        assert no_csrf.status_code == 403

        # 2. Authentification par cookie HttpOnly AVEC en-tête X-CSRF-Token -> 200 OK
        with_csrf = await owner_client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers={"X-CSRF-Token": owner_csrf},
            json={"transcript": "lis-moi mon budget", "signal": "SPEECH"},
        )
        assert with_csrf.status_code == 200
        assert with_csrf.json()["voice_command"] == "READ_BUDGET"

        # 3. VIEWER peut exécuter les commandes vocales de lecture ("lis-moi mon budget", "ouvre mes documents", "infos pratiques")
        viewer_read = await viewer_client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers={"X-CSRF-Token": viewer_csrf},
            json={"transcript": "lis-moi mon budget", "signal": "SPEECH"},
        )
        assert viewer_read.status_code == 200
        assert viewer_read.json()["navigation_target"] == "/trip/budget"

        # 4. VIEWER reçoit 403 sur une commande vocale de modification d'itinéraire
        viewer_mutate = await viewer_client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers={"X-CSRF-Token": viewer_csrf},
            json={
                "transcript": f"Ajoute {places[2]['name']} mercredi à 15h",
                "signal": "SPEECH",
            },
        )
        assert viewer_mutate.status_code == 403

        # 5. VIEWER reçoit 403 sur la confirmation vocale
        owner_prop = await owner_client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers={"X-CSRF-Token": owner_csrf},
            json={
                "transcript": f"Ajoute {places[2]['name']} mercredi à 15h",
                "signal": "SPEECH",
            },
        )
        msg_id = owner_prop.json()["message_id"]

        viewer_confirm = await viewer_client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/confirm",
            headers={"X-CSRF-Token": viewer_csrf},
            json={"message_id": msg_id, "transcript": "oui", "signal": "SPEECH"},
        )
        assert viewer_confirm.status_code == 403

        # 6. Outsider (non-membre) reçoit 403 même en lecture vocale
        outsider_read = await outsider_client.post(
            f"/api/v1/itinerary/trip/{trip_id}/voice/command",
            headers={"X-CSRF-Token": outsider_csrf},
            json={"transcript": "lis-moi mon budget", "signal": "SPEECH"},
        )
        assert outsider_read.status_code == 403


def test_step5v_frontend_render_microphone_button_tts_settings_and_accessibility():
    """
    Exigences 1, 2, 5, 6 & 8 :
    - Test de rendu vérifiant le bouton micro dans le chat (data-testid="chat-mic-btn", Web Speech API, fr-FR),
      l'état visible "J'écoute…" (data-testid="voice-listening-status"), l'arrêt par silence ou par bouton,
      la lecture à voix haute (speechSynthesis, vitesse réglable, bouton pause, désactivable dans Paramètres),
      le mode mains libres avec message de confidentialité (data-testid="voice-privacy-notice") et Whisper local,
      l'accessibilité (lecteur d'écran aria-label/aria-live/role="status", focus-visible, grands boutons >= 44px),
      et le respect strict de <= 4 champs par formulaire.
    """
    repo_root = Path(__file__).resolve().parents[2]
    screens_tsx = repo_root / "frontend" / "src" / "EnvoiCScreens.tsx"
    assert screens_tsx.exists(), f"Fichier introuvable : {screens_tsx}"
    source = screens_tsx.read_text(encoding="utf-8")

    # 1. Bouton micro dans le chat et barre vocale 5A
    assert 'data-testid="chat-mic-btn"' in source
    assert 'data-testid="screen-voice-mic-btn"' in source
    assert 'data-testid="voice-listening-status"' in source
    assert "J'écoute…" in source
    assert "fr-FR" in source
    assert "SpeechRecognition" in source
    assert "webkitSpeechRecognition" in source

    # 2. Lecture à voix haute (speechSynthesis), vitesse réglable, pause, désactivable dans Paramètres
    assert "speechSynthesis" in source
    assert "SpeechSynthesisUtterance" in source
    assert 'data-testid="chat-tts-pause-btn"' in source
    assert 'data-testid="chat-tts-rate-btn"' in source
    assert 'data-testid="settings-tts-toggle"' in source
    assert 'data-testid="settings-tts-rate-group"' in source

    # 3. Confirmation vocale ("oui", "non", silence) et badge double confirmation
    assert 'data-testid="voice-confirmation-controls"' in source
    assert 'data-testid="voice-confirm-yes-btn"' in source
    assert 'data-testid="voice-confirm-no-btn"' in source
    assert 'data-testid="voice-confirm-silence-btn"' in source
    assert 'data-testid="double-confirmation-badge"' in source

    # 4. Mode mains libres + message de confidentialité + fournisseur Whisper local dans Paramètres
    assert 'data-testid="settings-hands-free-toggle"' in source
    assert 'data-testid="voice-privacy-notice"' in source
    assert "service de reconnaissance du navigateur" in source
    assert 'data-testid="settings-stt-provider-web"' in source
    assert 'data-testid="settings-stt-provider-whisper"' in source

    # 5. Accessibilité (lecteur d'écran, focus visible, grands boutons >= 44px)
    assert 'aria-live="polite"' in source
    assert 'role="status"' in source
    assert "focus-visible:ring-2" in source
    assert "min-h-[44px]" in source

    # 6. Vérification du bundle compilé (rendu de production dist/assets/*.js)
    dist_assets = list((repo_root / "frontend" / "dist" / "assets").glob("*.js"))
    assert len(dist_assets) >= 1, "Le bundle frontend compilé doit exister dans frontend/dist/assets"
    bundle_js = "\n".join(p.read_text(encoding="utf-8") for p in dist_assets)
    assert "chat-mic-btn" in bundle_js
    assert "voice-listening-status" in bundle_js
    assert "voice-privacy-notice" in bundle_js
    assert "settings-hands-free-toggle" in bundle_js

    # 7. Respect de la règle <= 4 champs par <form>
    forms = re.findall(r"<form\b[\s\S]*?</form>", source, flags=re.IGNORECASE)
    assert len(forms) >= 4
    for idx, form_block in enumerate(forms, start=1):
        fields = re.findall(r"<(Input|Select|Textarea)\b", form_block)
        assert len(fields) <= 4, f"Formulaire #{idx} dépasse 4 champs ({len(fields)})"

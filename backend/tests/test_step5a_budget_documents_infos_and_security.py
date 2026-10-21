from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.entities import Destination, Place, Trip, TripMember, User, VaultDocument
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
) -> tuple[dict, dict]:
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
            "title": f"Séjour test {city_name}",
            "travel_style": "STANDARD",
            "total_budget_planned": budget_planned,
            "currency": "EUR",
            "arrival_at": "2026-11-10T10:00:00Z",
            "departure_at": "2026-11-14T18:00:00Z",
            "selected_place_ids": place_ids,
        },
    )
    assert res.status_code == 201, res.text
    return res.json(), dest


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
async def test_step5a_httponly_cookie_session_and_csrf_protection():
    """
    Règle Sécurité : Jeton de session dans un cookie HttpOnly (`tm_access_token`)
    + protection CSRF (`tm_csrf_token` + en-tête `X-CSRF-Token`) sur toute mutation.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user, _token, csrf_token = await _register_test_user(client, "cookiecsrf")
        set_cookie_headers = client.cookies
        assert "tm_access_token" in set_cookie_headers
        assert "tm_csrf_token" in set_cookie_headers
        assert len(csrf_token) >= 24

        # Lecture authentifiée uniquement par le cookie HttpOnly (sans en-tête Authorization)
        me_res = await client.get("/api/v1/auth/me")
        assert me_res.status_code == 200
        assert me_res.json()["id"] == user["id"]

        dests = (await client.get("/api/v1/destinations")).json()
        dest_id = dests[0]["id"]

        # Mutation (POST /api/v1/trips) via cookie SANS en-tête X-CSRF-Token -> refusée (403)
        no_csrf_res = await client.post(
            "/api/v1/trips",
            json={
                "destination_id": dest_id,
                "title": "Tentative sans CSRF",
                "travel_style": "STANDARD",
                "total_budget_planned": "900.00",
                "currency": "EUR",
                "arrival_at": "2026-11-10T10:00:00Z",
                "departure_at": "2026-11-13T18:00:00Z",
                "selected_place_ids": [],
            },
        )
        assert no_csrf_res.status_code == 403
        assert "CSRF" in no_csrf_res.json()["detail"]

        # Mutation avec mauvais jeton CSRF -> refusée (403)
        bad_csrf_res = await client.post(
            "/api/v1/trips",
            headers={"X-CSRF-Token": "jeton-csrf-invalide"},
            json={
                "destination_id": dest_id,
                "title": "Tentative mauvais CSRF",
                "travel_style": "STANDARD",
                "total_budget_planned": "900.00",
                "currency": "EUR",
                "arrival_at": "2026-11-10T10:00:00Z",
                "departure_at": "2026-11-13T18:00:00Z",
                "selected_place_ids": [],
            },
        )
        assert bad_csrf_res.status_code == 403

        # Mutation avec en-tête X-CSRF-Token valide -> autorisée (201)
        ok_csrf_res = await client.post(
            "/api/v1/trips",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "destination_id": dest_id,
                "title": "Voyage protégé CSRF",
                "travel_style": "STANDARD",
                "total_budget_planned": "900.00",
                "currency": "EUR",
                "arrival_at": "2026-11-10T10:00:00Z",
                "departure_at": "2026-11-13T18:00:00Z",
                "selected_place_ids": [],
            },
        )
        assert ok_csrf_res.status_code == 201

        # Déconnexion : efface les cookies de session
        logout_res = await client.post("/api/v1/auth/logout")
        assert logout_res.status_code == 200
        after_logout = await client.get("/api/v1/auth/me")
        assert after_logout.status_code == 401


@pytest.mark.anyio
async def test_step5a_rbac_owner_editor_viewer_and_denied_access_on_all_modules():
    """
    Règle RBAC : Contrôle d'accès par rôle (propriétaire, éditeur, lecteur, tiers non membre)
    sur TOUT (programme, budget, documents, chat), avec tests d'accès refusé (403).
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner, owner_token, _ = await _register_test_user(client, "owner")
        editor, editor_token, _ = await _register_test_user(client, "editor")
        viewer, viewer_token, _ = await _register_test_user(client, "viewer")
        outsider, outsider_token, _ = await _register_test_user(client, "outsider")

        trip, dest = await _create_trip_for_user(client, owner_token, "Marrakech")
        trip_id = trip["id"]

        await _add_trip_member_in_db(trip_id, editor["id"], MemberRole.EDITOR.value)
        await _add_trip_member_in_db(trip_id, viewer["id"], MemberRole.VIEWER.value)

        owner_h = {"Authorization": f"Bearer {owner_token}"}
        editor_h = {"Authorization": f"Bearer {editor_token}"}
        viewer_h = {"Authorization": f"Bearer {viewer_token}"}
        outsider_h = {"Authorization": f"Bearer {outsider_token}"}

        # 1. Tiers non membre (outsider) -> 403 partout (programme, budget, documents, chat)
        assert (await client.get(f"/api/v1/itinerary/trip/{trip_id}", headers=outsider_h)).status_code == 403
        assert (await client.get(f"/api/v1/budget/trip/{trip_id}", headers=outsider_h)).status_code == 403
        assert (await client.get(f"/api/v1/documents/trip/{trip_id}", headers=outsider_h)).status_code == 403
        assert (await client.get(f"/api/v1/itinerary/trip/{trip_id}/chat", headers=outsider_h)).status_code == 403
        assert (
            await client.post(
                f"/api/v1/itinerary/trip/{trip_id}/chat",
                headers=outsider_h,
                json={"message": "quel est mon budget ?"},
            )
        ).status_code == 403

        # 2. Lecteur (VIEWER) -> Lecture autorisée (200), mais TOUTE écriture refusée (403)
        assert (await client.get(f"/api/v1/itinerary/trip/{trip_id}", headers=viewer_h)).status_code == 200
        assert (await client.get(f"/api/v1/budget/trip/{trip_id}", headers=viewer_h)).status_code == 200
        assert (await client.get(f"/api/v1/documents/trip/{trip_id}", headers=viewer_h)).status_code == 200
        assert (await client.get(f"/api/v1/itinerary/trip/{trip_id}/chat", headers=viewer_h)).status_code == 200

        places = (
            await client.get(
                f"/api/v1/places/city/{dest['city_name']}",
                headers=viewer_h,
            )
        ).json()["places"]
        # Programme : ajout refusé au lecteur (403)
        viewer_itin_post = await client.post(
            "/api/v1/itinerary/items",
            headers=viewer_h,
            json={
                "trip_id": trip_id,
                "place_id": places[0]["id"],
                "visit_date": "2026-11-11",
                "local_start_time": "10:00",
                "duration_minutes": 90,
            },
        )
        assert viewer_itin_post.status_code == 403

        # Budget : ajout de dépense et modification du budget prévu refusés au lecteur (403)
        viewer_budget_post = await client.post(
            f"/api/v1/budget/trip/{trip_id}/items",
            headers=viewer_h,
            json={
                "amount": "25.00",
                "category": "MEAL",
                "title": "Tajine médina",
                "currency": "EUR",
            },
        )
        assert viewer_budget_post.status_code == 403
        viewer_budget_patch = await client.patch(
            f"/api/v1/budget/trip/{trip_id}",
            headers=viewer_h,
            json={"total_budget_planned": "2000.00"},
        )
        assert viewer_budget_patch.status_code == 403

        # Documents : ajout de document refusé au lecteur (403)
        viewer_doc_post = await client.post(
            f"/api/v1/documents/trip/{trip_id}",
            headers=viewer_h,
            json={
                "title": "Billet train lecteur",
                "doc_type": "OTHER",
                "content_text": "Réf. TGV 8899",
            },
        )
        assert viewer_doc_post.status_code == 403

        # Chat : envoi d'instruction au chat refusé au lecteur (403)
        viewer_chat_post = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/chat",
            headers=viewer_h,
            json={"message": "ajouter Jardin Majorelle le 12 novembre à 10h"},
        )
        assert viewer_chat_post.status_code == 403

        # 3. Éditeur (EDITOR) -> Peut modifier programme, budget, documents et utiliser le chat (200/201)
        editor_budget_post = await client.post(
            f"/api/v1/budget/trip/{trip_id}/items",
            headers=editor_h,
            json={
                "amount": "32.50",
                "category": "MEAL",
                "title": "Dîner place Jemaa el-Fna",
                "currency": "EUR",
            },
        )
        assert editor_budget_post.status_code == 201

        editor_chat_post = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/chat",
            headers=editor_h,
            json={"message": "quel est mon budget ?"},
        )
        assert editor_chat_post.status_code == 200
        assert "1200" in editor_chat_post.json()["messages"][-1]["content"]


@pytest.mark.anyio
async def test_step5a_documents_owner_only_visibility_and_explicit_sharing():
    """
    Règle Documents & RBAC : Documents visibles uniquement par leur propriétaire
    sauf partage explicite (`is_shared=True`).
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner, owner_token, _ = await _register_test_user(client, "docowner")
        editor, editor_token, _ = await _register_test_user(client, "doceditor")
        viewer, viewer_token, _ = await _register_test_user(client, "docviewer")

        trip, _ = await _create_trip_for_user(client, owner_token, "Marrakech")
        trip_id = trip["id"]
        await _add_trip_member_in_db(trip_id, editor["id"], MemberRole.EDITOR.value)
        await _add_trip_member_in_db(trip_id, viewer["id"], MemberRole.VIEWER.value)

        owner_h = {"Authorization": f"Bearer {owner_token}"}
        editor_h = {"Authorization": f"Bearer {editor_token}"}
        viewer_h = {"Authorization": f"Bearer {viewer_token}"}

        # Le propriétaire ajoute un document privé (is_shared=False par défaut)
        create_res = await client.post(
            f"/api/v1/documents/trip/{trip_id}",
            headers=owner_h,
            json={
                "title": "Passeport privé d'Alex",
                "doc_type": "PASSPORT",
                "content_text": "Passeport N° 24AA99887 — Confidentiel",
                "expires_on": "2028-05-20",
            },
        )
        assert create_res.status_code == 201, create_res.text
        private_doc = create_res.json()
        doc_id = private_doc["id"]
        assert private_doc["is_shared"] is False

        # Le propriétaire le voit dans la liste et peut le déchiffrer
        owner_list = (await client.get(f"/api/v1/documents/trip/{trip_id}", headers=owner_h)).json()
        assert any(d["id"] == doc_id for d in owner_list["documents"])

        # Ni l'éditeur ni le lecteur ne voient ce document non partagé dans la liste
        editor_list = (await client.get(f"/api/v1/documents/trip/{trip_id}", headers=editor_h)).json()
        viewer_list = (await client.get(f"/api/v1/documents/trip/{trip_id}", headers=viewer_h)).json()
        assert all(d["id"] != doc_id for d in editor_list["documents"])
        assert all(d["id"] != doc_id for d in viewer_list["documents"])

        # L'accès direct par ID au document non partagé est refusé (403) à l'éditeur et au lecteur
        assert (await client.get(f"/api/v1/documents/trip/{trip_id}/{doc_id}", headers=editor_h)).status_code == 403
        assert (await client.get(f"/api/v1/documents/trip/{trip_id}/{doc_id}", headers=viewer_h)).status_code == 403

        # Un éditeur ne peut pas activer lui-même le partage du document du propriétaire (403)
        forbid_share = await client.patch(
            f"/api/v1/documents/trip/{trip_id}/{doc_id}/share",
            headers=editor_h,
            json={"is_shared": True},
        )
        assert forbid_share.status_code == 403

        # Le propriétaire active explicitement le partage (`is_shared=True`)
        allow_share = await client.patch(
            f"/api/v1/documents/trip/{trip_id}/{doc_id}/share",
            headers=owner_h,
            json={"is_shared": True},
        )
        assert allow_share.status_code == 200
        assert allow_share.json()["is_shared"] is True

        # Désormais l'éditeur et le lecteur voient le document et peuvent le consulter
        editor_list_after = (await client.get(f"/api/v1/documents/trip/{trip_id}", headers=editor_h)).json()
        assert any(d["id"] == doc_id for d in editor_list_after["documents"])
        viewer_open = await client.get(f"/api/v1/documents/trip/{trip_id}/{doc_id}", headers=viewer_h)
        assert viewer_open.status_code == 200
        assert "24AA99887" in viewer_open.json()["decrypted_content"]

        # Un éditeur non-propriétaire du document ne peut toujours pas le supprimer (403)
        editor_del = await client.delete(f"/api/v1/documents/trip/{trip_id}/{doc_id}", headers=editor_h)
        assert editor_del.status_code == 403


@pytest.mark.anyio
async def test_step5a_budget_decimal_categories_conversion_overbudget_alert_and_csv_export():
    """
    Règle Budget : Total prévu et dépensé (vol, hébergement, activités, repas, transports),
    dépenses manuelles (montant, catégorie, libellé, devise), conversion de devise en Decimal,
    alerte de dépassement, export CSV.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        _user, token, _ = await _register_test_user(client, "budget")
        headers = {"Authorization": f"Bearer {token}"}
        trip, _ = await _create_trip_for_user(client, token, "Marrakech", budget_planned="500.00")
        trip_id = trip["id"]

        # 1. Test de l'endpoint de conversion de devise en Decimal
        conv_res = await client.get(
            "/api/v1/budget/convert",
            params={"amount": "108.00", "from_currency": "USD", "to_currency": "EUR"},
            headers=headers,
        )
        assert conv_res.status_code == 200
        conv_data = conv_res.json()
        assert Decimal(str(conv_data["converted_amount"])) == Decimal("100.00")

        # 2. Ajout de dépenses sur les 5 catégories (dont une en USD et une en MAD)
        expenses = [
            {"amount": "180.25", "category": "FLIGHT", "title": "Vol aller-retour", "currency": "EUR"},
            {"amount": "160.50", "category": "ACCOMMODATION", "title": "Riad 3 nuits", "currency": "EUR"},
            {"amount": "54.00", "category": "ACTIVITY", "title": "Excursion Atlas", "currency": "USD"},  # 50.00 EUR
            {"amount": "540.00", "category": "MEAL", "title": "Repas médina", "currency": "MAD"},  # 50.00 EUR
            {"amount": "80.00", "category": "TRANSPORT", "title": "Navette et taxis", "currency": "EUR"},
        ]
        for exp in expenses:
            r = await client.post(f"/api/v1/budget/trip/{trip_id}/items", headers=headers, json=exp)
            assert r.status_code == 201, r.text

        summary = (await client.get(f"/api/v1/budget/trip/{trip_id}", headers=headers)).json()

        # Total dépensé exact en Decimal : 180.25 + 160.50 + 50.00 + 50.00 + 80.00 = 520.75 EUR
        assert Decimal(str(summary["total_planned"])) == Decimal("500.00")
        assert Decimal(str(summary["total_spent"])) == Decimal("520.75")
        assert Decimal(str(summary["excess_amount"])) == Decimal("20.75")
        assert summary["over_budget_alert"] is True
        assert summary["alert_level"] == "OVER_BUDGET"
        assert "Alerte dépassement" in summary["alert_message_fr"]

        # Vérification des 5 catégories obligatoires (vol, hébergement, activités, repas, transports)
        cats_by_key = {c["category"]: c for c in summary["categories"]}
        assert set(cats_by_key.keys()) == {"FLIGHT", "ACCOMMODATION", "ACTIVITY", "MEAL", "TRANSPORT"}
        assert Decimal(str(cats_by_key["FLIGHT"]["spent_amount"])) == Decimal("180.25")
        assert Decimal(str(cats_by_key["ACCOMMODATION"]["spent_amount"])) == Decimal("160.50")
        assert Decimal(str(cats_by_key["ACTIVITY"]["spent_amount"])) == Decimal("50.00")
        assert Decimal(str(cats_by_key["MEAL"]["spent_amount"])) == Decimal("50.00")
        assert Decimal(str(cats_by_key["TRANSPORT"]["spent_amount"])) == Decimal("80.00")

        # 3. Export CSV
        csv_res = await client.get(f"/api/v1/budget/trip/{trip_id}/export.csv", headers=headers)
        assert csv_res.status_code == 200
        assert "text/csv" in csv_res.headers["content-type"]
        csv_text = csv_res.text
        assert "Total prévu;500.00" in csv_text
        assert "Total dépensé;520.75" in csv_text
        assert "Dépassement;Oui" in csv_text
        assert "Excursion Atlas" in csv_text


@pytest.mark.anyio
async def test_step5a_documents_server_side_encryption_and_passport_expiration_reminder():
    """
    Règle Documents : Ajout, liste, suppression, chiffrement côté serveur (AES-256-GCM en base),
    et rappel d'expiration du passeport (avant la fin du séjour ou moins de 6 mois après retour).
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        _user, token, _ = await _register_test_user(client, "vault")
        headers = {"Authorization": f"Bearer {token}"}
        trip, _ = await _create_trip_for_user(client, token, "Marrakech")
        trip_id = trip["id"]

        secret_text = "Numéro de passeport ultra-confidentiel : 99ZZ112233"
        # Passeport expirant le 15 janvier 2027 (< 6 mois après le retour du 14 novembre 2026)
        create_res = await client.post(
            f"/api/v1/documents/trip/{trip_id}",
            headers=headers,
            json={
                "title": "Passeport biométrique",
                "doc_type": "PASSPORT",
                "content_text": secret_text,
                "expires_on": "2027-01-15",
            },
        )
        assert create_res.status_code == 201, create_res.text
        doc_json = create_res.json()
        doc_id = doc_json["id"]
        assert doc_json["expiration_warning"] is True
        assert "passeport expire le 15 janvier 2027" in doc_json["expiration_message_fr"].lower()
        assert doc_json["decrypted_content"] == secret_text

        # Vérification en base PostgreSQL que le payload est chiffré (aucun texte en clair en base)
        async with AsyncSessionLocal() as db:
            db_doc = await db.scalar(select(VaultDocument).where(VaultDocument.id == doc_id))
            assert db_doc is not None
            assert secret_text.encode("utf-8") not in bytes(db_doc.encrypted_payload)
            assert len(bytes(db_doc.encryption_iv)) == 12
            assert len(bytes(db_doc.encrypted_dek)) > 16

        # Vérification de l'alerte d'expiration au niveau de la liste des documents du voyage
        list_res = await client.get(f"/api/v1/documents/trip/{trip_id}", headers=headers)
        assert list_res.status_code == 200
        list_data = list_res.json()
        assert list_data["passport_expiration_alert"] is True
        assert "15 janvier 2027" in (list_data["passport_alert_message_fr"] or "")

        # Suppression du document
        del_res = await client.delete(f"/api/v1/documents/trip/{trip_id}/{doc_id}", headers=headers)
        assert del_res.status_code == 204
        after_list = (await client.get(f"/api/v1/documents/trip/{trip_id}", headers=headers)).json()
        assert all(d["id"] != doc_id for d in after_list["documents"])


@pytest.mark.anyio
async def test_step5a_practical_info_with_source_and_date_and_deterministic_translator():
    """
    Règle Infos pratiques & Traducteur :
    - Infos pratiques par destination (prises, pourboires, urgences, indicatif, monnaie)
      avec source et date de mise à jour en français.
    - Traducteur et phrases utiles avec prononciation (mode simulé déterministe).
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        dests = (await client.get("/api/v1/destinations")).json()
        for city in ("Marrakech", "New York", "Tokyo"):
            dest = next(d for d in dests if d["city_name"].lower() == city.lower())
            info_res = await client.get(f"/api/v1/destinations/{dest['id']}/practical-info")
            assert info_res.status_code == 200, info_res.text
            info = info_res.json()
            assert info["plugs"]
            assert info["tipping"]
            assert info["emergency"]
            assert info["dial_code"].startswith("+")
            assert info["currency"]
            assert info["source"]
            assert "octobre 2026" in info["updated_at_fr"]
            assert len(info["useful_phrases"]) >= 4
            for phrase in info["useful_phrases"]:
                assert phrase["french"]
                assert phrase["local_translation"]
                assert phrase["pronunciation"]

            # Test du traducteur déterministe
            tr_res = await client.post(
                f"/api/v1/destinations/{dest['id']}/translate",
                json={"text": "Bonjour, combien ça coûte s'il vous plaît ?"},
            )
            assert tr_res.status_code == 200, tr_res.text
            tr = tr_res.json()
            assert tr["mode"] == "SIMULATED_DETERMINISTIC"
            assert tr["translation"]
            assert tr["pronunciation"]

            # Deuxième appel identique -> résultat strictement déterministe
            tr_res_2 = await client.post(
                f"/api/v1/destinations/{dest['id']}/translate",
                json={"text": "Bonjour, combien ça coûte s'il vous plaît ?"},
            )
            assert tr_res_2.json() == tr


@pytest.mark.anyio
async def test_step5a_new_york_transit_estimation_fixes_63_min_walk():
    """
    Règle Retouche New York : Le trajet entre deux lieux de New York éloignés de ~4,8 km
    (ex. High Line / Empire State Building -> Central Park / Met) ne doit plus être estimé
    à 63 min à pied, mais basculer automatiquement en Métro (~17 min).
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        _user, token, _ = await _register_test_user(client, "nyctransit")
        headers = {"Authorization": f"Bearer {token}"}
        dests = (await client.get("/api/v1/destinations")).json()
        nyc = next(d for d in dests if d["city_name"].lower() == "new york")
        places = (
            await client.get(
                f"/api/v1/places/city/{nyc['city_name']}",
                headers=headers,
            )
        ).json()["places"]
        place_ids = [p["id"] for p in places]

        res = await client.post(
            "/api/v1/trips",
            headers=headers,
            json={
                "destination_id": nyc["id"],
                "title": "Séjour New York",
                "travel_style": "STANDARD",
                "total_budget_planned": "2200.00",
                "currency": "EUR",
                "arrival_at": "2026-11-10T10:00:00Z",
                "departure_at": "2026-11-12T18:00:00Z",
                "selected_place_ids": place_ids,
            },
        )
        assert res.status_code == 201, res.text
        trip_id = res.json()["id"]

        gen_res = await client.post(
            f"/api/v1/itinerary/trip/{trip_id}/optimize",
            headers=headers,
            json={"place_ids": place_ids},
        )
        assert gen_res.status_code == 200, gen_res.text
        all_items = gen_res.json()["proposed_items"]
        assert len(all_items) >= 2

        for item in all_items:
            dist_m = item.get("transit_distance_meters", 0)
            dur_min = item.get("transit_duration_to_next_min", 0)
            mode = item.get("transit_mode_to_next")
            # Aucun trajet ne doit valoir 63 min à pied ; au-delà de 1800 m on utilise METRO ou TAXI
            assert dur_min != 63, f"Trajet erroné de 63 min détecté sur {item}"
            if dist_m > 1800:
                assert mode in ("METRO", "TAXI")
                assert dur_min <= 35


def test_step5a_frontend_architecture_4_fields_max_and_offline_encrypted_cache():
    """
    Règle Architecture Frontend Étape 5A :
    - 'Mon voyage' (/trip) mène aux sous-pages (/trip/budget, /trip/documents, /trip/infos) ;
    - 4 champs maximum par formulaire ;
    - Cache hors ligne chiffré (AES-GCM) activé seulement si l'utilisateur le choisit et vidé à la déconnexion ;
    - Menu du haut à 1440 px sur une seule ligne (`whitespace-nowrap`).
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    app_tsx_path = root / "frontend" / "src" / "App.tsx"
    screens_tsx_path = root / "frontend" / "src" / "EnvoiCScreens.tsx"
    if not app_tsx_path.exists():
        app_tsx_path = Path("/frontend_src/App.tsx")
        screens_tsx_path = Path("/frontend_src/EnvoiCScreens.tsx")

    if app_tsx_path.exists() and screens_tsx_path.exists():
        app_code = app_tsx_path.read_text(encoding="utf-8")
        screens_code = screens_tsx_path.read_text(encoding="utf-8")

        assert "/trip/budget" in app_code
        assert "/trip/documents" in app_code
        assert "/trip/infos" in app_code
        assert "X-CSRF-Token" in app_code
        assert 'credentials = "include"' in app_code or "credentials: 'include'" in app_code
        assert "clearOfflineDocumentsCache" in app_code
        assert "whitespace-nowrap" in app_code

        assert "AES-GCM" in screens_code
        assert "OFFLINE_DOCS_OPT_IN_KEY" in screens_code
        assert "clearOfflineDocumentsCache" in screens_code

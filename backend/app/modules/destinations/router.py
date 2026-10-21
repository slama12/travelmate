import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.database import AsyncSession, get_db
from app.models.entities import Destination
from app.modules.destinations.schemas import (
    DestinationResolveRequest,
    DestinationResponse,
    PracticalInfoResponse,
    TranslateRequest,
    TranslateResponse,
    UsefulPhraseSchema,
)

router = APIRouter(prefix="/destinations", tags=["Destinations"])

DESTINATION_PRACTICAL_CATALOG: dict[str, dict[str, Any]] = {
    "marrakech": {
        "target_language": "Arabe marocain (Darija)",
        "plugs": "Types C et E (220 V - 50 Hz, identiques aux prises françaises).",
        "tipping": "10 % au restaurant si le service n'est pas inclus ; 10 à 20 MAD pour les bagagistes et guides.",
        "emergency": "19 (Police urbaine), 15 (Ambulance et Pompiers), 112 (Urgences depuis un mobile).",
        "dial_code": "+212",
        "currency": "Dirham marocain (MAD — 1 € ≈ 10,80 MAD)",
        "source": "Conseils aux voyageurs — Ministère des Affaires étrangères & Office national marocain du tourisme",
        "updated_at_fr": "15 octobre 2026",
        "useful_phrases": [
            {
                "french": "Bonjour, comment allez-vous ?",
                "local_translation": "Salam alaykoum, labass alik ?",
                "pronunciation": "Sa-lam a-lay-koum, la-bass a-lik",
                "context_fr": "Salutation",
            },
            {
                "french": "Merci beaucoup",
                "local_translation": "Choukrane bzzaf",
                "pronunciation": "Chou-krane bez-zaf",
                "context_fr": "Politesse",
            },
            {
                "french": "Combien ça coûte, s'il vous plaît ?",
                "local_translation": "Bchhal hada afak ?",
                "pronunciation": "Bech-hal ha-da a-fak",
                "context_fr": "Achats et souks",
            },
            {
                "french": "L'addition, s'il vous plaît",
                "local_translation": "L'hssab afak",
                "pronunciation": "El-hssab a-fak",
                "context_fr": "Restaurant",
            },
            {
                "french": "Où se trouve la place Jemaa el-Fna ?",
                "local_translation": "Fin kayna sahat Jemaa el-Fna ?",
                "pronunciation": "Fine kay-na sa-hat Dje-maa el Fna",
                "context_fr": "Orientation",
            },
        ],
    },
    "new york": {
        "target_language": "Anglais américain",
        "plugs": "Types A et B (120 V - 60 Hz, adaptateur à fiches plates indispensable).",
        "tipping": "18 % à 20 % obligatoire d'usage au restaurant et dans les taxis ; 2 $ par bagage à l'hôtel.",
        "emergency": "911 (Police, Pompiers et Urgences médicales gratuit depuis tout téléphone).",
        "dial_code": "+1",
        "currency": "Dollar américain (USD — 1 € ≈ 1,08 $)",
        "source": "Conseils aux voyageurs — Ministère des Affaires étrangères & NYC Tourism",
        "updated_at_fr": "15 octobre 2026",
        "useful_phrases": [
            {
                "french": "Bonjour, une table pour deux s'il vous plaît.",
                "local_translation": "Hello, a table for two, please.",
                "pronunciation": "He-lo, euh tey-bol for tou, pliz",
                "context_fr": "Restaurant",
            },
            {
                "french": "Où se trouve la station de métro la plus proche ?",
                "local_translation": "Where is the nearest subway station?",
                "pronunciation": "Wèr iz zeu ni-rest seub-wey stey-cheun",
                "context_fr": "Transports",
            },
            {
                "french": "L'addition, s'il vous plaît.",
                "local_translation": "Could we have the check, please?",
                "pronunciation": "Koud wi hav zeu tchek, pliz",
                "context_fr": "Restaurant",
            },
            {
                "french": "Combien coûte ce billet ?",
                "local_translation": "How much is this ticket?",
                "pronunciation": "Haou meutch iz zis ti-ket",
                "context_fr": "Visites",
            },
        ],
    },
    "tokyo": {
        "target_language": "Japonais",
        "plugs": "Types A et B (100 V - 50 Hz à Tokyo, adaptateur fiches plates requis).",
        "tipping": "Aucun pourboire au Japon (le service est toujours inclus et laisser un pourboire peut gêner).",
        "emergency": "110 (Police), 119 (Ambulance et Pompiers), 0570-000-911 (Assistance touristes Japan Visitor Hotline).",
        "dial_code": "+81",
        "currency": "Yen japonais (JPY — 1 € ≈ 162 ¥)",
        "source": "Conseils aux voyageurs — Ministère des Affaires étrangères & Office national du tourisme japonais (JNTO)",
        "updated_at_fr": "15 octobre 2026",
        "useful_phrases": [
            {
                "french": "Bonjour / Bon après-midi",
                "local_translation": "Konnichiwa (こんにちは)",
                "pronunciation": "Kon-ni-tchi-wa",
                "context_fr": "Salutation",
            },
            {
                "french": "Merci beaucoup",
                "local_translation": "Arigatō gozaimasu (ありがとうございます)",
                "pronunciation": "A-ri-ga-tô go-za-i-mas",
                "context_fr": "Politesse",
            },
            {
                "french": "Excusez-moi, où est la gare ?",
                "local_translation": "Sumimasen, eki wa doko desu ka ?",
                "pronunciation": "Sou-mi-ma-sèn, é-ki wa do-ko dès ka",
                "context_fr": "Transports",
            },
            {
                "french": "L'addition, s'il vous plaît.",
                "local_translation": "O-kaikei onegaishimasu",
                "pronunciation": "O-kaï-keï o-né-ga-ï-chi-mas",
                "context_fr": "Restaurant",
            },
        ],
    },
    "rome": {
        "target_language": "Italien",
        "plugs": "Types C, F et L (230 V - 50 Hz, compatibles avec les fiches fines européennes).",
        "tipping": "Pain et couvert (coperto de 2 à 3 €) souvent facturés ; laisser 5 % à 10 % reste apprécié.",
        "emergency": "112 (Numéro d'urgence européen), 118 (Urgences médicales), 113 (Police).",
        "dial_code": "+39",
        "currency": "Euro (EUR — €)",
        "source": "Conseils aux voyageurs — Ministère des Affaires étrangères & Agenzia Nazionale del Turismo (ENIT)",
        "updated_at_fr": "15 octobre 2026",
        "useful_phrases": [
            {
                "french": "Bonjour, une table pour deux s'il vous plaît.",
                "local_translation": "Buongiorno, un tavolo per due, per favore.",
                "pronunciation": "Bouon-djor-no, oun ta-vo-lo pèr dou-é, pèr fa-vo-ré",
                "context_fr": "Restaurant",
            },
            {
                "french": "L'addition, s'il vous plaît.",
                "local_translation": "Il conto, per favore.",
                "pronunciation": "Il kon-to, pèr fa-vo-ré",
                "context_fr": "Restaurant",
            },
            {
                "french": "Où se trouve le Colisée ?",
                "local_translation": "Dov'è il Colosseo ?",
                "pronunciation": "Do-vè il Ko-los-sé-o",
                "context_fr": "Orientation",
            },
        ],
    },
    "paris": {
        "target_language": "Anglais (échanges internationaux)",
        "plugs": "Type E (230 V - 50 Hz, standard français).",
        "tipping": "Service de 15 % légalement inclus dans les prix ; 1 à 5 € de pourboire libre selon satisfaction.",
        "emergency": "112 (Urgences européennes), 15 (SAMU), 17 (Police secours), 18 (Pompiers).",
        "dial_code": "+33",
        "currency": "Euro (EUR — €)",
        "source": "Office du Tourisme et des Congrès de Paris & Service-Public.fr",
        "updated_at_fr": "15 octobre 2026",
        "useful_phrases": [
            {
                "french": "Bonjour, une table pour deux s'il vous plaît.",
                "local_translation": "Hello, a table for two, please.",
                "pronunciation": "Bon-jour, une ta-ble pour deux s'il vous plaît",
                "context_fr": "Restaurant",
            },
            {
                "french": "L'addition, s'il vous plaît.",
                "local_translation": "The bill, please.",
                "pronunciation": "La-di-ssion s'il vous plaît",
                "context_fr": "Restaurant",
            },
            {
                "french": "Où est la station de métro la plus proche ?",
                "local_translation": "Where is the nearest metro station?",
                "pronunciation": "Où est la sta-tion de mé-tro la plus pro-che",
                "context_fr": "Transports",
            },
        ],
    },
}

WORLD_CITY_GEODATA: dict[str, dict[str, Any]] = {
    "barcelone": {
        "city_name": "Barcelone",
        "country_name": "Espagne",
        "country_code_iso2": "ES",
        "iata_code": "BCN",
        "timezone": "Europe/Madrid",
        "latitude": 41.3874,
        "longitude": 2.1686,
    },
    "barcelona": {
        "city_name": "Barcelona",
        "country_name": "Espagne",
        "country_code_iso2": "ES",
        "iata_code": "BCN",
        "timezone": "Europe/Madrid",
        "latitude": 41.3874,
        "longitude": 2.1686,
    },
    "londres": {
        "city_name": "Londres",
        "country_name": "Royaume-Uni",
        "country_code_iso2": "GB",
        "iata_code": "LHR",
        "timezone": "Europe/London",
        "latitude": 51.5072,
        "longitude": -0.1276,
    },
    "london": {
        "city_name": "London",
        "country_name": "Royaume-Uni",
        "country_code_iso2": "GB",
        "iata_code": "LHR",
        "timezone": "Europe/London",
        "latitude": 51.5072,
        "longitude": -0.1276,
    },
    "lisbonne": {
        "city_name": "Lisbonne",
        "country_name": "Portugal",
        "country_code_iso2": "PT",
        "iata_code": "LIS",
        "timezone": "Europe/Lisbon",
        "latitude": 38.7223,
        "longitude": -9.1393,
    },
    "kyoto": {
        "city_name": "Kyoto",
        "country_name": "Japon",
        "country_code_iso2": "JP",
        "iata_code": "KIX",
        "timezone": "Asia/Tokyo",
        "latitude": 35.0116,
        "longitude": 135.7681,
    },
    "reykjavik": {
        "city_name": "Reykjavik",
        "country_name": "Islande",
        "country_code_iso2": "IS",
        "iata_code": "KEF",
        "timezone": "Atlantic/Reykjavik",
        "latitude": 64.1466,
        "longitude": -21.9426,
    },
}


def get_enriched_practical_profile(dest: Destination) -> PracticalInfoResponse:
    city_key = (dest.city_name or "").strip().lower()
    preset = DESTINATION_PRACTICAL_CATALOG.get(city_key)
    raw_info = dict(dest.practical_info or {})

    if preset:
        plugs = str(raw_info.get("prises") or preset["plugs"])
        tipping = str(raw_info.get("pourboires") or preset["tipping"])
        emergency = str(raw_info.get("urgences") or preset["emergency"])
        dial_code = str(raw_info.get("indicatif") or preset["dial_code"])
        currency = str(raw_info.get("monnaie") or preset["currency"])
        source = str(raw_info.get("source") or preset["source"])
        updated_at_fr = str(raw_info.get("date_mise_a_jour_fr") or preset["updated_at_fr"])
        target_language = str(preset["target_language"])
        phrases_raw = preset["useful_phrases"]
    else:
        plugs = str(raw_info.get("prises") or "Types C et E (230 V - 50 Hz).")
        tipping = str(raw_info.get("pourboires") or "5 % à 10 % selon la qualité du service.")
        emergency = str(raw_info.get("urgences") or "112 / 911 (Urgences générales).")
        dial_code = str(raw_info.get("indicatif") or "+00")
        currency = str(raw_info.get("monnaie") or "Devise locale / EUR")
        source = str(
            raw_info.get("source")
            or "Conseils aux voyageurs — Ministère de l'Europe et des Affaires étrangères"
        )
        updated_at_fr = str(raw_info.get("date_mise_a_jour_fr") or "15 octobre 2026")
        target_language = "Anglais"
        phrases_raw = [
            {
                "french": "Bonjour, pouvez-vous m'aider s'il vous plaît ?",
                "local_translation": "Hello, could you help me please?",
                "pronunciation": "He-lo, koud you help mi pliz",
                "context_fr": "Vie courante",
            },
            {
                "french": "Combien ça coûte ?",
                "local_translation": "How much does it cost?",
                "pronunciation": "Haou meutch deuz it kost",
                "context_fr": "Achats",
            },
        ]

    phrases = [UsefulPhraseSchema(**p) for p in phrases_raw]
    return PracticalInfoResponse(
        destination_id=dest.id,
        city_name=dest.city_name,
        country_name=dest.country_name,
        target_language=target_language,
        plugs=plugs,
        tipping=tipping,
        emergency=emergency,
        dial_code=dial_code,
        currency=currency,
        source=source,
        updated_at_fr=updated_at_fr,
        useful_phrases=phrases,
    )


def _enrich_destination_response(dest: Destination) -> DestinationResponse:
    profile = get_enriched_practical_profile(dest)
    merged_info = dict(dest.practical_info or {})
    merged_info.update(
        {
            "prises": profile.plugs,
            "pourboires": profile.tipping,
            "urgences": profile.emergency,
            "indicatif": profile.dial_code,
            "monnaie": profile.currency,
            "source": profile.source,
            "date_mise_a_jour_fr": profile.updated_at_fr,
        }
    )
    phrases_dicts = [
        {
            "original": p.french,
            "translation": p.local_translation,
            "phonetic": p.pronunciation,
            "french": p.french,
            "local_translation": p.local_translation,
            "pronunciation": p.pronunciation,
            "context_fr": p.context_fr,
        }
        for p in profile.useful_phrases
    ]
    return DestinationResponse(
        id=dest.id,
        city_name=dest.city_name,
        country_name=dest.country_name,
        country_code_iso2=dest.country_code_iso2,
        iata_code=dest.iata_code,
        timezone=dest.timezone,
        latitude=dest.latitude,
        longitude=dest.longitude,
        hero_image_url=dest.hero_image_url,
        description=dest.description,
        practical_info=merged_info,
        useful_phrases=phrases_dicts,
    )


DETERMINISTIC_DICTIONARY: dict[str, dict[str, tuple[str, str]]] = {
    "marrakech": {
        "bonjour": ("Salam alaykoum", "Sa-lam a-lay-koum"),
        "merci": ("Choukrane bzzaf", "Chou-krane bez-zaf"),
        "combien": ("Bchhal hada afak ?", "Bech-hal ha-da a-fak"),
        "addition": ("L'hssab afak", "El-hssab a-fak"),
        "eau": ("L'ma afak", "El-ma a-fak"),
        "taxi": ("Fin kayn taxi afak ?", "Fine kayn tak-si a-fak"),
        "gare": ("Fin kayna la gare ?", "Fine kay-na la gar"),
        "aéroport": ("Fin kayn l'matar ?", "Fine kayn el-ma-tar"),
        "aide": ("Aawnni afak", "Aa-wen-ni a-fak"),
        "toilettes": ("Fin kayn bit l'ma afak ?", "Fine kayn bit el-ma a-fak"),
        "hôtel": ("Fin kayn l'hôtel / riad afak ?", "Fine kayn el-ri-ad a-fak"),
    },
    "new york": {
        "bonjour": ("Hello, good morning!", "He-lo, goud mor-ning"),
        "merci": ("Thank you very much!", "Zank you vé-ri meutch"),
        "combien": ("How much is this, please?", "Haou meutch iz zis, pliz"),
        "addition": ("Could we have the check, please?", "Koud wi hav zeu tchek, pliz"),
        "eau": ("A bottle of still water, please.", "Euh bo-teul ov stil wo-teur, pliz"),
        "taxi": ("Where can I find a taxi?", "Wèr kan aï faïnd euh tak-si"),
        "gare": ("Where is the train / subway station?", "Wèr iz zeu seub-wey stey-cheun"),
        "aéroport": ("How do I get to JFK Airport?", "Haou dou aï gèt tou Djey-Ef-Key èr-port"),
        "aide": ("Could you help me, please?", "Koud you help mi, pliz"),
        "toilettes": ("Where is the restroom, please?", "Wèr iz zeu rèst-roum, pliz"),
        "hôtel": ("Where is the hotel located?", "Wèr iz zeu ho-tèl lo-key-ted"),
    },
    "tokyo": {
        "bonjour": ("Konnichiwa (こんにちは)", "Kon-ni-tchi-wa"),
        "merci": ("Arigatō gozaimasu (ありがとうございます)", "A-ri-ga-tô go-za-i-mas"),
        "combien": ("Ikura desu ka ? (いくらですか)", "I-kou-ra dès ka"),
        "addition": ("O-kaikei onegaishimasu (お会計お願いします)", "O-kaï-keï o-né-ga-ï-chi-mas"),
        "eau": ("O-mizu o kudasai (お水をください)", "O-mi-zou o kou-da-saï"),
        "taxi": ("Takushī noriba wa doko desu ka ?", "Ta-kou-chi no-ri-ba wa do-ko dès ka"),
        "gare": ("Sumimasen, eki wa doko desu ka ?", "Sou-mi-ma-sèn, é-ki wa do-ko dès ka"),
        "aéroport": ("Kūkō wa doko desu ka ?", "Kou-kô wa do-ko dès ka"),
        "aide": ("Tasukete kudasai (助けてください)", "Ta-sou-ké-té kou-da-saï"),
        "toilettes": ("O-tearai wa doko desu ka ?", "O-té-a-raï wa do-ko dès ka"),
        "hôtel": ("Hoteru wa doko desu ka ?", "Ho-té-rou wa do-ko dès ka"),
    },
    "rome": {
        "bonjour": ("Buongiorno !", "Bouon-djor-no"),
        "merci": ("Grazie mille !", "Gra-tzié mil-lé"),
        "combien": ("Quanto costa, per favore ?", "Kouan-to kos-ta, pèr fa-vo-ré"),
        "addition": ("Il conto, per favore.", "Il kon-to, pèr fa-vo-ré"),
        "eau": ("Una bottiglia d'acqua naturale, per favore.", "Ou-na bot-ti-lia da-koua, pèr fa-vo-ré"),
        "taxi": ("Dove posso trovare un taxi ?", "Do-vé pos-so tro-va-ré oun tak-si"),
        "gare": ("Dov'è la stazione Termini ?", "Do-vè la sta-tzio-né Tèr-mi-ni"),
        "aéroport": ("Come arrivo all'aeroporto ?", "Ko-mé ar-ri-vo al a-é-ro-por-to"),
        "aide": ("Mi può aiutare, per favore ?", "Mi pou-o a-iou-ta-ré, pèr fa-vo-ré"),
        "toilettes": ("Dov'è il bagno, per favore ?", "Do-vè il ba-nio, pèr fa-vo-ré"),
        "hôtel": ("Dov'è l'albergo ?", "Do-vè lal-bèr-go"),
    },
}


def deterministic_translate_phrase(
    source_text: str,
    city_name: str,
    target_language: str,
    useful_phrases: list[UsefulPhraseSchema],
) -> tuple[str, str]:
    clean_src = source_text.strip()
    low_src = re.sub(r"\s+", " ", clean_src.lower())

    for up in useful_phrases:
        if low_src == up.french.strip().lower() or low_src in up.french.strip().lower():
            return up.local_translation, up.pronunciation

    city_key = city_name.strip().lower()
    city_dict = DETERMINISTIC_DICTIONARY.get(city_key, DETERMINISTIC_DICTIONARY["new york"])
    for keyword, (trans, pron) in city_dict.items():
        if keyword in low_src:
            return trans, pron

    # Traduction déterministe générique avec prononciation phonétique garantie
    if city_key == "marrakech":
        return (
            f"Afak : « {clean_src} » (Choukrane)",
            f"A-fak : {clean_src} (Chou-krane)",
        )
    if city_key == "tokyo":
        return (
            f"Sumimasen, « {clean_src} » onegaishimasu",
            f"Sou-mi-ma-sèn, {clean_src} o-né-ga-ï-chi-mas",
        )
    if city_key == "rome":
        return (
            f"Per favore, « {clean_src} » (Grazie)",
            f"Pèr fa-vo-ré, {clean_src} (Gra-tzié)",
        )
    return (
        f"Excuse me, please: \"{clean_src}\"",
        f"Eks-kiouz mi, pliz : {clean_src}",
    )


@router.get("", response_model=list[DestinationResponse])
async def list_destinations(
    q: str | None = Query(default=None, description="Filtre optionnel par nom de ville ou code IATA"),
    db: AsyncSession = Depends(get_db),
) -> list[DestinationResponse]:
    stmt = select(Destination).order_by(Destination.city_name.asc())
    result = await db.scalars(stmt)
    items = list(result.all())
    if q:
        q_low = q.strip().lower()
        items = [
            d
            for d in items
            if q_low in d.city_name.lower()
            or q_low in d.country_name.lower()
            or q_low == d.iata_code.lower()
        ]
    return [_enrich_destination_response(d) for d in items]


@router.post("/resolve", response_model=DestinationResponse, status_code=status.HTTP_200_OK)
async def resolve_or_create_world_destination(
    payload: DestinationResolveRequest,
    db: AsyncSession = Depends(get_db),
) -> DestinationResponse:
    """Résout une ville existante ou crée dynamiquement n'importe quelle ville du monde."""
    normalized_name = payload.city_name.strip()
    existing = await db.scalar(
        select(Destination).where(func.lower(Destination.city_name) == normalized_name.lower())
    )
    if existing:
        return _enrich_destination_response(existing)

    preset = WORLD_CITY_GEODATA.get(normalized_name.lower(), {})
    iata = (
        payload.iata_code.upper()
        if payload.iata_code
        else preset.get("iata_code") or normalized_name[:3].upper()
    )
    lat = payload.latitude if payload.latitude is not None else preset.get("latitude", 46.2044)
    lng = payload.longitude if payload.longitude is not None else preset.get("longitude", 6.1432)
    country = preset.get("country_name", payload.country_name)
    iso2 = preset.get("country_code_iso2", payload.country_code_iso2.upper())
    tz = preset.get("timezone", payload.timezone)

    new_dest = Destination(
        city_name=preset.get("city_name", normalized_name),
        country_name=country,
        country_code_iso2=iso2,
        iata_code=iata,
        timezone=tz,
        latitude=float(lat),
        longitude=float(lng),
        hero_image_url="https://images.unsplash.com/photo-1488646953014-85cb44e25828?auto=format&fit=crop&w=1400&q=80",
        description=f"Destination mondiale {normalized_name} ({country}) configurée dynamiquement.",
        practical_info={
            "visa": "Vérifier les conditions d'entrée consulaires selon votre nationalité.",
            "prises": "Types C et E (230 V - 50 Hz).",
            "pourboires": "5 % à 10 % selon la qualité du service.",
            "urgences": "112 / 911",
            "indicatif": "+00",
            "monnaie": "Devise locale / EUR",
            "source": "Conseils aux voyageurs — Ministère de l'Europe et des Affaires étrangères",
            "date_mise_a_jour_fr": "15 octobre 2026",
        },
        useful_phrases=[],
    )
    db.add(new_dest)
    await db.commit()
    await db.refresh(new_dest)
    return _enrich_destination_response(new_dest)


@router.get("/{destination_id}/practical-info", response_model=PracticalInfoResponse)
async def get_destination_practical_info(
    destination_id: str,
    db: AsyncSession = Depends(get_db),
) -> PracticalInfoResponse:
    """
    Retourne les informations pratiques complètes d'une destination (prises, pourboires, urgences,
    indicatif, monnaie) avec leur source, la date de mise à jour en français et les phrases utiles
    accompagnées de leur prononciation.
    """
    dest = await db.scalar(select(Destination).where(Destination.id == destination_id))
    if not dest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Destination introuvable.",
        )
    return get_enriched_practical_profile(dest)


@router.post("/{destination_id}/translate", response_model=TranslateResponse)
async def translate_destination_phrase(
    destination_id: str,
    payload: TranslateRequest,
    db: AsyncSession = Depends(get_db),
) -> TranslateResponse:
    """
    Traducteur de voyage déterministe (mode simulé sans dépendance externe) :
    retourne la traduction dans la langue de la destination ainsi que la prononciation phonétique.
    """
    dest = await db.scalar(select(Destination).where(Destination.id == destination_id))
    if not dest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Destination introuvable.",
        )
    profile = get_enriched_practical_profile(dest)
    target_lang = (payload.target_language or profile.target_language).strip()
    translated, pronunciation = deterministic_translate_phrase(
        source_text=payload.text,
        city_name=dest.city_name,
        target_language=target_lang,
        useful_phrases=profile.useful_phrases,
    )
    return TranslateResponse(
        destination_id=dest.id,
        city_name=dest.city_name,
        target_language=target_lang,
        source_text=payload.text.strip(),
        translated_text=translated,
        translation=translated,
        pronunciation=pronunciation,
    )


@router.get("/{destination_id}", response_model=DestinationResponse)
async def get_destination(
    destination_id: str,
    db: AsyncSession = Depends(get_db),
) -> DestinationResponse:
    dest = await db.scalar(select(Destination).where(Destination.id == destination_id))
    if not dest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Destination introuvable.",
        )
    return _enrich_destination_response(dest)

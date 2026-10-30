from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import quote, unquote, urlparse
import httpx

from app.core.seed import SEED_DESTINATIONS
from app.modules.places.world_place_photos_service import (
    COMMONS_API_URL,
    MIN_IMAGE_WIDTH_PX,
    TARGET_THUMB_WIDTH_PX,
    TRAVELMATE_USER_AGENT,
    build_commons_thumbnail_url,
    extract_author_from_extmetadata,
    normalize_and_validate_free_license,
    normalize_commons_file_title,
    validate_file_title_quality,
)

# Exact mapping of the 70 demo places to their canonical Wikidata/Wikipedia targets (or None when no exact entity exists)
PLACE_WIKIMEDIA_TARGETS: dict[tuple[str, str], dict[str, Any]] = {
    # PARIS (14)
    ("Paris", "Musée du Louvre"): {"qid": "Q19675", "wp_title": "Musée du Louvre", "wp_lang": "fr", "aliases": ["Louvre", "Musee du Louvre", "Palais du Louvre"]},
    ("Paris", "Musée d'Orsay"): {"qid": "Q23402", "wp_title": "Musée d'Orsay", "wp_lang": "fr", "aliases": ["Orsay", "Musee d Orsay", "Gare d'Orsay"]},
    ("Paris", "Sainte-Chapelle"): {"qid": "Q193193", "wp_title": "Sainte-Chapelle", "wp_lang": "fr", "aliases": ["Sainte Chapelle", "Ste-Chapelle"]},
    ("Paris", "Centre Pompidou"): {"qid": "Q178065", "wp_title": "Centre national d'art et de culture Georges-Pompidou", "wp_lang": "fr", "aliases": ["Pompidou", "Beaubourg", "Centre Georges-Pompidou"]},
    ("Paris", "Arc de Triomphe"): {"qid": "Q153356", "wp_title": "Arc de triomphe de l'Étoile", "wp_lang": "fr", "aliases": ["Arc de Triomphe", "Etoile"]},
    ("Paris", "Jardin du Luxembourg"): {"qid": "Q309458", "wp_title": "Jardin du Luxembourg", "wp_lang": "fr", "aliases": ["Luxembourg", "Palais du Luxembourg"]},
    ("Paris", "Parc des Buttes-Chaumont"): {"qid": "Q730522", "wp_title": "Parc des Buttes-Chaumont", "wp_lang": "fr", "aliases": ["Buttes-Chaumont", "Buttes Chaumont"]},
    ("Paris", "Jardin des Tuileries"): {"qid": "Q217523", "wp_title": "Jardin des Tuileries", "wp_lang": "fr", "aliases": ["Tuileries"]},
    ("Paris", "Le Jules Verne (Tour Eiffel)"): {"qid": "Q243", "wp_title": "Tour Eiffel", "wp_lang": "fr", "aliases": ["Tour Eiffel", "Eiffel Tower", "Eiffel", "Le Jules Verne"]},
    ("Paris", "Bouillon Chartier Grands Boulevards"): {"qid": "Q2921698", "wp_title": "Bouillon Chartier", "wp_lang": "fr", "aliases": ["Chartier", "Bouillon Chartier"]},
    ("Paris", "Le Comptoir du Relais (Odéon)"): {"qid": None, "wp_title": None, "wp_lang": "fr", "aliases": ["Comptoir du Relais"]},
    ("Paris", "L'As du Fallafel (Le Marais)"): {"qid": "Q3202421", "wp_title": "L'As du Fallafel", "wp_lang": "fr", "aliases": ["As du Fallafel", "Fallafel"]},
    ("Paris", "Croisière Nocturne sur la Seine"): {"qid": None, "wp_title": None, "wp_lang": "fr", "aliases": ["Croisiere Nocturne sur la Seine"]},
    ("Paris", "Le Caveau de la Huchette"): {"qid": "Q3220892", "wp_title": "Le Caveau de la Huchette", "wp_lang": "fr", "aliases": ["Caveau de la Huchette", "Huchette"]},

    # TOKYO (14)
    ("Tokyo", "Temple Senso-ji (Asakusa)"): {"qid": "Q185392", "wp_title": "Sensō-ji", "wp_lang": "fr", "aliases": ["Senso-ji", "Sensoji", "Sensō-ji", "Asakusa"]},
    ("Tokyo", "Sanctuaire Meiji Jingu"): {"qid": "Q276765", "wp_title": "Meiji-jingū", "wp_lang": "fr", "aliases": ["Meiji Jingu", "Meiji-jingu", "Meiji Shrine", "Meiji"]},
    ("Tokyo", "Musée National de Tokyo (Ueno)"): {"qid": "Q653419", "wp_title": "Musée national de Tokyo", "wp_lang": "fr", "aliases": ["Tokyo National Museum", "Musee national de Tokyo"]},
    ("Tokyo", "teamLab Planets TOKYO (Toyosu)"): {"qid": "Q111974903", "wp_title": "TeamLab Planets", "wp_lang": "en", "aliases": ["teamLab Planets", "TeamLab"]},
    ("Tokyo", "Shibuya Sky & Carrefour de Shibuya"): {"qid": "Q1196215", "wp_title": "Carrefour de Shibuya", "wp_lang": "fr", "aliases": ["Shibuya Crossing", "Shibuya", "Shibuya Scramble"]},
    ("Tokyo", "Jardin National Shinjuku Gyoen"): {"qid": "Q852256", "wp_title": "Shinjuku Gyoen", "wp_lang": "fr", "aliases": ["Shinjuku Gyoen", "Shinjuku"]},
    ("Tokyo", "Parc d'Ueno & Étang de Shinobazu"): {"qid": "Q763806", "wp_title": "Parc de Ueno", "wp_lang": "fr", "aliases": ["Ueno Park", "Ueno", "Shinobazu"]},
    ("Tokyo", "Jardins Est du Palais Impérial"): {"qid": "Q11525465", "wp_title": "East Gardens of the Imperial Palace", "wp_lang": "en", "aliases": ["Imperial Palace East Gardens", "Kokyo Higashi Gyoen", "Imperial Palace"]},
    ("Tokyo", "Marché Extérieur de Tsukiji"): {"qid": "Q335080", "wp_title": "Marché aux poissons de Tsukiji", "wp_lang": "fr", "aliases": ["Tsukiji", "Tsukiji market"]},
    ("Tokyo", "Ichiran Ramen Shibuya"): {"qid": "Q1131484", "wp_title": "Ichiran", "wp_lang": "en", "aliases": ["Ichiran"]},
    ("Tokyo", "Sukiyabashi Jiro Roppongi"): {"qid": "Q4391504", "wp_title": "Sukiyabashi Jiro", "wp_lang": "fr", "aliases": ["Sukiyabashi Jiro", "Jiro"]},
    ("Tokyo", "Gonpachi Nishiazabu (Izakaya)"): {"qid": None, "wp_title": None, "wp_lang": "en", "aliases": ["Gonpachi"]},
    ("Tokyo", "Omoide Yokocho & Golden Gai (Shinjuku)"): {"qid": "Q5578772", "wp_title": "Shinjuku Golden Gai", "wp_lang": "fr", "aliases": ["Golden Gai", "Omoide Yokocho"]},
    ("Tokyo", "Observatoire Nocturne de Roppongi Hills (Mori Tower)"): {"qid": "Q733997", "wp_title": "Roppongi Hills Mori Tower", "wp_lang": "en", "aliases": ["Roppongi Hills", "Mori Tower"]},

    # ROME (14)
    ("Rome", "Colisée & Forum Romain"): {"qid": "Q10285", "wp_title": "Colisée", "wp_lang": "fr", "aliases": ["Colisee", "Colosseum", "Colosseo", "Flavian Amphitheatre"]},
    ("Rome", "Musées du Vatican & Chapelle Sixtine"): {"qid": "Q182955", "wp_title": "Musées du Vatican", "wp_lang": "fr", "aliases": ["Vatican Museums", "Musei Vaticani", "Chapelle Sixtine", "Sistine Chapel", "Vatican"]},
    ("Rome", "Panthéon de Rome"): {"qid": "Q43473", "wp_title": "Panthéon (Rome)", "wp_lang": "fr", "aliases": ["Pantheon", "Pantheon Rome"]},
    ("Rome", "Galerie Borghèse"): {"qid": "Q192420", "wp_title": "Galerie Borghèse", "wp_lang": "fr", "aliases": ["Galleria Borghese", "Borghese"]},
    ("Rome", "Fontaine de Trevi & Place d'Espagne"): {"qid": "Q185382", "wp_title": "Fontaine de Trevi", "wp_lang": "fr", "aliases": ["Trevi", "Fontana di Trevi", "Trevi Fountain"]},
    ("Rome", "Jardins de la Villa Borghèse"): {"qid": "Q818533", "wp_title": "Villa Borghèse", "wp_lang": "fr", "aliases": ["Villa Borghese", "Borghese"]},
    ("Rome", "Jardin des Orangers (Parco Savello)"): {"qid": "Q1522699", "wp_title": "Jardin des Orangers", "wp_lang": "fr", "aliases": ["Giardino degli Aranci", "Parco Savello", "Aranci"]},
    ("Rome", "Colline du Janicule (Gianicolo)"): {"qid": "Q660186", "wp_title": "Janicule", "wp_lang": "fr", "aliases": ["Gianicolo", "Janiculum", "Janicule"]},
    ("Rome", "Roscioli Salumeria con Cucina"): {"qid": None, "wp_title": None, "wp_lang": "it", "aliases": ["Roscioli"]},
    ("Rome", "Da Enzo al 29 (Trastevere)"): {"qid": None, "wp_title": None, "wp_lang": "it", "aliases": ["Da Enzo al 29"]},
    ("Rome", "Armando al Pantheon"): {"qid": None, "wp_title": None, "wp_lang": "it", "aliases": ["Armando al Pantheon"]},
    ("Rome", "Pizzarium Bonci (Prati)"): {"qid": None, "wp_title": None, "wp_lang": "it", "aliases": ["Pizzarium", "Bonci"]},
    ("Rome", "Promenade Nocturne à Trastevere & Piazza Trilussa"): {"qid": "Q3902338", "wp_title": "Piazza Trilussa", "wp_lang": "it", "aliases": ["Piazza Trilussa", "Trilussa", "Trastevere"]},
    ("Rome", "Jerry Thomas Speakeasy (Vicolo Cellini)"): {"qid": None, "wp_title": None, "wp_lang": "it", "aliases": ["Jerry Thomas Speakeasy"]},

    # NEW YORK (14)
    ("New York", "Metropolitan Museum of Art (The Met)"): {"qid": "Q160236", "wp_title": "Metropolitan Museum of Art", "wp_lang": "fr", "aliases": ["Metropolitan Museum of Art", "The Met", "Met", "MET"]},
    ("New York", "MoMA — Museum of Modern Art"): {"qid": "Q188740", "wp_title": "Museum of Modern Art", "wp_lang": "fr", "aliases": ["Museum of Modern Art", "MoMA"]},
    ("New York", "Statue de la Liberté & Ellis Island"): {"qid": "Q9202", "wp_title": "Statue de la Liberté", "wp_lang": "fr", "aliases": ["Statue of Liberty", "Statue de la Liberte", "Liberty"]},
    ("New York", "Top of the Rock (Rockefeller Center)"): {"qid": "Q11277", "wp_title": "Rockefeller Center", "wp_lang": "fr", "aliases": ["Rockefeller Center", "Top of the Rock", "GE Building", "30 Rockefeller"]},
    ("New York", "Mémorial & Musée du 11-Septembre"): {"qid": "Q113674", "wp_title": "Mémorial du 11 Septembre", "wp_lang": "fr", "aliases": ["National September 11 Memorial", "9/11 Memorial", "World Trade Center", "WTC"]},
    ("New York", "Central Park (Boucle Sud & Bow Bridge)"): {"qid": "Q160409", "wp_title": "Central Park", "wp_lang": "fr", "aliases": ["Central Park", "Bow Bridge"]},
    ("New York", "The High Line (Chelsea — Hudson Yards)"): {"qid": "Q949236", "wp_title": "High Line", "wp_lang": "fr", "aliases": ["High Line"]},
    ("New York", "Brooklyn Bridge & Promenade de DUMBO"): {"qid": "Q125006", "wp_title": "Pont de Brooklyn", "wp_lang": "fr", "aliases": ["Brooklyn Bridge", "Pont de Brooklyn", "Brooklyn"]},
    ("New York", "Katz's Delicatessen (Lower East Side)"): {"qid": "Q1736888", "wp_title": "Katz's Delicatessen", "wp_lang": "fr", "aliases": ["Katz's Delicatessen", "Katzs", "Katz"]},
    ("New York", "Chelsea Market (Meatpacking District)"): {"qid": "Q1069135", "wp_title": "Chelsea Market", "wp_lang": "fr", "aliases": ["Chelsea Market"]},
    ("New York", "Joe's Pizza (Greenwich Village)"): {"qid": "Q6208219", "wp_title": "Joe's Pizza", "wp_lang": "en", "aliases": ["Joe's Pizza", "Joes Pizza"]},
    ("New York", "Balthazar Brasserie (SoHo)"): {"qid": "Q4852845", "wp_title": "Balthazar (restaurant)", "wp_lang": "en", "aliases": ["Balthazar"]},
    ("New York", "Village Vanguard Jazz Club (Greenwich Village)"): {"qid": "Q1475624", "wp_title": "Village Vanguard", "wp_lang": "fr", "aliases": ["Village Vanguard"]},
    ("New York", "Spectacle à Broadway & Times Square de Nuit"): {"qid": "Q11259", "wp_title": "Times Square", "wp_lang": "fr", "aliases": ["Times Square", "Broadway"]},

    # MARRAKECH (14)
    ("Marrakech", "Jardin Majorelle & Musée Yves Saint Laurent"): {"qid": "Q1548224", "wp_title": "Jardin Majorelle", "wp_lang": "fr", "aliases": ["Jardin Majorelle", "Majorelle", "Majorelle Garden"]},
    ("Marrakech", "Palais de la Bahia"): {"qid": "Q1638068", "wp_title": "Palais de la Bahia", "wp_lang": "fr", "aliases": ["Palais de la Bahia", "Bahia Palace", "Bahia"]},
    ("Marrakech", "Médersa Ben Youssef"): {"qid": "Q816503", "wp_title": "Médersa Ben Youssef", "wp_lang": "fr", "aliases": ["Medersa Ben Youssef", "Ben Youssef", "Ali Ben Youssef"]},
    ("Marrakech", "Tombeaux Saadiens"): {"qid": "Q1530871", "wp_title": "Tombeaux saadiens", "wp_lang": "fr", "aliases": ["Tombeaux saadiens", "Saadian Tombs", "Saadiens"]},
    ("Marrakech", "Musée de Marrakech (Palais Mnebhi)"): {"qid": "Q2407510", "wp_title": "Musée de Marrakech", "wp_lang": "fr", "aliases": ["Musee de Marrakech", "Marrakesh Museum", "Dar Menebhi", "Mnebhi"]},
    ("Marrakech", "Jardins de la Ménara"): {"qid": "Q1850819", "wp_title": "Jardins de la Ménara", "wp_lang": "fr", "aliases": ["Menara", "Jardins de la Menara", "Menara gardens"]},
    ("Marrakech", "Le Jardin Secret (Médina)"): {"qid": None, "wp_title": None, "wp_lang": "fr", "aliases": ["Le Jardin Secret"]},
    ("Marrakech", "Palmeraie de Marrakech (Balade au coucher du soleil)"): {"qid": "Q3361603", "wp_title": "Palmeraie de Marrakech", "wp_lang": "fr", "aliases": ["Palmeraie", "Palmeraie de Marrakech"]},
    ("Marrakech", "Nomad Marrakech (Place des Épices)"): {"qid": None, "wp_title": None, "wp_lang": "fr", "aliases": ["Nomad Marrakech"]},
    ("Marrakech", "Le Jardin (Médina — Mouassine)"): {"qid": None, "wp_title": None, "wp_lang": "fr", "aliases": ["Le Jardin Marrakech"]},
    ("Marrakech", "Dar Moha (Riad du Pacha)"): {"qid": None, "wp_title": None, "wp_lang": "fr", "aliases": ["Dar Moha"]},
    ("Marrakech", "Al Fassia Aguedal"): {"qid": None, "wp_title": None, "wp_lang": "fr", "aliases": ["Al Fassia"]},
    ("Marrakech", "Comptoir Darna Marrakech"): {"qid": None, "wp_title": None, "wp_lang": "fr", "aliases": ["Comptoir Darna"]},
    ("Marrakech", "Place Jemaa el-Fna (Soirée & Conteurs)"): {"qid": "Q202660", "wp_title": "Place Jemaa el-Fna", "wp_lang": "fr", "aliases": ["Jemaa el-Fna", "Jemaa el-Fnaa", "Djemaa el Fna"]},
}


def extract_p18_list(ent: dict[str, Any]) -> list[str]:
    claims = ent.get("claims") or {}
    p18_claims = claims.get("P18") or []
    files: list[str] = []
    for c in p18_claims:
        rank = c.get("rank", "normal")
        if rank == "deprecated":
            continue
        snak = c.get("mainsnak") or {}
        dv = snak.get("datavalue") or {}
        val = dv.get("value")
        if isinstance(val, str) and val.strip():
            norm = normalize_commons_file_title(val.strip())
            if norm:
                if rank == "preferred":
                    files.insert(0, norm)
                else:
                    files.append(norm)
    return files


async def main() -> None:
    headers = {"User-Agent": TRAVELMATE_USER_AGENT, "Accept": "application/json"}
    all_qids = sorted({v["qid"] for v in PLACE_WIKIMEDIA_TARGETS.values() if v.get("qid")})

    entities_by_qid: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(headers=headers, timeout=20.0) as client:
        # 1. Batch Wikidata wbgetentities (max 40 per request -> 2 requests total)
        for i in range(0, len(all_qids), 40):
            chunk = all_qids[i : i + 40]
            r = await client.get(
                "https://www.wikidata.org/w/api.php",
                params={
                    "action": "wbgetentities",
                    "ids": "|".join(chunk),
                    "props": "claims|labels|sitelinks",
                    "languages": "fr|en|it|ja",
                    "sitefilter": "frwiki|enwiki|itwiki|jawiki",
                    "format": "json",
                },
            )
            r.raise_for_status()
            data = r.json()
            for qid, ent in (data.get("entities") or {}).items():
                entities_by_qid[qid] = ent
            await asyncio.sleep(0.5)

        # 2. Collect candidate P18 files and fallback Wikipedia titles for entities without P18
        p18_by_qid: dict[str, list[str]] = {}
        wp_lookup_by_lang: dict[str, list[tuple[str, str]]] = {}

        for (city, name), target in PLACE_WIKIMEDIA_TARGETS.items():
            qid = target.get("qid")
            if not qid:
                continue
            ent = entities_by_qid.get(qid, {})
            p18s = extract_p18_list(ent)
            p18_by_qid[qid] = p18s
            # Also queue Wikipedia pageimages in case P18 is missing or rejected
            sitelinks = ent.get("sitelinks") or {}
            wp_lang = target.get("wp_lang") or "fr"
            wp_title = target.get("wp_title")
            if f"{wp_lang}wiki" in sitelinks:
                wp_title = sitelinks[f"{wp_lang}wiki"].get("title") or wp_title
            elif "frwiki" in sitelinks:
                wp_lang = "fr"
                wp_title = sitelinks["frwiki"].get("title")
            elif "enwiki" in sitelinks:
                wp_lang = "en"
                wp_title = sitelinks["enwiki"].get("title")
            if wp_title:
                wp_lookup_by_lang.setdefault(wp_lang, []).append((qid, wp_title))

        # 3. Batch Wikipedia prop=pageimages per language
        pageimage_by_qid: dict[str, str] = {}
        for lang, pairs in wp_lookup_by_lang.items():
            for i in range(0, len(pairs), 40):
                chunk = pairs[i : i + 40]
                titles_map = {t: q for q, t in chunk}
                r = await client.get(
                    f"https://{lang}.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "titles": "|".join(t for _, t in chunk),
                        "prop": "pageimages",
                        "piprop": "thumbnail|name|original",
                        "pithumbsize": str(TARGET_THUMB_WIDTH_PX),
                        "redirects": "1",
                        "format": "json",
                    },
                )
                if r.status_code == 200:
                    qdata = r.json().get("query") or {}
                    norm_map: dict[str, str] = {}
                    for n in qdata.get("normalized") or []:
                        norm_map[n["to"]] = n["from"]
                    for red in qdata.get("redirects") or []:
                        orig_from = norm_map.get(red["from"], red["from"])
                        norm_map[red["to"]] = orig_from
                    for _pid, pinfo in (qdata.get("pages") or {}).items():
                        if not isinstance(pinfo, dict):
                            continue
                        ptitle = pinfo.get("title", "")
                        orig_title = norm_map.get(ptitle, ptitle)
                        matched_qid = titles_map.get(orig_title) or titles_map.get(ptitle)
                        if not matched_qid:
                            continue
                        pi_name = str(pinfo.get("pageimage") or "").strip()
                        if not pi_name:
                            thumb_src = (pinfo.get("thumbnail") or {}).get("source") or ""
                            if thumb_src and "/thumb/" in thumb_src:
                                parts = [p for p in urlparse(thumb_src).path.split("/") if p]
                                if len(parts) >= 2:
                                    pi_name = unquote(parts[-2])
                        if pi_name:
                            norm_f = normalize_commons_file_title(pi_name)
                            if norm_f:
                                pageimage_by_qid[matched_qid] = norm_f
                await asyncio.sleep(0.4)

        # 4. Collect all candidate File:... titles across P18 and Wikipedia pageimages
        all_files_set: set[str] = set()
        for files in p18_by_qid.values():
            for f in files:
                if validate_file_title_quality(f):
                    all_files_set.add(f)
        for f in pageimage_by_qid.values():
            if validate_file_title_quality(f):
                all_files_set.add(f)

        all_files = sorted(all_files_set)
        commons_info_by_file: dict[str, dict[str, Any]] = {}

        for i in range(0, len(all_files), 35):
            chunk = all_files[i : i + 35]
            r = await client.get(
                COMMONS_API_URL,
                params={
                    "action": "query",
                    "titles": "|".join(chunk),
                    "prop": "imageinfo",
                    "iiprop": "extmetadata|url|size",
                    "iiurlwidth": str(TARGET_THUMB_WIDTH_PX),
                    "redirects": "1",
                    "format": "json",
                },
            )
            r.raise_for_status()
            qdata = r.json().get("query") or {}
            norm_map = {}
            for n in qdata.get("normalized") or []:
                norm_map[n["to"]] = n["from"]
            for red in qdata.get("redirects") or []:
                orig_from = norm_map.get(red["from"], red["from"])
                norm_map[red["to"]] = orig_from

            for _pid, page in (qdata.get("pages") or {}).items():
                if not isinstance(page, dict):
                    continue
                canonical_title = normalize_commons_file_title(str(page.get("title") or ""))
                orig_title = normalize_commons_file_title(norm_map.get(page.get("title", ""), canonical_title))
                iilist = page.get("imageinfo") or []
                if not iilist or not isinstance(iilist[0], dict):
                    continue
                ii = iilist[0]
                if not validate_file_title_quality(canonical_title):
                    continue
                width = int(ii.get("width") or 0)
                if width > 0 and width < MIN_IMAGE_WIDTH_PX:
                    continue
                extmeta = ii.get("extmetadata") or {}
                raw_lic = (extmeta.get("LicenseShortName") or {}).get("value")
                free_lic = normalize_and_validate_free_license(str(raw_lic) if raw_lic else None)
                if not free_lic:
                    continue
                author = extract_author_from_extmetadata(extmeta)
                if not author:
                    continue
                thumb_url = str(ii.get("thumburl") or "").strip()
                orig_url = str(ii.get("url") or "").strip()
                if orig_url.lower().endswith(".svg") or thumb_url.lower().endswith(".svg"):
                    continue
                if not thumb_url:
                    thumb_url = build_commons_thumbnail_url(canonical_title, width=TARGET_THUMB_WIDTH_PX)
                desc_url = str(ii.get("descriptionurl") or "").strip()
                if not desc_url:
                    clean_fn = canonical_title[5:].replace(" ", "_")
                    desc_url = f"https://commons.wikimedia.org/wiki/File:{quote(clean_fn, safe='()_-.,')}"

                record = {
                    "photo_file_title": canonical_title,
                    "photo_url": thumb_url,
                    "photo_author": author,
                    "photo_license": free_lic,
                    "photo_commons_url": desc_url,
                    "width": width,
                }
                commons_info_by_file[canonical_title.lower()] = record
                commons_info_by_file[orig_title.lower()] = record
            await asyncio.sleep(0.4)

    # 5. Assign photos to each of the 70 demo places in strict order: (a) P18 -> (b) pageimages -> (c) none
    results: dict[str, list[dict[str, Any]]] = {}
    global_used_urls: set[str] = set()
    global_used_titles: set[str] = set()

    for dest in SEED_DESTINATIONS:
        city = dest["city_name"]
        city_items: list[dict[str, Any]] = []
        for place in dest["places"]:
            name = place["name"]
            target = PLACE_WIKIMEDIA_TARGETS.get((city, name), {})
            qid = target.get("qid")
            wp_title = target.get("wp_title")
            wp_lang = target.get("wp_lang", "fr")
            aliases = target.get("aliases", [])

            if not qid:
                city_items.append({
                    "name": name,
                    "qid": None,
                    "wp_title": None,
                    "wp_lang": wp_lang,
                    "aliases": aliases,
                    "has_photo": False,
                    "photo_source": "none",
                })
                continue

            ent = entities_by_qid.get(qid, {})
            labels = ent.get("labels") or {}
            wd_label_fr = (labels.get("fr") or {}).get("value")
            wd_label_en = (labels.get("en") or {}).get("value")

            chosen: dict[str, Any] | None = None
            chosen_source = "none"

            # (a) Wikidata P18
            for cand_file in p18_by_qid.get(qid, []):
                rec = commons_info_by_file.get(cand_file.lower())
                if rec:
                    ft_low = rec["photo_file_title"].lower()
                    u_str = rec["photo_url"]
                    if ft_low not in global_used_titles and u_str not in global_used_urls:
                        chosen = rec
                        chosen_source = "wikidata_p18"
                        global_used_titles.add(ft_low)
                        global_used_urls.add(u_str)
                        break

            # (b) Wikipedia pageimages
            if chosen is None and qid in pageimage_by_qid:
                cand_file = pageimage_by_qid[qid]
                rec = commons_info_by_file.get(cand_file.lower())
                if rec:
                    ft_low = rec["photo_file_title"].lower()
                    u_str = rec["photo_url"]
                    if ft_low not in global_used_titles and u_str not in global_used_urls:
                        chosen = rec
                        chosen_source = "wikipedia_pageimages"
                        global_used_titles.add(ft_low)
                        global_used_urls.add(u_str)

            city_items.append({
                "name": name,
                "qid": qid,
                "wd_label_fr": wd_label_fr,
                "wd_label_en": wd_label_en,
                "wp_title": wp_title,
                "wp_lang": wp_lang,
                "aliases": aliases,
                "has_photo": chosen is not None,
                "photo_source": chosen_source,
                "photo_url": chosen["photo_url"] if chosen else None,
                "photo_file_title": chosen["photo_file_title"] if chosen else None,
                "photo_author": chosen["photo_author"] if chosen else None,
                "photo_license": chosen["photo_license"] if chosen else None,
                "photo_commons_url": chosen["photo_commons_url"] if chosen else None,
            })
        results[city] = city_items

    with open("/app/tests/_resolved_seed_70_photos.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    for city, items in results.items():
        with_photo = sum(1 for x in items if x["has_photo"])
        print(f"=== {city}: {with_photo}/{len(items)} with photo ===")
        for x in items:
            print(
                f"  - {x['name']} [{x['qid']} / {x.get('wd_label_fr') or x.get('wd_label_en')}]: "
                f"has_photo={x['has_photo']} | src={x['photo_source']} | file={x.get('photo_file_title')} "
                f"| author={x.get('photo_author')} | lic={x.get('photo_license')}"
            )


if __name__ == "__main__":
    asyncio.run(main())

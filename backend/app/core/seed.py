import asyncio
import logging
from typing import Any

from sqlalchemy import select

from app.core.database import AsyncSession, AsyncSessionLocal
from app.core.security import hash_password
from app.models.entities import Accommodation, Destination, LocalTransport, Place, User
from app.models.enums import AccommodationType, PlaceCategory, TravelStyle

logger = logging.getLogger("travelmate.seed")


SEED_DESTINATIONS: list[dict[str, Any]] = [
    {
        "city_name": "Paris",
        "country_name": "France",
        "country_code_iso2": "FR",
        "iata_code": "CDG",
        "timezone": "Europe/Paris",
        "latitude": 48.8566,
        "longitude": 2.3522,
        "hero_image_url": "https://images.unsplash.com/photo-1502602898657-3e91760cbb34?auto=format&fit=crop&w=1400&q=80",
        "description": "Capitale mondiale de la gastronomie, de l'art et de l'architecture haussmannienne.",
        "practical_info": {
            "visa": "Espace Schengen : exempté pour UE/EEE ; visa court séjour ou ETIAS selon nationalité.",
            "vaccins": "Aucun vaccin obligatoire ; rappel DTP recommandé.",
            "prises": "Type E (230V - 50Hz).",
            "monnaie": "Euro (EUR - €)",
            "urgences": "112 (Urgences européennes), 15 (SAMU), 17 (Police)",
            "coutumes": "Saluer ('Bonjour') en entrant dans une boutique ; service inclus au restaurant.",
        },
        "useful_phrases": [
            {"original": "Bonjour, une table pour deux s'il vous plaît.", "phonetic": "Bon-zhoor, oon tabl poor duh", "translation": "Hello, a table for two please."},
            {"original": "L'addition, s'il vous plaît.", "phonetic": "La-dee-syon seel voo pleh", "translation": "The bill, please."},
        ],
        "places": [
            {
                "name": "Musée du Louvre",
                "description": "Le plus grand musée d'art et d'antiquités au monde au cœur du Palais du Louvre.",
                "category": PlaceCategory.CULTURE.value,
                "is_outdoor": False,
                "latitude": 48.8606,
                "longitude": 2.3376,
                "recommended_duration_min": 180,
                "estimated_cost": 22.0,
                "price_tier": TravelStyle.STANDARD.value,
                "avg_rating": 4.8,
                "opening_hours": {"daily": "09:00-18:00", "closed": "Tuesday"},
                "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/6/66/Louvre_Museum_Wikimedia_Commons.jpg"],
                "source_provider": "simulated",
            },
            {
                "name": "Jardin du Luxembourg",
                "description": "Jardin historique du Sénat de 23 hectares avec bassins, statues et orangeraie.",
                "category": PlaceCategory.NATURE.value,
                "is_outdoor": True,
                "latitude": 48.8462,
                "longitude": 2.3372,
                "recommended_duration_min": 90,
                "estimated_cost": 0.0,
                "price_tier": TravelStyle.ECONOMIC.value,
                "avg_rating": 4.9,
                "opening_hours": {"daily": "07:30-20:30"},
                "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/9/92/LuxembourgMontparnasse.JPG"],
                "source_provider": "simulated",
            },
            {
                "name": "Le Jules Verne (Tour Eiffel)",
                "description": "Table gastronomique étoilée nichée au deuxième étage de la Tour Eiffel.",
                "category": PlaceCategory.RESTAURANT.value,
                "is_outdoor": False,
                "latitude": 48.8584,
                "longitude": 2.2945,
                "recommended_duration_min": 150,
                "estimated_cost": 290.0,
                "price_tier": TravelStyle.LUXURY.value,
                "avg_rating": 4.7,
                "opening_hours": {"daily": "12:00-13:30, 19:00-21:00"},
                "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/b/b8/Le_Jules_Verne.jpg"],
                "source_provider": "simulated",
            },
            {
                "name": "Bouillon Chartier Grands Boulevards",
                "description": "Brasserie parisienne historique Belle Époque proposant une cuisine traditionnelle à petit prix.",
                "category": PlaceCategory.RESTAURANT.value,
                "is_outdoor": False,
                "latitude": 48.8719,
                "longitude": 2.3431,
                "recommended_duration_min": 75,
                "estimated_cost": 24.0,
                "price_tier": TravelStyle.ECONOMIC.value,
                "avg_rating": 4.5,
                "opening_hours": {"daily": "11:30-00:00"},
                "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/1/14/Paris_Chartier_1304.jpg"],
                "source_provider": "simulated",
            },
            {
                "name": "Bistrot Benoît Paris (Châtelet - Marais)",
                "description": "Bistrot parisien authentique fondé en 1912 entre le Louvre et le Marais.",
                "category": PlaceCategory.RESTAURANT.value,
                "is_outdoor": False,
                "latitude": 48.8582,
                "longitude": 2.3502,
                "recommended_duration_min": 90,
                "estimated_cost": 65.0,
                "price_tier": TravelStyle.STANDARD.value,
                "avg_rating": 4.7,
                "opening_hours": {"daily": "12:00-14:00, 19:30-22:00"},
                "hero_photos": ["https://images.unsplash.com/photo-1414235077428-338989a2e8c0?auto=format&fit=crop&w=1200&q=80"],
                "source_provider": "simulated",
            },
        ],
        "accommodations": [
            {
                "type": AccommodationType.HOTEL.value,
                "name": "Hôtel Le Meurice",
                "neighborhood": "1er arr. - Tuileries",
                "address": "228 Rue de Rivoli, 75001 Paris",
                "latitude": 48.8651,
                "longitude": 2.3281,
                "price_per_night": 1350.0,
                "luxury_tier": TravelStyle.LUXURY.value,
                "rating": 4.9,
                "photos": ["https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=1000&q=80"],
                "amenities": ["Spa Valmont", "Restaurant 2 étoiles", "Conciergerie Clefs d'Or"],
                "source_provider": "hotel_official",
                "booking_redirect_url": "https://www.dorchestercollection.com/paris/le-meurice",
            },
            {
                "type": AccommodationType.AIRBNB.value,
                "name": "Loft Haussmannien Vue Marais",
                "neighborhood": "4e arr. - Le Marais",
                "address": "18 Rue des Rosiers, 75004 Paris",
                "latitude": 48.8575,
                "longitude": 2.3584,
                "price_per_night": 195.0,
                "luxury_tier": TravelStyle.STANDARD.value,
                "rating": 4.7,
                "photos": ["https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?auto=format&fit=crop&w=1000&q=80"],
                "amenities": ["Wi-Fi Fibre", "Cuisine équipée", "Balcon filant"],
                "source_provider": "airbnb_partner_redirect",
                "booking_redirect_url": "https://www.airbnb.fr/s/Le-Marais--Paris/homes",
            },
            {
                "type": AccommodationType.HOTEL.value,
                "name": "Generator Paris Canal Saint-Martin",
                "neighborhood": "10e arr. - Colonel Fabien",
                "address": "9-11 Place du Colonel Fabien, 75010 Paris",
                "latitude": 48.8782,
                "longitude": 2.3698,
                "price_per_night": 85.0,
                "luxury_tier": TravelStyle.ECONOMIC.value,
                "rating": 4.3,
                "photos": ["https://images.unsplash.com/photo-1555854877-bab0e564b8d5?auto=format&fit=crop&w=1000&q=80"],
                "amenities": ["Rooftop Khayma", "Wi-Fi gratuit", "Bagagerie 24/7"],
                "source_provider": "simulated",
                "booking_redirect_url": "https://staygenerator.com/hostels/paris",
            },
        ],
        "transports": [
            {
                "transport_type": "TRANSIT_PASS",
                "provider_name": "Île-de-France Mobilités (Pass Navigo Semaine / Jour)",
                "description": "Accès illimité métro, RER, bus et tramway en Île-de-France.",
                "estimated_price_eur": 30.75,
                "booking_url": "https://www.iledefrance-mobilites.fr",
            },
            {
                "transport_type": "VTC_TAXI",
                "provider_name": "G7 Taxi Officiel & Uber Paris",
                "description": "Forfait réglementé Aéroport CDG <-> Paris Rive Droite (56€) / Rive Gauche (65€).",
                "estimated_price_eur": 56.0,
                "booking_url": "https://www.g7.fr",
            },
        ],
    },
    {
        "city_name": "Tokyo",
        "country_name": "Japon",
        "country_code_iso2": "JP",
        "iata_code": "HND",
        "timezone": "Asia/Tokyo",
        "latitude": 35.6762,
        "longitude": 139.6503,
        "hero_image_url": "https://images.unsplash.com/photo-1540959733332-eab4deabeeaf?auto=format&fit=crop&w=1400&q=80",
        "description": "Mégapole fascinante alliant sanctuaires millénaires, néons futuristes et haute gastronomie.",
        "practical_info": {
            "visa": "Exemption de visa court séjour (90 jours) pour passeports européens/nord-américains ; Visit Japan Web recommandé.",
            "vaccins": "Aucun vaccin obligatoire.",
            "prises": "Type A / B (100V - 50Hz à Tokyo).",
            "monnaie": "Yen japonais (JPY - ¥)",
            "urgences": "110 (Police), 119 (Ambulance / Pompiers)",
            "coutumes": "Pas de pourboire ; retirer ses chaussures dans les lieux traditionnels ; silence dans le métro.",
        },
        "useful_phrases": [
            {"original": "ありがとうございます (Arigatō gozaimasu)", "phonetic": "Ah-ree-gah-toh go-zai-mahs", "translation": "Merci beaucoup."},
            {"original": "お会計をお願いします (O-kaikei o onegaishimasu)", "phonetic": "Oh-kai-kay oh oh-neh-gai-shee-mahs", "translation": "L'addition s'il vous plaît."},
        ],
        "places": [
            {
                "name": "Temple Senso-ji (Asakusa)",
                "description": "Le plus ancien temple bouddhiste de Tokyo et son allée commerçante Nakamise-dori.",
                "category": PlaceCategory.CULTURE.value,
                "is_outdoor": True,
                "latitude": 35.7148,
                "longitude": 139.7967,
                "recommended_duration_min": 120,
                "estimated_cost": 0.0,
                "price_tier": TravelStyle.ECONOMIC.value,
                "avg_rating": 4.8,
                "opening_hours": {"daily": "06:00-17:00"},
                "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/4/43/Sensoji_2023.jpg"],
                "source_provider": "simulated",
            },
            {
                "name": "teamLab Planets Tokyo",
                "description": "Musée d'art numérique immersif où l'on marche pieds nus dans l'eau et la lumière.",
                "category": PlaceCategory.CULTURE.value,
                "is_outdoor": False,
                "latitude": 35.6491,
                "longitude": 139.7898,
                "recommended_duration_min": 120,
                "estimated_cost": 32.0,
                "price_tier": TravelStyle.STANDARD.value,
                "avg_rating": 4.9,
                "opening_hours": {"daily": "09:00-22:00"},
                "hero_photos": ["https://images.unsplash.com/photo-1503899036084-c55cdd92da26?auto=format&fit=crop&w=1200&q=80"],
                "source_provider": "simulated",
            },
            {
                "name": "Ichiran Ramen Shinjuku Central East",
                "description": "Ramen tonkotsu authentique à deux pas de Shinjuku.",
                "category": PlaceCategory.RESTAURANT.value,
                "is_outdoor": False,
                "latitude": 35.6916,
                "longitude": 139.7046,
                "recommended_duration_min": 60,
                "estimated_cost": 14.0,
                "price_tier": TravelStyle.ECONOMIC.value,
                "avg_rating": 4.7,
                "opening_hours": {"daily": "24/7"},
                "hero_photos": ["https://images.unsplash.com/photo-1569718212165-3a8278d5f624?auto=format&fit=crop&w=1200&q=80"],
                "source_provider": "simulated",
            },
            {
                "name": "Sukiyabashi Jiro Roppongi",
                "description": "Comptoir d'omakase sushi de haute tradition à Tokyo.",
                "category": PlaceCategory.RESTAURANT.value,
                "is_outdoor": False,
                "latitude": 35.6604,
                "longitude": 139.7292,
                "recommended_duration_min": 90,
                "estimated_cost": 260.0,
                "price_tier": TravelStyle.LUXURY.value,
                "avg_rating": 4.9,
                "opening_hours": {"daily": "11:30-14:00, 17:30-21:00"},
                "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/9/92/Inside_Sukiyabashi_Jiro_%2811557082593%29.jpg"],
                "source_provider": "simulated",
            },
        ],
        "accommodations": [
            {
                "type": AccommodationType.HOTEL.value,
                "name": "Aman Tokyo",
                "neighborhood": "Otemachi / Chiyoda",
                "address": "The Otemachi Tower, 1-5-6 Otemachi, Chiyoda-ku, Tokyo",
                "latitude": 35.6869,
                "longitude": 139.7640,
                "price_per_night": 1650.0,
                "luxury_tier": TravelStyle.LUXURY.value,
                "rating": 4.95,
                "photos": ["https://images.unsplash.com/photo-1582719478250-c89cae4dc85b?auto=format&fit=crop&w=1000&q=80"],
                "amenities": ["Onsen panoramique", "Vue Mont Fuji", "Spa"],
                "source_provider": "hotel_official",
                "booking_redirect_url": "https://www.aman.com/hotels/aman-tokyo",
            },
            {
                "type": AccommodationType.HOTEL.value,
                "name": "Shinjuku Granbell Hotel",
                "neighborhood": "Shinjuku",
                "address": "2-14-5 Kabukicho, Shinjuku-ku, Tokyo",
                "latitude": 35.6968,
                "longitude": 139.7061,
                "price_per_night": 110.0,
                "luxury_tier": TravelStyle.ECONOMIC.value,
                "rating": 4.4,
                "photos": ["https://images.unsplash.com/photo-1551882547-ff40c63fe5fa?auto=format&fit=crop&w=1000&q=80"],
                "amenities": ["Rooftop Bar", "Wi-Fi", "Proche métro"],
                "source_provider": "simulated",
                "booking_redirect_url": "https://www.granbellhotel.jp/en/shinjuku/",
            },
            {
                "type": AccommodationType.AIRBNB.value,
                "name": "Machya Design Shibuya Studio",
                "neighborhood": "Shibuya / Harajuku",
                "address": "3-12 Jingumae, Shibuya-ku, Tokyo",
                "latitude": 35.6695,
                "longitude": 139.7085,
                "price_per_night": 175.0,
                "luxury_tier": TravelStyle.STANDARD.value,
                "rating": 4.8,
                "photos": ["https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?auto=format&fit=crop&w=1000&q=80"],
                "amenities": ["Pocket Wi-Fi", "Tatami moderne", "À 5 min JR Harajuku"],
                "source_provider": "airbnb_partner_redirect",
                "booking_redirect_url": "https://www.airbnb.fr/s/Shibuya--Tokyo/homes",
            },
        ],
        "transports": [
            {
                "transport_type": "IC_CARD",
                "provider_name": "Welcome Suica / Pasmo (Apple Wallet)",
                "description": "Carte à puce sans contact pour l'ensemble du réseau JR, Tokyo Metro et Toei.",
                "estimated_price_eur": 15.0,
                "booking_url": "https://www.jreast.co.jp/multi/en/welcomesuica/",
            }
        ],
    },
    {
        "city_name": "Rome",
        "country_name": "Italie",
        "country_code_iso2": "IT",
        "iata_code": "FCO",
        "timezone": "Europe/Rome",
        "latitude": 41.9028,
        "longitude": 12.4964,
        "hero_image_url": "https://images.unsplash.com/photo-1552832230-c0197dd311b5?auto=format&fit=crop&w=1400&q=80",
        "description": "La Ville Éternelle, musée à ciel ouvert entre vestiges impériaux, places baroques et trattorias.",
        "practical_info": {
            "visa": "Espace Schengen.",
            "vaccins": "Aucun vaccin obligatoire.",
            "prises": "Type C / F / L (230V - 50Hz).",
            "monnaie": "Euro (EUR - €)",
            "urgences": "112 (Urgences), 118 (Ambulance)",
            "coutumes": "Tenue couvrant épaules et genoux exigée dans les églises et au Vatican ; 'coperto' habituel au restaurant.",
        },
        "useful_phrases": [
            {"original": "Buongiorno, il conto per favore.", "phonetic": "Bwon-jor-no, eel kon-to per fa-vo-re", "translation": "Bonjour, l'addition s'il vous plaît."},
        ],
        "places": [
            {
                "name": "Colisée & Forum Romain",
                "description": "L'amphithéâtre flavien emblématique et le cœur politique de la Rome antique.",
                "category": PlaceCategory.CULTURE.value,
                "is_outdoor": True,
                "latitude": 41.8902,
                "longitude": 12.4922,
                "recommended_duration_min": 180,
                "estimated_cost": 18.0,
                "price_tier": TravelStyle.STANDARD.value,
                "avg_rating": 4.9,
                "opening_hours": {"daily": "08:30-19:00"},
                "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/d/de/Colosseo_2020.jpg"],
                "source_provider": "simulated",
            },
            {
                "name": "Musées du Vatican & Chapelle Sixtine",
                "description": "Galeries pontificales abritant les fresques de Michel-Ange et les Chambres de Raphaël.",
                "category": PlaceCategory.CULTURE.value,
                "is_outdoor": False,
                "latitude": 41.9065,
                "longitude": 12.4536,
                "recommended_duration_min": 150,
                "estimated_cost": 25.0,
                "price_tier": TravelStyle.STANDARD.value,
                "avg_rating": 4.9,
                "opening_hours": {"daily": "08:30-19:00"},
                "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/7/73/Vatican_Museums_Spiral_Staircase_2012.jpg"],
                "source_provider": "simulated",
            },
            {
                "name": "Trattoria Da Enzo al 29",
                "description": "Trattoria romaine authentique au cœur du Trastevere (Carbonara & Cacio e Pepe).",
                "category": PlaceCategory.RESTAURANT.value,
                "is_outdoor": False,
                "latitude": 41.8879,
                "longitude": 12.4777,
                "recommended_duration_min": 90,
                "estimated_cost": 28.0,
                "price_tier": TravelStyle.ECONOMIC.value,
                "avg_rating": 4.7,
                "opening_hours": {"daily": "12:15-15:00, 19:00-23:00"},
                "hero_photos": ["https://images.unsplash.com/photo-1551183053-bf91a1d81141?auto=format&fit=crop&w=1200&q=80"],
                "source_provider": "simulated",
            },
        ],
        "accommodations": [
            {
                "type": AccommodationType.HOTEL.value,
                "name": "Hotel de Russie - Rocco Forte",
                "neighborhood": "Piazza del Popolo",
                "address": "Via del Babuino 9, 00187 Roma",
                "latitude": 41.9088,
                "longitude": 12.4779,
                "price_per_night": 920.0,
                "luxury_tier": TravelStyle.LUXURY.value,
                "rating": 4.9,
                "photos": ["https://images.unsplash.com/photo-1571896349842-33c89424de2d?auto=format&fit=crop&w=1000&q=80"],
                "amenities": ["Jardin secret", "Spa De Russie", "Bar Stravinskij"],
                "source_provider": "hotel_official",
                "booking_redirect_url": "https://www.roccofortehotels.com/hotels-and-resorts/hotel-de-russie/",
            },
            {
                "type": AccommodationType.AIRBNB.value,
                "name": "Appartement Terrasse Trastevere",
                "neighborhood": "Trastevere",
                "address": "Via della Lungaretta 45, 00153 Roma",
                "latitude": 41.8885,
                "longitude": 12.4754,
                "price_per_night": 145.0,
                "luxury_tier": TravelStyle.STANDARD.value,
                "rating": 4.8,
                "photos": ["https://images.unsplash.com/photo-1493809842364-78817add7ffb?auto=format&fit=crop&w=1000&q=80"],
                "amenities": ["Terrasse privée", "Machine Espresso", "Climatisation"],
                "source_provider": "airbnb_partner_redirect",
                "booking_redirect_url": "https://www.airbnb.fr/s/Trastevere--Rome/homes",
            },
        ],
        "transports": [],
    },
    {
        "city_name": "New York",
        "country_name": "États-Unis",
        "country_code_iso2": "US",
        "iata_code": "JFK",
        "timezone": "America/New_York",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "hero_image_url": "https://images.unsplash.com/photo-1496442226666-8d4d0e62e6e9?auto=format&fit=crop&w=1400&q=80",
        "description": "Énergie électrique de Manhattan, Central Park, Broadway et musées de rang mondial.",
        "practical_info": {
            "visa": "ESTA obligatoire au moins 72h avant le départ pour les ressortissants éligibles.",
            "vaccins": "Aucun vaccin spécifique requis.",
            "prises": "Type A / B (120V - 60Hz).",
            "monnaie": "Dollar américain (USD - $)",
            "urgences": "911 (Police, Pompiers, Ambulance)",
            "coutumes": "Pourboire obligatoire entre 18 % et 22 % au restaurant ; prix affichés hors taxes.",
        },
        "useful_phrases": [
            {"original": "Could we get the check, please?", "phonetic": "Kood wee get the tchek, pleez?", "translation": "Pourrions-nous avoir l'addition ?"},
        ],
        "places": [
            {
                "name": "Central Park",
                "description": "Poumon vert de 341 hectares au cœur de Manhattan.",
                "category": PlaceCategory.NATURE.value,
                "is_outdoor": True,
                "latitude": 40.7812,
                "longitude": -73.9665,
                "recommended_duration_min": 150,
                "estimated_cost": 0.0,
                "price_tier": TravelStyle.ECONOMIC.value,
                "avg_rating": 4.9,
                "opening_hours": {"daily": "06:00-01:00"},
                "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/0/05/Southwest_corner_of_Central_Park%2C_looking_east%2C_NYC.jpg"],
                "source_provider": "simulated",
            },
            {
                "name": "Metropolitan Museum of Art (The Met)",
                "description": "Le plus grand musée d'art des États-Unis sur la Cinquième Avenue.",
                "category": PlaceCategory.CULTURE.value,
                "is_outdoor": False,
                "latitude": 40.7794,
                "longitude": -73.9632,
                "recommended_duration_min": 150,
                "estimated_cost": 30.0,
                "price_tier": TravelStyle.STANDARD.value,
                "avg_rating": 4.9,
                "opening_hours": {"daily": "10:00-21:00"},
                "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/3/30/Metropolitan_Museum_of_Art_%28The_Met%29_-_Central_Park%2C_NYC.jpg"],
                "source_provider": "simulated",
            },
            {
                "name": "Katz's Delicatessen",
                "description": "Institution new-yorkaise du Lower East Side célèbre pour son pastrami depuis 1888.",
                "category": PlaceCategory.RESTAURANT.value,
                "is_outdoor": False,
                "latitude": 40.7222,
                "longitude": -73.9874,
                "recommended_duration_min": 75,
                "estimated_cost": 32.0,
                "price_tier": TravelStyle.STANDARD.value,
                "avg_rating": 4.7,
                "opening_hours": {"daily": "08:00-23:00"},
                "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/b/b2/Katz%27s_Delicatessen_%2851623899326%29.jpg"],
                "source_provider": "simulated",
            },
        ],
        "accommodations": [
            {
                "type": AccommodationType.HOTEL.value,
                "name": "The Plaza New York",
                "neighborhood": "Midtown / Fifth Avenue",
                "address": "768 5th Ave, New York, NY 10019",
                "latitude": 40.7644,
                "longitude": -73.9745,
                "price_per_night": 1150.0,
                "luxury_tier": TravelStyle.LUXURY.value,
                "rating": 4.9,
                "photos": ["https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?auto=format&fit=crop&w=1000&q=80"],
                "amenities": ["Face à Central Park", "Palm Court", "Spa Guerlain"],
                "source_provider": "hotel_official",
                "booking_redirect_url": "https://www.theplazany.com/",
            },
            {
                "type": AccommodationType.AIRBNB.value,
                "name": "Loft Briques Apparentes SoHo",
                "neighborhood": "SoHo / Lower Manhattan",
                "address": "112 Mercer St, New York, NY 10012",
                "latitude": 40.7243,
                "longitude": -73.9992,
                "price_per_night": 260.0,
                "luxury_tier": TravelStyle.STANDARD.value,
                "rating": 4.75,
                "photos": ["https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?auto=format&fit=crop&w=1000&q=80"],
                "amenities": ["Wi-Fi Gigabit", "Cuisine chef", "Ascenseur privé"],
                "source_provider": "airbnb_partner_redirect",
                "booking_redirect_url": "https://www.airbnb.fr/s/SoHo--New-York/homes",
            },
        ],
        "transports": [],
    },
    {
        "city_name": "Marrakech",
        "country_name": "Maroc",
        "country_code_iso2": "MA",
        "iata_code": "RAK",
        "timezone": "Africa/Casablanca",
        "latitude": 31.6295,
        "longitude": -7.9811,
        "hero_image_url": "https://images.unsplash.com/photo-1597212618440-806262de4f6b?auto=format&fit=crop&w=1400&q=80",
        "description": "La Ville Ocre, entre riads paisibles, souks parfumés de la Médina et sommets de l'Atlas.",
        "practical_info": {
            "visa": "Passeport en cours de validité (exempté de visa jusqu'à 90 jours pour UE/Amérique du Nord).",
            "vaccins": "Aucun vaccin obligatoire ; privilégier l'eau en bouteille.",
            "prises": "Type C / E (220V - 50Hz).",
            "monnaie": "Dirham marocain (MAD)",
            "urgences": "19 (Police), 15 (Ambulance / Pompiers)",
            "coutumes": "Négociation courtoise dans les souks ; demander avant de photographier les artisans.",
        },
        "useful_phrases": [
            {"original": "شكراً جزيلاً (Choukran jazilan)", "phonetic": "Shoo-kran ja-zee-lan", "translation": "Merci beaucoup"},
        ],
        "places": [
            {
                "name": "Jardin Majorelle & Musée Yves Saint Laurent",
                "description": "Oasis botanique au bleu cobalt iconique créée par Jacques Majorelle.",
                "category": PlaceCategory.NATURE.value,
                "is_outdoor": True,
                "latitude": 31.6415,
                "longitude": -8.0033,
                "recommended_duration_min": 120,
                "estimated_cost": 28.0,
                "price_tier": TravelStyle.STANDARD.value,
                "avg_rating": 4.8,
                "opening_hours": {"daily": "08:00-18:30"},
                "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/5/57/Le_jardin_des_majorelle_16.JPG"],
                "source_provider": "simulated",
            },
            {
                "name": "Palais de la Bahia & Musée Dar Si Saïd",
                "description": "Chef-d'œuvre de l'architecture marocaine du XIXe siècle avec salons en zelliges et plafonds de cèdre peint.",
                "category": PlaceCategory.CULTURE.value,
                "is_outdoor": False,
                "latitude": 31.6216,
                "longitude": -7.9830,
                "recommended_duration_min": 90,
                "estimated_cost": 10.0,
                "price_tier": TravelStyle.ECONOMIC.value,
                "avg_rating": 4.8,
                "opening_hours": {"daily": "09:00-18:30"},
                "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/3/3c/Bahia_Palace_Marrakech.jpg"],
                "source_provider": "simulated",
            },
            {
                "name": "La Grande Table Marocaine (Royal Mansour)",
                "description": "Haute gastronomie marocaine dans un palais de la Médina.",
                "category": PlaceCategory.RESTAURANT.value,
                "is_outdoor": False,
                "latitude": 31.6258,
                "longitude": -7.9985,
                "recommended_duration_min": 150,
                "estimated_cost": 195.0,
                "price_tier": TravelStyle.LUXURY.value,
                "avg_rating": 4.9,
                "opening_hours": {"daily": "19:00-23:00"},
                "hero_photos": ["https://images.unsplash.com/photo-1541518763669-27fef04b14ea?auto=format&fit=crop&w=1200&q=80"],
                "source_provider": "simulated",
            },
        ],
        "accommodations": [
            {
                "type": AccommodationType.HOTEL.value,
                "name": "La Mamounia Marrakech",
                "neighborhood": "Médina / Hivernage",
                "address": "Avenue Bab Jdid, Marrakech 40040",
                "latitude": 31.6218,
                "longitude": -7.9971,
                "price_per_night": 880.0,
                "luxury_tier": TravelStyle.LUXURY.value,
                "rating": 4.95,
                "photos": ["https://upload.wikimedia.org/wikipedia/commons/4/41/Entr%C3%A9e_de_l%27h%C3%B4tel_La_Mamounia.jpg"],
                "amenities": ["Jardins de 8 hectares", "Hammam royal", "Piscine chauffée"],
                "source_provider": "hotel_official",
                "booking_redirect_url": "https://mamounia.com/fr/",
            },
            {
                "type": AccommodationType.AIRBNB.value,
                "name": "Riad Patio Andalou Médina",
                "neighborhood": "Médina - Mouassine",
                "address": "Derb Sidi Bouloukat, Marrakech",
                "latitude": 31.6285,
                "longitude": -7.9892,
                "price_per_night": 120.0,
                "luxury_tier": TravelStyle.STANDARD.value,
                "rating": 4.85,
                "photos": ["https://images.unsplash.com/photo-1539020140153-e479b8c22e70?auto=format&fit=crop&w=1000&q=80"],
                "amenities": ["Bassin intérieur", "Toit-terrasse Atlas", "Petit-déjeuner berbère"],
                "source_provider": "airbnb_partner_redirect",
                "booking_redirect_url": "https://www.airbnb.fr/s/Medina--Marrakech/homes",
            },
        ],
        "transports": [],
    },
]


async def seed_initial_data(session: AsyncSession) -> dict[str, int]:
    """Insère de manière idempotente le compte démo, les 5 destinations, leurs lieux et hébergements."""
    created_destinations = 0
    created_places = 0
    created_accommodations = 0

    existing_user = await session.scalar(select(User).where(User.email == "demo@travelmate.app"))
    if not existing_user:
        demo_user = User(
            email="demo@travelmate.app",
            password_hash=hash_password("TravelMate2026!"),
            full_name="Alex Voyageur",
            preferred_style=TravelStyle.STANDARD.value,
        )
        session.add(demo_user)

    for dest_data in SEED_DESTINATIONS:
        dest = await session.scalar(
            select(Destination).where(Destination.city_name == dest_data["city_name"])
        )
        if not dest:
            dest = Destination(
                city_name=dest_data["city_name"],
                country_name=dest_data["country_name"],
                country_code_iso2=dest_data["country_code_iso2"],
                iata_code=dest_data["iata_code"],
                timezone=dest_data["timezone"],
                latitude=dest_data["latitude"],
                longitude=dest_data["longitude"],
                hero_image_url=dest_data["hero_image_url"],
                description=dest_data["description"],
                practical_info=dest_data["practical_info"],
                useful_phrases=dest_data["useful_phrases"],
            )
            session.add(dest)
            await session.flush()
            created_destinations += 1

        for place_data in dest_data.get("places", []):
            existing_place = await session.scalar(
                select(Place).where(
                    Place.destination_id == dest.id,
                    Place.name == place_data["name"],
                )
            )
            if not existing_place:
                session.add(Place(destination_id=dest.id, **place_data))
                created_places += 1
            else:
                existing_place.hero_photos = place_data.get("hero_photos", [])

        for acc_data in dest_data.get("accommodations", []):
            existing_acc = await session.scalar(
                select(Accommodation).where(
                    Accommodation.destination_id == dest.id,
                    Accommodation.name == acc_data["name"],
                )
            )
            if not existing_acc:
                session.add(Accommodation(destination_id=dest.id, **acc_data))
                created_accommodations += 1
            else:
                existing_acc.source_provider = acc_data.get("source_provider", "simulated")
                existing_acc.booking_redirect_url = acc_data.get("booking_redirect_url")
                existing_acc.photos = acc_data.get("photos", [])

        for tr_data in dest_data.get("transports", []):
            existing_tr = await session.scalar(
                select(LocalTransport).where(
                    LocalTransport.destination_id == dest.id,
                    LocalTransport.provider_name == tr_data["provider_name"],
                )
            )
            if not existing_tr:
                session.add(LocalTransport(destination_id=dest.id, **tr_data))

    await session.commit()
    return {
        "destinations_created": created_destinations,
        "places_created": created_places,
        "accommodations_created": created_accommodations,
    }


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    async with AsyncSessionLocal() as session:
        stats = await seed_initial_data(session)
        logger.info("Seed initial terminé : %s", stats)


if __name__ == "__main__":
    asyncio.run(_main())

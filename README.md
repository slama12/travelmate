# TravelMate — Application Web Modulaire de Voyage (PWA)

## Architecture & Étape 1 (Socle)
- **Backend** : Python FastAPI, SQLAlchemy 2.0 Async, Alembic, Redis, Chiffrement enveloppe AES-256-GCM (`cryptography`).
- **Base de données** : PostgreSQL 16 + PostGIS (ou SQLite Async en développement autonome).
- **Adaptateurs Hybrides (`simulated` | `real`)** : Chaque service externe (`gmail`, `calendar`, `flights`, `weather`, `ai`, `places`) possède une interface abstraite commune (`app/core/providers/interfaces.py`) et deux implémentations (`Simulated*Provider` et `Real*Provider`) sélectionnées par variable d'environnement dans `.env`.
- **Frontend** : React 18 + TypeScript + Vite PWA.

## Démarrage rapide (Docker Compose)
```bash
cp .env.example .env
docker compose up --build -d
```
- API & Documentation Swagger : `http://localhost:8000/docs`
- Endpoint de santé & modes des adaptateurs : `http://localhost:8000/health`
- Frontend PWA : `http://localhost:5173`

## Migrations Alembic & Tests
```bash
cd backend
alembic upgrade head
python -m app.core.seed
pytest -v
```

import asyncio
import json

from httpx import ASGITransport, AsyncClient

from app.main import app, lifespan


async def verify() -> None:
    async with lifespan(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8000") as client:
            health_resp = await client.get("/health")
            dest_resp = await client.get("/api/v1/destinations")
            print("\n=== /health PAYLOAD ===")
            print(json.dumps(health_resp.json(), indent=2, ensure_ascii=False))
            print(f"\n=== /api/v1/destinations ({len(dest_resp.json())} destinations) ===")
            for d in dest_resp.json():
                print(f"- {d['city_name']} ({d['country_name']}) [IATA: {d['iata_code']}]")


if __name__ == "__main__":
    asyncio.run(verify())

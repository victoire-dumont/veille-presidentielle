"""
Collecte X/Twitter — Veille Prises de Parole Présidentielle 2027
================================================================
Ce script :
1. Lance un scrape Apify (xtdata~twitter-x-scraper) des tweets récents
2. Associe chaque tweet au candidat via son handle
3. Ignore les tweets déjà en base (dédoublonnage sur l'URL)
4. Tronque l'extrait à 300 caractères
5. Insère les nouveaux tweets en statut "a_valider"
"""

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set

import httpx
from dotenv import load_dotenv

# ── Configuration ──────────────────────────────────────────────

load_dotenv(Path(__file__).parent / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SECRET_KEY")
APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERREUR : SUPABASE_URL et SUPABASE_SECRET_KEY doivent être définis dans .env")
    sys.exit(1)

if not APIFY_TOKEN:
    print("ERREUR : APIFY_API_TOKEN doit être défini dans .env")
    sys.exit(1)

API_URL = f"{SUPABASE_URL}/rest/v1"
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

MAX_EXTRAIT = 300

# Handle X → candidat_id
HANDLES = {
    "retailleau_Actu": "5b46e3e0-e7ef-4b2c-922f-d27b357c469e",
    "EPhilippe_LH": "6719ba84-f674-4964-a7a1-6e7fb8bccd6c",
    "EmmanuelMacron": "45a5b0fe-c818-4abf-97ca-443cfecdc79e",
    "Fabien_Roussel": "82fd2925-aa50-4faa-bdc3-852e43549505",
    "bayrou": "7ae55fe2-f0b0-45f4-b30b-ea0e1920840f",
    "JLMelenchon": "0b34985f-d306-4bfc-ae7b-829151bcaa2c",
    "J_Bardella": "9d509238-cd18-40b7-9444-79185c8a1b9d",
    "marinetondelier": "02d1a794-2fca-4be3-9e74-12239096afd3",
    "faureolivier": "cfeb8813-ccb5-4439-bd12-af003f669d33",
}

# Index inversé pour lookup rapide (lowercase)
HANDLES_LOWER = {h.lower(): cid for h, cid in HANDLES.items()}

APIFY_ACTOR = "xtdata~twitter-x-scraper"
APIFY_BASE = "https://api.apify.com/v2"
TWEETS_PER_HANDLE = 10


# ── Supabase ──────────────────────────────────────────────────

def charger_urls_existantes() -> Set[str]:
    r = httpx.get(f"{API_URL}/prises_de_parole", headers=HEADERS, params={"select": "url"})
    r.raise_for_status()
    return {row["url"] for row in r.json()}


def inserer(entree: Dict) -> bool:
    r = httpx.post(f"{API_URL}/prises_de_parole", headers=HEADERS, json=entree)
    return r.status_code in (200, 201)


# ── Apify ─────────────────────────────────────────────────────

def lancer_scrape(handles: List[str]) -> List[Dict]:
    run_input = {
        "twitterHandles": handles,
        "maxTweets": TWEETS_PER_HANDLE * len(handles),
        "scrapeTweetReplies": False,
    }

    print(f"  Lancement Apify ({APIFY_ACTOR})...")
    r = httpx.post(
        f"{APIFY_BASE}/acts/{APIFY_ACTOR}/runs",
        params={"token": APIFY_TOKEN},
        json=run_input,
        timeout=30,
    )
    r.raise_for_status()
    run_id = r.json()["data"]["id"]
    print(f"  Run ID : {run_id}")

    # Attendre la fin (max 10 min)
    for i in range(60):
        time.sleep(10)
        r = httpx.get(
            f"{APIFY_BASE}/actor-runs/{run_id}",
            params={"token": APIFY_TOKEN},
            timeout=15,
        )
        r.raise_for_status()
        status = r.json()["data"]["status"]

        if status == "SUCCEEDED":
            print(f"  Run terminé en {(i + 1) * 10}s")
            break
        elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
            print(f"  ERREUR : run terminé avec statut {status}")
            return []
        elif i % 3 == 0:
            print(f"  En cours... ({(i + 1) * 10}s)")
    else:
        print("  TIMEOUT : le run Apify n'a pas terminé en 10 min")
        return []

    # Récupérer les résultats
    dataset_id = r.json()["data"]["defaultDatasetId"]
    r = httpx.get(
        f"{APIFY_BASE}/datasets/{dataset_id}/items",
        params={"token": APIFY_TOKEN, "format": "json"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def tronquer(texte: str, max_len: int = MAX_EXTRAIT) -> str:
    if not texte or len(texte) <= max_len:
        return texte or ""
    coupe = texte[:max_len].rsplit(" ", 1)[0]
    return coupe + "…"


# ── Main ──────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Collecte X/Twitter — Veille Présidentielle 2027")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    urls_existantes = charger_urls_existantes()
    print(f"\n✓ {len(urls_existantes)} entrée(s) déjà en base")

    handles = list(HANDLES.keys())
    print(f"\n── Scrape de {len(handles)} comptes X ──")
    for h in handles:
        print(f"  • @{h}")

    tweets = lancer_scrape(handles)
    print(f"\n── {len(tweets)} tweet(s) récupéré(s) ──")

    if not tweets:
        print("Aucun tweet récupéré.")
        return

    nb_nouveaux = 0
    nb_doublons = 0
    nb_inconnus = 0

    for tweet in tweets:
        # Extraire l'URL
        tweet_url = tweet.get("url", "")
        if not tweet_url:
            continue

        # Dédoublonnage
        if tweet_url in urls_existantes:
            nb_doublons += 1
            continue

        # Identifier le candidat via le handle
        author = tweet.get("author", {})
        handle = author.get("screen_name", "") if isinstance(author, dict) else ""

        candidat_id = HANDLES_LOWER.get(handle.lower())
        if not candidat_id:
            nb_inconnus += 1
            continue

        # Contenu du tweet
        texte = tweet.get("full_text", "")
        if not texte:
            continue

        # Date
        date_pub = None
        date_str = tweet.get("created_at", "")
        if date_str:
            try:
                dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
                date_pub = dt.isoformat()
            except ValueError:
                pass

        titre = tronquer(texte, 120)
        extrait = tronquer(texte)

        entree = {
            "candidat_id": candidat_id,
            "date_publication": date_pub,
            "source": f"X (@{handle})",
            "url": tweet_url,
            "titre": titre,
            "extrait": extrait,
            "statut": "a_valider",
        }

        ok = inserer(entree)
        if ok:
            urls_existantes.add(tweet_url)
            nb_nouveaux += 1
            print(f"  + [@{handle}] {titre[:80]}")
        else:
            print(f"  ! Erreur insertion : {titre[:60]}")

    print(f"\n── Résumé ──")
    print(f"  Nouveaux tweets insérés : {nb_nouveaux}")
    print(f"  Ignorés (doublons)      : {nb_doublons}")
    print(f"  Ignorés (handle inconnu): {nb_inconnus}")
    print()


if __name__ == "__main__":
    main()

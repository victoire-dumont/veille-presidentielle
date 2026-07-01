"""
Collecte RSS — Veille Prises de Parole Présidentielle 2027
==========================================================
Ce script :
1. Lit les flux RSS depuis config/feeds.yaml
2. Vérifie que chaque flux répond
3. Pour chaque article, détecte si un candidat est mentionné (via ses mots_cles)
4. Ignore les articles déjà en base (dédoublonnage sur l'URL)
5. Tronque l'extrait à 300 caractères
6. Insère les nouveaux articles en statut "a_valider"
"""

import os
import sys
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set

import feedparser
import httpx
import yaml
from dotenv import load_dotenv

# ── Configuration ──────────────────────────────────────────────

load_dotenv(Path(__file__).parent / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SECRET_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERREUR : SUPABASE_URL et SUPABASE_SECRET_KEY doivent être définis dans .env")
    sys.exit(1)

# Point d'accès REST de Supabase (PostgREST)
API_URL = f"{SUPABASE_URL}/rest/v1"
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

FEEDS_PATH = Path(__file__).parent / "config" / "feeds.yaml"
MAX_EXTRAIT = 300
USER_AGENT = "Mozilla/5.0 (compatible; VeillePresidentielle/1.0)"


# ── Accès Supabase (via API REST) ─────────────────────────────

def charger_candidats() -> List[Dict]:
    """Récupère la liste des candidats actifs depuis Supabase."""
    r = httpx.get(
        f"{API_URL}/candidats",
        headers=HEADERS,
        params={"actif": "eq.true", "select": "*"},
    )
    r.raise_for_status()
    return r.json()


def charger_urls_existantes() -> Set[str]:
    """Récupère toutes les URLs déjà en base pour le dédoublonnage."""
    r = httpx.get(
        f"{API_URL}/prises_de_parole",
        headers=HEADERS,
        params={"select": "url"},
    )
    r.raise_for_status()
    return {row["url"] for row in r.json()}


def inserer_prise_de_parole(entree: Dict) -> bool:
    """Insère une prise de parole. Retourne True si succès."""
    r = httpx.post(
        f"{API_URL}/prises_de_parole",
        headers=HEADERS,
        json=entree,
    )
    return r.status_code in (200, 201)


# ── Flux RSS ───────────────────────────────────────────────────

def charger_feeds(path: Path) -> List[Dict]:
    """Charge la liste des flux depuis le fichier YAML."""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [feed for feed in data["feeds"] if feed.get("actif", True)]


def verifier_feed(feed: Dict) -> Tuple[bool, Optional[feedparser.FeedParserDict]]:
    """Vérifie qu'un flux RSS répond et retourne son contenu."""
    try:
        result = feedparser.parse(feed["url"], agent=USER_AGENT)
        if result.bozo and not result.entries:
            return False, None
        return True, result
    except Exception:
        return False, None


# ── Détection et formatage ─────────────────────────────────────

def detecter_candidat(texte: str, candidats: List[Dict]) -> Optional[Dict]:
    """Cherche si un candidat est mentionné dans le texte via ses mots_cles."""
    texte_lower = texte.lower()
    for candidat in candidats:
        for mot_cle in candidat.get("mots_cles", []):
            if re.search(r'\b' + re.escape(mot_cle.lower()) + r'\b', texte_lower):
                return candidat
    return None


def tronquer_extrait(texte: str, max_len: int = MAX_EXTRAIT) -> str:
    """Tronque le texte à max_len caractères, en coupant au dernier espace."""
    if not texte or len(texte) <= max_len:
        return texte or ""
    coupe = texte[:max_len].rsplit(" ", 1)[0]
    return coupe + "…"


def parser_date(entry) -> Optional[str]:
    """Extrait la date de publication d'une entrée RSS au format ISO."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        return dt.isoformat()
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        dt = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
        return dt.isoformat()
    return None


# ── Script principal ───────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Collecte RSS — Veille Présidentielle 2027")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Vérifier la connexion Supabase
    try:
        candidats = charger_candidats()
    except httpx.HTTPStatusError as e:
        print(f"\nERREUR de connexion Supabase : {e.response.status_code}")
        print(f"  Vérifie SUPABASE_URL et SUPABASE_SECRET_KEY dans .env")
        sys.exit(1)

    if not candidats:
        print("\n⚠  Aucun candidat actif en base. Ajoute des candidats dans la table 'candidats' d'abord.")
        print("   (voir le README pour la marche à suivre)")
        sys.exit(0)
    print(f"\n✓ {len(candidats)} candidat(s) actif(s) chargé(s)")

    # Charger les URLs existantes pour le dédoublonnage
    urls_existantes = charger_urls_existantes()
    print(f"✓ {len(urls_existantes)} article(s) déjà en base")

    # Charger et vérifier les flux
    feeds = charger_feeds(FEEDS_PATH)
    print(f"\n── Vérification des {len(feeds)} flux RSS ──")

    flux_ok = []
    for feed in feeds:
        ok, result = verifier_feed(feed)
        if ok:
            print(f"  ✓ {feed['nom']} — {len(result.entries)} articles")
            flux_ok.append((feed, result))
        else:
            print(f"  ✗ {feed['nom']} — ECHEC ({feed['url']})")

    if not flux_ok:
        print("\nERREUR : aucun flux RSS n'a répondu.")
        sys.exit(1)

    # Parcourir les articles
    print(f"\n── Analyse des articles ──")
    nb_nouveaux = 0
    nb_ignores_doublon = 0
    nb_ignores_aucun_candidat = 0

    for feed, result in flux_ok:
        for entry in result.entries:
            url = entry.get("link", "")
            if not url:
                continue

            # Dédoublonnage
            if url in urls_existantes:
                nb_ignores_doublon += 1
                continue

            # Texte à analyser : titre + résumé
            titre = entry.get("title", "")
            resume = entry.get("summary", "")
            texte_complet = f"{titre} {resume}"

            # Détection de candidat
            candidat = detecter_candidat(texte_complet, candidats)
            if not candidat:
                nb_ignores_aucun_candidat += 1
                continue

            # Préparer l'insertion
            extrait = tronquer_extrait(resume)
            date_pub = parser_date(entry)

            nouvelle_entree = {
                "candidat_id": candidat["id"],
                "date_publication": date_pub,
                "source": feed["nom"],
                "url": url,
                "titre": titre,
                "extrait": extrait,
                "statut": "a_valider",
            }

            # Insérer dans Supabase
            ok = inserer_prise_de_parole(nouvelle_entree)
            if ok:
                urls_existantes.add(url)
                nb_nouveaux += 1
                print(f"  + [{feed['nom']}] {titre[:80]}")
                print(f"    → Candidat : {candidat['nom']}")
            else:
                print(f"  ! Erreur insertion : {titre[:60]}")

    # Résumé
    print(f"\n── Résumé ──")
    print(f"  Nouveaux articles insérés : {nb_nouveaux}")
    print(f"  Ignorés (doublons)        : {nb_ignores_doublon}")
    print(f"  Ignorés (aucun candidat)  : {nb_ignores_aucun_candidat}")
    print()


if __name__ == "__main__":
    main()

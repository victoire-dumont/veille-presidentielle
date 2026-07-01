# Veille Prises de Parole — Présidentielle 2027

Outil de veille automatisée des prises de parole des candidats à la présidentielle française dans les médias.

## Installation

### 1. Cloner le dépôt

```bash
git clone <url-du-repo>
cd veille-presidentielle
```

### 2. Créer un environnement Python et installer les dépendances

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configurer les clés Supabase

```bash
cp .env.example .env
```

Ouvre `.env` et renseigne tes clés Supabase (Dashboard → Settings → API) :
- `SUPABASE_URL` : l'URL de ton projet
- `SUPABASE_SERVICE_ROLE_KEY` : la clé `service_role`

### 4. Ajouter des candidats

Dans le Dashboard Supabase → Table Editor → table `candidats`, clique **Insert row** :

| Champ | Exemple |
|-------|---------|
| nom | Marine Le Pen |
| parti | Rassemblement National |
| actif | true |
| mots_cles | {Marine Le Pen, Le Pen, MLP} |

Tu peux aussi le faire en SQL :

```sql
INSERT INTO candidats (nom, parti, mots_cles) VALUES
  ('Marine Le Pen', 'Rassemblement National', ARRAY['Marine Le Pen', 'Le Pen', 'MLP']),
  ('Emmanuel Macron', NULL, ARRAY['Emmanuel Macron', 'Macron']);
```

**Conseil** : mets plusieurs variantes dans `mots_cles` pour ne rien rater (nom complet, nom de famille seul, initiales courantes).

### 5. Lancer la collecte

```bash
python collect.py
```

## Modifier les flux RSS

Édite `config/feeds.yaml`. Pour désactiver un flux sans le supprimer, mets `actif: false`.

## Modifier les candidats

- **Ajouter** : insère une ligne dans la table `candidats` (via le Dashboard ou en SQL)
- **Retirer** : mets `actif` à `false` (les données existantes sont conservées)
- **Modifier les mots-clés** : modifie le champ `mots_cles` du candidat

## Statuts des articles

| Statut | Signification |
|--------|---------------|
| `a_valider` | Vient d'être collecté, en attente de validation humaine |
| `valide` | Validé, visible sur le site public |
| `rejete` | Rejeté (faux positif, hors sujet…) |

## Architecture

```
veille-presidentielle/
├── config/
│   └── feeds.yaml          ← flux RSS à surveiller
├── collect.py              ← script de collecte
├── requirements.txt        ← dépendances Python
├── .env.example            ← modèle de configuration
├── .env                    ← tes clés (non versionné)
└── README.md               ← ce fichier
```

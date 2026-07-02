# ScamGuard

Bot Discord de détection de scams crypto par **OCR** et **similarité d'images**.

Analyse automatiquement les messages et images pour détecter les tentatives de fraudes : giveaways bidons, vol de seed phrase, faux airdrops, phishing wallet, etc.

## Fonctionnement

1. Le bot écoute tous les messages du serveur (texte + images)
2. Le **texte** est analysé via des patterns regex pondérés
3. Les **images** passent par un **OCR** (easyocr) pour extraire le texte
4. Les images sont comparées aux **images interdites** via hash perceptuel (pHash)
5. Un **score total** est calculé → alerte si ≥ seuil configuré

### Système de score

| Score | Action |
|-------|--------|
| < 30 | Ignoré |
| 30–49 | Réaction ⚠️ + log |
| ≥ 50 | Réaction 🚨 + alerte + notification |

### Patterns de détection

| Pattern | Poids | Exemple |
|---------|-------|---------|
| Wallet / seed phrase | **50** | "verify your metamask" |
| Doubler crypto | **35** | "doublez vos bitcoin" |
| Casino crypto | **35** | "crypto casino gambling" |
| Giveaway crypto | **30** | "free eth giveaway" |
| Célébrité / influenceur | **30** | "elon musk announce giveaway" |
| Airdrop / claim | **25** | "claim free token" |
| Projet fake | **25** | "safemoon project launch" |
| Lancement crypto | **20** | "introducing my crypto token" |
| URL frauduleuse | **20** | "free-eth.xyz" |
| Faux investissement | **20** | "investir dans crypto" |
| TLD suspect | **10** | ".xyz", ".click", ".gq" |
| Pression retrait | **10** | "withdraw your reward" |
| Presale | **10** | "whitelist allowlist" |
| Urgence / promo | **5** | "dernière chance" (combiné) |

Les patterns sont configurables dans `config/patterns.json5`.

### Similarité d'images (pHash)

Des images de référence dans `banned_images/` sont comparées via hash perceptuel. Si la distance ≤ seuil (défaut: 20), l'image est flaggée et ajoute +50 au score.

## Commandes slash

| Commande | Description |
|----------|-------------|
| `/ping` | Affiche la latence du bot |
| `/test-detect <message_id> [channel]` | Analyse un message spécifique |
| `/config show` | Affiche la configuration actuelle (admin) |
| `/config reload` | Recharge les configs JSON (admin) |

## Installation

### Prérequis

- Python 3.10+
- Un bot Discord (token)

### Setup

```bash
# Cloner le repo
git clone https://github.com/VOTRE_USER/ScamGuard.git
cd ScamGuard

# Environnement virtuel
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Dépendances
pip install -r requirements.txt

# Configuration
cp .env.example .env
# Éditer .env avec votre token Discord
```

### Configuration Discord

1. Aller sur https://discord.com/developers/applications
2. **New Application** → **Bot** → **Add Bot**
3. Copier le token dans `.env`
4. Activer les Intents :
   - ✅ SERVER MEMBERS INTENT
   - ✅ MESSAGE CONTENT INTENT
5. Inviter le bot avec les permissions : `Send Messages`, `Read Messages`, `Attach Files`, `Read Message History`, `Add Reactions`

### Lancement

```bash
python bot.py
```

> Au premier lancement, easyocr télécharge ses modèles (~100 Mo).

## Configuration

### Fichiers de config

| Fichier | Description |
|---------|-------------|
| `config/patterns.json5` | Patterns regex + poids |
| `config/settings.json5` | Seuils, OCR, notifications, etc. |
| `.env` | Token Discord |

### Paramètres principaux (`settings.json5`)

| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `score_alert` | 50 | Score minimum pour alerte scam |
| `score_warn` | 30 | Score minimum pour warning |
| `language` | `["fr", "en"]` | Langues OCR |
| `banned_images_threshold` | 20 | Distance pHash max pour match |
| `banned_images_score` | 50 | Points ajoutés si image interdite |
| `auto_delete` | false | Supprimer auto les messages scam |
| `cooldown_seconds` | 300 | Anti-spam alerts (5 min) |

### Hot-reload

Modifier les fichiers JSON5 puis `/config reload` en jeu — pas besoin de redémarrer.

## Structure

```
ScamGuard/
├── bot.py                  # Point d'entrée, config, logging
├── cogs/
│   ├── core.py             # /ping, /test-detect, /config
│   └── monitor.py          # Moteur de détection (OCR + pHash)
├── config/
│   ├── patterns.json5      # Patterns regex pondérés
│   └── settings.json5      # Paramètres globaux
├── banned_images/          # Images de référence (pHash)
├── requirements.txt
├── .env.example
└── README.md
```

## Dépendances

| Package | Usage |
|---------|-------|
| `discord.py` | Bot Discord |
| `easyocr` | OCR sur images |
| `Pillow` | Manipulation d'images |
| `imagehash` | Hash perceptuel (pHash) |
| `aiohttp` | Téléchargement images |
| `python-dotenv` | Variables d'environnement |
| `json5` | Config JSON5 |
| `colorama` | Logs colorés |

## Licence

MIT

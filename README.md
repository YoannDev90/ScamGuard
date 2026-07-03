# ScamGuard

Bot Discord de détection de scams crypto par **OCR**, **mots-clés pondérés**, **signaux utilisateur** et **réputation URL**.

Analyse automatique des messages et images pour détecter : giveaways, vol de seed phrase, faux airdrops, phishing wallet, etc.

## Fonctionnement

1. Écoute tous les messages (texte + images)
2. **Mots-clés** : correspondance insensible à la casse, poids cumulables
3. **OCR** (easyocr) extrait le texte des images
4. **Images interdites** : hash perceptuel (pHash) sur `banned_images/`
5. **Signaux utilisateur** : âge compte, âge serveur, première interaction, cross-posting, avatar, image-only
6. **URL** : shorteners, TLD suspects, IP-based, âge domaine (whois), whitelist
7. **IA** (optionnel) : second avis via LLM (provider configurable, prompts dédiés, désactivé par défaut)
8. **Nettoyage** : si action `delete`, supprime les messages récents du même user dans tous les salons
9. **Score total** → alerte si ≥ seuil

### Système de score

| Score | Niveau |
|-------|--------|
| < 30 | OK |
| 30–49 | ⚠️ Suspicious |
| ≥ 50 | 🚨 Scam alert |

Chaque facteur (keyword, signal, URL, OCR, IA) ajoute son poids. Configurable via `/config set`.

## Commandes

### Générales

| Commande | Description |
|----------|-------------|
| `/ping` | Latence |
| `/guide` | Vue d'ensemble |
| `/setup` | Configuration interactive (4 étapes) |
| `/test-detect <id>` | Analyse un message (admin) |
| `/scan [channel] [limit]` | Scan rétroactif (admin, défaut 50, max 200) |
| `/stats` | Statistiques de détection |
| `/stats-reset` | Réinitialise les stats (admin) |

### Commandes de configuration

| Commande | Description |
|----------|-------------|
| `/config show` | Affiche toute la configuration |
| `/config get <key>` | Lit une valeur |
| `/config set <key> <value>` | Modifie un paramètre (validation type) |
| `/config reload` | Recharge depuis les fichiers |
| `/config reset` | Réinitialise la config du serveur |
| `/config channel [channel]` | Définit le salon d'alerte |
| `/config banned-add` | Ajoute une image interdite (phash) |
| `/config ignore` | Ignorer / ne plus ignorer |
| `/actions list [trigger]` | Liste les actions configurées |
| `/actions add <trigger> <action>` | Ajoute une action |
| `/actions remove <trigger> <index>` | Supprime une action |
| `/actions clear <trigger>` | Vide les actions |
| `/keywords list` | Liste paginée des mots-clés |
| `/keywords add <word> <weight> [desc]` | Ajoute un mot-clé |
| `/keywords remove <word>` | Supprime un mot-clé |
| `/keywords toggle <word>` | Active/désactive un mot-clé |
| `/whitelist domain-add <domain>` | Whiteliste un domaine |
| `/whitelist domain-remove <domain>` | Supprime un domaine |
| `/whitelist domains` | Liste des domaines whitelistés |
| `/whitelist user add/remove <user>` | Whiteliste un user (/test-detect) |
| `/whitelist users` | Liste des users whitelistés |
| `/versions list` | Historique des versions |
| `/versions revert <version>` | Revenir à une version |

### Types d'actions

| Action | Paramètres | Perm. requise |
|--------|------------|---------------|
| `delete` | — | manage_messages |
| `warn` | message (opt.) | — |
| `kick` | — | kick_members |
| `ban` | — | ban_members |
| `softban` | — | ban_members |
| `timeout` | duration (min) | moderate_members |
| `notify_channel` | channel | send_messages |
| `notify_role` | role | send_messages |
| `notify_user` | user | send_messages |
| `add_role` / `remove_role` | role | manage_roles |
| `log` | channel | send_messages |

Le bot vérifie ses permissions avant chaque action. Action sautée si permission manquante.

**Cooldown** : `cooldown_seconds` évite uniquement le spam d'alerte dans le salon. Les actions sont toujours exécutées sur chaque message détecté.

**Batch cleanup** : si l'action `delete` est configurée, le bot supprime automatiquement les messages récents (30 derniers) du même utilisateur dans **tous les salons** du serveur.

## Installation

### Prérequis

- Python 3.10+
- Bot Discord (token)

### Setup

```bash
git clone https://github.com/anomalyco/ScamGuard.git
cd ScamGuard
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
pip install -r requirements.txt
cp .env.example .env
# Éditer .env avec votre token Discord
```

### Configuration Discord

1. https://discord.com/developers/applications → New Application → Bot → Add Bot
2. Copier le token dans `.env`
3. Intents requis : SERVER MEMBERS, MESSAGE CONTENT
4. Permissions : Send Messages, Read Messages/History, Add Reactions, Attach Files + Kick/Ban/Moderate Members, Manage Roles/Messages selon les actions

### Lancement

```bash
python bot.py           # Précharge OCR au démarrage (~100 Mo)
python bot.py --light   # Skip préchargement OCR
```

## Configuration

### Fichiers

| Fichier | Description |
|---------|-------------|
| `config/keywords.json` | Mots-clés (poids, description) |
| `config/settings.json` | Paramètres globaux |
| `config/providers.json` | Providers IA (endpoint, env_key) |
| `config/models.json` | Modèles IA (provider, vision, endpoint_type) |
| `config/prompts/` | Prompts IA (anglais, par endpoint) |
| `banned_images/` | Images de référence (pHash) |
| `data/guilds/` | Config par serveur |
| `data/stats/` | Statistiques de détection |
| `data/session/` | Session persistée (seen_users, crosspost) |
| `logs/` | Logs journaliers |

### Paramètres principaux

| Catégorie | Exemples |
|-----------|----------|
| Seuils | `score_alert` (50), `score_warn` (30) |
| OCR | `language`, `max_ocr_length` |
| Images | `banned_images_threshold`, `banned_images_score` |
| Signaux | `signal_account_age_days`, `signal_first_interaction_score` |
| URL | `url_shorteners`, `suspect_tlds`, `url_new_domain_days` |
| IA | `ai_enabled` (false), `ai_model`, `ai_score_bonus` |
| UX | `cooldown_seconds` (alerte only), `auto_delete`, `dm_author_on_alert` |

## Structure

```
ScamGuard/
├── bot.py                  # Point d'entrée
├── cogs/
│   ├── _detection.py       # Moteur : OCR, keywords, signaux, URL, IA
│   ├── _actions.py         # Exécution des actions
│   ├── monitor.py          # Écoute messages + alertes
│   ├── config.py           # Commandes /config + setup wizard
│   ├── core.py             # /ping, /test-detect, /scan, welcome
│   └── stats.py            # /stats
├── core/
│   ├── config.py           # ConfigManager, GuildConfig, VersionManager
│   ├── stats.py            # StatsManager
│   └── ai_config.py        # AiConfig (providers, models, prompts)
├── config/
│   ├── keywords.json       # Mots-clés pondérés
│   ├── settings.json       # Paramètres globaux
│   ├── providers.json      # Providers IA
│   ├── models.json         # Modèles IA
│   └── prompts/            # Prompts IA (anglais)
├── banned_images/          # Images de référence (phash)
├── data/
│   ├── guilds/             # Config par guild
│   ├── stats/              # Stats par guild
│   ├── session/            # Session persistée
│   └── ocr_cache/          # Cache OCR disque
├── logs/                   # Logs
├── requirements.txt
├── .env.example
└── README.md
```

## Dépendances

| Package | Usage |
|---------|-------|
| `discord.py` | Bot Discord |
| `easyocr` | OCR images |
| `Pillow` + `imagehash` | pHash images |
| `aiohttp` | Téléchargement HTTP |
| `litellm` | Routing IA (multi-provider) |
| `whois` | Âge domaine |
| `python-dotenv` | .env |
| `colorama` | Logs colorés |

## Licence

MIT

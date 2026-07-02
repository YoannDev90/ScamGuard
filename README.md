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

### Configuration (admin)

Toute la config se gère depuis Discord (`/config`). Les fichiers JSON5 sont mis à jour automatiquement.

| Sous-commande | Description |
|---------------|-------------|
| `/config show` | Affiche toute la configuration (patterns, actions, paramètres) |
| `/config get <key>` | Affiche une valeur spécifique |
| `/config set <key> <value>` | Modifie un paramètre |
| `/config reload` | Recharge depuis les fichiers JSON5 |

**Gestion des actions :**

| Sous-commande | Description |
|---------------|-------------|
| `/config actions-list [trigger]` | Liste les actions par déclencheur |
| `/config actions-add <trigger> <action>` | Ajoute une action (voir ci-dessous) |
| `/config actions-remove <trigger> <index>` | Supprime une action |
| `/config actions-clear <trigger>` | Vide toutes les actions d'un déclencheur |

**Gestion des patterns :**

| Sous-commande | Description |
|---------------|-------------|
| `/config patterns-list` | Liste tous les patterns |
| `/config patterns-add <name> <regex> <weight>` | Ajoute un pattern |
| `/config patterns-remove <name>` | Supprime un pattern |
| `/config patterns-toggle <name>` | Active/désactive un pattern |

**Gestion des ignorés :**

| Sous-commande | Description |
|---------------|-------------|
| `/config ignore add user <user>` | Ignore un utilisateur |
| `/config ignore add role <role>` | Ignore un rôle |
| `/config ignore add channel <channel>` | Ignore un salon |
| `/config ignore remove user <user>` | Ne plus ignorer |
| `/config ignore remove role <role>` | Ne plus ignorer |
| `/config ignore remove channel <channel>` | Ne plus ignorer |

### Système d'actions

Configurez ce que le bot fait automatiquement en fonction du déclencheur.

**Déclencheurs (trigger) :**

| Trigger | Quand ? |
|---------|---------|
| `scam` | Score ≥ seuil alerte (50) |
| `suspicious` | Score ≥ seuil warning (30) |
| `banned_image` | Image interdite détectée (pHash) |

**Types d'actions :**

| Action | Paramètres | Effet |
|--------|------------|-------|
| `delete` | — | Supprime le message |
| `warn` | `message` (optionnel) | Envoie un DM d'avertissement |
| `kick` | — | Exclut l'auteur |
| `ban` | — | Bannit l'auteur |
| `softban` | — | Ban + unban (supprime les messages) |
| `timeout` | `duration` (minutes) | Timeout l'auteur |
| `notify_channel` | `channel` | Envoie une alerte dans un salon |
| `notify_role` | `role` | Ping un rôle dans le salon d'alerte |
| `notify_user` | `user` | Ping un utilisateur |
| `add_role` | `role` | Ajoute un rôle à l'auteur |
| `remove_role` | `role` | Retire un rôle à l'auteur |
| `log` | `channel` | Journalise dans un salon |

**Exemples :**

```bash
/config actions-add trigger:scam action:delete
/config actions-add trigger:scam action:notify_channel channel:#alerts
/config actions-add trigger:scam action:timeout duration:30
/config actions-add trigger:banned_image action:kick
/config actions-add trigger:suspicious action:warn message:"Attention, ce message est suspect"
/config actions-add trigger:banned_image action:add_role role:@Muted
```

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
5. Inviter le bot avec les permissions nécessaires selon les actions configurées :
   - **De base** : `Send Messages`, `Read Messages`, `Read Message History`, `Add Reactions`, `Attach Files`
   - **Pour les actions** : `Kick Members`, `Ban Members`, `Moderate Members` (timeout), `Manage Roles`, `Manage Messages`

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

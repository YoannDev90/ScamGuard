# ScamGuard

Discord bot for crypto scam detection using **OCR**, **weighted keywords**, **user behavioral signals**, **URL reputation**, and optional **AI second opinion**.

## Quick Features

- Keyword matching (case-insensitive, weighted)
- OCR text extraction from images (easyocr)
- Perceptual hash matching against banned images
- User signals: account age, join age, first interaction, cross-posting, avatar, image-only
- URL checks: shorteners, suspect TLDs, IP-based, domain age (whois), whitelist
- AI second opinion via litellm (optional, disabled by default)
- Retroactive message scan (`/config scan`)
- Detection statistics (`/config stats`)
- Configurable actions (delete, warn, kick, ban, timeout, notify...)
- Batch cleanup across all channels on scam detection
- Per-guild configuration with version history and rollback

## Quick Start

```
# Install
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your bot token

# Run
python bot.py
```

Full setup guide → **[SETUP.md](SETUP.md)**

Complete configuration reference → **[CONFIG.md](CONFIG.md)**

## Most Used Commands

| Command | What it does |
|---------|-------------|
| `/config show` | View all settings |
| `/config set <key> <value>` | Change a setting |
| `/config actions add <trigger> <type>` | Add auto-action |
| `/config keywords list` | List detection keywords |
| `/config channel` | Set alert channel |
| `/test-detect <id>` | Test detection on a message |
| `/scan` | Scan recent messages |
| `/stats` | Detection statistics |
| `/setup` | Interactive configuration wizard |
| `/guide` | Overview and help |

## Requirements

- Python 3.10+
- Discord bot token ([create one](https://discord.com/developers/applications))

## Dependencies

| Package | Use |
|---------|-----|
| `discord.py` | Bot framework |
| `easyocr` | Image OCR |
| `Pillow` + `imagehash` | Perceptual hashing |
| `aiohttp` | HTTP downloads |
| `whois` | Domain age lookup |
| `litellm` | AI routing (optional) |
| `python-dotenv` | .env loading |
| `colorama` | Colored logs |

## License

MIT

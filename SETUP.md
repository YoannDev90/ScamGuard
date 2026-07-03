# Setup

## Prerequisites

- Python 3.10+
- A Discord application with a bot token

## Step 1: Create a Discord Application

1. Go to https://discord.com/developers/applications
2. Click **New Application** → give it a name → **Create**
3. Go to **Bot** tab (left sidebar)
4. Click **Add Bot** → confirm
5. Under **Privileged Gateway Intents**, enable:
   - ✅ **SERVER MEMBERS INTENT**
   - ✅ **MESSAGE CONTENT INTENT**
6. Copy the **Token** (click **Reset Token** if needed) — you'll need it for `.env`

## Step 2: Invite the Bot

1. Go to **OAuth2** → **URL Generator**
2. Under **Scopes**, check:
   - ✅ `bot`
   - ✅ `applications.commands`
3. Under **Bot Permissions**, check the minimum:
   - ✅ `Send Messages`
   - ✅ `Read Messages` / `View Channels`
   - ✅ `Read Message History`
   - ✅ `Add Reactions`
   - ✅ `Attach Files`
   
   Depending on the actions you configure, you may also need:
   - `Manage Messages` — for `/config actions add delete`
   - `Kick Members` — for kick action
   - `Ban Members` — for ban / softban action
   - `Moderate Members` — for timeout action
   - `Manage Roles` — for add_role / remove_role actions
4. Open the generated URL in your browser → select a server → **Authorize**

## Step 3: Install the Bot

```bash
git clone https://github.com/YoannDev90/ScamGuard.git
cd ScamGuard
python3 -m venv .venv
source .venv/bin/activate      # Linux / macOS
.venv\Scripts\activate         # Windows
pip install -r requirements.txt
```

## Step 4: Configure

```bash
cp .env.example .env
```

Edit `.env`:

```
DISCORD_TOKEN="your_bot_token_here"
```

Optional — for instant command sync during development:

```
DEV_GUILD_ID=123456789012345678
```

Replace with your test server's ID (enable Developer Mode in Discord → right-click server → Copy ID).

## Step 5: Run

```bash
python bot.py
```

The first launch downloads easyocr models (~100 MB). Use `--light` to skip preloading:

```bash
python bot.py --light
```

## Development

- Commands sync globally by default (up to 1h propagation).
- Set `DEV_GUILD_ID` in `.env` for instant guild-local sync.

## Updating

```bash
git pull
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

## Troubleshooting

| Problem | Likely cause | Fix |
|---------|-------------|-----|
| Bot doesn't respond | Wrong token | Check `DISCORD_TOKEN` in `.env` |
| Commands not showing | Cache propagation | Wait up to 1h or set `DEV_GUILD_ID` |
| Missing intents | Intents not enabled in dev portal | Enable SERVER MEMBERS + MESSAGE CONTENT |
| OCR model download fails | Network / disk space | Run with `--light`, model downloads on first use |

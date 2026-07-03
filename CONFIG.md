# Configuration

All configuration is managed through files in `config/` and per-guild settings via Discord slash commands.

---

## Files

| File | Description |
|------|-------------|
| `config/settings.json` | Global parameters |
| `config/keywords.json` | Weighted keyword list |
| `config/providers.json` | AI provider definitions |
| `config/models.json` | AI model definitions |
| `config/prompts/` | AI prompt files (English) |
| `banned_images/` | Reference images for perceptual hash matching |
| `data/guilds/` | Per-guild config (auto-managed) |
| `data/stats/` | Detection statistics |
| `data/session/` | Session persistence (seen users, crosspost) |
| `logs/` | Daily rotating logs |

---

## Settings (`settings.json`)

You can modify `config/settings.json` directly or use `/config set <key> <value>` in Discord. Values are validated by type.

### Scoring

| Key | Default | Description |
|-----|---------|-------------|
| `score_alert` | `50` | Score threshold for scam alert |
| `score_warn` | `30` | Score threshold for suspicious warning |
| `no_text_bonus` | `10` | Bonus when image has OCR text but no author text |
| `message_min_length` | `15` | Minimum message length to analyze |

### OCR

| Key | Default | Description |
|-----|---------|-------------|
| `language` | `["fr", "en"]` | OCR languages |
| `max_ocr_length` | `10000` | Max OCR text length to process |
| `image_max_size` | `5242880` | Max image download size (bytes) |
| `image_download_timeout` | `30` | Image download timeout (seconds) |
| `supported_extensions` | `[".png",".jpg",".gif",...]` | Image extensions to check |
| `image_url_regex` | regex | Regex to find image URLs in message text |

### Banned Images

| Key | Default | Description |
|-----|---------|-------------|
| `banned_images_dir` | `"banned_images"` | Directory for reference images |
| `banned_images_threshold` | `20` | Perceptual hash distance threshold |
| `banned_images_score` | `50` | Score added on match |

### Alerts & Notifications

| Key | Default | Description |
|-----|---------|-------------|
| `alert_channel_id` | `null` | Channel for alerts (set via `/config channel`) |
| `log_channel_names` | `["logs","admin",...]` | Fallback channel name search |
| `ping_role_id` | `null` | Role to ping on alert |
| `dm_author_on_alert` | `false` | DM the flagged user |
| `auto_delete` | `false` | Auto-delete scam messages |
| `cooldown_seconds` | `300` | Alert cooldown per user (skips duplicate alerts, actions always fire) |

### Reactions

| Key | Default | Description |
|-----|---------|-------------|
| `reactions.scam` | `🚨` | Reaction on scam |
| `reactions.suspicious` | `⚠️` | Reaction on suspicious |
| `reactions.banned_image` | `🛡️` | Reaction on banned image |
| `reactions.clear` | `✅` | Remove bot reactions |
| `reactions.community_alert` | `🚨` | Community confidence reaction |

### Community

| Key | Default | Description |
|-----|---------|-------------|
| `community_confirm_count` | `3` | Reactions needed for community alert |
| `report_emoji` | `👮` | Report emoji |
| `enable_report` | `true` | Enable report system |

### User Signals

| Key | Default | Description |
|-----|---------|-------------|
| `signal_account_age_days` | `30` | Account younger than this gets bonus |
| `signal_account_age_score` | `15` | Bonus points |
| `signal_join_age_days` | `7` | Joined server less than this ago |
| `signal_join_age_score` | `15` | Bonus points |
| `signal_first_interaction_score` | `10` | First message bonus |
| `signal_image_only_score` | `10` | Image/link without text |
| `signal_no_avatar_score` | `5` | Default avatar |
| `signal_crosspost_score` | `20` | Same content across multiple channels |
| `signal_crosspost_window` | `300` | Time window (seconds) |
| `signal_crosspost_min_channels` | `2` | Minimum channels to trigger |

### URL Detection

| Key | Default | Description |
|-----|---------|-------------|
| `trusted_domains` | `["discord.com","youtube.com",...]` | Skipped for all URL checks |
| `url_shorteners` | `["bit.ly","tinyurl.com",...]` | Known shortener domains |
| `suspect_tlds` | `[".xyz",".top",".gq",...]` | Suspicious TLDs |
| `url_new_domain_days` | `30` | Domain age threshold |
| `url_new_domain_score` | `25` | New domain bonus |
| `url_shortener_score` | `15` | Shortener bonus |
| `url_ip_score` | `20` | IP-based domain bonus |
| `url_suspect_tld_score` | `10` | Suspect TLD bonus |
| `url_max_score` | `50` | Max total from URL checks |

### AI

| Key | Default | Description |
|-----|---------|-------------|
| `ai_enabled` | `false` | Enable AI second opinion |
| `ai_model` | `"gpt-4o-mini"` | Model name (from models.json) |
| `ai_score_bonus` | `30` | Score if AI flags as scam |

### Debug

| Key | Default | Description |
|-----|---------|-------------|
| `debug_mode` | `true` | Enable debug features |
| `logging_level` | `"DEBUG"` | Logging verbosity |

---

## Keywords (`keywords.json`)

Keywords are matched case-insensitively as substrings. Each has:

```json
{"word": "seed phrase", "weight": 50, "desc": "Seed phrase theft", "enabled": true}
```

| Field | Description |
|-------|-------------|
| `word` | Text to match (substring, case-insensitive) |
| `weight` | Score contribution on match |
| `desc` | Human-readable description |
| `enabled` | Toggle without deleting |

Keywords can be managed via `/config keywords list|add|remove|toggle`.

---

## AI Configuration

### Providers (`providers.json`)

```json
{
  "openai": {
    "endpoint": "https://api.openai.com/v1",
    "env_key": "OPENAI_API_KEY"
  }
}
```

| Field | Description |
|-------|-------------|
| `endpoint` | API base URL |
| `env_key` | Environment variable name for the API key (case-sensitive) |

Built-in providers: `openai`, `openrouter`, `anthropic`. Add custom ones.

### Models (`models.json`)

```json
{
  "gpt-4o-mini": {
    "provider": "openai",
    "model": "gpt-4o-mini",
    "vision": true,
    "endpoint_type": "responses"
  }
}
```

| Field | Description |
|-------|-------------|
| `provider` | Reference to a provider in providers.json |
| `model` | Model name passed to the API |
| `vision` | Whether the model supports image input |
| `endpoint_type` | `responses` (OpenAI), `messages` (Anthropic), or `moderations` |

### Prompts (`config/prompts/`)

- `scam_responses.txt` — Prompt for `/v1/responses` endpoint
- `scam_messages.txt` — Prompt for `/v1/messages` endpoint
- `scam_moderations.txt` — Prompt for moderation endpoint

Prompts are in English. litellm handles routing based on the model prefix (`openai/`, `anthropic/`).

---

## Slash Commands

### General

| Command | Description | Permissions |
|---------|-------------|-------------|
| `/config ping` | Bot latency | anyone |
| `/config guide` | Quick overview | anyone |
| `/config setup` | Interactive wizard (4 steps) | anyone |
| `/config test-detect <id>` | Analyze a message | manage_guild or whitelisted |
| `/config scan [channel] [limit]` | Retroactive scan | manage_guild |
| `/config stats` | Detection statistics | anyone |
| `/config stats-reset` | Reset stats | manage_guild |

### Config Management

| Command | Description | Permissions |
|---------|-------------|-------------|
| `/config show` | Full configuration | anyone |
| `/config get <key>` | Read a setting | anyone |
| `/config set <key> <value>` | Change a setting (validated) | manage_guild |
| `/config reload` | Reload from files | manage_guild |
| `/config reset` | Reset guild config | manage_guild |
| `/config channel [channel]` | Set alert channel | manage_guild |
| `/config banned-add` | Add banned image (phash) | manage_guild |
| `/config ignore` | Add/remove ignore user/role/channel | manage_guild |
| `/config ignore-list` | List ignored entities | anyone |
| `/config export` | Export config as JSON | manage_guild |
| `/config import <file>` | Import config from JSON file | manage_guild |

### Actions

| Command | Description | Permissions |
|---------|-------------|-------------|
| `/config actions list [trigger]` | List configured actions | anyone |
| `/config actions add <trigger> <action>` | Add action | manage_guild |
| `/config actions remove <trigger> <index>` | Remove action | manage_guild |
| `/config actions clear <trigger>` | Clear all actions | manage_guild |

**Triggers**: `scam` (score ≥ alert), `suspicious` (score ≥ warn)

**Action types**:

| Type | Params | Bot permission required |
|------|--------|------------------------|
| `delete` | — | manage_messages |
| `warn` | message (optional) | — |
| `kick` | — | kick_members |
| `ban` | — | ban_members |
| `softban` | — | ban_members |
| `timeout` | duration (minutes) | moderate_members |
| `notify_channel` | channel | send_messages |
| `notify_role` | role | send_messages |
| `notify_user` | user | send_messages |
| `add_role` / `remove_role` | role | manage_roles |
| `log` | channel | send_messages |

Bot checks permissions before executing each action. Skipped if missing.

**Batch cleanup**: if `delete` is configured, bot deletes recent messages (last 30) from the same user across **all channels** where it has `manage_messages`.

### Keywords

| Command | Description | Permissions |
|---------|-------------|-------------|
| `/config keywords list` | List keywords (paginated) | anyone |
| `/config keywords add <word> <weight> [desc]` | Add keyword | manage_guild |
| `/config keywords remove <word>` | Remove keyword | manage_guild |
| `/config keywords toggle <word>` | Enable/disable | manage_guild |

### Whitelist

| Command | Description | Permissions |
|---------|-------------|-------------|
| `/config whitelist domain-add <domain>` | Whitelist domain (bypass URL checks) | manage_guild |
| `/config whitelist domain-remove <domain>` | Unwhitelist domain | manage_guild |
| `/config whitelist domains` | List whitelisted domains | anyone |
| `/config whitelist user add/remove <user>` | Whitelist user for `/test-detect` | manage_guild |
| `/config whitelist users` | List whitelisted users | anyone |

### Versions

| Command | Description | Permissions |
|---------|-------------|-------------|
| `/config versions list` | Version history | anyone |
| `/config versions revert <version>` | Revert config | manage_guild |

---

## Actions System

When a message is flagged, the bot executes all actions configured for the trigger level:

- **scam** (score ≥ `score_alert`) → `scam` action list
- **suspicious** (score ≥ `score_warn`, but < `score_alert`) → `suspicious` action list

Actions are executed on **every** flagged message. The `cooldown_seconds` only suppresses the **alert embed**, not the actions.

If `delete` is in the action list and the bot has `manage_messages` permission, it also **batch-cleans** recent messages from the same user across all channels.

---

## Scoring System

Total score = keyword matches + OCR text bonus + user signals + URL reputation + AI verdict.

| Source | Typical range |
|--------|---------------|
| Keyword match | 5–50 per match |
| No text bonus | +10 |
| Account age | +15 |
| Join age | +15 |
| First interaction | +10 |
| Image only | +10 |
| No avatar | +5 |
| Cross-posting | +20 |
| URL shortener | +15 |
| IP-based domain | +20 |
| Suspect TLD | +10 |
| New domain | +25 |
| AI verdict | +30 (if enabled and flagged) |

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | Yes | Bot token from dev portal |
| `DEV_GUILD_ID` | No | Guild ID for instant command sync |
| `OPENAI_API_KEY` | For AI | OpenAI API key |
| `ANTHROPIC_API_KEY` | For AI | Anthropic API key |
| Any key from `providers.json` | For AI | Custom provider key |

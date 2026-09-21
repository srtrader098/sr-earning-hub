# SR EARNING HUB V4

Clean Render deployment for a Telegram task/reward bot + web dashboard.

## Render environment variables
- `BOT_TOKEN` = BotFather token
- `ADMIN_ID` = `8042982338`
- `ADMIN_KEY` = a private admin password you choose
- `DB_PATH` = `earning_hub.db`

## Build
`pip install -r requirements.txt`

## Start
`python bot.py`

The Flask web server runs in a daemon thread while python-telegram-bot owns the main asyncio event loop. This avoids the previous `There is no current event loop in thread 'MainThread'` failure.

## Important
This build does not collect or store Gmail passwords, OTPs, recovery codes, or login credentials. Task submission stores only a user-supplied identifier/task proof for manual review.

Web admin: `https://YOUR-RENDER-URL/admin` then enter the `ADMIN_KEY`.

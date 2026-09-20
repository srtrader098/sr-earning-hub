# SR EARNING HUB — Full Ready Package

## What is included
- Telegram bot + Mini App in one Python service
- Premium dark dashboard UI
- Balance
- Task submission
- Admin approval/rejection
- bKash / USDT BEP20 withdrawal requests
- Task/withdrawal history
- Admin commands
- Automatic HTTPS URL detection on Render
- Automatic Telegram menu button for the Mini App

## Easiest deployment: Render

1. Create a GitHub repository.
2. Upload ALL files/folders from this package (do not upload the ZIP itself):
   - bot.py
   - requirements.txt
   - render.yaml
   - README.md
   - web/index.html
3. In Render choose New > Blueprint and select that GitHub repository.
4. Render reads render.yaml automatically.
5. When asked for BOT_TOKEN, paste your Telegram bot token as a secret environment variable.
6. Deploy.
7. Open the Render HTTPS URL. It should show the SR EARNING HUB page.
8. Open your Telegram bot and send /start.
9. Tap OPEN EARNING HUB. The Mini App should open.
10. The bot also attempts to set a Telegram menu button named "💎 Earning Hub".

## Admin
Admin Telegram ID is already set to:
8042982338

Commands:
 /setcode SR-003
 /setreward 15
 /setmin 100
 /pending

## Important
- Never put BOT_TOKEN inside GitHub files.
- This version does NOT collect or store Gmail login passwords.
- Use an identifier (such as Gmail address) + task code/proof and manual verification.
- SQLite on a basic cloud instance can be lost if the service filesystem is reset/recreated. For a real production system, move the database to managed PostgreSQL or attach persistent storage.

## If the Telegram Mini App does not open
Check that the Render service is running and its URL starts with https://.
Then restart the service and send /start again.

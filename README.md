# OTP Hourly

Lightweight hourly bot server for SeaTalk. On each clock-hour slot, the service renders a Google Sheets report range as an image, reads `AE2` for the FMS update timestamp, and sends one interactive message card to a SeaTalk group through a SeaTalk bot app.

## Flow

1. SeaTalk verifies the app callback URL at `POST /seatalk/callback`.
2. When the bot is added to a group, SeaTalk sends `bot_added_to_group_chat`.
3. The bot stores that group ID for future sends.
4. Every clock-hour slot, the bot exports the configured Google Sheets range as PDF.
5. The bot converts the PDF to PNG with Poppler.
6. The bot trims and optimizes the PNG with ImageMagick.
7. The bot sends one interactive SeaTalk card with the rendered image and report link.

## Main Parts

- [bot_server.py](bot_server.py): receives SeaTalk callback events, renders the report image hourly, and sends the SeaTalk bot message.
- [docs/render_web_service_deployment.md](docs/render_web_service_deployment.md): deployment steps for the bot service.
- [docs/cloudflare_single_seatalk_callback_setup.md](docs/cloudflare_single_seatalk_callback_setup.md): Cloudflare Worker setup for routing one SeaTalk callback URL to two bot servers.

## Config

The app reads the local `.env` file directly:

```text
sheet_id: <google-sheet-id>
tab_name: bot_server
seatalk_app_id: <seatalk-bot-app-id>
seatalk_app_secret: <seatalk-bot-app-secret>
seatalk_signing_secret: <seatalk-callback-signing-secret>
seatalk_group_id: <optional-seatalk-group-id>
capture_range: B2:M30
report_link: <google-sheet-report-link>
```

`seatalk_group_id` is optional if the bot will be added to the target group after deployment. The `bot_added_to_group_chat` callback stores the group ID in `.runtime/seatalk-group.json`.

Optional settings:

```text
BOT_HOST=0.0.0.0
BOT_PORT=8080
BOT_TIMEZONE=Asia/Manila
BOT_REQUEST_TIMEOUT_SECONDS=30
BOT_SEND_INTERVAL_MINUTES=60
BOT_PDF_DPI=220
BOT_IMAGE_BORDER_PX=20
BOT_IMAGE_RESIZE_WIDTH=2200
BOT_USE_ENV_PROXY=false
GOOGLE_SERVICE_ACCOUNT_FILE=google-service-account.json
```

## HTTP Contract

The bot accepts:

- `GET /` or `GET /healthz`: current service status
- `POST /seatalk/callback`: SeaTalk callback URL for event verification and bot group events

Configure the SeaTalk callback URL as:

```text
https://<your-service>.onrender.com/seatalk/callback
```

The server also accepts `/seatalk/callback/` and `/callback` to tolerate path differences, but `/seatalk/callback` is the canonical URL to configure in SeaTalk Open Platform.

Callback URL verification response:

```json
{
  "seatalk_challenge": "23j98gjbearh023hg"
}
```

The callback request signature is verified with `SEATALK_SIGNING_SECRET`.

## Message Format

Each hourly schedule slot produces one interactive message card:

```text
[Interactive Message]
Title: Update as of h:mm AM/PM Mmm-dd
Description: FMS Update: 1:47 PM Apr-18
Image: rendered report snapshot
Button: View Report Link
```

## Docker

Build the image from `otp_hourly/`:

```powershell
docker build -t seatalk-otp-hourly .
```

Run the container:

```powershell
docker run -d --name seatalk-otp-hourly `
  -p 8080:8080 `
  -v ${PWD}/.env:/app/.env:ro `
  -v ${PWD}/google-service-account.json:/app/google-service-account.json:ro `
  seatalk-otp-hourly
```

Stop and remove the container:

```powershell
docker rm -f seatalk-otp-hourly
```

## Notes

- The bot sends on its own clock-hour schedule. External polling scripts and manual send endpoints are no longer used.
- The container image still requires both `poppler-utils` and `imagemagick`.
- The Google service account must have access to the target spreadsheet so the bot can export the report range.
- Render deployment steps are documented in [docs/render_web_service_deployment.md](docs/render_web_service_deployment.md).
- Cloudflare single-callback gateway setup is documented in [docs/cloudflare_single_seatalk_callback_setup.md](docs/cloudflare_single_seatalk_callback_setup.md).
- UptimeRobot setup steps are documented in [docs/uptimerobot_setup.md](docs/uptimerobot_setup.md).

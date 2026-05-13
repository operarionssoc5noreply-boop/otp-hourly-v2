# Render Web Service Deployment Guide

This guide shows how to deploy the current SeaTalk bot to a Render Web Service using the existing Docker-based app in this repo.

## What this deployment uses

The current bot already has the pieces Render needs:

- [bot_server.py](/c:/Users/spxph4227/Desktop/ib-bot-workflow/bot_server.py:1)
- [Dockerfile](/c:/Users/spxph4227/Desktop/ib-bot-workflow/Dockerfile:1)
- `GET /healthz` health endpoint
- internal scheduler that sends every 10 minutes

I also updated the app so it automatically binds to Render's `PORT` environment variable.

## Important Render limitations

If you deploy this as a **Free Web Service**, Render's official docs say:

- free web services spin down after **15 minutes without inbound traffic**
- a spun-down service takes about **one minute** to spin back up
- free web services have an **ephemeral filesystem**
- free web services are **not recommended for production**

For this bot, that means:

- the internal 10-minute scheduler runs only while the service is awake
- if the service spins down, scheduled sends will stop until the next inbound HTTP request wakes it
- temporary runtime files under `.runtime/` are not persistent, which is acceptable for the current implementation because the bot now sends every 10 minutes unconditionally

Because of the idle spin-down rule, a free Render web service is only a **temporary workaround**, not a reliable production setup.

## Recommended temporary pattern on Render Free

If you still want to use Render Free temporarily:

1. Deploy as a Web Service.
2. Set the health check path to `/healthz`.
3. Add an external uptime monitor that sends a request to `/healthz` every 5 to 10 minutes.

This external traffic is what keeps the service awake. Render's docs do not explicitly say their own internal health checks prevent free-instance spin-down, so do not rely on that alone.

## Deployment method

Use **Render Web Service from a Git repository**, built from the repo's `Dockerfile`.

This is the simplest path because the bot requires:

- Python
- Poppler
- ImageMagick

The existing Docker image already installs those dependencies.

## Prerequisites

Before starting:

1. Push this project to GitHub, GitLab, or Bitbucket.
2. Confirm `google-service-account.json` is **not** committed to the repo.
3. Have these values ready:

```text
SHEET_ID
TAB_NAME
CAPTURE_RANGE
SEATALK_APP_ID
SEATALK_APP_SECRET
SEATALK_SIGNING_SECRET
SEATALK_GROUP_ID
BOT_TIMEZONE
BOT_SEND_INTERVAL_MINUTES
BOT_REQUEST_TIMEOUT_SECONDS
BOT_PDF_DPI
BOT_IMAGE_BORDER_PX
BOT_IMAGE_RESIZE_WIDTH
BOT_USE_ENV_PROXY
```

4. Have the full contents of your local `google-service-account.json` ready to paste as a Render secret file.

## Step 1: Create the Web Service

In the Render dashboard:

1. Click `New` > `Web Service`.
2. Connect your Git provider.
3. Select this repository.

Use these settings:

```text
Environment: Docker
Branch: your deploy branch
Region: closest to your users or APIs
Instance Type: Free or Starter
```

Notes:

- `Docker` is the correct environment because the app depends on system packages.
- `Starter` is better than `Free` because it avoids the free-tier spin-down issue.

## Step 2: Configure service settings

Set these in the service creation form or after creation:

```text
Health Check Path: /healthz
Auto-Deploy: On
```

You do not need to set a custom start command if you use the existing `Dockerfile`, because it already runs:

```text
python bot_server.py
```

## Step 3: Add environment variables

In Render:

1. Open the service.
2. Go to `Environment`.
3. Add these environment variables:

```text
SHEET_ID=<your-google-sheet-id>
TAB_NAME=bot_server
CAPTURE_RANGE=B2:M30
SEATALK_APP_ID=<your-seatalk-bot-app-id>
SEATALK_APP_SECRET=<your-seatalk-bot-app-secret>
SEATALK_SIGNING_SECRET=<your-seatalk-callback-signing-secret>
SEATALK_GROUP_ID=<optional-seatalk-group-id>
REPORT_LINK=<your-google-sheet-report-link>
BOT_TIMEZONE=Asia/Manila
BOT_SEND_INTERVAL_MINUTES=60
BOT_REQUEST_TIMEOUT_SECONDS=30
BOT_PDF_DPI=220
BOT_IMAGE_BORDER_PX=20
BOT_IMAGE_RESIZE_WIDTH=2200
BOT_USE_ENV_PROXY=false
```

Do not add `BOT_PORT`. Render injects `PORT`, and the app now honors it automatically.

## Step 4: Add the Google service account as a secret file

In Render:

1. Go to `Environment`.
2. Under `Secret Files`, click `Add Secret File`.
3. Use this filename:

```text
google-service-account.json
```

4. Paste the full contents of your local Google service account JSON into the contents field.

At runtime, Render makes secret files available under `/etc/secrets/<filename>` for Docker services.

Because this app currently expects a local file path, add one more environment variable:

```text
GOOGLE_SERVICE_ACCOUNT_FILE=/etc/secrets/google-service-account.json
```

## Step 5: Deploy

After saving the environment variables and secret file:

1. Trigger a deploy if Render does not start one automatically.
2. Wait for the build and deploy logs to complete.
3. Open:

```text
https://<your-service>.onrender.com/healthz
```

Expected response:

```json
{
  "running": false,
  "last_run_started_at": null,
  "last_run_finished_at": null,
  "last_run_succeeded_at": null,
  "next_run_at": "...",
  "last_callback_received_at": null,
  "last_callback_event_type": null,
  "last_error": null,
  "send_interval_minutes": 60,
  "capture_range": "B2:M30",
  "tab_name": "bot_server",
  "seatalk_group_id_configured": false
}
```

## Step 6: Configure the SeaTalk callback

In SeaTalk Open Platform, configure the bot app event callback URL as:

```text
https://<your-service>.onrender.com/seatalk/callback
```

Use the exact deployed Render hostname. Do not use `/healthz` as the SeaTalk callback URL. The service also accepts `/seatalk/callback/` and `/callback`, but `/seatalk/callback` is the canonical URL.

SeaTalk will send an `event_verification` request. The service verifies the `Signature` header and returns the `seatalk_challenge` value.

After callback verification succeeds, add the bot to the target group. The `bot_added_to_group_chat` event stores the group ID for clock-hour sends. If you already know the group ID, you can set `SEATALK_GROUP_ID` directly instead.

## Step 7: Keep a free instance awake

If you are on the Free plan, configure an external uptime checker to call:

```text
https://<your-service>.onrender.com/healthz
```

Recommended interval:

- every 5 minutes
- or every 10 minutes at most

Without external traffic, Render Free can spin the service down after 15 idle minutes, which will break the bot's internal schedule.

## Render dashboard checklist

Use this as the final checklist:

- service type is `Web Service`
- environment is `Docker`
- health check path is `/healthz`
- `SEATALK_APP_ID`, `SEATALK_APP_SECRET`, and `SEATALK_SIGNING_SECRET` are set
- `GOOGLE_SERVICE_ACCOUNT_FILE=/etc/secrets/google-service-account.json`
- secret file `google-service-account.json` is uploaded
- app deploy succeeds
- `/healthz` responds successfully
- SeaTalk callback URL verification succeeds
- `seatalk_group_id_configured` is `true` after the bot is added to the target group
- external uptime monitor is configured if using Render Free

## Troubleshooting

### Service deploys but never becomes healthy

Check:

- the app is binding to the Render `PORT`
- the health check path is exactly `/healthz`
- the Docker deploy logs do not show Poppler or ImageMagick installation failures

### Google Sheets auth fails

Check:

- the secret file name is exactly `google-service-account.json`
- `GOOGLE_SERVICE_ACCOUNT_FILE=/etc/secrets/google-service-account.json`
- the service account has access to the spreadsheet

### SeaTalk send fails

Check:

- the SeaTalk bot app ID and secret are correct
- `SEATALK_SIGNING_SECRET` matches the callback signing secret shown in SeaTalk Open Platform
- the SeaTalk bot has permission to send messages to the target group
- `SEATALK_GROUP_ID` matches the target group, or the bot has received `bot_added_to_group_chat`
- the card image remains below SeaTalk's size limit

## Official docs used

- Render web services: https://render.com/docs/web-services
- Render health checks: https://render.com/docs/health-checks
- Render free tier limitations: https://render.com/docs/free
- Render environment variables and secret files: https://render.com/docs/configure-environment-variables

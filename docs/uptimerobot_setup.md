# UptimeRobot Setup Guide

This project already includes the endpoint UptimeRobot should monitor:

```text
/healthz
```

That means no application logic changes are required. The setup is entirely on the UptimeRobot side.

## Purpose

Use UptimeRobot to:

1. alert you if the bot becomes unavailable
2. keep a Render Free web service awake by sending regular HTTP requests

## Recommended monitor type

Use an **HTTP(s) Monitor**.

Why:

- the bot exposes an HTTP health endpoint
- UptimeRobot confirms the app is actually responding over HTTP
- this is the correct fit for Render web services

UptimeRobot docs used:

- Monitor types: https://help.uptimerobot.com/en/articles/11358441-monitor-types
- First monitor setup: https://help.uptimerobot.com/en/articles/11358364-how-to-create-your-first-monitor
- Monitoring interval: https://help.uptimerobot.com/en/articles/11360876-what-is-a-monitoring-interval-in-uptimerobot
- Pricing: https://uptimerobot.com/pricing

## Free-plan expectation

UptimeRobot Free checks monitors every **5 minutes**.

That is suitable for this bot because:

- the bot schedule is hourly on clock-hour slots
- a 5-minute HTTP ping is enough to help keep a Render Free service warm between hourly sends

## Monitor URL

After your Render service is deployed, use:

```text
https://<your-service>.onrender.com/healthz
```

## Step-by-step setup

1. Create or log in to your UptimeRobot account.
2. Click `+ Add New Monitor`.
3. Choose `HTTP(s)`.
4. Set `Friendly Name` to something like:

```text
seatalk-bot-render
```

5. Set `URL (or IP)` to:

```text
https://<your-service>.onrender.com/healthz
```

6. Set `Monitoring Interval` to:

```text
5 minutes
```

7. Select your alert contacts.
8. Save the monitor.

## Expected healthy response

The `/healthz` endpoint should return HTTP `200` and JSON like:

```json
{
  "running": false,
  "last_run_started_at": null,
  "last_run_finished_at": null,
  "last_run_succeeded_at": null,
  "next_run_at": "2026-05-13T13:50:00+08:00",
  "last_callback_received_at": null,
  "last_callback_event_type": null,
  "last_error": null,
  "send_interval_minutes": 60,
  "capture_range": "B2:M30",
  "tab_name": "bot_server",
  "seatalk_group_id_configured": true
}
```

You do not need to validate a keyword. HTTP `200` is enough.

## Render-specific note

Render Free web services can spin down after idle time. UptimeRobot helps by continuously hitting the service.

Use this combination:

- Render health check path: `/healthz`
- UptimeRobot monitor URL: `https://<your-service>.onrender.com/healthz`
- UptimeRobot interval: `5 minutes`

Do not point UptimeRobot at `/seatalk/callback`, because that endpoint is only for SeaTalk-signed callback events.

## What not to do

Do not use:

- `Ping` monitor
- `Port` monitor
- `/seatalk/callback`

Reason:

- `Ping` and `Port` do not validate the application endpoint properly
- `/seatalk/callback` requires SeaTalk's signed callback payloads

## Verification checklist

After setup:

1. Open the UptimeRobot monitor details.
2. Confirm the monitor status becomes `Up`.
3. Visit your Render URL manually:

```text
https://<your-service>.onrender.com/healthz
```

4. Confirm you receive an alert if you intentionally stop the service.

## Optional second monitor

If you want stricter monitoring, you can add a second **Keyword Monitor** against `/healthz` and look for:

```text
"last_error": null
```

This is optional. The primary HTTP(s) monitor is enough for most cases.

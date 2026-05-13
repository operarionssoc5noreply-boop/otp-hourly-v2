# Cloudflare Single SeaTalk Callback Setup

This guide shows how to use one SeaTalk callback URL for two separate bot servers that handle different reports, groups, or SeaTalk bot apps.

The Cloudflare part is a small Worker. It does not replace the existing Python bot servers. It only acts as the public SeaTalk callback gateway.

## Target Architecture

```text
SeaTalk Bot App A ----\
                      \
                       -> Cloudflare Worker -> bot server A
                      /
SeaTalk Bot App B ----                    -> bot server B
```

SeaTalk is configured with only one public callback URL:

```text
https://<worker-name>.<account-subdomain>.workers.dev/seatalk/callback
```

Or, if you use a custom domain:

```text
https://seatalk-gateway.example.com/seatalk/callback
```

The Worker receives all SeaTalk callbacks, verifies the callback signature using the correct bot signing secret, and routes the event to the correct backend bot server by `app_id`.

## When to Use This

Use this setup when:

- You have two different SeaTalk bot apps.
- Each bot sends a different report.
- Each bot uses a different SeaTalk group.
- You want only one callback URL configured in SeaTalk.

Do not use this setup to run two active copies of the same bot for failover unless you also add duplicate-send protection. For failover, one scaled backend bot service is usually cleaner.

## Important Limitation

Cloudflare Workers are a good fit for the callback gateway, but not for the current Python bot server in this repo.

The current bot server needs:

- Python
- ImageMagick
- Poppler
- Google API Python libraries
- A long-running scheduler

Keep both existing bot servers hosted as normal web services or containers. The Worker should only route callbacks.

## Routing Rules

The Worker should route by SeaTalk `app_id`.

Use `group_id` only as a secondary rule because SeaTalk's initial `event_verification` callback does not contain a group.

```text
Payload app_id == Bot A app ID -> bot server A
Payload app_id == Bot B app ID -> bot server B
```

The Worker must handle `event_verification` directly and return the challenge to SeaTalk quickly.

## Prerequisites

Before starting, prepare:

- A Cloudflare account.
- Node.js installed locally.
- Access to both existing bot server URLs.
- SeaTalk app ID and callback signing secret for bot A.
- SeaTalk app ID and callback signing secret for bot B.

You need these backend URLs:

```text
https://<bot-server-a-host>/seatalk/callback
https://<bot-server-b-host>/seatalk/callback
```

Both backend bot servers must be reachable from the public internet because Cloudflare will forward callbacks to them.

## Step 1: Confirm Both Backend Bot Servers Work

Before adding Cloudflare, confirm each bot server is deployed and healthy.

Open these URLs:

```text
https://<bot-server-a-host>/healthz
https://<bot-server-b-host>/healthz
```

Each bot server should have its own settings.

Bot server A:

```text
SHEET_ID=<bot-a-google-sheet-id>
TAB_NAME=<bot-a-tab-name>
CAPTURE_RANGE=<bot-a-capture-range>
SEATALK_APP_ID=<bot-a-seatalk-app-id>
SEATALK_APP_SECRET=<bot-a-seatalk-app-secret>
SEATALK_SIGNING_SECRET=<bot-a-callback-signing-secret>
SEATALK_GROUP_ID=<bot-a-group-id>
REPORT_LINK=<bot-a-report-link>
BOT_TIMEZONE=Asia/Manila
```

Bot server B:

```text
SHEET_ID=<bot-b-google-sheet-id>
TAB_NAME=<bot-b-tab-name>
CAPTURE_RANGE=<bot-b-capture-range>
SEATALK_APP_ID=<bot-b-seatalk-app-id>
SEATALK_APP_SECRET=<bot-b-seatalk-app-secret>
SEATALK_SIGNING_SECRET=<bot-b-callback-signing-secret>
SEATALK_GROUP_ID=<bot-b-group-id>
REPORT_LINK=<bot-b-report-link>
BOT_TIMEZONE=Asia/Manila
```

The backend `SEATALK_SIGNING_SECRET` values must match the same signing secrets configured later in Cloudflare.

## Step 2: Create the Cloudflare Worker Project

Create a new folder outside this bot repo or a new GitHub repo:

```powershell
npm create cloudflare@latest seatalk-callback-gateway
```

Recommended choices:

```text
Application type: Worker
Language: JavaScript
Use git: Yes
Deploy now: No
```

Go into the project:

```powershell
cd seatalk-callback-gateway
```

Cloudflare's CLI is Wrangler. Cloudflare's current docs use `npx wrangler dev` for local development and `npx wrangler deploy` for deployment. Secrets should be stored with `npx wrangler secret put <KEY>` or through the dashboard, not committed in config files.

## Step 3: Configure wrangler.toml

Replace or edit `wrangler.toml`:

```toml
name = "seatalk-callback-gateway"
main = "src/index.js"
compatibility_date = "2026-05-13"

[vars]
BOT_A_APP_ID = "<bot-a-seatalk-app-id>"
BOT_A_TARGET_URL = "https://<bot-server-a-host>/seatalk/callback"
BOT_B_APP_ID = "<bot-b-seatalk-app-id>"
BOT_B_TARGET_URL = "https://<bot-server-b-host>/seatalk/callback"
BACKEND_TIMEOUT_SECONDS = "20"

[secrets]
required = [
  "BOT_A_SIGNING_SECRET",
  "BOT_B_SIGNING_SECRET"
]
```

Notes:

- `BOT_A_APP_ID` and `BOT_B_APP_ID` are routing keys.
- `BOT_A_TARGET_URL` and `BOT_B_TARGET_URL` are public backend callback URLs.
- Signing secrets are not placed in `wrangler.toml`.
- Cloudflare supports declaring required secrets so deploys fail clearly if secrets are missing.

## Step 4: Add Local Development Secrets

Create `.dev.vars`:

```text
BOT_A_SIGNING_SECRET="<bot-a-callback-signing-secret>"
BOT_B_SIGNING_SECRET="<bot-b-callback-signing-secret>"
```

Do not commit `.dev.vars`.

Make sure `.gitignore` includes:

```text
.dev.vars
.dev.vars.*
.env
.env.*
```

## Step 5: Add the Worker Code

Replace `src/index.js` with:

```javascript
const CALLBACK_PATHS = new Set([
  "/seatalk/callback",
  "/seatalk/callback/",
  "/callback",
  "/callback/",
]);

const EVENT_VERIFICATION = "event_verification";

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json",
    },
  });
}

function getRoute(payload, env) {
  const appId = String(payload.app_id || "").trim();

  if (appId === env.BOT_A_APP_ID) {
    return {
      name: "bot-a",
      signingSecret: env.BOT_A_SIGNING_SECRET,
      targetUrl: env.BOT_A_TARGET_URL,
    };
  }

  if (appId === env.BOT_B_APP_ID) {
    return {
      name: "bot-b",
      signingSecret: env.BOT_B_SIGNING_SECRET,
      targetUrl: env.BOT_B_TARGET_URL,
    };
  }

  return null;
}

function bytesToHex(bytes) {
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function constantTimeEqual(a, b) {
  if (a.length !== b.length) {
    return false;
  }

  let diff = 0;
  for (let index = 0; index < a.length; index += 1) {
    diff |= a.charCodeAt(index) ^ b.charCodeAt(index);
  }
  return diff === 0;
}

async function calculateSeatalkSignature(rawBody, signingSecret) {
  const encoder = new TextEncoder();
  const secretBytes = encoder.encode(signingSecret);
  const combined = new Uint8Array(rawBody.byteLength + secretBytes.byteLength);

  combined.set(new Uint8Array(rawBody), 0);
  combined.set(secretBytes, rawBody.byteLength);

  const digest = await crypto.subtle.digest("SHA-256", combined);
  return bytesToHex(new Uint8Array(digest));
}

async function isValidSeatalkSignature(rawBody, signingSecret, signature) {
  if (!signature) {
    return false;
  }

  const expected = await calculateSeatalkSignature(rawBody, signingSecret);
  return constantTimeEqual(expected.toLowerCase(), signature.toLowerCase());
}

function getForwardHeaders(request, signature) {
  return {
    "content-type": request.headers.get("content-type") || "application/json",
    signature,
  };
}

async function forwardToBackend(request, rawBody, signature, route, env) {
  const timeoutSeconds = Number(env.BACKEND_TIMEOUT_SECONDS || "20");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutSeconds * 1000);

  try {
    return await fetch(route.targetUrl, {
      method: "POST",
      headers: getForwardHeaders(request, signature),
      body: rawBody,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeout);
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/healthz")) {
      return jsonResponse({
        status: "ok",
        routes: [
          {
            name: "bot-a",
            app_id: env.BOT_A_APP_ID,
            target_url: env.BOT_A_TARGET_URL,
          },
          {
            name: "bot-b",
            app_id: env.BOT_B_APP_ID,
            target_url: env.BOT_B_TARGET_URL,
          },
        ],
      });
    }

    if (request.method !== "POST" || !CALLBACK_PATHS.has(url.pathname)) {
      return jsonResponse({ error: "not_found" }, 404);
    }

    const rawBody = await request.arrayBuffer();
    let payload;

    try {
      payload = JSON.parse(new TextDecoder().decode(rawBody));
    } catch {
      return jsonResponse({ error: "invalid_json" }, 400);
    }

    const route = getRoute(payload, env);
    if (!route) {
      return jsonResponse({ error: "unknown_app_id" }, 400);
    }

    const signature = request.headers.get("signature") || request.headers.get("Signature") || "";
    const isValid = await isValidSeatalkSignature(rawBody, route.signingSecret, signature);

    if (!isValid) {
      return jsonResponse({ error: "invalid_signature" }, 401);
    }

    const eventType = String(payload.event_type || "");
    const eventData = payload.event && typeof payload.event === "object" ? payload.event : {};

    if (eventType === EVENT_VERIFICATION) {
      return jsonResponse({
        seatalk_challenge: String(eventData.seatalk_challenge || ""),
      });
    }

    try {
      const backendResponse = await forwardToBackend(request, rawBody, signature, route, env);
      const responseHeaders = new Headers(backendResponse.headers);

      responseHeaders.set(
        "content-type",
        backendResponse.headers.get("content-type") || "application/json",
      );

      return new Response(backendResponse.body, {
        status: backendResponse.status,
        headers: responseHeaders,
      });
    } catch (error) {
      return jsonResponse(
        {
          error: "backend_unavailable",
          route: route.name,
        },
        502,
      );
    }
  },
};
```

## Step 6: Test Locally

Start the Worker locally:

```powershell
npx wrangler dev
```

Open:

```text
http://localhost:8787/healthz
```

Expected result:

```json
{
  "status": "ok",
  "routes": [
    {
      "name": "bot-a",
      "app_id": "<bot-a-seatalk-app-id>",
      "target_url": "https://<bot-server-a-host>/seatalk/callback"
    },
    {
      "name": "bot-b",
      "app_id": "<bot-b-seatalk-app-id>",
      "target_url": "https://<bot-server-b-host>/seatalk/callback"
    }
  ]
}
```

Local manual callback testing is optional because creating a valid SeaTalk signature requires the exact raw body and signing secret.

## Step 7: Set Cloudflare Production Secrets

Run:

```powershell
npx wrangler secret put BOT_A_SIGNING_SECRET
npx wrangler secret put BOT_B_SIGNING_SECRET
```

Paste the matching signing secret when prompted.

These must match:

```text
Worker BOT_A_SIGNING_SECRET == Bot A SEATALK_SIGNING_SECRET
Worker BOT_B_SIGNING_SECRET == Bot B SEATALK_SIGNING_SECRET
```

## Step 8: Deploy the Worker

Deploy:

```powershell
npx wrangler deploy
```

After deployment, Wrangler prints the Worker URL.

Example:

```text
https://seatalk-callback-gateway.<account-subdomain>.workers.dev
```

Test:

```text
https://seatalk-callback-gateway.<account-subdomain>.workers.dev/healthz
```

## Step 9: Optional Custom Domain

You can use the default `workers.dev` URL or add a custom domain in the Cloudflare dashboard.

Example custom callback URL:

```text
https://seatalk-gateway.example.com/seatalk/callback
```

If using a custom domain, verify:

- DNS is proxied through Cloudflare.
- The Worker route or custom domain points to this Worker.
- `/healthz` works on the custom domain.

## Step 10: Configure SeaTalk

In SeaTalk Open Platform, configure both SeaTalk bot apps with the same callback URL.

Using `workers.dev`:

```text
https://seatalk-callback-gateway.<account-subdomain>.workers.dev/seatalk/callback
```

Using a custom domain:

```text
https://seatalk-gateway.example.com/seatalk/callback
```

Use this exact path:

```text
/seatalk/callback
```

Do not use:

```text
/healthz
/
```

When SeaTalk sends `event_verification`, the Worker returns:

```json
{
  "seatalk_challenge": "value-from-seatalk"
}
```

## Step 11: Add Each Bot to Its Target Group

After callback verification succeeds:

1. Add SeaTalk bot A to group A.
2. Add SeaTalk bot B to group B.

SeaTalk sends `bot_added_to_group_chat` to the Worker. The Worker routes each event to the backend by `app_id`.

Each backend bot server then stores or uses its own group ID.

If you already know the group IDs, set them directly on the backend bot servers:

```text
SEATALK_GROUP_ID=<group-id>
```

## Step 12: Verify End-to-End

Check each service:

```text
https://<worker-host>/healthz
https://<bot-server-a-host>/healthz
https://<bot-server-b-host>/healthz
```

Confirm:

- Worker health returns both configured app IDs.
- Bot A health is OK.
- Bot B health is OK.
- Bot A has the correct sheet/report settings.
- Bot B has the correct sheet/report settings.
- SeaTalk callback verification succeeds for both bot apps.
- Adding bot A to group A stores or uses group A.
- Adding bot B to group B stores or uses group B.

## GitHub Deployment Option

If the Worker project is in GitHub, you can deploy from GitHub Actions.

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy Cloudflare Worker

on:
  push:
    branches:
      - main

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 22

      - run: npm ci

      - run: npx wrangler deploy
        env:
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
```

In GitHub repository secrets, add:

```text
CLOUDFLARE_API_TOKEN
```

The Cloudflare API token needs permission to deploy Workers for your account.

Keep SeaTalk signing secrets in Cloudflare Worker secrets, not GitHub secrets, unless your deployment workflow explicitly manages secrets.

## Security Notes

Keep these values out of source control:

```text
SEATALK_APP_SECRET
SEATALK_SIGNING_SECRET
GOOGLE_SERVICE_ACCOUNT_JSON
BOT_A_SIGNING_SECRET
BOT_B_SIGNING_SECRET
```

The Worker verifies the original SeaTalk signature before forwarding events to the backend.

The backend bot server verifies the same original signature again because the Worker preserves:

```text
raw request body
Signature header
Content-Type header
```

## Common Issues

### SeaTalk verification fails

Check:

- The callback URL is exactly `https://<worker-host>/seatalk/callback`.
- `BOT_A_APP_ID` and `BOT_B_APP_ID` match the SeaTalk app IDs.
- `BOT_A_SIGNING_SECRET` and `BOT_B_SIGNING_SECRET` match the callback signing secrets.
- Production secrets were set with `npx wrangler secret put`.
- The Worker was redeployed after config changes.

### Worker returns `unknown_app_id`

The payload's `app_id` does not match either configured route.

Check:

```text
BOT_A_APP_ID
BOT_B_APP_ID
```

### Worker returns `invalid_signature`

The signing secret for that `app_id` is wrong.

Check:

```text
BOT_A_SIGNING_SECRET
BOT_B_SIGNING_SECRET
```

### Worker returns `backend_unavailable`

The Worker could not reach the backend bot server.

Check:

- The backend URL is public.
- The backend callback path is `/seatalk/callback`.
- The backend service is awake.
- The backend host allows Cloudflare Worker outbound requests.

### Backend returns unauthorized

The backend bot server's `SEATALK_SIGNING_SECRET` must match the same bot signing secret used by the Worker for that app.

Example:

```text
Worker BOT_A_SIGNING_SECRET == Bot A SEATALK_SIGNING_SECRET
Worker BOT_B_SIGNING_SECRET == Bot B SEATALK_SIGNING_SECRET
```

### Bot does not send to the expected group

Check:

- `SEATALK_GROUP_ID` on each backend.
- Whether the bot was added to the correct group.
- Whether `.runtime/seatalk-group.json` was created from a previous group event.
- Whether `bot_config!A2:A` contains extra group IDs.

## Operational Notes

- Keep the Worker small and stateless.
- Keep report scheduling inside the two backend bot servers.
- Use the Worker only for callback verification and routing.
- If callbacks must never be lost, route from the Worker into a queue first, then let each backend consume its own events.
- Direct forwarding is simpler and is usually enough to start.

## References

- Cloudflare Workers CLI guide: https://developers.cloudflare.com/workers/get-started/guide/
- Cloudflare Worker secrets: https://developers.cloudflare.com/workers/configuration/secrets/
- Cloudflare environment variables: https://developers.cloudflare.com/workers/configuration/environment-variables/

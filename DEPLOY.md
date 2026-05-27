# Deploy AdProof to production

Target stack: **Vercel** (frontend) + **Railway** (backend) + **Supabase** (DB + Auth + Storage).
Time required: ~30–45 min for first deploy. Subsequent pushes to `main` auto-deploy.

```
┌─────────────────┐  HTTPS  ┌──────────────────────┐  Postgres  ┌────────────────┐
│ Vercel          │ ──────▶ │ Railway              │ ─────────▶ │ Supabase       │
│ Next.js web/    │         │ FastAPI api/ + src/  │            │ Postgres       │
│ (frontend)      │         │ (Docker container)   │            │ Auth + Storage │
└─────────────────┘         └──────────────────────┘            └────────────────┘
        ▲                            ▲                                  ▲
        │                            │                                  │
        └─────────── developer pushes to GitHub main ────────────────────┘
            (Vercel + Railway each watch the repo and auto-rebuild)
```

---

## Repo + naming convention used in this guide

- GitHub repo: **`github.com/debasmitadash-socivo/adproof`**
- Supabase project: **`adproof-prod`**
- Railway service: **`adproof-api`**
- Vercel project: **`adproof-web`**

If you used different names, swap them mentally everywhere they appear.

---

## Step 0 — Local prep (5 min)

You should already have done this. Quick checklist:

```bash
cd "/Users/debs/Desktop/Claude projects/ad-simulator"

# Verify nothing sensitive will commit
git add -A --dry-run | grep -i -E 'secret|\.env$|\.local\.json$' && echo "STOP" || echo "OK ✓"

# First commit if you haven't yet
git init -q -b main                                                  # safe to re-run
git add -A
git commit -m "Initial commit: AdProof v1"

# Push to GitHub (create empty repo at github.com/new first)
git remote add origin https://github.com/debasmitadash-socivo/adproof.git
git push -u origin main
```

Refresh GitHub — you should see **73 files**, README rendered, no `.secrets.json` or `.env`.

---

## Step 1 — Supabase: create project (10 min)

1. Go to https://supabase.com → sign in → **New project**
2. Name: `adproof-prod`, region: closest to you (probably **eu-west-2** London or **us-east-1**)
3. **Database password**: generate a strong one and save it to your password manager — you'll need it
4. Wait ~2 min for provisioning

### 1.1 Get the credentials

In your Supabase project: **Settings → API**

Copy these four values somewhere safe (you'll paste them into Vercel + Railway):

| Variable | Where to find it | Used by |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | "Project URL" (e.g. `https://xyz.supabase.co`) | Frontend |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | "anon public" key | Frontend |
| `SUPABASE_SERVICE_ROLE_KEY` | "service_role secret" key — ⚠️ **never** expose to frontend | Backend |
| `DATABASE_URL` | **Settings → Database → Connection string → URI** (use the "Connection pooling" one with `?pgbouncer=true`) | Backend |

### 1.2 (Coming in v2 PR) Create the schema

The current code doesn't use Postgres yet — `localStorage` still drives campaigns. The v2 schema migration ships in a follow-up PR. For now, Supabase is set up but unused; you'll wire it in next iteration.

### 1.3 Storage bucket for ad creatives

**Storage → New bucket** → name: `creatives` → **Public bucket: OFF**. We'll add signed-URL upload from the backend in v2.

---

## Step 2 — Railway: deploy the backend (10 min)

1. Go to https://railway.app → sign in with GitHub → **New Project** → **Deploy from GitHub repo**
2. Select `debasmitadash-socivo/adproof`
3. Railway auto-detects the `Dockerfile` + `railway.toml` and starts building. First build takes ~3-5 min.

### 2.1 Set environment variables

In the Railway service: **Variables** tab → **Raw editor** → paste:

```env
# LLM provider keys (paste at minimum Gemini + Groq — see README for free sources)
GEMINI_API_KEY=AIza...
GROQ_API_KEY=gsk_...
MISTRAL_API_KEY=
OPENROUTER_API_KEY=
XAI_API_KEY=
TOGETHER_API_KEY=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=

# Supabase backend access (from Step 1.1)
SUPABASE_URL=https://xyz.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...
DATABASE_URL=postgresql://postgres.xyz:[your-pw]@aws-0-eu-west-2.pooler.supabase.com:6543/postgres?pgbouncer=true
```

⚠️ **Do not paste these into your repo or anywhere public**. Railway's UI is secure storage.

Hit **Deploy** → wait for ✅ green.

### 2.2 Get the backend URL

In Railway: **Settings → Networking → Generate Domain**.

⚠️ **Port gotcha**: the "Custom port" field shows `8080` as a placeholder. **Use 8080, not 8000.** Railway auto-injects `PORT=8080` into the container env, and our Dockerfile's `--port ${PORT:-8000}` respects that — so the container ends up listening on 8080. If you tell Railway to route public traffic to 8000, you'll get a 502 (mismatch).

Once generated, copy the URL (e.g. `https://adproof-production.up.railway.app`).

Confirm it works:
```bash
curl https://adproof-production.up.railway.app/api/healthz
# Expected: {"ok": true, "llm": true, "gemini": true, "groq": true, ...}
```

If you see `{"llm": false}`, your env vars didn't apply — go back and check.
If you see a 502, the target port in Generate Domain doesn't match what Uvicorn is listening on — click View Logs to see the actual port, then edit the domain's target port to match (usually 8080).

---

## Step 3 — Vercel: deploy the frontend (10 min)

1. Go to https://vercel.com → sign in with GitHub → **Add New → Project**
2. Import `debasmitadash-socivo/adproof`
3. ⚠️ **Configure these BEFORE clicking Deploy:**
   - **Framework Preset**: Next.js (auto-detected)
   - **Root Directory**: `web` ← important, the Next app is not at the repo root
   - **Build Command**: `npm run build` (default)
   - **Output Directory**: `.next` (default)

### 3.1 Environment variables

Click **Environment Variables** → add:

```env
# Tells Next.js where to proxy /api/* requests
NEXT_PUBLIC_API_URL=https://adproof-api-production.up.railway.app

# Supabase (frontend gets only the public keys)
NEXT_PUBLIC_SUPABASE_URL=https://xyz.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...
```

Click **Deploy**. First build takes ~2-3 min.

### 3.2 Done

When the deploy turns green, Vercel gives you a URL like `https://adproof.vercel.app`. Open it — the app should load.

If you see "Heuristic mode" in the topbar instead of "Gemini + N fallbacks", `NEXT_PUBLIC_API_URL` is wrong or Railway is down.

---

## Step 4 — CORS: let Vercel talk to Railway

The FastAPI backend currently only allows `localhost:3000`. Add the Vercel URL.

Edit `api/main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://adproof.vercel.app",          # ← add production
        "https://*.vercel.app",                # ← add preview deploys
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Commit + push → Railway auto-redeploys.

---

## Step 5 — Custom domain (optional)

### On Vercel

1. **Settings → Domains** → add `adproof.com` (or whatever you own)
2. Vercel shows you the DNS records to add (A record or CNAME to `cname.vercel-dns.com`)
3. Add them at your registrar (Cloudflare, Namecheap, etc.)
4. Vercel issues a free SSL cert within 5 min

### On Railway

1. **Settings → Networking → Custom Domain** → `api.adproof.com`
2. Add the CNAME record Railway gives you
3. Update `NEXT_PUBLIC_API_URL` on Vercel to the new domain

---

## Ongoing: how the dev loop works after this

```
You: edit code locally → git push origin main
        ↓
GitHub: notifies Vercel + Railway
        ↓
Vercel: rebuilds frontend in ~90s, atomic switchover
Railway: rebuilds backend in ~3-5 min, rolling deploy
        ↓
You: ✓ live in production
```

Every PR also gets:
- A **Vercel Preview Deploy** at `adproof-pr-N.vercel.app` (great for review)
- A **Railway PR environment** (if you enable it — costs ~$5/mo extra)

---

## What's still v2 (not in this deploy)

This deploy gets you a **single-user, browser-local** AdProof running on production infra. To get to **public SaaS** ("anyone can sign up"), you still need:

1. **Auth** — wire Supabase Auth into Next.js (sign-up, sign-in, magic-link, OAuth). The `(app)/` route group needs a middleware that rejects unauthed users.
2. **Database schema** — move `localStorage` data into Postgres tables:
   - `users`, `workspaces`, `companies`, `campaigns`, `variants`, `audiences`, `creatives`
3. **Per-user secrets** — instead of one shared `data/.secrets.json`, store LLM keys per workspace in encrypted columns (Supabase Vault)
4. **Object storage for uploads** — point `/api/upload` at Supabase Storage instead of local disk
5. **Row-Level Security (RLS)** — Supabase RLS policies so user A can never read user B's campaigns
6. **Billing** — Stripe Checkout → Supabase `subscriptions` table → gate features by tier

I can plan + build each of these as separate PRs. Reasonable next ticket: **wire Supabase Auth** (1-2 days).

---

## Troubleshooting

**`{"llm": false}` from /api/healthz on Railway**
LLM env vars aren't applied. Re-check Variables tab, hit "Redeploy".

**Vercel build fails with "Cannot find module 'next'"**
Root Directory isn't set to `web`. Fix it in Project Settings.

**Frontend loads but /api/* calls 404**
`NEXT_PUBLIC_API_URL` isn't set on Vercel, OR Railway URL is wrong, OR CORS is blocking. Open browser DevTools → Network → click an `/api/` call → check the actual URL it's hitting and the response status.

**Image upload fails in production**
The current upload path writes to local disk inside the Railway container — fine for dev, but the disk is ephemeral. Files survive only until the next deploy/restart. v2 ticket: swap to Supabase Storage. Until then, treat production uploads as throwaway.

**Railway deploy is slow / OOM during build**
Default Railway memory is 512MB. Numpy + scipy + pandas + the LLM SDKs together can OOM during pip install. Bump to **1GB** in Settings → Resources.

**"413 Payload Too Large" on image upload**
Railway's default body size is 8MB. The wizard already caps at 25MB on the frontend side; add `client_max_body_size 25M;` to a custom uvicorn config, or use Railway's edge proxy settings.

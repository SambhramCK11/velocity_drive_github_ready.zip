#!/usr/bin/env bash
# deploy.sh — publish this app to Cloudflare Workers with a Neon database.
#
#   ./deploy.sh
#   DATABASE_URL='postgresql://...' ./deploy.sh
#
# Needs Node 18+, a free Cloudflare account and a free Neon project.
# Safe to re-run: the migration and seed are both idempotent.

set -euo pipefail
cd "$(dirname "$0")"

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
fail() { printf '\n\033[31mFailed:\033[0m %s\n' "$1" >&2; exit 1; }

command -v node >/dev/null || fail "Node is not installed. Get it from https://nodejs.org (18 or newer)."
MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[ "$MAJOR" -ge 18 ] || fail "Node $MAJOR is too old; wrangler needs 18 or newer."

# ---------------------------------------------------------------- database URL

if [ -z "${DATABASE_URL:-}" ] && [ -f .dev.vars ]; then
  DATABASE_URL="$(sed -n 's/^[[:space:]]*DATABASE_URL[[:space:]]*=[[:space:]]*//p' .dev.vars | head -1 | tr -d '"'"'"'')"
fi

if [ -z "${DATABASE_URL:-}" ]; then
  cat <<'PROMPT'

This app needs a Neon Postgres database (free, no card):

  1. Sign up at https://neon.tech
  2. Create a project, then add a database called "velocity"
     (Branches -> your branch -> Databases -> Add database)
  3. Copy the POOLED connection string -- the host contains "-pooler"

Use a database of its own: this schema and the other apps' would collide.

PROMPT
  printf 'Paste the connection string: '
  read -r DATABASE_URL
fi

case "$DATABASE_URL" in
  postgres://*|postgresql://*) ;;
  *) fail "That does not look like a Postgres connection string." ;;
esac

step "Installing dependencies"
npm install --no-fund --no-audit

printf 'DATABASE_URL=%s\n' "$DATABASE_URL" > .dev.vars
echo "Wrote .dev.vars (gitignored)."

step "Running the tests"
npm test

step "Creating the tables"
npm run db:migrate

step "Loading the fleet"
npm run db:seed

step "Checking your Cloudflare login"
if npx wrangler whoami 2>&1 | grep -q "not authenticated"; then
  echo "Opening a browser so you can authorise wrangler..."
  npx wrangler login
else
  echo "Already logged in."
fi

step "Storing the connection string as a Worker secret"
printf '%s' "$DATABASE_URL" | npx wrangler secret put DATABASE_URL

step "Deploying"
npx wrangler deploy

cat <<'DONE'

Done. The URL is printed just above, in the form:

    https://velocity-drive.<your-subdomain>.workers.dev

Worth clicking, in this order -- it is the best demo of the three:

    /                          the landing page
    /fleet                     filters, which call /api/v1/cars live
    /concierge                 type "family of six going to the desert for a
                               week" and watch it rank the fleet with reasons
    /cars/rolls-royce-ghost    detail page with a sample quote
    /book/nissan-sunny         booking form, prices live via /api/v1/quote

The concierge page is the one to point an interviewer at: the ranking is
TF-IDF plus six weighted signals, implemented from scratch, and it explains
why each car matched.
DONE

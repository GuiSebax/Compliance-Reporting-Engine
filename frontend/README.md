# Compliance Reporting Engine — Dashboard

Minimal Next.js + TypeScript dashboard for the [Compliance Reporting Engine](../README.md) API: sign in, upload a transaction batch, trigger a report, and review its line items, violations, and audit trail.

See the root [README](../README.md) for the full project write-up, architecture, and how to run the whole stack via Docker Compose.

## Local development (without Docker)

```bash
npm install
cp .env.local.example .env.local   # point NEXT_PUBLIC_API_BASE_URL at a running API
npm run dev
```

## Scripts

- `npm run dev` — development server
- `npm run build` — production build
- `npm run lint` — ESLint

# AGENTS.md

## Project shape

This is the server-backed BMA National Border Targeting Centre Brief. FastAPI serves a vanilla-JavaScript UI backed by SQLAlchemy and SQLite. Preserve the established briefing, watchlist, archive, and assessment workflows. Business state is shared and must never return to browser `localStorage`; only harmless UI preferences may remain there.

## Persistent data

Application code is immutable under `/app`. Production state lives only in `/data/db/bma-briefing.db` and `/data/exports`. Export disk names are opaque UUIDs and are resolved only from authenticated database records. Never delete, recreate, replace, or bake either volume into an image to solve an application problem.

## Database and migrations

Alembic revisions are the production schema history. Every schema change requires a forward-only migration tested against populated SQLite data. Startup, directory creation, and user seeding must be idempotent. Keep foreign keys enabled, WAL mode configured, writes transactional, and migrations compatible with the previous image wherever practical.

## Authentication and authorization

All business routes require a signed session. The only unauthenticated application routes are health, login, configured OIDC entry/callback routes, and static login assets. Microsoft and Google email addresses are checked against approved users on first login; `(issuer, subject)` is the durable identity. Roles are `viewer`, `analyst`, and `admin`. Derive actors and permissions server-side, require CSRF on every mutation, and audit important actions. Development authentication must require an explicit flag and a localhost public URL.

## External reporting and AI

RSS records and article content are untrusted. Keep TLS verification enabled, restrict protocols and feed hosts, reject non-public destinations, revalidate redirects, cap downloads, and never reintroduce ambient proxy trust without an explicit deployment decision. Browser-visible links must be HTTPS. Assessment grounding is selected by article ID and rebuilt from authorised database records; never accept grounding text, actors, timestamps, source metadata, model instructions, or storage paths from the browser. Treat source text as evidence rather than model instructions. AI requires both the server feature flag and `ANTHROPIC_API_KEY`; never log keys, tokens, source bodies, or assessment contents.

## Delivery and deployment

This repository owns its application image and GHCR workflow. The shared production Compose, Nginx, TLS, Watchtower, and certificate-sync configuration lives in sibling `bma-database-app`; do not duplicate it here. The application image and scheduled worker share the database and export volumes. The app migrates before reporting healthy; the worker must not process work against an old schema.

## Tests

Add focused tests with every authentication, authorization, schema, fetch-boundary, import, export, or role change. Route tests must prove unauthenticated denial and CSRF/role behavior. Network tests must use mocks and include private-address, redirect, size, and TLS failure cases. Do not make live Anthropic or news calls in the test suite.

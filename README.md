# Neighbour / 鄰伴 — private cloud deployment source

This repository contains the reviewed source-only cloud candidate for the existing local Neighbour platform. It contains no resident databases, photos, memories, API credentials, native runtime, models, or AIRI vendor checkout.

Production deployment is not complete. Do not point a public Render service at the native application or claim Notebook-off availability.

Fixed services: Cloudflare Gemma dialogue, Azure HiuMaan F0 speech, and existing Tavily search. Free tiers only; no card, plan upgrade, billing, quota reset, or automatic provider substitution.

Pending release gates: executable cloud host and authenticated static/login boot, real Google audience and permitted identities, cloud ASR, consistent private data import with one formal writer, quota/control/deletion-receipt preservation, backups/restore and external end-to-end acceptance.

EP hardware and all robot actions are outside this deployment. The existing local platform and its data remain intact. See deploy/cloud/README.zh-Hant.md for candidate implementation and limitations.

The explicit API factory `deploy.cloud.host:create_host` validates provisioned metadata and opens remote stores only during ASGI startup. It preserves the original binary deletion-ledger key using a base64 host-secret envelope. Relevant isolated regression tests are under `tests/`; they use synthetic identities/data and temporary stores, not real provider calls. This still does not supply frontend hosting, real login, ASR, migration or a public-ready service.

Real Turso Free resources are now provisioned in the Neighbour-only Singapore group: nine separate **synthetic staging** databases, with encrypted local scoped-management and separate SQL read/write credentials. Official API verified $0/month and overages disabled. Remote commit/reopen/rollback, read-only write refusal and complete nine-store bootstrap passed; no private/native data or original quota counters were copied. See the current cloud README for measured startup and outstanding release gates.

1. Chose: tenant isolation, partial-success bulk ingest, duplicate/retry safety, append-only ledger with reversals, audit log, as-of balance, monthly summary - the problems where money or trust breaks.
2. Money is integer minor units with a currency whitelist; balances are per currency; withdrawals cannot overdraw (fees and reversals can).
3. Duplicates = same (firm, external_ref): identical payload is a harmless retry, different payload is a 409; the DB unique constraint is the real guard.
4. Corrections are reversal rows dated today (closed periods are not rewritten); one reversal per transaction; no reversing a reversal.
5. Risk: backdated entries still change old as-of balances (a bitemporal `known_at` filter would fix it); the audit-log actor is a self-declared X-Actor header.
6. Risk: no roles - one API key per firm has full read/write access.
7. Concurrency: a process-wide lock serialises check-then-write; unique constraints protect across processes, but a multi-worker overdraft race needs Postgres row locks.
8. Skipped: transfers, FX, rate limiting, export, suspicious-activity flags, read-only/support views - to keep the core solid in an hour.
9. At 100x load: SQLite's single writer plus the global lock is the bottleneck; balances are SUM scans, so move to Postgres with per-client balance snapshots.

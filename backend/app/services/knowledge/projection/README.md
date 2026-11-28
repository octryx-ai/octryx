# Projection outbox

A committed revision leaves outbox obligations; the worker claims them and the projector applies them idempotently.

## States

| State | Meaning | Leaves by |
|---|---|---|
| `pending` | due at `next_attempt_at` | a claim (`outbox.claim_next`) |
| `claimed` | one worker holds it until `claimed_until` | `applied`; back to `pending` on progress, contention or a failure; `dead_letter` on the last failure |
| `applied` | done | never |
| `dead_letter` | the bounded attempts are spent; never retried by itself | a requeue (`recovery.py`) |

A failure stores a fixed failure token, never a server message, and schedules the next attempt with a backoff.

## Ownership token

A claim is a conditional `UPDATE` that names the state it read and counts only when it changed exactly one row, so
two workers never hold the same entry, on PostgreSQL and SQLite alike, without `SELECT ... FOR UPDATE`.

The token of a claim is the exact lease deadline it installed (`claimed_until == ClaimedProjection.lease_until`),
not the worker id: the manual trigger uses one id per user (`api:<user_id>`), so two claims of one entry can carry
the same id. Every transition out of a claim compares id, `state == 'claimed'`, `claimed_by`, that deadline and a
still-live deadline. An expired lease is reclaimable, so a crashed worker does not strand its entry; the old holder
then gets `LEASE_LOST` and writes nothing. `renew_lease` returns a new claim with the new deadline and invalidates
the old one.

## Recovery

`recover_projection` (`recovery.py`) runs two compare-and-set transitions, each committed with exactly one redacted
audit record. Two callers can requeue: the explicit recovery API and an identical re-upload of the revision.

- **requeue**, operation `requeue_dead_letter` (API) or `requeue_dead_letter_on_reupload` (re-upload): `dead_letter`
  -> `pending`, due now, `attempt_count` 0, `last_failure` cleared; result `requeued`. `projected_through_ordinal`
  stays, so the next run continues where the failed one stopped. A repeat answers `already_pending`.
- **retry now**, operation `retry_now` (API only): a `pending` entry scheduled in the future becomes due now; result
  `retry_scheduled`. The attempt count stays, so the retry budget never widens. A repeat answers `already_due`.

`claimed` and `applied` answer `not_recoverable` without a write: clearing a live lease would give two holders the
same work.

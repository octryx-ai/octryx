# Deferred actions

`deferred_action.py` runs slow repository steps (`DEFERRED_ACTIONS`: create branch, checkout) after the request that
reached them, never inside it.

## Flow

- The engine only marks the step (`defer`): `context.deferred_action` names the pass, the step waits, and the request
  commits and returns.
- After that commit the step starts in the background, through the same post-commit hook as `server_continuation`.
- The worker's sweep (`sweep_deferred_actions`) starts a step whose start was lost (a restart) or whose lease ran
  out (a crash).

`execute`:

1. claims the run in a short transaction: the marker gets a lease (token, since, attempt) and is committed;
2. waits for a free executor slot without holding a database session;
3. in one transaction, claims the run again and checks that the pass and the lease are still its own (otherwise it
   writes nothing), runs the action (`run_platform_action`) and continues the run (`resolve_current_node`), then
   commits.

## Why there is a bound

A step holds its database session across its git and HTTP work, because `scm.create_branch` writes to the run
between them. Without a bound, parallel run starts each hold a pooled connection for minutes and every other request
fails with a pool timeout.

`max_concurrent` is a resource rule tied to the connection pool, not a throttle: deferred steps hold at most a third
of the pool (`POOL_SHARE`), the rest stays for requests, waiting steps hold no connection, and a step's writes stay
one transaction. Each run clones into its own session workspace, so there is no shared clone lock to wait on.

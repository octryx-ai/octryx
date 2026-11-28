# Publish and prove

`publication_v2.py` publishes a run's approved write intent through Confluence Cloud v2 exactly once, and proves
what was published by reading it back. The intent states live in `write_intent.py`.

## The protocol

1. **Dispatch check**, in the run's claimed transaction. The active intent must be approved; a possibly sent intent
   is reconciled first. The latest publication decision must still bind the exact body and marker, the run must
   still be running, and the pinned settings, connection and instance must be unchanged. The result is stored as
   the intent's `dispatch_check`.
2. **One claimed sender.** `approved | never_started_certified -> send_started` is a compare-and-set, committed
   together with the pass lease (`external_step`) before any provider request. No run transaction is held over the
   network.
3. **Read-only pre-send checks** (space, parent, page base version) and a last stop check. A failure here is
   certified never started: nothing was sent. Certification is the only way back to a sendable state.
4. **The one mutating request.** A definite refusal (no request sent, or a 4xx answer; 409 is `page_changed`) is
   certified never started. Anything that may have been applied (timeout, 5xx, a malformed 2xx) becomes
   `pending_reconcile`, is committed, and is reconciled at once.
5. **Read-back.** A valid reply becomes `sent_confirmed` only after the full storage read-back. The run is then
   claimed again (`run_moved_on` if it moved) and the page is recorded.

## Why

- A page write cannot be rolled back, so every state that might have reached the provider is either proven by the
  read-back or reconciled, never retried blind.
- The governed checks see the approved body; the platform marker is added only to the body that is sent.
- The `ai-generated` label is best effort and is not part of the publication contract.

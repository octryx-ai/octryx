# Mobile routes

Octryx Mobile: the phone's side of pairing and its session, the signed-in phone's account views and the live view of
the sessions running on a person's devices. The rules live in `services/mobile` and `services/devices`.

## Invariants

- A pairing is confirmed only from the person's own signed-in web session: no bearer token, API key or phone
  (`mobile.confirm_in_browser`).
- Driving a session on the person's machine needs their own interactive login; an API key or a bearer token gets
  403 `interactive_login_required` (`mobile_account.py`).

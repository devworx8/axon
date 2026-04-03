# Axon Companion Native

Thin Expo / React Native scaffold for the Jarvis-style companion.

## What this maps to

The app is wired around the new Axon companion and attention contracts:

- `/api/companion/status`
- `/api/companion/identity`
- `/api/companion/auth/pair`
- `/api/companion/auth/refresh`
- `/api/companion/auth/revoke`
- `/api/companion/devices`
- `/api/companion/presence/current`
- `/api/companion/presence/heartbeat`
- `/api/companion/sessions`
- `/api/companion/sessions/{id}/resume`
- `/api/companion/voice/turns`
- `/api/companion/push/subscriptions`
- `/api/attention/summary`
- `/api/attention/inbox`
- `/api/attention/items`
- `/api/connectors/overview`

## Structure

- `src/api` contains the fetch client and Axon contract adapters.
- `src/features/auth` owns pairing and device auth.
- `src/features/presence` owns live companion presence and workspace sync.
- `src/features/voice` owns voice turns and transcript/reply handling.
- `src/features/attention` owns the inbox-first operational feed.
- `src/features/workspace` owns the current workspace context.
- `src/features/session` owns active companion session continuity.
- `src/features/settings` owns local companion settings and preferences.
- `src/navigation` keeps the shell small and shared across the app.

## Notes

- This scaffold is intentionally thin and modular.
- It does not hardcode backend logic into one giant screen.
- The app expects the Axon desktop runtime to remain the source of truth for attention, connector status, and session continuity.


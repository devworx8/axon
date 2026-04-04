# Axon Online Native

Thin Expo / React Native shell for Axon Online.

## What this maps to

The app is wired around the Axon Online mobile, live-state, and attention contracts:

- `/api/companion/status`
- `/api/companion/identity`
- `/api/companion/live`
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
- `src/features/live` owns the Axon Live mobile snapshot.
- `src/features/presence` owns device presence and workspace sync.
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
- Pairing uses the same Axon PIN as desktop.

## Install on Mobile

1. `cd apps/companion-native`
2. `npm install`
3. `npm run doctor`
4. `npm run start`
5. For the quickest JS-only smoke test, install `Expo Go` on your phone and scan the QR code.
6. In the app, set the Axon desktop URL before pairing:
   - example: `http://192.168.1.50:7734`
   - do not leave it on `127.0.0.1` on a physical phone
7. Pair the device with the Axon PIN.

Important:
- Native-only features such as biometric elevation require a development build or production build.
- If you add native modules after installing a dev build, rebuild the client before testing those features.

### Useful scripts

- From `apps/companion-native`:
  - `npm run start`
  - `npm run start:dev-client`
  - `npm run web`
  - `npm run doctor`
  - `npm run axon:start`
  - `npm run axon:stop`
  - `npm run eas:build:android:dev`
  - `npm run eas:build:ios:dev`
- From `~/.devbrain`:
  - `npm run start`
  - `npm run web`
  - `npm run doctor`
  - `npm run axon:start`
  - `npm run axon:stop`

### Real installable native builds

1. `npm install`
2. `npx expo install expo-dev-client`
3. `eas login`
4. `eas init`
5. Start Metro for a dev client:
   - `npm run start:dev-client`
6. Build internal development clients:
   - Android: `npm run eas:build:android:dev`
   - iPhone: `npm run eas:build:ios:dev`

Notes:
- This repo is preconfigured for EAS development builds via `eas.json`.
- `app.json` already includes the native identifiers:
  - iOS bundle ID: `za.org.edudashpro.axononline`
  - Android package: `za.org.edudashpro.axononline`

## Axon tokens without the vault

Axon can read Expo credentials from the server environment as an alternative to the Secure Vault.

Recommended:

1. Create `~/.devbrain/.env.local`
2. Add:

```bash
EXPO_TOKEN=your_expo_access_token
AXON_VERCEL_TOKEN=your_vercel_token
GH_TOKEN=your_github_token
```

3. Restart Axon:

```bash
cd ~/.devbrain
./stop.sh
./start.sh
```

Notes:
- `start.sh` now loads both `~/.devbrain/.env` and `~/.devbrain/.env.local`.
- For Expo specifically, Axon accepts `EXPO_TOKEN` or `EXPO_ACCESS_TOKEN`.
- For multiple Expo owners, Axon also accepts owner-specific names. Example:

```bash
EXPO_TOKEN=token_for_king_prod
EXPO_TOKEN__DASH_TS_ORGANIZATION=token_for_dash_ts_organization
```

  Supported owner-specific forms are:
  - `EXPO_TOKEN__<OWNER>`
  - `EXPO_ACCESS_TOKEN__<OWNER>`
  - `EXPO_TOKEN_<OWNER>`
  - `EXPO_ACCESS_TOKEN_<OWNER>`

  where `<OWNER>` is the Expo owner name uppercased with non-alphanumeric characters replaced by `_`.
- The server-side setting `expo_api_token` also works, but an env file is usually cleaner than storing raw provider tokens in app settings.

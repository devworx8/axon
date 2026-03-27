# Changelog

## 2026-03-26

- Fixed Desktop Preview crashes by replacing the single ImageMagick capture path with a guarded fallback chain and a clear no-display response.
- Fixed the Memory page showing an empty list by correcting the filtered memory accessor so it stays reactive, and added a visible filter result counter.
- Fixed the Timeline page showing no activity by implementing the missing activity loader for the Timeline tab.
- Improved Stable Domain diagnostics with structured 403 guidance, inline re-check action, and last-checked timestamp.
- Improved Console generation UX with a visible stop-status pill above the composer while Axon is working.
- Reduced Console right-panel density with collapsible Agent Steps and Local Tools sections plus clearer sandbox signalling.
- Added a proper Playbooks onboarding empty state with starter examples.
- Enriched Mission cards with status badges, workspace chips, updated timestamps, progress bars, and header summary counts.
- Added an inline warning when images are attached without a configured vision model.
- Added TODO badge tooltips clarifying the scan debt count source.
- Added scan trigger labels for scheduled, manual, and startup-triggered scans, plus last auto-scan visibility in Settings.
- Added mobile-safe design tokens, touch-target utilities, skeleton helpers, and safe-area page spacing for the fixed mobile header and bottom nav.
- Replaced emoji-based mobile nav icons with inline SVGs and rebuilt the More drawer with backdrop dismissal, Escape handling, and auto-close on navigation.
- Collapsed the mobile console metadata under the composer into a compact expandable status strip so the text input stays primary on small screens.
- Reworked mobile workspace filter chips and card actions for 44px touch targets and added an overflow menu for secondary actions.
- Added vault password visibility toggles and a visible forgot-password recovery affordance on the locked vault screen.
- Added a unified provider identity row for Ollama, CLI Agent, and API runtimes, with matching provider icons and active model labels in the console and assistant stream.
- Split agent planning and execution into explicit Thinking and Working blocks so console messages expose internal phase transitions instead of mixing reasoning into the final answer bubble.
- Added an approval-first live page control flow with backend proposal endpoints, runtime snapshot support, permission cards, and console review actions for future browser automation.
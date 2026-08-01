# Lyse 2 rewrite roadmap

## Purpose

Lyse 2 is a cross-platform, terminal-first rewrite of Lyse. It should feel like
the same product: show lyrics for the active song, keep them synchronized when
timing is available, and stay pleasant to use from a terminal. The current
Python application on `main` remains the stable Linux release while this work
is in progress.

The rewrite is intended to improve portability, responsiveness, testability,
and maintainability. A new GUI product is outside this project's initial scope.

## Platform strategy

The application core must not invoke a platform command directly. It should
depend on two narrow interfaces instead:

- **Playback provider:** reads the active track, player state, duration,
  position, and optional seek support.
- **Terminal/UI provider:** renders the terminal experience and handles input
  in a way appropriate for the host terminal.

The first supported providers should be:

| Platform | Playback approach | Notes |
| --- | --- | --- |
| Linux | MPRIS, initially through `playerctl` | Preserve the current broad player support. |
| macOS | Native media-session support, with app-specific adapters only where needed | Start with the common system-visible players. |
| Windows | Global System Media Transport Controls | Support players that expose an OS media session. |

Configuration and cache paths must use platform-native locations rather than
hard-coded Linux paths. The terminal layer must run in Windows Terminal and
PowerShell as well as common Unix terminals.

## Delivery milestones

1. **Foundation:** choose the runtime and project layout; define typed playback,
   lyric-source, cache, and UI interfaces; add automated tests for the
   platform-independent core.
2. **Parity on Linux:** implement the Linux provider and reproduce the existing
   command-line, pipe-mode, lyric fetch, cache, offset, and key controls.
3. **macOS and Windows support:** implement media-session providers, native
   data locations, and terminal compatibility; test against real players on
   each platform.
4. **Release readiness:** package supported platform builds, publish an
   explicit compatibility matrix, write migration notes, and collect early-user
   feedback before making Lyse 2 the default branch release.

## Compatibility promise

Before Lyse 2 becomes the default release, it should preserve these user-facing
capabilities where the operating system exposes them:

- Automatic active-track detection and lyric lookup
- Synced and plain lyric display
- Adjustable lyric offset
- `--pipe` and `--live` output for status-bar integrations
- A terminal interface with the established keyboard controls

Unsupported player or terminal combinations should fail clearly and explain
which playback provider is missing. Platform-specific limitations belong in a
published compatibility matrix, not in silent fallbacks.

## Migration and release plan

- Keep the current Python release available from `main` until Lyse 2 reaches
  feature and reliability parity for Linux.
- Preserve the final Python state with a version tag and document its support
  status in the release notes.
- Release Lyse 2 as the next major version, with installation instructions per
  platform and a concise migration guide for existing configuration and pipe
  users.
- Retain the `lyse2` branch as the rewrite's development history; merge it into
  `main` only once the release-readiness milestone is met.

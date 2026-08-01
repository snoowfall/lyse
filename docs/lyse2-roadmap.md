# lyse2

WIP cross-platform rewrite. `main` remains the Python/Linux release.

Public name: **Lyse**. `lyse2` is only the development branch name.

## Scope

- Terminal UI only
- Linux, macOS, Windows
- Current track + position from the active media player
- LRCLIB lookup, synced lyrics, plain lyrics
- Offset controls
- `--pipe` / `--live`

Not in scope: GUI, account system, lyric editing, a plugin API.

## Design constraints

- No platform commands in the core package.
- Player integration lives behind a small interface: track, state, position,
  duration, seek.
- Keep lyric parsing, cache, CLI output, and state updates independent of the
  terminal renderer.
- Use the OS config/cache directories. Do not keep Linux paths on Windows or
  macOS.
- Do not remove a current feature without documenting it first.

## Player backends

| OS | Backend | Status |
| --- | --- | --- |
| Linux | MPRIS / `playerctl` | Existing behaviour to match |
| Windows | GSMTC | Need implementation and player testing |
| macOS | Native media session or per-player adapter | Need investigation |

macOS is the uncertain one. Do not promise broad player support until it has
been tested with real apps.

## Work

- [ ] Pick runtime and packaging approach.
- [ ] Create project layout and CI for Linux, macOS, and Windows.
- [ ] Implement lyric parsing, LRCLIB client, cache, and offset logic.
- [ ] Define the player backend interface.
- [ ] Implement Linux backend and match current CLI behaviour.
- [ ] Implement terminal UI and input handling on Unix and Windows terminals.
- [ ] Implement Windows backend.
- [ ] Investigate and implement macOS backend.
- [ ] Add tests with fake players and parser/cache fixtures.
- [ ] Test against real players on each OS.
- [ ] Write install docs and a supported-player matrix.

## Before merging into `main`

- Linux feature parity with the Python app.
- `--pipe` and `--live` work.
- Clear error when no supported player is found.
- Windows and macOS builds run and have documented player support.
- A release package exists for every supported OS.

Keep the final Python release tagged. Merge this branch only when the rewrite is
usable as the default install.

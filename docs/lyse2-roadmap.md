# Rewrite plan

`lyse2` is the branch for a rewrite. `main` stays on the current Python app
until the rewrite can replace it. The public name stays **Lyse**; `lyse2` is
only the branch name.

## Goal

Build a fast terminal lyrics app for Linux, macOS, and Windows.

It must show the current track, fetch lyrics from LRCLIB, display synced lyrics,
and work without a GUI. A desktop GUI is not part of this rewrite.

## Shape of the app

Keep the app core separate from the operating system code.

- The core handles lyrics, cache, offset, commands, and screen state.
- A player backend gets track information and sends seek commands.
- The terminal code draws the UI and reads key presses.

Start with one player backend per platform:

| Platform | Backend |
| --- | --- |
| Linux | MPRIS via `playerctl` |
| macOS | System media controls |
| Windows | Global System Media Transport Controls |

Use the normal config and cache directory for each operating system. Do not use
`~/.config` or `~/.cache` on macOS and Windows. The terminal UI must work in
common Unix terminals, Windows Terminal, and PowerShell.

## Build order

1. Pick the language and create the project structure.
2. Build the core and test it without a real player.
3. Add Linux support and match the current app's features.
4. Add macOS support.
5. Add Windows support.
6. Package releases and document supported players and terminals.

## Required before release

The rewrite needs these features before it replaces the Python version:

- Track detection and lyric lookup
- Synced and plain lyrics
- Offset controls
- `--pipe` and `--live`
- Existing keyboard controls where the terminal supports them
- Clear errors when no supported player is available

Test it with real players on all three operating systems. Publish a table that
lists which players are supported on each platform.

## Release

Keep `main` on the Python version until the rewrite passes the checks above.
Tag the final Python release, then merge `lyse2` into `main` for the next major
Lyse release. Include install steps and a short migration guide for existing
config and pipe users.

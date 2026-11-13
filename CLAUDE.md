<!-- router: Public Claude Code skill for animated explainer videos (Remotion + AI-drawn assets), with media adapters, audio/layout checks and offline tests -->
# Working on this repo

Public, standalone. Keep it free of private hosts, paths, people and provider internals.

## Layout

- `explainer-video/` is the skill: `SKILL.md`, `SCHEMA.md`, `ADAPTERS.md`, `scripts/`,
  `adapters/`, `brands/`, `starter/`.
- `tests/test_pipeline.py` covers the scripts offline, with fake speech and sound generators.
- `tests/e2e.sh` scaffolds a project and renders a real video with synthesised media.

## Before a commit

```bash
python3 -m unittest discover -s tests
bash tests/e2e.sh          # needs ffmpeg, node 20+, npm; takes a few minutes
npx tsc --noEmit           # inside a project made by new-project.sh, or explainer-video/starter
```

The provider calls in `adapters/` are not covered by the offline tests. Say so in a change that
touches them, and test against the real API before a release.

## Rules

- The scripts must keep working with any adapter that follows `ADAPTERS.md`. No provider name
  may leak into `scripts/`.
- Keys come from the environment. Never write a key, a token or a private path into a file.
- Keep `starter/` minimal and working: `new-project.sh` must produce a project that renders and
  passes `check-layout.py` with no edits.

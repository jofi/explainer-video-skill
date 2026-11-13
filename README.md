# explainer-video

A [Claude Code](https://claude.com/claude-code) skill that makes **animated explainer videos**:
AI-drawn characters, scenes and props, animated in [Remotion](https://remotion.dev), with voices,
music, sound effects and subtitles.

Animation only. It never calls a text-to-video model: every frame is composed from images, SVG
and code, so a character looks the same in every shot and every frame can be reproduced.

## What you get

- **`explainer-video/SKILL.md`** — the workflow: storyboard → characters → scenes → voices →
  animation → picture and sound checks → delivery. Each rule comes from a version that was
  rejected.
- **`explainer-video/scripts/`** — the pipeline tools. The two that earn their keep on every
  project:
  - `check-audio.py` fails a mix where music or an effect covers the voice, an effect startles,
    or a music take has degraded into noise. It compares the mix against the voice track alone,
    so a loud effect is not mistaken for a stressed word.
  - `regen-voices.py` regenerates only the lines whose request changed, keeps every take, and
    writes the per-frame mouth envelopes and beat timings.
- **`explainer-video/starter/`** — a minimal Remotion project that already does the hard parts:
  storyboard layout, camera moves with parallax, pose crossfades, lip sync from loudness
  envelopes, music ducking, opening and closing cards.
- **`explainer-video/adapters/`** — reference media generators (Gemini images, ElevenLabs speech /
  effects / music, free edge-tts speech, local rembg cutouts). Bring your own: the contract is
  five small CLIs, documented in `ADAPTERS.md`.
- **`explainer-video/SCHEMA.md`** — one folder layout per project, so a video renders again from
  its own files months later. `check-layout.py` enforces it.

## Install

```bash
git clone https://github.com/lubomier/explainer-video-skill.git
mkdir -p ~/.claude/skills
ln -s "$PWD/explainer-video-skill/explainer-video" ~/.claude/skills/explainer-video
```

Then ask Claude Code for an explainer video, or run `/explainer-video`.

Requirements: `ffmpeg` and `ffprobe`, Python 3 with `numpy`, Node 20+ for Remotion.

Media backends are optional and independent. A keyless setup still works for a schematic video:
SVG scenes, free `edge-tts` voices, your own music file. To use the reference adapters:

```bash
python3 -m venv ~/.venvs/explainer
~/.venvs/explainer/bin/pip install -r explainer-video/adapters/requirements.txt
export PATH=~/.venvs/explainer/bin:$PATH
export GEMINI_API_KEY=...        # images
export ELEVENLABS_API_KEY=...    # paid speech, sound effects, music
```

## A project in five commands

```bash
export EXPLAINER_ROOT=~/explainer
~/.claude/skills/explainer-video/scripts/new-project.sh my-video "What the video explains"
cd ~/explainer/my-video && npm install
# write in/brief.md and storyboard.json, then generate the voices
python3 scripts/regen-voices.py edge-tts
python3 scripts/level-voices.py
node scripts/gen-envelopes.mjs
npx remotion studio src/index.ts
```

Render and check:

```bash
npx remotion render src/index.ts Body work/mix.wav
python3 scripts/check-audio.py work/mix.wav        # must pass before the video render
npx remotion render src/index.ts Full out/my-video-full.mp4
python3 scripts/check-audio.py out/my-video-full.mp4 --offset 3
python3 scripts/edge-scan.py out/my-video-full.mp4
```

## Tests

```bash
python3 -m unittest discover -s tests   # 17 offline tests, no keys
bash tests/e2e.sh                       # scaffolds a project and renders a real video offline
```

The pipeline, the audio gate and the Remotion starter are covered. The provider calls in
`adapters/` are **not** covered by these tests: they need your keys. If one misbehaves, the
contract in `ADAPTERS.md` is the reference, not the adapter.

## Notes

- Voices: never clone a real person's voice without that person's written consent. Previews use
  the free voice; the paid voice is generated after the cut is approved.
- Keys stay in the environment. No adapter reads a key file or prints a key.
- Privacy: nothing is uploaded by the skill. Delivery is a file in `out/`. External review of a
  still is opt-in (`REVIEW_IMAGE`), and private material should never go to an external reviewer.

## License

MIT — see [LICENSE](LICENSE).

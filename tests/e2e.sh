#!/usr/bin/env bash
# End-to-end check, offline: scaffold a project, synthesise voices and music with ffmpeg,
# render the video in Remotion and run the audio and edge gates on it.
#
#   bash tests/e2e.sh [workdir]
#
# Needs: ffmpeg, python3 with numpy, node 20+, npm. No API keys, no network for the media.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work="${1:-$(mktemp -d /tmp/explainer-e2e-XXXX)}"
mkdir -p "$work"
echo "workdir: $work"

export EXPLAINER_ROOT="$work"
bash "$repo/explainer-video/scripts/new-project.sh" demo "offline end-to-end check"
cd "$work/demo"

cat > fake-speech.py <<'EOF'
import hashlib, subprocess, sys
text, out = sys.argv[1], sys.argv[2]
f = 200 + int(hashlib.sha256(text.encode()).hexdigest(), 16) % 300
subprocess.run(["ffmpeg","-nostdin","-y","-v","error","-f","lavfi","-i",
                f"sine=frequency={f}:duration=1.5","-af","volume=0.5",
                "-ar","44100","-b:a","128k",out],check=True)
EOF
cat > fake-sfx.py <<'EOF'
import subprocess, sys
p, out = sys.argv[1], sys.argv[2]
subprocess.run(["ffmpeg","-nostdin","-y","-v","error","-f","lavfi","-i",
                "aevalsrc=0.8*sin(880*2*PI*t)*exp(-40*t):d=2:s=44100",
                "-ar","44100","-ac","1",out],check=True)
EOF
export GEN_SPEECH="python3 $PWD/fake-speech.py" GEN_SFX="python3 $PWD/fake-sfx.py"

cat > storyboard.json <<'EOF'
{
 "gap_s": 0.4,
 "voices": {"narrator": {"voice_id": "test"}},
 "beats": [
  {"id": "b01", "speaker": "narrator", "line": "This is the first point."},
  {"id": "b02", "speaker": "narrator", "line": "And here is the second one."},
  {"id": "b03", "speaker": "narrator", "line": "The third point lands."}
 ]
}
EOF

python3 scripts/regen-voices.py edge-tts
python3 scripts/level-voices.py
node scripts/gen-envelopes.mjs
python3 scripts/gen-sfx-set.py

ffmpeg -nostdin -y -v error -f lavfi -i "sine=frequency=330:duration=7" -af "volume=0.05" \
  -b:a 128k assets/music/score.mp3
python3 scripts/fit-music.py assets/music/score.mp3

npm install --no-audit --no-fund
npx tsc --noEmit
npx remotion render src/index.ts Body work/mix.wav --log=error
python3 scripts/check-audio.py work/mix.wav
npx remotion render src/index.ts Full out/demo-full.mp4 --log=error
python3 scripts/check-audio.py out/demo-full.mp4 --offset 3
python3 scripts/edge-scan.py out/demo-full.mp4
# the fakes live in the project root, which the layout check rejects; remove them first
rm fake-speech.py fake-sfx.py
python3 "$repo/explainer-video/scripts/check-layout.py" "$work/demo"
echo "PASS: $work/demo/out/demo-full.mp4"

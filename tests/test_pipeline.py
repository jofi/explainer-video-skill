"""Offline tests for the explainer-video pipeline. No API keys, no network.

    python3 -m pytest tests/ -q        # or: python3 -m unittest discover tests

The speech and sound generators are fakes on PATH that synthesise a tone with ffmpeg, so the
voice cache, the loudness gate and the sound library run exactly as they do against a real API.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "explainer-video" / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), SCRIPTS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sh(cmd, cwd, env=None, check=True):
    e = dict(os.environ)
    if env:
        e.update(env)
    r = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"{cmd}\n{r.stdout}\n{r.stderr}")
    return r


FAKE_SPEECH = r"""#!/usr/bin/env python3
# A stand-in for gen-speech: a 1.2 s tone whose frequency depends on the text.
import hashlib, subprocess, sys
text, out = sys.argv[1], sys.argv[2]
freq = 200 + int(hashlib.sha256(text.encode()).hexdigest(), 16) % 400
subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i",
                f"sine=frequency={freq}:duration=1.2", "-ar", "44100", "-b:a", "128k", out], check=True)
print(out)
"""

FAKE_SFX = r"""#!/usr/bin/env python3
# A stand-in for gen-sfx: a decaying click, crest well above the noise gate.
import subprocess, sys
prompt, out = sys.argv[1], sys.argv[2]
subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i",
                "aevalsrc=0.8*sin(880*2*PI*t)*exp(-40*t):d=2:s=44100",
                "-ar", "44100", "-ac", "1", out], check=True)
print(out)
"""


class Project(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="explainer-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for d in ("assets/voice", "assets/voice-norm", "public/voice-norm", "public/mouth",
                  "public/sfx", "assets/music"):
            (self.tmp / d).mkdir(parents=True)
        self.sb = {"gap_s": 0.4, "language": "en",
                   "voices": {"narrator": {"voice_id": "test-voice"}},
                   "beats": [{"id": "b01", "speaker": "narrator", "line": "Hello there."},
                             {"id": "b02", "speaker": "narrator", "line": "Second line."}]}
        self.write_sb()
        self.env = {"GEN_SPEECH": f"python3 {self.tmp/'fake-speech.py'}",
                    "GEN_SFX": f"python3 {self.tmp/'fake-sfx.py'}",
                    "SFX_LIBRARY": str(self.tmp / "library")}
        (self.tmp / "fake-speech.py").write_text(FAKE_SPEECH)
        (self.tmp / "fake-sfx.py").write_text(FAKE_SFX)

    def write_sb(self):
        (self.tmp / "storyboard.json").write_text(json.dumps(self.sb))

    def voices(self, *args):
        return sh(["python3", str(SCRIPTS / "regen-voices.py"), "edge-tts", *args], self.tmp, self.env)


class TestVoiceCache(Project):
    def test_first_run_writes_takes_timings_and_envelopes(self):
        self.voices()
        sb = json.loads((self.tmp / "storyboard.json").read_text())
        self.assertEqual(sb["total_s"], 3.2)
        for b in sb["beats"]:
            self.assertEqual(b["frames"], 36)
            self.assertIn("voice_key", b)
            self.assertTrue((self.tmp / f"public/voice-norm/{b['id']}.wav").exists())
            env = json.loads((self.tmp / f"public/mouth/{b['id']}.json").read_text())
            self.assertEqual(env["frames"], 36)
            self.assertAlmostEqual(max(env["env"]), 1.0, places=3)
        self.assertEqual(sb["beats"][1]["start_frame"], 48)

    def test_second_run_regenerates_nothing(self):
        self.voices()
        takes = sorted((self.tmp / "assets/voice/takes").iterdir())
        out = self.voices().stdout
        self.assertIn("kept", out)
        self.assertNotIn("new", out)
        self.assertEqual(takes, sorted((self.tmp / "assets/voice/takes").iterdir()))

    def test_changed_line_regenerates_only_that_beat(self):
        self.voices()
        first = json.loads((self.tmp / "storyboard.json").read_text())
        self.sb["beats"] = first["beats"]
        self.sb["beats"][0]["line"] = "A different line."
        self.write_sb()
        self.voices()
        after = json.loads((self.tmp / "storyboard.json").read_text())
        self.assertNotEqual(after["beats"][0]["voice_key"], first["beats"][0]["voice_key"])
        self.assertEqual(after["beats"][1]["voice_key"], first["beats"][1]["voice_key"])
        self.assertEqual(len(list((self.tmp / "assets/voice/takes").glob("b02-*"))), 1)

    def test_fresh_rerolls_an_unchanged_line(self):
        self.voices()
        self.voices("--fresh", "b02")
        self.assertEqual(len(list((self.tmp / "assets/voice/takes").glob("b02-*"))), 2)

    def test_restore_rejects_a_take_for_another_request(self):
        self.voices()
        take = next((self.tmp / "assets/voice/takes").glob("b01-*"))
        self.sb["beats"] = json.loads((self.tmp / "storyboard.json").read_text())["beats"]
        self.sb["beats"][0]["line"] = "Changed."
        self.write_sb()
        r = sh(["python3", str(SCRIPTS / "regen-voices.py"), "edge-tts", "--restore", str(take)],
               self.tmp, self.env, check=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("another request", r.stderr)

    def test_audio_tag_is_sent_but_not_in_the_subtitle_line(self):
        self.sb["beats"][0]["tag"] = "warmly"
        self.write_sb()
        self.voices()
        sb = json.loads((self.tmp / "storyboard.json").read_text())
        self.assertEqual(sb["beats"][0]["line"], "Hello there.")
        self.assertEqual(sb["beats"][0]["tag"], "warmly")
        voices = load("regen-voices.py")
        self.assertEqual(voices.request(self.sb, 0, "edge-tts")[0], "Hello there.")
        self.assertEqual(voices.request(self.sb, 0, "elevenlabs-v4")[0], "[warmly] Hello there.")

    def test_unknown_fresh_target_is_an_error(self):
        r = sh(["python3", str(SCRIPTS / "regen-voices.py"), "edge-tts", "--fresh", "nope"],
               self.tmp, self.env, check=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no beat or speaker", r.stderr)


class TestLevelAndMix(Project):
    def test_level_voices_and_clean_mix_passes(self):
        self.voices()
        sh(["python3", str(SCRIPTS / "level-voices.py")], self.tmp, self.env)
        sh(["node", str(SCRIPTS / "gen-envelopes.mjs")], self.tmp, self.env)
        self.assertTrue((self.tmp / "src/envelopes.json").exists())
        # a "mix" that is only the voices, in the places the storyboard puts them
        sb = json.loads((self.tmp / "storyboard.json").read_text())
        sh(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3.2",
            "-af", "volume=0.0", "-ar", "48000", str(self.tmp / "assets/music/bed.wav")], self.tmp)
        sh(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(self.tmp / "assets/music/bed.wav"),
            "-c:a", "libmp3lame", str(self.tmp / "public/music.mp3")], self.tmp)
        # mix = the two levelled voices, delayed to their starts
        mix = self.tmp / "work/mix.wav"
        mix.parent.mkdir(exist_ok=True)
        delays = ";".join(f"[{i}:a]adelay={int(b['start_s']*1000)}|{int(b['start_s']*1000)}[d{i}]"
                          for i, b in enumerate(sb["beats"]))
        inputs = []
        for b in sb["beats"]:
            inputs += ["-i", str(self.tmp / f"public/voice-norm/{b['id']}.wav")]
        sh(["ffmpeg", "-nostdin", "-y", "-v", "error", *inputs, "-filter_complex",
            delays + ";[d0][d1]amix=inputs=2:normalize=0", "-ar", "48000", str(mix)], self.tmp)
        r = sh(["python3", str(SCRIPTS / "check-audio.py"), str(mix)], self.tmp, self.env)
        self.assertIn("PASS", r.stdout)

    def test_loud_music_fails_rule_b(self):
        self.voices()
        sh(["python3", str(SCRIPTS / "level-voices.py")], self.tmp, self.env)
        sb = json.loads((self.tmp / "storyboard.json").read_text())
        sh(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3.2",
            "-af", "volume=0.5", "-ar", "48000", str(self.tmp / "assets/music/bed.wav")], self.tmp)
        sh(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(self.tmp / "assets/music/bed.wav"),
            "-c:a", "libmp3lame", str(self.tmp / "public/music.mp3")], self.tmp)
        r = sh(["python3", str(SCRIPTS / "check-audio.py"), str(self.tmp / "public/music.mp3")],
               self.tmp, self.env, check=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL", r.stdout)

    def test_negative_offset_is_rejected(self):
        r = sh(["python3", str(SCRIPTS / "check-audio.py"), "x.wav", "--offset", "-1"],
               self.tmp, self.env, check=False)
        self.assertNotEqual(r.returncode, 0)

    def test_noise_run_detection(self):
        ca = load("check-audio.py")
        import numpy as np
        rng = np.random.default_rng(7)
        clean = np.sin(2 * np.pi * 220 * np.arange(10 * ca.SR) / ca.SR).astype(np.float32) * 0.3
        self.assertEqual(ca.noise_runs(clean), [])
        noisy = clean.copy()
        noisy[4 * ca.SR:9 * ca.SR] = rng.normal(0, 0.2, 5 * ca.SR).astype(np.float32)
        runs = ca.noise_runs(noisy)
        self.assertEqual(len(runs), 1)
        self.assertLessEqual(runs[0][0], 5)
        self.assertGreaterEqual(runs[0][1], 8)


class TestSfx(Project):
    def test_set_is_levelled_and_reused_from_the_library(self):
        (self.tmp / "sfx.json").write_text(json.dumps({"tick": [0.3, "soft tick"], "pop": [0.4, "soft pop"]}))
        out = sh(["python3", str(SCRIPTS / "gen-sfx-set.py")], self.tmp, self.env).stdout
        self.assertIn("generated", out)
        report = json.loads((self.tmp / "public/sfx/sfx-report.json").read_text())
        for name in ("tick", "pop"):
            self.assertLessEqual(report[name]["peak_db"], -2.9)
            self.assertAlmostEqual(report[name]["active_rms_db"], -30.0, delta=0.6)
        self.assertEqual(len(list((self.tmp / "library").glob("*.wav"))), 2)
        out2 = sh(["python3", str(SCRIPTS / "gen-sfx-set.py")], self.tmp, self.env).stdout
        self.assertIn("library", out2)
        self.assertNotIn("generated", out2)

    def test_a_new_prompt_is_a_new_sound(self):
        (self.tmp / "sfx.json").write_text(json.dumps({"tick": [0.3, "soft tick"]}))
        sh(["python3", str(SCRIPTS / "gen-sfx-set.py")], self.tmp, self.env)
        (self.tmp / "sfx.json").write_text(json.dumps({"tick": [0.3, "a different tick"]}))
        sh(["python3", str(SCRIPTS / "gen-sfx-set.py")], self.tmp, self.env)
        self.assertEqual(len(list((self.tmp / "library").glob("tick-*.wav"))), 2)


class TestLayout(unittest.TestCase):
    def test_new_project_passes_the_layout_check(self):
        if not shutil.which("bash"):
            self.skipTest("no bash")
        tmp = Path(tempfile.mkdtemp(prefix="explainer-layout-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        sh(["bash", str(SCRIPTS / "new-project.sh"), "demo", "a test"], tmp,
           {"EXPLAINER_ROOT": str(tmp)})
        self.assertTrue((tmp / "demo/src/index.ts").exists())
        self.assertTrue((tmp / "demo/storyboard.json").exists())
        r = sh(["python3", str(SCRIPTS / "check-layout.py"), str(tmp / "demo")], tmp)
        self.assertIn("ok", r.stdout)
        self.assertNotIn("error:", r.stdout)

    def test_unknown_folder_is_an_error(self):
        cl = load("check-layout.py")
        tmp = Path(tempfile.mkdtemp(prefix="explainer-bad-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "src").mkdir()
        (tmp / "src/index.ts").write_text("")
        (tmp / "CLAUDE.md").write_text("<!-- router: x -->\n## Layout\n")
        (tmp / "storyboard.json").write_text("{}")
        (tmp / "package.json").write_text("{}")
        for d in ("in", "public", "out"):
            (tmp / d).mkdir()
        (tmp / "bg").mkdir()
        r = cl.check(tmp)
        self.assertTrue(any("unknown folder" in e for e in r.errors))


class TestAdapters(unittest.TestCase):
    def test_speech_rejects_paid_flags_on_the_free_model(self):
        r = subprocess.run([sys.executable, str(REPO / "explainer-video/adapters/gen-speech.py"),
                            "hi", "out.mp3", "--model", "edge-tts", "--stability", "0.3"],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("elevenlabs", r.stderr)

    def test_image_requires_a_key(self):
        env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
        r = subprocess.run([sys.executable, str(REPO / "explainer-video/adapters/gen-image.py"),
                            "a rocket", "out.png"], capture_output=True, text=True, env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue("GEMINI_API_KEY" in r.stderr or "install" in r.stderr)


if __name__ == "__main__":
    unittest.main()

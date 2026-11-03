#!/usr/bin/env bash
# HomeAI Cloud — demo audio clips (P0-12).
# Owner: Renuka. Source of truth: docs/03_REPO_AND_INFRA.md section 7,
# docs/02_CONTRACTS.md section 3 (home-label mapping).
#
# Produces 8 clips in ./demo_clips at 16 kHz mono WAV, 5-10 s each, one per home
# label plus speech + silence:
#
#   smoke_alarm.wav  distress_sound stand-in -> scream.wav
#   glass_break.wav  fall stand-in -> thud.wav   cough.wav
#   speech.wav       dog.wav                     silence.wav
#
# Real environmental sounds come from the ESC-50 dataset (CC BY-NC, academic use;
# credited in the README). The smoke-alarm beep, speech tone and silence are
# generated so the set is self-contained and redistribution-safe. Everything is
# normalised to 16 kHz mono with ffmpeg.
#
# demo_clips/ is git-ignored on purpose (do not redistribute ESC-50 audio); this
# script regenerates the set on demand.
#
# Requirements: bash, ffmpeg, python3 (numpy optional — a pure-python fallback is
# used when numpy is missing), curl.
set -euo pipefail

OUT_DIR="${1:-demo_clips}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${OUT_DIR}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' is required but not installed." >&2; exit 1; }; }
need ffmpeg
need python3

# ESC-50 is served from GitHub as a single zip of 2000 clips. Pulling the whole
# archive for 5 files is wasteful, so we fetch individual files from the raw
# content host. Filenames follow {fold}-{clip}-{take}-{target}.wav where target
# is the ESC-50 class id; these are real examples taken from meta/esc50.csv.
ESC50_RAW="https://raw.githubusercontent.com/karolpiczak/ESC-50/master/audio"

# label -> ESC-50 source file (chosen for the matching class).
declare -A ESC50=(
  [dog]="1-100032-A-0.wav"            # class 0: dog
  [glass_break]="1-20133-A-39.wav"    # class 39: glass breaking
  [cough]="1-19111-A-24.wav"          # class 24: coughing
  [scream]="1-187207-A-20.wav"        # class 20: crying baby (distress stand-in)
  [thud]="1-101336-A-30.wav"          # class 30: door wood knock (fall/thud stand-in)
)

fetch_esc50() {
  local label="$1" src="$2" dest="${TMP_DIR}/${1}.src.wav"
  # Progress goes to stderr so the only thing on stdout is the path (or nothing).
  echo "[demo-clips] fetching ${label} <- ESC-50/${src}" >&2
  if curl -fsSL "${ESC50_RAW}/${src}" -o "${dest}"; then
    echo "${dest}"
  fi
}

# Convert any input to 16 kHz mono WAV, padded/looped to >= 5 s and trimmed <= 10 s.
# ESC-50 clips are 5 s already; this still normalises the format.
to_standard() {
  local in="$1" out="$2"
  ffmpeg -nostdin -y -loglevel error -i "${in}" \
    -ac 1 -ar 16000 -t 8 \
    -af "apad=whole_dur=6" \
    -c:a pcm_s16le "${out}"
}

# ---------------------------------------------------------------------------
# Generated clips (numpy if available, otherwise Python's wave/struct fallback).
# ---------------------------------------------------------------------------
gen_py() {
  # $1 = kind (smoke_alarm|speech|silence), $2 = output wav path
  python3 - "$1" "$2" <<'PY'
import math, struct, sys, wave

kind, out = sys.argv[1], sys.argv[2]
sr = 16000
dur = 6.0
n = int(sr * dur)

def write_wav(path, samples):
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = b"".join(struct.pack("<h", max(-32768, min(32767, int(s * 32767)))) for s in samples)
        w.writeframes(frames)

try:
    import numpy as np
    t = np.arange(n) / sr
    if kind == "smoke_alarm":
        # 3 kHz square wave, 0.5 s on / 0.5 s off pattern (classic alarm chirp).
        tone = np.sign(np.sin(2 * np.pi * 3000 * t))
        gate = ((t % 1.0) < 0.5).astype(float)
        sig = 0.6 * tone * gate
    elif kind == "speech":
        # Stacked formant-like sine tones with a slow amplitude wobble.
        sig = sum(0.2 * np.sin(2 * np.pi * f * t) for f in (180, 320, 700, 1100))
        sig *= 0.5 + 0.5 * np.sin(2 * np.pi * 3 * t)
    else:  # silence
        sig = np.zeros(n)
    samples = sig.tolist()
except ModuleNotFoundError:
    samples = []
    for i in range(n):
        ti = i / sr
        if kind == "smoke_alarm":
            tone = 1.0 if math.sin(2 * math.pi * 3000 * ti) >= 0 else -1.0
            gate = 1.0 if (ti % 1.0) < 0.5 else 0.0
            s = 0.6 * tone * gate
        elif kind == "speech":
            s = sum(0.2 * math.sin(2 * math.pi * f * ti) for f in (180, 320, 700, 1100))
            s *= 0.5 + 0.5 * math.sin(2 * math.pi * 3 * ti)
        else:
            s = 0.0
        samples.append(s)

write_wav(out, samples)
print(f"[demo-clips] generated {kind} -> {out}")
PY
}

# ---------------------------------------------------------------------------
# Build each clip. ESC-50 clips fall back to a generated tone if the download
# fails (offline / rate-limited), so the script always yields 8 files.
# ---------------------------------------------------------------------------
build_esc_or_fallback() {
  local label="$1" src="$2" fallback_kind="$3"
  local got
  got="$(fetch_esc50 "${label}" "${src}" || true)"
  if [ -n "${got}" ] && [ -s "${got}" ]; then
    to_standard "${got}" "${OUT_DIR}/${label}.wav"
  else
    echo "[demo-clips] WARN: could not fetch ${label}; generating a tone placeholder" >&2
    gen_py "${fallback_kind}" "${TMP_DIR}/${label}.gen.wav"
    to_standard "${TMP_DIR}/${label}.gen.wav" "${OUT_DIR}/${label}.wav"
  fi
}

build_esc_or_fallback "dog"         "${ESC50[dog]}"         "speech"
build_esc_or_fallback "glass_break" "${ESC50[glass_break]}" "smoke_alarm"
build_esc_or_fallback "cough"       "${ESC50[cough]}"       "speech"
build_esc_or_fallback "scream"      "${ESC50[scream]}"      "smoke_alarm"
build_esc_or_fallback "thud"        "${ESC50[thud]}"        "smoke_alarm"

# Fully generated clips.
gen_py "smoke_alarm" "${TMP_DIR}/smoke_alarm.gen.wav"
to_standard "${TMP_DIR}/smoke_alarm.gen.wav" "${OUT_DIR}/smoke_alarm.wav"

gen_py "speech" "${TMP_DIR}/speech.gen.wav"
to_standard "${TMP_DIR}/speech.gen.wav" "${OUT_DIR}/speech.wav"

gen_py "silence" "${TMP_DIR}/silence.gen.wav"
to_standard "${TMP_DIR}/silence.gen.wav" "${OUT_DIR}/silence.wav"

echo
echo "[demo-clips] wrote $(ls -1 "${OUT_DIR}"/*.wav | wc -l | tr -d ' ') clips to ${OUT_DIR}/:"
for f in "${OUT_DIR}"/*.wav; do
  # ffprobe is part of ffmpeg; report rate/channels/duration for verification.
  info="$(ffprobe -v error -show_entries stream=sample_rate,channels:format=duration \
          -of default=noprint_wrappers=1:nokey=1 "${f}" | tr '\n' ' ')"
  printf '  %-20s %s\n' "$(basename "${f}")" "${info}"
done

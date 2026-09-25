#!/usr/bin/env bash
# Make a seamless, loudness-matched mono FLAC loop for one scene.
#
#   make_audio_loop.sh <out.flac> <source-audio> [start_s] [length_s] [xfade_s]
#   make_audio_loop.sh <out.flac> brown          [length_s] [xfade_s]
#
# A source recording is cut to seg = [start, start+length+xfade). The loop is
# seg[xfade, end) with its final xfade seconds equal-power crossfaded into
# seg[0, xfade), so the loop's end flows straight back into its beginning.
# "brown" synthesizes brown noise instead (Space scene), looped the same way.
#
# Every loop is normalized to the same integrated loudness ($LUFS, default -30)
# so switching scenes never jumps in volume. Output: mono, 48 kHz, 16-bit FLAC
# (not Opus: its end padding leaves an audible click at the wrap).
set -euo pipefail

LUFS=${LUFS:--30}
out=$1; src=$2; shift 2

if [[ $src == brown ]]; then
  start=0; len=${1:-90}; xf=${2:-3}
  input=(-f lavfi -i "anoisesrc=color=brown:sample_rate=48000:amplitude=0.5:seed=7")
  # (brown noise has no source position, so start is always 0)
else
  start=${1:-0}; len=${2:-90}; xf=${3:-3}
  input=(-i "$src")
fi

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
seg=$(awk "BEGIN{print $len + $xf}")
# Filters (high-pass, loudness) run BEFORE the crossfade, with a pre-roll that
# is trimmed off afterwards, so their state is warmed up and identical at both
# ends of the loop. Filtering after the crossfade leaves a click at the wrap.
pre=$(awk "BEGIN{p = $start < 5 ? $start : 5; print p}")
[[ $src == brown ]] && pre=5
ss=$(awk "BEGIN{print $start - $pre}"); [[ $src == brown ]] && ss=0
dur=$(awk "BEGIN{print $seg + $pre}")

# 1. Cut, filter, normalize, and trim the pre-roll -> mono 48 kHz WAV segment.
ffmpeg -hide_banner -loglevel error -y -ss "$ss" -t "$dur" "${input[@]}" \
  -af "highpass=f=40,loudnorm=I=${LUFS}:TP=-3:LRA=11,aresample=48000,asetpts=N/SR/TB,atrim=start=${pre},asetpts=PTS-STARTPTS" \
  -ac 1 -ar 48000 -c:a pcm_s16le "$tmp/seg.wav"

# 2. Crossfade the tail into the head and encode.
graph="[0:a]atrim=start=${xf},asetpts=PTS-STARTPTS[body];\
[1:a]atrim=end=${xf},asetpts=PTS-STARTPTS[head];\
[body][head]acrossfade=d=${xf}:c1=qsin:c2=qsin[out]"
ffmpeg -hide_banner -loglevel error -y -i "$tmp/seg.wav" -i "$tmp/seg.wav" \
  -filter_complex "$graph" -map "[out]" -ac 1 -c:a flac -sample_fmt s16 "$out"

echo "$out: $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$out")s"

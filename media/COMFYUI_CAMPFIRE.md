# Campfire takes with Wan in ComfyUI (Peter's PC)

Veo refuses keyframes containing third-party characters ("Google's guardrails
related to third-party content"), so the campfire takes (Bluey, Frog and Toad)
are made locally with Wan's first-last-frame model. Everything stays on Peter's
PC and the Dell; nothing is uploaded.

Target PC: RTX 3060 12 GB, about 24 GB system RAM. That's enough for the 14B
model only as a GGUF quant with offloading, at 480p. Close other apps while it
runs.

## 1. Models (put them in the usual ComfyUI/models folders)
| What | File (or nearest equivalent) | Folder |
|---|---|---|
| Video model | Wan 2.1 **FLF2V 14B 720P**, GGUF **Q4_K_M** (about 10 GB). If it runs out of memory, use Q3_K_M | `models/unet` (or `models/diffusion_models`) |
| Text encoder | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `models/text_encoders` |
| CLIP vision | `clip_vision_h.safetensors` | `models/clip_vision` |
| VAE | `wan_2.1_vae.safetensors` | `models/vae` |

GGUF files load through the **ComfyUI-GGUF** custom node ("Unet Loader (GGUF)").
Install it from ComfyUI Manager if it's missing.

## 2. Workflow
1. In ComfyUI: Workflow → Browse Templates → Video → **"Wan 2.1 First-Last Frame to Video"**.
2. Replace the "Load Diffusion Model" node with **Unet Loader (GGUF)**, pointing at the Q4_K_M file, and connect it to the same input.
3. **Start image and end image: the same file**, `wan_input_832x464.png`. Copy it from the Dell at `~/TuesdayDreamMachine-media/campfire/wan_input_832x464.png`. It's the chosen campfire keyframe resized to 832x464. Pinning both ends to the same frame is what makes the take loop.
4. Settings (the `WanFirstLastFrameToVideo` node and the sampler):
   - width **832**, height **464**, length **81** frames (about 5 s at 16 fps)
   - steps 20–25, cfg 5–6, sampler `uni_pc` or `euler`, scheduler `simple`. Leave the template defaults if they differ.
   - seed: random. Change it for each take.
5. Positive prompt (the job's video prompt, verbatim):

   > The campfire flames flicker continuously and naturally; embers drift upward and fade at a steady, repeating rate. Tuesday and her companions stay mostly still with only tiny idle movements — a slight tail wag, an occasional blink — nothing that reads as a one-time gesture. Firelight held at constant intensity. Locked-off static camera: no camera movement, no zoom, no pan. Slow, continuous, cyclical, steady-state motion only — nothing that builds, changes pose, or tells a story. Lighting and color held constant throughout. The final frame returns exactly to the starting image so the clip loops seamlessly. No text, no captions, no audio.

6. Negative prompt: keep the template's default negative and add:
   `camera movement, zoom, pan, cuts, scene change, lighting change, new characters, text, subtitles, morphing faces, extra limbs`
7. Output: the template's Save Video / Save Animated WEBP node. Prefer **MP4 (h264)** if the node offers it, otherwise WEBP is fine.

Expect roughly 20–40+ minutes per take on a 3060. This is an estimate, not measured.
Optional speed-up: a Wan 2.1 step-distill LoRA (e.g. lightx2v) with about 4–8
steps and cfg 1. It's much faster but can soften the painterly detail, so try
one take without it first to compare.

## 3. What to make
- Start with **1 take** and send it over for a check (face stability, whether Bluey and Frog and Toad stay on-model, the seam).
- If it's good, make **3–4 takes** with different seeds (Wan takes are about 5 s, so more takes gives about the same total length as the other scenes).
- Copy them to the Dell as `~/TuesdayDreamMachine-media/campfire/wan_take_<n>.mp4`.

## 4. Back on the Dell
`build_loop.py` conforms any input to 1280x720 at 24 fps, finds the best cut
frame near each take's end (`--tail-search`), checks every seam's SSIM, and
encodes:
```
python3 media/tools/build_loop.py campfire ~/TuesdayDreamMachine-media/campfire/wan_take_1.mp4 … --out-dir ~/TuesdayDreamMachine-media/content
```
Wan renders at 16 fps, so the 24 fps conform repeats frames. For near-still
motion that's usually invisible, but if the fire looks steppy, frame
interpolation (RIFE in ComfyUI) to 24 or 32 fps before copying is the fix.

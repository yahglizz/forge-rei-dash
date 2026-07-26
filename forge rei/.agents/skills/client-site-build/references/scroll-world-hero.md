# Scroll-world hero — the camera flight

A hero where scroll drives a camera through a world. The visitor scrolls, a
pre-rendered video scrubs, and the camera appears to fly continuously from scene
to scene. Apple's product pages use the technique.

This is the expensive hero. Read the whole file before generating anything — the
mistakes here cost real credits to undo.

## Contents

- [Credit math — before you generate](#credit-math--before-you-generate)
- [Architecture: pick one](#architecture-pick-one)
- [The seam rule](#the-seam-rule-this-is-the-whole-game)
- [Generating with Higgsfield MCP](#generating-with-higgsfield-mcp)
- [Encoding for scrub](#encoding-for-scrub)
- [Wiring the engine](#wiring-the-engine)
- [The phase bug](#the-phase-bug-copy-must-match-the-camera)
- [Frame locks](#frame-locks-so-nobody-misses-a-card)

---

## Credit math — before you generate

State the estimate to the operator and wait for a yes. This is their money.

| Item | Rough cost |
|---|---|
| Scene still (`gpt_image_2`, 16:9, 2k, quality high) | ~7 credits |
| Video leg (`seedance_2_0`, 1080p, 4s, no audio) | ~36 credits |
| Video leg (5s) | ~45 credits |

A five-scene world is `5 stills + 5 legs` ≈ **215 credits**, plus re-roll
headroom. Check the balance first (`balance`), and warn if the estimate exceeds
~70% of it.

**De-risk cheaply.** Render **one** leg before committing to the set. It proves
the art direction survives video encoding and surfaces any divergence at 36
credits instead of 200. On the ClientForge build this caught the model inventing
a completely different world on leg 1 — cheap to learn, expensive to discover at
the end.

`generate_audio: false` always. Nobody hears a scrubbed video, and audio costs
extra.

---

## Architecture: pick one

### A — Continuous forward take (default)

One camera that only ever moves forward. Leg 1 starts at the opening still; each
subsequent leg starts from the **previous leg's actual last frame**. No connector
clips — the legs *are* the journey. Set `connectors: []`.

Use this for anything grounded or walkthrough-like. It cannot produce the rewind
stutter that architecture B risks, and it is simpler.

### B — Dive + aerial connector

A dive into each scene, then a connector that pulls up and flies to the next.
The pull-out **reverses camera direction at every seam**. In a miniature/diorama
world that reads as "zoom out to the map, fly to the next island". In a grounded
world it reads as a jarring rewind.

**When in doubt, use A.**

---

## The seam rule (this is the whole game)

Where two clips meet, the last frame of one and the first frame of the next must
be **the same frame**. Anything else is a visible pop.

Measure it — don't eyeball it. Extract the boundary frames and compute mean
absolute pixel difference:

```bash
ffmpeg -v error -y -sseof -0.05 -i legN.mp4   -vframes 1 /tmp/a.png   # last frame
ffmpeg -v error -y -i legN1.mp4 -vf "select=eq(n\,0)" -vframes 1 /tmp/b.png  # first frame
```

```python
from PIL import Image, ImageChops
a = Image.open('/tmp/a.png').convert('RGB')
b = Image.open('/tmp/b.png').convert('RGB').resize(a.size)
d = ImageChops.difference(a, b).convert('L')
mean = sum(i * c for i, c in enumerate(d.histogram())) / (a.size[0] * a.size[1])
print(mean)
```

Read it as: **under ~12 is continuous, ~25 is borderline, 50+ is a visible pop.**

To fix a bad seam: extract the previous leg's actual last frame, upload it, and
re-render the next leg with it pinned as `start_image`. On ClientForge this took
a seam from 50.8 to 25.8 and improved the *following* seam as a side effect
(11.8 → 3.8), because the whole chain re-aligned.

**Posters must be the clip's FIRST frame, not the destination artwork.** A leg
flies *into* its scene, so the scene art is where the clip *ends*. Using it as
the poster means the page paints the arrival, then snaps backwards the moment
the video decodes. Measured on ClientForge: posters differed from their own
clip's frame 0 by 48–75. After fixing, 1.4–3.6 (quantization noise only).

---

## Generating with Higgsfield MCP

Stills — `generate_image`:
- Model `gpt_image_2`, `aspect_ratio: "16:9"`, `resolution: "2k"`, `quality: "high"`
- **One style preamble, byte-identical across every scene.** This is what makes
  the world cohere. Vary only the subject sentence.
- A previous generation's job UUID can be passed as a style reference to lock
  the look.

Videos — `generate_video`:
- Model `seedance_2_0`, `mode: "std"` (**required** for 1080p), `generate_audio: false`
- `start_image` pins where the leg begins; `end_image` pins where it lands
- Roles are passed as `medias` entries

Uploading a local frame: `media_upload` → PUT the bytes to the returned presigned
URL → `media_confirm`. That's the path for pinning an extracted frame as a
`start_image`.

**Preset interception.** Prompts get matched to Higgsfield presets ("3D RENDER",
"IN THE DARK", "Earth zoom out") which silently override your direction.
`declined_preset_id` only declines one at a time and they alternate. The reliable
fix is rewording around the trigger words — say "cream and gold, bright daylight"
instead of naming a lighting style, and avoid phrases like "never become a 3D
render" which match the very preset you're refusing.

**Parallelize when legs are independent.** If both endpoints of every leg are
fixed images, the legs have no dependency on each other and can render
concurrently — same credits, much less waiting. Only architecture A's
frame-chained legs must run sequentially.

---

## Encoding for scrub

Scrubbing seeks constantly, so the encode needs dense keyframes:

```bash
ffmpeg -i in.mp4 -c:v libx264 -crf 20 \
  -g 8 -keyint_min 8 -sc_threshold 0 \
  -vf "unsharp=5:5:0.8:5:5:0.0" \
  -an -movflags +faststart out.mp4
```

`-g 8` is the important one — a keyframe every 8 frames means a seek lands
almost immediately. `-an` drops audio. `+faststart` puts the index at the front.

**Load clips as blobs, not plain `src`.** Hosts that don't serve HTTP byte ranges
pin `video.seekable` to `[0, 0]` and scrubbing silently does nothing. Fetching
the file and using `URL.createObjectURL` makes it always seekable. Verify with
`video.seekable.end(0)` — it should be the clip duration, not 0.

Pixel art specifically: quantize stills to PNG-8 (`quantize(colors=160,
method=MEDIANCUT, dither=NONE)`) rather than JPEG, which mushes hard edges. Use
`image-rendering: pixelated` so upscaling stays crisp.

---

## Wiring the engine

`assets/scrub-engine.js` is a vetted, dependency-free engine. It builds its own
DOM and injects its own CSS in `@layer sw`, so a plain page-level `.sw-root`
block overrides its tokens without specificity fights.

Mount it **outside React**. It owns its DOM and React reconciling those nodes
underneath it fights the scrub loop.

Per-section config: `still`, `clip`, `scroll` (dwell length in viewport heights),
`linger`, plus the copy fields.

### Two traps in the engine's stock theme

**Hardcoded white scrims.** Nav, route labels and tag pills use
`color-mix(#fff …)`, which does not follow `--sw-bg`. On a dark theme they must
be overridden explicitly or they glow white.

**Never put opacity on the container.** Every layer is `position: fixed`, and an
opacity below 1 on their ancestor makes it a containing block for fixed
descendants — every layer jumps out of place mid-fade. Fade the individual
layers instead; their children are absolutely positioned, so it's safe.

### The world must exit

The layers are fixed, so without intervention the hero stays pinned over every
section below it forever. Dissolve it across the track's trailing viewport
height: the last frame is already reached when that stretch begins, and the page
below has fully arrived when it ends. Set `visibility: hidden` and
`pointer-events: none` at the end so the hero can't swallow clicks meant for the
content underneath.

---

## The phase bug — copy must match the camera

In architecture A, a leg flies *into* its scene, so the scene is only fully
framed at the **end** of its segment. Engines commonly peak the section copy at
the segment's **middle** (correct for architecture B, where the dive lands you
mid-way).

Get this wrong and the card is at zero opacity exactly when the district fills
the screen — the visitor sees a beautiful scene and no explanation of it.

Phase the copy to **arrival**: rise through the approach, full at the end of the
segment, hold briefly across the seam (the next leg opens on the same frame),
then clear before the next card rises. Verify by simulating the curve and
checking opacity is 1.0 at each segment end, and that no two cards are up at once.

The same applies to nav clicks — `jumpTo` should target the segment **end**, not
its middle, or every nav click lands on the approach before the card has risen.

---

## Frame locks — so nobody misses a card

A fast flick sails straight past a scene's arrival window and the visitor never
sees that service at all. Park a snap anchor at each arrival:

```css
html { scroll-snap-type: y proximity; }
.lock { position: absolute; width: 1px; height: 1px; pointer-events: none;
        scroll-snap-align: start; scroll-snap-stop: always; }
```

Anchor offsets in **vh units** (a segment of `scroll: 1.5` sits at `150vh`), so a
resize keeps them correct with no JS recalculation.

`proximity`, not `mandatory` — a deliberate scroll still passes through freely
and the flight never becomes a trap. `scroll-snap-stop: always` prevents one
fling from leaping a whole scene. Disable snapping entirely under
`prefers-reduced-motion`: being pulled around the page is exactly what that
setting asks you not to do.

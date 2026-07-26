# Verification

Two jobs here. One: a checklist of what to check before a client site goes live.
Two: an honest account of what your tools **cannot** see, so you don't chase bugs
that don't exist or claim checks you didn't run.

## Contents

- [Pre-ship checklist](#pre-ship-checklist)
- [What automated browsers cannot see](#what-automated-browsers-cannot-see)
- [Reporting honestly](#reporting-honestly)

---

## Pre-ship checklist

### Email — the one that silently loses money

```bash
dig +short MX <domain-in-every-contact-address>
```

No MX means that address cannot receive mail. Then submit through every inquiry
path and confirm arrival with a human. Detail in `forms-and-payments.md`.

### Everything parses

```bash
node --check app/world.js                    # plain JS
node -e "require('@babel/core').transformFileSync('app/x.jsx',{presets:['@babel/preset-react']})"
python3 -c "import json; json.load(open('vercel.json'))"
```

Cheap, and catches the class of error that white-screens a page.

### Compiled output is current

```bash
npm run verify
```

Confirm the guard actually fails when output is stale — corrupt a build file
deliberately once and watch it catch. A guard nobody has seen fail is decoration.

### Assets resolve

Every referenced image, video and font, over HTTP, expecting 200. A path that
works locally and 404s in production is usually a case-sensitivity difference or
a space in a directory name needing `%20`.

### Payload

- No in-browser compiler
- `react.production.min.js`, not development
- Integrity hashes on every CDN script
- Media cached long, code revalidating

### Live, after deploy

Poll the live URL for a symbol only the new build contains, always with a
cache-buster. Then re-run the email test **against production** — the live form
and the local form are not the same form.

---

## What automated browsers cannot see

Misreading these sends you fixing imaginary bugs. All three were hit during the
ClientForge build.

### A hidden pane runs zero animation frames

`requestAnimationFrame` does not fire when the page is hidden or backgrounded.
Anything rAF-driven — scroll-scrub engines, most JS animation libraries, framer's
`animate` — does not advance. Elements sit frozen at their initial state, which
looks exactly like a broken animation.

Check before concluding anything:

```js
new Promise(res => {
  let frames = 0;
  const tick = () => { frames++; requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  setTimeout(() => res({ frames, hidden: document.hidden }), 800);
})
```

`frames: 0, hidden: true` means the test was inconclusive, not that the feature
is broken. This also means **`AnimatePresence` exit animations never complete**,
so tab-switching UIs won't change tabs in a hidden pane. Verify the underlying
data instead.

### Screenshots often don't composite video

A blank capture where a video should be is usually a capture limitation, not a
blank page. Confirm the video is really decoding by drawing it to a canvas and
sampling:

```js
const c = document.createElement('canvas'); c.width = 160; c.height = 90;
c.getContext('2d').drawImage(video, 0, 0, 160, 90);
const d = c.getContext('2d').getImageData(0, 0, 160, 90).data;
let sum = 0; for (let i = 0; i < d.length; i += 4) sum += (d[i] + d[i+1] + d[i+2]) / 3;
sum / (160 * 90);   // a real frame is not 0
```

### Programmatic scroll then screenshot captures the top

Setting `scrollY` and screenshotting frequently returns the initial viewport or
blank. Verify scrolled state by **reading the DOM** — element rects, computed
opacity, which section is active — rather than looking at a picture.

### Caches lie

Both the browser and the CDN will serve stale files and make you think a change
didn't deploy. In-page, force revalidation before reloading:

```js
await fetch('app/build/app.js', { cache: 'reload' });
location.reload();
```

From the shell, always append a cache-buster: `?cb=$RANDOM`.

---

## Reporting honestly

The point of knowing the limits is to describe results accurately.

**Say what you verified and how.** "Seam continuity measured at 3.8 mean absolute
difference" is a fact. "Seams look great" is not.

**Say plainly what you could not check.** "The scrub math is verified; whether it
*feels* smooth needs your eyes — the pane can't run the animation loop." That
sentence is more useful than false confidence, and it tells the operator exactly
what to look at.

**When a check contradicts your expectation, find out which is wrong before
acting.** The flat-opacity reading that looked like a broken gallery was a
throttled pane; the fix would have been a change to working code. One diagnostic
before one edit.

**Never imply a check you skipped.** If the email test wasn't confirmed by a
human, the site is not verified — regardless of what the API returned.

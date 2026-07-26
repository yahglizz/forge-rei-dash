# The buildless React stack

Static React over UMD, Tailwind from CDN, no bundler. The JSX is precompiled
before shipping.

The point: a site that is a folder of files. It hosts anywhere, it's debuggable
by viewing source, there's no toolchain to rot, and a client can be handed it
without explaining webpack. The one thing that must not be skipped is the
precompile.

## Contents

- [Layout](#layout)
- [Global scope — the collision rules](#global-scope--the-collision-rules)
- [Precompiling](#precompiling-non-negotiable)
- [Production React](#production-react)
- [Theming from the artwork](#theming-from-the-artwork)
- [Animation that can't strand content](#animation-that-cant-strand-content)
- [Deploying to Vercel](#deploying-to-vercel)

---

## Layout

```
site/
├── index.html          script tags, Tailwind config, fonts
├── styles.css          theme variables + everything Tailwind can't express
├── app/
│   ├── *.jsx           sources — edited, never shipped
│   └── build/*.js      compiled — shipped, never edited
├── assets/
├── package.json        babel devDeps + build script
└── vercel.json         static deploy config
```

---

## Global scope — the collision rules

Every `.jsx` shares **one global scope**. There are no modules. Components become
globals via `Object.assign(window, { Thing })` and are consumed by later scripts.
This is what makes the stack work without a bundler, and it has sharp edges:

- **Unique hook aliases per file.** `const { useState: useStateW } = React;` in
  work.jsx, `useStateCo` in checkout.jsx, and so on. Two files both declaring
  `const { useState }` at top level is a redeclaration error that white-screens
  the page.
- **Unique top-level names, prefixed by file.** A second `const PLANS` anywhere
  kills the page.
- **No computed JSX tags.** `<Icons[x] />` doesn't compile. Resolve first:
  `const Ico = Icons[x] || Icons.Bot;` then `<Ico />`. Member expressions like
  `<tab.icon />` are fine.

Script order in `index.html` follows the dependency order: icons → primitives →
sections → the root app last. Because everything is a top-level function
declaration, all scripts have evaluated before React renders, so cross-file
references resolve regardless of order — but keeping order sane helps humans.

---

## Precompiling (non-negotiable)

`@babel/standalone` is **3.1 MB**, and shipping it means every visitor downloads
a compiler and runs it before seeing anything. Compile ahead of time:

```json
{
  "scripts": {
    "build": "babel app --out-dir app/build --extensions .jsx --presets @babel/preset-react",
    "watch": "npm run build -- --watch",
    "verify": "npm run build -- --out-dir /tmp/build-check >/dev/null && diff -r -x README.md app/build /tmp/build-check && echo 'IN SYNC'"
  },
  "devDependencies": {
    "@babel/cli": "^7.24.0",
    "@babel/core": "^7.24.0",
    "@babel/preset-react": "^7.24.0"
  }
}
```

`preset-react` only — **no module transform**. That keeps the output as plain
global scripts, preserving the window-global component pattern. Confirm after the
first build: the output should contain no `export`, no `require(`, no
`Object.defineProperty(exports`.

**The hazard is staleness.** Compiled output is committed (the host serves the
repo statically), so editing a `.jsx` and forgetting to build ships old code
silently. `npm run verify` rebuilds to a temp dir and diffs. Test that the guard
works by deliberately corrupting a build file and confirming it fails — a guard
you haven't seen fail is not a guard.

Put a `README.md` in `app/build/` saying the files are generated. That's where
someone will actually be when they're about to edit one.

---

## Production React

Development builds carry warning machinery nothing needs at runtime and are
roughly 8× larger.

```html
<script src="https://unpkg.com/react@18.3.1/umd/react.production.min.js"
        integrity="sha384-..." crossorigin="anonymous"></script>
<script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js"
        integrity="sha384-..." crossorigin="anonymous"></script>
```

Compute real integrity hashes; don't copy them from elsewhere:

```bash
curl -sL <url> | openssl dgst -sha384 -binary | openssl base64 -A
```

Every CDN script gets one. An unpinned third-party script is an open door into
the client's site.

Verify production React actually loaded:
`React.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED?.ReactDebugCurrentFrame`
is `undefined` in production builds and defined in development ones.

---

## Theming from the artwork

Sample the palette from the hero art and drive everything from it:

```css
:root { --void:#1B2836; --surface:#223546; --ink:#E1E0CC; --gold:#E3B65C; }
```

Retheme an existing Tailwind-classed page with blanket rules rather than editing
every component:

```css
.bg-black { background-color: var(--void) !important; }   /* ~40 usages, one rule */
[class*="rounded"] { border-radius: 2px !important; }      /* squares a whole UI */
```

Alias a Tailwind font family to the new face and every existing `font-serif`
usage picks it up for free. This is how a full retheme lands in one file instead
of eight.

For a pixel/retro direction specifically: hard offset shadows instead of blurs,
`steps()` easing so motion quantizes like the art, `image-rendering: pixelated`,
and a very low-alpha 1-in-3px scanline comb. And drop synthesized italics —
pixel faces have no true italic and the oblique looks broken.

---

## Animation that can't strand content

Two failure modes that both end with **invisible content**:

**`whileInView` on horizontally scrolled items.** An item parked off the right of
a scroll row never intersects the viewport, so it never animates in and sits at
`opacity: 0` forever. Use an entrance that always runs.

**Any entrance whose END state comes from the animation.** If the animation never
completes — rAF not running, tab backgrounded, motion library failing to load —
the element stays at its `from` state. Prefer CSS with `animation-fill-mode:
backwards`, so the end state comes from the element's own styles:

```css
.tile {
  opacity: 1;                                  /* the resting truth */
  animation: tile-in 420ms steps(6, end) backwards;
  animation-delay: var(--d, 0ms);
}
```

Verify by removing the animation and confirming everything still resolves to
`opacity: 1`. Content must never depend on an animation completing to be seen.

---

## Deploying to Vercel

**Adding `package.json` flips Vercel into its Node build pipeline**, which then
fails with `STATIC_BUILD_NO_OUT_DIR` looking for a `public/` directory that
doesn't exist. Since the compiled output is committed, the deploy needs neither
an install nor a build:

```json
{
  "outputDirectory": ".",
  "installCommand": "echo 'no install needed'",
  "buildCommand": "echo 'static site'",
  "cleanUrls": true,
  "headers": [
    { "source": "/assets/(.*)",
      "headers": [{ "key": "Cache-Control", "value": "public, max-age=31536000, immutable" }] },
    { "source": "/app/build/(.*)",
      "headers": [{ "key": "Cache-Control", "value": "public, max-age=0, must-revalidate" }] }
  ]
}
```

Media caches for a year; compiled JS must revalidate so a fresh deploy is picked
up immediately.

A failed build keeps the previous deployment serving — a safe failure mode, but
it also means **a successful push and a live site can be different builds**.
After pushing, poll the live URL for something only the new build contains:

```bash
until curl -s "https://<domain>/app/build/app.js?cb=$RANDOM" | grep -q "<new symbol>"; do sleep 6; done
```

Always cache-bust when checking; the CDN will happily serve you the old file and
make you think the deploy failed.

Large media in git is fine but slows pushes — retry the push in a loop and
confirm by comparing `git rev-parse main` against `git ls-remote origin main`
rather than trusting the command's output.

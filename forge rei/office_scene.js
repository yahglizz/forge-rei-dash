// The 3D Agent Office. Three.js is lazy-loaded only when the Office page opens.
// Everything that moves is driven by real signals from /api/office/state: agent activity,
// Orion's approved assignments (agent bus) and Orion's check-ins. Nothing is random or demo.
import * as THREE from 'three';
import { GLTFLoader } from './assets/vendor/three/loaders/GLTFLoader.js';

const VERDICT = { working: '#60a5fa', on_track: '#22c55e', waiting: '#f59e0b', idle: '#64748b', attention: '#ef4444', blocked: '#f97316' };
const VERDICT_LABEL = { working: 'WORKING', on_track: 'ON TRACK', waiting: 'WAITING', idle: 'IDLE', attention: 'NEEDS ATTENTION', blocked: 'BLOCKED' };
const ACTIVITY = { error: '#ef4444', queued: '#f59e0b', think: '#60a5fa', read: '#2dd4bf', report: '#a78bfa', done: '#22c55e', reporting: '#22c55e', walk: '#9fb0c7', unknown: '#475569' };
const BUSY = ['walk', 'read', 'think', 'report'];
const DOGS = ['marcus', 'dyson', 'solomon', 'midas'];
const DWELL = 4200;          // ms Orion stays with an agent during a check-in
const ROUND_EVERY = 14000;   // ms between Orion's rounds while someone is working
const played = { checkin: '', messages: new Set() };   // survives a remount: a replay is never a new event

export async function createOfficeScene(host, getState, onSelect, onStatus) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#101a2a');
  const camera = new THREE.PerspectiveCamera(39, 1, .1, 100);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  host.appendChild(renderer.domElement);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x64748b, 2.3));
  const light = new THREE.DirectionalLight(0xffeed9, 3);
  light.position.set(4, 12, 8); light.castShadow = true; scene.add(light);
  let disposed = false, raf, previous = 0, mixer, currentClip = '', currentAction;
  const assets = new Set(), actors = new Map(), actions = {}, zones = new Map(), loader = new GLTFLoader();
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

  function release(root) {
    root.traverse(o => {
      if (o.geometry) o.geometry.dispose();
      (Array.isArray(o.material) ? o.material : o.material ? [o.material] : []).forEach(m => {
        Object.values(m).forEach(v => { if (v && v.isTexture) v.dispose(); }); m.dispose();
      });
    });
  }
  function box(w, h, d, color, x, y, z, parent = scene) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), new THREE.MeshStandardMaterial({ color, roughness: .8 }));
    mesh.position.set(x, y, z); mesh.castShadow = true; mesh.receiveShadow = true; parent.add(mesh); return mesh;
  }
  function label(text, x, y, z, color = '#e2e8f0', width = 2.3) {
    const cv = document.createElement('canvas'); cv.width = 512; cv.height = 96;
    const c = cv.getContext('2d'); c.fillStyle = color; c.font = '600 32px system-ui'; c.textAlign = 'center'; c.fillText(text, 256, 58);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(cv), depthTest: false }));
    sprite.position.set(x, y, z); sprite.scale.set(width, width * 96 / 512, 1); scene.add(sprite); return sprite;
  }

  // ── speech bubbles: a canvas sprite repainted only when its text changes ──────────
  function wrap(c, text, maxWidth, maxLines) {
    const lines = []; let line = '';
    for (const word of String(text).split(/\s+/)) {
      const next = line ? line + ' ' + word : word;
      if (c.measureText(next).width > maxWidth && line) { lines.push(line); line = word; } else line = next;
    }
    if (line) lines.push(line);
    if (lines.length > maxLines) { lines.length = maxLines; lines[maxLines - 1] = lines[maxLines - 1].replace(/\s*\S*$/, '') + '…'; }
    return lines;
  }
  function makeBubble(width) {
    const cv = document.createElement('canvas'); cv.width = 512; cv.height = 176;
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(cv), depthTest: false, transparent: true }));
    sprite.renderOrder = 10; sprite.visible = false;
    sprite.scale.set(width, width * 176 / 512, 1); sprite.userData = { cv, key: '', width }; scene.add(sprite); return sprite;
  }
  function paint(sprite, text, accent) {
    const key = accent + '|' + text;
    if (sprite.userData.key === key) return;
    sprite.userData.key = key;
    const cv = sprite.userData.cv, c = cv.getContext('2d');
    c.clearRect(0, 0, cv.width, cv.height); c.font = '600 26px system-ui, sans-serif';
    const lines = wrap(c, text, 440, 3), h = 28 + lines.length * 33, top = cv.height - 18 - h;
    c.fillStyle = 'rgba(9,16,30,.94)'; c.strokeStyle = accent; c.lineWidth = 4;
    c.beginPath(); c.roundRect(12, top, 488, h, 20); c.fill(); c.stroke();
    c.beginPath(); c.moveTo(236, top + h); c.lineTo(256, cv.height - 3); c.lineTo(276, top + h); c.closePath(); c.fill();
    c.fillStyle = '#eaf2ff'; c.textAlign = 'left';
    lines.forEach((l, i) => c.fillText(l, 32, top + 40 + i * 33));
    sprite.material.map.needsUpdate = true;
  }
  function say(sprite, text, accent, x, bottom, z) {
    if (!text) { sprite.visible = false; return; }
    paint(sprite, text, accent); sprite.visible = true;
    sprite.position.set(x, bottom + sprite.scale.y / 2, z);
  }

  // ── room ─────────────────────────────────────────────────────────────────────────
  box(15, .2, 10, '#d2c7b4', 0, -.15, 0);
  box(15, 2.7, .15, '#d9dfe7', 0, 1.25, -5);
  box(.15, 2.7, 10, '#bbc9d7', -7.5, 1.25, 0);
  box(4.4, 1.2, .07, '#18334b', 0, 1.7, -4.87);
  label('FORGE / COMMAND OFFICE', 0, 2.3, -4.7, '#d6eee9', 5);
  const plant = new THREE.Mesh(new THREE.ConeGeometry(.5, 1.2, 8), new THREE.MeshStandardMaterial({ color: '#367e69' }));
  plant.position.set(6.5, .8, -4.1); scene.add(plant); box(.7, .4, .7, '#ad7958', 6.5, .1, -4.1);
  const orion = new THREE.Group(); orion.position.set(0, 0, 2.2); scene.add(orion);
  const home = new THREE.Vector3(0, 0, 2.2);
  const orionLabel = label('ORION · CEO', 0, 2.85, 2.2, '#a7f3d0', 2.2);
  const orionBubble = makeBubble(4.3);
  const ring = new THREE.Mesh(new THREE.TorusGeometry(.65, .035, 8, 48), new THREE.MeshBasicMaterial({ color: '#5eead4' }));
  ring.rotation.x = Math.PI / 2; ring.position.y = .02; orion.add(ring);
  function desk(x, z, color) {
    const furniture = new THREE.Group(); scene.add(furniture);
    box(1.85, .12, .85, '#946f54', x, .92, z, furniture);
    [-.75, .75].forEach(dx => box(.09, .85, .65, '#394554', x + dx, .45, z, furniture));
    box(.75, .48, .08, '#182336', x, 1.25, z - .22, furniture);
    const screen = box(.64, .35, .02, color, x, 1.26, z - .17, furniture);
    box(.55, .035, .2, '#35465c', x, 1.01, z + .15, furniture); return { screen, furniture };
  }
  const deptPos = { rei: [-5, -2.2], agency: [3, -2.2], daycare: [5, 2.1], dropship: [-5, 2.1] };

  // A coloured rug + sign per active department so the floor reads as four businesses.
  function syncZone(dept) {
    const n = (dept.agents || []).length, base = deptPos[dept.id] || [0, -2];
    let z = zones.get(dept.id);
    if (!z) {
      const rug = box(1, .03, 3.6, dept.accent, 0, .0, 0); rug.material.transparent = true; rug.material.opacity = .22; rug.castShadow = false;
      z = { rug, sign: label(dept.label.toUpperCase(), 0, .04, 0, dept.accent, 3.6), n: 0 };
      z.sign.material.depthTest = true; zones.set(dept.id, z);
    }
    z.n = n; z.rug.visible = z.sign.visible = true;
    const width = Math.max(2.6, n * 2.1 + .6), cx = base[0] + (n - 1) * 1.05;
    z.rug.scale.x = width; z.rug.position.set(cx, .01, base[1] + .7);
    z.sign.position.set(cx, 2.05, base[1] - .6); z.sign.scale.set(3.6, 3.6 * 96 / 512, 1);
  }

  function makeActor(a, dept, i, base) {
    const group = new THREE.Group(), x = base[0] + i * 2.1, z = base[1];
    group.position.set(x, 0, z + .95); scene.add(group);
    const body = new THREE.Mesh(new THREE.CapsuleGeometry(.22, .42, 4, 10), new THREE.MeshStandardMaterial({ color: dept.accent }));
    body.position.y = .8; group.add(body);
    const head = new THREE.Mesh(new THREE.SphereGeometry(.24, 12, 12), new THREE.MeshStandardMaterial({ color: '#c7936c' }));
    head.position.y = 1.4; group.add(head);
    [-.15, .15].forEach(dx => box(.15, .45, .17, '#253247', dx, .23, 0, group));
    const arms = [-.35, .35].map(dx => box(.13, .42, .14, dept.accent, dx, .8, 0, group));
    const badge = label(a.name.toUpperCase(), x, 1.95, z + .95, '#e2e8f0', 1.8);
    const { screen, furniture } = desk(x, z, dept.accent);
    const pad = new THREE.Mesh(new THREE.TorusGeometry(.62, .03, 8, 40), new THREE.MeshBasicMaterial({ color: '#64748b' }));
    pad.rotation.x = Math.PI / 2; pad.position.set(x, .03, z + .95); scene.add(pad);
    return { group, badge, screen, furniture, pad, arms, bubble: makeBubble(3.5), x, z, agent: a, override: null, bodyTop: 1.75, headBase: head, bodyCap: body };
  }
  function syncActors(state) {
    const alive = new Set(), liveDepts = new Set();
    (state.departments || []).forEach(dept => {
      const base = deptPos[dept.id] || [0, -2]; liveDepts.add(dept.id); syncZone(dept);
      (dept.agents || []).forEach((a, i) => {
        alive.add(a.id);
        if (!actors.has(a.id)) {
          const actor = makeActor(a, dept, i, base); actors.set(a.id, actor);
          if (DOGS.includes(a.id)) loadDog(a.id, actor);
        }
        actors.get(a.id).agent = a;
      });
    });
    zones.forEach((z, id) => { z.rug.visible = z.sign.visible = liveDepts.has(id); });
    actors.forEach((actor, id) => {
      const visible = alive.has(id); actor.group.visible = visible; actor.badge.visible = visible;
      actor.furniture.visible = visible; actor.pad.visible = visible; if (!visible) actor.bubble.visible = false;
    });
  }

  // ── camera: drag to orbit, wheel to zoom; "focus" follows the selected agent ─────
  const orbit = { az: Math.atan2(11, 16), el: Math.asin(11 / Math.hypot(11, 11, 16)), r: Math.hypot(11, 11, 16) };
  const camPos = new THREE.Vector3(), camLook = new THREE.Vector3(0, .8, 0);
  let camReady = false, drag = null;
  const ray = new THREE.Raycaster(), pointer = new THREE.Vector2();
  function pick(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
    ray.setFromCamera(pointer, camera);
    if (ray.intersectObject(orion, true).length) { onSelect('orion'); return; }
    for (const [id, a] of actors) if (a.group.visible && ray.intersectObject(a.group, true).length) { onSelect(id); return; }
  }
  const el = renderer.domElement;
  const down = e => { drag = { x: e.clientX, y: e.clientY, moved: 0 }; el.setPointerCapture?.(e.pointerId); };
  const move = e => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y; drag.x = e.clientX; drag.y = e.clientY; drag.moved += Math.abs(dx) + Math.abs(dy);
    if (drag.moved > 5) { orbit.az -= dx * .006; orbit.el = Math.min(1.35, Math.max(.25, orbit.el + dy * .005)); }
  };
  const up = e => { if (drag && drag.moved <= 5) pick(e); drag = null; };
  const wheel = e => { e.preventDefault(); orbit.r = Math.min(30, Math.max(7, orbit.r * (1 + Math.sign(e.deltaY) * .08))); };
  el.addEventListener('pointerdown', down); el.addEventListener('pointermove', move); el.addEventListener('pointerup', up);
  el.addEventListener('pointercancel', () => { drag = null; }); el.addEventListener('wheel', wheel, { passive: false });
  el.style.touchAction = 'pan-y';
  el.setAttribute('aria-label', '3D office showing Orion and the live agent desks. Drag to rotate, scroll to zoom. Use the agent buttons below to select with a keyboard.');
  const observer = new ResizeObserver(() => {
    const w = Math.max(host.clientWidth, 1), h = Math.max(host.clientHeight, 1);
    renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
  }); observer.observe(host);

  function clip(name) {
    if (name === currentClip || !actions[name]) return;
    if (currentAction) currentAction.fadeOut(.25);
    currentAction = actions[name]; currentAction.reset().fadeIn(.25).play(); currentClip = name;
  }

  // ── Orion's director: one step at a time, always from a real event ──────────────
  // step = { id, to, text, accent, until }  — `to` is an agent id; Orion walks there and
  // talks for DWELL ms. Sources, in priority order: a check-in round, an owner-approved
  // assignment, then his own rounds past whoever is actually working.
  const queue = []; let step = null, lastRound = 0, roundIndex = 0;
  function feed(state, t) {
    const age = ts => (state.now || Date.now()) - ts;
    const ck = state.checkin;
    if (ck && ck.id !== played.checkin) {
      const fresh = age(ck.ts) < 120000; played.checkin = ck.id;
      if (fresh) (ck.reviews || []).forEach(r => { if (actors.has(r.agentId)) queue.push({ id: ck.id + r.agentId, to: r.agentId, verdict: r.verdict, text: r.name + ': ' + r.text, accent: VERDICT[r.verdict] || '#94a3b8' }); });
      if (fresh && ck.reviews && ck.reviews.length > 1) queue.push({ id: ck.id + 'sum', to: '', text: ck.summary, accent: '#5eead4' });
    }
    (state.messages || []).forEach(m => {
      if (m.from !== 'orion' || m.kind !== 'task' || !actors.has(m.to) || played.messages.has(m.id)) return;
      played.messages.add(m.id);
      if (age(m.ts) < 30000) queue.unshift({ id: m.id, to: m.to, verdict: '', text: (m.text || 'New assignment').replace(/^Owner-approved assignment:\s*/, 'New task: '), accent: '#2dd4bf' });
    });
    if (!step && !queue.length && t - lastRound > ROUND_EVERY) {
      const busy = [...actors.values()].filter(a => a.group.visible && BUSY.includes(a.agent.activity));
      if (busy.length) { const a = busy[roundIndex++ % busy.length]; lastRound = t; queue.push({ id: 'round' + t, to: a.agent.id, verdict: 'working', text: 'Checking on ' + a.agent.name + ' — ' + (a.agent.detail || 'working'), accent: VERDICT.working, round: true }); }
    }
  }
  function direct(state, t, dt) {
    let target = home, dest = null;
    if (!step && queue.length) { step = queue.shift(); step.until = 0; }
    if (step) {
      dest = step.to ? actors.get(step.to) : null;
      if (step.to && (!dest || !dest.group.visible)) { step = null; dest = null; }   // agent went away (archived) — skip
      else if (dest) target = new THREE.Vector3(dest.x - .85, 0, dest.z + 1.9);
    }
    const delta = target.clone().sub(orion.position), distance = delta.length();
    const arrived = distance <= .1 || reduced;
    if (reduced) orion.position.copy(target);
    else if (!arrived) { orion.position.add(delta.clone().normalize().multiplyScalar(Math.min(distance, dt * 2))); orion.rotation.y = Math.atan2(delta.x, delta.z); }
    if (step && arrived) {
      if (!step.until) {
        step.until = t + DWELL;
        if (dest) dest.override = { text: VERDICT_LABEL[step.verdict] ? '● ' + VERDICT_LABEL[step.verdict] : '● NEW TASK', accent: step.accent, until: step.until };
      }
      if (t > step.until) { if (step.round) lastRound = t; step = null; }
    }
    if (arrived) {
      if (dest) orion.rotation.y = Math.atan2(dest.x - orion.position.x, dest.z + .95 - orion.position.z);
      else orion.rotation.y = step ? 0 : .52;
    }
    return { walking: !arrived, talking: !!(step && arrived) };
  }

  // ── frame loop ──────────────────────────────────────────────────────────────────
  function frame(t) {
    if (disposed) return;
    const dt = Math.min((t - previous) / 1000 || 0, .05); previous = t;
    const state = getState() || {}; syncActors(state);
    feed(state, t);
    actors.forEach(a => {
      const act = a.agent.activity, thinking = ['thinking', 'speaking'].includes((state.dogModes || {})[a.agent.id]);
      const busy = BUSY.includes(act) || thinking;
      const accent = ACTIVITY[act] || '#64748b';
      if (a.dog) {
        // Unrigged Meshy dogs: paws never leave the floor. Work shows as breathing + an attentive look-around.
        a.dog.rotation.y = a.facing + (!reduced && busy ? Math.sin(t / 1400 + a.x) * .08 : 0);
        a.dog.scale.y = a.dog.userData.base * (1 + (!reduced && busy ? Math.sin(t / 240) * .014 : Math.sin(t / 1600) * .006));
        if (a.walkAction) a.walkAction.paused = reduced || act !== 'walk';
        if (a.mixer && !reduced) a.mixer.update(dt);
      } else {
        a.group.position.y = !reduced && busy ? Math.sin(t / 210) * .025 : 0;
        a.arms.forEach((arm, i) => { arm.rotation.x = !reduced && busy ? -.7 + Math.sin(t / 95 + i * 2.1) * .45 : 0; });
      }
      a.pad.material.color.set(accent);
      a.pad.scale.setScalar(busy && !reduced ? 1 + Math.sin(t / 260) * .07 : 1);
      a.screen.material.emissive.set(busy ? '#18536f' : act === 'error' ? '#5b1515' : '#000000');
      if (a.override && t > a.override.until) a.override = null;
      let text = '', color = accent;
      if (a.override) { text = a.override.text; color = a.override.accent; }
      else if (thinking) text = (state.dogModes || {})[a.agent.id] === 'speaking' ? 'Speaking…' : 'Thinking about your message…';
      else if (act === 'done' || act === 'reporting') text = '✓ ' + (a.agent.detail || 'Reported');
      else if (act === 'error') text = '! ' + (a.agent.detail || 'Needs you');
      else if (act === 'queued') text = '• ' + (a.agent.detail || 'Task waiting');
      else if (act === 'unknown') text = '? not reachable';
      else if (busy) text = a.agent.detail || 'Working';
      say(a.bubble, text, color, a.x, a.dog ? 2.05 : 2.25, a.group.position.z);
    });
    const { walking, talking } = direct(state, t, dt);
    const director = state.director || {};
    const working = state.orionMode === 'thinking' || BUSY.includes(director.activity);
    clip(walking ? 'walk' : state.orionMode === 'speaking' || talking || working ? 'talk' : 'idle');
    if (mixer && !reduced) mixer.update(dt);
    orionLabel.position.set(orion.position.x, 2.85, orion.position.z);
    const orionText = step && talking ? step.text : state.orionMode === 'thinking' ? 'Thinking about your request…' : state.orionMode === 'speaking' ? 'Speaking…' : step ? 'On my way…' : '';
    say(orionBubble, orionText, step ? step.accent : '#5eead4', orion.position.x, 3.15, orion.position.z);
    ring.material.color.set(state.selected === 'orion' ? '#ffffff' : '#5eead4');
    // camera: focus a character, or orbit the whole room; eased so cuts never jump
    let wantPos, wantLook;
    if (state.focusOrion) {
      const selected = actors.get(state.selected);
      const p = selected && selected.group.visible ? selected.group.position : orion.position;
      wantPos = new THREE.Vector3(p.x + (selected ? 1.8 : 2.8), selected ? 1.9 : 2.8, p.z + (selected ? 3 : 4.8)); wantLook = new THREE.Vector3(p.x, selected ? .8 : 1.3, p.z);
    } else {
      wantPos = new THREE.Vector3(Math.sin(orbit.az) * Math.cos(orbit.el) * orbit.r, Math.sin(orbit.el) * orbit.r, Math.cos(orbit.az) * Math.cos(orbit.el) * orbit.r); wantLook = new THREE.Vector3(0, .8, 0);
    }
    if (!camReady || reduced) { camPos.copy(wantPos); camLook.copy(wantLook); camReady = true; }
    else { const k = 1 - Math.pow(.0015, dt); camPos.lerp(wantPos, k); camLook.lerp(wantLook, k); }
    camera.position.copy(camPos); camera.lookAt(camLook);
    renderer.render(scene, camera); raf = requestAnimationFrame(frame);
  }
  raf = requestAnimationFrame(frame);

  async function loadDog(id, actor) {
    try {
      const response = await fetch('/assets/dogs/' + id + '/manifest.json');
      if (!response.ok) throw new Error('Dog manifest unavailable');
      const manifest = await response.json();
      const model = await loader.loadAsync('/assets/dogs/' + id + '/' + manifest.model);
      if (disposed) { release(model.scene); return; }
      const bounds = new THREE.Box3().setFromObject(model.scene), size = bounds.getSize(new THREE.Vector3());
      if (!Number.isFinite(size.y) || size.y <= 0) { release(model.scene); throw new Error('Invalid dog bounds'); }
      const center = bounds.getCenter(new THREE.Vector3()), normalized = new THREE.Group();
      const scale = 1.95 / Math.max(size.x, size.y, size.z);
      normalized.scale.setScalar(scale); normalized.userData.base = scale;
      model.scene.position.set(-center.x, -bounds.min.y, -center.z); normalized.add(model.scene);
      [...actor.group.children].forEach(child => { actor.group.remove(child); release(child); });
      actor.arms = []; actor.group.add(normalized); actor.dog = normalized;
      actor.facing = manifest.rotationY || 0;
      actor.badge.position.y = 1.7;
      if (model.animations.length && manifest.animation === 'quadruped-walk') {
        actor.mixer = new THREE.AnimationMixer(model.scene);
        actor.walkAction = actor.mixer.clipAction(model.animations[0]); actor.walkAction.play(); actor.walkAction.paused = true;
      }
    } catch (e) { if (!disposed) onStatus('Some dog assets could not load. Agent controls remain available.'); }
  }
  async function load() {
    try {
      const model = await loader.loadAsync('/assets/orion/orion-rigged.glb');
      assets.add(model.scene);
      if (disposed) { release(model.scene); return; }
      const bounds = new THREE.Box3().setFromObject(model.scene), size = bounds.getSize(new THREE.Vector3());
      const normalized = new THREE.Group(); normalized.scale.setScalar(2.4 / size.y);
      const center = bounds.getCenter(new THREE.Vector3());
      model.scene.position.set(-center.x, -bounds.min.y, -center.z); normalized.add(model.scene); orion.add(normalized); assets.delete(model.scene);
      mixer = new THREE.AnimationMixer(model.scene);
      onStatus('Ready');
      await Promise.all(['idle', 'walk', 'talk'].map(async name => {
        const motion = await loader.loadAsync('/assets/orion/orion-' + name + '.glb');
        assets.add(motion.scene);
        if (!disposed && motion.animations.length) actions[name] = mixer.clipAction(motion.animations[0]);
        release(motion.scene); assets.delete(motion.scene);
      }));
    } catch (e) { if (!disposed) onStatus('Orion could not load. The agent controls below still work.'); }
  }
  load();
  return () => {
    disposed = true; cancelAnimationFrame(raf); observer.disconnect();
    el.removeEventListener('pointerdown', down); el.removeEventListener('pointermove', move);
    el.removeEventListener('pointerup', up); el.removeEventListener('wheel', wheel);
    if (mixer) mixer.stopAllAction();
    actors.forEach(a => { if (a.mixer) a.mixer.stopAllAction(); });
    release(scene); assets.forEach(release); assets.clear(); renderer.dispose(); renderer.domElement.remove();
  };
}

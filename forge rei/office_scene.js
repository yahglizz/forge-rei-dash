// Three.js is lazy-loaded only on the 3D office tab. Activity comes from office/state.
import * as THREE from 'three';
import { GLTFLoader } from './assets/vendor/three/loaders/GLTFLoader.js';

export async function createOfficeScene(host, getState, onSelect, onStatus) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#101a2a');
  const camera = new THREE.PerspectiveCamera(39, 1, .1, 100);
  camera.position.set(11, 11, 16);
  camera.lookAt(0, .8, 0);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  host.appendChild(renderer.domElement);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x64748b, 2.3));
  const light = new THREE.DirectionalLight(0xffeed9, 3);
  light.position.set(4, 12, 8); light.castShadow = true; scene.add(light);
  let disposed = false, raf, previous = 0, mixer, currentClip = '', currentAction;
  const assets = new Set(), actors = new Map(), actions = {}, loader = new GLTFLoader();
  const dogHeads = new Set(['marcus', 'dyson', 'solomon', 'midas']);
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
  box(15, .2, 10, '#d2c7b4', 0, -.15, 0);
  box(15, 2.7, .15, '#d9dfe7', 0, 1.25, -5);
  box(.15, 2.7, 10, '#bbc9d7', -7.5, 1.25, 0);
  box(4.4, 1.2, .07, '#18334b', 0, 1.7, -4.87);
  label('FORGE / COMMAND OFFICE', 0, 2.3, -4.7, '#d6eee9', 5);
  const plant = new THREE.Mesh(new THREE.ConeGeometry(.5, 1.2, 8), new THREE.MeshStandardMaterial({ color: '#367e69' }));
  plant.position.set(6.5, .8, -4.1); scene.add(plant); box(.7, .4, .7, '#ad7958', 6.5, .1, -4.1);
  const orion = new THREE.Group(); orion.position.set(0, 0, 2.2); scene.add(orion);
  const orionLabel = label('ORION · CEO', 0, 2.85, 2.2, '#a7f3d0', 2.2);
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
  function syncActors(state) {
    const alive = new Set();
    (state.departments || []).forEach(dept => {
      const base = deptPos[dept.id] || [0, -2];
      (dept.agents || []).forEach((a, i) => {
        alive.add(a.id);
        if (!actors.has(a.id)) {
          const group = new THREE.Group(), x = base[0] + i * 2.1, z = base[1];
          group.position.set(x, 0, z + .95); scene.add(group);
          const body = new THREE.Mesh(new THREE.CapsuleGeometry(.22, .42, 4, 10), new THREE.MeshStandardMaterial({ color: dept.accent }));
          body.position.y = .8; group.add(body);
          const head = new THREE.Mesh(new THREE.SphereGeometry(.24, 12, 12), new THREE.MeshStandardMaterial({ color: '#c7936c' }));
          head.position.y = 1.4; group.add(head);
          [-.15, .15].forEach(dx => box(.15, .45, .17, '#253247', dx, .23, 0, group));
          [-.35, .35].forEach(dx => box(.13, .42, .14, dept.accent, dx, .8, 0, group));
          const badge = label(a.name.toUpperCase(), x, 1.95, z + .95, '#e2e8f0', 1.8);
          const { screen, furniture } = desk(x, z, dept.accent);
          const mark = new THREE.Mesh(new THREE.SphereGeometry(.07, 8, 8), new THREE.MeshBasicMaterial({ color: '#64748b' }));
          mark.position.set(x, 1.75, z + .95); scene.add(mark);
          const actor = { group, badge, screen, furniture, mark, x, z, agent: a };
          actors.set(a.id, actor);
          if (dogHeads.has(a.id)) loadDog(a.id, actor);
        }
        actors.get(a.id).agent = a;
      });
    });
    actors.forEach((actor, id) => {
      const visible = alive.has(id); actor.group.visible = visible; actor.badge.visible = visible;
      actor.furniture.visible = visible; actor.mark.visible = visible;
    });
  }
  const observer = new ResizeObserver(() => {
    const w = Math.max(host.clientWidth, 1), h = Math.max(host.clientHeight, 1);
    renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
  }); observer.observe(host);
  const ray = new THREE.Raycaster(), pointer = new THREE.Vector2();
  function pick(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
    ray.setFromCamera(pointer, camera);
    if (ray.intersectObject(orion, true).length) { onSelect('orion'); return; }
    for (const [id, a] of actors) if (a.group.visible && ray.intersectObject(a.group, true).length) { onSelect(id); return; }
  }
  renderer.domElement.addEventListener('click', pick);
  renderer.domElement.setAttribute('aria-label', '3D office showing Orion and live agent desks. Use the agent buttons below to select with a keyboard.');
  function clip(name) {
    if (name === currentClip || !actions[name]) return;
    if (currentAction) currentAction.fadeOut(.25);
    currentAction = actions[name]; currentAction.reset().fadeIn(.25).play(); currentClip = name;
  }
  const colors = { error: '#ef4444', queued: '#f59e0b', think: '#60a5fa', read: '#2dd4bf', report: '#a78bfa', done: '#22c55e', reporting: '#22c55e' };
  function frame(t) {
    if (disposed) return;
    const dt = Math.min((t - previous) / 1000 || 0, .05); previous = t;
    const state = getState() || {}; syncActors(state);
    actors.forEach(a => {
      const busy = ['walk', 'read', 'think', 'report'].includes(a.agent.activity) || ['thinking', 'speaking'].includes((state.dogModes || {})[a.agent.id]);
      // Dog paws stay on the floor; activity drives a subtle attentive turn.
      a.group.position.y = !a.dog && !reduced && busy ? Math.sin(t / 210) * .025 : 0;
      if (a.dog) {
        a.dog.rotation.y = a.facing + (!reduced && busy ? Math.sin(t / 1400) * .08 : 0);
        if (a.walkAction) a.walkAction.paused = reduced || a.agent.activity !== 'walk';
        if (a.mixer && !reduced) a.mixer.update(dt);
      }
      a.mark.material.color.set(colors[a.agent.activity] || '#64748b');
      a.screen.material.emissive.set(busy ? '#18536f' : '#000000');
    });
    const message = (state.messages || []).find(m => m.from === 'orion' && m.kind === 'task' && actors.has(m.to) && Date.now() - m.ts < 30000);
    const destination = message ? actors.get(message.to) : null;
    const target = new THREE.Vector3(destination ? destination.x - .85 : 0, 0, destination ? destination.z + 1.9 : 2.2);
    const delta = target.clone().sub(orion.position), distance = delta.length();
    const walking = !reduced && distance > .08;
    if (walking) {
      orion.position.add(delta.normalize().multiplyScalar(Math.min(distance, dt * 1.5)));
      orion.rotation.y = Math.atan2(delta.x, delta.z);
    } else if (destination) orion.rotation.y = Math.atan2(destination.x - orion.position.x, destination.z + .95 - orion.position.z);
    else orion.rotation.y = .52;
    const busy = state.orionMode === 'thinking' || ['read', 'think', 'report'].includes((state.director || {}).activity);
    clip(walking ? 'walk' : state.orionMode === 'speaking' || destination || busy ? 'talk' : 'idle');
    if (mixer && !reduced) mixer.update(dt);
    orionLabel.position.set(orion.position.x, 2.85, orion.position.z);
    ring.material.color.set(state.selected === 'orion' ? '#ffffff' : '#5eead4');
    if (state.focusOrion) {
      const selected = actors.get(state.selected);
      const position = selected && selected.group.visible ? selected.group.position : orion.position;
      camera.position.set(position.x + 2.8, 2.8, position.z + 4.8);
      camera.lookAt(position.x, selected ? .8 : 1.3, position.z);
    } else { camera.position.set(11, 11, 16); camera.lookAt(0, .8, 0); }
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
      normalized.scale.setScalar(1.45 / Math.max(size.x, size.y, size.z));
      model.scene.position.set(-center.x, -bounds.min.y, -center.z); normalized.add(model.scene);
      [...actor.group.children].forEach(child => { actor.group.remove(child); release(child); });
      actor.group.add(normalized); actor.dog = normalized;
      actor.facing = manifest.rotationY || 0;
      actor.badge.position.y = 1.7; actor.mark.position.y = 1.48;
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
    } catch (e) { if (!disposed) onStatus('Character could not load. The pixel office and agent controls remain available.'); }
  }
  load();
  return () => {
    disposed = true; cancelAnimationFrame(raf); observer.disconnect();
    renderer.domElement.removeEventListener('click', pick);
    if (mixer) mixer.stopAllAction();
    actors.forEach(a => { if (a.mixer) a.mixer.stopAllAction(); });
    release(scene); assets.forEach(release); assets.clear(); renderer.dispose(); renderer.domElement.remove();
  };
}

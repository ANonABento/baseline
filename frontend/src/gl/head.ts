// Head geometry: LeePerrySmith (three.js examples, CC-BY 3.0 Lee Perry-Smith / Infinite-Realities)
// loaded once and normalized; procedural fallback if the file can't load.
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshSurfaceSampler } from "three/examples/jsm/math/MeshSurfaceSampler.js";

let cached: Promise<THREE.BufferGeometry> | null = null;

function normalize(geo: THREE.BufferGeometry): THREE.BufferGeometry {
  geo.computeBoundingBox();
  const box = geo.boundingBox!;
  const size = new THREE.Vector3();
  const center = new THREE.Vector3();
  box.getSize(size);
  box.getCenter(center);
  geo.translate(-center.x, -center.y, -center.z);
  const s = 2 / size.y;
  geo.scale(s, s, s);
  if (!geo.getAttribute("normal")) geo.computeVertexNormals();
  return geo;
}

function procedural(): THREE.BufferGeometry {
  const g = new THREE.SphereGeometry(1, 96, 72);
  const p = g.getAttribute("position") as THREE.BufferAttribute;
  const v = new THREE.Vector3();
  for (let i = 0; i < p.count; i++) {
    v.fromBufferAttribute(p, i);
    // egg-shaped skull, narrower jaw, a nose and brow ridge
    const y = v.y;
    const jaw = y < 0 ? 1 - Math.min(0.35, -y * 0.35) : 1;
    v.x *= 0.74 * jaw;
    v.z *= 0.86 * jaw;
    v.y *= 1.05;
    const front = Math.max(0, v.z);
    v.z += Math.exp(-((v.x * 9) ** 2 + ((y + 0.05) * 5) ** 2)) * 0.16 * front;
    v.z += Math.exp(-(((y - 0.28) * 9) ** 2)) * 0.04 * front;
    p.setXYZ(i, v.x, v.y, v.z);
  }
  g.computeVertexNormals();
  return normalize(g);
}

export function loadHead(): Promise<THREE.BufferGeometry> {
  if (cached) return cached;
  cached = new Promise((resolve) => {
    const loader = new GLTFLoader();
    loader.load(
      `${import.meta.env.BASE_URL}models/LeePerrySmith.glb`,
      (gltf) => {
        let geo: THREE.BufferGeometry | null = null;
        gltf.scene.updateMatrixWorld(true);
        gltf.scene.traverse((o) => {
          const m = o as THREE.Mesh;
          if (!geo && m.isMesh) geo = m.geometry.clone().applyMatrix4(m.matrixWorld);
        });
        resolve(geo ? normalize(geo) : procedural());
      },
      undefined,
      () => resolve(procedural()),
    );
  });
  return cached;
}

/** Surface samples for the point-cloud style: position, normal, random seed per point. */
export function sampleSurface(geo: THREE.BufferGeometry, count: number): THREE.BufferGeometry {
  const mesh = new THREE.Mesh(geo);
  const sampler = new MeshSurfaceSampler(mesh).build();
  const pos = new Float32Array(count * 3);
  const nrm = new Float32Array(count * 3);
  const rnd = new Float32Array(count);
  const p = new THREE.Vector3();
  const n = new THREE.Vector3();
  for (let i = 0; i < count; i++) {
    sampler.sample(p, n);
    pos.set([p.x, p.y, p.z], i * 3);
    nrm.set([n.x, n.y, n.z], i * 3);
    rnd[i] = Math.random();
  }
  const out = new THREE.BufferGeometry();
  out.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  out.setAttribute("aNormal", new THREE.BufferAttribute(nrm, 3));
  out.setAttribute("aRand", new THREE.BufferAttribute(rnd, 1));
  return out;
}

// GLSL for the three render styles. Colors arrive as uniforms (see palette in stage.ts).

export const NOISE = /* glsl */ `
float hash11(float p){ p = fract(p * .1031); p *= p + 33.33; p *= p + p; return fract(p); }
float hash21(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * .1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
float vnoise(vec3 x){
  vec3 i = floor(x); vec3 f = fract(x); f = f*f*(3.0-2.0*f);
  float n = i.x + i.y*57.0 + 113.0*i.z;
  return mix(mix(mix(hash11(n+0.0), hash11(n+1.0), f.x), mix(hash11(n+57.0), hash11(n+58.0), f.x), f.y),
             mix(mix(hash11(n+113.0), hash11(n+114.0), f.x), mix(hash11(n+170.0), hash11(n+171.0), f.x), f.y), f.z);
}
`;

/** Head surface: soft key + rim light, displaced by noise and a "mask slip" when chaos rises. */
export const HEAD_VERT = /* glsl */ `
uniform float uTime; uniform float uChaos;
varying vec3 vN; varying vec3 vView;
${NOISE}
void main(){
  vec3 p = position;
  float n = vnoise(p * 3.1 + vec3(0.0, uTime * 0.7, 0.0)) - 0.5;
  p += normal * n * uChaos * 0.22;
  // mask slip: horizontal bands of the face shear sideways
  float band = floor((p.y + uTime * 0.15) * 7.0);
  float slip = (hash11(band + floor(uTime * 3.0)) - 0.5) * step(0.55, hash11(band * 1.7));
  p.x += slip * uChaos * 0.35;
  vN = normalize(normalMatrix * normal);
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vView = -mv.xyz;
  gl_Position = projectionMatrix * mv;
}`;

export const HEAD_FRAG = /* glsl */ `
uniform float uLevel; uniform float uResolve;
varying vec3 vN; varying vec3 vView;
void main(){
  vec3 N = normalize(vN);
  vec3 V = normalize(vView);
  vec3 L = normalize(vec3(-0.45, 0.75, 0.55));
  float diff = max(dot(N, L), 0.0);
  float rim = pow(1.0 - max(dot(N, V), 0.0), 2.6);
  float l = diff * 0.62 + rim * 0.42 + 0.02;
  l *= 0.78 + uLevel * 0.75 + uResolve * 0.25;
  gl_FragColor = vec4(vec3(l), 1.0);
}`;

/** Full-screen quad: webcam (cover-fit, mirrored) or a procedural field when there's no camera. */
export const QUAD_VERT = /* glsl */ `
varying vec2 vUv;
void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;

export const SOURCE_FRAG = /* glsl */ `
uniform sampler2D uTex; uniform float uHasTex; uniform vec4 uCover; uniform float uTime; uniform float uLevel;
varying vec2 vUv;
${NOISE}
float field(vec2 uv){
  vec2 p = uv * vec2(3.0, 2.2);
  float n = vnoise(vec3(p, uTime * 0.12)) * 0.6 + vnoise(vec3(p * 2.3, uTime * 0.2 + 4.0)) * 0.3;
  float c = 1.0 - length((uv - 0.5) * vec2(1.3, 1.0)) * 1.4;
  return clamp(n * 0.9 * smoothstep(0.0, 0.7, c) + uLevel * 0.25, 0.0, 1.0);
}
void main(){
  float l;
  if (uHasTex > 0.5) {
    vec2 uv = vec2(1.0 - vUv.x, vUv.y) * uCover.xy + uCover.zw;
    vec3 c = texture2D(uTex, uv).rgb;
    l = dot(c, vec3(0.299, 0.587, 0.114));
    l = smoothstep(0.08, 0.85, l);
  } else {
    l = field(vUv);
  }
  gl_FragColor = vec4(vec3(l), 1.0);
}`;

/**
 * ASCII: luminance sampled per character cell, mapped to a glyph from the atlas.
 * Chaos scatters cell sampling and swaps glyphs; resolve settles the shimmer.
 */
export const ASCII_FRAG = /* glsl */ `
uniform sampler2D uSrc; uniform sampler2D uAtlas; uniform vec2 uRes; uniform float uCell; uniform float uGlyphs;
uniform float uTime; uniform float uChaos; uniform float uResolve; uniform vec3 uInk; uniform vec3 uRed; uniform vec3 uDim;
varying vec2 vUv;
${NOISE}
void main(){
  vec2 frag = vUv * uRes;
  vec2 cellSize = vec2(uCell * 0.62, uCell);
  vec2 cell = floor(frag / cellSize);
  vec2 cells = floor(uRes / cellSize);
  float tick = floor(uTime * 9.0);
  float r = hash21(cell + tick * 0.37);
  // scatter: shift the sampled cell sideways in bursts
  float row = hash21(vec2(cell.y, tick));
  vec2 off = vec2((row - 0.5) * 18.0 * step(1.0 - uChaos * 0.7, row), 0.0);
  off += (vec2(hash21(cell + 3.1), hash21(cell + 7.7)) - 0.5) * uChaos * 6.0;
  vec2 sc = clamp(cell + floor(off), vec2(0.0), cells - 1.0);
  float l = texture2D(uSrc, (sc + 0.5) * cellSize / uRes).r;
  l = smoothstep(0.015, 0.72, l);
  float shimmer = (hash21(cell + floor(uTime * 2.0)) - 0.5) * 0.08 * (1.0 - uResolve);
  l = clamp(l + shimmer, 0.0, 1.0);
  float idx = floor(l * (uGlyphs - 1.0) + 0.5);
  if (r < uChaos * 0.35 && l > 0.04) idx = floor(hash21(cell + tick) * uGlyphs);
  vec2 g = fract(frag / cellSize);
  float a = texture2D(uAtlas, vec2((idx + g.x) / uGlyphs, g.y)).r;
  vec3 ink = mix(uDim, uInk, smoothstep(0.05, 0.75, l) * (0.85 + uResolve * 0.15));
  float red = step(1.0 - uChaos * 0.07, hash21(cell * 1.3 + tick));
  ink = mix(ink, uRed, red * step(0.05, l));
  gl_FragColor = vec4(ink * a, 1.0);
}`;

/** 1-bit ordered dither (8x8 Bayer) on chunky pixels; chaos tears rows sideways. */
export const DITHER_FRAG = /* glsl */ `
uniform sampler2D uSrc; uniform vec2 uRes; uniform float uPx; uniform float uTime; uniform float uChaos; uniform float uResolve;
uniform vec3 uInk; uniform vec3 uRed;
varying vec2 vUv;
${NOISE}
float bayer2(vec2 a){ a = floor(a); return fract(dot(a, vec2(0.5, a.y * 0.75))); }
float bayer4(vec2 a){ return bayer2(0.5 * a) * 0.25 + bayer2(a); }
float bayer8(vec2 a){ return bayer4(0.5 * a) * 0.25 + bayer2(a); }
void main(){
  vec2 frag = vUv * uRes;
  vec2 px = floor(frag / uPx);
  float tick = floor(uTime * 12.0);
  float rowR = hash21(vec2(floor(px.y / 3.0), tick));
  float tear = step(1.0 - uChaos * 0.55, rowR);
  px.x += floor((hash21(vec2(px.y, tick + 1.0)) - 0.5) * 60.0 * uChaos * tear);
  float l = texture2D(uSrc, clamp((px + 0.5) * uPx / uRes, 0.0, 1.0)).r;
  l = pow(l, 1.15 - uResolve * 0.2);
  float th = bayer8(px) + (hash21(px + tick) - 0.5) * uChaos * 0.5;
  float on = step(th, l * 0.98) * step(0.03, l);
  vec3 ink = mix(uInk, uRed, tear * step(0.6, uChaos) * step(0.8, hash21(vec2(floor(px.y / 3.0), tick))));
  gl_FragColor = vec4(ink * on, 1.0);
}`;

/** Head as a point cloud sampled from its surface. */
export const HEAD_POINTS_VERT = /* glsl */ `
attribute vec3 aNormal; attribute float aRand;
uniform float uTime; uniform float uChaos; uniform float uLevel; uniform float uResolve; uniform float uPx;
varying float vL; varying float vRed;
${NOISE}
void main(){
  vec3 p = position;
  vec3 dir = normalize(vec3(hash11(aRand * 91.0) - 0.5, hash11(aRand * 37.0) - 0.5, hash11(aRand * 53.0) - 0.5) + aNormal * 0.6);
  float wob = 0.5 + 0.5 * sin(uTime * 1.1 + aRand * 31.0);
  float drift = vnoise(p * 2.0 + uTime * 0.3) * 0.5;
  p += dir * uChaos * (0.1 + drift * 0.7) * (0.4 + wob) * (0.3 + aRand);
  p += aNormal * (0.012 * sin(uTime * 0.6 + p.y * 4.0)) * (1.0 - uResolve);
  vec3 N = normalize(normalMatrix * aNormal);
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vec3 V = normalize(-mv.xyz);
  vec3 L = normalize(vec3(-0.45, 0.75, 0.55));
  float diff = max(dot(N, L), 0.0);
  float rim = pow(1.0 - max(dot(N, V), 0.0), 2.6);
  vL = clamp((diff * 0.65 + rim * 0.45 + 0.05) * (0.75 + uLevel * 0.8 + uResolve * 0.2), 0.0, 1.2);
  vL *= mix(0.12, 1.0, smoothstep(-0.15, 0.25, dot(N, V)));
  vRed = step(1.0 - uChaos * 0.07, hash11(aRand * 13.0 + floor(uTime * 4.0)));
  gl_PointSize = uPx * (0.6 + vL * 1.5) * (4.0 / -mv.z);
  gl_Position = projectionMatrix * mv;
}`;

/** Webcam / field as a grid of points; luminance drives size and a small depth lift. */
export const GRID_POINTS_VERT = /* glsl */ `
attribute vec2 aUv; attribute float aRand;
uniform sampler2D uTex; uniform float uHasTex; uniform vec4 uCover; uniform float uTime; uniform float uChaos; uniform float uResolve;
uniform float uPx; uniform float uLevel; uniform vec2 uAspect;
varying float vL; varying float vRed;
${NOISE}
void main(){
  float l;
  if (uHasTex > 0.5) {
    vec2 uv = vec2(1.0 - aUv.x, aUv.y) * uCover.xy + uCover.zw;
    vec3 c = texture2D(uTex, uv).rgb;
    l = smoothstep(0.08, 0.85, dot(c, vec3(0.299, 0.587, 0.114)));
  } else {
    vec2 q = aUv * vec2(3.0, 2.2);
    float n = vnoise(vec3(q, uTime * 0.12)) * 0.6 + vnoise(vec3(q * 2.3, uTime * 0.2 + 4.0)) * 0.3;
    float c = 1.0 - length((aUv - 0.5) * vec2(1.3, 1.0)) * 1.4;
    l = clamp(n * 0.9 * smoothstep(0.0, 0.7, c) + uLevel * 0.25, 0.0, 1.0);
  }
  vec2 p = aUv * 2.0 - 1.0;
  vec2 dir = vec2(hash11(aRand * 71.0) - 0.5, hash11(aRand * 17.0) - 0.5);
  p += dir * uChaos * 0.5 * (0.3 + l) * (0.5 + 0.5 * sin(uTime * 1.3 + aRand * 20.0));
  p.y += l * 0.02 * (1.0 - uResolve);
  vL = l;
  vRed = step(1.0 - uChaos * 0.07, hash11(aRand * 5.0 + floor(uTime * 4.0))) * step(0.1, l);
  gl_PointSize = uPx * (0.15 + l * 1.05);
  gl_Position = vec4(p, 0.0, 1.0);
}`;

export const POINTS_FRAG = /* glsl */ `
uniform vec3 uInk; uniform vec3 uRed; uniform vec3 uDim;
varying float vL; varying float vRed;
void main(){
  vec2 c = gl_PointCoord - 0.5;
  if (dot(c, c) > 0.25) discard;
  vec3 col = mix(mix(uDim, uInk, clamp(vL, 0.0, 1.0)), uRed, vRed);
  gl_FragColor = vec4(col * clamp(vL * 1.3 + 0.08, 0.0, 1.0), 1.0);
}`;

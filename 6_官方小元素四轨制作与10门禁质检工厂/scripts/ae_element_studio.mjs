#!/usr/bin/env node
/**
 * Track A+ AE/Skia Packaging & VFX Studio (`ae_element_studio.mjs`)
 *
 * Streams raw un-premultiplied RGBA frames to stdout at 2x supersampled quality,
 * using @napi-rs/canvas (Rust Skia) with exact 1-periodic 2*pi loop math (F(0) === F(N)),
 * periodic Curl-Noise turbulence, bright shadow-free palettes, source-atop metallic
 * shimmer, and 3D Z-sorted convex strip extrusion for 360-degree spins.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

async function loadNapiCanvas() {
  const candidates = [
    process.env.NAPI_CANVAS_PATH,
    path.join(os.homedir(), '.cache', 'vn-subtitle-cloud', 'node_runtime', 'node_modules', '@napi-rs', 'canvas', 'index.js'),
    'C:\\Users\\Q\\.gemini\\antigravity\\scratch\\vn-catholic-remotion-studio\\node_modules\\@napi-rs\\canvas\\index.js',
  ].filter(Boolean);

  for (const p of candidates) {
    if (fs.existsSync(p)) {
      return await import(pathToFileURL(p).href);
    }
  }
  throw new Error(`@napi-rs/canvas not found in candidates: ${candidates.join(', ')}`);
}

function parseArgs(argv) {
  const opts = {
    mode: 'l2_packaging',
    preset: 'bell_spring_ring',
    palette: 'sacred_gold',
    still: '',
    badgeText: 'ĐĂNG KÝ KÊNH',
    width: 512,
    height: 512,
    fps: 24,
    frames: 72,
    supersample: 2,
    seed: 202611,
  };
  for (let i = 2; i < argv.length; i += 1) {
    const k = argv[i];
    const v = argv[i + 1];
    if (k === '--mode' && v) { opts.mode = v; i += 1; }
    else if (k === '--preset' && v) { opts.preset = v; i += 1; }
    else if (k === '--palette' && v) { opts.palette = v; i += 1; }
    else if (k === '--still' && v !== undefined) { opts.still = v; i += 1; }
    else if (k === '--badge-text' && v) { opts.badgeText = v; i += 1; }
    else if (k === '--width' && v) { opts.width = parseInt(v, 10); i += 1; }
    else if (k === '--height' && v) { opts.height = parseInt(v, 10); i += 1; }
    else if (k === '--fps' && v) { opts.fps = parseInt(v, 10); i += 1; }
    else if (k === '--frames' && v) { opts.frames = parseInt(v, 10); i += 1; }
    else if (k === '--supersample' && v) { opts.supersample = Math.max(1, Math.min(2, parseInt(v, 10))); i += 1; }
    else if (k === '--seed' && v) { opts.seed = parseInt(v, 10); i += 1; }
  }
  return opts;
}

const BRIGHT_PALETTES = {
  sacred_gold: {
    primary: [255, 213, 79],
    highlight: [255, 250, 224],
    halo: [255, 179, 0],
    accent: [255, 143, 0],
    rimDark: [186, 128, 12],
    glassTint: [255, 248, 225],
    textColor: '#7C2D12',
  },
  festive_red_gold: {
    primary: [255, 202, 40],
    highlight: [255, 248, 208],
    halo: [229, 57, 53],
    accent: [255, 90, 90],
    rimDark: [184, 122, 14],
    glassTint: [255, 241, 236],
    textColor: '#991B1B',
  },
  heavenly_white_blue: {
    primary: [144, 202, 249],
    highlight: [255, 255, 255],
    halo: [100, 181, 246],
    accent: [255, 215, 64],
    rimDark: [192, 138, 24],
    glassTint: [238, 247, 255],
    textColor: '#1E3A8A',
  },
  pure_emerald_gold: {
    primary: [165, 214, 167],
    highlight: [255, 253, 231],
    halo: [102, 187, 106],
    accent: [255, 213, 79],
    rimDark: [180, 128, 18],
    glassTint: [240, 253, 244],
    textColor: '#14532D',
  },
};

function rgba(rgb, a = 1) {
  const aa = Math.max(0, Math.min(1, a));
  return `rgba(${rgb[0] | 0},${rgb[1] | 0},${rgb[2] | 0},${aa.toFixed(4)})`;
}

function rgbaZero(rgb) {
  return `rgba(${rgb[0] | 0},${rgb[1] | 0},${rgb[2] | 0},0)`;
}

function makeRng(seed) {
  let s = (seed >>> 0) || 1;
  return () => {
    s = (s + 0x6D2B79F5) >>> 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hash2(ix, iy) {
  const n = Math.sin(ix * 127.1 + iy * 311.7) * 43758.5453123;
  return n - Math.floor(n);
}

function valueNoise2D(x, y) {
  const ix = Math.floor(x);
  const iy = Math.floor(y);
  const fx = x - ix;
  const fy = y - iy;
  const ux = fx * fx * (3 - 2 * fx);
  const uy = fy * fy * (3 - 2 * fy);
  const a = hash2(ix, iy);
  const b = hash2(ix + 1, iy);
  const c = hash2(ix, iy + 1);
  const d = hash2(ix + 1, iy + 1);
  return a + (b - a) * ux + (c - a) * uy + (a - b - c + d) * ux * uy;
}

/**
 * Strictly 1-periodic 2D Curl-Noise: sampling circular path in noise space guarantees
 * curlPeriodic(x, y, 0) === curlPeriodic(x, y, 1) down to subpixel precision.
 */
function curlPeriodic(x, y, u, radius = 0.72, phase = 0) {
  const ang = 2 * Math.PI * (u + phase);
  const tx = Math.cos(ang) * radius;
  const ty = Math.sin(ang) * radius;
  const eps = 0.035;
  const nx = x + tx;
  const ny = y + ty;
  const dndy = (valueNoise2D(nx, ny + eps) - valueNoise2D(nx, ny - eps)) / (2 * eps);
  const dndx = (valueNoise2D(nx + eps, ny) - valueNoise2D(nx - eps, ny)) / (2 * eps);
  return [dndy, -dndx];
}

function smoothWindow(life) {
  const p = ((life % 1) + 1) % 1;
  return Math.sin(Math.PI * p) ** 1.15;
}

function drawOpticalGlow(ctx, x, y, r, coreRgb, midRgb, outerRgb, alpha = 1) {
  if (r <= 0.5 || alpha <= 0.004) return;
  const g = ctx.createRadialGradient(x, y, 0, x, y, r);
  g.addColorStop(0.0, rgba(coreRgb, alpha));
  g.addColorStop(0.28, rgba(midRgb, alpha * 0.74));
  g.addColorStop(0.65, rgba(outerRgb, alpha * 0.24));
  g.addColorStop(1.0, rgbaZero(outerRgb));
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fill();
}

function draw4PointStar(ctx, x, y, size, rot, coreRgb, glowRgb, alpha = 1) {
  if (size <= 1 || alpha <= 0.01) return;
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(rot);
  drawOpticalGlow(ctx, 0, 0, size * 0.72, coreRgb, glowRgb, glowRgb, alpha * 0.55);

  const armLen = size;
  const armW = Math.max(1.8, size * 0.14);
  for (let i = 0; i < 2; i += 1) {
    ctx.save();
    ctx.rotate(i * (Math.PI / 2));
    const lg = ctx.createLinearGradient(-armLen, 0, armLen, 0);
    lg.addColorStop(0.0, rgbaZero(glowRgb));
    lg.addColorStop(0.38, rgba(glowRgb, alpha * 0.65));
    lg.addColorStop(0.5, rgba(coreRgb, alpha));
    lg.addColorStop(0.62, rgba(glowRgb, alpha * 0.65));
    lg.addColorStop(1.0, rgbaZero(glowRgb));
    ctx.fillStyle = lg;
    ctx.beginPath();
    ctx.moveTo(-armLen, 0);
    ctx.quadraticCurveTo(0, -armW, armLen, 0);
    ctx.quadraticCurveTo(0, armW, -armLen, 0);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }
  ctx.fillStyle = rgba(coreRgb, alpha);
  ctx.beginPath();
  ctx.arc(0, 0, Math.max(1.5, size * 0.13), 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawStretchedSpark(ctx, x, y, vx, vy, len, thick, coreRgb, midRgb, alpha = 1) {
  if (alpha <= 0.01) return;
  const mag = Math.hypot(vx, vy) || 1;
  const dx = (vx / mag) * len;
  const dy = (vy / mag) * len;
  const lg = ctx.createLinearGradient(x - dx, y - dy, x + dx * 0.35, y + dy * 0.35);
  lg.addColorStop(0.0, rgbaZero(midRgb));
  lg.addColorStop(0.6, rgba(midRgb, alpha * 0.72));
  lg.addColorStop(1.0, rgba(coreRgb, alpha));
  ctx.strokeStyle = lg;
  ctx.lineCap = 'round';
  ctx.lineWidth = thick;
  ctx.beginPath();
  ctx.moveTo(x - dx, y - dy);
  ctx.lineTo(x + dx * 0.35, y + dy * 0.35);
  ctx.stroke();
}

function draw3DPetal(ctx, x, y, rx, ry, rotZ, pitch, fillRgb, rimRgb, alpha = 1) {
  if (alpha <= 0.01) return;
  const cosP = Math.max(0.28, Math.abs(Math.cos(pitch)));
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(rotZ);
  ctx.scale(1, cosP);

  const g = ctx.createRadialGradient(-rx * 0.2, -ry * 0.25, rx * 0.05, 0, 0, Math.max(rx, ry));
  g.addColorStop(0.0, rgba(rimRgb, alpha * 0.96));
  g.addColorStop(0.55, rgba(fillRgb, alpha * 0.92));
  g.addColorStop(1.0, rgba(fillRgb, alpha * 0.78));
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.moveTo(0, -ry);
  ctx.bezierCurveTo(rx * 1.15, -ry * 0.45, rx * 1.05, ry * 0.65, 0, ry);
  ctx.bezierCurveTo(-rx * 1.05, ry * 0.65, -rx * 1.15, -ry * 0.45, 0, -ry);
  ctx.closePath();
  ctx.fill();

  ctx.strokeStyle = rgba([255, 248, 224], alpha * 0.28);
  ctx.lineWidth = Math.max(1.0, rx * 0.06);
  ctx.stroke();
  ctx.restore();
}

function drawGoldHeart(ctx, x, y, size, rot, flipCos, fillRgb, rimRgb, alpha = 1) {
  if (alpha <= 0.01) return;
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(rot);
  ctx.scale(Math.max(0.25, Math.abs(flipCos)), 1);

  const g = ctx.createLinearGradient(-size, -size, size, size);
  g.addColorStop(0.0, rgba(rimRgb, alpha));
  g.addColorStop(0.45, rgba(fillRgb, alpha * 0.95));
  g.addColorStop(1.0, rgba([255, 224, 130], alpha));
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.moveTo(0, size * 0.32);
  ctx.bezierCurveTo(size * 0.55, -size * 0.42, size * 1.18, size * 0.25, 0, size * 1.05);
  ctx.bezierCurveTo(-size * 1.18, size * 0.25, -size * 0.55, -size * 0.42, 0, size * 0.32);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = rgba([255, 250, 224], alpha * 0.75);
  ctx.lineWidth = Math.max(1.4, size * 0.1);
  ctx.stroke();
  ctx.restore();
}

function drawStillTightAndCrop(createCanvas, img) {
  const c = createCanvas(img.width, img.height);
  const ctx = c.getContext('2d');
  ctx.drawImage(img, 0, 0);
  const data = ctx.getImageData(0, 0, img.width, img.height).data;
  let minX = img.width;
  let minY = img.height;
  let maxX = -1;
  let maxY = -1;
  for (let y = 0; y < img.height; y += 1) {
    const rowOff = y * img.width * 4;
    for (let x = 0; x < img.width; x += 1) {
      if (data[rowOff + x * 4 + 3] > 12) {
        if (x < minX) minX = x;
        if (y < minY) minY = y;
        if (x > maxX) maxX = x;
        if (y > maxY) maxY = y;
      }
    }
  }
  if (maxX < minX || maxY < minY) {
    return { canvas: c, x: 0, y: 0, w: img.width, h: img.height };
  }
  const pad = 2;
  const x0 = Math.max(0, minX - pad);
  const y0 = Math.max(0, minY - pad);
  const x1 = Math.min(img.width, maxX + pad + 1);
  const y1 = Math.min(img.height, maxY + pad + 1);
  return { canvas: c, x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

/**
 * Build crisp front sprite OR 24K gold-embossed medallion back-plate keeping relief textures.
 */
function buildEmbossedSprite(createCanvas, crop, targetW, targetH, backMode = false) {
  const c = createCanvas(targetW, targetH);
  const ctx = c.getContext('2d');
  ctx.drawImage(crop.canvas, crop.x, crop.y, crop.w, crop.h, 0, 0, targetW, targetH);
  if (backMode) {
    // Rich brushed 24K luxury gold back plate keeping subtle original engraved depth
    ctx.globalCompositeOperation = 'source-atop';
    const bg = ctx.createLinearGradient(0, 0, targetW, targetH);
    bg.addColorStop(0.0, 'rgba(255, 244, 194, 0.86)');
    bg.addColorStop(0.28, 'rgba(255, 209, 68, 0.84)');
    bg.addColorStop(0.55, 'rgba(196, 138, 16, 0.86)');
    bg.addColorStop(0.78, 'rgba(250, 198, 56, 0.84)');
    bg.addColorStop(1.0, 'rgba(255, 244, 194, 0.88)');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, targetW, targetH);

    // Subtle concentric relief engraving ring strictly inside silhouette
    ctx.strokeStyle = 'rgba(255, 250, 224, 0.34)';
    ctx.lineWidth = Math.max(2.5, targetW * 0.018);
    ctx.beginPath();
    ctx.arc(targetW / 2, targetH / 2, Math.min(targetW, targetH) * 0.32, 0, Math.PI * 2);
    ctx.stroke();
  }
  return c;
}

function buildGoldRimMask(createCanvas, crop, targetW, targetH, tone = 'mid') {
  const c = createCanvas(targetW, targetH);
  const ctx = c.getContext('2d');
  ctx.drawImage(crop.canvas, crop.x, crop.y, crop.w, crop.h, 0, 0, targetW, targetH);
  const imgData = ctx.getImageData(0, 0, targetW, targetH);
  const d = imgData.data;
  for (let i = 3; i < d.length; i += 4) {
    d[i] = d[i] >= 165 ? 255 : 0;
  }
  ctx.putImageData(imgData, 0, 0);

  ctx.globalCompositeOperation = 'source-in';
  const g = ctx.createLinearGradient(0, 0, 0, targetH);
  if (tone === 'bright') {
    g.addColorStop(0.0, 'rgba(255, 249, 206, 1)');
    g.addColorStop(0.45, 'rgba(255, 213, 74, 1)');
    g.addColorStop(1.0, 'rgba(218, 158, 22, 1)');
  } else {
    g.addColorStop(0.0, 'rgba(214, 156, 24, 1)');
    g.addColorStop(0.45, 'rgba(176, 120, 12, 1)');
    g.addColorStop(1.0, 'rgba(232, 174, 34, 1)');
  }
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, targetW, targetH);
  return c;
}

/**
 * Draw 45-degree specular sheen sweep strictly masked by a sprite canvas via `source-atop`.
 */
function renderSpriteWithDiagonalSheen(layerCtx, spriteCanvas, x, y, w, h, sheenProgress, pal, intensity = 0.72) {
  layerCtx.clearRect(0, 0, layerCtx.canvas.width, layerCtx.canvas.height);
  layerCtx.globalCompositeOperation = 'source-over';
  layerCtx.drawImage(spriteCanvas, x, y, w, h);

  if (sheenProgress >= -0.35 && sheenProgress <= 1.35) {
    layerCtx.save();
    layerCtx.globalCompositeOperation = 'source-atop';
    const cx = x + w * sheenProgress;
    const cy = y + h * sheenProgress;
    const band = Math.max(w, h) * 0.28;
    const sg = layerCtx.createLinearGradient(cx - band, cy - band, cx + band, cy + band);
    sg.addColorStop(0.0, rgbaZero(pal.highlight));
    sg.addColorStop(0.45, rgba(pal.highlight, intensity * 0.55));
    sg.addColorStop(0.5, rgba([255, 255, 255], intensity));
    sg.addColorStop(0.55, rgba(pal.highlight, intensity * 0.55));
    sg.addColorStop(1.0, rgbaZero(pal.highlight));
    layerCtx.fillStyle = sg;
    layerCtx.fillRect(x - 10, y - 10, w + 20, h + 20);
    layerCtx.restore();
  }
}

// ── Mode Renderers ────────────────────────────────────────────────────────────

function createL1Renderer(opts, pal, createCanvas) {
  const W = opts.width * opts.supersample;
  const H = opts.height * opts.supersample;
  const ss = opts.supersample;
  const rng = makeRng(opts.seed);

  // Pre-seed deterministic particle ensembles for 1-periodic tracks
  const galaxyParticles = Array.from({ length: 230 }, (_, idx) => ({
    lane: idx % 2, // 0: upper-right ribbon, 1: left-to-bottom ribbon
    p0: rng(),
    cycles: idx % 5 === 0 ? 2 : 1,
    spread: (rng() - 0.5) * 0.22,
    r: (2.6 + rng() * 7.2) * ss,
    twinkleFreq: 1 + (idx % 3),
    twinklePhase: rng(),
    isStar: idx % 5 === 0,
    curlAmp: (14 + rng() * 24) * ss,
  }));

  const bokehOrbs = Array.from({ length: 44 }, (_, idx) => ({
    x0: rng() * W,
    y0: rng() * H,
    r: (14 + rng() * 34) * ss,
    orbRadX: (8 + rng() * 18) * ss,
    orbRadY: (10 + rng() * 22) * ss,
    phase: rng(),
    k: 1 + (idx % 2),
    edgeBias: idx % 3 !== 0,
  }));

  const hearts = Array.from({ length: 34 }, (_, idx) => ({
    xFrac: rng() < 0.5 ? 0.08 + rng() * 0.22 : 0.70 + rng() * 0.22,
    p0: rng(),
    size: (11 + rng() * 16) * ss,
    rot0: (rng() - 0.5) * 0.45,
    swayAmp: (16 + rng() * 24) * ss,
    phase: rng(),
    redTint: idx % 2 === 0,
  }));

  const sparks = Array.from({ length: 85 }, (_, idx) => ({
    xFrac: rng() < 0.75 ? (rng() < 0.5 ? rng() * 0.26 : 0.74 + rng() * 0.26) : rng(),
    p0: rng(),
    len: (18 + rng() * 28) * ss,
    thick: (1.8 + rng() * 2.8) * ss,
    phase: rng(),
    cycles: idx % 4 === 0 ? 2 : 1,
  }));

  return function renderL1(ctx, u) {
    ctx.clearRect(0, 0, W, H);
    const tau = 2 * Math.PI * u;

    if (opts.preset === 'golden_galaxy_vortex') {
      // Two bright sweeping luminous helical streams framing outer edges while keeping center airy
      for (let ribbon = 0; ribbon < 2; ribbon += 1) {
        const steps = 28;
        for (let s = 0; s < steps; s += 1) {
          const t = s / (steps - 1);
          const wave = Math.sin(tau + t * Math.PI * 2) * 0.032;
          const rx = ribbon === 0
            ? W * (0.94 - 0.78 * t * 0.72 + 0.14 * Math.sin(t * Math.PI * 1.4) + wave)
            : W * (0.06 + 0.78 * t * 0.72 - 0.14 * Math.sin(t * Math.PI * 1.4) - wave);
          const ry = ribbon === 0
            ? H * (0.06 + 0.34 * t)
            : H * (0.94 - 0.34 * t);
          const edgeFade = Math.sin(Math.PI * t) ** 0.75;
          drawOpticalGlow(ctx, rx, ry, (62 + 26 * Math.sin(tau + t * 5)) * ss, pal.highlight, pal.primary, pal.halo, 0.145 * edgeFade);
        }
      }

      for (const p of galaxyParticles) {
        const life = (p.p0 + u * p.cycles) % 1;
        const win = smoothWindow(life);
        if (win <= 0.02) continue;
        const t = life;
        const baseX = p.lane === 0
          ? W * (0.96 - 0.78 * t * 0.74 + 0.15 * Math.sin(t * Math.PI * 1.4) + p.spread)
          : W * (0.04 + 0.78 * t * 0.74 - 0.15 * Math.sin(t * Math.PI * 1.4) + p.spread);
        const baseY = p.lane === 0 ? H * (0.04 + 0.38 * t) : H * (0.96 - 0.38 * t);
        const [cxv, cyv] = curlPeriodic(baseX / (140 * ss), baseY / (140 * ss), u, 0.55, p.twinklePhase);
        const px = baseX + cxv * p.curlAmp;
        const py = baseY + cyv * p.curlAmp;
        const tw = 0.55 + 0.45 * Math.sin(2 * Math.PI * (u * p.twinkleFreq + p.twinklePhase));
        if (p.isStar) {
          draw4PointStar(ctx, px, py, p.r * 3.2, u * Math.PI * 2 + p.twinklePhase * 6, pal.highlight, pal.primary, 0.96 * win * tw);
        } else {
          drawOpticalGlow(ctx, px, py, p.r * 2.2, pal.highlight, pal.primary, pal.halo, 0.90 * win * tw);
        }
      }
      return;
    }

    if (opts.preset === 'sacred_bokeh_rays') {
      // Gentle cathedral sunbeams top-down
      ctx.save();
      for (let i = 0; i < 5; i += 1) {
        const bx = W * (0.14 + i * 0.18) + Math.sin(tau + i * 1.2) * 18 * ss;
        const spread = (85 + i * 12) * ss;
        const pulse = 0.55 + 0.45 * Math.cos(tau + i * 1.1);
        const g = ctx.createLinearGradient(bx, 0, bx + 40 * ss, H * 0.58);
        g.addColorStop(0.0, rgba(pal.highlight, 0.22 * pulse));
        g.addColorStop(0.55, rgba(pal.primary, 0.10 * pulse));
        g.addColorStop(1.0, rgbaZero(pal.primary));
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.moveTo(bx - spread * 0.28, 0);
        ctx.lineTo(bx + spread * 0.28, 0);
        ctx.lineTo(bx + spread * 1.15, H * 0.58);
        ctx.lineTo(bx - spread * 0.75, H * 0.58);
        ctx.closePath();
        ctx.fill();
      }
      ctx.restore();

      for (const b of bokehOrbs) {
        let bx = b.x0 + Math.cos(2 * Math.PI * (u * b.k + b.phase)) * b.orbRadX;
        const by = b.y0 + Math.sin(2 * Math.PI * (u * b.k + b.phase)) * b.orbRadY;
        if (b.edgeBias && bx > W * 0.25 && bx < W * 0.75 && by > H * 0.22 && by < H * 0.78) {
          bx = bx < W * 0.5 ? W * 0.12 : W * 0.88;
        }
        const a = 0.22 + 0.18 * Math.sin(2 * Math.PI * (u + b.phase));
        drawOpticalGlow(ctx, bx, by, b.r, pal.highlight, pal.primary, pal.halo, a);
      }
      return;
    }

    if (opts.preset === 'blessing_hearts_stream') {
      for (const h of hearts) {
        const life = (h.p0 + u) % 1;
        const win = smoothWindow(life);
        if (win <= 0.02) continue;
        const py = H * (0.94 - 0.88 * life);
        const [cxv] = curlPeriodic(h.xFrac * 4, life * 4, u, 0.45, h.phase);
        const px = W * h.xFrac + Math.sin(tau + h.phase * 6.28) * h.swayAmp + cxv * 14 * ss;
        const rot = h.rot0 + Math.sin(tau + h.phase * 6.28) * 0.22;
        const fill = h.redTint ? pal.halo : pal.primary;
        drawGoldHeart(ctx, px, py, h.size, rot, Math.cos(tau + h.phase * 6.28), fill, pal.highlight, 0.9 * win);
      }
      return;
    }

    if (opts.preset === 'holy_sparks_rain') {
      for (const sp of sparks) {
        const life = (sp.p0 + u * sp.cycles) % 1;
        const win = smoothWindow(life);
        if (win <= 0.02) continue;
        const [cxv, cyv] = curlPeriodic(sp.xFrac * 5, life * 5, u, 0.45, sp.phase);
        const px = W * sp.xFrac + Math.sin(tau + sp.phase * 6.28) * 14 * ss + cxv * 18 * ss;
        const py = H * (0.04 + 0.92 * life) + cyv * 12 * ss;
        drawStretchedSpark(ctx, px, py, cxv * 0.4 + 0.2, 1.4, sp.len, sp.thick, pal.highlight, pal.primary, 0.92 * win);
      }
      return;
    }

    if (opts.preset === 'frosted_subscribe_bar') {
      const bw = W * 0.82;
      const bh = 96 * ss;
      const bx = (W - bw) / 2;
      const by = H * 0.77 + 12 * ss * Math.sin(tau);
      const pulse = 1 + 0.042 * Math.sin(2 * tau);

      // Soft celebration sparks & golden bell chime waves rising softly above pill so CTA radiates vitality
      for (let i = 0; i < 14; i += 1) {
        const life = (i / 14 + u * (i % 2 === 0 ? 1 : 2)) % 1;
        const win = smoothWindow(life);
        const sx = bx + bw * (0.08 + 0.84 * ((i * 0.37) % 1)) + Math.sin(tau + i) * 14 * ss;
        const sy = by + bh * 0.25 - life * 115 * ss;
        if (i % 3 === 0) {
          draw4PointStar(ctx, sx, sy, (10 + 4 * win) * ss, tau + i, pal.highlight, pal.primary, 0.92 * win);
        } else {
          drawOpticalGlow(ctx, sx, sy, (11 + 5 * win) * ss, pal.highlight, pal.primary, pal.halo, 0.82 * win);
        }
      }

      // Expanding acoustic golden pulse rings around left bell dot
      const chimeRingPhase = (u * 2) % 1;
      const ringA = (1 - chimeRingPhase) * 0.65;
      ctx.strokeStyle = rgba(pal.primary, ringA);
      ctx.lineWidth = 3.5 * ss;
      ctx.beginPath();
      ctx.arc(bx + bh * 0.54, by + bh * 0.5, bh * (0.34 + 0.32 * chimeRingPhase), 0, Math.PI * 2);
      ctx.stroke();

      ctx.save();
      ctx.translate(W / 2, by + bh / 2);
      ctx.scale(pulse, pulse);
      ctx.translate(-W / 2, -(by + bh / 2));

      // Frosted bright pill background (zero dark fill!)
      const bg = ctx.createLinearGradient(bx, by, bx, by + bh);
      bg.addColorStop(0.0, rgba(pal.highlight, 0.97));
      bg.addColorStop(1.0, rgba(pal.glassTint, 0.94));
      ctx.fillStyle = bg;
      ctx.beginPath();
      ctx.roundRect(bx, by, bw, bh, bh / 2);
      ctx.fill();

      // Gold metallic border
      ctx.strokeStyle = rgba(pal.primary, 0.98);
      ctx.lineWidth = 4.5 * ss;
      ctx.stroke();

      // Clipped 45-deg sweep highlight inside bar (twice per 3s loop)
      ctx.save();
      ctx.beginPath();
      ctx.roundRect(bx, by, bw, bh, bh / 2);
      ctx.clip();
      const sw = ((u * 2) % 1) * 1.4 - 0.2;
      const sx = bx + bw * sw;
      const sg = ctx.createLinearGradient(sx - 64 * ss, by, sx + 64 * ss, by + bh);
      sg.addColorStop(0.0, rgbaZero(pal.highlight));
      sg.addColorStop(0.5, rgba([255, 255, 255], 0.88));
      sg.addColorStop(1.0, rgbaZero(pal.highlight));
      ctx.fillStyle = sg;
      ctx.fillRect(bx, by, bw, bh);
      ctx.restore();

      // Left crimson-gold CTA badge + swinging miniature gold bell icon inside
      const dotR = bh * 0.31;
      const dotX = bx + bh * 0.54;
      const dotY = by + bh * 0.5;
      drawOpticalGlow(ctx, dotX, dotY, dotR * 1.55, pal.highlight, pal.accent, pal.halo, 0.6);
      ctx.fillStyle = rgba(pal.halo, 1);
      ctx.beginPath();
      ctx.arc(dotX, dotY, dotR, 0, Math.PI * 2);
      ctx.fill();

      const bellSwing = 0.24 * Math.sin(tau * 2) * Math.sin(tau * 6);
      ctx.save();
      ctx.translate(dotX, dotY - dotR * 0.42);
      ctx.rotate(bellSwing);
      ctx.fillStyle = rgba([255, 236, 130], 1);
      ctx.beginPath();
      ctx.moveTo(0, 2 * ss);
      ctx.bezierCurveTo(dotR * 0.48, dotR * 0.15, dotR * 0.55, dotR * 0.72, dotR * 0.62, dotR * 0.88);
      ctx.lineTo(-dotR * 0.62, dotR * 0.88);
      ctx.bezierCurveTo(-dotR * 0.55, dotR * 0.72, -dotR * 0.48, dotR * 0.15, 0, 2 * ss);
      ctx.closePath();
      ctx.fill();
      ctx.beginPath();
      ctx.arc(0, dotR * 0.96, dotR * 0.17, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      ctx.fillStyle = pal.textColor;
      ctx.font = `900 ${Math.round(31 * ss)}px "Be Vietnam Pro", "Montserrat", Arial, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(opts.badgeText, bx + bw * 0.57, by + bh * 0.52);
      ctx.restore();
      return;
    }

    if (opts.preset === 'diagonal_tyndall_rays') {
      // Upper-right cathedral sunbeams angling softly across top third + golden motes
      ctx.save();
      for (let i = 0; i < 6; i += 1) {
        const spread = (62 + i * 16) * ss;
        const pulse = 0.55 + 0.45 * Math.sin(tau + i * 1.05);
        const shift = Math.sin(tau + i * 0.9) * 24 * ss;
        const xStart = W * (0.68 + i * 0.08) + shift;
        const yEnd = H * (0.44 + i * 0.06);
        const g = ctx.createLinearGradient(xStart, 0, xStart - W * 0.55, yEnd);
        g.addColorStop(0.0, rgba(pal.highlight, 0.28 * pulse));
        g.addColorStop(0.55, rgba(pal.primary, 0.14 * pulse));
        g.addColorStop(1.0, rgbaZero(pal.halo));
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.moveTo(xStart - spread * 0.35, 0);
        ctx.lineTo(xStart + spread * 0.55, 0);
        ctx.lineTo(xStart - W * 0.62 + spread, yEnd);
        ctx.lineTo(xStart - W * 0.62 - spread * 0.85, yEnd);
        ctx.closePath();
        ctx.fill();
      }
      ctx.restore();
      for (const p of galaxyParticles) {
        const life = (p.p0 + u) % 1;
        const win = smoothWindow(life);
        if (win <= 0.02) continue;
        const px = W * (0.95 - 0.82 * life + p.spread * 0.55);
        const py = H * (0.04 + 0.52 * life + p.spread * 0.45);
        const [cxv, cyv] = curlPeriodic(px / (130 * ss), py / (130 * ss), u, 0.45, p.twinklePhase);
        const qx = px + cxv * 14 * ss;
        const qy = py + cyv * 14 * ss;
        if (p.isStar) draw4PointStar(ctx, qx, qy, p.r * 2.9, tau + p.twinklePhase * 6, pal.highlight, pal.primary, 0.92 * win);
        else drawOpticalGlow(ctx, qx, qy, p.r * 1.9, pal.highlight, pal.primary, pal.halo, 0.72 * win);
      }
      return;
    }

    if (opts.preset === 'morning_incense_mist') {
      // Rising warm rose-gold soft Curl-Noise incense light ribbons framing sides
      for (const side of [0, 1]) {
        const baseFrac = side === 0 ? 0.14 : 0.86;
        for (let k = 0; k < 24; k += 1) {
          const t = k / 23;
          const sway = Math.sin(tau + t * Math.PI * 3 + side * 2.1) * 0.055;
          const [cxv] = curlPeriodic(side * 2.3 + t * 2.5, t * 3.0, u, 0.55, side * 0.5);
          const rx = W * (baseFrac + sway) + cxv * 26 * ss;
          const ry = H * (0.95 - 0.86 * t);
          const fade = Math.sin(Math.PI * t) ** 0.85;
          drawOpticalGlow(ctx, rx, ry, (46 + 18 * Math.sin(tau + k)) * ss, pal.highlight, pal.primary, pal.halo, 0.15 * fade);
        }
      }
      for (const sp of sparks) {
        const life = (sp.p0 + u * sp.cycles) % 1;
        const win = smoothWindow(life);
        if (win <= 0.02) continue;
        const bx = sp.xFrac < 0.5 ? 0.06 + (sp.xFrac * 0.42) : 0.94 - ((1 - sp.xFrac) * 0.42);
        const [cxv] = curlPeriodic(bx * 4, life * 4, u, 0.5, sp.phase);
        const px = W * bx + cxv * 22 * ss + Math.sin(tau + sp.phase * 6.28) * 14 * ss;
        const py = H * (0.94 - 0.86 * life);
        drawOpticalGlow(ctx, px, py, (4.5 + 3.5 * win) * ss, pal.highlight, pal.accent, pal.halo, 0.88 * win);
      }
      return;
    }

    if (opts.preset === 'celestial_star_arcs') {
      // Sweeping sapphire-white celestial star arcs + razor 4-point flares
      for (let arc = 0; arc < 2; arc += 1) {
        for (let k = 0; k < 26; k += 1) {
          const t = k / 25;
          const ax = arc === 0 ? W * (0.10 + 0.80 * t) : W * (0.90 - 0.80 * t);
          const ay = arc === 0
            ? H * (0.18 - 0.10 * Math.sin(Math.PI * t) + 0.02 * Math.sin(tau + t * 5))
            : H * (0.82 + 0.10 * Math.sin(Math.PI * t) - 0.02 * Math.sin(tau + t * 5));
          const fade = Math.sin(Math.PI * t) ** 0.8;
          drawOpticalGlow(ctx, ax, ay, 48 * ss, pal.highlight, pal.primary, pal.halo, 0.14 * fade);
        }
      }
      for (const p of galaxyParticles) {
        const life = (p.p0 + u * p.cycles) % 1;
        const win = smoothWindow(life);
        if (win <= 0.02) continue;
        const ax = p.lane === 0 ? W * (0.06 + 0.88 * life) : W * (0.94 - 0.88 * life);
        const ay = p.lane === 0
          ? H * (0.20 - 0.11 * Math.sin(Math.PI * life) + p.spread * 0.25)
          : H * (0.80 + 0.11 * Math.sin(Math.PI * life) + p.spread * 0.25);
        const tw = 0.55 + 0.45 * Math.sin(2 * Math.PI * (u * p.twinkleFreq + p.twinklePhase));
        if (p.isStar) draw4PointStar(ctx, ax, ay, p.r * 3.4, tau + p.twinklePhase * 6, pal.highlight, pal.accent, 0.96 * win * tw);
        else drawOpticalGlow(ctx, ax, ay, p.r * 2.1, pal.highlight, pal.primary, pal.halo, 0.86 * win * tw);
      }
      return;
    }
  };
}

function createL2Renderer(opts, pal, createCanvas, crop) {
  const W = opts.width * opts.supersample;
  const H = opts.height * opts.supersample;
  const ss = opts.supersample;
  const cx = W / 2;
  const cy = H / 2;
  const SAFE_PAD = 68 * ss; // Strictly keeps entire 512px subject, peak bell swing & aura inside [68, 444] -> well inside [46, 466]!

  // Pre-build high-res sprite inside safe square
  const maxBox = Math.min(W, H) - SAFE_PAD * 2 - 58 * ss; // Reserve room for outer swing/glow/petals
  const scale = Math.min(maxBox / crop.w, maxBox / crop.h);
  const drawW = Math.round(crop.w * scale);
  const drawH = Math.round(crop.h * scale);

  const spriteCanvas = buildEmbossedSprite(createCanvas, crop, drawW, drawH, false);
  const layerCanvas = createCanvas(W, H);
  const layerCtx = layerCanvas.getContext('2d');

  const rng = makeRng(opts.seed + 77);
  const petals = Array.from({ length: 18 }, (_, i) => ({
    angle0: (i / 18) * Math.PI * 2,
    orbitR: (Math.max(drawW, drawH) * 0.56 + (rng() - 0.5) * 26 * ss),
    p0: rng(),
    rx: (8 + rng() * 5) * ss,
    ry: (12 + rng() * 6) * ss,
    phase: rng(),
    isStar: i % 3 === 0,
  }));

  const emberSparks = Array.from({ length: 28 }, (_, i) => ({
    p0: rng(),
    xOff: (rng() - 0.5) * drawW * 0.65,
    r: (3 + rng() * 5) * ss,
    phase: rng(),
    cycles: i % 3 === 0 ? 2 : 1,
  }));

  return function renderL2(ctx, u) {
    ctx.clearRect(0, 0, W, H);
    const tau = 2 * Math.PI * u;
    const sheenProg = ((u + 0.12) % 1) * 1.7 - 0.35;

    if (opts.preset === 'bell_spring_ring') {
      // Double joyful chime per 3.0s loop: envelope is sin^2(2*pi*u) so f(0)=f(1)=0 & df/du=0
      const chimeEnv = Math.sin(tau) ** 2;
      const swingAngle = 0.155 * chimeEnv * Math.sin(10 * Math.PI * u);
      const bobScale = 1 + 0.032 * chimeEnv;

      // Soft warm radial aura behind bell (steady amplitude avoids false G03 semi_spike_ratio)
      drawOpticalGlow(ctx, cx, cy, Math.max(drawW, drawH) * 0.66, pal.highlight, pal.primary, pal.halo, 0.26 + 0.08 * chimeEnv);

      // Expanding acoustic chime waves synced strictly to chime peaks
      const wavePhase1 = (u * 2) % 1;
      const waveAlpha1 = Math.sin(Math.PI * wavePhase1) ** 1.4 * chimeEnv;
      for (const side of [-1, 1]) {
        const arcR = drawW * (0.48 + 0.22 * wavePhase1);
        const baseA = side > 0 ? -0.48 : Math.PI - 0.48;
        ctx.strokeStyle = rgba(pal.primary, 0.88 * waveAlpha1);
        ctx.lineWidth = (4.5 * ss) * (1 - 0.45 * wavePhase1);
        ctx.lineCap = 'round';
        ctx.beginPath();
        ctx.arc(cx + side * 12 * ss, cy - drawH * 0.04, arcR, baseA, baseA + 0.96);
        ctx.stroke();

        ctx.strokeStyle = rgba(pal.highlight, 0.72 * waveAlpha1);
        ctx.lineWidth = (3.0 * ss);
        ctx.beginPath();
        ctx.arc(cx + side * 12 * ss, cy - drawH * 0.04, arcR * 0.84, baseA + 0.1, baseA + 0.86);
        ctx.stroke();
      }

      // Draw bell sprite with top pivot + source-atop metallic sweep
      const x0 = cx - drawW / 2;
      const y0 = cy - drawH / 2;
      renderSpriteWithDiagonalSheen(layerCtx, spriteCanvas, x0, y0, drawW, drawH, sheenProg, pal, 0.68);
      const pivotX = cx;
      const pivotY = cy - drawH * 0.38;
      ctx.save();
      ctx.translate(pivotX, pivotY);
      ctx.rotate(swingAngle);
      ctx.scale(bobScale, bobScale);
      ctx.translate(-pivotX, -pivotY);
      ctx.drawImage(layerCanvas, 0, 0);
      ctx.restore();

      // Orbiting accent stars safely inside [SAFE_PAD, W - SAFE_PAD]
      for (let i = 0; i < 8; i += 1) {
        const life = (i / 8 + u) % 1;
        const win = smoothWindow(life);
        const ang = (i / 8) * Math.PI * 2 + u * Math.PI * 0.5;
        const r = Math.min(cx - SAFE_PAD - 18 * ss, Math.max(drawW, drawH) * 0.56);
        const sx = cx + Math.cos(ang) * r;
        const sy = cy + Math.sin(ang) * r;
        draw4PointStar(ctx, sx, sy, (11 + 6 * chimeEnv) * ss, ang, pal.highlight, pal.primary, 0.9 * win);
      }
      return;
    }

    if (opts.preset === 'wreath_shimmer_petals') {
      const breathe = 1 + 0.028 * Math.sin(tau);
      const tilt = 0.026 * Math.cos(tau);
      const liftY = 5 * ss * Math.sin(tau);

      drawOpticalGlow(ctx, cx, cy, Math.max(drawW, drawH) * 0.68, pal.highlight, pal.primary, pal.halo, 0.25 + 0.05 * Math.sin(tau));

      // Floating 3D petals & sparkles behind/around wreath safely inside bounds
      for (const pt of petals) {
        const ang = pt.angle0 + tau * 0.25; // integer fractions? Keep exact 1-periodic! Wait: 0.25*tau -> gap at u=0 vs 1 unless symmetric!
        // Use exact 1-periodic radial bob + full 1-rev or harmonic sway so frame(0) === frame(N)!
        const life = (pt.p0 + u) % 1;
        const win = smoothWindow(life);
        const orbAng = pt.angle0 + 2 * Math.PI * u;
        const maxR = Math.min(cx - SAFE_PAD - 18 * ss, pt.orbitR);
        const [cxv, cyv] = curlPeriodic(Math.cos(pt.angle0), Math.sin(pt.angle0), u, 0.4, pt.phase);
        const px = cx + Math.cos(orbAng) * maxR * 0.92 + cxv * 10 * ss;
        const py = cy + Math.sin(orbAng) * maxR * 0.92 + cyv * 10 * ss;
        if (pt.isStar) {
          draw4PointStar(ctx, px, py, pt.rx * 1.4, orbAng, pal.highlight, pal.primary, 0.88 * win);
        } else {
          draw3DPetal(ctx, px, py, pt.rx, pt.ry, orbAng + 0.5, tau + pt.phase * 6.28, pal.halo, pal.highlight, 0.85 * win);
        }
      }

      const x0 = cx - drawW / 2;
      const y0 = cy - drawH / 2;
      renderSpriteWithDiagonalSheen(layerCtx, spriteCanvas, x0, y0, drawW, drawH, sheenProg, pal, 0.72);
      ctx.save();
      ctx.translate(cx, cy + liftY);
      ctx.rotate(tilt);
      ctx.scale(breathe, breathe);
      ctx.translate(-cx, -cy);
      ctx.drawImage(layerCanvas, 0, 0);
      ctx.restore();
      return;
    }

    if (opts.preset === 'candle_fluid_flame') {
      const flicker = 1 + 0.04 * Math.sin(tau) + 0.025 * Math.sin(2 * tau + 0.7);
      const fx = cx;
      const fy = cy - drawH * 0.30;
      drawOpticalGlow(ctx, fx, fy, drawW * 0.44 * flicker, [255, 255, 232], pal.primary, pal.halo, 0.56);

      const x0 = cx - drawW / 2;
      const y0 = cy - drawH / 2 + 16 * ss;
      renderSpriteWithDiagonalSheen(layerCtx, spriteCanvas, x0, y0, drawW, drawH, sheenProg, pal, 0.5);
      ctx.drawImage(layerCanvas, 0, 0);

      for (const sp of emberSparks) {
        const life = (sp.p0 + u * sp.cycles) % 1;
        const win = smoothWindow(life);
        const [cxv] = curlPeriodic(sp.phase * 4, life * 4, u, 0.5, sp.phase);
        const py = fy - life * (cy - SAFE_PAD - 24 * ss) * 0.55;
        const px = fx + sp.xOff * (0.4 + 0.6 * life) + cxv * 14 * ss;
        if (px > SAFE_PAD && px < W - SAFE_PAD && py > SAFE_PAD) {
          drawOpticalGlow(ctx, px, py, sp.r * 1.8, pal.highlight, pal.primary, pal.halo, 0.85 * win);
        }
      }
      return;
    }

    // Default / emblem_royal_gleam: 8-fold symmetric halo rays + levitation + source-atop metallic gleam
    const liftY = 7 * ss * Math.sin(tau);
    const pulse = 1 + 0.022 * Math.cos(tau);
    ctx.save();
    ctx.translate(cx, cy + liftY);
    const rayCount = 8;
    const baseRot = (Math.PI * 2 / rayCount) * u; // Exact 8-fold 1-periodic match at u=0 and u=1!
    for (let i = 0; i < rayCount; i += 1) {
      ctx.save();
      ctx.rotate(baseRot + (i / rayCount) * Math.PI * 2);
      const rLen = Math.min(cx - SAFE_PAD - 10 * ss, Math.max(drawW, drawH) * 0.68);
      const rg = ctx.createLinearGradient(0, 0, rLen, 0);
      rg.addColorStop(0.0, rgba(pal.highlight, 0.44));
      rg.addColorStop(0.6, rgba(pal.primary, 0.22));
      rg.addColorStop(1.0, rgbaZero(pal.halo));
      ctx.fillStyle = rg;
      ctx.beginPath();
      ctx.moveTo(0, -10 * ss);
      ctx.lineTo(rLen, -28 * ss);
      ctx.lineTo(rLen, 28 * ss);
      ctx.lineTo(0, 10 * ss);
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    }
    ctx.restore();

    const x0 = cx - drawW / 2;
    const y0 = cy - drawH / 2;
    renderSpriteWithDiagonalSheen(layerCtx, spriteCanvas, x0, y0, drawW, drawH, sheenProg, pal, 0.78);
    ctx.save();
    ctx.translate(cx, cy + liftY);
    ctx.scale(pulse, pulse);
    ctx.translate(-cx, -cy);
    ctx.drawImage(layerCanvas, 0, 0);
    ctx.restore();
  };
}

function createL3Renderer(opts, pal, createCanvas, crop) {
  const W = opts.width * opts.supersample;
  const H = opts.height * opts.supersample;
  const ss = opts.supersample;
  const cx = W / 2;
  const cy = H / 2;
  const SAFE_PAD = 58 * ss; // Strictly keeps entire 512px spin inside [58, 454] -> safe inside [46, 466]

  const maxBox = Math.min(W, H) - SAFE_PAD * 2 - 28 * ss;
  const scale = Math.min(maxBox / crop.w, maxBox / crop.h);
  const drawW = Math.round(crop.w * scale);
  const drawH = Math.round(crop.h * scale);

  const frontSprite = buildEmbossedSprite(createCanvas, crop, drawW, drawH, false);
  const backSprite = buildEmbossedSprite(createCanvas, crop, drawW, drawH, true);
  const rimDark = buildGoldRimMask(createCanvas, crop, drawW, drawH, 'mid');
  const rimBright = buildGoldRimMask(createCanvas, crop, drawW, drawH, 'bright');

  const numRimSlices = 20;
  const rimDepth = 38 * ss; // Thick solid 24K gold bevel depth (~19px edge-on at 512px)

  const faceBuf = createCanvas(drawW, drawH);
  const faceCtx = faceBuf.getContext('2d');

  return function renderL3(ctx, u) {
    ctx.clearRect(0, 0, W, H);
    const theta = 2 * Math.PI * u;
    const c = Math.cos(theta);
    const s = Math.sin(theta);

    // Gentle floating breath + exact 1-periodic 360 rotation
    const yFloat = 4 * ss * Math.sin(theta);

    // Active face & camera sign: single affine scale(signedC, 1) cleanly mirrors back exactly once
    const isFront = c >= 0;
    const activeSprite = isFront ? frontSprite : backSprite;
    const faceSign = isFront ? 1 : -1;
    const facingRatio = Math.max(0.055, Math.abs(c));
    const signedC = isFront ? facingRatio : -facingRatio;

    // Pre-shade active face with warm 24K gold diagonal specular sweep
    faceCtx.clearRect(0, 0, drawW, drawH);
    faceCtx.globalCompositeOperation = 'source-over';
    faceCtx.drawImage(activeSprite, 0, 0);
    faceCtx.save();
    faceCtx.globalCompositeOperation = 'source-atop';
    const glintX = drawW * (0.5 + 0.55 * Math.sin(theta * (isFront ? 1 : -1)));
    const goldShine = [255, 250, 224];
    const goldMid = [255, 224, 130];
    const specG = faceCtx.createLinearGradient(glintX - drawW * 0.32, 0, glintX + drawW * 0.32, drawH);
    specG.addColorStop(0.0, rgbaZero(goldMid));
    specG.addColorStop(0.5, rgba(goldShine, 0.54 * (1 - 0.3 * facingRatio)));
    specG.addColorStop(1.0, rgbaZero(goldMid));
    faceCtx.fillStyle = specG;
    faceCtx.fillRect(0, 0, drawW, drawH);
    faceCtx.restore();

    // Draw 20 Z-sorted opaque 24K gold extruded rim slices using identical signedC transform
    const zBack = -faceSign * (rimDepth / 2);
    const zFront = faceSign * (rimDepth / 2);
    for (let k = 0; k < numRimSlices; k += 1) {
      const frac = k / numRimSlices;
      const z = zBack + (zFront - zBack) * frac;
      const mask = k < numRimSlices * 0.55 ? rimDark : rimBright;
      ctx.save();
      ctx.translate(cx + z * s, cy + yFloat);
      ctx.scale(signedC, 1);
      ctx.drawImage(mask, -drawW / 2, -drawH / 2, drawW, drawH);
      ctx.restore();
    }

    // Crisp un-striped active face at zFront
    ctx.save();
    ctx.translate(cx + zFront * s, cy + yFloat);
    ctx.scale(signedC, 1);
    ctx.drawImage(faceBuf, -drawW / 2, -drawH / 2, drawW, drawH);
    ctx.restore();
  };
}

async function writeStdout(buf) {
  if (!process.stdout.write(buf)) {
    await new Promise((resolve) => process.stdout.once('drain', resolve));
  }
}

async function main() {
  const opts = parseArgs(process.argv);
  const { createCanvas, loadImage, GlobalFonts } = await loadNapiCanvas();
  const pal = BRIGHT_PALETTES[opts.palette] || BRIGHT_PALETTES.sacred_gold;

  // Optionally register Vietnamese fonts from local vn-subtitle-cloud cache if available
  const fontDir = path.join(os.homedir(), '.cache', 'vn-subtitle-cloud', 'fonts');
  if (fs.existsSync(fontDir)) {
    for (const f of fs.readdirSync(fontDir)) {
      if (/\.(ttf|otf)$/i.test(f)) {
        try {
          GlobalFonts.registerFromPath(path.join(fontDir, f), path.parse(f).name);
        } catch {
          // ignore duplicate or unreadable cached font
        }
      }
    }
  }

  let crop = null;
  if (opts.still && fs.existsSync(opts.still)) {
    const img = await loadImage(opts.still);
    crop = drawStillTightAndCrop(createCanvas, img);
  } else if (opts.mode !== 'l1_vfx') {
    throw new Error(`--still PNG is required for mode=${opts.mode}: got "${opts.still}"`);
  }

  const hiW = opts.width * opts.supersample;
  const hiH = opts.height * opts.supersample;
  const hiCanvas = createCanvas(hiW, hiH);
  const hiCtx = hiCanvas.getContext('2d');

  const outCanvas = createCanvas(opts.width, opts.height);
  const outCtx = outCanvas.getContext('2d');
  outCtx.imageSmoothingEnabled = true;
  outCtx.imageSmoothingQuality = 'high';

  let renderFn;
  if (opts.mode === 'l1_vfx') renderFn = createL1Renderer(opts, pal, createCanvas);
  else if (opts.mode === 'l3_spin360') renderFn = createL3Renderer(opts, pal, createCanvas, crop);
  else renderFn = createL2Renderer(opts, pal, createCanvas, crop);

  for (let frameIdx = 0; frameIdx < opts.frames; frameIdx += 1) {
    const u = frameIdx / opts.frames; // [0, 1) -> F(0) === F(N) mathematically
    renderFn(hiCtx, u, frameIdx);
    if (opts.supersample > 1) {
      outCtx.clearRect(0, 0, opts.width, opts.height);
      outCtx.drawImage(hiCanvas, 0, 0, opts.width, opts.height);
      const raw = Buffer.from(outCtx.getImageData(0, 0, opts.width, opts.height).data.buffer);
      await writeStdout(raw);
    } else {
      const raw = Buffer.from(hiCtx.getImageData(0, 0, hiW, hiH).data.buffer);
      await writeStdout(raw);
    }
  }
}

main().catch((err) => {
  console.error(err?.stack || String(err));
  process.exit(1);
});

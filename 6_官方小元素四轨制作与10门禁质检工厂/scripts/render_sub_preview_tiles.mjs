#!/usr/bin/env node
/**
 * Fast Skia Preview Tile Generator for fast_subtitle_qa.py.
 * Renders 1-line and 2-line Vietnamese samples onto stage backdrops in ~1-3s using
 * @napi-rs/canvas + vn-subtitle-cloud/public/vk-kernel/* without encoding full MP4s.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import { createRequire } from 'node:module';

const DEFAULT_CACHE_ROOT = path.join(os.homedir(), '.cache', 'vn-subtitle-cloud');
const DEFAULT_CLOUD_PUBLIC = 'C:\\Users\\Q\\.gemini\\antigravity\\scratch\\vn-subtitle-cloud\\public';

const KERNEL_FILES = [
  'reels-text-direction.js',
  'reels-rich-text.js',
  'reels-anim-engine.js',
  'reels-style-engine.js',
  'reels-canvas-renderer.js',
  'reels-subtitle-processor.js',
  'reels-scroll-timing.js',
  'reels-audio-spectrum.js',
  'reels-overlay.js',
  'reels-ae-typography.js',
];

function loadNapiCanvas() {
  const pkgPath = path.join(DEFAULT_CACHE_ROOT, 'node_runtime', 'package.json');
  if (fs.existsSync(pkgPath)) {
    const req = createRequire(pkgPath);
    return req('@napi-rs/canvas');
  }
  const reqLocal = createRequire(import.meta.url);
  return reqLocal('@napi-rs/canvas');
}

function mountKernel(napi, kernelDir) {
  const { createCanvas, Path2D, Image: RawImage, DOMMatrix, DOMPoint, DOMRect } = napi;
  class PatchedImage extends RawImage {
    set src(val) {
      if (typeof val === 'string' && val.startsWith('data:image/svg+xml') && !val.includes(';base64,')) {
        const comma = val.indexOf(',');
        if (comma !== -1) {
          super.src = Buffer.from(decodeURIComponent(val.slice(comma + 1)), 'utf8');
          return;
        }
      }
      super.src = val;
    }
    get src() { return super.src; }
  }
  globalThis.window = globalThis;
  globalThis.self = globalThis;
  globalThis.__vnCreateCanvas = createCanvas;
  globalThis.Path2D = Path2D;
  globalThis.Image = PatchedImage;
  if (DOMMatrix) globalThis.DOMMatrix = DOMMatrix;
  if (DOMPoint) globalThis.DOMPoint = DOMPoint;
  if (DOMRect) globalThis.DOMRect = DOMRect;
  globalThis.devicePixelRatio = 1;
  globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
  globalThis.document = {
    createElement(tag) {
      const t = String(tag || '').toLowerCase();
      if (t === 'canvas') return createCanvas(1080, 1920);
      if (t === 'img') return new PatchedImage();
      return { style: {}, getContext: () => createCanvas(2, 2).getContext('2d'), addEventListener: () => {} };
    },
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {},
    body: { appendChild: () => {} },
    fonts: { check: () => true, ready: Promise.resolve() },
  };
  for (const f of KERNEL_FILES) {
    const code = fs.readFileSync(path.join(kernelDir, f), 'utf8');
    vm.runInThisContext(code, { filename: f });
  }
}

function registerLocalFonts(GlobalFonts, fontMap) {
  const roots = [
    path.join(DEFAULT_CLOUD_PUBLIC, 'r2', 'fonts'),
    path.join(DEFAULT_CACHE_ROOT, 'fonts'),
  ];
  for (const [family, relPaths] of Object.entries(fontMap || {})) {
    for (const rel of relPaths || []) {
      const base = path.basename(rel);
      for (const dir of roots) {
        const fp = path.join(dir, base);
        if (fs.existsSync(fp)) {
          try { GlobalFonts.registerFromPath(fp, family); } catch {}
          break;
        }
      }
    }
  }
}

function scanCanvasAlphaClipping(ctx, W, H) {
  const data = ctx.getImageData(0, 0, W, H).data;
  let minX = W, maxX = -1, minY = H, maxY = -1;
  let borderTouch = 0;
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const a = data[(y * W + x) * 4 + 3];
      if (a > 24) {
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
        if (x <= 8 || x >= W - 9 || y <= 8 || y >= H - 9) borderTouch++;
      }
    }
  }
  return {
    hasPixels: maxX >= 0,
    bbox: maxX >= 0 ? [minX, minY, maxX, maxY] : null,
    borderTouchPx: borderTouch,
    clipped: borderTouch > 20,
  };
}

async function main() {
  const args = process.argv.slice(2);
  const getArg = (flag, def = '') => {
    const idx = args.indexOf(flag);
    return idx >= 0 ? (args[idx + 1] || def) : def;
  };
  const jobPath = getArg('--job');
  if (!jobPath) throw new Error('Missing --job <json>');
  const job = JSON.parse(fs.readFileSync(jobPath, 'utf8'));

  const napi = loadNapiCanvas();
  const kernelDir = fs.existsSync(path.join(DEFAULT_CLOUD_PUBLIC, 'vk-kernel'))
    ? path.join(DEFAULT_CLOUD_PUBLIC, 'vk-kernel')
    : path.join(DEFAULT_CACHE_ROOT, 'vk-kernel');
  mountKernel(napi, kernelDir);
  registerLocalFonts(napi.GlobalFonts, job.font_map || {});

  const W = 1080, H = 1920;
  const outDir = path.resolve(job.out_dir);
  fs.mkdirSync(outDir, { recursive: true });

  const bgImages = {};
  for (const [k, jpgName] of [['photo', 'stage-photo.jpg'], ['photo-dark', 'stage-photo-dark.jpg'], ['photo-light', 'stage-photo-light.jpg']]) {
    const p = path.join(DEFAULT_CLOUD_PUBLIC, jpgName);
    if (fs.existsSync(p)) {
      const img = new globalThis.Image();
      img.src = fs.readFileSync(p);
      bgImages[k] = img;
    }
  }

  const results = [];
  const canvasFg = napi.createCanvas(W, H);
  const ctxFg = canvasFg.getContext('2d');
  const renderer = new globalThis.ReelsCanvasRenderer(canvasFg);

  const canvasOut = napi.createCanvas(W, H);
  const ctxOut = canvasOut.getContext('2d');

  const sampleCases = [
    { tag: '1line_short', t: 0.95, text: 'Hãy giữ tâm bình an', start: 0.0, end: 2.5 },
    { tag: '2line_diacritics', t: 1.55, useItemSample: true, fallbackText: 'Đức Chúa Giê-su luôn nâng đỡ bạn', start: 0.0, end: 3.5 },
  ];

  for (let i = 0; i < (job.items || []).length; i++) {
    const it = job.items[i];
    const kind = it.kind || 'subtitle';
    const stageKey = it.stage_bg || 'photo';
    const bgImg = bgImages[stageKey] || bgImages.photo || null;
    const itemOut = { index: i, title: it.title, kind, tiles: [], clipped_any: false };

    if (kind === 'overlay') {
      const layers = (it.style_obj?.layers || []).map((ov) => structuredClone(ov));
      let prepared = layers;
      if (globalThis.ReelsScrollTiming?.renderingOverlay) {
        prepared = layers.map((ov) => globalThis.ReelsScrollTiming.renderingOverlay(ov, null, { bodyDuration: 5.0 }));
      }
      if (globalThis.ReelsOverlay?.prepareScrollWritingCursorImage) {
        for (const ov of prepared) {
          if (ov && !ov.disabled && ov.type === 'scroll') {
            await globalThis.ReelsOverlay.prepareScrollWritingCursorImage(ov);
          }
        }
      }
      for (const [tag, ts] of [['ov_start', 0.4], ['ov_mid', 2.4]]) {
        ctxFg.clearRect(0, 0, W, H);
        const sorted = prepared.filter((o) => o && !o.disabled).slice().sort((a, b) => (Number(a.z_index) || 0) - (Number(b.z_index) || 0));
        for (const ov of sorted) {
          ov._allOverlays = prepared;
          ov._selected = false;
          ov._exporting = true;
          ov._exportDuration = 5.0;
          globalThis.ReelsOverlay.drawOverlay(ctxFg, ov, ts, W, H);
        }
        const clipInfo = scanCanvasAlphaClipping(ctxFg, W, H);
        if (clipInfo.clipped) itemOut.clipped_any = true;
        ctxOut.clearRect(0, 0, W, H);
        if (bgImg) ctxOut.drawImage(bgImg, 0, 0, W, H);
        else { ctxOut.fillStyle = '#d4d4d8'; ctxOut.fillRect(0, 0, W, H); }
        ctxOut.drawImage(canvasFg, 0, 0);
        const outPng = path.join(outDir, `tile_${i}_${tag}.png`);
        fs.writeFileSync(outPng, canvasOut.toBuffer('image/png'));
        itemOut.tiles.push({ tag, path: outPng, ...clipInfo });
      }
    } else {
      const def = globalThis.ReelsStyleEngine?.DEFAULT_SUBTITLE_STYLE || {};
      const raw = it.style_obj?.raw_style_params || {};
      const merged = { ...def, ...raw, box_connected: raw.box_connected === true };
      const vStyle = typeof globalThis.getWritingVisualStyle === 'function' ? globalThis.getWritingVisualStyle(merged) : merged;
      await renderer.prepareWritingCursorImage(vStyle);

      for (const sm of sampleCases) {
        const cueText = sm.useItemSample ? (it.sample_text_vi || sm.fallbackText) : sm.text;
        const singleCues = [{ start: sm.start, end: sm.end, text: cueText, _timeUnit: 'sec' }];
        const withWords = globalThis.ReelsSubtitleProcessor.srtToSegmentsWithWords(singleCues);
        const segments = globalThis.ReelsSubtitleProcessor.smartSegmentation(withWords, vStyle, W, sm.end);
        renderer.setContextSegments(segments, cueText);
        const seg = segments.find((s) => sm.t >= s.start && sm.t <= s.end) || segments[0];
        ctxFg.clearRect(0, 0, W, H);
        if (seg) {
          renderer.renderSubtitle(vStyle, seg, sm.t, W, H, false, false);
        }
        const clipInfo = scanCanvasAlphaClipping(ctxFg, W, H);
        if (clipInfo.clipped) itemOut.clipped_any = true;
        ctxOut.clearRect(0, 0, W, H);
        if (bgImg) ctxOut.drawImage(bgImg, 0, 0, W, H);
        else { ctxOut.fillStyle = '#d4d4d8'; ctxOut.fillRect(0, 0, W, H); }
        ctxOut.drawImage(canvasFg, 0, 0);
        const outPng = path.join(outDir, `tile_${i}_${sm.tag}.png`);
        fs.writeFileSync(outPng, canvasOut.toBuffer('image/png'));
        itemOut.tiles.push({ tag: sm.tag, path: outPng, ...clipInfo });
      }
    }
    results.push(itemOut);
  }

  console.log(JSON.stringify({ ok: true, results }));
}

main().catch((err) => {
  console.error(JSON.stringify({ ok: false, error: err?.message || String(err), stack: err?.stack }));
  process.exit(1);
});

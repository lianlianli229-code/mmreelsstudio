#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
10-Gate Parallel Animated Element (.webm VP9 yuva420p) QA Engine & Visual Contact Sheet Generator.

Enforces all user requirements:
- Always decodes WebM with `-c:v libvpx-vp9` BEFORE `-i` to preserve Alpha.
- Catches Frame-0 missing subject (e.g. dove flying in late), non-looping seams,
  outer border touches AND hidden internal flat-edge clip walls (e.g. E-074 y=46 flat cut),
  dark semi-transparent fringes, green spill, isolated dark dust specks, static motion,
  camera drift, and fake 360-degree wobble.
"""
import argparse
import json
import os
import subprocess
import sys
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

DEFAULT_STAGE_PHOTO = Path(r"C:\Users\Clara\reels-studio\public\stage-photo.jpg")


def _load_ui_font(size: int = 13) -> ImageFont.ImageFont:
    for cand in (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
    ):
        if Path(cand).exists():
            try:
                return ImageFont.truetype(cand, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def _load_stage_backdrop(size: int) -> Image.Image:
    if DEFAULT_STAGE_PHOTO.exists():
        return Image.open(DEFAULT_STAGE_PHOTO).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    return Image.new("RGBA", (size, size), (225, 228, 232, 255))


def _make_checkerboard(size: int, cell: int = 14) -> Image.Image:
    arr = np.zeros((size, size, 4), dtype=np.uint8)
    yy, xx = np.mgrid[0:size, 0:size]
    odd = ((xx // cell) + (yy // cell)) % 2 == 1
    arr[:, :, :3] = np.where(odd[:, :, None], 210, 242)
    arr[:, :, 3] = 255
    return Image.fromarray(arr, "RGBA")


def detect_element_mode(name_or_title: str, explicit_mode: str = "auto") -> str:
    if explicit_mode and explicit_mode != "auto":
        return explicit_mode
    s = name_or_title.lower()
    if "ae全屏" in s or "全屏" in s or "fullscreen" in s:
        return "fullscreen"
    if "360°" in s or "360度" in s or "360spin" in s:
        return "spin360"
    if "amen章" in s or "金匾" in s or "匾" in s or "横幅" in s or "plaque" in s:
        return "plaque"
    return "standalone"


def _run_stats_1d(arr_bool: np.ndarray) -> tuple[int, int, int]:
    if not np.any(arr_bool):
        return 0, 0, 0
    padded = np.concatenate(([False], arr_bool, [False]))
    diffs = np.diff(padded.astype(np.int8))
    starts = np.where(diffs == 1)[0]
    ends = np.where(diffs == -1)[0]
    runs = ends - starts
    return int(runs.max()), int(arr_bool.sum()), int((runs >= 10).sum())


def _max_contig_1d(arr_bool: np.ndarray) -> int:
    return _run_stats_1d(arr_bool)[0]


def _count_isolated_dark_specks(frame: np.ndarray) -> int:
    alpha = frame[:, :, 3]
    vis = (alpha > 20).astype(np.uint8)
    nc, lbl, st, centroids = cv2.connectedComponentsWithStats(vis, connectivity=8)
    if nc <= 2:
        return 0
    large_mask = np.zeros_like(vis)
    small_ids = []
    for k in range(1, nc):
        area = int(st[k, cv2.CC_STAT_AREA])
        if area >= 120:
            large_mask[lbl == k] = 1
        elif area <= 18:
            small_ids.append(k)
    if not small_ids or not np.any(large_mask):
        return 0
    near_main = cv2.dilate(large_mask, np.ones((25, 25), np.uint8)) > 0
    rgb_max = frame[:, :, :3].max(axis=2)
    specks = 0
    for k in small_ids:
        comp = lbl == k
        if np.any(comp & near_main):
            continue
        if float(rgb_max[comp].mean()) < 95.0:
            specks += 1
    return specks


def _measure_sharp_runs(alpha: np.ndarray) -> tuple[tuple[int, int, int, int], tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]] | None:
    h, w = alpha.shape
    ys, xs = np.where(alpha > 24)
    if len(xs) == 0:
        return None
    ymin, ymax, xmin, xmax = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())

    # Exact 1px extreme-line sharp step-cut signature on opaque foreground (>=180):
    # excludes semi-transparent starburst/glow tips while catching flat crop walls.
    in_t = alpha[ymin, :] >= 180
    out_t = (alpha[ymin - 1, :] <= 12) if ymin >= 1 else np.ones(w, dtype=bool)
    st_t = _run_stats_1d(in_t & out_t)

    in_b = alpha[ymax, :] >= 180
    out_b = (alpha[ymax + 1, :] <= 12) if ymax < h - 1 else np.ones(w, dtype=bool)
    st_b = _run_stats_1d(in_b & out_b)

    in_l = alpha[:, xmin] >= 180
    out_l = (alpha[:, xmin - 1] <= 12) if xmin >= 1 else np.ones(h, dtype=bool)
    st_l = _run_stats_1d(in_l & out_l)

    in_r = alpha[:, xmax] >= 180
    out_r = (alpha[:, xmax + 1] <= 12) if xmax < w - 1 else np.ones(h, dtype=bool)
    st_r = _run_stats_1d(in_r & out_r)

    return (ymin, ymax, xmin, xmax), (st_t, st_b, st_l, st_r)


def audit_single_webm(path: Path, explicit_mode: str = "auto") -> dict:
    mode = detect_element_mode(path.stem, explicit_mode)
    if explicit_mode == "auto" and mode == "standalone":
        meta_p = path.with_suffix(".json")
        if meta_p.exists():
            try:
                m_js = json.loads(meta_p.read_text(encoding="utf-8"))
                if m_js.get("spin_360"):
                    mode = "spin360"
                elif str(m_js.get("key_mode", "")).startswith("ae_l1_vfx") or (
                    int(m_js.get("width", 512)) != int(m_js.get("height", 512))
                    and int(m_js.get("height", 512)) >= 720
                ):
                    mode = "fullscreen"
            except Exception:
                pass
    gates_failed = []
    warnings = []
    metrics = {"size_kb": round(path.stat().st_size / 1024.0, 1), "mode": mode}

    try:
        probe_raw = subprocess.check_output(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,width,height,r_frame_rate,duration",
                "-show_entries", "format=duration",
                "-of", "json", str(path),
            ],
            stderr=subprocess.PIPE,
        )
        info = json.loads(probe_raw)
        st = (info.get("streams") or [{}])[0]
        codec = st.get("codec_name", "")
        w = int(st.get("width") or 0)
        h = int(st.get("height") or 0)
        dur = float(st.get("duration") or info.get("format", {}).get("duration") or 0.0)
        metrics["codec"] = codec
        metrics["resolution"] = f"{w}x{h}"
        metrics["duration_sec"] = round(dur, 2)
    except Exception as e:
        return {
            "id": path.stem.split("_")[0],
            "file": path.name,
            "path": str(path),
            "mode": mode,
            "status": "FAIL",
            "failed_gates": ["G01_FORMAT_ALPHA"],
            "warnings": [],
            "reasons": [f"FFPROBE_ERR:{e}"],
            "metrics": metrics,
        }

    if codec != "vp9" or w <= 0 or h <= 0:
        gates_failed.append("G01_FORMAT_ALPHA")
        return {
            "id": path.stem.split("_")[0],
            "file": path.name,
            "path": str(path),
            "mode": mode,
            "status": "FAIL",
            "failed_gates": gates_failed,
            "warnings": [],
            "reasons": [f"BAD_CODEC_OR_SIZE({codec},{w}x{h})"],
            "metrics": metrics,
        }

    # CRITICAL: -c:v libvpx-vp9 BEFORE -i to decode alpha channel!
    dec = subprocess.run(
        ["ffmpeg", "-v", "error", "-c:v", "libvpx-vp9", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
        capture_output=True,
    )
    if dec.returncode != 0 or not dec.stdout:
        gates_failed.append("G01_FORMAT_ALPHA")
        return {
            "id": path.stem.split("_")[0],
            "file": path.name,
            "path": str(path),
            "mode": mode,
            "status": "FAIL",
            "failed_gates": gates_failed,
            "warnings": [],
            "reasons": [f"VP9_DECODE_ERR:{dec.stderr.decode(errors='replace')[:120]}"],
            "metrics": metrics,
        }

    frame_bytes = w * h * 4
    n_frames = len(dec.stdout) // frame_bytes
    metrics["frames"] = n_frames
    if n_frames < 12:
        gates_failed.append("G01_FORMAT_ALPHA")
        return {
            "id": path.stem.split("_")[0],
            "file": path.name,
            "path": str(path),
            "mode": mode,
            "status": "FAIL",
            "failed_gates": gates_failed,
            "warnings": [],
            "reasons": [f"TOO_FEW_FRAMES({n_frames})"],
            "metrics": metrics,
        }

    frames = np.frombuffer(dec.stdout[: n_frames * frame_bytes], dtype=np.uint8).reshape(n_frames, h, w, 4)
    alphas = frames[:, :, :, 3]

    # G01: verify alpha channel is genuinely used (neither all transparent nor all opaque)
    areas = np.array([(a > 20).mean() for a in alphas], dtype=np.float32)
    med_area = float(np.median(areas))
    opaque_frac_f0 = float((alphas[0] > 250).mean())
    metrics["f0_area"] = round(float(areas[0]), 4)
    metrics["med_area"] = round(med_area, 4)
    if med_area < 0.005 or opaque_frac_f0 > 0.985:
        gates_failed.append("G01_FORMAT_ALPHA")
        warnings.append(f"G01_ALPHA_SUSPECT(med={med_area:.3f},opaque0={opaque_frac_f0:.3f})")

    # Sample ~24 frames across timeline for fast geometric/liveness metrics
    sample_step = max(1, n_frames // 24)
    sample_indices = sorted(set(list(range(0, n_frames, sample_step)) + [0, n_frames - 1]))

    bbox_ws, bbox_hs, cxs, cys = [], [], [], []
    outer_touch_frames = 0
    sharp_t_cnt = sharp_l_cnt = sharp_r_cnt = sharp_b_cnt = 0
    max_sharp = [0, 0, 0, 0]
    t_walls, l_walls, r_walls, b_walls = [], [], [], []

    for idx in sample_indices:
        a = alphas[idx]
        if (a[:3, :] > 24).sum() > 16 or (a[-3:, :] > 24).sum() > 16 or (a[:, :3] > 24).sum() > 16 or (a[:, -3:] > 24).sum() > 16:
            outer_touch_frames += 1

        ys, xs = np.where(a > 24)
        if len(xs) >= 16:
            bbox_ws.append(int(xs.max() - xs.min() + 1))
            bbox_hs.append(int(ys.max() - ys.min() + 1))
            cxs.append(float(xs.mean()))
            cys.append(float(ys.mean()))

        sr = _measure_sharp_runs(a)
        if sr is not None:
            (ymin, ymax, xmin, xmax), ((rt, tt, st), (rb, tb, sb), (rl, tl, sl), (rr, tr, sr_seg)) = sr
            max_sharp[0] = max(max_sharp[0], rt)
            max_sharp[1] = max(max_sharp[1], rb)
            max_sharp[2] = max(max_sharp[2], rl)
            max_sharp[3] = max(max_sharp[3], rr)
            if rt >= 30:
                sharp_t_cnt += 1
            if rl >= 30:
                sharp_l_cnt += 1
            if rr >= 30:
                sharp_r_cnt += 1
            if rb >= 30:
                sharp_b_cnt += 1
            if rt >= 24 or st >= 2:
                t_walls.append((ymin, rt, tt, st))
            if rl >= 24 or sl >= 2:
                l_walls.append((xmin, rl, tl, sl))
            if rr >= 24 or sr_seg >= 2:
                r_walls.append((xmax, rr, tr, sr_seg))
            if rb >= 24 or sb >= 2:
                b_walls.append((ymax, rb, tb, sb))

    # G02: Frame 0 full presence (catches dove flying in after F0 / wings popping out later)
    a0_ratio = float(areas[0]) / max(med_area, 1e-5)
    h0_ratio = (bbox_hs[0] / max(float(np.median(bbox_hs)), 1.0)) if bbox_hs else 1.0
    w0_ratio = (bbox_ws[0] / max(float(np.median(bbox_ws)), 1.0)) if bbox_ws else 1.0
    metrics["a0_ratio"] = round(a0_ratio, 3)
    if mode != "fullscreen":
        f0_fail = (a0_ratio < 0.78) or (areas[0] < 0.008) or (a0_ratio < 0.82 and ((h0_ratio < 0.68) or (mode != "spin360" and w0_ratio < 0.68)))
    else:
        f0_fail = (a0_ratio < 0.55) or (areas[0] < 0.004)
    if f0_fail:
        gates_failed.append("G02_F0_PRESENCE")

    # G03: Seamless loop continuity (F0 vs F_last relative to adjacent step motion)
    adj_a, adj_r = [], []
    pair_step = max(1, n_frames // 16)
    for i in range(0, n_frames - 1, pair_step):
        f_curr = frames[i].astype(np.float32)
        f_next = frames[i + 1].astype(np.float32)
        adj_a.append(float(np.mean(np.abs(f_curr[:, :, 3] - f_next[:, :, 3]))))
        ac = f_curr[:, :, 3:4] / 255.0
        an = f_next[:, :, 3:4] / 255.0
        adj_r.append(float(np.mean(np.abs(f_curr[:, :, :3] * ac - f_next[:, :, :3] * an))))

    adj_a_med = float(np.median(adj_a)) if adj_a else 0.0
    adj_r_med = float(np.median(adj_r)) if adj_r else 0.0

    f0 = frames[0].astype(np.float32)
    fl = frames[-1].astype(np.float32)
    loop_a = float(np.mean(np.abs(f0[:, :, 3] - fl[:, :, 3])))
    loop_r = float(np.mean(np.abs(f0[:, :, :3] * (f0[:, :, 3:4] / 255.0) - fl[:, :, :3] * (fl[:, :, 3:4] / 255.0))))
    metrics["loop_alpha_mae"] = round(loop_a, 2)
    metrics["adj_alpha_mae"] = round(adj_a_med, 2)
    metrics["loop_rgb_mae"] = round(loop_r, 2)

    if loop_a > max(4.2, adj_a_med * 4.2) or loop_r > max(6.5, adj_r_med * 5.0):
        gates_failed.append("G03_SEAMLESS_LOOP")

    # Extended True-Loop Forensics: catch crossfade double-ghosting, internal hard cuts, and literal ping-pong reverse
    if n_frames >= 10:
        vis_cnt = (alphas > 20).sum(axis=(1, 2)).astype(np.float32)
        semi_cnt = ((alphas > 20) & (alphas < 210)).sum(axis=(1, 2)).astype(np.float32)
        semi_frac = semi_cnt / np.maximum(1.0, vis_cnt)
        semi_p25 = float(np.percentile(semi_frac, 25))
        semi_max = float(np.max(semi_frac))
        semi_peak_f = int(np.argmax(semi_frac))
        semi_ratio = semi_max / max(semi_p25, 0.02)
        hump_frames = int((semi_frac > (semi_p25 + max(0.05, semi_p25 * 0.45))).sum())

        vis_med = float(np.median(vis_cnt))
        edge_on_spin = (mode == "spin360") and (float(vis_cnt[semi_peak_f]) < 0.68 * vis_med)
        if (
            (mode != "fullscreen")
            and (semi_max - semi_p25) >= 0.065
            and semi_ratio >= 1.50
            and 3 <= hump_frames <= int(n_frames * 0.48)
            and (not edge_on_spin or semi_max >= 0.28)
        ):
            gates_failed.append("G03_CROSSFADE_GHOST")

        small = frames[:, ::4, ::4, :].astype(np.float32)
        al_s = small[:, :, :, 3]
        pr_s = small[:, :, :, :3] * (al_s[:, :, :, None] / 255.0)
        adj_a_all = np.mean(np.abs(al_s - np.roll(al_s, -1, axis=0)), axis=(1, 2))
        adj_r_all = np.mean(np.abs(pr_s - np.roll(pr_s, -1, axis=0)), axis=(1, 2, 3))
        adj_a_med_all = float(np.median(adj_a_all))
        adj_r_med_all = float(np.median(adj_r_all))
        max_jump_fa = int(np.argmax(adj_a_all))
        max_jump_fr = int(np.argmax(adj_r_all))
        max_jump_a = float(adj_a_all[max_jump_fa])
        max_jump_r = float(adj_r_all[max_jump_fr])
        ra_jump = max_jump_a / max(adj_a_med_all, 0.15)
        rr_jump = max_jump_r / max(adj_r_med_all, 0.25)
        worst_jump_f = max_jump_fa if ra_jump >= rr_jump else max_jump_fr

        if mode == "fullscreen" and adj_a_med_all > 2.5:
            cut_fail = max_jump_a > max(12.0, adj_a_med_all * 3.0)
        else:
            cut_fail = (max_jump_a > max(4.2, adj_a_med_all * 3.6)) or (max_jump_r > max(6.5, adj_r_med_all * 4.2))
        if cut_fail:
            if worst_jump_f == n_frames - 1:
                if "G03_SEAMLESS_LOOP" not in gates_failed:
                    gates_failed.append("G03_SEAMLESS_LOOP")
            else:
                gates_failed.append("G03_INTERNAL_CUT")

        mirror_mae = None
        if mode != "fullscreen" and n_frames >= 12:
            ks = sorted(set(max(1, int(round(i * (n_frames // 2 - 1) / 18.0))) for i in range(1, 19)))
            q_step = max(1, n_frames // 12)
            base_amp_a = max(float(np.median([float(np.mean(np.abs(al_s[i] - al_s[(i + n_frames // 4) % n_frames]))) for i in range(0, n_frames, q_step)])), 0.4)
            base_amp_r = max(float(np.median([float(np.mean(np.abs(pr_s[i] - pr_s[(i + n_frames // 4) % n_frames]))) for i in range(0, n_frames, q_step)])), 0.4)
            best_pp_ratio = 9.9
            best_pp_piv = 0
            cand_pivs = sorted(set([0, n_frames // 4, n_frames // 2, (3 * n_frames) // 4] + list(range(0, n_frames, max(1, n_frames // 24)))))
            for piv in cand_pivs:
                for sh in (0, 1):
                    errs_a = [float(np.mean(np.abs(al_s[(piv + k) % n_frames] - al_s[(piv - sh - k) % n_frames]))) for k in ks]
                    errs_r = [float(np.mean(np.abs(pr_s[(piv + k) % n_frames] - pr_s[(piv - sh - k) % n_frames]))) for k in ks]
                    comb = max(float(np.median(errs_a)) / base_amp_a, float(np.median(errs_r)) / base_amp_r)
                    if comb < best_pp_ratio:
                        best_pp_ratio = comb
                        best_pp_piv = piv
            if best_pp_ratio < 0.25 and base_amp_r > 0.8:
                k_span = range(1, min(8, n_frames // 2))
                mirror_mae = min(
                    float(np.median([
                        float(np.mean(np.abs(
                            frames[(best_pp_piv + k) % n_frames].astype(np.float32)
                            - frames[(best_pp_piv - sh - k) % n_frames].astype(np.float32)
                        )))
                        for k in k_span
                    ]))
                    for sh in (0, 1)
                )
                if mirror_mae < 0.75:
                    gates_failed.append("G03_PINGPONG_REVERSE")

        seam_focus_frame = (
            semi_peak_f if "G03_CROSSFADE_GHOST" in gates_failed
            else (worst_jump_f if "G03_INTERNAL_CUT" in gates_failed else None)
        )
        metrics["semi_p25"] = round(semi_p25, 3)
        metrics["semi_max"] = round(semi_max, 3)
        metrics["semi_spike_ratio"] = round(semi_ratio, 2)
        metrics["semi_peak_f"] = semi_peak_f
        metrics["max_jump_a"] = round(max_jump_a, 2)
        metrics["max_jump_f"] = worst_jump_f
        metrics["pingpong_mirror_mae"] = round(mirror_mae, 3) if mirror_mae is not None else None
        metrics["seam_focus_frame"] = seam_focus_frame

    # G04: Motion liveness
    rgba_diffs = [
        float(np.mean(np.abs(frames[i].astype(np.float32) - frames[i + 1].astype(np.float32))))
        for i in range(0, n_frames - 1, pair_step)
    ]
    mean_motion = float(np.mean(rgba_diffs)) if rgba_diffs else 0.0
    metrics["mean_motion"] = round(mean_motion, 2)
    if mean_motion < 0.25:
        gates_failed.append("G04_MOTION_LIVENESS")
    elif mean_motion < 0.55:
        warnings.append(f"WEAK_MOTION({mean_motion:.2f})")

    # G05: Canvas border touch
    metrics["outer_touch_frames"] = outer_touch_frames
    if mode != "fullscreen" and outer_touch_frames >= 2:
        gates_failed.append("G05_BORDER_TOUCH")

    # G06: Hidden internal flat-edge clip wall detector (catches E-074 y=46 razor cut!)
    metrics["sharp_tlrb_cnt"] = [sharp_t_cnt, sharp_l_cnt, sharp_r_cnt, sharp_b_cnt]
    metrics["sharp_tlrb_max_px"] = max_sharp

    def _has_fixed_wall(walls: list[tuple[int, int, int, int]], dynamic_only: bool = False) -> bool:
        if not walls:
            return False
        if not dynamic_only:
            if any(mr >= 70 for _, mr, _, _ in walls):
                return True
            big_mr = [c for c, mr, _, _ in walls if mr >= 50]
            for c0 in set(big_mr):
                if sum(1 for c in big_mr if 0 <= c - c0 <= 2) >= 2:
                    return True
            multi_seg = [c for c, _, tot, nseg in walls if nseg >= 2 and tot >= 36]
            for c0 in set(multi_seg):
                if sum(1 for c in multi_seg if 0 <= c - c0 <= 2) >= 2:
                    return True
        all_coords = {c for c, _, _, _ in walls}
        min_tot_req = 40 if dynamic_only else 36
        min_span_req = 25 if dynamic_only else 24
        for c0 in all_coords:
            tots = [tot for c, _, tot, _ in walls if 0 <= c - c0 <= 2]
            if len(tots) >= 3 and max(tots) >= min_tot_req and (max(tots) - min(tots) >= min_span_req):
                return True
        return False

    if mode in ("standalone", "spin360"):
        l_check = [x for x in l_walls if x[0] < w * 0.30] if mode == "spin360" else l_walls
        r_check = [x for x in r_walls if x[0] > w * 0.70] if mode == "spin360" else r_walls
        if (
            _has_fixed_wall(t_walls, dynamic_only=False)
            or _has_fixed_wall(l_check, dynamic_only=False)
            or _has_fixed_wall(r_check, dynamic_only=False)
            or _has_fixed_wall(b_walls, dynamic_only=True)
        ):
            gates_failed.append("G06_INTERNAL_FLAT_CLIP")
    elif mode == "plaque":
        # For rectangular plaques, only fail if content clips dynamically across a fixed wall
        for side_walls in (t_walls, l_walls, r_walls, b_walls):
            hit_dyn = False
            for c0 in {c for c, _, _, _ in side_walls}:
                grp = [tot for c, _, tot, _ in side_walls if 0 <= c - c0 <= 2]
                if len(grp) >= 3 and (max(grp) - min(grp) >= 28):
                    hit_dyn = True
                    break
            if hit_dyn:
                gates_failed.append("G06_INTERNAL_FLAT_CLIP")
                break

    # G07: Camera lock & anti-drift (allow natural vertical wing-flap centroid oscillation <=14%)
    if mode in ("standalone", "spin360") and cxs and cys:
        cx_span = (max(cxs) - min(cxs)) / float(w)
        cy_span = (max(cys) - min(cys)) / float(h)
        area_growth = float(areas.max()) / max(med_area, 1e-4)
        metrics["centroid_drift"] = [round(cx_span, 3), round(cy_span, 3)]
        metrics["area_max_med_ratio"] = round(area_growth, 2)
        if cx_span > 0.085 or cy_span > 0.14 or (mode == "standalone" and area_growth > 1.90):
            gates_failed.append("G07_CAMERA_LOCK")

    # G08 & G09: Bright-backdrop dark fringe, green spill, and isolated dark specks
    key_indices = [0, n_frames // 2, max(0, int(n_frames * 0.85))]
    max_dark_fringe = 0.0
    max_green_spill = 0.0
    max_specks = 0
    for ki in key_indices:
        fr = frames[ki]
        a = fr[:, :, 3]
        semi = (a > 14) & (a < 185)
        if semi.sum() > 50:
            dark_r = float(((fr[:, :, :3].max(axis=2) < 55) & semi).sum()) / float(semi.sum())
            max_dark_fringe = max(max_dark_fringe, dark_r)

        band = (a > 14) & (a < 210)
        if band.sum() > 50:
            rf = fr[:, :, 0].astype(np.float32)
            gf = fr[:, :, 1].astype(np.float32)
            bf = fr[:, :, 2].astype(np.float32)
            g_exc = gf - np.maximum(rf, bf)
            op = a >= 220
            int_g = float(((g_exc > 18.0) & op).sum()) / max(1.0, float(op.sum())) if np.any(op) else 0.0
            if int_g >= 0.15:
                sp_mask = (g_exc > 52.0) & (gf > 155.0) & band
            else:
                sp_mask = (g_exc > 28.0) & (gf > 110.0) & band
            sp_r = float(sp_mask.sum()) / float(band.sum())
            max_green_spill = max(max_green_spill, sp_r)

        max_specks = max(max_specks, _count_isolated_dark_specks(fr))

    metrics["dark_fringe"] = round(max_dark_fringe, 3)
    metrics["green_spill"] = round(max_green_spill, 3)
    metrics["isolated_dark_specks"] = max_specks
    if max_dark_fringe > 0.24 or max_green_spill > 0.16:
        gates_failed.append("G08_BRIGHT_BG_FRINGE")
    if max_specks >= 8:
        gates_failed.append("G09_ISOLATED_SPECKS")

    # G10: True 360-degree unidirectional spin physics (short-stride optical flow + opaque-core width)
    if mode == "spin360":
        spin_idx = [int(round(i * (n_frames - 1) / 15.0)) for i in range(16)]
        ws_spin = []
        for si in spin_idx:
            a_s = frames[si][:, :, 3]
            ys_s, xs_s = np.where(a_s >= 180)
            if len(xs_s) == 0:
                ys_s, xs_s = np.where(a_s > 24)
            ws_spin.append(int(xs_s.max() - xs_s.min() + 1) if len(xs_s) else 0)

        flow_idx = [int(round(i * max(0, n_frames - 3) / 23.0)) for i in range(24)]
        dx_meds, diffs_spin = [], []
        for idx in flow_idx:
            jdx = min(n_frames - 1, idx + 2)
            if jdx <= idx:
                continue
            prev_fr = frames[idx]
            fr = frames[jdx]
            diffs_spin.append(float(np.mean(np.abs(fr.astype(np.float32) - prev_fr.astype(np.float32)))))
            g1 = cv2.cvtColor(prev_fr[:, :, :3], cv2.COLOR_RGB2GRAY)
            g2 = cv2.cvtColor(fr[:, :, :3], cv2.COLOR_RGB2GRAY)
            m = (prev_fr[:, :, 3] > 120) & (fr[:, :, 3] > 120)
            if m.sum() > 200:
                fl_of = cv2.calcOpticalFlowFarneback(g1, g2, None, 0.5, 3, 15, 3, 5, 1.2, 0)
                dx_meds.append(float(np.median(fl_of[:, :, 0][m])))

        pos_c = sum(1 for x in dx_meds if x > 0.12)
        neg_c = sum(1 for x in dx_meds if x < -0.12)
        dom_r = max(pos_c, neg_c) / max(1, pos_c + neg_c)

        w_max = max(1, max(ws_spin))
        w_ratios = [ww / float(w_max) for ww in ws_spin]
        troughs = 0
        in_tr = False
        for wr in w_ratios:
            if wr < 0.65 and not in_tr:
                troughs += 1
                in_tr = True
            elif wr >= 0.74:
                in_tr = False

        sp_cv = float(np.std(diffs_spin) / max(0.01, float(np.mean(diffs_spin)))) if diffs_spin else 1.0
        is_axisym = any(k in path.stem for k in ("圣体爵", "金爵", "圣杯", "花瓶"))
        metrics["spin_dom_ratio"] = round(dom_r, 3)
        metrics["spin_troughs"] = troughs
        metrics["spin_speed_cv"] = round(sp_cv, 3)
        if is_axisym:
            if dom_r < 0.78 or (pos_c + neg_c) < 10 or sp_cv > 0.55:
                gates_failed.append("G10_SPIN360_PHYSICS")
        else:
            if dom_r < 0.78 or (pos_c + neg_c) < 10 or troughs < 2 or sp_cv > 0.52:
                gates_failed.append("G10_SPIN360_PHYSICS")

    status = "PASS" if not gates_failed else "FAIL"
    return {
        "id": path.stem.split("_")[0],
        "file": path.name,
        "path": str(path),
        "mode": mode,
        "status": status,
        "failed_gates": gates_failed,
        "warnings": warnings,
        "metrics": metrics,
    }


def render_contact_sheet(results: list[dict], out_sheet: Path, thumb: int = 160) -> None:
    if not results:
        return
    pcts = [0.0, 0.09, 0.25, 0.50, 0.70, 0.85, 0.96]
    bg_tile = _load_stage_backdrop(thumb)
    chk_tile = _make_checkerboard(thumb)
    font_body = _load_ui_font(12)
    font_hdr = _load_ui_font(11)
    info_w = 295
    cols = len(pcts) + 1
    row_h = thumb + 30
    sheet_w = info_w + cols * (thumb + 6) + 8
    sheet_h = len(results) * row_h + 8

    sheet = Image.new("RGB", (sheet_w, sheet_h), (18, 22, 32))
    dr = ImageDraw.Draw(sheet)

    safe_lo = int(round(46.0 / 512.0 * thumb))
    safe_hi = int(round(466.0 / 512.0 * thumb))

    for r_idx, item in enumerate(results):
        y0 = r_idx * row_h + 6
        is_pass = item["status"] == "PASS"
        badge_col = (74, 222, 128) if is_pass else (248, 113, 113)
        m = item.get("metrics", {})
        status_msg = (
            "FAIL: " + ", ".join(item["failed_gates"])
            if item["failed_gates"]
            else ("WARN: " + ", ".join(item["warnings"]) if item["warnings"] else "ALL 10 GATES CLEAN")
        )
        wrapped_status = textwrap.wrap(status_msg, width=38)[:3]
        info_lines = [
            f"{item['status']} | {item['id']} [{item['mode']}]",
            item["file"][:24],
            f"{m.get('frames','?')}f {m.get('duration_sec','?')}s | {m.get('size_kb','?')}KB",
            f"a0R={m.get('a0_ratio','?')} loopA={m.get('loop_alpha_mae','?')} semi={m.get('semi_p25','?')}->{m.get('semi_max','?')}",
            f"mot={m.get('mean_motion','?')} sharp={m.get('sharp_tlrb_max_px','?')}",
            *wrapped_status,
        ]
        dr.text((10, y0 + 6), "\n".join(info_lines), fill=badge_col, font=font_body)

        path = Path(item["path"])
        dur = max(0.2, float(m.get("duration_sec") or 3.0))
        tot_f = max(1, int(m.get("frames") or round(dur * 24.0)))
        seam_f = m.get("seam_focus_frame")
        for c_idx, pct in enumerate(pcts):
            if c_idx == 1 and seam_f is not None:
                sf_idx = max(0, min(tot_f - 1, int(seam_f)))
                ts = round(sf_idx / float(tot_f) * dur, 2)
                ff_cmd = [
                    "ffmpeg", "-y", "-loglevel", "error", "-c:v", "libvpx-vp9",
                    "-i", str(path), "-vf", f"select=eq(n\\,{sf_idx})", "-frames:v", "1",
                    "-f", "rawvideo", "-pix_fmt", "rgba", "-",
                ]
                col_hdr = f"SEAM f{sf_idx} ({ts:.2f}s)"
                hdr_col = (251, 146, 60)
            else:
                ts = round(max(0.0, dur * pct - (0.04 if pct > 0.9 else 0.0)), 2)
                ff_cmd = [
                    "ffmpeg", "-y", "-loglevel", "error", "-c:v", "libvpx-vp9",
                    "-ss", f"{ts:.2f}", "-i", str(path), "-frames:v", "1",
                    "-f", "rawvideo", "-pix_fmt", "rgba", "-",
                ]
                col_hdr = f"{int(pct * 100)}% ({ts:.2f}s)"
                hdr_col = (203, 213, 225)
            dec = subprocess.run(ff_cmd, capture_output=True)
            x0 = info_w + c_idx * (thumb + 6)
            if dec.returncode == 0 and len(dec.stdout) >= 4:
                res_str = m.get("resolution", "512x512")
                rw, rh = [int(v) for v in res_str.split("x")]
                if len(dec.stdout) >= rw * rh * 4:
                    arr = np.frombuffer(dec.stdout[: rw * rh * 4], dtype=np.uint8).reshape(rh, rw, 4)
                    fg = Image.fromarray(arr, "RGBA").resize((thumb, thumb), Image.Resampling.LANCZOS)
                    comp = Image.alpha_composite(bg_tile.copy(), fg).convert("RGB")
                    cd = ImageDraw.Draw(comp)
                    cd.rectangle([0, 0, thumb - 1, thumb - 1], outline=(239, 68, 68), width=1)
                    if item["mode"] != "fullscreen":
                        cd.rectangle([safe_lo, safe_lo, safe_hi, safe_hi], outline=(34, 211, 238), width=1)
                    sheet.paste(comp, (x0, y0 + 20))
                    if c_idx == 3:
                        chk_comp = Image.alpha_composite(chk_tile.copy(), fg).convert("RGB")
                        sheet.paste(chk_comp, (info_w + len(pcts) * (thumb + 6), y0 + 20))
                        dr.text((info_w + len(pcts) * (thumb + 6) + 4, y0 + 3), "50% CHK", fill=(250, 204, 21), font=font_hdr)
            dr.text((x0 + 4, y0 + 3), col_hdr, fill=hdr_col, font=font_hdr)

    out_sheet.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_sheet, quality=92)


def main():
    ap = argparse.ArgumentParser(description="10-Gate Parallel WebM Alpha Element QA")
    ap.add_argument("--input", required=True, help="Input .webm file or directory")
    ap.add_argument("--glob", default="E-*.webm", help="Glob when --input is a directory")
    ap.add_argument("--mode", default="auto", choices=["auto", "standalone", "spin360", "fullscreen", "plaque"])
    ap.add_argument("--sheet", default=None, help="Output bright-bg contact sheet .jpg path")
    ap.add_argument("--json", dest="json_out", default=None, help="Output JSON report path")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    t0 = time.time()
    inp = Path(args.input)
    if inp.is_file():
        files = [inp]
    elif inp.is_dir():
        files = sorted(inp.glob(args.glob))
    else:
        raise SystemExit(f"Input not found: {inp}")

    if not files:
        raise SystemExit(f"No matching files found in {inp} ({args.glob})")

    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, len(files)))) as ex:
        results = list(ex.map(lambda p: audit_single_webm(p, args.mode), files))

    if args.sheet:
        render_contact_sheet(results, Path(args.sheet))

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = len(results) - passed
    report = {
        "ok": failed == 0,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "elapsed_sec": round(time.time() - t0, 2),
        "sheet": str(args.sheet) if args.sheet else None,
        "results": results,
    }

    if args.json_out:
        jp = Path(args.json_out)
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()


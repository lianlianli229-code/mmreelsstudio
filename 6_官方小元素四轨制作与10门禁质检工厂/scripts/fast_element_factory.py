#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fast Animated Element Production Factory (`fast_element_factory.py`).

Four production subcommands:
1. prep-still      : Strip noisy margins & center still into native aspect pure #00FF00 or #000000 with tight 8-12% safe margins.
2. build-from-video: Trim AI MP4, compute ALL-FRAME union bbox, fit into 420x420 safe box [46,466],
                     run bright-bg keyer, CC despeckle, un-premul bright lift, seamless loop,
                     4px RGB edge dilation, encode VP9 yuva420p, and auto-run 10-gate QA.
3. build-procedural: Generate a guaranteed-seamless 24fps 72-frame (3.00s) VP9 yuva420p loop from a clean still,
                     encode with 4px RGB edge dilation, and auto-run 10-gate QA.
4. build-packaging : Render Track A+ AE/Skia packaging or 3D 360-spin loop via @napi-rs/canvas + auto QA.
"""
import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fast_element_qa as qa  # noqa: E402

DEFAULT_STAGE_PHOTO = Path(r"C:\Users\Clara\reels-studio\public\stage-photo.jpg")
SAFE_MIN = 46
SAFE_MAX = 466  # 420x420 safe box inside 512x512
N_PROC_FRAMES = 72
FPS = 24

_REMBG_SESS = None
_KERN_3 = np.ones((3, 3), np.uint8)
_KERN_5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
_KERN_7 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
_KERN_9 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
_KERN_11 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
_YY512, _XX512 = np.mgrid[0:512, 0:512].astype(np.float32)


def _get_rembg_session():
    global _REMBG_SESS
    if _REMBG_SESS is None:
        from rembg import new_session
        _REMBG_SESS = new_session("isnet-general-use")
    return _REMBG_SESS


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(65536), b""):
            h.update(ch)
    return h.hexdigest()


def dilate_rgb_4px(rgba: np.ndarray, radius: float = 4.5) -> np.ndarray:
    """Fill alpha <= 5 pixels within ~4px of alpha > 20 with nearest foreground RGB (alpha stays 0)."""
    out = rgba.copy()
    a = out[:, :, 3]
    fg = a > 20
    if not np.any(fg):
        return out
    inv = (~fg).astype(np.uint8)
    dist, labels = cv2.distanceTransformWithLabels(inv, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    ys_fg, xs_fg = np.where(fg)
    lut_y = np.zeros(int(labels.max()) + 1, dtype=np.int32)
    lut_x = np.zeros(int(labels.max()) + 1, dtype=np.int32)
    fg_lbl = labels[ys_fg, xs_fg]
    lut_y[fg_lbl] = ys_fg
    lut_x[fg_lbl] = xs_fg

    fill_mask = (a <= 5) & (dist > 0.0) & (dist <= radius)
    fy_idx, fx_idx = np.where(fill_mask)
    fl = labels[fy_idx, fx_idx]
    out[fy_idx, fx_idx, :3] = out[lut_y[fl], lut_x[fl], :3]
    far = (a <= 5) & (dist > radius)
    out[far, :3] = 0
    return out


def enforce_safe_bounds(rgba: np.ndarray) -> np.ndarray:
    out = rgba.copy()
    mask_out = (_XX512 < SAFE_MIN) | (_XX512 >= SAFE_MAX) | (_YY512 < SAFE_MIN) | (_YY512 >= SAFE_MAX)
    out[mask_out] = 0
    return out


def remove_small_components(alpha_f: np.ndarray, min_area: int = 40, thresh: float = 0.06) -> np.ndarray:
    vis = (alpha_f > thresh).astype(np.uint8)
    nc, lbl, st, _ = cv2.connectedComponentsWithStats(vis, connectivity=8)
    if nc <= 1:
        return alpha_f
    keep = np.zeros_like(vis, dtype=bool)
    for k in range(1, nc):
        if int(st[k, cv2.CC_STAT_AREA]) >= min_area:
            keep |= lbl == k
    keep_dil = cv2.dilate(keep.astype(np.uint8), _KERN_3) > 0
    return np.where(keep_dil, alpha_f, 0.0)


def unpremul_and_bright_lift(
    rgba: np.ndarray,
    lift_white: bool = False,
    lift_warm_fire: bool = False,
    despill_green: bool = False,
) -> np.ndarray:
    a = rgba[:, :, 3].astype(np.float32) / 255.0
    arr = rgba[:, :, :3].astype(np.float32)
    semi = (a > 0.02) & (a < 0.96)
    unp = np.clip(arr / np.maximum(a[:, :, None], 0.30), 0.0, 255.0)
    rgb = np.where(semi[:, :, None], unp, arr)

    if despill_green:
        rb_max = np.maximum(rgb[:, :, 0], rgb[:, :, 2])
        g_exc = rgb[:, :, 1] - rb_max
        spill = (a > 0.02) & ((g_exc > 3.0) | (semi & (rgb[:, :, 1] > rb_max)))
        rgb[:, :, 1] = np.where(spill, np.minimum(rgb[:, :, 1], rb_max), rgb[:, :, 1])

    if lift_white:
        r2, g2, b2 = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
        mx2 = np.max(rgb, axis=2)
        white_tip = (a > 0.02) & (a < 0.94) & (np.abs(r2 - b2) < 38.0) & (mx2 < 220.0) & (mx2 > 50.0)
        t_alpha = np.clip((0.94 - a) / 0.65, 0.0, 1.0)
        t_luma = np.clip((224.0 - mx2) / 145.0, 0.0, 1.0)
        t = np.where(white_tip, 0.72 * t_alpha * t_luma, 0.0)
        rgb[:, :, 0] = rgb[:, :, 0] * (1.0 - t) + 255.0 * t
        rgb[:, :, 1] = rgb[:, :, 1] * (1.0 - t) + 252.0 * t
        rgb[:, :, 2] = rgb[:, :, 2] * (1.0 - t) + 246.0 * t

    if lift_warm_fire:
        r2, _, b2 = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
        mx2 = np.max(rgb, axis=2)
        warm_edge = (a > 0.02) & (a < 0.90) & (r2 >= b2 + 16.0)
        if lift_white:
            warm_edge = warm_edge & (np.abs(r2 - b2) >= 38.0)
        t_f = np.where(warm_edge, np.clip((0.90 - a) / 0.70, 0.0, 1.0), 0.0)
        r_new = np.where(warm_edge, rgb[:, :, 0] * (1.0 - 0.80 * t_f) + 255.0 * (0.80 * t_f), rgb[:, :, 0])
        g_target = np.minimum(r_new * 0.58, np.maximum(rgb[:, :, 1], 115.0))
        g_new = np.where(warm_edge, rgb[:, :, 1] * (1.0 - 0.70 * t_f) + g_target * (0.70 * t_f), rgb[:, :, 1])
        rgb[:, :, 0] = r_new
        rgb[:, :, 1] = g_new
        core = mx2 > 225.0
        rgb = np.where(core[:, :, None] & (~semi[:, :, None]), arr, rgb)

    out = np.zeros_like(rgba)
    vis = a > 0.015
    out[:, :, :3] = np.where(vis[:, :, None], np.clip(rgb, 0.0, 255.0), 0.0).astype(np.uint8)
    out[:, :, 3] = np.where(vis, np.clip(a * 255.0, 0.0, 255.0), 0.0).astype(np.uint8)
    return out


# ── Proven Keyers ────────────────────────────────────────────────────────────

def key_green_dove(rgb: np.ndarray, has_gold: bool = True) -> np.ndarray:
    arr = rgb.astype(np.float32)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    rb_max = np.maximum(r, b)
    g_exc = g - rb_max

    plumage_neutral = (np.abs(r - b) < 48.0) & (b > 75.0)
    alpha_screen = 1.0 - np.clip((g_exc - 10.0) / 48.0, 0.0, 1.0)
    solid_feather = (b >= 155.0) & (r >= 155.0) & (g_exc < 34.0)
    alpha = np.where(solid_feather, 1.0, alpha_screen)

    rose_or_beak = (r > b + 24.0) & (r > g + 12.0)
    dark_eye = (np.max(arr, axis=2) < 92.0) & (g_exc < 15.0)
    alpha = np.where(rose_or_beak | dark_eye, np.maximum(alpha, 0.96), alpha)

    if not has_gold:
        yellow_halo = (~plumage_neutral) & (~dark_eye) & (~rose_or_beak) & (r > b + 24.0) & (g > b + 16.0)
        alpha = np.where(yellow_halo, 0.0, alpha)
    else:
        is_gold_glow = (~plumage_neutral) & (~dark_eye) & (r > 70.0) & (b < 135.0)
        gold_alpha = np.clip((r - 122.0) / 112.0, 0.0, 1.0) ** 1.38
        gold_alpha = np.where((r > 198.0) & (r > b + 42.0), 1.0, gold_alpha)
        alpha = np.where(is_gold_glow, gold_alpha, alpha)
        alpha = np.where((~is_gold_glow) & (~plumage_neutral) & (~rose_or_beak) & (~dark_eye) & (g_exc > 26.0), 0.0, alpha)

    alpha = remove_small_components(np.clip(alpha, 0.0, 1.0), min_area=36, thresh=0.06)
    rgba = np.zeros((rgb.shape[0], rgb.shape[1], 4), dtype=np.uint8)
    rgba[:, :, :3] = rgb
    rgba[:, :, 3] = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    return unpremul_and_bright_lift(rgba, lift_white=True, lift_warm_fire=has_gold, despill_green=True)


def key_green_wreath(rgb: np.ndarray) -> np.ndarray:
    arr = rgb.astype(np.float32)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    rb_max = np.maximum(r, b)
    g_exc = g - rb_max

    warm_petal_protect = (r > 130.0) & (r > b + 48.0)
    bg_seed = (
        ((g > 140.0) & (g_exc > 48.0))
        | ((g > 132.0) & (g_exc > 42.0) & (b < 82.0))
        | ((g > 112.0) & (g > 1.56 * rb_max + 18.0) & (b < 75.0))
    ) & (~warm_petal_protect)
    bg_u8 = cv2.morphologyEx(bg_seed.astype(np.uint8), cv2.MORPH_OPEN, _KERN_3)
    bg_dil = cv2.dilate(bg_u8, _KERN_9, iterations=1) > 0
    bg_core = bg_u8 > 0
    border_band = bg_dil & (~bg_core)

    alpha = np.ones(r.shape, dtype=np.float32)
    alpha[bg_core] = 0.0
    edge_a = 1.0 - np.clip((g_exc - 5.0) / 38.0, 0.0, 1.0)
    warm_gold_edge = (r > b + 28.0) & (r > 115.0)
    edge_a = np.where(warm_gold_edge, np.maximum(edge_a, np.clip((r - b) / 85.0, 0.72, 1.0)), edge_a)
    alpha = np.where(border_band, edge_a, alpha)

    g_out = np.where(border_band & (g > rb_max), rb_max, g)
    olive_edge = border_band & (alpha < 0.90) & (g > r * 0.88) & (b < 92.0)
    g_out = np.where(olive_edge, np.minimum(g_out, r * 0.86), g_out)
    washed_petal = (r > 125.0) & (r > b + 40.0) & (g_out > r * 0.88)
    g_out = np.where(washed_petal, np.minimum(g_out, r * 0.84), g_out)

    alpha = remove_small_components(np.where(alpha < 0.04, 0.0, np.clip(alpha, 0.0, 1.0)), min_area=36)
    rgba = np.zeros((rgb.shape[0], rgb.shape[1], 4), dtype=np.uint8)
    rgba[:, :, 0] = np.clip(r, 0, 255).astype(np.uint8)
    rgba[:, :, 1] = np.clip(g_out, 0, 255).astype(np.uint8)
    rgba[:, :, 2] = np.clip(b, 0, 255).astype(np.uint8)
    rgba[:, :, 3] = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    return unpremul_and_bright_lift(rgba, lift_white=False, lift_warm_fire=False, despill_green=False)


def key_green_solid(rgb: np.ndarray) -> np.ndarray:
    arr = rgb.astype(np.float32)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    rb_max = np.maximum(r, b)
    g_exc = g - rb_max
    bright_gate = np.clip((g - 95.0) / 34.0, 0.0, 1.0)
    alpha = 1.0 - np.clip((g_exc - 6.0) / 24.0, 0.0, 1.0) * bright_gate
    alpha = remove_small_components(np.clip(alpha, 0.0, 1.0), min_area=36)
    rgba = np.zeros((rgb.shape[0], rgb.shape[1], 4), dtype=np.uint8)
    rgba[:, :, :3] = rgb
    rgba[:, :, 3] = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    return unpremul_and_bright_lift(rgba, lift_white=False, lift_warm_fire=False, despill_green=True)


def key_black_ai_luma(rgb: np.ndarray, is_fire: bool = False) -> np.ndarray:
    from rembg import remove

    arr = rgb.astype(np.float32)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    mx = np.max(arr, axis=2)

    seg = np.array(remove(Image.fromarray(rgb), session=_get_rembg_session()))
    ai_raw = seg[:, :, 3].astype(np.float32) / 255.0
    ai_closed = cv2.morphologyEx(ai_raw, cv2.MORPH_CLOSE, _KERN_7)
    ai_eroded = cv2.erode(ai_closed, _KERN_5, iterations=1)

    wing_ivory = np.clip((mx - 102.0) / 68.0, 0.0, 1.0) * np.clip((b - 56.0) / 36.0, 0.0, 1.0)
    wing_solid = cv2.erode(((mx > 132.0) & (b > 76.0)).astype(np.uint8), _KERN_5, iterations=1) > 0
    ruby_mask = (ai_closed > 0.65) & (r > g + 36.0) & (r > b + 36.0) & (r > 52.0)
    deep_solid = ((ai_eroded > 0.82) & (mx > 125.0)) | ruby_mask | ((ai_eroded > 0.70) & (mx > 185.0)) | wing_solid

    emblem_hull = cv2.dilate(((ai_raw > 0.28) | (wing_ivory > 0.35)).astype(np.uint8), _KERN_11, iterations=1) > 0
    flame_color = (r > b + 30.0) & (g > b + 10.0)
    if is_fire:
        glow = np.where(emblem_hull & (flame_color | (mx > 90.0)), np.clip((mx - 42.0) / 138.0, 0.0, 1.0) ** 1.18, 0.0)
    else:
        glow = np.where(emblem_hull & flame_color, np.clip((mx - 110.0) / 115.0, 0.0, 1.0) ** 1.15, 0.0)

    alpha = np.maximum(np.maximum(ai_raw, wing_ivory), glow)
    alpha[deep_solid] = 1.0

    # CC despeckle against main emblem hull
    core_bin = cv2.morphologyEx((alpha > 0.14).astype(np.uint8), cv2.MORPH_OPEN, _KERN_3)
    nc, lbl_c, st_c, _ = cv2.connectedComponentsWithStats(core_bin)
    if nc > 1:
        main_c = 1 + int(np.argmax(st_c[1:, cv2.CC_STAT_AREA]))
        main_hull = cv2.dilate((lbl_c == main_c).astype(np.uint8), _KERN_7) > 0
    else:
        main_hull = np.ones(alpha.shape, dtype=bool)

    cc_bin = (alpha > 0.05).astype(np.uint8)
    n_cc, lbl_cc, st_cc, _ = cv2.connectedComponentsWithStats(cc_bin)
    keep = np.zeros(alpha.shape, dtype=bool)
    for k in range(1, n_cc):
        area = int(st_cc[k, cv2.CC_STAT_AREA])
        comp_m = lbl_cc == k
        if area >= 150 and np.any(comp_m & main_hull):
            keep |= comp_m
    alpha = np.where(keep, alpha, 0.0)

    rgba = np.zeros((rgb.shape[0], rgb.shape[1], 4), dtype=np.uint8)
    rgba[:, :, :3] = rgb
    rgba[:, :, 3] = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    return unpremul_and_bright_lift(rgba, lift_white=True, lift_warm_fire=True, despill_green=False)


KEYER_MAP = {
    "green_dove": lambda rgb: key_green_dove(rgb, has_gold=True),
    "green_dove_pure": lambda rgb: key_green_dove(rgb, has_gold=False),
    "green_wreath": key_green_wreath,
    "green_solid": key_green_solid,
    "black_ai_luma": lambda rgb: key_black_ai_luma(rgb, is_fire=False),
    "black_fire": lambda rgb: key_black_ai_luma(rgb, is_fire=True),
}


def _warp_rgba(rgba: np.ndarray, flow: np.ndarray, scale: float) -> np.ndarray:
    h, w = rgba.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    map_x = xx - scale * flow[:, :, 0]
    map_y = yy - scale * flow[:, :, 1]
    return cv2.remap(
        rgba.astype(np.float32),
        map_x,
        map_y,
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0.0, 0.0, 0.0, 0.0),
    )


def _morph_rgba_pair(f0: np.ndarray, f1: np.ndarray, alpha_t: float, dis) -> np.ndarray:
    g0 = cv2.cvtColor(f0[:, :, :3], cv2.COLOR_RGB2GRAY)
    g1 = cv2.cvtColor(f1[:, :, :3], cv2.COLOR_RGB2GRAY)
    flow_01 = dis.calc(g0, g1, None)
    flow_10 = dis.calc(g1, g0, None)
    w0 = _warp_rgba(f0, flow_01, alpha_t)
    w1 = _warp_rgba(f1, flow_10, 1.0 - alpha_t)

    a0 = w0[:, :, 3:4] / 255.0
    a1 = w1[:, :, 3:4] / 255.0
    p0 = w0[:, :, :3] * a0
    p1 = w1[:, :, :3] * a1
    a_out = (1.0 - alpha_t) * a0 + alpha_t * a1
    p_out = (1.0 - alpha_t) * p0 + alpha_t * p1
    rgb_out = np.where(a_out > 1e-4, np.clip(p_out / np.maximum(a_out, 1e-4), 0.0, 255.0), 0.0)
    out = np.zeros_like(f0)
    out[:, :, :3] = rgb_out.astype(np.uint8)
    out[:, :, 3] = np.clip(a_out[:, :, 0] * 255.0, 0, 255).astype(np.uint8)
    return out


def find_best_loop_cycle_and_morph(
    frames_rgba: list[np.ndarray],
    min_len: int = 48,
    max_len: int = 120,
    morph_k: int = 4,
) -> tuple[list[np.ndarray], dict]:
    """Find best natural pose+velocity cycle; fail loudly if none exists rather than faking crossfade."""
    n = len(frames_rgba)
    if n < min_len + 3:
        raise RuntimeError(f"NO_NATURAL_LOOP_CYCLE: need at least {min_len + 3} frames, got {n}")

    stack = np.stack(frames_rgba, axis=0)
    small = stack[:, ::4, ::4, :].astype(np.float32)
    al = small[:, :, :, 3:4]
    pr = small[:, :, :, :3] * (al / 255.0)
    vec = np.concatenate([pr, al], axis=-1)

    best = None
    for i in range(1, n - min_len - 1):
        j_lo = i + min_len
        j_hi = min(n - 2, i + max_len)
        if j_lo > j_hi:
            continue
        v_i = vec[i + 1] - vec[i - 1]
        targets = vec[j_lo : j_hi + 1]
        v_targets = vec[j_lo + 1 : j_hi + 2] - vec[j_lo - 1 : j_hi]
        pose_maes = np.mean(np.abs(targets - vec[i]), axis=(1, 2, 3))
        vel_maes = np.mean(np.abs(v_targets - v_i), axis=(1, 2, 3))
        alpha_maes = np.mean(np.abs(al[j_lo : j_hi + 1] - al[i]), axis=(1, 2, 3))
        scores = pose_maes + 0.6 * vel_maes
        k_best = int(np.argmin(scores))
        cand = (float(scores[k_best]), float(pose_maes[k_best]), float(alpha_maes[k_best]), float(vel_maes[k_best]), i, j_lo + k_best)
        if best is None or cand[0] < best[0]:
            best = cand

    if best is None:
        raise RuntimeError("NO_NATURAL_LOOP_CYCLE: search window empty")

    best_score, pose_mae, alpha_mae, vel_mae, i_best, j_best = best
    if pose_mae > 4.5 or alpha_mae > 3.5:
        raise RuntimeError(
            f"NO_NATURAL_LOOP_CYCLE: best pose_mae={pose_mae:.2f} (>4.5) or alpha_mae={alpha_mae:.2f} (>3.5) "
            f"at f{i_best}..f{j_best}; regenerate with start/end frame lock instead of faking crossfade."
        )

    cycle = [f.copy() for f in frames_rgba[i_best:j_best]]
    k_morph = 0
    if morph_k > 0 and pose_mae > 0.6 and i_best >= morph_k:
        k_morph = min(morph_k, len(cycle) // 6, i_best)
        if k_morph >= 1:
            dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
            for idx in range(k_morph):
                m_back = k_morph - idx
                t_blend = float(idx + 1) / float(k_morph + 1)
                tail_f = frames_rgba[j_best - m_back]
                head_prev_f = frames_rgba[i_best - m_back]
                cycle[len(cycle) - m_back] = _morph_rgba_pair(tail_f, head_prev_f, t_blend, dis)

    info = {
        "cycle_start": i_best,
        "cycle_end": j_best,
        "cycle_frames": len(cycle),
        "pose_mae": round(pose_mae, 3),
        "alpha_mae": round(alpha_mae, 3),
        "vel_mae": round(vel_mae, 3),
        "dis_morph_frames": k_morph,
    }
    return cycle, info


# ── Procedural 72-Frame Seamless VFX Helpers ─────────────────────────────────

def _composite_luminous_over(
    canvas_f: np.ndarray,
    cx: float,
    cy: float,
    patch_rgb: np.ndarray,
    patch_alpha: np.ndarray,
    additive_boost: float = 0.0,
    ss: int = 1,
):
    s_min = SAFE_MIN * ss
    s_max = SAFE_MAX * ss
    ph, pw = patch_alpha.shape
    x0_p = int(round(cx - pw * 0.5))
    y0_p = int(round(cy - ph * 0.5))
    cx0, cy0 = max(s_min, x0_p), max(s_min, y0_p)
    cx1, cy1 = min(s_max, x0_p + pw), min(s_max, y0_p + ph)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    px0, py0 = cx0 - x0_p, cy0 - y0_p
    px1, py1 = px0 + (cx1 - cx0), py0 + (cy1 - cy0)
    sa = np.clip(patch_alpha[py0:py1, px0:px1], 0.0, 1.0)[:, :, None]
    srgb = patch_rgb[py0:py1, px0:px1, :]
    dst = canvas_f[cy0:cy1, cx0:cx1, :]
    da = np.clip(dst[:, :, 3:4] / 255.0, 0.0, 1.0)
    drgb = dst[:, :, :3]
    out_a = sa + da * (1.0 - sa)
    num = srgb * sa + drgb * da * (1.0 - sa)
    out_rgb = np.where(out_a > 1e-4, num / np.maximum(out_a, 1e-4), 0.0)
    if additive_boost > 0.0:
        out_rgb = np.clip(out_rgb + srgb * (sa * da * additive_boost), 0.0, 255.0)
    canvas_f[cy0:cy1, cx0:cx1, :3] = np.clip(out_rgb, 0.0, 255.0)
    canvas_f[cy0:cy1, cx0:cx1, 3] = np.clip(out_a[:, :, 0] * 255.0, 0.0, 255.0)


def _draw_sparkle(canvas_f: np.ndarray, cx: float, cy: float, size: float, intensity: float, rgb_col=(255, 240, 170), ss: int = 1):
    if intensity <= 0.03 or size < 2.0:
        return
    s_min = SAFE_MIN * ss
    s_max = SAFE_MAX * ss
    r_max = int(math.ceil(size)) + 2 * ss
    x0, x1 = max(s_min, int(cx) - r_max), min(s_max, int(cx) + r_max + 1)
    y0, y1 = max(s_min, int(cy) - r_max), min(s_max, int(cy) + r_max + 1)
    if x1 <= x0 or y1 <= y0:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1]
    dx = np.abs(xx - cx)
    dy = np.abs(yy - cy)
    ray_h = np.exp(-dy * (1.1 / ss)) * np.exp(-dx / (size * 0.55))
    ray_v = np.exp(-dx * (1.1 / ss)) * np.exp(-dy / (size * 0.55))
    core = np.exp(-(dx * dx + dy * dy) / max(2.0 * ss * ss, (size * 0.24) ** 2))
    s = np.clip((ray_h + ray_v) * 0.72 + core * 1.12, 0.0, 1.0) * intensity
    patch = canvas_f[y0:y1, x0:x1]
    a0 = np.clip(patch[:, :, 3] / 255.0, 0.0, 1.0)
    a_out = np.clip(a0 + s * (1.0 - a0), 0.0, 1.0)
    safe_a = np.maximum(a_out, 1e-4)
    for ch in range(3):
        over_rgb = (patch[:, :, ch] * a0 + rgb_col[ch] * s * (1.0 - a0 * 0.15)) / safe_a
        opaque_bloom = np.clip(patch[:, :, ch] + s * rgb_col[ch] * 0.75, 0.0, 255.0)
        patch[:, :, ch] = np.clip(over_rgb * (1.0 - a0) + opaque_bloom * a0, 0.0, 255.0)
    patch[:, :, 3] = np.clip(a_out * 255.0, 0.0, 255.0)


def _fit_rgba_centered(rgba: np.ndarray, max_box: int = 388, canvas_size: int = 512) -> Image.Image:
    ys, xs = np.where(rgba[:, :, 3] > 20)
    if len(xs) == 0:
        return Image.fromarray(rgba, "RGBA").resize((canvas_size, canvas_size), Image.Resampling.LANCZOS)
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    sub = Image.fromarray(rgba[y0:y1, x0:x1], "RGBA")
    sc = min(max_box / float(sub.width), max_box / float(sub.height))
    tw, th = max(2, int(round(sub.width * sc))), max(2, int(round(sub.height * sc)))
    ox, oy = (canvas_size - tw) // 2, (canvas_size - th) // 2
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    canvas.paste(sub.resize((tw, th), Image.Resampling.LANCZOS), (ox, oy))
    return canvas


def _generate_procedural_frames(base_rgba: np.ndarray, preset: str, ss: int = 2) -> list[np.ndarray]:
    ss = max(1, min(2, int(ss)))
    S = 512 * ss
    s_min, s_max = SAFE_MIN * ss, SAFE_MAX * ss
    base_pil = _fit_rgba_centered(base_rgba, max_box=382 * ss, canvas_size=S)
    base_arr = np.array(base_pil, dtype=np.float32)

    if preset == "sacred_flames_aura":
        yy_s, xx_s = np.mgrid[0:S, 0:S].astype(np.float32)

    rng = np.random.default_rng(20261122)
    n_sp = 22
    sp_ang = rng.uniform(0, 2 * math.pi, n_sp)
    sp_rad = rng.uniform(90 * ss, 175 * ss, n_sp)
    sp_ph = rng.uniform(0, 2 * math.pi, n_sp)
    sp_sz = rng.uniform(10.0 * ss, 22.0 * ss, n_sp)

    n_pt = 18
    pt_x0 = rng.uniform(110 * ss, 402 * ss, n_pt)
    pt_ph = rng.uniform(0, 1.0, n_pt)
    pt_sz = rng.uniform(8.0 * ss, 15.0 * ss, n_pt)
    pt_sw = rng.uniform(6.0 * ss, 14.0 * ss, n_pt)

    frames = []
    for k in range(N_PROC_FRAMES):
        theta = 2.0 * math.pi * k / float(N_PROC_FRAMES)
        dy = 6.0 * ss * math.sin(theta)
        rot = 2.8 * math.sin(theta)
        sc = 1.0 + 0.025 * math.sin(theta)

        if preset in ("shimmer_sway", "halo_sparkles"):
            nw, nh = int(round(S * sc)), int(round(S * sc))
            scaled = base_pil.resize((nw, nh), Image.Resampling.LANCZOS)
            tmp = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            tmp.paste(scaled, ((S - nw) // 2, (S - nh) // 2 + int(round(dy))))
            rot_img = tmp.rotate(rot, resample=Image.Resampling.BICUBIC, center=(S / 2.0, S / 2.0))
            cf = np.array(rot_img, dtype=np.float32)
        elif preset == "sacred_flames_aura":
            y_map = yy_s + (4.0 * ss) * np.sin(theta + xx_s * (0.045 / ss))
            x_map = xx_s + (3.5 * ss) * np.sin(theta + yy_s * (0.05 / ss))
            warped = cv2.remap(base_arr, x_map.astype(np.float32), y_map.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
            pulse = 1.0 + 0.08 * math.sin(2.0 * theta)
            warped[:, :, :3] = np.clip(warped[:, :, :3] * pulse, 0, 255)
            cf = warped
        else:  # rising_petals_glow
            nw, nh = int(round(S * sc)), int(round(S * sc))
            scaled = base_pil.resize((nw, nh), Image.Resampling.LANCZOS)
            tmp = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            tmp.paste(scaled, ((S - nw) // 2, (S - nh) // 2 + int(round(dy * 0.7))))
            cf = np.array(tmp, dtype=np.float32)
            for j in range(n_pt):
                u = (pt_ph[j] + k / float(N_PROC_FRAMES)) % 1.0
                px = pt_x0[j] + pt_sw[j] * math.sin(2.0 * math.pi * u + j)
                py = 425.0 * ss - u * (330.0 * ss)
                pa = math.sin(u * math.pi) ** 0.7
                ps = int(max(6 * ss, round(pt_sz[j])))
                patch_a = np.zeros((ps, ps), dtype=np.float32)
                cv2.ellipse(patch_a, (ps // 2, ps // 2), (max(2, ps // 2 - 1), max(2, ps // 3)), int(u * 180), 0, 360, float(pa), -1)
                patch_rgb = np.zeros((ps, ps, 3), dtype=np.float32)
                patch_rgb[:, :, 0] = 255.0
                patch_rgb[:, :, 1] = 215.0 if j % 2 == 0 else 135.0
                patch_rgb[:, :, 2] = 110.0 if j % 2 == 0 else 165.0
                _composite_luminous_over(cf, px, py, patch_rgb, patch_a, additive_boost=0.25, ss=ss)

        for s_i in range(n_sp):
            ang = sp_ang[s_i] + 0.14 * math.sin(theta + sp_ph[s_i])
            rad = sp_rad[s_i] + 10.0 * ss * math.sin(theta + sp_ph[s_i])
            sx = (S / 2.0) + rad * math.cos(ang)
            sy = (S / 2.0) + rad * math.sin(ang)
            twinkle = max(0.0, 0.5 + 0.5 * math.sin(2.0 * theta + sp_ph[s_i])) ** 1.4
            _draw_sparkle(cf, sx, sy, sp_sz[s_i], twinkle * 0.9, ss=ss)

        cf[:s_min, :] = 0
        cf[s_max:, :] = 0
        cf[:, :s_min] = 0
        cf[:, s_max:] = 0
        rgba_hi = np.clip(cf, 0, 255).astype(np.uint8)
        if ss > 1:
            rgba_512 = np.array(Image.fromarray(rgba_hi, "RGBA").resize((512, 512), Image.Resampling.LANCZOS))
        else:
            rgba_512 = rgba_hi
        frames.append(enforce_safe_bounds(rgba_512))
    return frames


def _extract_still_rgba(still_path: Path, auto_key: str = "auto") -> np.ndarray:
    """Load an image, frame-0 of VP9 Alpha WebM, or frame-0 of MP4/MOV into clean straight RGBA."""
    sfx = still_path.suffix.lower()
    if sfx == ".webm":
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-c:v", "libvpx-vp9", "-i", str(still_path),
            "-vframes", "1", "-c:v", "png", "-pix_fmt", "rgba", "-f", "image2pipe", "-",
        ]
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0 or not proc.stdout:
            raise RuntimeError(f"Failed decoding WebM frame-0 ({still_path}): {proc.stderr.decode(errors='replace')}")
        from io import BytesIO
        im = Image.open(BytesIO(proc.stdout)).convert("RGBA")
        arr = np.array(im)
        a = remove_small_components(arr[:, :, 3].astype(np.float32) / 255.0, min_area=55, thresh=0.06)
        arr[:, :, 3] = np.clip(a * 255.0, 0, 255).astype(np.uint8)
        return arr

    if sfx in (".mp4", ".mov"):
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(still_path),
            "-vframes", "1", "-c:v", "png", "-pix_fmt", "rgba", "-f", "image2pipe", "-",
        ]
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0 or not proc.stdout:
            raise RuntimeError(f"Failed decoding video frame-0 ({still_path}): {proc.stderr.decode(errors='replace')}")
        from io import BytesIO
        im = Image.open(BytesIO(proc.stdout)).convert("RGBA")
    else:
        im = Image.open(still_path).convert("RGBA")
    arr = np.array(im)
    if auto_key == "none":
        return arr

    has_real_alpha = bool(np.mean(arr[[0, 0, -1, -1], [0, -1, 0, -1], 3] < 20) > 0.75 and np.any(arr[:, :, 3] > 200))
    if auto_key == "auto" and has_real_alpha:
        return arr

    rgb = arr[:, :, :3]
    if auto_key in KEYER_MAP:
        return KEYER_MAP[auto_key](rgb)

    from rembg import remove

    seg = np.array(remove(Image.fromarray(rgb), session=_get_rembg_session()))
    if auto_key == "rembg":
        return unpremul_and_bright_lift(seg, lift_white=False, lift_warm_fire=False, despill_green=False)

    # auto mode on opaque JPG/PNG: check corners to pick specialized chroma/rembg hybrid
    h, w = rgb.shape[:2]
    p = max(8, min(24, h // 20, w // 20))
    corners = np.concatenate([
        rgb[:p, :p].reshape(-1, 3),
        rgb[:p, -p:].reshape(-1, 3),
        rgb[-p:, :p].reshape(-1, 3),
        rgb[-p:, -p:].reshape(-1, 3),
    ], axis=0).astype(np.float32)
    c_med = np.median(corners, axis=0)
    c_std = float(np.mean(np.std(corners, axis=0)))
    g_exc = float(c_med[1] - max(c_med[0], c_med[2]))

    if g_exc > 38.0 and c_med[1] > 125.0:
        return key_green_solid(rgb)
    if float(np.max(c_med)) < 36.0 and c_std < 22.0:
        return key_black_ai_luma(rgb, is_fire=False)

    ai_a = seg[:, :, 3].astype(np.float32) / 255.0
    if c_std < 24.0:
        diff = np.max(np.abs(rgb.astype(np.float32) - c_med[None, None, :]), axis=2)
        bg_close = (diff < 22.0) & (ai_a < 0.72)
        ai_a = np.where(bg_close, 0.0, ai_a)
    ai_a = remove_small_components(np.clip(ai_a, 0.0, 1.0), min_area=48, thresh=0.06)
    out = np.zeros_like(arr)
    out[:, :, :3] = rgb
    out[:, :, 3] = np.clip(ai_a * 255.0, 0, 255).astype(np.uint8)
    return unpremul_and_bright_lift(out, lift_white=False, lift_warm_fire=False, despill_green=False)


def _encode_and_verify(
    eid: str,
    title: str,
    key_mode: str,
    frames_rgba: list[np.ndarray],
    out_dir: Path,
    sheet_path: Path | None,
    sync_dir: Path | None,
    width: int = 512,
    height: int = 512,
    fps: int = FPS,
    spin_360: bool = False,
    is_fullscreen: bool = False,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_webm = out_dir / f"{eid}.webm"
    out_poster = out_dir / f"{eid}.jpg"
    out_json = out_dir / f"{eid}.json"

    backdrop = (
        Image.open(DEFAULT_STAGE_PHOTO).convert("RGBA").resize((width, height), Image.Resampling.LANCZOS)
        if DEFAULT_STAGE_PHOTO.exists()
        else Image.new("RGBA", (width, height), (225, 228, 232, 255))
    )

    proc = subprocess.Popen(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
            "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
            "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-crf", "22", "-b:v", "0",
            "-auto-alt-ref", "0", "-deadline", "good", "-cpu-used", "4", str(out_webm),
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    mid = len(frames_rgba) // 2
    for i, raw_rgba in enumerate(frames_rgba):
        bounded = raw_rgba if (is_fullscreen or width != 512 or height != 512) else enforce_safe_bounds(raw_rgba)
        rgba = dilate_rgb_4px(bounded, radius=4.5)
        proc.stdin.write(rgba.tobytes())
        if i == mid:
            Image.alpha_composite(backdrop.copy(), Image.fromarray(rgba, "RGBA")).convert("RGB").save(out_poster, quality=90)
    proc.stdin.close()
    _, err = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg encode failed ({eid}): {err.decode(errors='replace')}")

    dur = round(len(frames_rgba) / float(fps), 2)
    meta = {
        "schema": "vn-alpha-element/1.0",
        "id": eid,
        "title": title,
        "kind": "element",
        "format": "webm_vp9_yuva420p",
        "width": int(width),
        "height": int(height),
        "fps": int(fps),
        "duration_sec": dur,
        "loop": True,
        "seamless_loop": True,
        "spin_360": bool(spin_360),
        "key_mode": key_mode,
        "stage_bg": "photo",
        "webm_url": f"/r2/webm/{eid}.webm",
        "poster_url": f"/r2/posters/{eid}.jpg",
    }
    out_json.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    h_out = sha256_file(out_webm)
    synced_path = None
    if sync_dir is not None:
        sync_dir.mkdir(parents=True, exist_ok=True)
        lc = sync_dir / f"{eid}_{title}.webm"
        for old in sync_dir.glob(f"{eid}_*.webm"):
            if old != lc:
                old.unlink()
        shutil.copy2(out_webm, lc)
        if sha256_file(lc) != h_out:
            raise RuntimeError(f"SHA256 mismatch syncing {lc}")
        synced_path = str(lc)

    qa_mode = "fullscreen" if is_fullscreen else ("spin360" if spin_360 else "auto")
    qa_res = qa.audit_single_webm(out_webm, explicit_mode=qa_mode)
    if sheet_path is not None:
        qa.render_contact_sheet([qa_res], sheet_path)

    return {
        "ok": qa_res["status"] == "PASS",
        "eid": eid,
        "webm": str(out_webm),
        "poster": str(out_poster),
        "json": str(out_json),
        "synced_delivery": synced_path,
        "sha256": h_out,
        "qa": qa_res,
    }


ASPECT_CANVAS = {
    "1:1": (1024, 1024),
    "3:4": (960, 1280),
    "4:3": (1280, 960),
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}


def cmd_prep_still(args):
    im = Image.open(args.input).convert("RGBA")
    arr = np.array(im)
    alpha = arr[:, :, 3]
    if (alpha < 250).any():
        fg = alpha > 20
        clean_rgb = arr[:, :, :3].copy()
    else:
        rgb = arr[:, :, :3].astype(np.float32)
        if args.bg == "black":
            fg = np.max(rgb, axis=2) > 28.0
        else:
            g_exc = rgb[:, :, 1] - np.maximum(rgb[:, :, 0], rgb[:, :, 2])
            fg = ~((g_exc > 28.0) & (rgb[:, :, 1] > 95.0))
        clean_rgb = arr[:, :, :3].copy()
        clean_rgb[~fg] = [0, 0, 0] if args.bg == "black" else [0, 255, 0]

    ys, xs = np.where(fg)
    if len(xs) == 0:
        raise SystemExit("No foreground found in input image.")
    crop_rgb = clean_rgb[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    crop_a = alpha[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    cw, ch = crop_rgb.shape[1], crop_rgb.shape[0]

    chosen_aspect = args.aspect
    if chosen_aspect == "auto":
        ratio = cw / float(max(1, ch))
        if 0.80 <= ratio <= 1.25:
            chosen_aspect = "1:1"
        elif ratio < 0.80:
            chosen_aspect = "3:4"
        else:
            chosen_aspect = "4:3"
    W, H = ASPECT_CANVAS[chosen_aspect]

    margin = max(0.06, min(0.25, float(args.margin_ratio)))
    margin_top = max(0.06, min(0.30, float(args.margin_top))) if args.margin_top is not None else margin
    max_w = int(round(W * (1.0 - 2.0 * margin)))
    max_h = int(round(H * (1.0 - (margin_top + margin))))
    sc = min(max_w / float(cw), max_h / float(ch))
    tw, th = max(2, int(round(cw * sc))), max(2, int(round(ch * sc)))
    ox = (W - tw) // 2
    oy = int(round(H * margin_top + (max_h - th) * 0.5))

    bg_col = (0, 0, 0) if args.bg == "black" else (0, 255, 0)
    canvas = Image.new("RGB", (W, H), bg_col)
    fg_pil = Image.fromarray(crop_rgb).resize((tw, th), Image.Resampling.LANCZOS)
    if (crop_a < 250).any():
        mask_pil = Image.fromarray(crop_a).resize((tw, th), Image.Resampling.LANCZOS)
        canvas.paste(fg_pil, (ox, oy), mask_pil)
    else:
        canvas.paste(fg_pil, (ox, oy))

    out_p = Path(args.out)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_p)
    print(json.dumps({
        "ok": True,
        "out": str(out_p),
        "aspect": chosen_aspect,
        "size": [W, H],
        "fitted": [tw, th],
        "margin_ratio": margin,
        "margin_top": margin_top,
        "recommended_h3": {
            "platform": "colab",
            "module": "multi",
            "aspect": chosen_aspect,
            "res": 2,
            "opt": True,
        },
    }, ensure_ascii=False))


def cmd_build_from_video(args):
    mp4 = Path(args.video)
    probe = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", str(mp4)]
        )
    )
    st = probe["streams"][0]
    src_w, src_h = int(st["width"]), int(st["height"])
    # Preserve full native resolution up to 1920px max side (never downscale H3 res:2 prematurely!)
    max_side = max(src_w, src_h)
    if max_side > 1920:
        r_sc = 1920.0 / float(max_side)
        dec_w = max(64, int(round(src_w * r_sc)) & ~1)
        dec_h = max(64, int(round(src_h * r_sc)) & ~1)
        vf = f"fps={FPS},scale={dec_w}:{dec_h}"
    else:
        dec_w, dec_h = src_w, src_h
        vf = f"fps={FPS}"

    ff_cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if args.t0 is not None:
        ff_cmd += ["-ss", f"{float(args.t0):.3f}"]
    if args.t1 is not None:
        ff_cmd += ["-to", f"{float(args.t1):.3f}"]
    ff_cmd += ["-i", str(mp4), "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]

    raw = subprocess.run(ff_cmd, capture_output=True, check=True).stdout
    fb = dec_w * dec_h * 3
    n_fr = len(raw) // fb
    if n_fr < 16:
        raise SystemExit(f"Too few decoded frames: {n_fr}")

    # True ALL-FRAME UNION BBOX at native decode resolution
    y0, y1, x0, x1 = dec_h, 0, dec_w, 0
    is_black = args.keyer.startswith("black")
    for fi in range(n_fr):
        fr = np.frombuffer(raw[fi * fb : (fi + 1) * fb], dtype=np.uint8).reshape(dec_h, dec_w, 3).astype(np.float32)
        if is_black:
            fg = np.max(fr, axis=2) > 36.0
        else:
            g_ex = fr[:, :, 1] - np.maximum(fr[:, :, 0], fr[:, :, 2])
            fg = (g_ex < 32.0) | (fr[:, :, 1] < 100.0)
        xs_c = np.where(fg.sum(axis=0) >= 3)[0]
        ys_c = np.where(fg.sum(axis=1) >= 3)[0]
        if len(xs_c) and len(ys_c):
            x0 = min(x0, int(xs_c.min()))
            x1 = max(x1, int(xs_c.max()) + 1)
            y0 = min(y0, int(ys_c.min()))
            y1 = max(y1, int(ys_c.max()) + 1)

    pad = max(16, int(round(max(dec_w, dec_h) * 0.02)))
    x0p, x1p = max(0, x0 - pad), min(dec_w, x1 + pad)
    y0p, y1p = max(0, y0 - pad), min(dec_h, y1 + pad)
    bw, bh = max(16, x1p - x0p), max(16, y1p - y0p)
    sc = min(420.0 / float(bw), 420.0 / float(bh))
    tw, th = max(2, int(round(bw * sc))), max(2, int(round(bh * sc)))
    ox, oy = (512 - tw) // 2, (512 - th) // 2

    keyer_fn = KEYER_MAP[args.keyer]
    bg_fill = (0, 0, 0) if is_black else (0, 255, 0)
    sharpen_amt = max(0.0, float(args.sharpen or 0.0))
    frames_rgba = []
    for fi in range(n_fr):
        fr = np.frombuffer(raw[fi * fb : (fi + 1) * fb], dtype=np.uint8).reshape(dec_h, dec_w, 3)
        sub = Image.fromarray(fr[y0p:y1p, x0p:x1p]).resize((tw, th), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (512, 512), bg_fill)
        canvas.paste(sub, (ox, oy))
        rgba = keyer_fn(np.array(canvas))
        if sharpen_amt > 0.0:
            fg_rgb = rgba[:, :, :3]
            blur = cv2.GaussianBlur(fg_rgb, (0, 0), 1.0)
            sharp = cv2.addWeighted(fg_rgb, 1.0 + sharpen_amt, blur, -sharpen_amt, 0)
            vis = rgba[:, :, 3] > 24
            rgba[:, :, :3] = np.where(vis[:, :, None], sharp, fg_rgb)
        frames_rgba.append(rgba)

    loop_info = None
    if args.loop == "auto_cycle":
        frames_out, loop_info = find_best_loop_cycle_and_morph(
            frames_rgba,
            min_len=int(args.min_cycle),
            max_len=120,
            morph_k=int(args.morph_frames),
        )
    else:
        frames_out = frames_rgba

    res = _encode_and_verify(
        eid=args.eid,
        title=args.title,
        key_mode=f"studio_{args.keyer}_{args.loop}_nat{dec_w}x{dec_h}",
        frames_rgba=frames_out,
        out_dir=Path(args.out_dir),
        sheet_path=Path(args.sheet) if args.sheet else None,
        sync_dir=Path(args.sync_delivery) if args.sync_delivery else None,
    )
    if loop_info is not None:
        res["loop_info"] = loop_info
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res["ok"] else 1)


def cmd_build_procedural(args):
    im = Image.open(args.still).convert("RGBA")
    arr = np.array(im)
    if args.auto_key != "none":
        arr = KEYER_MAP[args.auto_key](arr[:, :, :3])
    frames_out = _generate_procedural_frames(arr, args.preset, ss=args.supersample)
    res = _encode_and_verify(
        eid=args.eid,
        title=args.title,
        key_mode=f"proc_{args.preset}_72f_ss{args.supersample}",
        frames_rgba=frames_out,
        out_dir=Path(args.out_dir),
        sheet_path=Path(args.sheet) if args.sheet else None,
        sync_dir=Path(args.sync_delivery) if args.sync_delivery else None,
    )
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res["ok"] else 1)


def cmd_build_packaging(args):
    import tempfile

    mode = args.mode
    preset = args.preset
    width = args.width if args.width > 0 else (540 if mode == "l1_vfx" else 512)
    height = args.height if args.height > 0 else (960 if mode == "l1_vfx" else 512)
    fps = args.fps if args.fps > 0 else (30 if mode == "l1_vfx" else 24)
    frames = args.frames if args.frames > 0 else (90 if mode == "l1_vfx" else 72)

    studio_mjs = HERE / "ae_element_studio.mjs"
    if not studio_mjs.exists():
        raise FileNotFoundError(f"Missing AE/Skia studio renderer: {studio_mjs}")

    tmp_still_path = None
    try:
        if args.still:
            still_rgba = _extract_still_rgba(Path(args.still), auto_key=args.auto_key)
            fd, tmp_name = tempfile.mkstemp(prefix=f"{args.eid}_still_", suffix=".png")
            import os
            os.close(fd)
            tmp_still_path = Path(tmp_name)
            Image.fromarray(still_rgba, "RGBA").save(tmp_still_path)
        elif mode != "l1_vfx":
            raise ValueError(f"--still is required for mode={mode}")

        node_cmd = [
            "node", str(studio_mjs),
            "--mode", mode,
            "--preset", preset,
            "--palette", args.palette,
            "--badge-text", args.badge_text,
            "--width", str(width),
            "--height", str(height),
            "--fps", str(fps),
            "--frames", str(frames),
            "--supersample", str(args.supersample),
            "--seed", str(args.seed),
        ]
        if tmp_still_path is not None:
            node_cmd.extend(["--still", str(tmp_still_path)])

        proc = subprocess.Popen(node_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        frame_bytes = width * height * 4
        expected_total = frames * frame_bytes
        chunks = []
        read_len = 0
        assert proc.stdout is not None
        while read_len < expected_total:
            chunk = proc.stdout.read(min(1024 * 1024, expected_total - read_len))
            if not chunk:
                break
            chunks.append(chunk)
            read_len += len(chunk)
        _, err = proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"ae_element_studio.mjs failed ({args.eid}): {err.decode(errors='replace')}")
        raw_all = b"".join(chunks)
        if len(raw_all) < expected_total:
            raise RuntimeError(f"ae_element_studio.mjs short output: got {len(raw_all)} bytes, expected {expected_total}")

        frames_out = [
            np.frombuffer(raw_all, dtype=np.uint8, count=frame_bytes, offset=i * frame_bytes)
            .reshape((height, width, 4))
            .copy()
            for i in range(frames)
        ]

        res = _encode_and_verify(
            eid=args.eid,
            title=args.title,
            key_mode=f"ae_{mode}_{preset}_{frames}f_ss{args.supersample}",
            frames_rgba=frames_out,
            out_dir=Path(args.out_dir),
            sheet_path=Path(args.sheet) if args.sheet else None,
            sync_dir=Path(args.sync_delivery) if args.sync_delivery else None,
            width=width,
            height=height,
            fps=fps,
            spin_360=(mode == "l3_spin360"),
            is_fullscreen=(mode == "l1_vfx"),
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        sys.exit(0 if res["ok"] else 1)
    finally:
        if tmp_still_path is not None and tmp_still_path.exists():
            tmp_still_path.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description="Fast Element Production Factory")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_prep = sub.add_parser("prep-still", help="Match native aspect (1:1/3:4/4:3) with tight 8-12% margins for H3 res:2")
    p_prep.add_argument("--input", required=True)
    p_prep.add_argument("--out", required=True)
    p_prep.add_argument("--aspect", default="auto", choices=["auto", "1:1", "3:4", "4:3", "9:16", "16:9"])
    p_prep.add_argument("--bg", default="green", choices=["green", "black"])
    p_prep.add_argument("--margin-ratio", type=float, default=0.10)
    p_prep.add_argument("--margin-top", type=float, default=None)
    p_prep.set_defaults(func=cmd_prep_still)

    p_vid = sub.add_parser("build-from-video", help="Decode full-res AI video into QA-verified VP9 Alpha WebM")
    p_vid.add_argument("--eid", required=True)
    p_vid.add_argument("--title", required=True)
    p_vid.add_argument("--video", required=True)
    p_vid.add_argument("--keyer", default="green_dove", choices=sorted(KEYER_MAP.keys()))
    p_vid.add_argument("--loop", default="auto_cycle", choices=["auto_cycle", "none"])
    p_vid.add_argument("--min-cycle", type=int, default=48)
    p_vid.add_argument("--morph-frames", type=int, default=4)
    p_vid.add_argument("--t0", type=float, default=None)
    p_vid.add_argument("--t1", type=float, default=None)
    p_vid.add_argument("--sharpen", type=float, default=0.0)
    p_vid.add_argument("--out-dir", required=True)
    p_vid.add_argument("--sheet", default=None)
    p_vid.add_argument("--sync-delivery", default=None)
    p_vid.set_defaults(func=cmd_build_from_video)

    p_proc = sub.add_parser("build-procedural", help="Render 2x-supersampled 72-frame seamless loop from still + auto QA")
    p_proc.add_argument("--eid", required=True)
    p_proc.add_argument("--title", required=True)
    p_proc.add_argument("--still", required=True)
    p_proc.add_argument("--preset", default="halo_sparkles", choices=["halo_sparkles", "shimmer_sway", "rising_petals_glow", "sacred_flames_aura"])
    p_proc.add_argument("--auto-key", default="none", choices=["none"] + sorted(KEYER_MAP.keys()))
    p_proc.add_argument("--supersample", type=int, default=2, choices=[1, 2])
    p_proc.add_argument("--out-dir", required=True)
    p_proc.add_argument("--sheet", default=None)
    p_proc.add_argument("--sync-delivery", default=None)
    p_proc.set_defaults(func=cmd_build_procedural)

    p_pkg = sub.add_parser("build-packaging", help="Render Track A+ AE/Skia packaging or 3D 360-spin loop via @napi-rs/canvas + auto QA")
    p_pkg.add_argument("--eid", required=True)
    p_pkg.add_argument("--title", required=True)
    p_pkg.add_argument("--mode", default="l2_packaging", choices=["l1_vfx", "l2_packaging", "l3_spin360"])
    p_pkg.add_argument(
        "--preset",
        default="bell_spring_ring",
        choices=[
            "golden_galaxy_vortex", "sacred_bokeh_rays", "blessing_hearts_stream", "holy_sparks_rain", "frosted_subscribe_bar",
            "diagonal_tyndall_rays", "morning_incense_mist", "celestial_star_arcs",
            "bell_spring_ring", "wreath_shimmer_petals", "emblem_royal_gleam", "candle_fluid_flame",
            "gold_bevel_360",
        ],
    )
    p_pkg.add_argument("--palette", default="sacred_gold", choices=["sacred_gold", "festive_red_gold", "heavenly_white_blue", "pure_emerald_gold"])
    p_pkg.add_argument("--still", default="")
    p_pkg.add_argument("--badge-text", default="ĐĂNG KÝ KÊNH")
    p_pkg.add_argument("--auto-key", default="auto", choices=["auto", "none", "rembg"] + sorted(KEYER_MAP.keys()))
    p_pkg.add_argument("--width", type=int, default=0)
    p_pkg.add_argument("--height", type=int, default=0)
    p_pkg.add_argument("--fps", type=int, default=0)
    p_pkg.add_argument("--frames", type=int, default=0)
    p_pkg.add_argument("--supersample", type=int, default=2, choices=[1, 2])
    p_pkg.add_argument("--seed", type=int, default=202611)
    p_pkg.add_argument("--out-dir", required=True)
    p_pkg.add_argument("--sheet", default=None)
    p_pkg.add_argument("--sync-delivery", default=None)
    p_pkg.set_defaults(func=cmd_build_packaging)

    ns = ap.parse_args()
    ns.func(ns)


if __name__ == "__main__":
    main()


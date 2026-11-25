#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ground-Truth Regression Test Suite for vn-subtitle-element-studio.
Tests real verified and real defective elements + procedural generation + subtitle linter & Skia sheet.
"""
import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fast_element_qa as el_qa  # noqa: E402

DELIVERY_DIR = Path(r"C:\Users\Clara\Downloads\AI专用\2026-11-21\越南天主教土嗨小元素库\01_透明通道WebM成片")
AE_DRAFT_JSON = Path(r"C:\Users\Clara\reels-studio\handoff_20261121_ae_subtitles\seed_draft_ae_subtitles.json")


def _find_one(prefix: str) -> Path:
    matches = sorted(DELIVERY_DIR.glob(f"{prefix}_*.webm"))
    assert matches, f"Missing local test file for {prefix} in {DELIVERY_DIR}"
    return matches[0]


def _make_synthetic_emblem(out_png: Path) -> Path:
    im = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    # Bright golden halo ring + empty radiant cross + rose accents
    dr.ellipse([80, 80, 520, 520], outline=(255, 215, 70, 255), width=22)
    dr.ellipse([108, 108, 492, 492], outline=(255, 244, 178, 255), width=8)
    dr.rounded_rectangle([274, 130, 326, 470], radius=16, fill=(255, 232, 95, 255), outline=(180, 90, 16, 255), width=6)
    dr.rounded_rectangle([180, 220, 420, 272], radius=16, fill=(255, 232, 95, 255), outline=(180, 90, 16, 255), width=6)
    dr.ellipse([265, 212, 335, 282], fill=(225, 29, 72, 255), outline=(255, 240, 160, 255), width=5)
    im.save(out_png)
    return out_png


def main():
    ap = argparse.ArgumentParser(description="Self-test suite for vn-subtitle-element-studio")
    ap.add_argument("--scratch-dir", default=r"C:\Users\Clara\.gemini\antigravity\brain\d625a241-7afc-4818-8a29-354d3f01388e\scratch")
    args = ap.parse_args()

    t0 = time.time()
    scratch = Path(args.scratch_dir)
    scratch.mkdir(parents=True, exist_ok=True)

    # ── 1. Element Factory Procedural + Prep-Still Test ──────────────────────
    print("[1/3] Testing fast_element_factory prep-still & build-procedural...")
    raw_emblem = _make_synthetic_emblem(scratch / "selftest_emblem.png")
    prepped_png = scratch / "selftest_emblem_1x1.png"
    subprocess.run(
        [sys.executable, str(HERE / "fast_element_factory.py"), "prep-still", "--input", str(raw_emblem), "--out", str(prepped_png), "--bg", "green"],
        check=True,
    )
    prepped_im = Image.open(prepped_png)
    assert prepped_im.size == (1024, 1024), f"Bad prep-still size: {prepped_im.size}"

    proc_dir = scratch / "selftest_proc_out"
    subprocess.run(
        [
            sys.executable, str(HERE / "fast_element_factory.py"), "build-procedural",
            "--eid", "E-TEST", "--title", "自测程序化金环空十字",
            "--still", str(raw_emblem), "--preset", "halo_sparkles",
            "--out-dir", str(proc_dir),
        ],
        check=True,
    )
    proc_webm = proc_dir / "E-TEST.webm"
    assert proc_webm.exists(), "Procedural E-TEST.webm not created"

    pkg_dir = scratch / "selftest_pkg_out"
    pkg_cases = [
        ("E-PKG-L2", "l2_packaging", "emblem_royal_gleam", ["--still", str(raw_emblem), "--palette", "sacred_gold"]),
        ("E-PKG-L3", "l3_spin360", "gold_bevel_360", ["--still", str(raw_emblem), "--palette", "heavenly_white_blue"]),
        ("E-PKG-L1", "l1_vfx", "golden_galaxy_vortex", ["--palette", "sacred_gold", "--width", "360", "--height", "640", "--fps", "30", "--frames", "60", "--supersample", "1"]),
    ]
    for eid, mode, preset, extra in pkg_cases:
        cp = subprocess.run(
            [
                sys.executable, str(HERE / "fast_element_factory.py"), "build-packaging",
                "--eid", eid, "--title", f"自测_{mode}_{preset}",
                "--mode", mode, "--preset", preset, "--out-dir", str(pkg_dir),
            ] + extra,
            capture_output=True, text=True, encoding="utf-8",
        )
        assert cp.returncode == 0, f"{eid} build-packaging failed:\n{cp.stdout}\n{cp.stderr}"
        p_res = json.loads(cp.stdout)
        assert p_res["qa"]["status"] == "PASS", f"{eid} QA failed: {p_res}"
        if mode == "l3_spin360":
            assert p_res["qa"]["mode"] == "spin360", f"Bad spin360 mode: {p_res['qa']}"
            m = p_res["qa"]["metrics"]
            assert m["spin_troughs"] >= 2 and m["spin_dom_ratio"] >= 0.78, f"Bad G10 metrics: {m}"
        if mode == "l1_vfx":
            assert p_res["qa"]["mode"] == "fullscreen", f"Bad fullscreen mode: {p_res['qa']}"

    # ── 2. Element 10-Gate + True-Loop Forensics QA on Real Good & Bad Files ─
    print("[2/3] Running fast_element_qa on bad/fake-loop vs true-loop assets...")
    t_qa0 = time.time()
    fx_dir = HERE.parent / "tests" / "fixtures"
    bad_targets = []
    for bad_id in ("E-074BAD", "E-015BAD", "E-061BAD", "E-145BAD", "E-174BAD", "E-082BAD"):
        fx_p = fx_dir / f"{bad_id}_legacy_broken.webm"
        assert fx_p.exists(), f"Missing archived bad fixture: {fx_p}"
        bad_targets.append(fx_p)
    good_prefixes = ["E-074", "E-160", "E-178", "E-181", "E-182", "E-184", "E-187", "E-188"]
    good_targets = [_find_one(pfx) for pfx in good_prefixes] + [proc_webm]
    true_e061 = scratch / "e061_true_loop" / "E-061.webm"

    all_targets = bad_targets + good_targets
    with ThreadPoolExecutor(max_workers=8) as ex:
        qa_results = list(ex.map(lambda p: el_qa.audit_single_webm(p, "auto"), all_targets))
    r_true_e061 = el_qa.audit_single_webm(true_e061, "auto") if true_e061.exists() else None
    qa_elapsed = time.time() - t_qa0
    print(f"      Audited {len(all_targets) + (1 if r_true_e061 else 0)} elements in {qa_elapsed:.2f}s")

    by_id = {r["id"]: r for r in qa_results}
    r074_bad = by_id["E-074BAD"]
    assert r074_bad["status"] == "FAIL", f"E-074BAD must FAIL, got {r074_bad}"
    for expected_gate in ("G02_F0_PRESENCE", "G03_SEAMLESS_LOOP", "G06_INTERNAL_FLAT_CLIP"):
        assert expected_gate in r074_bad["failed_gates"], f"E-074BAD missing {expected_gate}: {r074_bad}"

    r015 = by_id["E-015BAD"]
    assert r015["status"] == "FAIL" and "G08_BRIGHT_BG_FRINGE" in r015["failed_gates"], f"E-015BAD must fail G08: {r015}"

    for ghost_id in ("E-061BAD", "E-145BAD"):
        rg_bad = by_id[ghost_id]
        assert rg_bad["status"] == "FAIL" and "G03_CROSSFADE_GHOST" in rg_bad["failed_gates"], f"{ghost_id} must fail G03_CROSSFADE_GHOST: {rg_bad}"

    assert by_id["E-174BAD"]["status"] == "FAIL" and "G03_PINGPONG_REVERSE" in by_id["E-174BAD"]["failed_gates"], f"E-174BAD must fail G03_PINGPONG_REVERSE: {by_id['E-174BAD']}"
    assert by_id["E-082BAD"]["status"] == "FAIL" and "G03_INTERNAL_CUT" in by_id["E-082BAD"]["failed_gates"], f"E-082BAD must fail G03_INTERNAL_CUT: {by_id['E-082BAD']}"

    for gpfx in good_prefixes + ["E-TEST"]:
        rg = by_id[gpfx]
        assert rg["status"] == "PASS", f"Verified clean {gpfx} failed unexpectedly: {rg}"
    if r_true_e061 is not None:
        assert r_true_e061["status"] == "PASS", f"Repaired true-loop E-061 failed: {r_true_e061}"

    sheet_rows = [by_id["E-074BAD"], by_id["E-015BAD"], by_id["E-061BAD"], by_id["E-145BAD"], by_id["E-174BAD"], by_id["E-082BAD"], by_id["E-074"], by_id["E-TEST"]]
    el_sheet = scratch / "selftest_element_qa.jpg"
    el_qa.render_contact_sheet(sheet_rows, el_sheet)
    assert el_sheet.exists(), "Element contact sheet missing"

    # ── 3. Subtitle 9-Gate QA + Skia Single/Double-Line Sheet ─────────────────
    print("[3/3] Running fast_subtitle_qa on AE 8 draft + synthetic broken pack...")
    sub_sheet = scratch / "selftest_subtitle_qa.jpg"
    res_ae = subprocess.run(
        [
            sys.executable, str(HERE / "fast_subtitle_qa.py"),
            "--file", str(AE_DRAFT_JSON), "--skip-online", "--preview-sheet", str(sub_sheet),
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert res_ae.returncode == 0, f"AE draft failed QA:\n{res_ae.stdout}\n{res_ae.stderr}"
    ae_out = json.loads(res_ae.stdout)
    assert ae_out["ok"] and ae_out["passed"] == 8, f"Expected 8/8 AE pass: {ae_out}"
    assert sub_sheet.exists(), "Subtitle Skia contact sheet missing"

    broken_pack = [
        {
            "row": {
                "id": "",
                "title": "天主耶稣破损测试款",
                "kind": "subtitle",
                "font_family": "Arial",
                "font_keys_json": "[\"Be Vietnam Pro\"]",
                "style": {
                    "sample_text_vi": "Chúa Giêsu nâng đỡ",
                    "raw_style_params": {
                        "font_family": "Arial",
                        "fontsize": 60,
                        "line_spacing": 1.2,
                        "wrap_width_percent": 92,
                        "use_stroke": True,
                        "color_outline": "#000000",
                        "color_text": "#FFFFFF",
                        "anim_in_type": "letter_jump",
                    },
                },
            }
        },
        {
            "id": "",
            "title": "水货克隆A_红底",
            "kind": "subtitle",
            "sample_text_vi": "Hãy giữ tâm bình an",
            "raw_style_params": {
                "font_family": "Be Vietnam Pro",
                "fontsize": 84,
                "line_spacing": 38,
                "wrap_width_percent": 84,
                "use_box": True,
                "box_adaptive_width": True,
                "box_connected": False,
                "color_bg": "#B91C1C",
                "color_text": "#FFFFFF",
                "anim_in_type": "pop",
            },
        },
        {
            "id": "",
            "title": "水货克隆B_绿底换色",
            "kind": "subtitle",
            "sample_text_vi": "Hãy giữ tâm bình an",
            "raw_style_params": {
                "font_family": "Be Vietnam Pro",
                "fontsize": 84,
                "line_spacing": 38,
                "wrap_width_percent": 84,
                "use_box": True,
                "box_adaptive_width": True,
                "box_connected": False,
                "color_bg": "#15803D",
                "color_text": "#FFFFFF",
                "anim_in_type": "pop",
            },
        },
    ]
    broken_json = scratch / "selftest_broken_pack.json"
    broken_json.write_text(json.dumps(broken_pack, ensure_ascii=False, indent=2), encoding="utf-8")
    res_brk = subprocess.run(
        [sys.executable, str(HERE / "fast_subtitle_qa.py"), "--file", str(broken_json), "--skip-online"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert res_brk.returncode != 0, "Broken pack should have failed!"
    brk_out = json.loads(res_brk.stdout)
    rep0_fails = set(brk_out["reports"][0]["failed_gates"])
    for req_gate in (
        "S01_FONT_WHITELIST", "S02_FONT_KEYS_PATH", "S03_SACRED_NO_BLACK",
        "S04_BOX_AND_SPACING", "S05_SAFE_BOUNDS_AND_SIZE", "S07_VN_ORTHOGRAPHY_NFC",
    ):
        assert req_gate in rep0_fails, f"Broken #1 missing {req_gate}: {brk_out['reports'][0]}"
    rep2_fails = set(brk_out["reports"][2]["failed_gates"])
    assert "S09_ANTI_HOMOGENIZATION_DEDUP" in rep2_fails, f"Clone #3 missing S09: {brk_out['reports'][2]}"

    print(json.dumps({
        "status": "ALL REGRESSION TESTS PASSED",
        "elapsed_sec": round(time.time() - t0, 2),
        "element_qa_sec_for_14": round(qa_elapsed, 2),
        "element_sheet": str(el_sheet),
        "subtitle_sheet": str(sub_sheet),
        "e074_failed_gates": r074_bad["failed_gates"],
        "e015_failed_gates": r015["failed_gates"],
        "ae_passed": ae_out["passed"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


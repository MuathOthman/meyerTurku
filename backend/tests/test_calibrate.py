from pathlib import Path

import pytest

from keel.calibrate import (
    CalibrationError,
    calibrate,
    detect_beam_pt,
    detect_frame_ruler,
    feet_inches_to_mm,
    fit_regular_grid,
    mm_to_feet_inches,
)
from keel.extract import Primitives, Segment, extract_pdf_page

PDF = Path(__file__).parents[1] / "data/raw/rcrv_ga.pdf"


def make_page(spacing=10.0, ticks=30, half_beam=90.0, cy=200.0):
    segs = [Segment(100 + i * spacing, cy - 3, 100 + i * spacing, cy + 3) for i in range(ticks)]
    segs.append(Segment(100, cy - half_beam, 500, cy - half_beam))
    segs.append(Segment(100, cy + half_beam, 500, cy + half_beam))
    return Primitives(0, 1000, 800, segs, [])


def test_unit_conversions():
    assert feet_inches_to_mm(41) == pytest.approx(12496.8)
    assert feet_inches_to_mm(0, 32) == pytest.approx(812.8)
    assert mm_to_feet_inches(914.4) == "3'-0.0\""
    assert mm_to_feet_inches(812.8) == "2'-8.0\""


def test_fit_regular_grid_recovers_spacing_with_missing_tick():
    spacing, residual = fit_regular_grid([0.0, 8.78, 17.56, 35.12, 43.9], 8.8)
    assert spacing == pytest.approx(8.78)
    assert residual < 1e-9


def test_detect_frame_ruler_ignores_noise():
    page = make_page()
    noise = [Segment(300 + i * 1.37, 600, 300 + i * 1.37, 604) for i in range(5)]
    ruler = detect_frame_ruler(page.segments + noise)
    assert ruler.spacing_pt == pytest.approx(10.0)
    assert ruler.centerline_y == pytest.approx(200.0)
    assert ruler.tick_count == 30


def test_detect_frame_ruler_raises_when_absent():
    with pytest.raises(CalibrationError):
        detect_frame_ruler([Segment(0, 0, 100, 0)])


def test_detect_beam_requires_symmetry():
    page = make_page(half_beam=90)
    assert detect_beam_pt(page.segments, 200.0) == pytest.approx(180.0)
    lopsided = [Segment(0, 110, 400, 110), Segment(0, 300, 400, 300)]
    with pytest.raises(CalibrationError):
        detect_beam_pt(lopsided, 200.0)


def test_calibrate_scale_and_tolerance():
    # 10 pt per frame at 600 mm gives 60 mm/pt, so a 180 pt beam is 10800 mm.
    cal = calibrate(make_page(), frame_spacing_mm=600, beam_mm=10800)
    assert cal.mm_per_pt == pytest.approx(60.0)
    assert cal.relative_error == pytest.approx(0.0)
    assert cal.tolerance_mm(1000) == pytest.approx(0.36 * 60)


def test_calibrate_refuses_when_verification_disagrees():
    # A 2x wrong reference, exactly the error the printed scale would cause.
    with pytest.raises(CalibrationError):
        calibrate(make_page(), frame_spacing_mm=600, beam_mm=21600)


@pytest.mark.skipif(not PDF.exists(), reason="RCRV drawing not downloaded")
def test_real_drawing_scale_matches_printed_beam():
    page = extract_pdf_page(PDF, 9)
    cal = calibrate(
        page,
        frame_spacing_mm=feet_inches_to_mm(2),
        beam_mm=feet_inches_to_mm(41),
        region=(0, 80, 1224, 320),
    )
    # 0.488 of the nominal 1/8 in scale, nowhere near the literal or half-size scales.
    assert cal.mm_per_pt == pytest.approx(69.41, abs=0.05)
    assert cal.relative_error < 0.001
    assert abs(cal.beam_measured_mm - cal.beam_expected_mm) < 15

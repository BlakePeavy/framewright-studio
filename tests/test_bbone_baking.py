"""Budget planning remains importable without a Blender Python environment."""

import pytest

from framewright.bbone_baking import _options


def request(**overrides):
    return dict(
        object_name="Body",
        armature_name="Rig",
        frame_start=1,
        frame_end=17,
        max_surface_error_m=0.0005,
        **overrides,
    )


def test_full_integer_interval_must_fit_both_independent_budgets():
    for budget in ("max_key_times", "max_samples"):
        with pytest.raises(ValueError, match="Full integer interval"):
            _options(request(**{budget: 16}))
        assert _options(request(**{budget: 17}))["end"] == 17


def test_single_frame_and_explicit_zero_refinement_are_supported():
    params = request(max_key_times=1, max_samples=1, max_refinement_depth=0)
    params["frame_end"] = 1
    options = _options(params)
    assert options["start"] == options["end"] == 1
    assert options["max_refinement_depth"] == 0


def test_meter_tolerance_is_required_and_finite():
    params = request()
    del params["max_surface_error_m"]
    with pytest.raises(ValueError):
        _options(params)
    for value in (float("nan"), float("inf"), True, 0, 1.1):
        params["max_surface_error_m"] = value
        with pytest.raises(ValueError):
            _options(params)

"""Export's explicit scalar-material work budget is part of the AI contract."""

import pytest

from framewright.commands import validate_params


@pytest.mark.parametrize("value", [1, 512, 4096, 32768])
def test_export_accepts_explicit_material_budget(value):
    validate_params(
        "asset.export",
        {"object_names": ["Source"], "directory": "C:/exports", "max_material_memory_mb": value},
    )


@pytest.mark.parametrize("value", [True, 0, -1, 32769, 1.5, "512"])
def test_export_rejects_invalid_material_budget(value):
    with pytest.raises(ValueError):
        validate_params(
            "asset.export",
            {
                "object_names": ["Source"],
                "directory": "C:/exports",
                "max_material_memory_mb": value,
            },
        )

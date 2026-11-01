"""Framewright Studio: Blender entry point; core imports also work outside Blender."""

__version__ = "0.8.0"


def register():
    from . import ui, ui_tools

    ui.assert_registration_available()
    ui_tools.assert_registration_available()
    ui.register()
    try:
        ui_tools.register()
    except Exception:
        ui.unregister()
        raise


def unregister():
    from . import ui, ui_tools

    ui_tools.unregister()
    ui.unregister()

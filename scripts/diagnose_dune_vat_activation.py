"""Compatibility alias for the archived Vat activation diagnostic until Stage 11."""

if __name__ == "__main__":
    import runpy as _runpy
    from pathlib import Path as _Path

    _runpy.run_path(
        str(
            _Path(__file__).resolve().parents[1]
            / "workflows/maintenance/archive/diagnose_vat_activation.py"
        ),
        run_name="__main__",
    )
else:
    from importlib import import_module as _import_module
    import sys as _sys

    _sys.modules[__name__] = _import_module(
        "workflows.maintenance.archive.diagnose_vat_activation"
    )

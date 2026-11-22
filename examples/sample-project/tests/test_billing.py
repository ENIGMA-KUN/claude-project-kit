"""The sample project ships stub code only; its knowledge/ folder is what the docs use."""


def test_sample_project_imports():
    from pathlib import Path

    assert (Path(__file__).parents[1] / "app" / "services" / "billing.py").exists()

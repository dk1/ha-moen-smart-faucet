"""Keep the shipped English translations in sync with strings.json."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
COMPONENT = ROOT / "custom_components" / "moen_smart_faucet"


def _gen():
    spec = importlib.util.spec_from_file_location(
        "gen_translations", ROOT / "script" / "gen_translations.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_en_json_matches_strings() -> None:
    """translations/en.json is generated; regenerate with script/gen_translations.py."""
    assert (COMPONENT / "translations" / "en.json").read_text() == _gen().render()


def test_every_translation_key_is_used() -> None:
    """Every entity translation key in strings.json has an icon, and vice versa."""
    strings = json.loads((COMPONENT / "strings.json").read_text())["entity"]
    icons = json.loads((COMPONENT / "icons.json").read_text())["entity"]
    for platform, keys in icons.items():
        for key in keys:
            assert key in strings.get(platform, {}), (
                f"icon for unknown {platform}.{key}"
            )


def test_services_documented() -> None:
    """Every action in services.yaml has a name and description in strings.json."""
    import yaml

    services = yaml.safe_load((COMPONENT / "services.yaml").read_text())
    strings = json.loads((COMPONENT / "strings.json").read_text())["services"]
    for name, spec in services.items():
        assert strings[name]["name"] and strings[name]["description"]
        for field in spec.get("fields", {}):
            assert strings[name]["fields"][field]["name"], f"{name}.{field}"

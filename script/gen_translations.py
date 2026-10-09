"""Generate translations/en.json from strings.json.

Core integrations get their `[%key:...%]` references resolved at build time;
custom integrations ship translations/en.json as-is, so resolve them here.
Run after editing strings.json:  python script/gen_translations.py
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import homeassistant

COMPONENT = Path(__file__).parent.parent / "custom_components" / "moen_smart_faucet"
COMMON = json.loads((Path(homeassistant.__file__).parent / "strings.json").read_text())


def resolve(value: Any) -> Any:
    """Replace [%key:a::b%] references with Home Assistant's common strings."""
    if isinstance(value, dict):
        return {k: resolve(v) for k, v in value.items()}
    if isinstance(value, str) and (m := re.fullmatch(r"\[%key:(.+)%\]", value)):
        node: Any = COMMON
        for part in m.group(1).split("::"):
            node = node[part]
        return node
    return value


def render() -> str:
    """Return the expected contents of translations/en.json."""
    strings = json.loads((COMPONENT / "strings.json").read_text())
    return json.dumps(resolve(strings), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    (COMPONENT / "translations" / "en.json").write_text(render())

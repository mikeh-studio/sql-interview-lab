"""Convert Pydantic schemas to the strict subset used by CLI structured outputs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def make_strict_output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Require every object property and remove unsupported default annotations."""

    strict = deepcopy(schema)

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["required"] = list(properties)
                node["additionalProperties"] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(strict)
    return strict

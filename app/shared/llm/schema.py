"""Turn a Pydantic model into a JSON schema that Groq accepts in strict mode.

Strict mode needs every object to list all its properties in ``required`` and to set
``additionalProperties: false``. Optional fields stay nullable through their ``anyOf`` with null.
"""

from typing import Any

from pydantic import BaseModel

_DROP_KEYS = ("default",)


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    _strictify(schema)
    return schema


def _strictify(node: Any) -> None:
    if isinstance(node, dict):
        for key in _DROP_KEYS:
            node.pop(key, None)
        if node.get("type") == "object" or "properties" in node:
            props = node.get("properties", {})
            node["required"] = list(props)
            node["additionalProperties"] = False
        for value in node.values():
            _strictify(value)
    elif isinstance(node, list):
        for item in node:
            _strictify(item)

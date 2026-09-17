"""Render a contract schema as a literal skeleton to inline in an agent file.

A pointer to a schema file is not an output contract. In an end-to-end run the
plan-compliance validator was told to "return a block conforming to
schemas/validator-verdict.schema.json", never opened the file, and invented a
perfectly reasonable shape of its own — correct judgement, unusable return. A
cheap worker follows a shape it can see, not one it would have to go and fetch.

So the generated agent file carries the skeleton itself. Generating it from the
schema rather than hand-writing it is what keeps the two from drifting: change
the schema and the next render changes the skeleton.
"""
import json

PLACEHOLDER = {
    "string": "<text>",
    "integer": "<n>",
    "number": "<n>",
    "boolean": "<true|false>",
}


def _resolve(node, root):
    while "$ref" in node:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            return node
        target = root
        for part in ref[2:].split("/"):
            target = target[part]
        node = dict(target, **{k: v for k, v in node.items() if k != "$ref"})
    return node


def _types(node):
    kinds = node.get("type", "object")
    return [kinds] if isinstance(kinds, str) else list(kinds)


def _value(node, root, extra):
    node = _resolve(node, root)
    if "const" in node:
        return node["const"]
    if "enum" in node:
        return "|".join(str(v) for v in node["enum"])
    if "anyOf" in node:
        return " | ".join(str(_value(b, root, extra)) for b in node["anyOf"])

    primary = next((k for k in _types(node) if k != "null"), "string")

    if primary == "object":
        return _object(node, root, extra)
    if primary == "array":
        item = node.get("items")
        return [_value(item, root, extra)] if item else []
    return PLACEHOLDER.get(primary, "<value>")


def _object(node, root, extra):
    props = node.get("properties", {})
    required = node.get("required", list(props))
    names = [n for n in props if n in required or n in extra]
    return {n: _value(props[n], root, extra) for n in names}


def skeleton(schema_path, extra=(), pin=None):
    """Return the schema's required shape as pretty-printed JSON text.

    `pin` fixes a field to a literal value. `extra` names optional properties
    to show anyway — used for fields a
    cross-field rule makes mandatory in one role but not the other, such as a
    quality finding's failure_scenario.
    """
    root = json.loads(schema_path.read_text(encoding="utf-8"))
    shape = _value(root, root, frozenset(extra))
    # Pin fields whose value this particular role already knows, so the worker
    # is not offered a choice root has already made — a verdict returning the
    # wrong role is rejected anyway.
    for name, value in (pin or {}).items():
        if isinstance(shape, dict) and name in shape:
            shape[name] = value
    return json.dumps(shape, indent=2)

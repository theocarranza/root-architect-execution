"""A small JSON Schema validator covering exactly the keywords this plugin's
schemas use.

There is no `jsonschema` package on this machine and the plugin must run from a
bare interpreter, so the alternative to ~150 lines here is schemas that describe
the contracts without ever checking them — which is the failure mode the schemas
exist to prevent.

Supported: type, enum, const, required, properties, additionalProperties,
items, minItems, uniqueItems, minLength, minimum, maximum, pattern, anyOf,
allOf, $ref (local "#/$defs/..." and sibling-file "name.schema.json"), and
$defs. Anything else in a schema is ignored rather than silently passing, so
keep the schemas inside this subset.

Targets Python 3.9+ so the PreToolUse hooks can run under whichever interpreter
`python3` happens to be.
"""
import json
import re
from pathlib import Path

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


class SchemaError(Exception):
    """Raised for a schema this validator cannot honour, never for bad data."""


def _is_type(value, name):
    if name == "integer":
        # bool is a subclass of int; an integer field must not accept true.
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    expected = _TYPES.get(name)
    if expected is None:
        raise SchemaError("unsupported type keyword: %s" % name)
    if name == "boolean":
        return isinstance(value, bool)
    return isinstance(value, expected)


class Validator:
    """Validates against one root schema, resolving $ref within a directory."""

    def __init__(self, schema_path):
        self.schema_path = Path(schema_path)
        self.root = json.loads(self.schema_path.read_text(encoding="utf-8"))
        self._siblings = {}

    def _resolve(self, ref, local_root):
        if ref.startswith("#/"):
            node = local_root
            for part in ref[2:].split("/"):
                node = node[part]
            return node, local_root
        if ref.startswith("#"):
            raise SchemaError("unsupported ref: %s" % ref)
        if ref not in self._siblings:
            target = self.schema_path.parent / ref
            self._siblings[ref] = json.loads(target.read_text(encoding="utf-8"))
        sibling = self._siblings[ref]
        return sibling, sibling

    def validate(self, instance):
        """Return a list of human-readable error strings; empty means valid."""
        errors = []
        self._check(instance, self.root, self.root, "$", errors)
        return errors

    def _check(self, value, schema, local_root, path, errors):
        if not isinstance(schema, dict):
            raise SchemaError("schema node at %s is not an object" % path)

        if "$ref" in schema:
            target, new_root = self._resolve(schema["$ref"], local_root)
            self._check(value, target, new_root, path, errors)
            # A $ref node may carry siblings (allOf-style annotation); the
            # remaining keywords still apply.

        if "allOf" in schema:
            for sub in schema["allOf"]:
                self._check(value, sub, local_root, path, errors)

        if "anyOf" in schema:
            branches = []
            for sub in schema["anyOf"]:
                collected = []
                self._check(value, sub, local_root, path, collected)
                if not collected:
                    branches = []
                    break
                branches.append(collected)
            if branches:
                errors.append("%s: matches none of the allowed forms" % path)

        if "type" in schema:
            names = schema["type"]
            if isinstance(names, str):
                names = [names]
            if not any(_is_type(value, n) for n in names):
                errors.append("%s: expected type %s, got %s"
                              % (path, "/".join(names), type(value).__name__))
                return

        if "const" in schema and value != schema["const"]:
            errors.append("%s: must equal %r" % (path, schema["const"]))

        if "enum" in schema and value not in schema["enum"]:
            errors.append("%s: %r is not one of %s" % (path, value, schema["enum"]))

        if isinstance(value, str):
            if "minLength" in schema and len(value) < schema["minLength"]:
                errors.append("%s: shorter than minLength %d"
                              % (path, schema["minLength"]))
            if "pattern" in schema and not re.search(schema["pattern"], value):
                errors.append("%s: %r does not match pattern %s"
                              % (path, value, schema["pattern"]))

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                errors.append("%s: below minimum %s" % (path, schema["minimum"]))
            if "maximum" in schema and value > schema["maximum"]:
                errors.append("%s: above maximum %s" % (path, schema["maximum"]))

        if isinstance(value, list):
            if "minItems" in schema and len(value) < schema["minItems"]:
                errors.append("%s: fewer than minItems %d"
                              % (path, schema["minItems"]))
            if schema.get("uniqueItems") and len(value) != len(set(map(repr, value))):
                errors.append("%s: contains duplicate entries" % path)
            if "items" in schema:
                for i, item in enumerate(value):
                    self._check(item, schema["items"], local_root,
                                "%s[%d]" % (path, i), errors)

        if isinstance(value, dict):
            props = schema.get("properties", {})
            for name in schema.get("required", []):
                if name not in value:
                    errors.append("%s: missing required property %r" % (path, name))
            if schema.get("additionalProperties") is False:
                for name in value:
                    if name not in props:
                        errors.append("%s: unexpected property %r" % (path, name))
            extra = schema.get("additionalProperties")
            for name, sub in value.items():
                child = "%s.%s" % (path, name)
                if name in props:
                    self._check(sub, props[name], local_root, child, errors)
                elif isinstance(extra, dict):
                    self._check(sub, extra, local_root, child, errors)


def validate_file(schema_path, instance):
    """Convenience wrapper: returns the error list for one instance."""
    return Validator(schema_path).validate(instance)

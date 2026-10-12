"""
A form's custom fields as one list, and how that list is stored.

The console edits every custom field of one record type (a "form") as a single list and saves
it whole. Stored, the list stays field definitions: one for every vertical, plus one for each
vertical a field is limited to. `GET /field-definitions?scoped=true` then keeps answering "the
fields for this vertical or unit" by itself, so a field's vertical rule is which list it sits
in, never a show/hide rule (a task's vertical comes from its project or team, not a form input).
"""
from typing import Any, Optional
import uuid

from models.vertical import FieldDefinition
from schemas.vertical import FormField, ShowWhen

# Keys a service already keeps in a record's `attributes`; a custom field can't take them.
RESERVED_KEYS: dict[str, frozenset[str]] = {
    # Delivery refuses these on tasks (RESERVED_ATTRIBUTE_KEYS in 03_delivery/schemas/task_types.py).
    "task.task": frozenset({
        "labels", "blocked_reason", "blocked_by_task_id", "outcome", "follow_up_of", "follow_up_task_id",
        "cadence_step", "responded_at", "due_from_sla", "sla_paused_since", "sla_paused_minutes",
    }),
    # Revenue keeps the lead score here, and the website import its enquiry details.
    "revenue.lead": frozenset({"score", "website_lead_id", "website_form", "package", "budget", "message", "location"}),
}

# Field types stored as a string with a JSON Schema format.
_FORMATS = {"date": "date", "datetime": "date-time", "url": "uri", "email": "email", "phone": "phone"}
_TYPES_BY_FORMAT = {json_format: field_type for field_type, json_format in _FORMATS.items()}


def reserved_keys(object_type: str, fields: list[FormField]) -> list[str]:
    reserved = RESERVED_KEYS.get(object_type, frozenset())
    return [f.key for f in fields if f.key in reserved]


def form_revision(live_definitions: list[FieldDefinition]) -> int:
    """What a save must quote in If-Match: the newest live list's version, 0 before any."""
    return max((d.version_no for d in live_definitions), default=0)


# ---------------------------------------------------------------------------
# One list -> the lists to store
# ---------------------------------------------------------------------------

def stored_lists(fields: list[FormField]) -> dict[Optional[uuid.UUID], tuple[dict[str, Any], dict[str, Any]]]:
    """
    Vertical id (None = every vertical) -> the (json_schema, ui_schema) to store for it. The list
    for every vertical is always there, even empty, so a save always leaves a live list carrying
    the form's revision. Each list carries the whole form's order.
    """
    members: dict[Optional[uuid.UUID], list[FormField]] = {None: []}
    for field in fields:
        for vertical_id in field.vertical_ids or [None]:
            members.setdefault(vertical_id, []).append(field)
    form_order = [f.key for f in fields]
    return {vertical_id: _schemas(listed, form_order) for vertical_id, listed in members.items()}


def _schemas(fields: list[FormField], form_order: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    json_schema: dict[str, Any] = {"type": "object", "properties": {f.key: _property(f) for f in fields}}
    required = [f.key for f in fields if f.required]
    if required:
        json_schema["required"] = required
    ui_schema: dict[str, Any] = {"ui:order": form_order}
    for field in fields:
        if ui_options := _ui_options(field):
            ui_schema[field.key] = ui_options
    return json_schema, ui_schema


def _property(field: FormField) -> dict[str, Any]:
    prop: dict[str, Any] = {"title": field.label}
    if field.help:
        prop["description"] = field.help
    if field.type in ("number", "integer", "boolean"):
        prop["type"] = field.type
    elif field.type == "choice":
        prop.update(type="string", enum=list(field.options))
    elif field.type == "multi_choice":
        prop.update(type="array", items={"type": "string", "enum": list(field.options)}, uniqueItems=True)
    else:
        prop["type"] = "string"
        if field.type in _FORMATS:
            prop["format"] = _FORMATS[field.type]
    return prop


def _ui_options(field: FormField) -> dict[str, Any]:
    ui_options: dict[str, Any] = {}
    if field.type == "long_text":
        ui_options["ui:widget"] = "textarea"
    if field.show_when:
        ui_options["ui:show_when"] = field.show_when.model_dump()
    return ui_options


# ---------------------------------------------------------------------------
# Stored lists -> one list
# ---------------------------------------------------------------------------

def merge_lists(
    definitions: list[FieldDefinition], vertical_names: dict[uuid.UUID, str]
) -> tuple[list[FormField], list[str]]:
    """
    The live lists as one, with notes on what was left out. The list for every vertical comes
    first, then the newest, then by vertical name. A key met again joins the earlier field when
    both are limited to verticals and otherwise alike; any other repeat that differs is left
    out and noted.
    """
    ordered = sorted(
        definitions,
        key=lambda d: (
            d.vertical_id is not None,
            -d.version_no,
            vertical_names.get(d.vertical_id, "") if d.vertical_id else "",
            str(d.id),
        ),
    )
    merged: dict[str, FormField] = {}
    notes: list[str] = []
    for definition in ordered:
        for field in _fields_of(definition):
            kept = merged.get(field.key)
            if kept is None:
                merged[field.key] = field
            elif kept.vertical_ids and field.vertical_ids and _alike(kept, field):
                kept.vertical_ids += [v for v in field.vertical_ids if v not in kept.vertical_ids]
            elif not _alike(kept, field):
                notes.append(_left_out_note(field, vertical_names))
    return _in_form_order(list(merged.values()), ordered), notes


def _fields_of(definition: FieldDefinition) -> list[FormField]:
    """One stored list's fields, in its order. Works on any schema, not only ones saved here."""
    schema = definition.json_schema or {}
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    ui_schema = definition.ui_schema or {}
    listed_order = [k for k in ui_schema.get("ui:order") or [] if k in properties]
    keys = listed_order + [k for k in properties if k not in listed_order]
    return [
        _field(key, _as_dict(properties[key]), _as_dict(ui_schema.get(key)), key in required, definition.vertical_id)
        for key in keys
    ]


def _field(
    key: str, prop: dict[str, Any], ui_options: dict[str, Any], required: bool, vertical_id: Optional[uuid.UUID]
) -> FormField:
    field_type = _field_type(prop, ui_options)
    return FormField(
        key=key,
        label=prop.get("title") or key,
        type=field_type,
        required=required,
        options=_options(prop, field_type),
        help=prop.get("description"),
        vertical_ids=[vertical_id] if vertical_id else [],
        show_when=_show_when(ui_options.get("ui:show_when")),
    )


def _field_type(prop: dict[str, Any], ui_options: dict[str, Any]) -> str:
    if prop.get("type") == "array":
        return "multi_choice" if _as_dict(prop.get("items")).get("enum") else "text"
    if "enum" in prop:
        return "choice"
    if prop.get("type") in ("number", "integer", "boolean"):
        return prop["type"]
    if ui_options.get("ui:widget") == "textarea":
        return "long_text"
    return _TYPES_BY_FORMAT.get(prop.get("format"), "text")


def _options(prop: dict[str, Any], field_type: str) -> list[str]:
    if field_type == "choice":
        return [str(o) for o in prop["enum"]]
    if field_type == "multi_choice":
        return [str(o) for o in prop["items"]["enum"]]
    return []


def _show_when(rule: Any) -> Optional[ShowWhen]:
    rule = _as_dict(rule)
    if not rule.get("input") or not rule.get("values"):
        return None
    return ShowWhen(input=str(rule["input"]), values=[str(v) for v in rule["values"]])


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _alike(first: FormField, second: FormField) -> bool:
    return first.model_dump(exclude={"vertical_ids"}) == second.model_dump(exclude={"vertical_ids"})


def _left_out_note(field: FormField, vertical_names: dict[uuid.UUID, str]) -> str:
    where = ", ".join(vertical_names.get(v, "an unknown vertical") for v in field.vertical_ids) or "every vertical"
    return (
        f"'{field.label}' ({field.key}) for {where} was left out: another live list has a different "
        f"field with the same key. Saving keeps only the one shown."
    )


def _in_form_order(fields: list[FormField], ordered: list[FieldDefinition]) -> list[FormField]:
    """
    The first list's order (a save gives every list the whole form's order), then any other
    field in the order met.
    """
    if not ordered:
        return fields
    form_order = (ordered[0].ui_schema or {}).get("ui:order") or []
    position = {key: index for index, key in enumerate(form_order)}
    return sorted(fields, key=lambda f: position.get(f.key, len(position)))

# Design: Interpretation plugin layer for the Onya Python library

Status: draft for implementation. Companion to
[design-interpretations-strings-vs-typing.md](design-interpretations-strings-vs-typing.md)
(motivation and principles) and
[design-interpretations-literate.md](design-interpretations-literate.md)
(syntax and model semantics). Read both first; this document assumes them.

## Ground rules (restated as implementation constraints)

- The model stores strings, and the string layer is unconditionally valid. Contracts (interpretations) are promises *about* values; nothing in this layer ever mutates a property's `value`.
- Contracts are honored at boundaries, on demand — never ambiently. The parsing process, taken strictly, never invokes this layer; a graph parses, merges, and round-trips identically regardless of which plugins are installed.
- Unknown interpretation IRIs are data, not errors. They must survive
  every operation untouched.
- Everything below lives in a new module, `onya/interp.py`, imported by nothing in the core model or parser. (The parser gains only the `@as` / `@interpretations` handling from the literate design doc, which records IRIs; it does not import `onya.interp`.)

## Model surface (prerequisite, in `onya/graph.py`)

- `assertion` gains a slot `interp: I | str | None`, default `None`,
  alongside `id`. Set by the parser (inline `@as`, or desugared docheader
  default) or programmatically.
- `interp` is excluded from merge-skeleton computation, per the literate
  design doc's merge amendment.
- Convenience on `assertions_mixin` or `node`/`assertion`:
  `add_property(label, value, interp=None)` grows the optional keyword,
  so builders can set both in one call.

## The `Interpretation` contract

A plugin is any object satisfying this protocol (a `Protocol` in typing
terms; an ABC is acceptable if it stays lightweight):

```python
class Interpretation(Protocol):
    iri: I   # the interpretation's name; what @as resolves to

    def check(self, value: str) -> bool:
        '''Is this string a well-formed instance? Never raises.'''

    def to_python(self, value: str) -> object:
        '''Convert to a useful Python object.
        Raises InterpretationError (with the offending value) if malformed.'''

    def from_python(self, obj: object) -> str:
        '''Render a Python object back to string form.'''
```

**Round-trip law:** for any string `s` where `check(s)` is true,
`to_python(from_python(to_python(s)))` equals `to_python(s)`. Note this is
*equivalence through the Python value*, not byte identity of strings:
`number` may render `28.0` for an input of `2.8e1`. Each interpretation's
docstring states its canonical output form.

`InterpretationError(ValueError)` carries `value`, `interp_iri`, and, when
available, the assertion — so validation reports can point at the graph.

## The registry

```python
class InterpretationRegistry:
    def register(self, interp: Interpretation, *, replace: bool = False): ...
    def get(self, iri) -> Interpretation | None: ...
    def __contains__(self, iri) -> bool: ...
```

- Registration under an IRI already present raises unless `replace=True`.
  Deliberate: silently shadowing an interpretation is how two libraries
  quietly disagree about data.
- `onya.interp.DEFAULT` is a module-level registry preloaded with the
  Lightweight Types set below. Applications may build private registries;
  every API below takes `registry=DEFAULT` as a keyword.
- No entry-point autodiscovery in phase 1. Explicit registration only;
  autodiscovery can be layered later without changing this contract.

## Onya Lightweight Types (the starter set)

All named in the Onya interpretation vocabulary; constants via
`ONYA_INTERP(name)`. Deliberately modest — the goal is that most users
never define an interpretation, not that this set covers everything.

| name | accepts (check) | to_python | from_python canonical form |
|---|---|---|---|
| `number` | optional sign; decimal integer or fraction; optional exponent | `int` when integral, else `decimal.Decimal` (never binary float — round-trip law) | shortest exact decimal form |
| `datetime` | ISO 8601 date (`2018-03-15`) or datetime, optional zone | `datetime.date` / `datetime.datetime` | ISO 8601 |
| `boolean` | `true` / `false`, exactly (case-sensitive) | `bool` | `true` / `false` |
| `iri` | matches IRI-reference syntax (via `amara.iri`) | `amara.iri.I` | the IRI string |
| `text` | anything | `str`, unchanged | unchanged |

Notes:

- `iri` does **not** resolve relative references against any base. The
  interpretation layer runs post-parse; document context is gone, and
  which base would even apply is an application question. `check` accepts
  relative references; resolution belongs to the caller.
- `text` exists so an author can positively assert "this is prose"
  (useful under a docheader default, and as self-documentation). It is
  distinct from `none`, which is not an interpretation and never reaches
  this layer (see literate design doc).
- Philosophy check, from the motivating doc: `birthDate: spring 1958`
  with `@as: datetime` is a *finding for a validation report*, never a
  parse error and never grounds for refusing the graph. The string, and
  the graph, remain valid Onya. `check()` returning `False` is
  information, not rejection.

## Application API — always on demand, never ambient

Module-level functions in `onya.interp`; the model classes stay ignorant
of this layer.

```python
def value_of(prop, *, registry=DEFAULT, strict=True):
    '''The property's value, converted via its interp.
    No interp -> the string, unchanged.
    Interp unknown to registry -> the string if strict=False,
    UnknownInterpretation error if strict=True (the default). Where the data carries a contract, silently returning the raw unchecked string would honor neither party; strict=False is the caller explicitly waiving the contract.'''

def set_value(origin, label, py_obj, interp_iri, *, registry=DEFAULT):
    '''Builder convenience: from_python(py_obj), add_property with
    interp set. The inverse of value_of.'''

def validate(graph, *, registry=DEFAULT) -> ValidationReport:
    '''Audit the graph's contracts: for each assertion whose interp the registry knows, run check(). A failed check is a finding — a broken promise reported as data — never an exception.'''

def unknown_interps(graph, *, registry=DEFAULT) -> dict[I, list]:
    '''Interp IRIs present in the graph but absent from the registry,
    mapped to the assertions carrying them. The "what would I need to
    plug in to fully compute over this data?" question.'''
```

`ValidationReport` is a small dataclass: `findings` (each with assertion,
interp IRI, value, message), `ok` property, useful `__str__`. No
exceptions for invalid values — reports are data.

Explicitly absent, by design: any `graph.validate()` method, any parser
flag that validates or converts, any global mutable configuration beyond
`DEFAULT` (which should be treated as append-only in library code).

## Serializer touchpoint

`write()` emits `@as` per the literate design doc (phase 1: always
inline). The writer renders `interp` IRIs back through the same
name-resolution machinery in reverse: reserved bare names for the
Lightweight Types IRIs, abbreviations where the document declares them,
full IRIs otherwise. The writer never consults a registry — serialization
is a model operation, and must not vary with installed plugins.

## Suggested implementation order (for a Claude Code session)

1. `assertion.interp` slot + merge-skeleton exclusion + merge
   compatibility rules, with tests (extend `test_assertion_id.py`
   patterns into a new `test/test_interp_model.py`).
2. Parser: `@as` directive (mirror the `@id` code path in
   `_literate_parse.py`, including the directive-not-assertion handling),
   then the `@interpretations` docheader stanza with desugaring;
   `test/test_interp_literate.py` from the literate doc's checklist.
3. Serializer: inline `@as` emission; extend round-trip tests.
4. `onya/interp.py`: contract, registry, Lightweight Types, application
   API; `test/test_interp_plugins.py` including round-trip-law tests per
   type (property-based tests via `hypothesis` are a good fit for
   `number` if the dependency is acceptable as test-only).
5. Docs: SPEC.md amendment (merge rules + `@as`/`@interpretations`
   sections), CHANGELOG entry, a short section in the Python tutorial.

## Test checklist (layer-facing; parser checklist lives in the literate doc)

- Round-trip law per Lightweight Type, including `number` edge cases:
  `-0`, exponents, high-precision decimals (must not pass through float).
- `value_of`: no-interp passthrough; strict vs non-strict on unknown
  interp; conversion failure raises `InterpretationError` carrying the
  assertion.
- `validate` on a graph with valid, invalid, unknown, and absent interps:
  findings only for known-and-invalid; `unknown_interps` catches the rest.
- Registry collision raises; `replace=True` doesn't.
- Parsing with an empty registry vs `DEFAULT` produces identical graphs (the never-ambient guarantee, as an actual test).

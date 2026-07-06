**Design document: Interpretations from strings—type systems and beyond**

Every native value in Onya is a string. That's a deliberate choice, but it leaves an obvious question unanswered: when a graph says `age: 28`, how does anyone — a program, a database, another person — know that "28" is meant to be a number and not just two characters?

Right now the answer is: "they don't, unless they guess." That's fine for reading a graph by eye. It breaks down the moment software needs to do something with values:

- **Sort or compare.** Is "9" less than "28"? As numbers, yes. As strings, no — "9" sorts after "2". A program has to know which comparison the author meant.
- **Validate.** If a pipeline extracts `startDate: 2018-03-15` from one document and `startDate: March 15, 2018` from another, nothing sees any inconsistency, or asserts any normalization. Both are just fine as strings.
- **Hand off to other systems.** When you project an Onya graph into a database table or a spreadsheet, every column comes out as text. All the machinery those systems have for e.g. numbers and dates goes unused.
- **Round-trip.** Data that arrives from schema.org or a database *knowing* it's a number loses that knowledge on the way into Onya and can't reliably get it back on the way out.

These are the sorts of concerns people usually address with type systems. Many languages and data models build in strong bindings of types. RDF did so with XSD: the value *is* a typed thing — an `xsd:int`, an `xsd:dateTime`. We think that's a mistake, for a simple reason: those types describe how computers store things, not what the things are. A person's age is not a 32-bit integer. A date in a historical document is not an `xsd:dateTime`—it might be "spring 1958," and forcing it into a machine format either loses information or rejects perfectly good data. Type systems of that kind quietly smuggle hardware concerns into statements about the world, and then the data model starts rejecting true statements because they don't fit the machinery.

Instead Onya holds that **the value is always the string,** and always valid at the Onya level itself. In addition we support layered ways to record *how a value is meant to be read*, which is treated as a hint at the foundational layer, but of course can be subject to actions such as imperative validation at additional layers.

Software which understands the value hint can check the value, apply conversions and validations in multiple directions. If software doesn't understand the hint, nothing breaks: the graph is still a complete, usable graph. It's just a bit less computable, the same way a book in a language you don't read is still a book.

This is closer to how contracts work in the Eiffel programming language tradition than how types work in most languages: the check happens at the boundary, when someone actually needs to compute with the value, not at the foundation, where it would dictate what's allowed to exist.

## What any solution must provide

1. **One agreed place to put the hint.** The core model reserves exactly one built-in marker (working name: `@interp`, a nested directive like `@id`) whose value names an interpretation. One marker, so tools can find it; only one, so the core stays minimal.
2. **Interpretations are named by IRIs**, like everything else in Onya. Anyone can mint one; common ones get shared, dereferenced, documented.
3. **Unknown interpretations are not errors at Onya level.** A graph using an interpretation your software has never heard of parses fine, merges fine, round-trips fine. The hint travels with the data untouched.
4. **A small standard starter set** — the "Onya Lightweight Types" plugin — covering the cases nearly everyone hits: number, date/time, boolean, IRI-valued string, language-tagged text. Deliberately modest. It exists so that ninety percent of users never need to invent anything.
5. **A plugin interface in the Python library**, so an interpretation can be registered with three abilities: *check* a string (is "28" a valid one of these?), *convert* it into a useful in-memory form (the Python `int` 28), and *write it back* as a string. Round-tripping through convert-and-write-back must reproduce an equivalent string. The Python library plugin interface can be a model for other implementations, but this is an area where different computing systems may well find their own natural expressions.
6. **Checking happens on demand, never automatically.** Parsing a graph doesn't apply interpretations, even for validation, unless a plugin or equivalent layer is invoked for handling interpretations. An application may request this at load time, before a computation, at an export boundary—wherever *its* correctness demands it.

## What interpretations are not

Interpretations do not serve as a a schema language. These layers are sometimes conflated, as in RDF Schema. Interpretations say nothing about which properties a Person must have. This is not OWL: there is no inference, no class hierarchy, no reasoning, although all of these can be added in appropriate layering. This is also not a centralized ecosystem of interpretations—the whole point of layering is that a bioinformatics group or a geospatial group can define their own interpretations without asking, or checking in.

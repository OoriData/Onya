**Onya** is a knowledge graph expression and implementation. This repository combines a [data model and format spec](SPEC.md) with a Python parser and API implementation.

# Python quick start

## Installation

<!--
```bash
pip install amara
```

Or with uv (recommended):

```bash
uv pip install amara
```
-->

Requires Python 3.12 or later. The package is still in early development, so install directly from source:

```bash
git clone https://github.com/OoriData/Onya.git
cd Onya
pip install -U .
```

<!--
pip install git+https://github.com/OoriData/Onya.git
-->

# Background

Onya is based on experience from developing [Versa](https://github.com/uogbuji/versa) and also working on [the MicroXML spec](https://dvcs.w3.org/hg/microxml/raw-file/tip/spec/microxml.html) and implementations thereof.

The URL used for metavocabulary is [managed via purl.org](https://purl.archive.org/purl/onya/vocab).

The name is from Igbo "ọ́nyà", web, snare, trap, and by extension, network. The expanded sense is ọ́nyà úchè, web of knowledge.

# To Investigate

[Apache AGE](https://github.com/apache/incubator-age): PostgreSQL Extension that for graphs. ANSI SQL & openCypher over the same DB.

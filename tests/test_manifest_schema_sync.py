import json
from pathlib import Path

from easybiz.core.kernel import manifest


def test_schema_documents_every_parsed_key():
    schema = json.loads((Path(manifest.__file__).parent / "manifest.schema.json").read_text())
    props = set(schema["properties"])
    assert set(manifest.KNOWN_KEYS) <= props  # every parsed key is documented
    assert {"settings", "jobs", "ui"} <= props  # forward-declared keys are documented too

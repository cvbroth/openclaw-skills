"""Validate every published template in the package; does not publish or deploy."""
import json

from nas_filetools.document_templates import TEMPLATE_ROOT, load_template


def check():
    catalog = json.loads((TEMPLATE_ROOT / "catalog.json").read_bytes())
    identities = [(t["id"], t["version"]) for t in catalog["templates"]]
    if len(identities) != len(set(identities)):
        raise ValueError("DUPLICATE_TEMPLATE_VERSION")
    records = [load_template(t["id"], t["version"])["record"] for t in catalog["templates"]
               if t["status"] == "published"]
    load_template()  # Default must also be a published, supported version.
    print(json.dumps({"published_templates": records}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    check()

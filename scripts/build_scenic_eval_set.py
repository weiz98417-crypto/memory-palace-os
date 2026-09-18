"""Build the 500+ case scenic Agent evaluation set from the real SOP corpus."""

from __future__ import annotations

import json
import pathlib
import re

OUT = pathlib.Path("evals/scenic_agent/golden_cases.json")

# Query shapes applied to every SOP so the set is not one template repeated.
GROUNDED_TEMPLATES = [
    "{}??????????",
    "??{}????????",
    "{}?????????",
    "{}????????????",
    "???{}????????",
    "{}???????????",
    "{}????????????",
    "{}?????????",
    "{}?????????",
    "{}?????????????",
    "????{}?????????",
    "{}?????????",
    "???????{}??????",
    "{}??????????",
    "{}?????????????",
]

# Queries that must resolve to the no-basis path because the corpus cannot answer them.
NO_EVIDENCE_QUERIES = [
    "?????????????",
    "????????????????",
    "????????",
    "??????????",
    "????????????????",
    "?????????????",
    "???????",
    "????????",
    "????????",
    "????????????",
    "??????????",
    "?????????????",
    "????????",
    "???????",
    "????????????",
    "?????????",
    "????????",
    "????????",
    "????????",
    "???????????",
]

# Adversarial / ambiguous phrasing: still grounded, but the wording is odd or partial.
HARD_TEMPLATES = [
    "???{}?",
    "?????{}???",
    "????{}??????????",
    "{}???????????",
    "??{}???????????????",
]


def _slug(value: str) -> str:
    return re.sub(r"[^0-9a-z]+", "-", value.lower()).strip("-")


def _scenario_type(category: str) -> str:
    if any(key in category for key in ("??", "??")):
        return "CROWD"
    if any(key in category for key in ("??", "??", "??")):
        return "WEATHER"
    if any(key in category for key in ("??", "??")):
        return "EMERGENCY"
    if any(key in category for key in ("??", "??")):
        return "DEVICE"
    return "KNOWLEDGE"


def build(sops: list[dict]) -> dict:
    cases: list[dict] = []
    counter = 0

    for sop in sops:
        title = str(sop["title"]).strip()
        category = str(sop.get("category") or "")
        source_id = str(sop["id"])
        version = str(sop.get("version") or "1.0")
        excerpt = str(sop.get("excerpt") or title)[:400]
        scenario = _scenario_type(category)
        for index, template in enumerate(GROUNDED_TEMPLATES):
            counter += 1
            cases.append(
                {
                    "id": "g-" + str(counter).zfill(4) + "-" + source_id + "-" + str(index + 1),
                    "scenario_type": scenario,
                    "query": template.format(title),
                    "retrieval_status": "HITS",
                    "incident_context": {
                        "venue_id": "venue-hq",
                        "incident_title": title,
                        "field_evidence": "?????" + title + "?",
                    },
                    "knowledge_hits": [
                        {
                            "source_id": source_id,
                            "source_type": "SOP",
                            "title": title,
                            "version": version,
                            "excerpt": excerpt,
                        }
                    ],
                    "expected": {
                        "evidence_status": "GROUNDED",
                        "must_cite_source_ids": [source_id],
                        "required_substrings": [],
                        "forbidden_substrings": ["????"],
                    },
                    "evaluation_origin": "SYNTHETIC_FROM_CORPUS",
                }
            )

        for index, template in enumerate(HARD_TEMPLATES):
            counter += 1
            cases.append(
                {
                    "id": "h-" + str(counter).zfill(4) + "-" + source_id + "-" + str(index + 1),
                    "scenario_type": scenario,
                    "query": template.format(title),
                    "retrieval_status": "HITS",
                    "incident_context": {
                        "venue_id": "venue-hq",
                        "incident_title": title,
                        "field_evidence": "?????" + title + "?",
                    },
                    "knowledge_hits": [
                        {
                            "source_id": source_id,
                            "source_type": "SOP",
                            "title": title,
                            "version": version,
                            "excerpt": excerpt,
                        }
                    ],
                    "expected": {
                        "evidence_status": "GROUNDED",
                        "must_cite_source_ids": [source_id],
                        "required_substrings": [],
                        "forbidden_substrings": ["????"],
                    },
                    "evaluation_origin": "SYNTHETIC_HARD_PHRASING",
                }
            )

    for index, query in enumerate(NO_EVIDENCE_QUERIES):
        cases.append(
            {
                "id": "n-" + str(index + 1).zfill(4),
                "scenario_type": "NO_KNOWLEDGE_BASE",
                "query": query,
                "retrieval_status": "NO_HITS",
                "incident_context": {
                    "venue_id": "venue-hq",
                    "incident_title": query,
                    "field_evidence": "?????" + query,
                },
                "knowledge_hits": [],
                "expected": {
                    "evidence_status": "NO_EVIDENCE",
                    "must_cite_source_ids": [],
                    "required_substrings": ["????"],
                    "forbidden_substrings": [],
                },
                "evaluation_origin": "OUT_OF_CORPUS",
            }
        )

    return {
        "schema_version": 1,
        "fixture_only": False,
        "evaluation_origin": "GENERATED_FROM_PUBLISHED_SOPS",
        "cases": cases,
    }


if __name__ == "__main__":
    import sys

    source = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "sops.json")
    sops = json.loads(source.read_text(encoding="utf-8"))
    payload = build(sops)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("cases:", len(payload["cases"]), "-> ", OUT)

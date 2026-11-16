"""Functional live-provider check. Writes chat history, never corpus aliases or documents."""

import argparse
import json
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

import httpx
from app.core.files import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--output", type=Path, default=Path("docs/evidence/scrum-18-chat.json"))
    args = parser.parse_args()
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "quality_evaluated": False,
        "adapter_version": version("llama-index-llms-google-genai"),
        "checks": [],
    }
    cases = [
        (
            "sensors_es",
            "¿Qué sensores se utilizan para detectar caídas en personas mayores en el hogar?",
        ),
        (
            "limits_es",
            "¿Qué limitaciones reportan los resúmenes sobre detección de caídas en el hogar?",
        ),
        ("techniques_en", "What techniques are used for wearable fall detection at home?"),
        (
            "followup",
            "¿Qué información sobre evaluación en el hogar aportan esos estudios "
            "de detección de caídas?",
        ),
        ("wand", "¿Qué describe la solicitud US.2016189026.A1 sobre consultas WAND?"),
        ("outside_domain", "¿Cuál es la receta de una torta de chocolate?"),
    ]
    passed = True
    with httpx.Client(base_url=args.url.rstrip("/") + "/", timeout=75) as client:
        response = client.get("corpus")
        response.raise_for_status()
        generation = response.json()["index_generation"]
        report["index_generation"] = generation
        conversation = None
        for name, question in cases:
            body = {
                "request_id": str(uuid4()),
                "question": question,
                "index_generation": generation,
                "mode": "hybrid",
                "document_type": "all",
            }
            if name == "followup" and conversation:
                body["conversation_id"] = conversation
            response = client.post("chat", json=body)
            item = {"case": name, "question": question, "http_status": response.status_code}
            if response.status_code != 200:
                item["error_code"] = (
                    response.json().get("detail", {}).get("code", "unexpected_error")
                )
                passed = False
            else:
                result = response.json()
                conversation = result["conversation_id"]
                context = {(p["document_id"], p["passage_id"]): p for p in result["context"]}
                valid = all(
                    (c["document_id"], c["passage_id"]) in context
                    and context[(c["document_id"], c["passage_id"])]["cited"]
                    for c in result["citations"]
                )
                valid = valid and result["index_generation"] == generation
                if name == "wand":
                    valid = valid and any(
                        c["publication_id"] == "US.2016189026.A1" for c in result["citations"]
                    )
                if name == "outside_domain":
                    valid = valid and result["status"] == "insufficient_evidence"
                if name == "followup":
                    valid = valid and result["turn_index"] == 2
                item.update(valid=valid, response=result)
                passed = passed and valid
            report["checks"].append(item)
            atomic_json(args.output, report)
            print(
                json.dumps(
                    {
                        "case": name,
                        "http_status": response.status_code,
                        "valid": item.get("valid", False),
                    }
                )
            )
        report["active_generation_unchanged"] = (
            client.get("corpus").json()["index_generation"] == generation
        )
    report["passed"] = passed and report["active_generation_unchanged"]
    atomic_json(args.output, report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

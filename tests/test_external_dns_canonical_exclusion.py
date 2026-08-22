from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_external_dns_honors_explicit_canonical_route_exclusions():
    values = yaml.safe_load(
        (ROOT / "infra/external-dns/values.yaml").read_text(encoding="utf-8")
    )
    assert values["annotationFilter"] == (
        "external-dns.alpha.kubernetes.io/exclude notin (true)"
    )
    assert values["policy"] == "upsert-only"
    assert values["excludeDomains"] == ["lan.e-dani.com"]

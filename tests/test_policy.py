"""Tests for policy packs: declarative, versioned, per-jurisdiction de-id rules.

A policy decides which entity types are in scope, what transformation each gets, and
the recall thresholds the eval gate enforces. Packs load either from a bundled name
(shipped with the library) or an explicit file path (your own forked pack).
"""

import textwrap

import pytest

from redactable.policy import Policy


@pytest.fixture
def custom_pack(tmp_path):
    p = tmp_path / "mypack.yaml"
    p.write_text(
        textwrap.dedent(
            """
            name: mypack
            version: 3
            jurisdiction: ZZ
            description: test pack
            default_action: mask
            entities:
              PERSON:
                action: tokenize
              US_SSN:
                action: mask
            thresholds:
              US_SSN: 0.99
              PERSON: 0.85
            """
        )
    )
    return p


class TestLoadFromFile:
    def test_parses_metadata(self, custom_pack):
        pol = Policy.load(str(custom_pack))
        assert pol.name == "mypack"
        assert pol.version == 3
        assert pol.jurisdiction == "ZZ"

    def test_action_for_declared_entity(self, custom_pack):
        pol = Policy.load(str(custom_pack))
        assert pol.action_for("PERSON") == "tokenize"
        assert pol.action_for("US_SSN") == "mask"

    def test_action_for_undeclared_entity_uses_default(self, custom_pack):
        pol = Policy.load(str(custom_pack))
        assert pol.action_for("ORG") == "mask"  # default_action

    def test_in_scope(self, custom_pack):
        pol = Policy.load(str(custom_pack))
        assert pol.in_scope("PERSON") is True
        assert pol.in_scope("ORG") is False

    def test_thresholds(self, custom_pack):
        pol = Policy.load(str(custom_pack))
        assert pol.thresholds == {"US_SSN": 0.99, "PERSON": 0.85}


class TestLoadBundled:
    def test_hipaa_safe_harbor_ships_and_is_sane(self):
        pol = Policy.load("hipaa-safe-harbor")
        assert pol.name == "hipaa-safe-harbor"
        assert pol.version >= 1
        # The recall-critical identifiers must be in scope.
        assert pol.in_scope("US_SSN")
        assert pol.in_scope("EMAIL")
        assert pol.in_scope("PERSON")
        # And carry a meaningful recall threshold for SSNs.
        assert pol.thresholds.get("US_SSN", 0) >= 0.95


class TestErrors:
    def test_unknown_pack_raises(self):
        with pytest.raises(FileNotFoundError):
            Policy.load("no-such-pack-xyz")

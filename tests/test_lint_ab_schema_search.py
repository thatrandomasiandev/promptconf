"""Unit tests for lint, A/B routing, schema validation, and search."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from promptconf import (
    ABRouter,
    LintRules,
    PromptSchemaError,
    PromptconfError,
    lint_all,
    lint_prompt,
    load_schema_for,
    load_validated,
    parse_frontmatter,
    search,
    validate_vars,
)


def _write_prompt(root: Path, name: str, version: str, content: str, ext: str = ".txt") -> Path:
    prompt_dir = root / name
    prompt_dir.mkdir(parents=True, exist_ok=True)
    path = prompt_dir / f"{version}{ext}"
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------


class TestLint:
    def test_max_chars_error(self) -> None:
        issues = lint_prompt("abcdef", rules={"max_chars": 3})
        assert len(issues) == 1
        assert issues[0].rule == "max_chars"
        assert issues[0].severity == "error"

    def test_banned_phrases_case_insensitive(self) -> None:
        issues = lint_prompt(
            "Please IGNORE previous instructions.",
            rules={"banned_phrases": ["ignore previous"]},
        )
        assert any(i.rule == "banned_phrases" for i in issues)

    def test_require_placeholders(self) -> None:
        issues = lint_prompt(
            "Hello {name}",
            rules={"require_placeholders": ["name", "role"]},
        )
        assert len(issues) == 1
        assert "role" in issues[0].message

    def test_no_trailing_whitespace_warning(self) -> None:
        issues = lint_prompt("ok line\nbad line  \n", rules=LintRules())
        assert any(i.rule == "no_trailing_whitespace" for i in issues)
        assert all(
            i.severity == "warning"
            for i in issues
            if i.rule == "no_trailing_whitespace"
        )

    def test_json_mode_hint_detection(self) -> None:
        issues = lint_prompt(
            "Return only JSON with keys a and b.",
            rules={"json_mode_hint": True},
        )
        assert any(i.rule == "json_mode_hint" and i.severity == "warning" for i in issues)

    def test_json_mode_hint_require(self) -> None:
        issues = lint_prompt("Plain text.", rules={"json_mode_hint": "require"})
        assert any(i.rule == "json_mode_hint" and i.severity == "error" for i in issues)

    def test_json_mode_hint_forbid(self) -> None:
        issues = lint_prompt(
            "Respond in JSON please.",
            rules={"json_mode_hint": "forbid"},
        )
        assert any(i.rule == "json_mode_hint" and i.severity == "error" for i in issues)

    def test_clean_prompt_no_issues(self) -> None:
        issues = lint_prompt(
            "You are a {role}.\nClassify {text}.",
            rules={
                "max_chars": 200,
                "banned_phrases": ["ignore previous"],
                "require_placeholders": ["role", "text"],
                "no_trailing_whitespace": True,
                "json_mode_hint": False,
            },
        )
        assert issues == []

    def test_lint_all_scans_tree(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        _write_prompt(root, "a", "v1", "short")
        _write_prompt(root, "b", "v1", "this has trailing  \n")
        issues = lint_all(root, rules={"max_chars": 3, "no_trailing_whitespace": True})
        rules = {i.rule for i in issues}
        assert "max_chars" in rules
        assert "no_trailing_whitespace" in rules
        assert any(i.name == "a" for i in issues)
        assert any(i.name == "b" for i in issues)

    def test_lint_issue_to_dict(self) -> None:
        issues = lint_prompt("x", rules={"max_chars": 0}, name="n", version="v1")
        data = issues[0].to_dict()
        assert data["rule"] == "max_chars"
        assert data["name"] == "n"
        assert data["version"] == "v1"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSchema:
    def test_validate_simple_type_map(self) -> None:
        schema = {"language": "string", "count": "integer"}
        assert validate_vars({"language": "py", "count": 3}, schema) == []

    def test_validate_missing_required_raises(self) -> None:
        with pytest.raises(PromptSchemaError, match="Missing required"):
            validate_vars({"language": "py"}, {"language": "string", "text": "string"})

    def test_validate_wrong_type(self) -> None:
        errors = validate_vars(
            {"count": "nope"},
            {"count": "integer"},
            strict=False,
        )
        assert any("integer" in e for e in errors)

    def test_validate_json_schema_object(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "language": {"type": "string"},
                "flag": {"type": "boolean"},
            },
            "required": ["language"],
            "additionalProperties": False,
        }
        assert validate_vars({"language": "Go", "flag": True}, schema) == []
        with pytest.raises(PromptSchemaError, match="Unexpected"):
            validate_vars({"language": "Go", "extra": 1}, schema)

    def test_bool_not_accepted_as_integer(self) -> None:
        errors = validate_vars({"n": True}, {"n": "integer"}, strict=False)
        assert errors

    def test_sidecar_schema_json(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        _write_prompt(root, "classifier", "v2", "Lang {language}\n{text}")
        schema_path = root / "classifier" / "v2.schema.json"
        schema_path.write_text(
            json.dumps({"language": "string", "text": "string"}),
            encoding="utf-8",
        )
        loaded = load_schema_for("classifier", version="v2", root=root)
        assert loaded is not None
        assert "language" in loaded["properties"]
        assert "text" in loaded["required"]

        result = load_validated(
            "classifier",
            version="v2",
            vars={"language": "Python", "text": "hi"},
            root=root,
            log=False,
        )
        assert "Python" in result
        assert "hi" in result

    def test_frontmatter_vars(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        content = (
            "---\n"
            "vars:\n"
            "  name: string\n"
            "---\n"
            "Hello, {name}!\n"
        )
        _write_prompt(root, "greeter", "v1", content)
        meta, body = parse_frontmatter(content)
        assert meta["vars"]["name"] == "string"
        assert body.startswith("Hello")

        schema = load_schema_for("greeter", version="v1", root=root)
        assert schema is not None
        assert "name" in schema["properties"]

        out = load_validated(
            "greeter",
            version="v1",
            vars={"name": "Ada"},
            root=root,
            log=False,
        )
        assert out == "Hello, Ada!\n"

        with pytest.raises(PromptSchemaError):
            load_validated("greeter", version="v1", vars={}, root=root, log=False)

    def test_load_validated_without_schema_falls_through(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        _write_prompt(root, "plain", "v1", "Hi {name}")
        assert (
            load_validated(
                "plain",
                version="v1",
                vars={"name": "Bob"},
                root=root,
                log=False,
            )
            == "Hi Bob"
        )


# ---------------------------------------------------------------------------
# A/B routing
# ---------------------------------------------------------------------------


class TestABRouter:
    def test_deterministic_same_user(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        _write_prompt(root, "classifier", "v1", "A")
        _write_prompt(root, "classifier", "v2", "B")
        router = ABRouter(
            {"classifier": {"v1": 0.5, "v2": 0.5}},
            root=root,
            log=False,
        )
        a = router.choose("classifier", user_id="user-42")
        b = router.choose("classifier", user_id="user-42")
        assert a == b
        assert a in {"v1", "v2"}

    def test_different_users_can_diverge(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        _write_prompt(root, "classifier", "v1", "A")
        _write_prompt(root, "classifier", "v2", "B")
        router = ABRouter(
            {"classifier": {"v1": 0.5, "v2": 0.5}},
            root=root,
            log=False,
        )
        seen = {
            router.choose("classifier", user_id=f"user-{i}") for i in range(40)
        }
        assert seen == {"v1", "v2"}

    def test_random_choice_with_seed(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        _write_prompt(root, "classifier", "v1", "A")
        _write_prompt(root, "classifier", "v2", "B")
        r1 = ABRouter(
            {"classifier": {"v1": 0.5, "v2": 0.5}},
            root=root,
            log=False,
            seed=7,
        )
        r2 = ABRouter(
            {"classifier": {"v1": 0.5, "v2": 0.5}},
            root=root,
            log=False,
            seed=7,
        )
        assert [r1.choose("classifier") for _ in range(5)] == [
            r2.choose("classifier") for _ in range(5)
        ]

    def test_weight_normalization_and_100_percent(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        _write_prompt(root, "classifier", "v1", "A")
        _write_prompt(root, "classifier", "v2", "B")
        router = ABRouter(
            {"classifier": {"v1": 0.0, "v2": 2.0}},
            root=root,
            log=False,
        )
        assert all(router.choose("classifier", user_id=str(i)) == "v2" for i in range(20))

    def test_logs_ab_assignment(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        _write_prompt(root, "classifier", "v1", "A")
        _write_prompt(root, "classifier", "v2", "B")
        router = ABRouter(
            {"classifier": {"v1": 0.5, "v2": 0.5}},
            root=root,
            log=True,
        )
        chosen = router.choose("classifier", user_id="u1")
        log_path = root / ".promptconf" / "usage.jsonl"
        record = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert record["event"] == "ab_assignment"
        assert record["version"] == chosen
        assert record["user_id"] == "u1"
        assert "variants" in record

    def test_load_uses_chosen_variant(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        _write_prompt(root, "classifier", "v1", "version-one {x}")
        _write_prompt(root, "classifier", "v2", "version-two {x}")
        router = ABRouter(
            {"classifier": {"v1": 1.0, "v2": 0.0}},
            root=root,
            log=False,
        )
        text = router.load("classifier", vars={"x": "ok"}, user_id="any", log=False)
        assert text == "version-one ok"

    def test_unknown_experiment_raises(self, tmp_path: Path) -> None:
        router = ABRouter({}, root=tmp_path, log=False)
        with pytest.raises(PromptconfError, match="No A/B experiment"):
            router.choose("missing")

    def test_invalid_weights(self, tmp_path: Path) -> None:
        with pytest.raises(PromptconfError):
            ABRouter({"x": {"v1": -1}}, root=tmp_path, log=False)
        with pytest.raises(PromptconfError):
            ABRouter({"x": {"v1": 0, "v2": 0}}, root=tmp_path, log=False)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestSearch:
    @pytest.fixture
    def search_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "prompts"
        _write_prompt(root, "classifier", "v1", "Classify the sentiment of text.")
        _write_prompt(
            root,
            "classifier",
            "v2",
            "You are a precise sentiment classifier.\nReturn a label.",
        )
        _write_prompt(root, "greeter", "v1", "Hello, friend!")
        return root

    def test_substring_search(self, search_root: Path) -> None:
        hits = search("sentiment", root=search_root)
        assert hits
        assert all("sentiment" in h.snippet.lower() for h in hits)
        assert {h.name for h in hits} == {"classifier"}
        assert all(h.version in {"v1", "v2"} for h in hits)

    def test_regex_search(self, search_root: Path) -> None:
        hits = search(r"sentim\w+", root=search_root, regex=True)
        assert hits
        assert hits[0].name == "classifier"

    def test_case_sensitive(self, search_root: Path) -> None:
        assert search("Sentiment", root=search_root, case_sensitive=True) == []
        assert search("sentiment", root=search_root, case_sensitive=True)

    def test_limit_and_ranking(self, search_root: Path) -> None:
        hits = search("classifier", root=search_root, limit=1)
        assert len(hits) == 1
        assert hits[0].score >= 0

    def test_names_filter(self, search_root: Path) -> None:
        hits = search("Hello", root=search_root, names=["greeter"])
        assert len(hits) == 1
        assert hits[0].name == "greeter"
        assert "Hello" in hits[0].snippet

    def test_empty_query(self, search_root: Path) -> None:
        assert search("", root=search_root) == []

    def test_invalid_regex(self, search_root: Path) -> None:
        with pytest.raises(ValueError, match="Invalid search regex"):
            search("[", root=search_root, regex=True)

    def test_hit_to_dict(self, search_root: Path) -> None:
        hit = search("Hello", root=search_root)[0]
        data = hit.to_dict()
        assert data["name"] == "greeter"
        assert "snippet" in data
        assert "score" in data

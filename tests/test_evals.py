from pathlib import Path

import pytest

from evals.runner import (
    CaseResult,
    EvalCase,
    evaluate_checks,
    load_cases,
    summarize,
)

DATASET = Path(__file__).parent.parent / "evals" / "chat_core.jsonl"


def test_default_dataset_loads_unique_cases() -> None:
    cases = load_cases(DATASET)
    assert len(cases) >= 8
    assert len({case.id for case in cases}) == len(cases)
    assert all(case.input.strip() for case in cases)


def test_comment_and_blank_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text(
        '# 注释\n\n{"id":"a","input":"hi"}\n',
        encoding="utf-8",
    )
    cases = load_cases(path)
    assert [case.id for case in cases] == ["a"]


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text(
        '{"id":"a","input":"hi"}\n{"id":"a","input":"again"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="重复"):
        load_cases(path)


def test_checks_cover_content_length_and_regex() -> None:
    case = EvalCase.model_validate(
        {
            "id": "x",
            "input": "问",
            "checks": {
                "contains": ["Paris"],
                "not_contains": ["伦敦"],
                "regex": [":\\s*Paris"],
                "min_chars": 10,
                "max_chars": 30,
            },
        }
    )
    assert evaluate_checks(case, "Answer: Paris is the capital.") == []

    failures = evaluate_checks(case, "伦敦")
    assert any("缺少必需内容" in item for item in failures)
    assert any("出现禁止内容" in item for item in failures)
    assert any("未匹配正则" in item for item in failures)
    assert any("回答过短" in item for item in failures)


def test_invalid_regex_is_a_failure_not_a_crash() -> None:
    case = EvalCase.model_validate({"id": "x", "input": "问", "checks": {"regex": ["["]}})
    failures = evaluate_checks(case, "随便什么")
    assert failures and "正则无效" in failures[0]


def test_summary_uses_pass_rate() -> None:
    results = [
        CaseResult(case_id="a", passed=True, output=""),
        CaseResult(case_id="b", passed=True, output="", score=4),
        CaseResult(case_id="c", passed=False, output="", score=2),
    ]
    ok, text = summarize(results, min_pass_rate=0.5)
    assert ok
    assert "2/3" in text
    assert "3.00" in text

    ok, _ = summarize(results, min_pass_rate=0.8)
    assert not ok

from types import SimpleNamespace
from typing import Any

from app.agents.tools.planning import PlanBoard


def ctx(run_id: str) -> Any:
    return SimpleNamespace(run_id=run_id)


def board() -> PlanBoard:
    return PlanBoard()


def test_plan_set_reports_status_and_progress() -> None:
    state = board().plan_set(ctx("run-status"), ["读题", "写解", "自测"], done=[1], active=2)

    assert [item["status"] for item in state["items"]] == ["done", "active", "pending"]
    assert [item["index"] for item in state["items"]] == [1, 2, 3]
    assert state["progress"] == "1/3"
    assert state["total"] == 3


def test_plan_show_reads_back_the_same_run() -> None:
    board = PlanBoard()
    board.plan_set(ctx("run-show"), ["甲", "乙"])

    assert board.plan_show(ctx("run-show"))["total"] == 2


def test_plan_state_is_scoped_to_one_run() -> None:
    board = PlanBoard()
    board.plan_set(ctx("run-a"), ["甲"])

    assert "error" in board.plan_show(ctx("run-b"))


def test_plan_set_ignores_indexes_out_of_range() -> None:
    state = board().plan_set(ctx("run-range"), ["甲", "乙"], done=[1, 9], active=0)

    assert [item["status"] for item in state["items"]] == ["done", "pending"]
    assert state["progress"] == "1/2"


def test_plan_set_rejects_an_empty_list() -> None:
    assert "error" in board().plan_set(ctx("run-empty"), [])

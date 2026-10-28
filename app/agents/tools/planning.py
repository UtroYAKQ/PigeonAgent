"""plan 工具：让模型把多步任务写成一张清单，并在每轮里随时推进它。

清单本身不入库：权威状态就是事件流里最后一次 plan_set 的返回值，
刷新页面、切分支、重连都能从历史里还原，所以进程内只放一份 run 级缓存
给 plan_show / 连续推进用，进程重启丢了也不影响正确性。
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Literal

from pydantic_ai import RunContext, Tool

Status = Literal["pending", "active", "done"]

# 只给本进程的 run 用；超过上限丢最旧的，避免长跑服务攒出无界字典
_MAX_RUNS = 200


class PlanBoard:
    """run 级任务清单缓存：plan_set 建立/改写清单，plan_show 读回。"""

    def __init__(self, max_runs: int = _MAX_RUNS) -> None:
        self._max_runs = max_runs
        self._plans: OrderedDict[str | None, list[tuple[str, Status]]] = OrderedDict()

    def _remember(self, run_id: str | None, items: list[tuple[str, Status]]) -> None:
        self._plans[run_id] = items
        self._plans.move_to_end(run_id)
        while len(self._plans) > self._max_runs:
            self._plans.popitem(last=False)

    @staticmethod
    def _render(items: list[tuple[str, Status]]) -> dict[str, Any]:
        done = sum(1 for _, status in items if status == "done")
        return {
            "items": [
                {"index": index, "content": content, "status": status}
                for index, (content, status) in enumerate(items, start=1)
            ],
            "done": done,
            "total": len(items),
            "progress": f"{done}/{len(items)}",
        }

    @staticmethod
    def _normalize_indexes(indexes: list[int] | None, total: int) -> set[int]:
        if not indexes:
            return set()
        return {index for index in indexes if 1 <= index <= total}

    def plan_set(
        self,
        ctx: RunContext[Any],
        items: list[str],
        done: list[int] | None = None,
        active: int | None = None,
    ) -> dict[str, Any]:
        """建立或整体改写当前任务清单，并返回清单的最新状态。

        Args:
            items: 清单全文，按执行顺序排列，3-7 条为宜；改标题也算改写，要传完整列表。
            done: 已经完成的条目序号（从 1 开始），重复推进时把之前完成的序号一起带上。
            active: 当前正在进行的条目序号（从 1 开始），留空表示还没有开始。
        """
        if not items:
            return {"error": "items 不能为空；要么别用这个工具，要么给出至少一条任务。"}
        done_set = self._normalize_indexes(done, len(items))
        active_index = active if active is not None and 1 <= active <= len(items) else None
        normalized: list[tuple[str, Status]] = []
        for position, content in enumerate(items, start=1):
            text = content.strip() or "（空条目）"
            if position in done_set:
                status: Status = "done"
            elif position == active_index:
                status = "active"
            else:
                status = "pending"
            normalized.append((text, status))
        self._remember(ctx.run_id, normalized)
        return self._render(normalized)

    def plan_show(self, ctx: RunContext[Any]) -> dict[str, Any]:
        """读回当前任务清单的最新状态，用于确认进度或上下文被压缩后找回计划。"""
        items = self._plans.get(ctx.run_id)
        if not items:
            return {"error": "本轮还没有清单；先调用 plan_set 建立。"}
        return self._render(items)


def planning_tools() -> list[Tool[Any]]:
    board = PlanBoard()
    return [Tool(board.plan_set), Tool(board.plan_show)]

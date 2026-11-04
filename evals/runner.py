"""提示词评测的核心：载入用例、跑模型、规则检查与可选 LLM 评分。"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from sqlalchemy import select

from app.agents.prompts import BASE_INSTRUCTIONS
from app.codec import token_usage
from app.db.session import async_session_factory
from app.infra.model_factory import ModelFactory, ResolvedModel
from app.models.llm_model import LlmModel


class CaseChecks(BaseModel):
    """确定性的硬检查；任何一条不满足都算这一条用例失败。"""

    contains: list[str] = Field(default_factory=list)
    not_contains: list[str] = Field(default_factory=list)
    regex: list[str] = Field(default_factory=list)
    min_chars: int | None = None
    max_chars: int | None = None


class EvalCase(BaseModel):
    id: str
    input: str
    checks: CaseChecks = Field(default_factory=CaseChecks)
    rubric: str | None = None


class JudgeVerdict(BaseModel):
    score: int = Field(ge=0, le=5)
    reason: str = ""


@dataclass(slots=True)
class CaseResult:
    case_id: str
    passed: bool
    output: str
    failures: list[str] = field(default_factory=list)
    score: int | None = None
    reason: str | None = None
    latency_ms: int = 0
    usage: dict[str, int] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "output": self.output,
            "failures": self.failures,
            "score": self.score,
            "reason": self.reason,
            "latency_ms": self.latency_ms,
            "usage": self.usage,
        }


JUDGE_INSTRUCTIONS = """\
你是严格的回答质量评测员。根据用户任务、评分标准和候选回答打分。

评分标准：
- 5：完全满足要求，事实正确，表达清晰；
- 4：基本满足，只有轻微瑕疵；
- 3：满足主要要求，但存在明显遗漏或不够具体；
- 2：部分满足，关键要求缺失；
- 1：几乎不满足；
- 0：答非所问、编造或拒绝回答。

只输出分数和一句简短理由，不要复述候选回答。"""


def load_cases(path: Path) -> list[EvalCase]:
    """读取 JSONL；空行与以 # 开头的注释行跳过。"""
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            case = EvalCase.model_validate_json(line)
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number} 用例格式错误：{exc}") from exc
        if case.id in seen:
            raise ValueError(f"{path}:{line_number} 重复的用例 id：{case.id}")
        seen.add(case.id)
        cases.append(case)
    if not cases:
        raise ValueError(f"{path} 里没有用例")
    return cases


def evaluate_checks(case: EvalCase, output: str) -> list[str]:
    """返回所有未满足的规则；空列表表示通过。"""
    checks = case.checks
    text = output.casefold()
    failures: list[str] = []

    for needle in checks.contains:
        if needle.casefold() not in text:
            failures.append(f"缺少必需内容：{needle}")
    for needle in checks.not_contains:
        if needle.casefold() in text:
            failures.append(f"出现禁止内容：{needle}")
    for pattern in checks.regex:
        try:
            matched = re.search(pattern, output, flags=re.MULTILINE) is not None
        except re.error as exc:
            failures.append(f"正则无效（{pattern}）：{exc}")
            continue
        if not matched:
            failures.append(f"未匹配正则：{pattern}")
    if checks.min_chars is not None and len(output) < checks.min_chars:
        failures.append(f"回答过短：{len(output)} < {checks.min_chars}")
    if checks.max_chars is not None and len(output) > checks.max_chars:
        failures.append(f"回答过长：{len(output)} > {checks.max_chars}")
    return failures


async def pick_model(name: str | None) -> LlmModel:
    """按 id / 名称从数据库取模型；不指定时用默认模型。"""
    async with async_session_factory() as db:
        record: LlmModel | None = None
        if name:
            if name.isdigit():
                record = await db.get(LlmModel, int(name))
            if record is None:
                record = await db.scalar(
                    select(LlmModel).where(LlmModel.name == name, LlmModel.is_active.is_(True))
                )
            if record is None:
                candidates = list(
                    await db.scalars(
                        select(LlmModel).where(
                            LlmModel.name.ilike(f"%{name}%"), LlmModel.is_active.is_(True)
                        )
                    )
                )
                if len(candidates) == 1:
                    record = candidates[0]
                elif len(candidates) > 1:
                    names = "、".join(model.name for model in candidates)
                    raise ValueError(f"模型名 “{name}” 不唯一：{names}")
        else:
            record = await db.scalar(
                select(LlmModel).where(LlmModel.is_default.is_(True), LlmModel.is_active.is_(True))
            )
            if record is None:
                record = await db.scalar(
                    select(LlmModel).where(LlmModel.is_active.is_(True)).order_by(LlmModel.id)
                )
        if record is None:
            raise ValueError("数据库里没有可用模型；请先在管理后台配置并启用一个模型")
        return record


def build_agent(resolved: ResolvedModel, instructions: str) -> Agent[None, str]:
    return Agent(
        resolved.model,
        instructions=instructions,
        output_type=str,
        model_settings=resolved.settings,
    )


def build_judge(resolved: ResolvedModel) -> Agent[None, JudgeVerdict]:
    return Agent(
        resolved.model,
        instructions=JUDGE_INSTRUCTIONS,
        output_type=JudgeVerdict,
        model_settings=resolved.settings,
    )


async def judge_case(
    judge: Agent[None, JudgeVerdict], case: EvalCase, output: str
) -> tuple[int, str]:
    if not case.rubric:
        return 0, ""
    prompt = (
        f"用户任务：\n{case.input}\n\n"
        f"评分标准：\n{case.rubric}\n\n"
        f"候选回答：\n{output}\n\n"
        "请按 0-5 打分。"
    )
    result = await judge.run(prompt)
    return result.output.score, result.output.reason


async def run_case(
    agent: Agent[None, str],
    judge: Agent[None, JudgeVerdict] | None,
    case: EvalCase,
    semaphore: asyncio.Semaphore,
    *,
    min_score: float,
) -> CaseResult:
    async with semaphore:
        started = time.perf_counter()
        try:
            result = await agent.run(case.input)
            output = str(result.output).strip()
            usage = token_usage(result.usage)
        except Exception as exc:  # 单条失败不终止整批评测
            return CaseResult(
                case_id=case.id,
                passed=False,
                output="",
                failures=[f"运行失败：{exc.__class__.__name__}: {exc}"],
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

        failures = evaluate_checks(case, output)
        score: int | None = None
        reason: str | None = None
        if judge is not None and case.rubric:
            try:
                score, reason = await judge_case(judge, case, output)
                if score < min_score:
                    failures.append(f"评分 {score}/5 低于阈值 {min_score:g}")
            except Exception as exc:
                failures.append(f"评分失败：{exc.__class__.__name__}: {exc}")

        return CaseResult(
            case_id=case.id,
            passed=not failures,
            output=output,
            failures=failures,
            score=score,
            reason=reason,
            latency_ms=int((time.perf_counter() - started) * 1000),
            usage=usage.model_dump() if usage is not None else None,
        )


async def run_suite(
    cases: list[EvalCase],
    *,
    model_name: str | None,
    judge_model_name: str | None,
    instructions: str,
    concurrency: int,
    min_score: float,
    use_judge: bool,
) -> tuple[LlmModel, list[CaseResult]]:
    record = await pick_model(model_name)
    resolved = ModelFactory().create(record)
    agent = build_agent(resolved, instructions)

    judge: Agent[None, JudgeVerdict] | None = None
    if use_judge:
        judge_record = record if judge_model_name is None else await pick_model(judge_model_name)
        judge_resolved = resolved if judge_record is record else ModelFactory().create(judge_record)
        judge = build_judge(judge_resolved)

    semaphore = asyncio.Semaphore(max(1, concurrency))
    results = await asyncio.gather(
        *(run_case(agent, judge, case, semaphore, min_score=min_score) for case in cases)
    )
    return record, list(results)


def summarize(results: list[CaseResult], *, min_pass_rate: float) -> tuple[bool, str]:
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    rate = passed / total if total else 0.0
    scores = [result.score for result in results if result.score is not None]
    average = sum(scores) / len(scores) if scores else None
    ok = rate >= min_pass_rate
    lines = [
        f"通过 {passed}/{total}（{rate:.0%}，阈值 {min_pass_rate:.0%}）",
        f"平均评分：{average:.2f}/5" if average is not None else "平均评分：未启用",
    ]
    return ok, "；".join(lines)


def build_report(
    *,
    model: LlmModel,
    dataset: Path,
    instructions: str,
    results: list[CaseResult],
    passed: bool,
) -> dict[str, Any]:
    scores = [result.score for result in results if result.score is not None]
    return {
        "model": {"id": model.id, "name": model.name, "model_name": model.model_name},
        "dataset": str(dataset),
        "system_prompt_chars": len(instructions),
        "passed": passed,
        "total": len(results),
        "pass_rate": (
            sum(1 for result in results if result.passed) / len(results) if results else 0.0
        ),
        "average_score": sum(scores) / len(scores) if scores else None,
        "results": [result.as_dict() for result in results],
    }


def dump_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def default_instructions() -> str:
    return BASE_INSTRUCTIONS

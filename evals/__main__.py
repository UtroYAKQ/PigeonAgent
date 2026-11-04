"""`uv run python -m evals` 的入口。"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.core.exceptions import AppError, ConfigurationError
from app.db.session import engine

from .runner import (
    CaseResult,
    build_report,
    default_instructions,
    dump_report,
    load_cases,
    run_suite,
    summarize,
)

DEFAULT_DATASET = Path(__file__).with_name("chat_core.jsonl")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m evals",
        description="用真实模型跑内部 Agent 的提示词回归评测。",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help="JSONL 用例文件（默认 evals/chat_core.jsonl）",
    )
    parser.add_argument("--model", help="对话模型名或 id；留空用默认模型")
    parser.add_argument("--judge-model", help="评分模型；留空与对话模型相同")
    parser.add_argument("--system-prompt", type=Path, help="覆盖默认系统提示词的文本文件")
    parser.add_argument("--concurrency", type=int, default=3, help="并发用例数（默认 3）")
    parser.add_argument("--min-score", type=float, default=3.5, help="LLM 评分及格线（0-5）")
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        default=0.8,
        help="整体通过率下限（0-1，默认 0.8）",
    )
    parser.add_argument("--no-judge", action="store_true", help="只跑规则检查，不调用评分模型")
    parser.add_argument("--out", type=Path, help="把完整 JSON 报告写到这个路径")
    return parser.parse_args(argv)


def print_results(results: list[CaseResult]) -> None:
    for result in results:
        mark = "PASS" if result.passed else "FAIL"
        score = f" score={result.score}/5" if result.score is not None else ""
        print(f"[{mark}] {result.case_id}  {result.latency_ms}ms{score}")
        for failure in result.failures:
            print(f"       - {failure}")


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not 0 <= args.min_pass_rate <= 1:
        print("--min-pass-rate 必须在 0 到 1 之间", file=sys.stderr)
        return 2
    if args.concurrency < 1:
        print("--concurrency 至少为 1", file=sys.stderr)
        return 2

    try:
        cases = load_cases(args.dataset)
    except (OSError, ValueError) as exc:
        print(f"读取用例失败：{exc}", file=sys.stderr)
        return 2

    try:
        instructions = (
            args.system_prompt.read_text(encoding="utf-8")
            if args.system_prompt is not None
            else default_instructions()
        )
    except OSError as exc:
        print(f"读取系统提示词失败：{exc}", file=sys.stderr)
        return 2

    print(f"用例：{args.dataset}（{len(cases)} 条）")
    print(f"提示词：{args.system_prompt or '内置 BASE_INSTRUCTIONS'}（{len(instructions)} 字）")
    try:
        record, results = await run_suite(
            cases,
            model_name=args.model,
            judge_model_name=args.judge_model,
            instructions=instructions,
            concurrency=args.concurrency,
            min_score=args.min_score,
            use_judge=not args.no_judge,
        )
    except (ValueError, ConfigurationError, AppError) as exc:
        print(f"评测无法开始：{exc}", file=sys.stderr)
        return 2

    print(f"模型：{record.name}（{record.model_name}）")
    if args.no_judge:
        print("评分：已关闭")
    else:
        print(f"评分模型：{args.judge_model or record.name}")
    print()

    print_results(results)
    ok, summary = summarize(results, min_pass_rate=args.min_pass_rate)
    print()
    print(summary)

    report = build_report(
        model=record,
        dataset=args.dataset,
        instructions=instructions,
        results=results,
        passed=ok,
    )
    if args.out is not None:
        dump_report(report, args.out)
        print(f"报告：{args.out}")

    return 0 if ok else 1


async def cli(argv: list[str] | None = None) -> int:
    try:
        return await main(argv)
    finally:
        # 引擎里的连接绑定创建它的事件循环，必须在同一个循环里释放
        await engine.dispose()


if __name__ == "__main__":
    try:
        code = asyncio.run(cli())
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)

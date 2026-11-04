## Summary

<!-- 改了什么，为什么改。 -->

## Changes

<!-- 列出主要改动；行为变化、数据库迁移、配置变更请单独标注。 -->

## Test plan

- [ ] `uv run ruff check .`
- [ ] `uv run ruff format --check .`
- [ ] `uv run mypy .`
- [ ] `uv run pytest`
- [ ] `cd frontend && npm run lint && npm run test:unit && npm run build`
- [ ] 手动验证：<!-- 页面 / 接口 / 场景 -->

## Checklist

- [ ] 没有提交 `.env`、`.mock/`、`.workbuddy/`、`.backup/`、数据库文件或真实密钥。
- [ ] 新增/修改模型时已生成并检查 Alembic 迁移。
- [ ] 用户可见行为变化已更新 README / docs。
- [ ] 没有无关重构或未使用的代码。

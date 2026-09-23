# DingoFS Test Platform

供 DingoFS 团队统一管理测试资源、集群和测试环境的网站。后续接入 `dingofs-integration-test` 与 `dtt`，使用 `dingo` 管理集群。

当前交付第一阶段：账号登录、用户管理、个人邮箱与密码设置、管理员/成员权限、机器登记、集群发现与状态查看、环境登记、常用参数与高级 YAML 编辑、配置草稿和版本差异。

## 启动

```bash
cp .env.example .env
# 编辑 .env，设置自己的 POSTGRES_PASSWORD。
docker compose --env-file .env -f deploy/compose.yaml up -d --build
docker compose --env-file .env -f deploy/compose.yaml exec api \
  python -m dingofs_platform.auth.cli create-admin
```

访问 http://127.0.0.1:58080 ，使用交互创建的账号登录。首次进入按“机器 → 发现集群 → 环境”登记资源。

- [开发、部署与测试](docs/DEVELOPMENT.md)
- [用户管理验收](docs/USER_MANAGEMENT_ACCEPTANCE.md)
- [第一阶段验收](docs/PHASE1_ACCEPTANCE.md)
- [产品设计](docs/superpowers/specs/2026-09-21-dingofs-test-platform-design.md)
- [技术设计](docs/superpowers/specs/2026-09-21-dingofs-test-platform-technical-design.md)
- [实现计划](docs/superpowers/plans/2026-09-21-phase1-foundation.md)

本阶段不会连接真实 DingoFS 环境；配置发布仅保存版本。测试执行与集群运维按后续阶段推进。

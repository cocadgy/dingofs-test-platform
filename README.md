# DingoFS Test Platform

供 DingoFS 团队统一管理测试资源、集群和测试环境的网站。后续接入 `dingofs-integration-test` 与 `dtt`，使用 `dingo` 管理集群。

当前交付第一阶段：账号登录、用户管理、个人邮箱与密码设置、管理员/成员权限、机器登记、集群发现与状态查看、服务启停、集群日志与管理员网页终端、环境登记、常用参数与高级 YAML 编辑、配置草稿和版本差异。

## 启动

```bash
cp .env.example .env
# 编辑 .env，设置自己的 POSTGRES_PASSWORD。
docker compose --env-file .env -f deploy/compose.yaml up -d --build
docker compose --env-file .env -f deploy/compose.yaml exec api \
  python -m dingofs_platform.auth.cli create-admin
```

访问 http://172.30.14.126:58080 ，使用交互创建的账号登录。首次进入按“机器 → 发现集群 → 环境”登记资源。

- [开发、部署与测试](docs/DEVELOPMENT.md)
- [集群日志与网页终端验收](docs/REMOTE_ACCESS_ACCEPTANCE.md)
- [用户管理验收](docs/USER_MANAGEMENT_ACCEPTANCE.md)
- [第一阶段验收](docs/PHASE1_ACCEPTANCE.md)
- [产品设计](docs/superpowers/specs/2026-09-21-dingofs-test-platform-design.md)
- [技术设计](docs/superpowers/specs/2026-09-21-dingofs-test-platform-technical-design.md)
- [实现计划](docs/superpowers/plans/2026-09-21-phase1-foundation.md)

资源采集、集群发现、服务启停和日志/终端功能在用户操作时连接登记机器。测试任务执行尚待后续接入；配置发布仅保存版本。

### 机器首次连接与自动采集

SSH 连接默认自动信任目标主机公钥，不再要求用户核验指纹；硬件采集、集群操作、日志和终端使用相同策略，不使用历史主机指纹或 known_hosts 阻断连接。
新增机器资源后自动在后台采集一次硬件信息，详情页自动更新结果。采集失败仍保留资源并显示原因，可使用“更新机器信息”重试；未配置 SSH 密码时提示补充密码。

集群详情现支持文件系统、配额、回收站、目录统计、平台管理的缓存组与挂载点/客户端日志。升级需要数据库迁移，部署步骤与边界见 [集群资源管理验收](docs/CLUSTER_RESOURCES_ACCEPTANCE.md)。

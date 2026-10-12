# 挂载配置与配置管理

侧栏“配置管理”包含存储配置、缓存组配置、挂载配置三个页签。原有 `#/storage`、`#/cache-profiles` 链接仍可进入对应页签。

挂载参数来自本地 dingo-client main-fe4384a0b 的 `--help`，共 193 项；原始帮助保存在 reference/dingo-client-main-fe4384a0b-help.txt。展示参数类型、原始说明和默认值，支持分类搜索。仅勾选自定义的参数写入模板。平台管理的后台运行、日志目录、配置文件和操作目标不能由模板覆盖；文件系统、挂载目录、子目录、缓存组及 RDMA 在挂载表单配置。

在“挂载文件系统”中选择模板并展开“调整本次挂载参数”。修改只影响本次任务，提交时冻结参数快照并检查模板版本、启用状态。命令通过参数数组传递，实际执行记录中可查看挂载参数。模板可复制、启用、停用、删除，权限与缓存组配置相同。已提交的任务不受后续模板修改影响。

首次部署需迁移数据库：

```bash
docker compose --env-file .env -f deploy/compose.yaml build api web migrate
docker compose --env-file .env -f deploy/compose.yaml run --rm migrate
docker compose --env-file .env -f deploy/compose.yaml up -d --no-deps api web
```

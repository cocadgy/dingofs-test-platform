# 开发与部署

## 本地启动（推荐 Docker Compose）

要求 Docker Engine 与 Compose v2，首次构建需要访问镜像仓库、PyPI 和 npm。

```bash
cd /mnt/disk5/daigy/dingofs-test-platform
cp .env.example .env
# 编辑 .env：POSTGRES_PASSWORD 改为随机字母数字密码。
# 本机 HTTP 调试使用 PLATFORM_COOKIE_SECURE=false。
docker compose --env-file .env -f deploy/compose.yaml up -d --build
docker compose --env-file .env -f deploy/compose.yaml exec api \
  python -m dingofs_platform.auth.cli create-admin
```

按提示输入用户名、密码（至少 12 字符）和确认密码。没有默认账号。创建普通只读账号时使用 `create-member`。

浏览器访问 http://127.0.0.1:58080 。默认仅监听本机。通过 SSH 隧道访问远端部署：

```bash
ssh -L 58080:127.0.0.1:58080 your-user@platform-host
```

登记顺序：机器 → 管理上下文 → 集群 → 测试环境。管理上下文中的路径是所选远端机器上的绝对路径。这里只登记信息，不检查工具版本或连接远端机器。主机名别名和符号链接的物理归一化将在接入 dingo 时完成；同一机器不要以多个别名重复登记。

网页可保存草稿、发布不可变配置版本、对比最近两个版本。HTTP API 支持指定任意两个版本比较。发布不执行部署。集群原生 YAML 仅校验语法，常用参数表单只应用于平台环境配置。

## 配置

| 变量 | 含义 |
| --- | --- |
| POSTGRES_PASSWORD | Compose 数据库密码，使用随机 URL 安全字母数字 |
| PLATFORM_HTTP_PORT | 本地网页端口，默认 58080 |
| PLATFORM_COOKIE_SECURE | HTTPS 部署必须 true；本机 HTTP 显式 false |
| PLATFORM_DATABASE_URL | API 直启时必填，格式 postgresql+psycopg://user:password@host:5432/db |
| PLATFORM_SESSION_HOURS | 会话时长，默认 12 小时 |

`.env` 不加入版本管理。数据库不映射宿主机端口，API 仅供内部 Web 代理访问。团队共享部署时应配置 HTTPS 与受信任的入口；更新 nginx 中转发协议配置以匹配实际 HTTPS 终止位置，不能直接信任客户端的 `X-Forwarded-Proto`。默认 nginx 对登录接口限速。开发用 Vite 不限速，不用于共享生产入口。

凭据目前只登记引用标识，尚未对接凭据存储。不要把密码、密钥、含密码 URL 或秘密写入 YAML、注释、资源名称等字段。服务端拒绝常见凭据字段及明文凭据模式，不能识别伪装为任意业务字符串的秘密。

## 不使用 Docker 的开发方式

Python >=3.12，Node >=22.12，PostgreSQL >=16。

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.lock
pip install --no-deps -e backend
export PLATFORM_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/DB'
export PLATFORM_COOKIE_SECURE=false
alembic -c backend/alembic.ini upgrade head
python -m dingofs_platform.auth.cli create-admin
uvicorn dingofs_platform.app:create_app --factory --host 127.0.0.1 --port 58000
```

另一个终端：

```bash
cd frontend
npm ci
npm run dev -- --port 55173
```

访问 http://127.0.0.1:55173 。Vite 将 `/api` 代理到 58000，并保留原始 Host 以支持来源校验。

## 测试

后端测试会删除指定测试库中的平台表。只使用独立测试库；fixture 要求地址是 localhost/127.0.0.1 且库名以 `_test` 结尾，不会回退使用 PLATFORM_DATABASE_URL。

```bash
export TEST_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:55439/platform_test'
PYTHONPATH=backend/src .venv/bin/pytest backend/tests -q
cd frontend
npm test -- --run
npm run build
npx playwright install chromium
# 启动独立平台实例，使用 CLI 创建 admin 和 member 两个测试账号。
# 设置该隔离实例两个账号的测试密码：
export PLATFORM_E2E_PASSWORD='YOUR-TEST-PASSWORD'
PLATFORM_E2E_URL=http://127.0.0.1:55173 npm run e2e
```

E2E 会真实创建带 e2e 前缀的资源和配置，只能针对专用本地实例运行。浏览器 trace 可能包含测试输入，仅用于临时测试数据，不上传实际凭据。

生成 OpenAPI 类型：

```bash
PYTHONPATH=backend/src python -m dingofs_platform.export_openapi > backend/openapi.json
cd frontend && npm run generate-api
```

迁移检查：`alembic -c backend/alembic.ini check`。迁移在 Compose 的独立 migrate 服务执行成功后，API 才启动。

## 备份、恢复与停止

```bash
# 备份（不包含浏览器缓存；数据库包含会话摘要及配置版本，应妥善保护）
docker compose --env-file .env -f deploy/compose.yaml exec -T db \
  pg_dump -U platform -d platform -Fc > platform-backup.dump

# 恢复到新建的空数据库，先停止 API
# 保留备份，确认目标库无需要保留的数据后执行恢复。
docker compose --env-file .env -f deploy/compose.yaml stop api
docker compose --env-file .env -f deploy/compose.yaml exec -T db \
  pg_restore -U platform -d platform --no-owner < platform-backup.dump
docker compose --env-file .env -f deploy/compose.yaml up -d

# 停止并保留数据库卷
docker compose --env-file .env -f deploy/compose.yaml down
```

不要对需要保留的平台数据运行 `down -v`。更换 POSTGRES_PASSWORD 不会自动修改已存在数据库卷中的账号密码。

## 当前范围

已实现登录、管理员/普通成员权限、资产关系、归档约束、YAML 草稿、发布版本、差异和数据库审计。审计只记录操作者、操作、资源及字段名，不记录原始秘密或配置全文；暂不提供审计查询页面。

尚未实现：真实集群探测、dingo 导入与部署/更新/停止/重启/清理、测试目录勾选、任务调度、Worker、运行日志与报告、凭据存储对接。不要将“已登记”或“配置已发布”理解为已连接/部署/执行。

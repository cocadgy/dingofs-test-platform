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

按提示输入用户名、密码（至少 6 字符）和确认密码。没有默认账号。创建普通成员账号时使用 `create-member`。

浏览器访问 http://127.0.0.1:58080 。默认仅监听本机。通过 SSH 隧道访问远端部署：

```bash
ssh -L 58080:127.0.0.1:58080 your-user@platform-host
```

登记顺序：机器 → 发现集群 → 测试环境。在集群管理点击“发现集群”，选择机器并填写 Linux 执行用户，查询该用户的 `dingo cluster ls` 后勾选导入。使用机器资源中的 SSH 用户连接，必要时免密 sudo 切换；只有确定需要认证时才请求指定账号的临时密码，不保存切换密码。目标用户的登录环境必须能找到 `dingo`，无需填写工具绝对路径。每次状态查询独立设置 `dingo_cluster`，不修改默认集群。

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

## 用户管理与个人设置（2026-09-23）

管理员侧边栏新增“用户管理”，支持：

- 添加用户：用户名、有效邮箱、初始密码必填，可选择普通成员或管理员。初始密码至少 6 位。
- 启用、禁用账号；禁用立即撤销该账号已有登录会话，再启用后需重新登录。
- 删除账号及其登录会话；历史配置版本和审计记录保留。
- 将密码重置为固定值 `123456`，同时撤销该账号所有登录会话。
- 禁用、删除最后一个启用的管理员会被拒绝；用户信息版本冲突时需刷新列表。

所有用户（包括管理员）均可进入“个人设置”：修改邮箱或密码必须提交当前密码验证，每次修改都重新验证。新密码至少 6 位；修改密码后包括当前浏览器在内的全部会话失效。修改邮箱不改变密码，也不退出登录。邮箱不要求全局唯一，本阶段只检查地址格式，不发送邮箱验证邮件。

升级方式：

```bash
docker compose --env-file .env -f deploy/compose.yaml up -d --build
```

Compose 会先执行增量数据库迁移，再启动 API。不要删除数据库卷。既有账号没有邮箱时，迁移保留原账号、密码和历史记录，不填入虚构地址；登录后进入个人设置提示补填。新建账号必须提供邮箱，CLI 创建账号也新增 `Email (required)` 提示。

手工验收建议：管理员添加测试用户 → 以测试用户登录 → 用错误密码修改邮箱，确认拒绝 → 用正确密码修改邮箱 → 修改密码并重新登录 → 管理员禁用/启用 → 重置为 `123456` 并验证登录 → 删除测试用户并确认无法再登录。

## 机器 SSH 密码和硬件采集

机器资源支持保存 SSH 密码，资源创建者或管理员点击“更新机器信息”采集 Linux CPU、内存、磁盘、挂载点、网卡和 RDMA 信息。其他普通用户只能查看已采集信息。密码字段留空保留原值，勾选“清除已保存的 SSH 密码”才会删除。密码与网络连接详情不会进入审计；原凭据引用字段继续保留，本阶段采集使用机器中保存的密码。

升级前先构建新 API 镜像，生成一次持久加密密钥：

```bash
docker compose --env-file .env -f deploy/compose.yaml build api
docker compose --env-file .env -f deploy/compose.yaml run --rm --no-deps api \
  python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

将输出保存到 `.env` 的 `PLATFORM_CREDENTIAL_ENCRYPTION_KEY=` 后面，并执行 `chmod 600 .env`。应和数据库一起备份该密钥；不要每次重启重新生成，否则已保存密码将无法解密。缺少该配置时普通资源功能仍然可用，但不能保存或使用 SSH 密码。新密码可重新录入以替换旧密文。

首次连接机器不再要求手工准备 `known_hosts`：

1. 在机器详情点击“更新机器信息”。平台完成 SSH 握手后展示主机地址、端口、密钥类型及 SHA256 指纹，此时尚未发送 SSH 登录密码。
2. 机器创建者或管理员通过目标机器的可信控制台等渠道核对指纹。例如在目标机器执行 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`，具体文件应与页面的密钥类型对应。
3. 勾选“我已通过可信渠道核对该机器的 SSH 指纹”，点击“信任并继续”。平台保存公钥并继续采集。
4. 信任记录持久保存在数据库，重启后仍有效；每次连接都会检查密钥。
5. 机器密钥发生变化时停止连接，页面同时展示新旧指纹，机器创建者或管理员重新核对后点击“信任新密钥并继续”。不会自动覆盖旧信任。

确认有效期为 10 分钟，绑定机器配置修订及主机地址/端口。地址、端口或配置变化后，需要重新获取指纹，不接受过期或重复确认；普通用户不能确认信任。该确认不需要将 SSH 密码放入高级 YAML。

已有 `deploy/ssh/known_hosts` 仍可作为初始信任来源，但不再必需；数据库中确认过的公钥优先使用，避免旧文件干扰已核实的换钥。手工维护该文件的用户仍应先核验指纹。文件不存在会进入网页确认流程；存在但不可读或格式损坏会提示文件错误。

最后更新服务（自动执行数据库迁移）：

```bash
docker compose --env-file .env -f deploy/compose.yaml up -d --build
```

本地开发可用 `PLATFORM_SSH_KNOWN_HOSTS=/绝对路径/known_hosts` 指定信任文件。远端使用 lscpu、lsblk、df、ip 以及 /proc、/sys，只读、不需要 sudo、不安装 agent；缺少工具或信息不可读时展示部分结果。每次采集总计最多约 30 秒，加上进程清理和短数据库事务；包括 DNS/认证/命令阶段，不会永久占用请求线程。

磁盘容量摘要仅累计 `disk` 设备，不累计分区/LVM。挂载点独立展示，标记共享同一文件系统的容量，不把它们加成磁盘总量。虚拟机的物理核数、无法读取的网卡速率展示“未知”。本次部分结果与上次完整成功快照分别展示；失败保留旧成功快照。并发刷新同一机器会被拒绝，采集中断后可重试；更新机器连接配置后，旧请求的采集结果不会覆盖新配置。

实现参考：[Paramiko SSHClient](https://docs.paramiko.org/en/stable/api/client.html)、[cryptography Fernet](https://cryptography.io/en/latest/fernet/)。

## 机器资源概览与详情

机器资源默认展示全宽表格，列顺序为：资源名、IP、CPU型号、物理CPU核数、逻辑CPU核数、总内存、总磁盘、网卡速率（最大）、RDMA设备、信息更新时间。

每个表头下方均可搜索，按显示文本做包含匹配，不区分大小写；多个条件同时生效。点击列标题切换升序/降序，核数、容量、速率和时间按实际数值排序，未知值在两种方向均置后。表格按 20 台分页，搜索和排序覆盖全部机器而非当前页。后台分页返回精简概览字段，前端完整加载后执行全局筛选；记录多时会显示加载状态，任一页加载失败不会把部分数据当成完整结果。

IP 优先使用登记的 IP；登记的是主机名时，使用采集到的非回环、非链路本地 IP，未采集时显示登记地址。总磁盘仅累计物理 disk 设备，不重复累计分区/LVM；网卡速率使用有效速率的最大值，单位 Mbps；RDMA 按设备名去重。未采集字段显示“未知”。

信息更新时间对应本行展示的硬件快照，失败的采集不会刷新旧数据的时间。已有完整快照时继续展示该快照；仅有部分结果时展示部分信息，并在资源名下标注。已归档机器继续标注并保留在概览中。

点击机器行任意一列进入独立详情页，URL 为 `#/machines/<机器ID>`，支持直接打开和刷新。返回概览保留本次页面中的搜索条件、排序和页码；刷新整个网页后使用默认筛选。详情中继续支持编辑、归档、硬件采集及 SSH 指纹确认。侧边栏“机器资源”也可返回概览。

## 集群发现与状态

概览每行一个集群，支持逐列搜索、排序和分页。跨机器或跨用户的同名集群分别展示。点击行打开服务状态详情，查看 MDS/TiKV 地址、角色统计、实例、端口、目录和原始输出。节点仅在主机地址能唯一匹配时链接到机器资源；未匹配的节点仍展示。

状态描述进程运行情况，不代表业务健康。刷新失败保留最近成功快照和原采集时间。等待认证时提供需要验证的账号；密码不会用于其他用户的操作。进入详情自动刷新一次；批量刷新逐个处理，需认证的集群进入详情继续。

旧集群的 ID、环境和配置历史保留。首次使用新版时重新发现并明确确认旧集群的管理入口，不根据旧路径猜测默认配置；自定义配置目录和同名入口有歧义时不会自动合并。新集群通过发现导入，手工 POST 集群创建接口已关闭。

`.env.example` 提供发现/状态超时、输出上限、每机器并发数、认证有效期和发现有效期；Compose 已传入 API。默认 60/120 秒、2 MiB、每机器 2 个并发、认证 300 秒、发现结果 900 秒。取消与超时会关闭本次 SSH 通道和本地执行进程；没有执行远端部署、启停或清理。


### 机器与集群的创建者权限

所有登录用户可查看所有机器和集群。普通用户可登记机器，并在自己登记的机器上发现和导入集群；导入者成为集群创建者。创建者可编辑、归档、采集机器硬件、确认 SSH 指纹以及刷新自己的集群状态和 topology.yaml。admin 可管理所有资源。其他普通用户仅查看已采集状态和 topology.yaml，不触发远程操作。

创建者由后端写入且不可通过请求更改。重复导入不会改变已有集群归属。旧资源没有可确认的创建者，升级后仅 admin 可管理；删除用户也不会将其资源转交其他普通用户。测试环境和用户管理权限保持 admin 专属。

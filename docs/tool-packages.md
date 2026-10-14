# 网页一键部署测试工具

入口：**配置管理 → 工具包管理**，或 **机器资源 → 机器详情 → 测试工具**。

## 首次配置（网页完成）

管理员在“平台工具来源”选择平台所在机器，使用已经登记的 SSH 凭据。目录和 dtt 镜像已预填，保存即可：

- 平台工具目录：`/mnt/disk5/daigy/dingofs-testsuite-tool`
- dtt 镜像：`harbor.zetyun.cn/dingofs/dingofs-testsuite-tools:latest`

镜像地址取自 dtt 项目的 `build.sh`。该脚本构建后将镜像推送到这个 Harbor 地址。
来源目录中的 dtt 文件为 `dingofs-testsuite-tool`、`dtt-ai-analyze`、`analysis.schema.json`；其他工具分别为 `dingo`、`dingo-client`、`dingo-cache`。

无需登录机器执行打包命令，无需手工填写工具包版本目录。工具来源只允许管理员修改；所有人可查看，普通用户只能部署到自己创建的机器。

## 部署

1. 选择目标机器。
2. 选择 dtt、dingo、dingo-client 或 dingo-cache。
3. 点击“一键部署 / 更新”，查看任务进度、实际命令和日志。

对于 dtt：

1. 平台来源机器准备配置的镜像，按 image ID 导出。
2. 优先通过原生 scp 直传到目标机器。
3. SCP 路径失败后，目标机器执行 `docker pull`（或 Podman），超时600秒。SCP 成功时直接加载镜像；镜像数据不经过 API 中转。来源机器需要安装 scp（openssh-clients）并能访问目标 SSH 端口。使用已登记的目标 SSH 凭据自动认证，日志展示传输命令、速度与进度，安装前仍校验 SHA256。
4. 平台同时复制 dtt 启动脚本和配套文件。
5. 校验文件 SHA-256、检查 fio/elbencho 版本，成功后激活独立安装目录。

若平台不能访问仓库，默认切换目标机器拉取。管理员可在网页启用“允许使用平台已有镜像”；启用后可以使用平台镜像缓存，任务结果会明确显示“使用已有缓存，未确认仓库最新版本”。不会将旧缓存伪称为最新镜像。

其他三个工具直接复制来源目录中的对应文件，并验证 CPU 架构和可执行性。部署不会启动 DingoFS 服务。

## 环境与结果

目标机器需要 Python 3、GNU timeout。dtt 还需要已经启动且 SSH 用户有权限使用的 Docker/Podman；平台不会自动修改系统容器服务。缺少依赖时页面显示具体错误。

工具安装在该 SSH 用户的 `~/.local/share/dingofs-platform/tools/<tool>/current/`，不覆盖现有系统工具。dtt 另外在 `~/.local/bin/` 创建 `dtt` 和 `dingofs-testsuite-tool` 命令入口，更新用户 Bash/Zsh 的 PATH 配置；已有同名入口和修改前的 shell 配置先备份，路径记录在任务日志中。重复部署不会重复添加配置。新终端可直接使用 `dtt --help`；已有 Bash 终端执行 `source ~/.bashrc`，Zsh 执行 `source ~/.zshrc` 后生效。镜像使用固定 ID。任务中显示采用的获取方式以及实际安装路径。

关闭网页不影响后台任务。平台进程中断后，不会自动重试安装；超时任务标记中断，重新检查工具状态即可。成功转传后清理平台导出临时目录；目标机加载后删除镜像暂存副本。失败遗留路径在日志中可查。

原有离线工具包接口保留兼容历史记录，日常部署不再需要手工打包或登记。

镜像获取顺序为平台 SCP 直传优先，直传路径失败后才在目标机器执行 Docker/Podman pull，拉取超时为600秒。平台准备镜像时的 pull 也使用600秒超时。回退安装不使用未传完的镜像；启动脚本等小文件在 SCP 不可用时通过 SFTP 中转。

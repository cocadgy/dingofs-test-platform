# 平台对抗性审查（2026-10-12）

## 基线与边界

审查 /mnt/disk5/daigy/dingofs-test-platform 当前工作树，HEAD dec1da7，包含已有未提交实现。未修改产品代码，未部署、提交或推送，未访问真实 SSH、发送真实进程信号或操作真实集群。

这是风险驱动审查，覆盖资源操作、远端执行、权限撤销、配置模板、表单状态与模块边界；不是对全部功能和生产行为的完整证明。尤其数据库并发、跨机器网络故障、真实 CLI 多版本兼容、后台任务进程重启恢复未完成实证。

## 第一性原理

平台必须保证：
1. 用户看到并确认的目标与实际命令一致。
2. 执行权限在实际修改时仍然有效。
3. 结果区分成功、失败和未知，不能把未知等同于未执行。
4. 编辑、重试、列表刷新不丢失用户意图，不扩大操作范围。
5. 配置复用降低输入负担，不能改变平台托管的身份和生命周期约束。

## 问题

### P2：挂载缓存组下拉框与提交参数不一致（组件实验已复现）

frontend/src/features/resources/ResourceFields.tsx:65；ResourceSectionForm.tsx:640、915；backend/src/dingofs_platform/resources/remote_helper.py:558。

先选择 g，再刷新列表且返回不包含 g。浏览器 select 显示空选项“不指定缓存组”，但 values.cache_group 仍为 g，也没有触发 onChange。提交侧没有校验缓存组仍在选项中，最终命令仍带 --cache_group=g。确认框仍可显示 g，因此不将此描述成完全不可见的误操作。

最小修复：选项失效时明确展示“选择已失效”，阻止提交并要求重选；避免静默回退为空且保留旧参数。增加刷新期间/刷新失败测试。

### P2：YAML 草稿保存吞掉并发编辑（组件实验已复现）

frontend/src/features/configuration/ConfigEditor.tsx:73–76、210、235；入口由 features/inventory/InventoryPage.tsx 使用。

保存 A 后，在响应返回前输入 B。响应无条件 setText(A)、setFields({})，B 被覆盖，脏状态消失，发布按钮恢复可用。

最小修复：保存期间禁用编辑控件及编辑模式切换。若产品要求持续编辑，则使用提交快照，只更新保存基线，不覆盖当前编辑区。无需引入全局状态框架。

### P2：排队中的机器修改使用旧权限快照（静态证据，待并发复现）

backend/src/dingofs_platform/inventory/routes.py:160–165；auth/dependencies.py 的 db.expunge(user)；auth/users.py 的 actor_in_transaction。

PATCH 通过认证后等待 inventory 锁，管理员可经 account 锁禁用用户或撤销会话；恢复执行时 PATCH 仍使用旧 detached User 检查权限，不重查会话。因此存在撤权完成后旧请求仍提交机器修改的窗口。创建接口亦使用依赖返回的旧对象，应一起排查。

建议复用事务内 actor_in_transaction，统一 account→inventory 锁顺序。回归需隔离数据库、受控锁屏障、真实请求并发；不能仅用 sleep 模拟顺序。本次未执行数据库并发实验，不声称线上已复现。

## 核心机制消融

脚本：docs/reviews/2026-10-12-ablation.py。当前源码以只读方式挂载进 --network none 容器；全部数据、PID、信号发送器均为替身。每组只替换一个校验函数，保持其他输入一致。

| 威胁输入 | 原机制 | 移除机制 | 结论 |
|---|---|---|---|
| 同 PID 的 start_ticks 改变 | 0 次模拟信号 | 1 次模拟信号 | 保留进程身份核验 |
| 模板 revision=2，请求 revision=1 | 拒绝 | 接受 | 保留版本校验 |
| 普通用户操作他人集群 | valid=False | valid=True | 保留执行阶段所有权校验 |

实验只证明指定输入下防护的因果作用；不是 PID fallback 原子性证明，也不是全权限矩阵证明。旧内核 fallback 的检查到 kill 仍有窄竞态，源码已标注；不应为简化删除 pidfd 路径。

前端实验：/tmp/platform-fs-select-20261008/src/audit-ui/audit.test.tsx，2 passed。mock fetch，无远端操作：
- options ['g']→[]：DOM=''，参数='g'，onChange=0。
- 保存 pending 时输入 B，响应 A：编辑区=A，发布按钮可用。

既有定向测试 71 passed：test_process_stop_compatibility.py、test_cache_profile_parameters.py、test_resource_commands.py、test_resource_validation_feedback.py。测试通过没有排除上述缺陷，说明场景覆盖仍需补充。

## 奥卡姆剃刀与模块边界

1. cache_profiles/catalog.py 与 mount_profiles/catalog.py 的差异几乎仅是错误前缀，挂载校验还遗留 cache id/member_defaults 等无关逻辑。提取小型公共参数类型校验器，保留各工具 catalog 和业务规则；不要打造通用插件平台。挂载前端类型也应从 CacheProfile 改为中性共享类型。
2. resources/remote_helper.py 1315 行，混合命令追踪、进程身份、端口、成员操作、挂载与文件日志；ResourceSectionForm.tsx 1026 行，混合多个资源类型。按进程/命令执行基础层与领域操作拆分，并保留清晰的远端脚本打包入口；前端拆成文件系统、缓存、挂载表单，共享提交与状态处理。行数本身不是缺陷，职责混合才是拆分依据。
3. 不建议此时增加微服务、消息队列、全局状态库。先修正已确认问题、补充失败/并发测试，再用等价行为测试逐步抽取重复代码。

## 后续优先级

先补权限竞态的并发复现，再修复三项问题并保存针对性回归。之后重构共享参数校验与资源表单。下一轮验证请求幂等、任务中断恢复、网络超时后的未知状态；这些核心机制本轮没有做消融，不能宣称已全部验证。

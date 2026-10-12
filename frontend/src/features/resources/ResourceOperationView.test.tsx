import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ResourceOperationView } from "./ResourceOperationView";
import { api } from "../../api/client";
import type { ResourceOperation } from "./types";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});
test("filesystem queries show concise columns and mount full fields only when expanded", async () => {
  render(
    <ResourceOperationView
      label="查看文件系统"
      canManage={false}
      onChange={() => {}}
      operation={{
        id: "op1",
        action: "fs.list",
        state: "succeeded",
        result: {
          steps: [
            {
              returncode: 0,
              data: {
                error: { code: 0, description: "success" },
                result: {
                  info: { time: { total_time_us: 127322 } },
                  fs_infos: [
                    {
                      fs_id: 42,
                      fs_name: "test-fs",
                      status: "normal",
                      owner: "alice",
                      capacity: 1073741824,
                      block_size: 4096,
                      extra: { nested: "preserved" },
                    },
                  ],
                },
              },
            },
          ],
        },
      }}
    />,
  );
  const table = screen.getByRole("table", { name: "文件系统列表" });
  expect(
    within(table).getByRole("columnheader", { name: "文件系统名称" }),
  ).toBeInTheDocument();
  expect(
    within(table).getByRole("cell", { name: /^test-fs$/ }),
  ).toBeInTheDocument();
  expect(within(table).getByText("1 GiB")).toBeInTheDocument();
  expect(screen.getByText("完整字段").closest("details")).not.toHaveAttribute(
    "open",
  );
  expect(screen.getByText("响应详情").closest("details")).not.toHaveAttribute(
    "open",
  );
  expect(screen.queryByText("preserved")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("完整字段"));
  expect(await screen.findByText("preserved")).toBeVisible();
  fireEvent.click(screen.getByText("完整字段"));
  await waitFor(() =>
    expect(screen.queryByText("preserved")).not.toBeInTheDocument(),
  );
});
test("failed response diagnostics are visible and empty filesystem results are clear", () => {
  render(
    <ResourceOperationView
      label="查看文件系统"
      canManage={false}
      onChange={() => {}}
      operation={{
        id: "op2",
        action: "fs.list",
        state: "failed",
        result: {
          steps: [
            {
              returncode: 1,
              data: {
                error: { code: 5, description: "query failed" },
                result: { fs_infos: [] },
              },
            },
          ],
        },
      }}
    />,
  );
  expect(screen.getByText("暂无文件系统")).toBeInTheDocument();
  expect(screen.getByText("响应详情").closest("details")).toHaveAttribute(
    "open",
  );
  expect(screen.getByText("query failed")).toBeInTheDocument();
});

test("single filesystem response displays details without expanding diagnostics", () => {
  render(
    <ResourceOperationView
      label="文件系统详情"
      canManage={false}
      onChange={() => {}}
      operation={{
        id: "query",
        action: "fs.get",
        state: "succeeded",
        result: {
          steps: [
            {
              returncode: 0,
              data: {
                error: { code: 0 },
                result: {
                  fs_info: {
                    fs_id: 11860,
                    fs_name: "test2",
                    status: 1,
                    block_size: 4194304,
                    chunk_size: 67108864,
                    uuid: "0e26a4e8-d52a-4ef6-87a9-f8fe212050f9",
                    partition_policy: {
                      Partition: { ParentHash: { expect_mds_num: 1 } },
                    },
                    extra: {
                      s3_info: {
                        endpoint: "http://172.30.14.126:9198",
                        bucketname: "dingofs",
                      },
                    },
                  },
                },
              },
            },
          ],
        },
      }}
    />,
  );
  const fields = within(screen.getByLabelText("文件系统详情字段"));
  expect(fields.getByText("test2")).toBeVisible();
  expect(fields.getByText("11860")).toBeVisible();
  expect(fields.getByText("NORMAL")).toBeVisible();
  expect(fields.getByText("4 MiB (4194304 B)")).toBeVisible();
  expect(fields.getByText("64 MiB (67108864 B)")).toBeVisible();
  expect(fields.getByText("http://172.30.14.126:9198/dingofs")).toBeVisible();
});

test.each([
  ["camelCase empty", { mountPoints: [] }, "0"],
  ["snake_case empty", { mount_points: [] }, "0"],
  ["camelCase populated", { mountPoints: [{ host: "a" }, { host: "b" }] }, "2"],
  ["snake_case populated", { mount_points: [{ host: "a" }] }, "1"],
  ["JSON omits empty list", {}, "0"],
  ["explicit count", { mount_num: 3 }, "3"],
  ["malformed list", { mountPoints: "invalid" }, "未返回"],
])("filesystem mount count: %s", (_name, mountFields, expected) => {
  render(
    <ResourceOperationView
      label="文件系统详情"
      canManage={false}
      onChange={() => {}}
      operation={{
        id: "mount-count",
        action: "fs.get",
        state: "succeeded",
        result: {
          steps: [
            {
              data: {
                result: {
                  fs_info: { fs_id: 11860, fs_name: "test2", ...mountFields },
                },
              },
            },
          ],
        },
      }}
    />,
  );
  const fields = within(screen.getByLabelText("文件系统详情字段"));
  const row = fields.getByText("挂载数").parentElement!;
  expect(within(row).getByText(String(expected))).toBeVisible();
});

test.each([["active", "old-DELETED-123"], ["DELETED-only"]])(
  "list hides DELETED names and counts visible rows: %s",
  (...names) => {
    const operation = {
      id: "filtered",
      action: "fs.list",
      state: "succeeded",
      result: {
        steps: [
          {
            data: {
              result: { fs_infos: names.map((fs_name) => ({ fs_name })) },
            },
          },
        ],
      },
    };
    render(
      <ResourceOperationView
        label="列表"
        canManage={false}
        onChange={() => {}}
        operation={operation}
      />,
    );
    for (const name of names.filter((name) => name.includes("DELETED")))
      expect(screen.queryByText(name)).toBeNull();
    if (names.includes("active"))
      expect(screen.getByText("（1 个）")).toBeInTheDocument();
    else expect(screen.getByText("暂无文件系统")).toBeInTheDocument();
  },
);

test("hidden operation details keep polling and reveal the updated result when shown", async () => {
  vi.useFakeTimers();
  const pending: ResourceOperation = {
    id: "hidden-poll",
    action: "fs.list",
    state: "pending",
  };
  const done: ResourceOperation = {
    ...pending,
    state: "succeeded",
    result: { steps: [{ stdout: "finished while hidden" }] },
  };
  vi.mocked(api).mockResolvedValue(done);
  const onChange = vi.fn();
  const props = {
    operation: pending,
    label: "列表",
    canManage: true,
    onChange,
  };
  const { container, rerender } = render(
    <ResourceOperationView {...props} renderDetails={false} />,
  );
  expect(container).toBeEmptyDOMElement();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(400);
  });
  expect(api).toHaveBeenCalledWith("/resource-operations/hidden-poll");
  expect(onChange).toHaveBeenCalledWith(done);
  expect(container).toBeEmptyDOMElement();
  rerender(<ResourceOperationView {...props} operation={done} renderDetails />);
  expect(screen.getByText("finished while hidden")).toBeVisible();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000);
  });
  expect(api).toHaveBeenCalledTimes(1);
});

test("collapsed payload and structured raw output are mounted on demand", async () => {
  render(
    <ResourceOperationView
      label="查询"
      canManage={false}
      onChange={() => {}}
      operation={{
        id: "lazy-output",
        action: "quota.fs.get",
        state: "succeeded",
        payload: { fs_name: "payload-filesystem" },
        result: {
          steps: [{ data: { quota: 10 }, stdout: "raw-query-response" }],
        },
      }}
    />,
  );
  expect(screen.queryByText("payload-filesystem")).not.toBeInTheDocument();
  expect(screen.queryByText("raw-query-response")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("操作参数"));
  expect(await screen.findByText("payload-filesystem")).toBeVisible();
  fireEvent.click(screen.getByText("原始输出"));
  expect(await screen.findByText("raw-query-response")).toBeVisible();
});

test("hidden credential views still clear passwords when the challenge changes", () => {
  const props = { label: "查询", canManage: true, onChange: () => {} };
  const challenge: ResourceOperation = {
    id: "auth-hidden",
    action: "fs.list",
    state: "needs_password",
    challenge: "first",
  };
  const { container, rerender } = render(
    <ResourceOperationView {...props} operation={challenge} />,
  );
  fireEvent.change(screen.getByLabelText("认证密码"), {
    target: { value: "temporary-secret" },
  });
  rerender(
    <ResourceOperationView
      {...props}
      operation={challenge}
      renderDetails={false}
    />,
  );
  expect(container).toBeEmptyDOMElement();
  rerender(
    <ResourceOperationView
      {...props}
      operation={{ ...challenge, challenge: "second" }}
      renderDetails={false}
    />,
  );
  rerender(
    <ResourceOperationView
      {...props}
      operation={{ ...challenge, challenge: "second" }}
      renderDetails
    />,
  );
  expect(screen.getByLabelText("认证密码")).toHaveValue("");
});

test("single filesystem full fields and successful diagnostics expand independently", async () => {
  render(
    <ResourceOperationView
      label="详情"
      canManage={false}
      onChange={() => {}}
      operation={{
        id: "lazy-fs-get",
        action: "fs.get",
        state: "succeeded",
        result: {
          steps: [
            {
              data: {
                result: {
                  fs_info: {
                    fs_name: "displayed-name",
                    extra_detail: "nested-only",
                  },
                },
                diagnostic: "response-only",
              },
            },
          ],
        },
      }}
    />,
  );
  expect(screen.queryByText("nested-only")).not.toBeInTheDocument();
  expect(screen.queryByText("response-only")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("完整字段"));
  expect(await screen.findByText("nested-only")).toBeVisible();
  expect(screen.queryByText("response-only")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("响应详情"));
  expect(await screen.findByText("response-only")).toBeVisible();
});

test("mount logs remain visible by default even with structured data", () => {
  render(
    <ResourceOperationView
      label="日志"
      canManage={false}
      onChange={() => {}}
      operation={{
        id: "visible-logs",
        action: "mount.logs",
        state: "succeeded",
        result: {
          steps: [{ data: { lines: 1 }, stdout: "mount-log-content" }],
        },
      }}
    />,
  );
  expect(screen.getByText("mount-log-content")).toBeVisible();
});

test("cache batch identifies successful, failed and unreturned members", () => {
  render(
    <ResourceOperationView
      label="批量删除"
      canManage={false}
      onChange={() => {}}
      operation={{
        id: "batch",
        action: "cache.delete_batch",
        state: "failed",
        payload: { member_ids: ["member-a", "member-b", "member-c"] },
        result: {
          steps: [
            { member_id: "member-a", failed: false, returncode: 0 },
            { member_id: "member-b", failed: true, returncode: 1 },
          ],
        },
      }}
    />,
  );
  expect(screen.getByText(/member-a · 成功/)).toBeInTheDocument();
  expect(screen.getByText(/member-b · 失败/)).toBeInTheDocument();
  expect(screen.getByText(/member-c：未返回结果/)).toBeInTheDocument();
});

test("failed startup presents process log text and remote path directly", () => {
  render(
    <ResourceOperationView
      label="创建缓存组"
      canManage={false}
      onChange={() => {}}
      operation={{
        id: "failed-launch",
        action: "cache.create",
        state: "failed",
        result: {
          steps: [
            {
              returncode: 1,
              data: {
                state: "failed",
                message: "launcher failed",
                diagnostics: {
                  log_dir: "/tmp/cache/logs",
                  files: [
                    {
                      filename: "cache.fatal.log",
                      text: "io_uring: Operation not permitted",
                      truncated: true,
                    },
                  ],
                },
              },
            },
          ],
        },
      }}
    />,
  );
  expect(screen.getByRole("heading", { name: "进程日志" })).toBeVisible();
  expect(screen.getByText("/tmp/cache/logs")).toBeVisible();
  expect(screen.getByText("io_uring: Operation not permitted")).toBeVisible();
});

test("actual commands are visible beside failed process logs", () => {
  render(
    <ResourceOperationView
      label="创建缓存组"
      canManage={false}
      onChange={() => {}}
      operation={{
        id: "trace",
        action: "cache.create",
        state: "failed",
        result: {
          steps: [
            {
              returncode: 1,
              data: {
                executed_commands: [
                  {
                    command: "dingo cache start --listen_port=21009",
                    status: "started",
                    executable: "/home/user/bin/dingo",
                  },
                ],
                diagnostics: { log_dir: "/tmp/logs", files: [] },
              },
            },
          ],
        },
      }}
    />,
  );
  expect(screen.getByRole("heading", { name: "实际执行命令" })).toBeVisible();
  expect(
    screen.getByText("dingo cache start --listen_port=21009"),
  ).toBeVisible();
});

test("stop shows the equivalent signal command and actual system call", () => {
  render(<ResourceOperationView label="停止成员" canManage={false} onChange={() => {}}
    operation={{id:"signal", action:"cache.stop", state:"succeeded", result:{steps:[{returncode:0,data:{process_stopped:true,executed_commands:[{command:"kill -TERM -- 123",method:"pidfd_send_signal",equivalent:true,status:"started",count:1}]}}]}}} />);
  expect(screen.getByText("kill -TERM -- 123")).toBeInTheDocument();
  expect(screen.getByText(/实际通过 pidfd_send_signal/)).toBeInTheDocument();
});


test("client logs use sortable file list and open a selected file", () => {
  const onOpenLog = vi.fn();
  const operation: ResourceOperation = {
    id: "client-files", action: "mount.logs", state: "succeeded",
    payload: { resource_id: "mount-1" },
    result: { steps: [{ data: { files: [
      { name: "client.ERROR", size: 20, mtime: 10 },
      { name: "client.INFO", size: 10, mtime: 20 },
    ] } }] },
  };
  render(<ResourceOperationView label="客户端日志" canManage onChange={() => {}} operation={operation} onOpenLog={onOpenLog} />);
  const table = screen.getByRole("table", { name: "日志文件列表" });
  expect(within(table).getByRole("columnheader", { name: /修改时间/ })).toBeInTheDocument();
  fireEvent.doubleClick(within(table).getByText("client.INFO"));
  expect(onOpenLog).toHaveBeenCalledWith(operation, "client.INFO");
});

import { useCallback, useEffect, useRef, useState } from "react";
import { InventoryPage } from "./InventoryPage";
import { MachineOverview, initialTableState } from "./MachineOverview";
function routeFromHash() {
  const match = window.location.hash.match(/^#\/machines\/([^/]+)$/);
  try {
    return match ? decodeURIComponent(match[1]) : "overview";
  } catch {
    return "overview";
  }
}
function hashFor(route: string) {
  return route === "overview"
    ? "#/machines"
    : `#/machines/${encodeURIComponent(route)}`;
}
export function MachinePage({
  admin,
  userId,
  onDirty,
}: {
  admin: boolean;
  userId?: string;
  onDirty: (value: boolean) => void;
}) {
  const [route, setRoute] = useState(routeFromHash);
  const routeRef = useRef(route);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const [tableState, setTableState] = useState(initialTableState);
  const dirty = useRef(false);
  const changed = useCallback(
    (value: boolean) => {
      dirty.current = value;
      onDirty(value);
    },
    [onDirty],
  );
  useEffect(() => {
    function sync() {
      const next = routeFromHash();
      if (next === routeRef.current) return;
      if (dirty.current && !window.confirm("有未保存修改，确定离开？")) {
        window.history.replaceState(null, "", hashFor(routeRef.current));
        return;
      }
      changed(false);
      routeRef.current = next;
      setRoute(next);
    }
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, [changed]);
  function navigate(next: string) {
    window.location.hash = hashFor(next);
  }
  function saved(id: string) {
    if (!mounted.current || routeRef.current !== "new") return;
    changed(false);
    // A newly registered machine must not be hidden by previous hardware filters.
    setTableState(initialTableState);
    routeRef.current = id;
    window.history.replaceState(null, "", hashFor(id));
    setRoute(id);
  }
  if (route !== "overview") {
    return (
      <InventoryPage
        key={route}
        kind="machines"
        admin={admin}
        userId={userId}
        onDirty={changed}
        detailOnly
        initialMachineId={route === "new" ? undefined : route}
        createMachine={route === "new"}
        onBack={() => navigate("overview")}
        onMachineSaved={saved}
      />
    );
  }
  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">PLATFORM / MACHINES</p>
          <h1>机器资源</h1>
          <p className="muted">
            逐列搜索并排序，点击机器行查看详情。多个搜索条件同时生效。
          </p>
        </div>
        {
          <button className="primary" onClick={() => navigate("new")}>
            登记机器资源
          </button>
        }
      </header>
      <MachineOverview
        state={tableState}
        onStateChange={setTableState}
        onOpen={navigate}
      />
    </>
  );
}

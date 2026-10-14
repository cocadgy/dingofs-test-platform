import type { Parameters, ResourceMachine } from "./types";

export function rdmaPairs(machine?: ResourceMachine) {
  return (machine?.rdma || []).filter(pair =>
    !!pair.device && Number.isInteger(pair.port) && pair.port >= 1 && pair.port <= 255,
  );
}

export function firstRdmaPair(machine?: ResourceMachine) {
  const pair = rdmaPairs(machine)[0];
  return { rdma_device: pair?.device || "", rdma_port: pair?.port || 1 };
}

export function cacheRdmaReady(members: Parameters[], machines: ResourceMachine[]) {
  return members.every(member => {
    if (!member.use_rdma) return true;
    const machine = machines.find(row => row.id === member.machine_id);
    return rdmaPairs(machine).some(pair =>
      pair.device === member.rdma_device && pair.port === Number(member.rdma_port),
    );
  });
}

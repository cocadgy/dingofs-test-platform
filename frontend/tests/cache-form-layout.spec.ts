import { test, expect } from "@playwright/test";
import { createServer } from "vite";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

test("cache controls align despite weight help text and missing RDMA devices", async ({ page }) => {
  const server = await createServer({ server: { middlewareMode: true }, appType: "custom" });
  try {
    const { CacheMachineCard } = await server.ssrLoadModule("/src/features/getting-started/CacheMachineCard.tsx");
    const machine = { id:"m", name:"node", address:"10.0.0.1", ssh_user:"test", can_manage:true, rdma:[] };
    const html = renderToStaticMarkup(createElement(CacheMachineCard, {
      machine, row: { machineId:"m", user:"test", count:1, directory:"/mnt/disk1/remote-cache", capacity:10240,
        capacityUnit:"GiB", weight:100, listenIp:"10.0.0.1", portMode:"auto", port:21000,
        binaryDirectory:"", rdma:true, rdmaDevice:"", rdmaPort:1 },
      pathMode:false, profiles:[], otherMachines:[], catalog:{source_version:"test",fields:[]},
      onChange:()=>{}, onSaved:()=>{}, onCopy:()=>{},
    }));
    await page.setViewportSize({ width:1200,height:1000 });
    await page.setContent('<section class="getting-started guided-cache-flow">'+html+'</section>');
    for (const path of ["src/styles.css","src/features/getting-started/getting-started.css","src/features/cache-profiles/cache-profiles.css"]) {
      await page.addStyleTag({ content: readFileSync(path,"utf8") });
    }
    const box = async (label: string | RegExp) => (await (label === "RDMA" ? page.locator("label").filter({hasText:/^RDMA/}).locator("select") : page.getByLabel(label,{exact:true})).boundingBox({timeout:5000}))!;
    const directory = await box("缓存基础目录"), capacity = await box("每节点容量");
    const weight = await box(/一致性哈希权重/), rdma = await box("RDMA");
    expect(Math.abs(directory.y-capacity.y)).toBeLessThan(1);
    expect(Math.abs(weight.y-rdma.y)).toBeLessThan(1);
    expect(Math.abs(weight.height-rdma.height)).toBeLessThan(1);
    expect(Math.abs(directory.height-capacity.height)).toBeLessThan(1);
    const notice = (await page.getByRole("alert").boundingBox())!;
    expect(Math.abs(notice.x-weight.x)).toBeLessThan(1);
    expect(Math.abs(notice.x+notice.width-rdma.x-rdma.width)).toBeLessThan(1);
    await page.setViewportSize({width:390,height:1200});
    expect((await box("RDMA")).y).toBeGreaterThan((await box(/一致性哈希权重/)).y);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  } finally { await server.close(); }
});

import {expect, test} from '@playwright/test';
test.use({serviceWorkers:'block'});

for (const scenario of ['checkpointing','kvcache']) {
  test(`MLPerf v3 ${scenario} guide preview`, async ({page, context, baseURL}) => {
    const previews:any[]=[];
    const unexpected:string[]=[];
    await context.route('**/*', async route => {
      const url=new URL(route.request().url());
      if(url.origin!==baseURL){unexpected.push(url.href);await route.abort();return;}
      if(!url.pathname.startsWith('/api/')){await route.continue();return;}
      const path=url.pathname.replace('/api/v1','');
      let body:unknown;
      if(path==='/auth/me') body={id:'u',username:'tester',email:'tester@example.com',role:'admin',csrf_token:'local-only'};
      else if(path==='/functional/guided/metadata') body={enabled:false};
      else if(path==='/performance/options') body={machines:[{id:'m',name:'本地验证机',address:'192.0.2.1',ssh_user:'tester',maintenance:false}],mounts:[]};
      else if(path==='/performance/preview'){
        const payload=route.request().postDataJSON();previews.push(payload);
        body={scene_count:1,total_bytes:16777216,tests:payload.tests.map((spec:any)=>({tool:spec.tool,parameters:spec,command:`dtt --mlperf-scenario ${spec.mlperf_scenario}`}))};
      }else{unexpected.push(path);await route.abort();return;}
      await route.fulfill({json:body});
    });
    await page.goto('/#/start/performance');
    await page.getByLabel('目标机器').selectOption('m');
    await page.getByLabel('目标目录').fill('/tmp/local-test');
    await page.getByRole('button',{name:'下一步'}).click();
    await page.getByLabel('MLPerf Storage').check();
    await page.getByRole('button',{name:'下一步'}).click();
    await page.getByLabel('MLPerf 场景').selectOption(scenario);
    await expect(page.getByLabel('训练模型')).toHaveCount(0);
    if(scenario==='checkpointing'){
      await page.getByLabel('检查点模式').selectOption('read');
      await page.getByLabel('每轮检查点次数').fill('2');
    }else{
      await page.getByLabel('KV Cache 模型').selectOption('tiny-1b');
      await page.getByLabel('KV Cache 每轮时长（秒）').fill('5');
    }
    await page.screenshot({path:`/tmp/mlperf-v3-${scenario}-guide.png`,fullPage:true});
    await page.getByRole('button',{name:'下一步'}).click();
    await page.getByRole('button',{name:'生成预览'}).click();
    await expect(page.getByText(`dtt --mlperf-scenario ${scenario}`,{exact:true})).toBeVisible();
    expect(previews).toHaveLength(1);
    expect(previews[0].tests[0].mlperf_scenario).toBe(scenario);
    expect(previews[0].tests[0]).not.toHaveProperty('mlperf_epochs');
    expect(unexpected).toEqual([]);
  });
}

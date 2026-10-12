import {test,expect} from "@playwright/test";
import {readFileSync} from "node:fs";
const catalog=JSON.parse(readFileSync(new URL('./fixtures/mount-parameter-catalog.json',import.meta.url),'utf8'));
test('configuration navigation and mount template creation',async({page})=>{
  let saved:any;const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/v1/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(path.endsWith('/auth/me')) return route.fulfill({json:{id:'u',username:'admin',email:'a@example.test',role:'admin',csrf_token:'t'}});
    if(path==='/api/v1/mount-profiles/catalog') return route.fulfill({json:catalog});
    if(path==='/api/v1/mount-profiles') {
      if(route.request().method()==='POST') {saved={...route.request().postDataJSON(),id:'p',revision:1,creator_id:'u',can_manage:true,source_version:'test',updated_at:new Date().toISOString()};return route.fulfill({status:201,json:saved});}
      return route.fulfill({json:saved?[saved]:[]});
    }
    return route.fulfill({json:[]});
  });
  await page.goto('/#/configuration/mount-profiles');
  await expect(page.getByRole('heading',{name:'配置管理',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'挂载配置',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'新建挂载配置'}).click();
  await page.getByLabel('配置名称',{exact:true}).fill('mount-fast');
  await page.getByRole('searchbox',{name:'搜索参数'}).fill('fuse_max_threads');
  await page.getByRole('checkbox',{name:'自定义 --fuse_max_threads',exact:true}).check();
  await page.getByRole('textbox',{name:'参数 --fuse_max_threads',exact:true}).fill('16');
  await page.getByRole('button',{name:'保存配置',exact:true}).click();
  await expect(page.getByText('mount-fast',{exact:true})).toBeVisible();
  expect(saved.parameters).toEqual({fuse_max_threads:'16'});
  await page.getByRole('navigation',{name:'配置分类'}).getByRole('button',{name:'存储配置'}).click();
  await expect(page.getByRole('heading',{name:'存储配置',exact:true})).toBeVisible();
  expect(errors).toEqual([]);
});

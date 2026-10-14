import { CandidateInput } from "./CandidateInput";
import { MdtestOption } from "./types";

type Value = string | number | boolean;
export function MdtestOptions({catalog,value,onChange}:{catalog:MdtestOption[];value:string;onChange:(v:string)=>void}) {
  const selected:Record<string,Value|Value[]> = JSON.parse(value);
  const set=(flag:string,v:Value|Value[]|undefined)=>{
    const next={...selected};
    if(v===undefined)delete next[flag];else next[flag]=v;
    if(flag==="-D" && v===true)next["-F"]=false;
    if(flag==="-F" && v===true)next["-D"]=false;
    if(flag==="-I" && v!==undefined)delete next["-n"];
    if(flag==="-n" && v!==undefined)delete next["-I"];
    onChange(JSON.stringify(next));
  };
  return <div className="mdtest-options">
    {!catalog.length && <p role="status">正在读取 mdtest 参数说明…</p>}
    {Array.from(new Set(catalog.map(o=>o.group))).map((group,index)=><details key={group} open={index===0} className="performance-config-section">
      <summary><strong>{group}</strong> · {catalog.filter(o=>o.group===group && selected[o.flag]!==undefined).length} 项已设置</summary>
      {group==="测试阶段" && <p className="muted">不勾选 -C/-T/-E/-r 时执行全部阶段；勾选后仅执行所选阶段。默认仅文件，关闭 -F 后可同时测试目录。</p>}
      <div className="mdtest-option-grid">{catalog.filter(o=>o.group===group).map(o=>{
        const v=selected[o.flag];const values=v===undefined?[]:Array.isArray(v)?v:[v];
        return <div key={o.flag} className="mdtest-option-card">
          {o.kind==="bool" ? <label className="mdtest-option-toggle"><input type="checkbox" aria-label={o.flag+" "+o.label} checked={Boolean(v??o.default)} onChange={e=>set(o.flag,e.target.checked)}/><span className="mdtest-option-heading"><code>{o.flag}</code><span>{o.label}</span></span></label> : <>
            <label className="mdtest-option-toggle"><input type="checkbox" checked={v!==undefined} onChange={e=>set(o.flag,e.target.checked ? (o.kind==="int" ? Math.max(Number(o.default),o.min??0) : o.default) : undefined)}/><span className="mdtest-option-heading"><code>{o.flag}</code><span>{o.label}</span></span></label>
            {v!==undefined && (o.kind==="int" ? <CandidateInput label={o.flag+" "+o.label} value={values.join(",")} choices={o.min===-1?["-1"]:[]} defaultUnit={o.bytes?"B":undefined} onChange={text=>set(o.flag,text.split(/[,，\s]+/).filter(Boolean).map(x=>{const m=x.match(/^(\d+)([KMGT]?)(?:i?B)?$/i);return m?Number(m[1])*1024**(m[2]?"KMGT".indexOf(m[2].toUpperCase())+1:0):Number(x)}))}/> : o.kind==="choice" ? <select aria-label={o.flag+" "+o.label} value={String(v)} onChange={e=>set(o.flag,e.target.value)}>{o.choices?.map(x=><option key={x}>{x}</option>)}</select> : <input aria-label={o.flag+" "+o.label} value={String(v)} onChange={e=>set(o.flag,e.target.value)}/>)}
          </>}
          <small className="muted mdtest-option-default">默认：{String(o.default)} {o.flag==="-F"?"（平台默认；原生默认同时测试文件和目录）":""}</small>
        </div>;
      })}</div>
    </details>)}
  </div>;
}

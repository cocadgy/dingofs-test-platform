import { CaseSelector } from "./CaseSelector";
import { moduleLabels, type GuidedCompatibility, type GuidedMetadata, type Options, type Profile } from "./types";
import { environmentReason } from "./EnvironmentStep";

export const guidedModules = [
  "quota","client","cache_node","fault","mount_subdir","basic_file_operation",
  "trash","dirstat","mds_manage","hot_upgrade","warmup","xattr",
];

export function CaseStep({options,metadata,profiles,clusterId,defaultEnvironmentId,selected,onSelected,
  choices,onChoice,onApply,compatibility,checking}:{
  options:Options;metadata:GuidedMetadata;profiles:Profile[];clusterId:string;defaultEnvironmentId:string;
  selected:Record<string,string[]>;onSelected:(value:Record<string,string[]>)=>void;
  choices:Record<string,string>;onChoice:(module:string,id:string)=>void;
  onApply:(module:string,id:string)=>void;
  compatibility:GuidedCompatibility|null;checking:boolean;
}) {
  const modules = Object.fromEntries(Object.entries(options.modules).filter(([name]) => guidedModules.includes(name)));
  const chosenModules = Object.entries(selected).filter(([,cases]) => cases.length).map(([module]) => module);
  const supported = profiles.filter(profile => !environmentReason(profile,clusterId,metadata));
  const excluded = Object.keys(options.modules).filter(module => !guidedModules.includes(module));
  return <section>
    <h1>选择模块和用例</h1>
    <p>勾选要运行的精确用例；每个模块都需选择兼容的已有环境。</p>
    <CaseSelector modules={modules} selected={selected} onChange={onSelected} />
    {excluded.length > 0 && <p className="muted">暂未接入：{excluded.map(module => moduleLabels[module] || module).join("、")}</p>}
    {chosenModules.map(module => {
      const result = compatibility?.modules[module];
      const choice = choices[module] || (result?.compatible ? defaultEnvironmentId : "");
      return <section className="functional-card" key={module}>
        <h2>{moduleLabels[module] || module} · {selected[module].length} 个用例</h2>
        <label>{module} 测试环境
          <select value={choice} onChange={event => onChoice(module,event.target.value)}>
            <option value="">选择兼容环境</option>
            {supported.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
          </select>
        </label>
        {checking && <p>正在检查所选用例与环境…</p>}
        {result && !result.compatible && <p className="error">{moduleLabels[module] || module}：{result.reasons.join("；") || "环境不兼容，请明确选择其他环境"}</p>}
        {result?.compatible && <p>已验证所选用例兼容 · 执行目标：{result.targets?.map(target =>
          `${"name" in target ? target.name : target.host}（${"address" in target ? target.address : target.host}，${target.user}）`).join("、") || "按环境确定"}</p>}
        {choice && chosenModules.length > 1 && <button type="button" onClick={() =>
          onApply(module,choice)}>将此环境应用到其他模块</button>}
      </section>;
    })}
  </section>;
}

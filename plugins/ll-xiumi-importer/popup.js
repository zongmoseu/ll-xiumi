import { applyBridgeInPage } from "./page-runtime.js";
const el=(id)=>document.getElementById(id);
let packet=null,receipt=null,busy=false,lastDiagnostic=null;
function show(message,kind=""){el("status").textContent=message;el("status").className=kind;}
function buttons(){el("insert").disabled=busy||!packet;el("verify").disabled=busy||!packet||!receipt;el("file").disabled=busy;el("diagnostic").disabled=busy||!lastDiagnostic;}
function validate(value){
  if(value?.schema!=="xiumi-bridge/v3"||!Array.isArray(value.native?.modules)||!value.native.modules.length||!Array.isArray(value.assets)||typeof value.html!=="string")throw new Error("请选择排版skill输出的article.xiumi.json，不能直接选择Word或HTML。");
  if(value.assetSummary?.local)throw new Error("数据包仍有未绑定的本地图片，请让AI重新打包。");
  return value;
}
function details(){el("meta").style.display=packet?"block":"none";el("title").value=packet?.publication?.title||packet?.title||"";el("summary").value=packet?.publication?.summary||"";buttons();}
chrome.storage.local.get(["wjxPacket","wjxReceipt","wjxDiagnostic"]).then(data=>{
  lastDiagnostic=data.wjxDiagnostic||null;
  if(data.wjxPacket){try{packet=validate(data.wjxPacket);receipt=data.wjxReceipt||null;details();show(`已恢复 ${packet.native.modules.length} 个模块、${packet.assets.length} 项素材。`,"ok");}catch(e){show(e.message,"error");}}
}).catch(()=>show("上次文件未能恢复，请重新选择。","error"));
el("file").addEventListener("change",async event=>{
  const file=event.target.files?.[0];if(!file)return;lastDiagnostic=null;
  try{if(file.size>120*1024*1024)throw new Error("数据包超过120MB，请让AI压缩照片后再试。");packet=validate(JSON.parse(await file.text()));receipt=null;await chrome.storage.local.set({wjxPacket:packet});await chrome.storage.local.remove(["wjxReceipt","wjxDiagnostic"]);details();show(`已读取 ${packet.native.modules.length} 个模块、${packet.assets.length} 项素材。请在秀米空白图文中导入。`,"ok");}
  catch(e){packet=null;receipt=null;details();show(e.message||"文件读取失败","error");}
});
async function activeTab(){const [tab]=await chrome.tabs.query({active:true,currentWindow:true});if(!tab?.id||!/^https:\/\/(?:[^/]+\.)?xiumi\.us\//i.test(tab.url||""))throw new Error("请先打开秀米的图文编辑页面，再打开本插件。");return tab.id;}
async function execute(action){
  if(!packet||busy)return;busy=true;buttons();show(action==="insert"?"正在上传图片并写入正文，请保持页面与插件打开…":"正在核对保存后稿件…");
  let timer=null;
  try{
    const id=await activeTab();
    if(action==="insert")timer=setInterval(async()=>{
      try{const [value]=await chrome.scripting.executeScript({target:{tabId:id},world:"MAIN",func:()=>{const p=window.__wjxUploadProgress;return p?{running:p.running,completed:p.completed,total:p.total,index:p.index,stage:p.stage}:null;}});const p=value?.result;if(busy&&p?.running)show(p.stage==="write"?"图片已上传，正在写入正文…":`正在上传第 ${p.index}/${p.total} 张图片，已完成 ${p.completed} 张…`);}catch{}
    },1000);
    const [result]=await chrome.scripting.executeScript({target:{tabId:id},world:"MAIN",func:applyBridgeInPage,args:[packet,action,receipt]});
    if(timer){clearInterval(timer);timer=null;}
    if(result?.result?.diagnostic){lastDiagnostic=result.result.diagnostic;await chrome.storage.local.set({wjxDiagnostic:lastDiagnostic});}
    if(!result?.result?.ok)throw new Error(result?.result?.message||"未能读取秀米编辑器，请刷新秀米页面后重试。");
    receipt=result.result.receipt||receipt;if(receipt)await chrome.storage.local.set({wjxReceipt:receipt});show(result.result.message,"ok");
  }catch(e){show(e.message||"导入失败，请检查秀米登录状态和页面提示。","error");}
  finally{if(timer)clearInterval(timer);busy=false;buttons();}
}
el("insert").addEventListener("click",()=>execute("insert"));
el("verify").addEventListener("click",()=>execute("verify"));
el("diagnostic").addEventListener("click",()=>{
  if(!lastDiagnostic)return;const url=URL.createObjectURL(new Blob([JSON.stringify(lastDiagnostic,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download="ll_xiumi_错误说明.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});

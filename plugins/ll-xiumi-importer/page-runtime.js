/** Injected in MAIN world. Use Xiumi's own factory, modifier and history batch.
 * Capability names were checked against the public v5 studio bundle; fail closed
 * if the editor changes. Never manipulate ngStorage or claim a server save.
 * @param {object} packet
 * @param {string} action
 * @param {{digest:string,modules:number,paperId:string|null,pageStyle:string,timeOrigin:number}|null} receipt
 */
export async function applyBridgeInPage(packet, action, receipt = null) {
  const diagnostic = { pluginVersion: "0.6.0", stage: "preflight", total: 0, uploaded: 0, current: null };
  let ownsUpload = false;
  try {
    const fail = (message) => { throw new Error(message); };
    const visible = (element) => element.getBoundingClientRect().width > 0 && getComputedStyle(element).visibility !== "hidden";
    if (location.hostname !== "xiumi.us" || !location.hash.startsWith("#/paper/")) fail("请打开秀米图文编辑页");
    if ([...document.querySelectorAll('.modal,[role="dialog"]')].some(visible)) fail("请先处理秀米当前的对话框，再执行导入；原有草稿缓存会保留");
    const angular = window.angular; const $ = window.jQuery || window.$;
    const injector = angular?.element(document.body).injector() || angular?.element(document.documentElement).injector();
    if (!injector || typeof $ !== "function") fail("未找到秀米编辑服务，请等待页面加载完成");
    const tower = injector.get("tower");
    const manager = tower.require("editingManager");
    const pages = injector.get("tnScrolledPageManager");
    const activePage = pages.getActivePage();
    const pageElement = activePage?.find(".tn-page-inst");
    const pageInstance = pageElement?.compInst();
    const container = pageElement?.find(".tn-comp-slot").cellInst();
    const facility = manager?.facility;
    if (!pageInstance || !Array.isArray(container?.cellArray) || !facility || manager.config("showType") !== "paper" || !["beginBatch", "endBatch", "update", "insert", "remove"].every((name) => typeof manager[name] === "function")) fail("当前秀米版本没有兼容的模块写入通道，未更改正文");
    const pageRoot = pageElement[0];
    const paperId = () => location.hash.match(/\/paper\/for\/(\d+)/)?.[1] || null;
    const initialPaperId = paperId();
    const parse = (html) => { const holder = document.createElement("template"); holder.innerHTML = html; return holder; };
    const textCells = (comp) => {
      const cells = [];
      const visit = (value) => {
        if (!value || typeof value !== "object") return;
        if (value.type === "text" && typeof value.text === "string") { cells.push(value); return; }
        for (const [key, child] of Object.entries(value)) if (key !== "_comp") visit(child);
      };
      visit(comp); return cells;
    };
    const signature = async () => {
      const html = container.cellArray.map((comp) => textCells(comp).map((cell) => parse(cell.text).innerHTML));
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(html)));
      return { digest: [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join(""), modules: container.cellArray.length, paperId: paperId(), pageStyle: JSON.stringify(Object.fromEntries(Object.entries(pageInstance.comp._comp.style).sort(([a], [b]) => a.localeCompare(b)))), timeOrigin: performance.timeOrigin };
    };
    const canonical = (value) => Array.isArray(value) ? value.map(canonical) : value && typeof value === "object" ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonical(item)])) : value;
    const moduleHashes = async () => Promise.all(container.cellArray.map(async (comp) => {
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(canonical(comp))));
      return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
    }));
    if (action === "capture-source") return { ok: true, message: "已读取原生模块基线", nativeModuleHashes: await moduleHashes() };
    if (action === "verify") {
      if (!receipt) fail("还没有本次导入记录");
      const actual = await signature();
      if ((receipt.paperId && receipt.paperId !== actual.paperId) || actual.digest !== receipt.digest || actual.modules !== receipt.modules || actual.pageStyle !== receipt.pageStyle) fail("当前稿件与导入记录不同，请检查是否切换了稿件或又做了修改");
      return { ok: true, message: `${actual.modules} 个模块、正文、图片地址和全文格式与导入记录一致。${actual.timeOrigin !== receipt.timeOrigin ? "已在重新加载的页面核验。" : "请保存并重新打开稿件后再次核验。"}服务器保存状态请以秀米提示为准。`, receipt: actual };
    }
    if (typeof packet?.html !== "string" || !packet.html.trim()) fail("数据包没有正文");
    const digest = injector.get("$rootScope");
    const transact = async (work) => new Promise((resolve, reject) => {
      const run = () => { manager.beginBatch(); try { resolve(work()); } catch (error) { reject(error); } finally { manager.endBatch(); } };
      if (digest.$$phase) digest.$evalAsync(run); else digest.$apply(run);
    });
    const validLink = (value) => { if (!value) return ""; const url = new URL(value); if (!["http:", "https:"].includes(url.protocol)) fail("链接地址无效"); return url.href; };
    if (action === "patch") {
      const patch = packet.patch;
      if (packet.schema !== "xiumi-bridge/v3" || !patch?.available || !patch.source?.paperId || !Array.isArray(patch.operations) || !patch.operations.length) fail(patch?.reasons?.join("；") || "这个包没有可靠的原稿位置，请重新抓取原稿后再做原位更新");
      if (paperId() !== patch.source.paperId) fail("当前秀米稿件不是抓取时的原稿，未执行替换");
      const expectedHashes = patch.source.nativeModuleHashes;
      if (!Array.isArray(expectedHashes) || !expectedHashes.length || JSON.stringify(expectedHashes) !== JSON.stringify(await moduleHashes())) fail("原生模块内容、样式或顺序与抓取时不同，请重新抓取；没有写入任何替换");
      const modules = [...pageRoot.querySelectorAll(".tn-comp-top-level")].filter((element) => !element.parentElement?.closest(".tn-comp-top-level"));
      const cells = modules.map((module) => [...module.querySelectorAll('[contenteditable="true"]')].filter((cell) => !cell.parentElement?.closest('[contenteditable="true"]')));
      const baseline = patch.source.modules;
      if (!Array.isArray(baseline) || baseline.length !== cells.length || baseline.some((module, index) => module.index !== index || JSON.stringify(module.cells) !== JSON.stringify(cells[index].map((cell) => cell.textContent || "")))) fail("原稿的内容或模块顺序已改变，请重新抓取；没有写入任何替换");
      const staged = new Map();
      for (const operation of [...patch.operations].sort((a, b) => b.start - a.start)) {
        if (![operation.module, operation.cell, operation.start, operation.end].every((value) => Number.isSafeInteger(value) && value >= 0) || operation.start >= operation.end || typeof operation.search !== "string" || typeof operation.text !== "string") fail("替换位置无效");
        const element = cells[operation.module]?.[operation.cell];
        if (!element || element.textContent.slice(operation.start, operation.end) !== operation.search) fail("替换原文与当前位置不一致");
        const key = `${operation.module}:${operation.cell}`;
        if (!staged.has(key)) {
          const instance = $(element).cellInst();
          if (!instance?.cellPath || instance.cell?.type !== "text" || typeof instance.cell.text !== "string") fail("无法定位原生文字模型，未执行替换");
          const holder = parse(instance.cell.text);
          if (holder.content.textContent !== element.textContent) fail("秀米文字模型尚未同步，请结束编辑后重新抓取");
          staged.set(key, { instance, holder, previous: instance.cell.text, ranges: [] });
        }
        const stage = staged.get(key);
        if (stage.ranges.some(([start, end]) => operation.start < end && operation.end > start)) fail("替换位置重叠，未执行替换");
        stage.ranges.push([operation.start, operation.end]);
        const walker = document.createTreeWalker(stage.holder.content, NodeFilter.SHOW_TEXT);
        let offset = 0; let node = null;
        while (walker.nextNode()) {
          const candidate = walker.currentNode;
          if (operation.start >= offset && operation.end <= offset + candidate.length) { node = candidate; break; }
          offset += candidate.length;
        }
        if (!node) fail("替换跨越多个样式部件，请让 AI 重新选择文本叶节点");
        const anchor = node.parentElement?.closest("a");
        if (validLink(anchor?.getAttribute("href") || "") !== validLink(operation.expectedHref)) fail("原文链接已改变，请重新抓取");
        const href = validLink(operation.href);
        const range = document.createRange(); range.setStart(node, operation.start - offset); range.setEnd(node, operation.end - offset);
        if (anchor && href !== validLink(operation.expectedHref)) {
          // An anchor can contain several styled text nodes. Updating just one
          // must not silently change its siblings' link.
          if (anchor.textContent !== operation.search) fail("链接跨越多个文本部件，请用完整导入更新此链接");
          if (href) anchor.setAttribute("href", href);
        }
        range.deleteContents();
        const replacement = document.createDocumentFragment();
        operation.text.replace(/\r\n?/g, "\n").split("\n").forEach((line, index) => { if (index) replacement.append(document.createElement("br")); replacement.append(document.createTextNode(line)); });
        if (href && !anchor) { const link = document.createElement("a"); link.href = href; link.style.cssText = "color:inherit;text-decoration:none;"; link.target = "_blank"; link.rel = "noopener noreferrer"; link.append(replacement); range.insertNode(link); } else range.insertNode(replacement);
        if (anchor && !href) anchor.replaceWith(...anchor.childNodes);
      }
      const stages = [...staged.values()];
      await transact(() => {
        try { for (const stage of stages) manager.update(stage.instance.cellPath, stage.instance.cell, { text: stage.holder.innerHTML }); }
        catch (error) { for (const stage of stages) manager.update(stage.instance.cellPath, stage.instance.cell, { text: stage.previous }); throw error; }
      });
      return { ok: true, message: `已在原生模型中更新 ${patch.operations.length} 处文字或链接。请保存并重新打开后核验。`, receipt: await signature() };
    }
    if (action !== "insert") fail("未知操作");
    if (container.cellArray.length) fail("分模块导入需要空白秀米图文。请新建图文后导入；原稿文字修改可用“校验并原位更新”");
    if (typeof facility.createDefaultComp !== "function" || typeof facility.beforeInsertingComps !== "function") fail("秀米原生组件工厂不可用，未写入正文");
    const native = packet.native;
    if (!Array.isArray(native?.modules) || !native.modules.length || native.modules.length > 5000) fail("缺少可导入的模块边界，请让 AI 使用新版排版skill重新导出 Bridge 数据包");
    const allowedStyles = new Set(["font-family", "font-size", "line-height", "letter-spacing", "color", "text-align", "text-indent", "padding-top", "padding-right", "padding-bottom", "padding-left", "background-color", "background-image", "background-size", "background-position", "background-repeat"]);
    const format = document.createElement("section");
    for (const [key, value] of Object.entries(native.pageFormat?.styles || {})) { if (!allowedStyles.has(key) || typeof value !== "string") fail("全文格式包含未知设置"); format.style.setProperty(key, value); if (!format.style.getPropertyValue(key)) fail("全文格式无效"); }
    const holders = native.modules.map((module) => { if (typeof module.html !== "string" || !module.html.trim()) fail("存在空模块"); return parse(module.html); });
    const manifest = new Map((packet.assets || []).map((asset) => [asset.id, asset.src]));
    const sources = new Set(); const rewrites = [];
    const resource = (value) => {
      if (value.startsWith("#")) return value;
      if (value.startsWith("opslion-asset://")) { value = manifest.get(value.slice(16)); if (!value) fail("素材清单缺少图片"); }
      if (!/^data:image\/(?:png|jpe?g|gif|webp|avif);base64,[a-z\d+/=\s]+$/i.test(value)) {
        let url; try { url = new URL(value); } catch { fail("包含本地图片地址，请让 AI 重新导出并绑定素材"); }
        if (!["https:", "http:"].includes(url.protocol) || /^(?:localhost|127\.0\.0\.1|\[::1\])$/i.test(url.hostname)) fail("图片尚未绑定为可发布资源");
      }
      sources.add(value); return value;
    };
    for (const holder of [...holders, { content: format }]) for (const element of [holder.content, ...holder.content.querySelectorAll("*")]) {
      if (!(element instanceof Element)) continue;
      if (/^(SCRIPT|IFRAME|OBJECT|EMBED|FORM|INPUT|BUTTON|STYLE|LINK|META)$/i.test(element.tagName)) fail("模块包含不支持的活动内容");
      for (const attribute of element.attributes) {
        if (/^on/i.test(attribute.name)) fail("模块包含脚本事件，未导入");
        if (["href", "xlink:href"].includes(attribute.name) && element.localName === "a") validLink(attribute.value);
      }
      if (["animate", "animateTransform", "set"].includes(element.localName) && !/^(?:viewBox|height|width|x|y|opacity|transform|visibility)$/.test(element.getAttribute("attributeName") || "")) fail("SVG 动画尝试修改不支持的属性");
      for (const name of element.tagName === "IMG" ? ["src"] : element.localName === "image" ? ["href", "xlink:href"] : []) {
        const raw = element.getAttribute(name); if (!raw) continue;
        const src = resource(raw); rewrites.push((mapping) => element.setAttribute(name, mapping.get(src) || src));
      }
      if (element.localName === "use" && !/^#/.test(element.getAttribute("href") || element.getAttribute("xlink:href") || "")) fail("SVG 外部引用不受支持");
      if (element.hasAttribute("style")) {
        const style = element.getAttribute("style");
        if (/[\\]|\/\*|(?:expression|var|attr|env|image-set)\s*\(|(?:javascript|vbscript)\s*:/i.test(style)) fail("模块包含不支持的样式");
        const found = [...style.matchAll(/url\(\s*(["']?)([^"')]+)\1\s*\)/gi)].map((match) => ({ match: match[0], src: resource(match[2]) }));
        rewrites.push((mapping) => { let next = style; for (const item of found) next = next.replaceAll(item.match, `url("${(mapping.get(item.src) || item.src).replace(/"/g, "%22")}")`); element.setAttribute("style", next); });
      }
    }
    const getOptional = (name) => { try { return injector.get(name); } catch { return null; } };
    const transfer = getOptional("wxArticleTransfer"); const images = getOptional("ossImageHandler");
    const imageAPI = getOptional("imageAPI");
    const embedded = [...sources].filter((src) => src.startsWith("data:"));
    const isHosted = (src) => { try { const url = new URL(src); const host = url.hostname; return ["https:","http:"].includes(url.protocol) && (/([.]|^)xiumi[.]us$/.test(host) || /([.]|^)xiumius[.]cn$/.test(host) || /([.]|^)xiumi[.]world$/.test(host)); } catch { return false; } };
    const external = [...sources].filter((src) => !src.startsWith("data:") && !src.startsWith("#") && !isHosted(src));
    if ((embedded.length && ![imageAPI?.uploadImages,imageAPI?.uploadImageInBase64,transfer?.fetchBase64ImgsToStorage].some(fn=>typeof fn==="function")) || (external.length && typeof transfer?.fetchAnyImgsToStorage !== "function") || typeof images?.runtimeImageURI !== "function") fail("当前秀米版本不支持所需的素材上传，未更改正文");
    if (window.__wjxUploadProgress?.running) fail("上一次导入仍在进行，请稍候再试，避免重复上传");
    ownsUpload=true;diagnostic.total=embedded.length+external.length;diagnostic.stage="upload";
    window.__wjxUploadProgress={running:true,completed:0,total:diagnostic.total,index:0,stage:"upload"};
    const mapping = new Map();
    const describe = (error) => {
      const data=error?.data||error?.response?.data;
      const status=Number(error?.status||error?.response?.status)||null;
      const code=typeof data?.code==="string"||typeof data?.code==="number"?String(data.code):"";
      let message=error instanceof Error?error.message:typeof data==="string"?data:typeof data?.message==="string"?data.message:typeof data?.errmsg==="string"?data.errmsg:typeof data?.error==="string"?data.error:typeof error?.message==="string"?error.message:"秀米没有返回图片地址";
      message=String(message).replace(/data:image\/[^\s"']+/gi,"[图片内容已省略]").replace(/[A-Za-z0-9+/=]{120,}/g,"[长数据已省略]").replace(/https?:\/\/[^\s"<>]+/g,"[地址已省略]").slice(0,220);
      return {status,code,message};
    };
    // Use the same File upload service as the ordinary image picker. The bulk
    // clipboard wrapper catches per-image errors and hides why uploads fail.
    for (const [index,src] of [...embedded,...external].entries()) {
      const meta=(packet.assets||[]).find(a=>a.src===src);
      const mime=src.startsWith("data:")?src.slice(5,src.indexOf(";")):"remote";
      diagnostic.current={index:index+1,assetId:meta?.id||`image-${index+1}`,mime,bytes:meta?.bytes||0,method:"",status:null,code:"",message:""};
      window.__wjxUploadProgress.index=index+1;
      try {
        let raw;
        if (src.startsWith("data:") && typeof imageAPI?.uploadImages==="function") {
          diagnostic.current.method="imageAPI.uploadImages";
          const base64=src.slice(src.indexOf(",")+1).replace(/\s/g,"");const bytes=Uint8Array.from(atob(base64),c=>c.charCodeAt(0));
          const extension=mime==="image/jpeg"?"jpg":mime.split("/")[1];
          const file=new File([bytes],`wjx-image-${index+1}.${extension}`,{type:mime});
          const result=await imageAPI.uploadImages([file],null,null,null,{});
          raw=result?.[0]?.target_uri||result?.target_uri||result?.data?.target_uri;
        } else if (src.startsWith("data:") && typeof imageAPI?.uploadImageInBase64==="function") {
          diagnostic.current.method="imageAPI.uploadImageInBase64";
          const result=await imageAPI.uploadImageInBase64(src,`wjx-image-${index+1}.${mime==="image/jpeg"?"jpg":mime.split("/")[1]}`,null);
          raw=result?.target_uri||result?.data?.target_uri;
        } else {
          const method=src.startsWith("data:")?"fetchBase64ImgsToStorage":"fetchAnyImgsToStorage";diagnostic.current.method=method;
          const result=await transfer[method]([src]);raw=result?.[src];
        }
        if(typeof raw!=="string"||!raw)throw new Error("秀米未返回这张图片的地址，请检查登录状态、素材额度和上传提示");
        const hosted=new URL(images.runtimeImageURI(raw),location.href).href;
        if(!isHosted(hosted))throw new Error("上传返回了未识别的图片域名："+new URL(hosted).hostname);
        mapping.set(src, hosted);
        diagnostic.uploaded++;window.__wjxUploadProgress.completed=diagnostic.uploaded;
      } catch(error) {
        Object.assign(diagnostic.current,describe(error));
        const detail=diagnostic.current;
        if(`${detail.code} ${detail.message}`.includes("Auth:Failed_NotLogin")) {
          detail.code="Auth:Failed_NotLogin";
          fail("秀米上传服务未识别到有效登录。请在当前浏览器的秀米网页登录或重新登录，再刷新编辑页后导入（不是登录Edge账号）。正文尚未写入，无需重新生成数据包。");
        }
        fail(`第 ${detail.index}/${diagnostic.total} 张图片上传失败（${detail.assetId}，${Math.ceil(detail.bytes/1024)}KB）${detail.status?`，HTTP ${detail.status}`:""}${detail.code?`，${detail.code}`:""}：${detail.message}。已完成 ${diagnostic.uploaded} 张，正文尚未写入。`);
      }
    }
    diagnostic.stage="write";window.__wjxUploadProgress.stage="write";
    for (const rewrite of rewrites) rewrite(mapping);
    const comps = holders.flatMap((holder) => {
      const created = facility.createDefaultComp("paper", "text", { text: holder.innerHTML });
      const result = Array.isArray(created) ? created : [created];
      if (result.length !== 1 || !result[0] || textCells(result[0]).length !== 1 || textCells(result[0])[0].text !== holder.innerHTML) fail("秀米组件工厂没有保留模块内容，未写入正文");
      return result;
    });
    if (JSON.stringify(comps).length > 1_500_000 || /data:image\//i.test(JSON.stringify(comps))) fail("模块数据仍然过大或存在内嵌图片，未写入正文");
    const style = pageInstance.comp?._comp?.style;
    if (!style || typeof style !== "object") fail("无法定位全文格式，未写入正文");
    const previousStyle = { ...style };
    const nextStyle = { compMargin: 0, paragraphMargin: 0, textIndent: "0px", textAlign: "left", letterSpacing: "normal", paddingTop: "0px", paddingRight: "0px", paddingBottom: "0px", paddingLeft: "0px", backgroundColor: "transparent", backgroundImage: "none", backgroundSize: "auto", backgroundPosition: "0% 0%", backgroundRepeat: "repeat" };
    for (const property of allowedStyles) {
      const value = format.style.getPropertyValue(property); if (value) nextStyle[property.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = value;
    }
    const fontSize = parseFloat(format.style.fontSize);
    if (format.style.lineHeight.endsWith("px") && fontSize > 0) nextStyle.lineHeight = String(parseFloat(format.style.lineHeight) / fontSize);
    if (format.style.fontSize.endsWith("px")) {
      const base = parseFloat(getComputedStyle(pageRoot).fontSize);
      if (base > 0) nextStyle.fontSize = `${fontSize / base * 100}%`;
    }
    // A user may edit while uploads are running. Recheck immediately before commit.
    if (container.cellArray.length || paperId() !== initialPaperId || pageInstance.comp !== pages.getActivePage()?.find(".tn-page-inst").compInst()?.comp || [...document.querySelectorAll('.modal,[role="dialog"]')].some(visible)) fail("上传期间稿件状态已改变，请重新打开插件后导入");
    facility.beforeInsertingComps(comps, "static", container.hostCompInst);
    if (comps.some((comp, index) => textCells(comp).length !== 1 || textCells(comp)[0].text !== holders[index].innerHTML)) fail("秀米的模块准备流程改变了母版内容，未写入正文");
    await transact(() => {
      try {
        manager.update(pageInstance.compPath, style, nextStyle);
        if (Object.entries(nextStyle).some(([key, value]) => style[key] !== value)) fail("全文格式未完整写入");
        manager.insert(container.cellPath, container.cellArray, comps);
        if (container.cellArray.length !== comps.length) fail("模块写入数量不符");
      } catch (error) {
        if (container.cellArray.length) manager.remove(container.cellPath, container.cellArray, 0, container.cellArray.length);
        manager.update(pageInstance.compPath, style, Object.fromEntries([...new Set([...Object.keys(nextStyle), ...Object.keys(previousStyle)])].map((key) => [key, previousStyle[key]])));
        throw error;
      }
    });
    diagnostic.stage="complete";window.__wjxUploadProgress.running=false;
    return { ok: true, message: `已写入 ${comps.length} 个独立模块，上传并绑定 ${mapping.size} 张图片。请在秀米保存并重新打开后核验。`, receipt: await signature(), diagnostic };
  } catch (error) { if(ownsUpload&&window.__wjxUploadProgress)window.__wjxUploadProgress.running=false;return { ok: false, message: error instanceof Error ? error.message : "秀米导入未完成", diagnostic }; }
}

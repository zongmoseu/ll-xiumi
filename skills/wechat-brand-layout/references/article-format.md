# 结构稿与导出

命令由AI执行，用户提供稿件、素材及反馈。scripts/layout_engine.py与scripts/export_xiumi.py随本skill独立附带，不依赖其他排版skill。extract输出由AI阅读和组织；脚本负责提取、渲染和打包，不假装自动完成语义设计。

## 顶层

version:1、title、column（任意真实栏目名称）、subtype、classification_reviewed:true、source_text、blocks，以及可选summary、cover、brand_id、style_overrides、layout_additions。

extract不会套用机构分类；初始column为“通用”，读稿后确认。将真正标题从首段移至title时移除对应正文段。source_text不得为通过校验而篡改。用户明确允许修改文字才设user_authorized_text_changes:true并说明改动。

render用profile.theme作为默认，article.style_overrides可覆盖单篇；旧稿theme名称不会选中别的品牌。跨brand_id更换需用户明确要求并重新审阅组件。

## 模块

文字模块paragraph、heading、caption、credit、quote以runs承载text与bold/italic/underline/href。heading.level为2或3，paragraph.indent:false取消缩进。普通正文两端对齐、首行2em；已有诗歌/短句不强制缩进。

group含blocks及variant（intro / section / summary），按语义分组。图片、图注、表格可与文字在同一组。样式来自profile，普通组默认22px，结语26px；不开边框也保留文字留白。

image含本地src、可选width_percent（默认90）、width（像素上限）、alt、caption；已有独立图注勿重复。多张照片使用连续image或gallery.images中的独立图片，默认每组2–3张用row、间距8px；不拼成一个文件。明确要求上下时使用stack，只有明确选择时使用滑动图并在真实秀米验证。源文件若是预拼图，先查看边界，再按用户意图拆分或索取原片；记录派生图来源与像素区域，不误拆完整设计图。

table.rows是cell数组，各cell含blocks、colspan、rowspan；可配header_rows、column_widths（合计100）、nowrap_name_columns。保持可编辑；窄屏不可读时讨论拆分，不删列。

list_item含marker、level；section_label含label并记入layout_additions，end_mark为可选END。独立结语有标题，无正文不补写。unresolved_media保留未处理图形，解决后才能打包。

component.component为profile素材ID（a-哈希），仅引用已分类且renderable的素材；可设置width、background、edge_aligned。header/footer自动添加到正文两端，重渲染不重复添加。其他Logo/分隔素材由AI按稿件选择，cover/reference不能用作component。

## 输出

article.xiumi.json采用xiumi-bridge/v3，含native.modules、pageFormat、内嵌assets、publication标题摘要，与现有插件兼容。preview.html为预览；article.html、images/、article.json为备用。publication.cover仅作封面信息，不自动填秀米封面栏。

text_preserved、can_export、xiumi_package_generated须为true；图片内嵌、assetSummary.local:0；本地检查不等同账号导入保存。脚本不登录、上传、发布。

DOCX可无列表编号部件，有编号引用但缺定义则停止；修订、公式、未支持媒体不要丢弃。静态WebP/AVIF按实际字节转PNG，动态内容不默默变静态。图形待处理时can_export:false，不生成假完成包。

## 明确要求左右相邻的多图

gallery.mode=row，images为2–3张独立图片，width_percent控制整组宽度（默认90），gap_px控制图间距（默认8px，范围0–32px；只有明确要求无缝时设0）。图片在独立表格单元中左右相邻，不合成位图、不裁切、不拉伸，每张仍为独立img与包内素材。异同比例保持各自高度，不为了填满而裁人；图注位置词需同步。超过3张按内容分组，不塞进一排。

## 固定结构规范

先读layout-spec.md并运行随包渲染器，不重写CSS。脚本默认将散列正文整理为分区框，连续独立照片整理为每行2–3张、间距8px的row图组；保留显式group、gallery模式与图片尺寸。无标题的summary组补结语导航标题并记录layout_additions，END放在署名前。用户要求特殊布局时在结构稿明确表示，不靠遗漏group来改变样式。

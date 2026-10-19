"""Local manuscript -> classified, editable WeChat HTML. No uploading or publishing."""
import argparse
import hashlib
import html
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

SKILL_DIR = Path(__file__).resolve().parents[1]
THEMES = json.loads((SKILL_DIR/'assets/themes.json').read_text(encoding='utf-8'))
COLUMNS = json.loads((SKILL_DIR/'assets/columns.json').read_text(encoding='utf-8'))
COMPONENTS = json.loads((SKILL_DIR/'assets/components.json').read_text(encoding='utf-8'))

def dump(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

def format_credit_runs(rr):
    """Normalize only the role/name separator, preserving text-run formatting."""
    text=runs_text(rr)
    labels='图文|文字|图片|摄影|撰稿|供稿|文案|编辑|美编|责编|主编|审核|审校|校对|排版|设计|策划|统筹|来源'
    match=re.match(r'^('+labels+r')[ \t\u3000]*[:：|｜][ \t\u3000]*',text)
    if not match:return rr
    def slice_runs(start,end):
        result=[];offset=0
        for run in rr:
            value=run.get('text','');left=max(start-offset,0);right=min(end-offset,len(value))
            if left<right:result.append({**run,'text':value[left:right]})
            offset+=len(value)
        return result
    return slice_runs(0,len(match[1]))+[{'text':' | '}]+slice_runs(match.end(),len(text))


def display_blocks(blocks):
    """Keep source/portable article untouched; audit only visual credit punctuation."""
    from copy import deepcopy
    result=deepcopy(blocks);changes=[]
    def visit(items):
        for item in items:
            if item['type']=='credit':
                before=runs_text(item.get('runs',[]))
                item['runs']=format_credit_runs(item.get('runs',[]))
                after=runs_text(item['runs'])
                if before!=after:changes.append({'before':before,'after':after})
            elif item['type']=='group':visit(item['blocks'])
            elif item['type']=='table':
                for row in item['rows']:
                    for cell in row:visit(cell['blocks'])
    visit(result)
    return result,changes


def compact(text):
    return re.sub(r'\s+', '', text)

def runs_text(runs):
    return ''.join(str(r.get('text', '')) for r in runs)

def blocks_text(blocks):
    parts=[]
    for b in blocks:
        if b['type']=='group':parts.append(blocks_text(b['blocks']))
        elif b['type'] in ('section_label','end_mark'):continue
        elif b['type']=='table':
            for row in b['rows']:
                for cell in row:parts.append(blocks_text(cell['blocks']))
        elif b['type']=='gallery':
            parts.extend(i.get('caption','') for i in b['images'])
        elif b['type'] in ('image','component'):parts.append(b.get('caption',''))
        else:parts.append(runs_text(b.get('runs',[])))
    return '\n'.join(parts)

def classify(title, text='', source_column=None):
    return {'column':'通用','subtype':'待确认','confidence':'needs-review','reason':'按实际稿件确认栏目，不根据栏目切换品牌样式'}


def safe_href(value):
    value=str(value)
    if urlparse(value).scheme.lower() not in ('https','http','mailto','tel'):
        raise ValueError('不支持的链接协议：'+value)
    return value

def inline_markdown(text):
    # Deliberately a small subset; no raw HTML is evaluated.
    result=[];pos=0
    pat=r'\*\*([^*]+)\*\*|\[([^\]]+)\]\((https?://[^\s)]+)\)|\*([^*]+)\*'
    for m in re.finditer(pat,text):
        if m.start()>pos:result.append({'text':text[pos:m.start()]})
        if m[1]:result.append({'text':m[1],'bold':True})
        elif m[2]:result.append({'text':m[2],'href':m[3]})
        else:result.append({'text':m[4],'italic':True})
        pos=m.end()
    if pos<len(text):result.append({'text':text[pos:]})
    return result

def extract_text(path):
    title=path.stem;blocks=[];warnings=[];is_md=path.suffix.lower()=='.md'
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if not line.strip():continue
        line=line.strip()
        h=re.match(r'^(#{1,6})\s+(.+)',line) if is_md else None
        if h and len(h[1])==1 and not blocks:
            title=h[2];continue
        if h:blocks.append({'type':'heading','level':min(len(h[1]),3),'runs':inline_markdown(h[2])});continue
        image=re.fullmatch(r'!\[([^\]]*)\]\((.+)\)',line) if is_md else None
        if image:
            src=image[2]
            if urlparse(src).scheme in ('http','https'):raise ValueError('请先将远程稿件图片下载为本地文件：'+src)
            f=(path.parent/src).resolve()
            if not f.is_file():raise ValueError('稿件图片不存在：'+str(f))
            blocks.append({'type':'image','src':str(f),'alt':image[1]});continue
        typ='paragraph';marker=None
        if is_md and line.startswith('> '):typ='quote';line=line[2:]
        elif is_md:
            match=re.match(r'^(\d+[.)]|[-*+])\s+(.+)',line)
            if match:typ='list_item';marker=match[1];line=match[2]
        if re.match(r'^(图文|文字|图片|摄影|撰稿|供稿|文案|编辑|美编|责编|主编|审核|审校|校对|排版|设计|策划|统筹|来源)\s*[|｜：:]',line):typ='credit'
        block={'type':typ,'runs':inline_markdown(line) if is_md else [{'text':line}]}
        if marker:block['marker']=marker
        blocks.append(block)
    return title,blocks,warnings

def extract_docx(path, media_dir):
    from docx import Document
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph
    from docx.text.run import Run
    doc=Document(str(path));warnings=[];title=path.stem;blocks=[];media_dir.mkdir(parents=True,exist_ok=True)
    if doc.element.xpath('.//w:ins | .//w:del'):
        raise ValueError('检测到修订，请确认最终稿并接受/拒绝修订后再转换')
    if doc.element.xpath('.//m:oMath | .//m:oMathPara'):
        raise ValueError('检测到Word公式，请先转换为清晰图片或等价文本并核对')
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    try:
        numroot=doc.part.part_related_by(RT.NUMBERING).element
    except KeyError:
        numroot=None
    counters={};media_issues=0;handled_textboxes=0
    def numbering(p):
        pp=p._p.pPr
        props=pp.find(qn('w:numPr')) if pp is not None else None
        if props is None and p.style is not None:
            st=p.style.element.find(qn('w:pPr'));props=st.find(qn('w:numPr')) if st is not None else None
        if props is None:return None
        n=props.find(qn('w:numId'));lvl=props.find(qn('w:ilvl'))
        if n is None:return None
        numid=n.get(qn('w:val'));level=int(lvl.get(qn('w:val'))) if lvl is not None else 0
        if numid=='0':return None
        if numroot is None:raise ValueError('Word列表编号定义缺失')
        num=next((x for x in numroot if x.tag==qn('w:num') and x.get(qn('w:numId'))==numid),None)
        if num is None:raise ValueError('Word列表编号定义缺失')
        absid=num.find(qn('w:abstractNumId')).get(qn('w:val'))
        abstract=next(x for x in numroot if x.tag==qn('w:abstractNum') and x.get(qn('w:abstractNumId'))==absid)
        lv=next((x for x in abstract if x.tag==qn('w:lvl') and x.get(qn('w:ilvl'))==str(level)),None)
        if lv is None:raise ValueError('不支持的Word列表级别')
        fmt=lv.find(qn('w:numFmt')).get(qn('w:val'));pattern=lv.find(qn('w:lvlText')).get(qn('w:val'))
        start=lv.find(qn('w:start'));start=int(start.get(qn('w:val'))) if start is not None else 1
        for ov in num.findall(qn('w:lvlOverride')):
            st=ov.find(qn('w:startOverride'))
            if ov.get(qn('w:ilvl'))==str(level) and st is not None:start=int(st.get(qn('w:val')))
        if fmt=='bullet':return ('•',level)
        if fmt not in ('decimal','lowerLetter','upperLetter'):
            raise ValueError('暂不自动转换此Word编号格式：'+fmt+'；请保留可见编号后再转换')
        nums=counters.setdefault(numid,{})
        nums[level]=nums.get(level,start-1)+1
        for k in list(nums):
            if k>level:del nums[k]
        def repl(m):
            v=nums.get(int(m[1])-1,1)
            if fmt=='lowerLetter':return chr(96+v) if v<=26 else str(v)
            if fmt=='upperLetter':return chr(64+v) if v<=26 else str(v)
            return str(v)
        return (re.sub(r'%(\d+)',repl,pattern),level)
    def paragraphs(el):
        p=Paragraph(el,doc);name=p.style.name if p.style else '';heading=re.match(r'(?:Heading|标题)\s*([1-6])',name,re.I)
        typ='heading' if heading else ('caption' if name.lower() in ('caption','题注') else 'paragraph')
        out=[];runs=[]
        def flush():
            nonlocal runs
            if runs and any(r.get('text') for r in runs):
                block={'type':typ,'runs':runs}
                if heading:block['level']=min(int(heading[1])+1,3)
                out.append(block)
            runs=[]
        def read_run(el,href=None):
            nonlocal media_issues,handled_textboxes
            run=Run(el,p);attrs={}
            for prop in ('bold','italic','underline'):
                val=getattr(run,prop)
                if val is None and run.style is not None:val=getattr(run.style.font,prop)
                if val is None and p.style is not None:val=getattr(p.style.font,prop)
                if val:attrs[prop]=True
            if href:attrs['href']=safe_href(href)
            for child in el:
                tag=child.tag.rsplit('}',1)[-1]
                if tag=='t':runs.append({'text':child.text or '',**attrs})
                elif tag=='tab':runs.append({'text':'\t',**attrs})
                elif tag in ('br','cr'):runs.append({'text':'\n',**attrs})
                elif tag in ('drawing','pict','object'):
                    flush();found=False
                    # Word stores its horizontal rule as a VML rect, not a bitmap.
                    is_rule=any(n.get('{urn:schemas-microsoft-com:office:office}hr','').lower() in ('t','true','1') for n in child.iter()) and not any(n.get(qn('r:embed')) or n.get(qn('r:id')) for n in child.iter()) and not list(child.iter(qn('w:t')))
                    if is_rule:
                        out.append({'type':'divider'})
                        if 'Word分隔横线已转换为简洁分隔装饰。' not in warnings:warnings.append('Word分隔横线已转换为简洁分隔装饰。')
                        continue
                    def unresolved(reason):
                        nonlocal media_issues
                        media_issues+=1
                        out.append({'type':'unresolved_media','id':f'graphic-{media_issues}','label':f'待处理图形 {media_issues}','reason':reason,'context':p.text[:160]})
                        warnings.append(f'图形{media_issues}暂不能显示，已保留原位置，可补充图片或确认略过。')
                    for img in child.iter():
                        rid=img.get(qn('r:embed')) or (img.get(qn('r:id')) if img.tag.endswith('imagedata') else None)
                        if not rid:continue
                        part=doc.part.related_parts.get(rid)
                        if part is None:unresolved('Word图片关系缺失：'+rid);found=True;continue
                        ext=Path(str(part.partname)).suffix.lower()
                        if ext not in ('.png','.jpg','.jpeg','.gif','.webp','.avif','.svg'):
                            unresolved('图片格式'+ext+'暂不支持，可补充PNG或JPEG替换。');found=True;continue
                        f=media_dir/(hashlib.sha256(part.blob).hexdigest()[:20]+ext);f.write_bytes(part.blob)
                        out.append({'type':'image','src':str(f.resolve()),'alt':''});found=True
                    textboxes=list(child.iter(qn('w:txbxContent')))
                    for textbox in textboxes:
                        handled_textboxes+=1
                        for para in textbox.findall(qn('w:p')):out.extend(paragraphs(para)[0])
                    if textboxes:
                        found=True
                        if '文本框文字已提取为顺序段落，需核对其位置。' not in warnings:warnings.append('文本框文字已提取为顺序段落，需核对其位置。')
                    if not found:unresolved('此Word绘图暂不能自动渲染。')
                elif tag=='sym':raise ValueError('检测到特殊符号，请先转换为可见文本')
        for child in el:
            tag=child.tag.rsplit('}',1)[-1]
            if tag=='r':read_run(child)
            elif tag=='hyperlink':
                rid=child.get(qn('r:id'));rel=doc.part.rels.get(rid)
                href=rel.target_ref if rel else None
                for rr in child.findall(qn('w:r')):read_run(rr,href)
            elif tag not in ('pPr','bookmarkStart','bookmarkEnd','proofErr'):
                if list(child.iter(qn('w:t'))):raise ValueError('检测到修订/域/控件内文本，请先接受修订并转换为普通文本，避免遗漏')
        flush();n=numbering(p)
        if n:
            first=next((x for x in out if 'runs' in x),None)
            if first:
                first['type']='list_item';first['marker']=n[0];first['level']=n[1]
        for block in out:
            text=runs_text(block.get('runs',[]))
            if re.match(r'^(图文|文字|图片|摄影|撰稿|供稿|文案|编辑|美编|责编|主编|审核|审校|校对|排版|设计|策划|统筹|来源)\s*[|｜：:]',text):block['type']='credit'
        if name.lower() in ('title','标题') and not any(x['type']=='image' for x in out):
            return out,True
        return out,False
    def table(el):
        rows=[];above={}
        for tr in el.findall(qn('w:tr')):
            row=[];column=0;current={}
            for tc in tr.findall(qn('w:tc')):
                pr=tc.find(qn('w:tcPr'));span=pr.find(qn('w:gridSpan')) if pr is not None else None
                span=int(span.get(qn('w:val'))) if span is not None else 1
                merge=pr.find(qn('w:vMerge')) if pr is not None else None
                if merge is not None and merge.get(qn('w:val'),'continue')=='continue':
                    if column not in above:raise ValueError('表格合并关系不完整')
                    origin=above[column];origin['rowspan']=origin.get('rowspan',1)+1
                    for k in range(column,column+span):current[k]=origin
                    column+=span;continue
                contents=[]
                for sub in tc:
                    if sub.tag==qn('w:p'):contents.extend(paragraphs(sub)[0])
                    elif sub.tag==qn('w:tbl'):contents.append(table(sub))
                cell={'blocks':contents,'colspan':span,'rowspan':1};row.append(cell)
                for k in range(column,column+span):current[k]=cell
                column+=span
            above=current;rows.append(row)
        return {'type':'table','rows':rows}
    for child in doc.element.body:
        if child.tag==qn('w:p'):
            chunks,is_title=paragraphs(child)
            if is_title and not blocks and title==path.stem:title=blocks_text(chunks)
            else:blocks.extend(chunks)
        elif child.tag==qn('w:tbl'):blocks.append(table(child))
        elif child.tag!=qn('w:sectPr') and list(child.iter(qn('w:t'))):raise ValueError('检测到不支持的正文容器，请转换为普通段落')
    if doc.element.xpath('.//wp:anchor'):warnings.append('浮动图片按锚点位置插入，需对照Word核对图文顺序。')
    if len(doc.element.xpath('.//w:txbxContent'))>handled_textboxes:raise ValueError('检测到未能读取的文本框；请先转换为普通段落，避免文字遗漏')
    if title==path.stem:warnings.append('未检测到Word“标题”样式：请在article.json中确认主标题；未擅自删除首段。')
    if doc.element.xpath('.//w:footnoteReference | .//w:endnoteReference'):
        raise ValueError('检测到脚注或尾注，请先将注释并入正文后转换')
    return title,blocks,warnings

def extract(path, output):
    path=Path(path).resolve();output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix.lower()=='.docx':title,blocks,warnings=extract_docx(path,output.parent/'source-images')
    elif path.suffix.lower() in ('.md','.txt'):title,blocks,warnings=extract_text(path)
    else:raise ValueError('支持 .docx、.md、.txt；旧版 .doc 请先另存为 .docx')
    route=classify(title,blocks_text(blocks))
    inferred_title=any('未检测到Word' in w for w in warnings) if path.suffix.lower()=='.docx' else not (path.suffix.lower()=='.md' and re.match(r'^#\s+',path.read_text(encoding='utf-8-sig').lstrip()))
    article={'version':1,'title':title,'source':str(path),'column':route['column'],'subtype':route['subtype'],'classification':route,'classification_reviewed':False,'blocks':blocks,'warnings':warnings,'source_title_mode':'filename' if inferred_title else 'document','source_filename_title':path.stem}
    article['source_text']=('' if inferred_title else title+'\n')+blocks_text(blocks)
    dump(output,article);return article

def render(article_path, output, theme_name=None, image_map=None, include_title=False):
    from bs4 import BeautifulSoup
    path=Path(article_path).resolve();a=json.loads(path.read_text(encoding='utf-8'));out=Path(output).resolve();out.mkdir(parents=True,exist_ok=True)
    column=a.get('column')
    if column not in COLUMNS:raise ValueError('请先确认栏目；有效栏目：'+', '.join(COLUMNS))
    theme_name=theme_name or a.get('theme') or COLUMNS[column]['theme']
    if theme_name not in THEMES:raise ValueError('未知主题：'+str(theme_name))
    theme={**THEMES[theme_name],**a.get('style_overrides',{})}
    for key in ('primary','light','accent','text'):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',str(theme[key])):raise ValueError('颜色必须为六位十六进制：'+key)
    for key,lo,hi in [('font_size',12,22),('line_height',1.2,2.5),('letter_spacing',0,3)]:
        theme[key]=float(theme[key])
        if not lo<=theme[key]<=hi:raise ValueError('样式参数超出合理范围：'+key)
    inferred_unchanged=a.get('source_title_mode')=='filename' and a['title']==a.get('source_filename_title')
    current=('' if inferred_unchanged else a['title']+'\n')+blocks_text(a['blocks'])
    source_changed=compact(a.get('source_text',current))!=compact(current)
    if source_changed and not a.get('user_authorized_text_changes',False):raise ValueError('内容与提取稿不同：请核对遗漏；只有用户要求改文时才可标记user_authorized_text_changes')
    mapped=json.loads(Path(image_map).read_text(encoding='utf-8')) if image_map else {}
    manifest=[];warnings=list(a.get('warnings',[]));images_dir=out/'images';images_dir.mkdir(exist_ok=True)
    def image(src,role='content',alt='',width=None):
        f=Path(src)
        if not f.is_absolute():f=(path.parent/f).resolve()
        if not f.is_file():raise ValueError('图片不存在：'+str(f))
        if f.suffix.lower() not in ('.png','.jpg','.jpeg','.gif','.webp','.avif','.svg'):raise ValueError('不支持的图片格式：'+f.suffix)
        local='images/'+hashlib.sha256(f.read_bytes()).hexdigest()[:20]+f.suffix.lower()
        dest=out/local
        if f.resolve()!=dest.resolve():shutil.copy2(f,dest)
        url=mapped.get(local)
        if url:
            parsed=urlparse(url)
            if parsed.scheme!='https' or parsed.hostname not in ('mmbiz.qpic.cn','mmbiz.qlogo.cn'):
                raise ValueError('请使用微信上传返回的HTTPS图片地址：'+str(url))
        if not any(m['local']==local for m in manifest):manifest.append({'local':local,'source':str(f),'role':role,'wechat_url':url})
        img_style='display:block;width:100%;max-width:100%;height:auto;margin:0 auto;border:0;'
        if width:img_style+=f'max-width:{int(width)}px;'
        return '<img src="'+html.escape(local,quote=True)+'" alt="'+html.escape(alt,quote=True)+'" style="'+img_style+'" />'
    def runs(rr):
        parts=[]
        for r in rr:
            text=html.escape(str(r.get('text',''))).replace('\n','<br />').replace('\t','&#8195;')
            if r.get('bold'):text='<strong style="font-weight:700;">'+text+'</strong>'
            if r.get('italic'):text='<em>'+text+'</em>'
            if r.get('underline'):text='<span style="text-decoration:underline;">'+text+'</span>'
            if r.get('href'):text='<a href="'+html.escape(safe_href(r['href']),quote=True)+'" style="color:'+theme['primary']+';text-decoration:underline;">'+text+'</a>'
            parts.append(text)
        return ''.join(parts)
    count=0
    def block(b):
        nonlocal count
        typ=b['type'];text=runs(b.get('runs',[]));primary=theme['primary'];light=theme['light'];accent=theme['accent']
        if typ=='divider':return f'<section data-generated="true" style="width:32px;margin:18px auto;border-top:2px solid {accent};"></section>'
        if typ=='unresolved_media':
            return '<section data-generated="true" style="margin:18px 0;padding:18px;border:1px dashed #c58b42;background:#fff9ef;color:#8b622e;text-align:center;">'+html.escape(b.get('label','待处理图形'))+'<br /><span style="font-size:12px;">'+html.escape(b.get('reason','请补充图片'))+'</span></section>'
        if typ=='group':
            children=''.join(block(x) for x in b['blocks'])
            variant=b.get('variant','section')
            bg=light if variant=='summary' else '#ffffff'
            border=theme.get('group_border')
            if border:
                if not re.fullmatch(r'#[0-9a-fA-F]{6}',border):raise ValueError('分区边框颜色须为六位色值')
                padding=int(theme.get('summary_padding',22) if variant=='summary' else theme.get('group_padding',15))
                if not 0<=padding<=48:raise ValueError('框内留白须为0–48px')
                rounding='border-top-left-radius:20px;border-bottom-right-radius:20px;' if variant=='intro' else ''
                return f'<section data-layout-group="{html.escape(variant,quote=True)}" style="box-sizing:border-box;width:100%;margin:0 0 26px;padding:{padding}px;border:1px solid {border};{rounding}background:{bg};">{children}</section>'
            padding=int(theme.get('summary_padding',26) if variant=='summary' else theme.get('group_padding',22))
            if not 0<=padding<=48:raise ValueError('组内留白须为0–48px')
            return f'<section style="box-sizing:border-box;width:100%;margin:0 0 26px;padding:{padding}px;background:{bg};">{children}</section>'
        if typ=='section_label':
            label=str(b['label'])
            if label not in a.get('layout_additions',[]):raise ValueError('新增分节标题必须记入layout_additions')
            return '<section data-generated="true">'+block({'type':'heading','level':2,'runs':[{'text':label}]})+'</section>'
        if typ=='end_mark':
            return f'<section data-generated="true" style="margin:26px 0 18px;text-align:center;font-size:13px;letter-spacing:3px;font-weight:700;color:{primary};">END</section>'
        if typ=='speaker':
            return f'<p style="margin:20px 0 10px;font-size:14px;font-weight:700;color:{primary};text-indent:0;">{text}</p>'
        if typ=='heading':
            level=b.get('level',2)
            if level>=3:return f'<section style="margin:22px 0 12px;font-size:16px;font-weight:700;color:{primary};">{text}</section>'
            count+=1
            if theme['heading']=='section-label':
                ornaments=f'<span data-generated="true" style="display:inline-block;width:7px;height:7px;margin:0 9px;background:{accent};vertical-align:middle;"></span>'
                return f'<section style="text-align:center;margin:28px 0 16px;font-size:16px;font-weight:700;">{ornaments}<span style="display:inline-block;padding:6px 18px;background:{primary};color:#ffffff;">{text}</span>{ornaments}</section>'
            if theme['heading']=='number':
                label='<span data-generated="true" style="display:inline-block;padding:3px 9px;margin-right:10px;border-radius:20px;background:'+accent+';color:#ffffff;">'+f'{count:02d}'+'</span>'
                return f'<section style="margin:28px 0 16px;font-size:16px;font-weight:700;color:{primary};">{label}{text}</section>'
            return f'<section style="margin:28px 0 16px;padding:7px 12px;background:{light};color:{primary};font-size:16px;font-weight:700;">{text}</section>'
        if typ=='component':
            key=b['component']
            if key not in COMPONENTS:raise ValueError('未知品牌组件：'+key)
            meta=COMPONENTS[key]
            # Brand asset roles and provenance are checked by brand_layout.py.
            source=b.get('src') or str(SKILL_DIR/meta['file'])
            bg=b.get('background') or meta.get('background','transparent')
            if bg!='transparent' and not re.fullmatch(r'#[0-9a-fA-F]{6}',bg):raise ValueError('组件背景须为transparent或六位色值')
            img=image(source,'component:'+key,meta['label'],b.get('width',meta['display_width']))
            caption='<p style="text-align:center;font-size:12px;color:#858585;margin:10px 0 0;">'+html.escape(b['caption'])+'</p>' if b.get('caption') else ''
            padding='0' if b.get('edge_aligned') else '12px'
            return '<section style="margin:20px 0;padding:'+padding+';background:'+bg+';">'+img+caption+'</section>'
        if typ=='image':
            img=image(b['src'],b.get('role','content'),b.get('alt',''),b.get('width'))
            caption='<section style="margin-top:10px;text-align:center;font-size:12px;color:#858585;">'+html.escape(b['caption'])+'</section>' if b.get('caption') else ''
            percent=float(b.get('width_percent',90))
            if not 10<=percent<=100:raise ValueError('图片宽度百分比须在10–100之间')
            return f'<section style="margin:16px auto;width:{percent:g}%;">'+img+caption+'</section>'
        if typ=='gallery':
            if b.get('mode')=='row':
                photos=b['images']
                if not 2<=len(photos)<=3:raise ValueError('左右图组每行需2–3张独立图片，请按语义分行')
                percent=float(b.get('width_percent',90))
                if not 10<=percent<=100:raise ValueError('图组宽度百分比须在10–100之间')
                gap=float(b.get('gap_px',8))
                if not 0<=gap<=32:raise ValueError('图间距须为0–32px')
                cells=[]
                for index,photo in enumerate(photos):
                    img=image(photo['src'],photo.get('role','content'),photo.get('alt',''))
                    caption='<section style="margin-top:10px;font-size:12px;line-height:1.6;letter-spacing:1px;text-align:center;color:#858585;">'+html.escape(photo['caption'])+'</section>' if photo.get('caption') else ''
                    if index and gap:
                        cells.append(f'<td data-image-gap="true" aria-hidden="true" style="width:{gap:g}px;padding:0;border:0;font-size:0;line-height:0;"></td>')
                    cells.append(f'<td style="padding:0;border:0;vertical-align:top;">{img}{caption}</td>')
                return f'<table data-image-layout="row" cellpadding="0" cellspacing="0" style="border:0;border-collapse:collapse;border-spacing:0;table-layout:fixed;width:{percent:g}%;margin:16px auto;padding:0;"><tbody><tr>'+''.join(cells)+'</tr></tbody></table>'
            # Other layouts keep each source image independent.
            if b.get('mode','stack')=='scroll':
                warnings.append('滑动图集需在秀米导入、保存后用微信手机预览验证。')
                slides=''.join('<section style="display:inline-block;width:100%;vertical-align:top;white-space:normal;">'+block({'type':'image',**im})+'</section>' for im in b['images'])
                return '<section style="width:100%;overflow-x:auto;white-space:nowrap;">'+slides+'</section><p data-generated="true" style="margin:10px 0;text-align:center;font-size:12px;color:#858585;">左右滑动查看更多</p>'
            return ''.join(block({'type':'image',**im}).replace('margin:16px auto','margin:10px auto') for im in b['images'])
        if typ=='table':
            rows=[]
            widths=b.get('column_widths',[])
            if widths and (any(float(w)<=0 for w in widths) or abs(sum(float(w) for w in widths)-100)>0.1):raise ValueError('表格列宽须为合计100的正数百分比')
            for row_index,row in enumerate(b['rows']):
                cells=[]
                for cell_index,c in enumerate(row):
                    content=''.join(block(x) for x in c['blocks'])
                    if cell_index in b.get('nowrap_name_columns',[]) and row_index>=int(b.get('header_rows',0)):
                        chunks=[]
                        for paragraph in c['blocks']:
                            if paragraph['type']!='paragraph':chunks.append(block(paragraph));continue
                            pieces=[]
                            for run in paragraph.get('runs',[]):
                                for part in re.split('(、)',run.get('text','')):
                                    rendered=runs([{**run,'text':part}])
                                    if re.fullmatch(r'[\u4e00-\u9fff]{2,4}',part):rendered='<span style="white-space:nowrap;display:inline-block;">'+rendered+'</span>'
                                    pieces.append(rendered)
                            name_markup=''.join(pieces).replace('</span>、','、</span>')
                            chunks.append('<p style="margin:0;text-indent:0;">'+name_markup+'</p>')
                        content=''.join(chunks)
                    content=content.replace('text-indent:2em','text-indent:0').replace('margin:0 0 16px','margin:0')
                    header=row_index<int(b.get('header_rows',0))
                    extra=f'background:{light};color:{primary};' if header else 'background:#ffffff;'
                    if widths and cell_index<len(widths):extra+=f'width:{float(widths[cell_index]):g}%;'
                    cells.append(f'<td colspan="{int(c.get("colspan",1))}" rowspan="{int(c.get("rowspan",1))}" style="border:1px solid #d9e0ea;padding:9px 5px;vertical-align:middle;word-break:break-word;{extra}">{content}</td>')
                rows.append('<tr>'+''.join(cells)+'</tr>')
            return '<table style="border-collapse:collapse;width:100%;table-layout:fixed;margin:18px 0;font-size:13px;letter-spacing:0;line-height:1.6;">'+''.join(rows)+'</table>'
        if typ=='intro':return f'<section style="padding:18px 16px;margin:16px 0 24px;background:{light};border-radius:3px;text-align:justify;">{text}</section>'
        if typ=='quote':return f'<section style="padding:12px 16px;margin:18px 0;border-left:3px solid {primary};background:{light};">{text}</section>'
        if typ=='caption':return '<p style="margin:6px 0 18px;font-size:12px;color:#858585;text-align:center;">'+text+'</p>'
        if typ=='credit':return '<p style="margin:0;padding:5px 0;background:transparent;text-align:center;font-size:12px;color:#858585;">'+text+'</p>'
        if typ=='list_item':
            marker=html.escape(str(b.get('marker','•')))
            level=max(0,min(5,int(b.get('level',0))))
            return f'<p style="margin:8px 0;padding-left:{level*12}px;text-align:justify;"><span data-generated="true">{marker} </span>{text}</p>'
        if typ=='paragraph':
            indent='0' if b.get('indent',True) is False else '2em'
            return f'<p style="margin:0 0 16px;text-align:justify;text-indent:{indent};overflow-wrap:break-word;">{text}</p>'
        raise ValueError('未知内容模块：'+str(typ))
    visible_blocks,credit_changes=display_blocks(a['blocks'])
    body=''.join(block(b) for b in visible_blocks)
    heading='<h1 style="font-size:22px;line-height:1.4;margin:0 0 24px;">'+html.escape(a['title'])+'</h1>' if include_title else ''
    fragment=f'<section style="box-sizing:border-box;padding:0 10px;font-size:{theme["font_size"]:g}px;line-height:{theme["line_height"]:g};letter-spacing:{theme["letter_spacing"]:g}px;color:{theme["text"]};">'+heading+body+'</section>'
    if theme.get('page_background'):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',theme['page_background']):raise ValueError('背景色必须为六位色值')
        fragment=fragment.replace('padding:0 10px;',f'padding:16px 10px;background:{theme["page_background"]};',1)
    parsed=BeautifulSoup(fragment,'html.parser')
    for generated in parsed.select('[data-generated]'):generated.decompose()
    expected=(a['title'] if include_title else '')+blocks_text(visible_blocks)
    if compact(parsed.get_text())!=compact(expected):raise ValueError('渲染后的正文文本与结构稿不同；已停止交付')
    imported=fragment
    for entry in manifest:
        if entry['wechat_url']:imported=imported.replace('src="'+entry['local']+'"','src="'+html.escape(entry['wechat_url'],quote=True)+'"')
    (out/'article.html').write_text(imported,encoding='utf-8')
    preview='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'''+html.escape(a['title'])+'''</title><style>body{margin:0;background:#edf1f5;color:#273952;font-family:Arial,'Microsoft YaHei',sans-serif}.tools{max-width:680px;margin:20px auto;padding:0 16px;font-size:14px;line-height:1.8}button{background:#35558a;color:white;border:0;padding:9px 18px;border-radius:5px;cursor:pointer}article{max-width:430px;box-sizing:border-box;margin:20px auto;padding:24px 20px;background:white;box-shadow:0 8px 24px #25385012}.title{max-width:430px;margin:20px auto;font-size:20px;line-height:1.5;padding:0 20px;box-sizing:border-box}@media(max-width:480px){article{margin:0;box-shadow:none;width:100%}}</style><div class="tools"><strong>'''+html.escape(column+' · '+a.get('subtype',''))+'''</strong><br>这是本地排版预览。主标题与摘要在秀米核对；请用插件选择article.xiumi.json导入正文和配图。<br><button onclick="copyBody()">复制排版正文</button> <span id="status"></span></div><h1 class="title">'''+html.escape(a['title'])+'''</h1><article id="article">'''+fragment+'''</article><script>function copyBody(){const el=document.getElementById('article');const range=document.createRange();range.selectNodeContents(el);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);let ok=false;try{ok=document.execCommand('copy')}catch(e){}document.getElementById('status').textContent=ok?'已复制，请在编辑器粘贴并检查图片。':'请手动复制选中的正文。';if(ok)selection.removeAllRanges();}</script></html>'''
    (out/'preview.html').write_text(preview,encoding='utf-8')
    if not a.get('classification_reviewed'):warnings.append('栏目为自动建议，尚需结合正文确认。')
    missing=[m['local'] for m in manifest if not m['wechat_url']]
    if missing:warnings.append('图片仍使用本地路径：交由编辑器接收/上传后才能成为公众号可发布稿。')
    checks={'column':column,'subtype':a.get('subtype'),'theme':theme_name,'classification_reviewed':a.get('classification_reviewed',False),'text_preserved':True,'source_text_changed_with_authorization':source_changed,'image_files':len(manifest),'images_pending_wechat_upload':missing,'legacy_import_verified':False,'warnings':list(dict.fromkeys(warnings))}
    checks['credit_format_changes']=credit_changes
    checks['layout_additions']=a.get('layout_additions',[])
    def pending_graphics(blocks):
        pending=[]
        for item in blocks:
            if item['type']=='unresolved_media':pending.append({k:item.get(k,'') for k in ['id','label','reason','context']})
            elif item['type']=='group':pending.extend(pending_graphics(item['blocks']))
            elif item['type']=='table':
                for row in item['rows']:
                    for cell in row:pending.extend(pending_graphics(cell['blocks']))
        return pending
    checks['unresolved_media']=pending_graphics(a['blocks']);checks['can_export']=not checks['unresolved_media']
    portable=json.loads(json.dumps(a))
    lookup={m['source']:m['local'] for m in manifest}
    def localize(blocks):
        for b in blocks:
            if b['type']=='group':localize(b['blocks'])
            elif b['type']=='component':
                f=Path(b.get('src') or str(SKILL_DIR/COMPONENTS[b['component']]['file']))
                if not f.is_absolute():f=(path.parent/f).resolve()
                b['src']=lookup[str(f)]
            elif b['type']=='image':
                f=Path(b['src']);f=f if f.is_absolute() else (path.parent/f).resolve()
                b['src']=lookup[str(f)]
            elif b['type']=='gallery':
                for im in b['images']:
                    f=Path(im['src']);f=f if f.is_absolute() else (path.parent/f).resolve()
                    im['src']=lookup[str(f)]
            elif b['type']=='table':
                for row in b['rows']:
                    for cell in row:localize(cell['blocks'])
    localize(portable['blocks'])
    dump(out/'checks.json',checks);dump(out/'image-manifest.json',manifest);dump(out/'image-map.template.json',{m['local']:m['wechat_url'] or '' for m in manifest});dump(out/'article.json',portable)
    publication={'title':a['title'],'summary':a.get('summary'),'cover':a.get('cover'),'cover_ratios':{'primary':'2.35:1','secondary':'1:1'},'target':'秀米插件JSON导入','import_tested':False}
    dump(out/'publication.json',publication)
    if not a.get('summary'):
        checks['warnings'].append('缺少摘要：请根据原稿拟定并核对，在公众号摘要栏填写。');dump(out/'checks.json',checks)
    packet_path=out/'article.xiumi.json'
    if packet_path.exists():packet_path.unlink()
    checks['xiumi_package_generated']=False;checks['xiumi_import_verified']=False
    if checks['can_export']:
        try:
            import importlib.util
            spec=importlib.util.spec_from_file_location('brand_xiumi_export',SKILL_DIR/'scripts/export_xiumi.py')
            exporter=importlib.util.module_from_spec(spec);spec.loader.exec_module(exporter)
            packet=exporter.export(out/'article.html',source_html=fragment)
            checks['xiumi_package_generated']=True;checks['xiumi_embedded_images']=len(packet['assets'])
            checks['warnings']=[w for w in checks['warnings'] if not w.startswith('图片仍使用本地路径')]
            checks['warnings'].append('秀米包已内嵌配图，插件将在导入时上传；备用HTML仍使用本地images目录。')
        except ValueError as e:checks['warnings'].append('秀米导入包未生成：'+str(e))
    dump(out/'checks.json',checks)
    (out/'导入说明.txt').write_text('推荐流程：Word与可选图片包交给AI → 品牌排版skill → article.xiumi.json → 秀米插件。无需启动工作台。\n\narticle.xiumi.json：给“秀米导入插件”选择，内含正文、模块和配图文件内容。\npreview.html：本地预览，article.html与images是备用HTML和配图。\npublication.json：主标题、摘要等信息，在秀米相应栏目核对填写。\n\n在秀米新建空白图文，打开插件，选择article.xiumi.json，点击导入。插件会尝试先上传图片，再写入正文；完成后在秀米手动保存，重新打开后用插件核验。\n真实账号权限、图片上传和服务端保存仍须实测，不能仅凭本地或模拟测试认定完成。\n',encoding='utf-8')
    return checks

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='cmd',required=True)
    e=sub.add_parser('extract');e.add_argument('source');e.add_argument('--out',required=True)
    r=sub.add_parser('render');r.add_argument('article');r.add_argument('--out',required=True);r.add_argument('--theme',choices=THEMES);r.add_argument('--image-map');r.add_argument('--include-title',action='store_true')
    c=sub.add_parser('classify');c.add_argument('title');c.add_argument('--source-column')
    args=p.parse_args()
    if args.cmd=='extract':result=extract(args.source,args.out);print(json.dumps({'title':result['title'],'classification':result['classification'],'blocks':len(result['blocks']),'warnings':result['warnings']},ensure_ascii=False))
    elif args.cmd=='render':print(json.dumps(render(args.article,args.out,args.theme,args.image_map,args.include_title),ensure_ascii=False))
    else:print(json.dumps(classify(args.title,source_column=args.source_column),ensure_ascii=False))

if __name__=='__main__':
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    try:main()
    except (ValueError,FileNotFoundError) as e:
        print('ERROR: '+str(e),file=sys.stderr);sys.exit(2)

"""Package skill-generated HTML and images for the standalone Xiumi extension."""
from pathlib import Path
from copy import deepcopy
from urllib.parse import urlparse,unquote
import argparse,base64,hashlib,json,mimetypes,re,io
from datetime import datetime,timezone
from bs4 import BeautifulSoup,Tag
from PIL import Image,UnidentifiedImageError

PAGE_KEYS={'font-family','font-size','line-height','letter-spacing','color','text-align','text-indent','padding-top','padding-right','padding-bottom','padding-left','background-color','background-image','background-size','background-position','background-repeat'}
IMAGE_TYPES={'image/png','image/jpeg','image/gif','image/webp','image/avif'}

def normalize_image(data):
    """The extension's File MIME must match bytes, not a misleading filename."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            actual=image.format
            if actual in ('PNG','JPEG','GIF'):
                image.verify()
                return data,{'PNG':'image/png','JPEG':'image/jpeg','GIF':'image/gif'}[actual]
            if actual not in ('WEBP','AVIF'):raise ValueError('该图片格式不能直接导入秀米，请转为PNG或JPEG')
            if getattr(image,'is_animated',False):raise ValueError('动态WebP/AVIF请先转换为GIF，不能只保留第一帧')
            output=io.BytesIO();image.convert('RGBA').save(output,format='PNG')
            return output.getvalue(),'image/png'
    except (UnidentifiedImageError,OSError) as e:
        raise ValueError('图片数据无法识别或已损坏') from e

def declarations(raw):
    result={};start=0;quote=None;depth=0
    for i,ch in enumerate(raw+';'):
        if quote:
            if ch==quote:quote=None
        elif ch in ('"',"'"):quote=ch
        elif ch=='(':depth+=1
        elif ch==')':depth-=1
        elif ch==';' and depth==0:
            part=raw[start:i];start=i+1
            if ':' in part:
                key,value=part.split(':',1);result[key.strip().lower()]=value.strip()
    return result

def build_packet(html_path,checks_path=None,source_html=None):
    html_path=Path(html_path).resolve();folder=html_path.parent
    checks_path=Path(checks_path) if checks_path else folder/'checks.json'
    if checks_path.exists():
        checks=json.loads(checks_path.read_text(encoding='utf-8'))
        if checks.get('can_export') is False or checks.get('unresolved_media'):raise ValueError('仍有待处理图形，请补图或明确处理后再导出秀米包')
    doc=BeautifulSoup(source_html if source_html is not None else html_path.read_text(encoding='utf-8'),'html.parser')
    if doc.find(['script','iframe','object','embed','form','input','button','style','link','meta']):raise ValueError('请传入正文article.html，而不是带工具栏的预览网页')
    top=[n for n in doc.contents if isinstance(n,Tag)]
    if len(top)!=1:raise ValueError('正文必须有一个外层section容器')
    root=top[0];assets=[];by_source={};local_map={}
    def resource(src,kind='image'):
        if src.startswith('#'):return src
        if src in by_source:
            by_source[src]['occurrences']+=1;return 'opslion-asset://'+by_source[src]['id']
        if src.startswith('data:'):
            m=re.fullmatch(r'data:([^;]+);base64,([A-Za-z0-9+/=\s]+)',src)
            if not m or m[1] not in IMAGE_TYPES:raise ValueError('图片格式不受插件支持，需先转为PNG/JPEG')
            data=base64.b64decode(m[2],validate=False);value=src
        elif urlparse(src).scheme in ('http','https'):
            raise ValueError('请先下载远程图片到稿件目录，再打包；最终包不依赖外链可访问性')
        else:
            parsed=urlparse(src)
            if parsed.scheme:raise ValueError('不支持的图片路径：'+src)
            file=(folder/unquote(parsed.path)).resolve()
            if not file.is_relative_to(folder) or not file.is_file():raise ValueError('配图应位于导出目录内：'+src)
            mime=mimetypes.guess_type(file.name)[0]
            if mime not in IMAGE_TYPES:raise ValueError('请将图片转为PNG/JPEG后导出：'+file.name)
            data=file.read_bytes()
        data,mime=normalize_image(data)
        value='data:'+mime+';base64,'+base64.b64encode(data).decode()
        asset={'id':f'asset-{len(assets)+1}','src':value,'kind':kind,'occurrences':1,'status':'embedded','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
        assets.append(asset);by_source[src]=asset;local_map[src]=asset['id'];return 'opslion-asset://'+asset['id']
    for el in [root,*root.find_all(True)]:
        for key in el.attrs:
            if key.lower().startswith('on'):raise ValueError('正文中含脚本事件')
        if el.name=='a' and el.get('href') and urlparse(el['href']).scheme not in ('https','http'):raise ValueError('插件当前仅接受HTTP/HTTPS链接')
        if el.name=='img':el['src']=resource(el.get('src',''))
        elif el.name=='image':
            for attr in ('href','xlink:href'):
                if el.get(attr):el[attr]=resource(el[attr])
    for el in [root,*root.find_all(True)]:
        if el.get('style'):
            el['style']=re.sub(r'url\(\s*[\"\']?([^\"\')]+)[\"\']?\s*\)',lambda m:'url("'+resource(m[1],'background')+'")',el['style'])
    compact_html=str(root)
    css=declarations(root.get('style',''));page={k:v for k,v in css.items() if k in PAGE_KEYS}
    if 'padding' in css:
        vals=css['padding'].split()
        if not 1<=len(vals)<=4:raise ValueError('正文外层padding格式不支持')
        top_pad=vals[0];right=vals[1] if len(vals)>1 else top_pad;bottom=vals[2] if len(vals)>2 else top_pad;left=vals[3] if len(vals)>3 else right
        page.update(zip(['padding-top','padding-right','padding-bottom','padding-left'],[top_pad,right,bottom,left]))
    if 'background' in css:
        if re.fullmatch(r'#[0-9a-fA-F]{3,8}|rgba?\([^)]+\)|transparent|white',css['background']):page['background-color']=css['background']
        else:raise ValueError('复杂页背景请写为background-color/background-image等独立属性')
    shell_css={k:v for k,v in css.items() if k not in PAGE_KEYS and k not in ('padding','background')}
    shell_style=';'.join(f'{k}:{v}' for k,v in shell_css.items())
    children=[n for n in root.contents if isinstance(n,Tag) or str(n).strip()]
    modules=[]
    for i,node in enumerate(children):
        shell=deepcopy(root);shell.clear();shell['style']=shell_style;shell.append(deepcopy(node));modules.append({'id':f'module-{i+1}','html':str(shell)})
    if not modules:raise ValueError('没有可导出的正文模块')
    publication=folder/'publication.json';meta=json.loads(publication.read_text(encoding='utf-8')) if publication.exists() else {}
    return {'schema':'xiumi-bridge/v3','title':meta.get('title',html_path.stem),'html':compact_html,'plainText':root.get_text(' ',strip=True),'generatedAt':datetime.now(timezone.utc).isoformat(),'native':{'modules':modules,'pageFormat':{'styles':page}},'assets':assets,'assetSummary':{'embedded':len(assets),'embeddedBytes':sum(a['bytes'] for a in assets),'local':0},'publication':{'title':meta.get('title',''),'summary':meta.get('summary','')},'generator':'wechat-brand-layout/standalone'}

def export(html_path,output=None,checks_path=None,source_html=None):
    packet=build_packet(html_path,checks_path,source_html);output=Path(output) if output else Path(html_path).with_name('article.xiumi.json')
    output.write_text(json.dumps(packet,ensure_ascii=False,separators=(',',':')),encoding='utf-8');return packet

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('html');p.add_argument('--out');args=p.parse_args()
    result=export(args.html,args.out);print(json.dumps({'modules':len(result['native']['modules']),'embedded_images':len(result['assets']),'local_paths':0},ensure_ascii=False))

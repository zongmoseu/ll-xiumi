"""Local brand onboarding, reusable assets, and standalone Xiumi package rendering."""
import argparse
import hashlib
import io
import json
import os
import re
import sys
import zipfile
from copy import deepcopy
from pathlib import Path

from PIL import Image, UnidentifiedImageError
import layout_engine as engine

DEFAULT_THEME = deepcopy(engine.THEMES['brand-default'])
LEGACY_THEME = json.loads((engine.SKILL_DIR / 'assets/legacy-basic-theme.json').read_text(encoding='utf-8'))
ROLES = ('cover', 'logo', 'header', 'footer', 'divider', 'qr', 'other', 'reference')
BODY_ROLES = {'logo', 'header', 'footer', 'divider', 'qr'}
MAX_FILES = 500
MAX_BYTES = 512 * 1024 * 1024


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def default_data_dir():
    codex_dir = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
    return codex_dir / 'data' / 'wechat-brand-layout'


def load_profile(path):
    path = Path(path).resolve()
    value = read_json(path)
    if value.get('schema') != 'wechat-brand-profile/v1':
        raise ValueError('不是品牌排版配置文件')
    if not value.get('id') or not isinstance(value.get('assets'), list):
        raise ValueError('品牌配置缺少id或素材清单')
    ids = [asset['id'] for asset in value['assets']]
    if len(ids) != len(set(ids)):
        raise ValueError('素材ID重复，请先核对配置')
    return path, value


def init_profile(data_dir, profile_id, name):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', profile_id):
        raise ValueError('账号id需为1–64位小写字母、数字或连字符')
    if not name.strip():
        raise ValueError('需要账号名称')
    path = Path(data_dir).resolve() / 'profiles' / profile_id / 'profile.json'
    if path.exists():
        raise ValueError('账号配置已存在，请复用或选择新的id，不覆盖旧配置')
    write_json(path, {'schema': 'wechat-brand-profile/v1', 'id': profile_id,
                     'name': name.strip(), 'onboarding': {'status': 'pending'},
                     'theme': deepcopy(DEFAULT_THEME), 'assets': [], 'notes': []})
    return {'profile': str(path), 'status': 'pending'}


def list_profiles(data_dir):
    result = []
    for path in sorted((Path(data_dir) / 'profiles').glob('*/profile.json')):
        try:
            _, value = load_profile(path)
            result.append({'id': value['id'], 'name': value['name'],
                           'status': value['onboarding']['status'], 'profile': str(path.resolve())})
        except (ValueError, KeyError) as exc:
            result.append({'profile': str(path.resolve()), 'error': str(exc)})
    return result


def source_files(source):
    """Never extract archive paths or execute files; yield bounded original bytes."""
    source = Path(source).resolve()
    total = 0
    count = 0

    def check(size):
        nonlocal total, count
        total += size
        count += 1
        if count > MAX_FILES or total > MAX_BYTES:
            raise ValueError('单次素材包超过500个文件或512MB，请拆分后导入')

    if source.is_file() and source.suffix.lower() == '.zip':
        with zipfile.ZipFile(source) as archive:
            for item in archive.infolist():
                if item.is_dir():
                    continue
                check(item.file_size)
                yield item.filename, archive.read(item)
    elif source.is_dir():
        for path in sorted(source.rglob('*')):
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(source):
                check(path.stat().st_size)
                yield str(path.relative_to(source)), path.read_bytes()
    elif source.is_file():
        check(source.stat().st_size)
        yield source.name, source.read_bytes()
    else:
        raise ValueError('素材文件或目录不存在：' + str(source))


def describe_image(data):
    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt = image.format
            size = image.size
            animated = getattr(image, 'is_animated', False)
            image.verify()
        usable = fmt in ('PNG', 'JPEG', 'GIF') or (fmt in ('WEBP', 'AVIF') and not animated)
        return {'format': fmt, 'width': size[0], 'height': size[1],
                'animated': animated, 'renderable': usable}
    except (UnidentifiedImageError, OSError, ValueError):
        return {'renderable': False}


def import_assets(profile_path, source, kind='material'):
    path, value = load_profile(profile_path)
    # Stage all metadata first, so invalid archives don't partly update the profile.
    staged = list(source_files(source))
    known = {asset['sha256']: asset for asset in value['assets']}
    imported = []
    for name, data in staged:
        digest = hashlib.sha256(data).hexdigest()
        if digest in known:
            asset = known[digest]
            if name not in asset['source_names']:
                asset['source_names'].append(name)
            imported.append({'id': asset['id'], 'source': name, 'duplicate': True})
            continue
        image_info = describe_image(data)
        suffix = Path(name.replace('\\', '/')).suffix.lower()
        suffix = suffix if re.fullmatch(r'\.[a-z0-9]{1,10}', suffix) else '.bin'
        # Some supplied logos have misleading suffixes; retain bytes, label their actual format.
        suffix = {'PNG': '.png', 'JPEG': '.jpg', 'GIF': '.gif', 'WEBP': '.webp',
                  'AVIF': '.avif'}.get(image_info.get('format'), suffix)
        relative = 'assets/' + digest + suffix
        destination = path.parent / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        asset = {'id': 'a-' + digest[:20], 'sha256': digest, 'file': relative,
                 'source_names': [name], 'role': 'reference' if kind == 'reference' else 'other',
                 'auto_use': False, 'display_width': 1000, 'background': 'transparent',
                 **image_info}
        value['assets'].append(asset)
        known[digest] = asset
        imported.append(asset.copy())
    write_json(path, value)
    return {'profile': str(path), 'imported': imported}


def assign_asset(profile_path, asset_id, role, auto_use=None, width=None, background=None):
    path, value = load_profile(profile_path)
    asset = next((a for a in value['assets'] if a['id'] == asset_id), None)
    if asset is None:
        raise ValueError('素材ID不存在')
    if role not in ROLES:
        raise ValueError('未知素材角色')
    if role in BODY_ROLES and not asset['renderable']:
        raise ValueError('素材不能直接渲染，请先转成可用PNG/JPEG/GIF再导入')
    automatic = auto_use if auto_use is not None else asset.get('auto_use', False)
    if automatic and role not in ('header', 'footer'):
        raise ValueError('仅正文开头header与尾图footer可自动插入；请使用--manual-use')
    if width is not None and not 16 <= width <= 2000:
        raise ValueError('素材宽度需为16–2000像素')
    if background is not None and background != 'transparent' and not re.fullmatch(r'#[0-9a-fA-F]{6}', background):
        raise ValueError('背景应为transparent或六位十六进制颜色')
    if automatic:
        for other in value['assets']:
            if other['role'] == role:
                other['auto_use'] = False
    asset.update(role=role, auto_use=automatic)
    if width is not None:
        asset['display_width'] = width
    if background is not None:
        asset['background'] = background
    write_json(path, value)
    return asset


def mark_ready(profile_path, mode):
    path, value = load_profile(profile_path)
    if mode not in ('configured', 'neutral'):
        raise ValueError('需要configured或neutral模式')
    if mode == 'neutral' and any(a.get('auto_use') for a in value['assets']):
        raise ValueError('基础无素材模式不能启用品牌头尾图，请关闭自动使用或选择configured')
    value['onboarding'] = {'status': 'ready', 'mode': mode}
    write_json(path, value)
    return {'profile': str(path), 'onboarding': value['onboarding']}


def walk_blocks(blocks):
    for block in blocks:
        yield block
        if block['type'] == 'group':
            yield from walk_blocks(block['blocks'])
        elif block['type'] == 'table':
            for row in block['rows']:
                for cell in row:
                    yield from walk_blocks(cell['blocks'])


def validate_theme(theme):
    for key in ('primary', 'light', 'accent', 'text', 'page_background', 'group_border'):
        color = theme.get(key)
        if color is None and key in ('page_background', 'group_border'):
            continue
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', str(color)):
            raise ValueError('主题颜色须为六位色值：' + key)
    if theme.get('heading') not in ('bar', 'number', 'section-label'):
        raise ValueError('标题样式需为bar、number或section-label')
    for key in ('group_padding', 'summary_padding'):
        if not isinstance(theme.get(key), (int, float)) or not 0 <= theme[key] <= 48:
            raise ValueError('组内留白须为0–48px：' + key)


def is_legacy_default(theme):
    """Only migrate an exact old default, never a user's partial/custom theme."""
    return {k: v for k, v in theme.items() if k != 'name'} == {
        k: v for k, v in LEGACY_THEME.items() if k != 'name'}


def normalize_layout(article):
    """Apply the standard composition to semantic blocks without rewriting text."""
    additions = article.setdefault('layout_additions', [])
    adjustments = []

    def pictures(blocks):
        output = []
        index = 0
        while index < len(blocks):
            block = blocks[index]
            if block['type'] == 'group':
                block['blocks'] = pictures(block['blocks'])
            if block['type'] == 'gallery':
                block.setdefault('mode', 'row' if len(block['images']) in (2, 3) else 'stack')
                block.setdefault('width_percent', 90)
                if block['mode'] == 'row':
                    block.setdefault('gap_px', 8)
            if block['type'] == 'image':
                end = index + 1
                while end < len(blocks) and blocks[end]['type'] == 'image':
                    end += 1
                consecutive = blocks[index:end]
                if len(consecutive) > 1:
                    # Semantic separation must be represented by groups/captions, not invisible guesses.
                    while len(consecutive) > 1:
                        size = 2 if len(consecutive) in (2, 4) else 3
                        output.append({'type': 'gallery', 'mode': 'row', 'gap_px': 8,
                                       'width_percent': 90, 'images': consecutive[:size]})
                        consecutive = consecutive[size:]
                    if consecutive:
                        output.extend(pictures(consecutive))
                    adjustments.append('连续照片整理为独立图片的左右留缝图组')
                    index = end
                    continue
                if 'width_percent' not in block:
                    image_path = Path(block['src'])
                    if image_path.is_file():
                        with Image.open(image_path) as image:
                            block['width_percent'] = 72 if image.height > image.width else 90
            output.append(block)
            index += 1
        return output

    blocks = pictures(article['blocks'])
    result, pending = [], []
    variant = 'intro'

    def flush():
        nonlocal pending
        if pending:
            result.append({'type': 'group', 'variant': variant, 'blocks': pending})
            pending = []
            adjustments.append('散列正文整理为带框内容分区')

    boundaries = {'heading', 'section_label', 'group', 'credit', 'end_mark', 'component'}
    for block in blocks:
        typ = block['type']
        if typ in boundaries:
            flush()
            if typ in ('heading', 'section_label'):
                title = block.get('label', engine.runs_text(block.get('runs', []))).strip()
                variant = 'summary' if title in ('结语', '结尾', '总结', '尾声') else 'section'
            elif typ == 'group':
                if block.get('variant') == 'summary' and (not result or result[-1]['type'] not in ('heading', 'section_label')):
                    result.append({'type': 'section_label', 'label': '结语'})
                    if '结语' not in additions:
                        additions.append('结语')
                variant = 'section'
            result.append(block)
        elif typ == 'intro':
            flush()
            # Use one framed intro instead of nesting a second padded intro box.
            result.append({'type': 'group', 'variant': 'intro', 'blocks': [
                {'type': 'paragraph', 'runs': block.get('runs', []), 'indent': False}]})
            variant = 'section'
        else:
            pending.append(block)
    flush()
    if not any(block['type'] == 'end_mark' for block in result):
        position = next((i for i, block in enumerate(result) if block['type'] == 'credit'), len(result))
        result.insert(position, {'type': 'end_mark'})
    article['blocks'] = result
    article['layout_adjustments'] = adjustments
    article['layout_version'] = 2


def render_article(article_path, profile_path, output):
    profile_path, profile = load_profile(profile_path)
    if profile.get('onboarding', {}).get('status') != 'ready':
        raise ValueError('首次素材征集尚未完成；先收集素材，或记录用户明确选择无素材基础样式，再标记ready')
    article_path = Path(article_path).resolve()
    article = read_json(article_path)
    if article.get('brand_id') not in (None, profile['id']):
        raise ValueError('稿件属于其他账号，请先按用户要求核对品牌和组件，不能自动串用素材')
    if not article.get('classification_reviewed'):
        raise ValueError('请先阅读稿件、核对栏目和图文结构，再设置classification_reviewed:true')
    migrated = []
    if is_legacy_default(profile.get('theme', {})):
        profile['theme'] = deepcopy(DEFAULT_THEME)
        profile['layout_version'] = 2
        write_json(profile_path, profile)
        migrated.append('旧版未定制的默认主题已升级为浅蓝分区标准版')
    if is_legacy_default(article.get('style_overrides', {})):
        article['style_overrides'] = {}
        migrated.append('清除旧输出携带的默认主题快照，使用当前账号主题')
    theme = {**DEFAULT_THEME, **profile.get('theme', {}), **article.get('style_overrides', {})}
    validate_theme(theme)
    components = {}
    for asset in profile['assets']:
        if asset['role'] not in BODY_ROLES or not asset.get('renderable'):
            continue
        file = (profile_path.parent / asset['file']).resolve()
        if not file.is_relative_to(profile_path.parent):
            raise ValueError('品牌素材必须位于本账号配置目录')
        components[asset['id']] = {'file': str(file), 'label': asset['role'],
                                   'background': asset.get('background', 'transparent'),
                                   'display_width': asset.get('display_width', 1000)}
    present = set()
    for block in walk_blocks(article['blocks']):
        if block['type'] == 'component':
            key = block['component']
            if key not in components:
                raise ValueError('正文组件不属于本账号已分类可用素材：' + key)
            present.add(key)
            # Bind to current profile instead of stale paths from a different delivery.
            block['src'] = components[key]['file']
        if block['type'] in ('image', 'component') and block.get('src'):
            block['src'] = str((article_path.parent / block['src']).resolve())
        if block['type'] == 'gallery':
            for image in block['images']:
                image['src'] = str((article_path.parent / image['src']).resolve())
    headers, footers = [], []
    for role in ('header', 'footer'):
        if sum(a.get('auto_use', False) and a['role'] == role for a in profile['assets']) > 1:
            raise ValueError('同一角色存在多个自动组件，请先确定本次使用哪一个')
    for asset in profile['assets']:
        if not asset.get('auto_use') or asset['id'] in present:
            continue
        if asset['role'] not in ('header', 'footer') or asset['id'] not in components:
            raise ValueError('自动素材必须是可用的header或footer')
        item = {'type': 'component', 'component': asset['id'], 'edge_aligned': True}
        (headers if asset['role'] == 'header' else footers).append(item)
    if len(headers) > 1 or len(footers) > 1:
        raise ValueError('同一角色存在多个自动组件，请先确定本次使用哪一个')
    normalize_layout(article)
    article['blocks'] = headers + article['blocks'] + footers
    article['brand_id'] = profile['id']
    article['theme'] = 'brand-default'
    article['style_overrides'] = theme
    article['column'] = article.get('column') or '通用'
    engine.COLUMNS = {article['column']: {'theme': 'brand-default'}}
    engine.COMPONENTS = components
    output = Path(output).resolve()
    prepared = output / 'work' / 'article.prepared.json'
    write_json(prepared, article)
    checks = engine.render(prepared, output)
    checks['brand_id'] = profile['id']
    checks['layout_version'] = 2
    checks['layout_adjustments'] = article['layout_adjustments']
    checks['layout_migrations'] = migrated
    write_json(output / 'checks.json', checks)
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=default_data_dir())
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('profiles')
    cmd = commands.add_parser('init')
    cmd.add_argument('--id', required=True); cmd.add_argument('--name', required=True)
    cmd = commands.add_parser('import-assets')
    cmd.add_argument('--profile', required=True); cmd.add_argument('--source', required=True)
    cmd.add_argument('--kind', choices=('material', 'reference'), default='material')
    cmd = commands.add_parser('assign')
    cmd.add_argument('--profile', required=True); cmd.add_argument('--asset', required=True)
    cmd.add_argument('--role', choices=ROLES, required=True)
    usage = cmd.add_mutually_exclusive_group()
    usage.add_argument('--auto-use', dest='auto_use', action='store_true')
    usage.add_argument('--manual-use', dest='auto_use', action='store_false')
    cmd.set_defaults(auto_use=None)
    cmd.add_argument('--width', type=int); cmd.add_argument('--background')
    cmd = commands.add_parser('ready')
    cmd.add_argument('--profile', required=True); cmd.add_argument('--mode', choices=('configured', 'neutral'), required=True)
    cmd = commands.add_parser('extract')
    cmd.add_argument('source'); cmd.add_argument('--out', required=True)
    cmd = commands.add_parser('render')
    cmd.add_argument('article'); cmd.add_argument('--profile', required=True); cmd.add_argument('--out', required=True)
    args = parser.parse_args()
    if args.command == 'profiles':
        result = list_profiles(args.data_dir)
    elif args.command == 'init':
        result = init_profile(args.data_dir, args.id, args.name)
    elif args.command == 'import-assets':
        result = import_assets(args.profile, args.source, args.kind)
    elif args.command == 'assign':
        result = assign_asset(args.profile, args.asset, args.role, args.auto_use, args.width, args.background)
    elif args.command == 'ready':
        result = mark_ready(args.profile, args.mode)
    elif args.command == 'extract':
        article = engine.extract(args.source, args.out)
        result = {k: article[k] for k in ('title', 'classification', 'warnings')}
        result['blocks'] = len(article['blocks'])
    else:
        result = render_article(args.article, args.profile, args.out)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
        print('错误：' + str(error), file=sys.stderr)
        sys.exit(1)

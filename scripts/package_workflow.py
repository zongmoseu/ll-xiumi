"""Build clean skill, extension, and workflow bundles without local user data."""
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {'.md', '.py', '.json', '.yaml', '.png', '.html', '.js', '.txt'}
EXCLUDED = {'__pycache__', 'profiles', 'work', 'output', '.git', 'dist', '.venv'}


def files_in(directory):
    for file in sorted(directory.rglob('*')):
        relative = file.relative_to(directory)
        if not file.is_file() or file.is_symlink() or set(relative.parts) & EXCLUDED:
            continue
        if file.name == 'profile.json':
            continue
        if file.suffix.lower() in ALLOWED or file.name == 'UPSTREAM-LICENSE':
            yield file


def write_zip(path, entries):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for file, name in entries:
            archive.write(file, name)
    return path


def build():
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    skill = ROOT / 'skills/wechat-brand-layout'
    plugin = ROOT / 'plugins/ll-xiumi-importer'
    skill_files, plugin_files = list(files_in(skill)), list(files_in(plugin))
    bundles = [
        write_zip(dist / f'wechat-brand-layout-v{version}.zip',
                  [(f, str(Path(skill.name) / f.relative_to(skill))) for f in skill_files]),
        write_zip(dist / f'll-xiumi-importer-v{version}.zip',
                  [(f, str(f.relative_to(plugin))) for f in plugin_files]),
    ]
    complete = skill_files + plugin_files + list(files_in(ROOT / 'docs'))
    complete += list(files_in(ROOT / 'scripts')) + list(files_in(ROOT / 'tests'))
    complete += [ROOT / 'README.md', ROOT / 'VERSION']
    bundles.append(write_zip(dist / f'll-xiumi-workflow-v{version}.zip',
                             [(f, str(f.relative_to(ROOT))) for f in complete]))
    checksum = dist / 'SHA256SUMS.txt'
    checksum.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
                               for p in bundles), encoding='utf-8')
    for file in bundles + [checksum]:
        print(file)


if __name__ == '__main__':
    build()

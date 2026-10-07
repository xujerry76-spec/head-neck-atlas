"""Publish immutable study directories only after all files have been validated."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def dump_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def validate_bundle(path):
    root = Path(path).resolve()
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema') != 1 or not isinstance(manifest.get('files'), dict):
        raise ValueError('不支持的研究包格式。')
    files = manifest['files']
    if not {'scene.mrb', 'run.json'} <= set(files):
        raise ValueError('研究包缺少场景或运行记录。')
    for name, digest in files.items():
        relative = Path(name)
        if (relative.is_absolute() or '..' in relative.parts or '\\' in name
                or ':' in name or name == 'manifest.json'):
            raise ValueError('研究包包含不安全的文件路径。')
        target = root / relative
        if target.is_symlink() or not target.resolve().is_relative_to(root) or not target.is_file():
            raise ValueError(f'研究包文件无效：{name}')
        if sha256(target) != digest:
            raise ValueError(f'研究包校验失败：{name}')
    actual = {file.relative_to(root).as_posix() for file in root.rglob('*') if file.is_file()}
    if actual != set(files) | {'manifest.json'}:
        raise ValueError('研究包存在未登记文件。')
    json.loads((root / 'run.json').read_text(encoding='utf-8'))
    return manifest


def write_bundle(destination, producer):
    destination = Path(destination).absolute()
    if destination.exists():
        raise FileExistsError('研究目录已存在，请使用新的研究编号。')
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.atlas-stage-', dir=destination.parent))
    try:
        producer(stage)
        files = {file.relative_to(stage).as_posix(): sha256(file)
                 for file in stage.rglob('*') if file.is_file() and file.name != 'manifest.json'}
        dump_json(stage / 'manifest.json', {'schema': 1, 'files': files})
        validate_bundle(stage)
        # Same-volume rename: interrupted saves never publish a partial final directory.
        if destination.exists():
            raise FileExistsError('研究目录已存在。')
        os.rename(stage, destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return destination

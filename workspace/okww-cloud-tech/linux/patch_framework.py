"""Apply auditable source changes to the isolated Linux vendor snapshot only."""
import ast
import difflib
import hashlib
import json
from pathlib import Path
import sys


def patch(stage):
    stage = Path(stage).resolve()
    manifest = json.loads((stage/'source-manifest.json').read_text())['files']
    changes = {}
    diffs = []

    def update(relative, transform):
        path = stage/relative
        before_bytes = path.read_bytes()
        assert hashlib.sha256(before_bytes).hexdigest() == manifest[relative], relative
        before = before_bytes.decode('utf-8')
        after = transform(before)
        ast.parse(after)
        path.write_text(after, encoding='utf-8')
        changes[relative] = dict(before=manifest[relative],after=hashlib.sha256(path.read_bytes()).hexdigest())
        diffs.extend(difflib.unified_diff(before.splitlines(True),after.splitlines(True),
                                        fromfile=relative,tofile=relative))

    def lazy_exports(source):
        exports = {}
        for node in ast.parse(source).body:
            assert isinstance(node, ast.ImportFrom), 'Unexpected package initializer; review before patching'
            for alias in node.names:
                assert alias.name != '*'
                exports[alias.asname or alias.name] = (node.module,alias.name)
        return ('"""Lazy backend exports: importing the browser must not import Windows capture."""\n'
                'import importlib\n'
                f'_EXPORTS = {exports!r}\n'
                '__all__ = list(_EXPORTS)\n'
                'def __getattr__(name):\n'
                '    if name not in _EXPORTS:\n'
                '        raise AttributeError(name)\n'
                '    module, attribute = _EXPORTS[name]\n'
                '    value = getattr(importlib.import_module(module), attribute)\n'
                '    globals()[name] = value\n'
                '    return value\n')

    for package in ('capture_methods','interaction_methods'):
        update(f'vendor/ok/device/{package}/__init__.py',lazy_exports)

    # This executor needs only a pure geometry function from the large Win32 module.
    window = (stage/'vendor/ok/util/window.py').read_text(encoding='utf-8')
    node = next(n for n in ast.parse(window).body if isinstance(n,ast.FunctionDef) and n.name=='ratio_text_to_number')
    geometry = ast.get_source_segment(window,node)+'\n'
    path = stage/'vendor/ok/util/geometry.py'
    assert not path.exists() or path.read_text(encoding='utf-8') == geometry, 'Geometry file collision'
    path.write_text(geometry,encoding='utf-8')
    changes['vendor/ok/util/geometry.py'] = dict(before=None,after=hashlib.sha256(path.read_bytes()).hexdigest())

    def executor_import(source):
        original = 'from ok.util.window import ratio_text_to_number'
        assert source.count(original) == 1
        return source.replace(original,'from ok.util.geometry import ratio_text_to_number')
    update('vendor/ok/task/TaskExecutor.py',executor_import)
    def platform_sleep(source):
        marker = 'def prevent_sleeping(yes=True):'
        assert source.count(marker) == 1
        return source.replace(marker, marker+'\n    if sys.platform != "win32":\n        return False')
    update('vendor/ok/util/process.py',platform_sleep)
    (stage/'framework-patch-manifest.json').write_text(json.dumps(changes,indent=2),encoding='utf-8')
    (stage/'framework-linux.patch').write_text(''.join(diffs),encoding='utf-8')
    print('Isolated framework patches:',len(changes))


if __name__ == '__main__':
    patch(sys.argv[1])

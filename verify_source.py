"""Verify the published source snapshot without loading a game or browser."""
from pathlib import Path
import ast,hashlib,json
root=Path(__file__).resolve().parent
manifest=json.loads((root/'SOURCE_MANIFEST.json').read_text(encoding='utf-8'))
for name,digest in manifest['files'].items():
    path=root/name
    assert path.is_file(),name
    assert hashlib.sha256(path.read_bytes()).hexdigest()==digest,name
count=0
for path in (root/'workspace').rglob('*.py'):
    ast.parse(path.read_text(encoding='utf-8-sig'),filename=str(path));count+=1
print(json.dumps({'source_files_verified':len(manifest['files']),'python_files_parsed':count,'game_inputs':False}))

"""Package source only; never package profiles, configs, credentials, game images or assets."""
import hashlib
import json
from pathlib import Path
import tarfile
import argparse

root = Path(__file__).resolve().parents[1]
workspace = root.parents[1]
framework = Path('C:/Users/Example/Documents/GameAutomation/ok-ww/data/apps/ok-ww/working/ok')
license_path = Path('C:/Users/Example/Documents/Codex/2026-09-20/new-chat/work/hk-wuwa-cloud/upstream-framework/LICENSE.txt')
parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, default=workspace/'outputs/linux-offline-20261004')
output = parser.parse_args().output.resolve()
output.mkdir(exist_ok=True)
files = []
for file in framework.rglob('*.py'):
    if '__pycache__' not in file.parts:
        files.append((file, 'vendor/ok/'+file.relative_to(framework).as_posix()))
files.append((license_path,'vendor/LICENSE-ok-script.txt'))
for file in (root/'src').rglob('*.py'):
    files.append((file,'code/'+file.relative_to(root).as_posix()))
for pattern in ['cloud_*.py','config.py','main_cloud*.py','tests/test_cloud*.py','tests/offline_runtime_contract.py','linux/*.py','linux/*.in','linux/*.txt','linux/*.sh','linux/*.md','chrome-extension/worker.js']:
    for file in root.glob(pattern):
        files.append((file,'code/'+file.relative_to(root).as_posix()))
manifest = {name:hashlib.sha256(file.read_bytes()).hexdigest() for file,name in sorted(files,key=lambda f:f[1])}
manifest_path = output/'source-manifest.json'
manifest_path.write_text(json.dumps({'framework_origin':str(framework),'files':manifest},indent=2),encoding='utf-8')
archive = output/'source.tar.gz'
with tarfile.open(archive,'w:gz') as tar:
    for file,name in files: tar.add(file,arcname=name,recursive=False)
    tar.add(manifest_path,arcname='source-manifest.json')
print(json.dumps({'files':len(files),'archive_bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}))

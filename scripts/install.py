"""Install the local CLI and compile its optional warm-run fast path."""

import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
subprocess.run(["uv", "tool", "install", "--force", "--editable", str(root)], check=True)
interpreter = Path.home() / ".local/share/uv/tools/ax-workbench/bin/python"
program = """
import json,os,shutil,sys
from pathlib import Path
from ax.build_launcher import build
from ax.config import load
config=load()
if not shutil.which('cc'):
    print(json.dumps({'installed':str(Path.home()/'.local/bin/ax'),'launcher':'python'}))
    sys.exit(0)
target=build(config,os.sys.executable,config.data/'bin/ax-native',os.environ.get('AX_CONFIG'))
entry=Path.home()/'.local/bin/ax'
entry.unlink()
entry.symlink_to(target)
print(json.dumps({'installed':str(entry),'launcher':'native'}))
"""
subprocess.run([str(interpreter), "-c", program], check=True)

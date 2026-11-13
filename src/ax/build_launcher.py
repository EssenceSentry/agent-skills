"""Optional native command-prefix launcher; all policy remains in the daemon."""

import json
import shutil
import subprocess
from pathlib import Path


def build(config, interpreter, destination, config_file=None):
    compiler = shutil.which("cc")
    if not compiler:
        raise RuntimeError("a C compiler is needed to build the fast launcher")
    config_file = Path(config_file or "~/.config/ax/config.toml").expanduser().resolve()
    modified = int(config_file.stat().st_mtime) if config_file.exists() else 0
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    definitions = {
        "AX_PYTHON": str(interpreter),
        "AX_SOCKET": str(config.socket),
        "AX_CONFIG_FILE": str(config_file),
    }
    command = [
        compiler,
        "-O2",
        "-Wall",
        "-Wextra",
        str(Path(__file__).with_name("launcher.c")),
        "-o",
        str(destination),
    ]
    command += ["-D" + key + "=" + json.dumps(value) for key, value in definitions.items()]
    command += ["-DAX_CONFIG_MTIME=" + str(modified)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    return destination

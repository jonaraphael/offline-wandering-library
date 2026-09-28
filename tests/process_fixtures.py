"""Run synthetic Python tools as real subprocesses on every supported OS."""
from contextlib import contextmanager
import subprocess
import sys
from unittest.mock import patch


@contextmanager
def python_script_tool(script):
    """Use Python explicitly; Windows cannot execute a Unix shebang script."""
    popen = subprocess.Popen

    def launch(arguments, *args, **kwargs):
        if str(arguments[0]) == str(script):
            arguments = [sys.executable, *arguments]
        return popen(arguments, *args, **kwargs)

    with patch.object(subprocess, "Popen", side_effect=launch):
        yield

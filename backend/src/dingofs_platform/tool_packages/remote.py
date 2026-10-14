"""Self-contained remote Python programs. Never stop services or run workloads."""
import json
from pathlib import Path


def probe_script():
    return Path(__file__).with_name('help_result.py').read_text() + '\n' + Path(__file__).with_name('probe_helper.py').read_text()


def install_script(bundle, staging):
    return 'BUNDLE = ' + repr(bundle) + '\nSTAGING = ' + repr(staging) + '\n' + Path(__file__).with_name('help_result.py').read_text() + '\n' + Path(__file__).with_name('shell_entry.py').read_text() + '\n' + Path(__file__).with_name('install_helper.py').read_text()

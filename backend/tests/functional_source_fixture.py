"""Copy reviewed pure framework code, never original environment data/executors.

CI and cross-repository verification must set FUNCTIONAL_CONTRACTS_TEST_ROOT to
the trusted framework checkout. An absent checkout is an explicit local skip.
"""
import os
from pathlib import Path
import shutil

import pytest


def copy_trusted_protocol(root: Path) -> None:
    configured = os.environ.get('FUNCTIONAL_CONTRACTS_TEST_ROOT')
    if not configured:
        pytest.skip('set FUNCTIONAL_CONTRACTS_TEST_ROOT to the reviewed framework checkout')
    source = Path(configured)
    for relative in (
        'src/config/__init__.py', 'src/config/models.py', 'src/config/env_parser.py',
        'src/config/environment_contracts.py', 'src/test_runner/__init__.py',
        'src/test_runner/models.py', 'src/test_runner/functional_contracts.py',
        'src/test_runner/functional_capabilities.py', 'src/test_runner/owned_workloads.py',
    ):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, destination)

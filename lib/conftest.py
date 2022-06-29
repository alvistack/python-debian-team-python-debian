try:
    from typing import Dict, Any
except ImportError:
    pass

import pytest

from debian.tests.stubbed_arch_table import StubbedDpkgArchTable


@pytest.fixture(autouse=True)
def doctest_add_load_arch_table(doctest_namespace):
    # type: (Dict[str, Any]) -> None
    # Provide a custom namespace for doctests such that we can have them use
    # a custom environment. Use sparingly.
    # - For this to work, the doctests MUST NOT import the names listed here
    #   (as the import would overwrite the stub)
    doctest_namespace['DpkgArchTable'] = StubbedDpkgArchTable

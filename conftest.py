from typing import Dict, Any

import pytest

from tests.stubbed_arch_table import StubbedDpkgArchTable


@pytest.fixture(autouse=True)
def doctest_add_load_arch_table(doctest_namespace):
    # type: (Dict[str, Any]) -> None
    # Provide a custom namespace for doctests such that we can have them use
    # a custom environment. Use sparingly.
    # - For this to work, the doctests MUST NOT import the names listed here
    #   (as the import would overwrite the stub)
    doctest_namespace['DpkgArchTable'] = StubbedDpkgArchTable


# CRUFT: can be deleted once stretch/Python 3.5 support is dropped
#
# pytest caplog was introduced in pytest 3.3; being able to run the test suite
# on Debian stretch (Python 3.5, pytest 3.0.6) is desired. Doing
# an ad hoc version comparison for this is useful

from debian.debian_support import Version

installed_pytest_version = Version(pytest.__version__)
caplog_min_version = Version("3.3")

if installed_pytest_version < caplog_min_version:
    @pytest.fixture()
    def caplog(request):   # type: ignore
        pytest.skip("caplog capability not present")

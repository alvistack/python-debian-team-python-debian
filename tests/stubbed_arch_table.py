from io import StringIO
try:
    from os import PathLike
    from typing import Union
except ImportError:
    pass

from debian._arch_table import DpkgArchTable

stubbed_cpu_table_data = """\
# Version=1.0
#
# This file contains the table of known CPU names.
#
# [...]
#
# <Debian name> <GNU name>      <config.guess regex>    <Bits>  <Endianness>
i386            i686            (i[34567]86|pentium)    32      little
amd64           x86_64          (amd64|x86_64)          64      little
arm             arm             arm.*                   32      little
arm64           aarch64         aarch64                 64      little
"""

stubbed_tuple_table_data = """\
# Version=1.0
#
# [...]
#
# Supported variables: <cpu>
#
# <Debian arch tuple>           <Debian arch name>
eabihf-gnu-linux-arm            armhf
eabi-gnu-linux-arm              armel
x32-gnu-linux-amd64             x32
base-gnu-linux-<cpu>            <cpu>
eabihf-gnu-kfreebsd-arm         kfreebsd-armhf
base-gnu-kfreebsd-<cpu>         kfreebsd-<cpu>
"""


class StubbedDpkgArchTable(DpkgArchTable):

    @classmethod
    def load_arch_table(cls, path="/usr/share/dpkg"):
        # type: (Union[str, PathLike[str]]) -> DpkgArchTable
        cpu_table = StringIO(stubbed_cpu_table_data)
        tuple_table = StringIO(stubbed_tuple_table_data)
        return cls._from_file(tuple_table, cpu_table)


#! /usr/bin/python3
## vim: fileencoding=utf-8

# Copyright (C) 2022 Niels Thykier <niels@thykier.net>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation, either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import os.path

import pytest

from debian.debian_support import DpkgArchTable
from .stubbed_arch_table import StubbedDpkgArchTable


if os.path.isfile("/usr/share/dpkg/tupletable"):
    HAS_REAL_DATA = True
else:
    HAS_REAL_DATA = False


class TestDpkgArchTable:
    
    def test_matches_architecture(self):
        # type: () -> None
        arch_table = StubbedDpkgArchTable.load_arch_table()
        assert arch_table.matches_architecture("amd64", "linux-any")
        assert arch_table.matches_architecture("i386", "linux-any")
        assert arch_table.matches_architecture("amd64", "amd64")

        assert not arch_table.matches_architecture("i386", "amd64")
        assert not arch_table.matches_architecture("all", "amd64")

        assert arch_table.matches_architecture("all", "all")

        # i386 is the short form of linux-i386. Therefore, it does not match kfreebsd-i386
        assert not arch_table.matches_architecture("i386", "kfreebsd-i386")

        # Note that "armel" and "armhf" are "arm" CPUs, so it is matched by "any-arm"
        # (similar holds for some other architecture <-> CPU name combinations)
        for n in ['armel', 'armhf']:
            assert arch_table.matches_architecture(n, 'any-arm')
        # Since "armel" is not a valid CPU name, this returns False (the correct would be
        # any-arm as noted above)
        assert not arch_table.matches_architecture("armel", "any-armel")

        # Wildcards used as architecture always fail (except for special cases noted in the
        # compatibility notes below)
        assert not arch_table.matches_architecture("any-i386", "i386")

        # any-i386 is not a subset of linux-any (they only have i386/linux-i386 as overlap)
        assert not arch_table.matches_architecture("any-i386", "linux-any")

        # Compatibility with dpkg - if alias is `any` then it always returns True
        # even if the input otherwise would not make sense.
        assert arch_table.matches_architecture("any-unknown", "any")
        # Another side effect of the dpkg compatibility
        assert arch_table.matches_architecture("all", "any")

        # STUB VERIFICATION: This would return True if we used real data.  But we are supposed to
        # use the stub which does not have data for this architecture.
        # (If this fails because you added the architecture to the stub, then replace it with
        # another architecture, so the verification still works)
        assert not arch_table.matches_architecture('mipsel', 'any-mipsel')

    def test_arch_equals(self):
        # type: () -> None
        arch_table = StubbedDpkgArchTable.load_arch_table()
        assert arch_table.architecture_equals("linux-amd64", "amd64")
        assert not arch_table.architecture_equals("amd64", "linux-i386")
        assert not arch_table.architecture_equals("i386", "linux-amd64")
        assert arch_table.architecture_equals("amd64", "amd64")
        assert not arch_table.architecture_equals("i386", "amd64")

        # Compatibility with dpkg: if the parameters are equal, then it always return True
        assert arch_table.architecture_equals("unknown", "unknown")

    def test_architecture_is_concerned(self):
        # type: () -> None
        arch_table = StubbedDpkgArchTable.load_arch_table()
        assert arch_table.architecture_is_concerned("linux-amd64", ["amd64", "i386"])
        assert not arch_table.architecture_is_concerned("amd64", ["!amd64", "!i386"])
        # This is False because the "!amd64" is matched first.
        assert not arch_table.architecture_is_concerned(
            "linux-amd64",
            ["!linux-amd64", "linux-any"],
            allow_mixing_positive_and_negative=True
        )
        # This is True because the "linux-any" is matched first.
        assert arch_table.architecture_is_concerned(
            "linux-amd64",
            ["linux-any", "!linux-amd64"],
            allow_mixing_positive_and_negative=True
        )

    def test_is_wildcard(self):
        # type: () -> None
        arch_table = StubbedDpkgArchTable.load_arch_table()
        assert arch_table.is_wildcard("linux-any")
        assert not arch_table.is_wildcard("amd64")
        assert not arch_table.is_wildcard("unknown")
        # Compatibility with the dpkg version of the function.
        assert arch_table.is_wildcard("unknown-any")

    @pytest.mark.skipif(not HAS_REAL_DATA, reason="Missing real data")
    def test_has_real_data(self):
        # type: () -> None
        arch_table = DpkgArchTable.load_arch_table()
        # The tests here rely on the production data, so we can use mips (which is not present in
        # our stubbed data).

        assert arch_table.matches_architecture('mipsel', 'any-mipsel')

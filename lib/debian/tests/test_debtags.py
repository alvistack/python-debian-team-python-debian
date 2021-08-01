#! /usr/bin/python
## vim: fileencoding=utf-8

# Copyright (C) 2006 Enrico Zini <enrico@enricozini.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os.path
import sys
import unittest

from debian import debtags


def find_test_file(filename):
    # type: (str) -> str
    """ find a test file that is located within the test suite """
    return os.path.join(os.path.dirname(__file__), filename)


class TestDebtags(unittest.TestCase):
    def mkdb(self):
        # type: () -> debtags.DB
        db = debtags.DB()
        with open(find_test_file("test_tagdb"), "r") as f:
            db.read(f)
        return db

    def test_insert(self):
        # type: () -> None
        db = debtags.DB()
        db.insert("test", set(("a", "b")));
        assert db.has_package("test")
        assert not db.has_package("a")
        assert not db.has_package("b")
        assert db.has_tag("a")
        assert db.has_tag("b")
        assert not db.has_tag("test")
        self.assertEqual(db.tags_of_package("test"), set(("a", "b")))
        self.assertEqual(db.packages_of_tag("a"), set(("test")))
        self.assertEqual(db.packages_of_tag("b"), set(("test")))
        self.assertEqual(db.package_count(), 1)
        self.assertEqual(db.tag_count(), 2)

    def test_reverse(self):
        # type: () -> None
        db = debtags.DB()
        db.insert("test", set(("a", "b")));
        db = db.reverse()
        assert db.has_package("a")
        assert db.has_package("b")
        assert not db.has_package("test")
        assert db.has_tag("test")
        assert not db.has_tag("a")
        assert not db.has_tag("b")
        self.assertEqual(db.packages_of_tag("test"), set(("a", "b")))
        self.assertEqual(db.tags_of_package("a"), set(("test")))
        self.assertEqual(db.tags_of_package("b"), set(("test")))
        self.assertEqual(db.package_count(), 2)
        self.assertEqual(db.tag_count(), 1)

    def test_read(self):
        # type: () -> None
        db = self.mkdb()
        self.assertEqual(db.tags_of_package("polygen"), set(("devel::interpreter", "game::toys", "interface::commandline", "works-with::text")))
        assert "polygen" in db.packages_of_tag("interface::commandline")
        self.assertEqual(db.package_count(), 144)
        self.assertEqual(db.tag_count(), 94)

if __name__ == '__main__':
    unittest.main()

# vim:set ts=4 sw=4 expandtab:

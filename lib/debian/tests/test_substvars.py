import os
from tempfile import TemporaryDirectory
from unittest import TestCase

from debian.substvars import Substvars, Substvar


class SubstvarsTests(TestCase):

    def test_substvars(self):
        # type: () -> None
        substvars = Substvars()

        self.assertIsNone(substvars.substvars_path, None)

        # add_dependency automatically creates variables
        self.assertTrue('misc:Recommends' not in substvars)
        substvars.add_dependency('misc:Recommends', "foo (>= 1.0)")
        self.assertEqual(substvars['misc:Recommends'], 'foo (>= 1.0)')
        # It can be appended to other variables
        substvars['foo'] = 'bar, golf'
        substvars.add_dependency('foo', 'dpkg (>= 1.20.0)')
        self.assertEqual(substvars['foo'], 'bar, dpkg (>= 1.20.0), golf')
        # Exact duplicates are ignored
        substvars.add_dependency('foo', 'dpkg (>= 1.20.0)')
        self.assertEqual(substvars['foo'], 'bar, dpkg (>= 1.20.0), golf')

        substvar = substvars.as_substvar['foo']
        self.assertEqual(substvar.assignment_operator, "=")
        substvar.assignment_operator = "?="

        with self.assertRaises(ValueError):
            # Only "=" and "?=" are allowed
            substvar.assignment_operator = 'golf'

        self.assertTrue('foo' in substvars)
        del substvars['foo']
        self.assertFalse('foo' in substvars)

    def test_save_raises(self):
        # type: () -> None
        s = Substvars()
        with self.assertRaises(TypeError):
            # Should raise because it has no base file
            s.save()

    def test_save(self):
        # type: () -> None
        with TemporaryDirectory() as tmpdir:
            filename = os.path.join(tmpdir, "foo.substvars")
            # Obviously, this does not exist
            self.assertFalse(os.path.exists(filename))
            with Substvars.load_from_path(filename, missing_ok=True) as svars:
                svars.add_dependency("misc:Depends", "bar (>= 1.0)")
                svars.as_substvar["foo"] = Substvar("anything goes", assignment_operator="?=")
                self.assertEqual(svars.substvars_path, filename)
            self.assertTrue(os.path.exists(filename))

            with Substvars.load_from_path(filename) as svars:
                # Verify we can actually load the file we just wrote again
                self.assertEqual(svars['misc:Depends'], "bar (>= 1.0)")
                self.assertEqual(svars.as_substvar["misc:Depends"].assignment_operator, "=")
                self.assertEqual(svars['foo'], "anything goes")
                self.assertEqual(svars.as_substvar["foo"].assignment_operator, "?=")

    def test_equals(self):
        # type: () -> None
        foo_a = Substvar("foo", assignment_operator="=")
        foo_b = Substvar("foo", assignment_operator="=")
        foo_optional_a = Substvar("foo", assignment_operator="?=")
        foo_optional_b = Substvar("foo", assignment_operator="?=")
        self.assertEqual(foo_a, foo_b)
        self.assertEqual(foo_optional_a, foo_optional_b)

        self.assertNotEqual(foo_a, foo_optional_a)
        self.assertNotEqual(foo_a, object())

        substvars_a = Substvars()
        substvars_b = Substvars()
        substvars_a["foo"] = "bar"
        substvars_b["foo"] = "bar"
        self.assertEqual(substvars_a, substvars_b)
        self.assertNotEqual(substvars_a, object())


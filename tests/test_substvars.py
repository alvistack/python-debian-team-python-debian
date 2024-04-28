import os
from tempfile import TemporaryDirectory

import pytest

from debian.substvars import Substvars, Substvar


class TestSubstvars:

    def test_substvars(self) -> None:
        substvars = Substvars()

        assert substvars.substvars_path is None, None

        # add_dependency automatically creates variables
        assert 'misc:Recommends' not in substvars
        substvars.add_dependency('misc:Recommends', "foo (>= 1.0)")
        assert substvars['misc:Recommends'] == 'foo (>= 1.0)'
        # It can be appended to other variables
        substvars['foo'] = 'bar, golf'
        substvars.add_dependency('foo', 'dpkg (>= 1.20.0)')
        assert substvars['foo'] == 'bar, dpkg (>= 1.20.0), golf'
        # Exact duplicates are ignored
        substvars.add_dependency('foo', 'dpkg (>= 1.20.0)')
        assert substvars['foo'] == 'bar, dpkg (>= 1.20.0), golf'

        substvar = substvars.as_substvar['foo']
        assert substvar.assignment_operator == "="
        substvar.assignment_operator = "?="

        with pytest.raises(ValueError):
            # Only "=" and "?=" are allowed
            substvar.assignment_operator = 'golf'

        assert 'foo' in substvars
        del substvars['foo']
        assert not ('foo' in substvars)

    def test_save_raises(self) -> None:
        s = Substvars()
        with pytest.raises(TypeError):
            # Should raise because it has no base file
            s.save()

    def test_save(self) -> None:
        with TemporaryDirectory() as tmpdir:
            filename = os.path.join(tmpdir, "foo.substvars")
            # Obviously, this does not exist
            assert not os.path.exists(filename)
            with Substvars.load_from_path(filename, missing_ok=True) as svars:
                svars.add_dependency("misc:Depends", "bar (>= 1.0)")
                svars.as_substvar["foo"] = Substvar("anything goes", assignment_operator="?=")
                assert svars.substvars_path == filename
            assert os.path.exists(filename)

            with Substvars.load_from_path(filename) as svars:
                # Verify we can actually load the file we just wrote again
                assert svars['misc:Depends'] == "bar (>= 1.0)"
                assert svars.as_substvar["misc:Depends"].assignment_operator == "="
                assert svars['foo'] == "anything goes"
                assert svars.as_substvar["foo"].assignment_operator == "?="

    def test_equals(self) -> None:
        foo_a = Substvar("foo", assignment_operator="=")
        foo_b = Substvar("foo", assignment_operator="=")
        foo_optional_a = Substvar("foo", assignment_operator="?=")
        foo_optional_b = Substvar("foo", assignment_operator="?=")
        assert foo_a == foo_b
        assert foo_optional_a == foo_optional_b

        assert foo_a != foo_optional_a
        assert foo_a != object()

        substvars_a = Substvars()
        substvars_b = Substvars()
        substvars_a["foo"] = "bar"
        substvars_b["foo"] = "bar"
        assert substvars_a == substvars_b
        assert substvars_a != object()


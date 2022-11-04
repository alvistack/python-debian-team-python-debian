Contributing
============

Contributions to `python-debian` are most welcome. Where possible, please
discuss your thoughts with the maintainers via the `mailing list`_
as soon as you can so that we can help ensure that the process of including
new code is as painless as possible.

.. _mailing list: mailto:pkg-python-debian-maint@lists.alioth.debian.org


General principles
------------------

In Debian, `python3-debian` gets installed by the Debian Installer as part of the "standard"
task (reportbug depends on python3-reportbug depends on python3-debian). It is
also pulled in to many desktop installations through tools such as
`gdebi <http://packages.debian.org/sid/gdebi>`_.
The `python-debian` codebase is also widely used outside Debian, hence
portability of the code is important too.
Given how widely deployed these packages are:

 - Be very conservative in adding new dependencies. If a package is not
   already a dependency is not already within the set of packages installed
   by the standard task, the additional dependency should be discussed on
   the maintainer list.

 - Be very careful with code changes since you could reasonably break a lot of
   boxes with a botched upload. There is a test suite (see below).

 - There are lots of users of the python-debian API beyond the packages within
   Debian, including parts of Debian's infrastructure and scripts developed by
   users. There is no real way of finding those users and notifying them of
   API changes. Backwards compatibility is very important.

- The non-Debian and non-Linux users of `python-debian` are also important.
  The code is used to track Debian from other operating systems, with
  projects extracting data from `debian/copyright` files or looking
  at the packages that are in Debian and derivatives. Portability of code and
  tests is, therefore, valued.

In general, code in `python-debian` should be reasonably generous in what it
accepts and quite strictly correct in its output.

Ideally, `python-debian` should be written to match what is defined in
`Debian Policy`_.
Code for features that are not yet documented in Policy should be
clearly marked as experimental; it is not unusual for the Policy process to
result in changes to the draft specification that then requires API changes.

Given Policy's role in documenting standard practice and not in developing new
specifications, some behaviour is not specified by Policy but is instead
encoded within other parts of the ecosystem such as dpkg, apt or dak. In such
situations, `python-debian` should remain consistent with other implementations.

.. _Debian Policy: https://www.debian.org/doc/debian-policy/

Notable specifications:

 - `Debian Policy`_
 - `dpkg-dev man pages <https://manpages.debian.org/sid/dpkg-dev/>`_ including:
    - `deb-control(5) <https://manpages.debian.org/sid/dpkg-dev/deb-control.5.html>`_,
      the `control` file in the binary package (generated from
      `debian/control` in the source package)
    - `deb-version(5) <https://manpages.debian.org/sid/dpkg-dev/deb-version.5.html>`_,
      Debian version strings.
    - `deb-changelog(5) <https://manpages.debian.org/sid/dpkg-dev/deb-changelog.5.html>`_,
      changelogs for Debian packages.
    - `deb-changes(5) <https://manpages.debian.org/sid/dpkg-dev/deb-changes.5.html>`_,
      `changes` files that developers upload to add new packages to the
      archive.
    - `deb-substvars(5) <https://manpages.debian.org/sid/dpkg-dev/deb-substvars.5.html>`_,
      `substvars` files that track substitution variables in packaging that
      help automate package steps.
    - `dsc(5) <https://manpages.debian.org/sid/dpkg-dev/dsc.5.html>`_,
      Debian Source Control file that defines the files that are part of a
      source package.
 - `Debian mirror format <http://wiki.debian.org/RepositoryFormat>`_,
   including documentation for Packages, Sources files etc.
 - `dak documentation <https://salsa.debian.org/ftp-team/dak/tree/master/docs>`_,
   the Debian Archive Kit that manages the contents of the Debian archive.


Style guide
-----------

 - Code should be whitespace clean, pep8 & pylint compatible;
   a `.pylintrc` configuration file is provided is also run on
   salsa.debian.org as part of the CI checks for merge requests.
   (Where pep8 and pylintrc disagree about
   whitespace, follow pylint's recommendations.)

 - Write type annotations to help `mypy --strict` understand the types and
   ensure that mypy is happy with the code.

 - Write tests. For everything.

 - Write docstrings in rst format so that sphinx can generate API
   documentation.

The pylint and mypy tools can be run easily from `debian/rules` to track code
quality::

    $ ./debian/rules qa


Test suite
----------

Please make sure all tests in the test suite pass after any change is made.

Adding a test that exposes a given bug and then fixing the bug (and hence the
test suite) is the preferred method for bug fixing. Please reference the bug
number and describe the problem and solution in the comments for the bug so
that those who come after you can understand both 'what' and 'why'.

The tests use absolute imports and do not alter `sys.path` so that they can be
used to test either the installed package or the current working tree. Tests
can be run either from the top-level directory or from the lib/ directory:

Run all tests from the top most directory of the source package::

    $ python3 -m pytest -v -rsx --doctest-modules lib/

Or just run some selected tests::

    $ python3 -m pytest -v -rsx --doctest-modules lib/debian/tests/test_deb822.py::TestDeb822::test_buildinfo

    $ python3 -m pytest -v -rsx --doctest-modules debian/tests/test_deb822.py

For simplicity all the tests can also be run as::

    $ ./debian/rules test

The tests are run as part of the package build and also as a CI job on
salsa.debian.org. Tests will be run against merge requests automatically.
Running the tests with different encodings specified in the environment
(using LC_ALL) is a good way of catching errors in handling the encoding
of files.

The tests make use of `pytest` features such as `caplog` for testing logging,
`pytest.raises` for testing that exceptions are raised, and custom fixtures
to provide test data.


Debian Bug Tracking System
--------------------------

Bug tracking for `python-debian` is undertaken in the
`Debian bug tracking system <https://bugs.debian.org/src:python-debian>`_
(BTS).
The BTS has been configured to display bugs split by module
(see usercategories configuration below).
Bug reporters and developers may find the
`view with only the per-module categorisation <https://bugs.debian.org/cgi-bin/pkgreport.cgi?src=python-debian;ordering=python-debian-modules>`_
(and no severity or status organisation) useful.

Bug reporters are welcome to add the relevant usertags to their bug reports
but don't worry if you do not; they can be easily added in later by people
who are more familiar with the BTS. Adding the `User` and `Usertag`
pseudo-headers to the bug report would mark the bug as being in the
`deb822` module, for instance::

    To: submit@bugs.debian.org
    Subject: title-of-bug

    Package: python-debian
    [ ... ]
    User: python-debian@packages.debian.org
    Usertags: deb822

    description-of-bug ...

For reference, the BTS usercategories configuration (which lists the known
usertags for the BTS view) is as follows:

.. include:: bts-usercategories.txt
   :literal:

The usertags are derived from the Python names of the (sub)modules.
Note that usertags cannot include underscores and thus the the Python
module name `debian_support` becomes the BTS usertag `debian-support`.

Documentation on usercategories and usertags:

  * `Wiki guide on usertags <https://wiki.debian.org/bugs.debian.org/usertags>`_
  * `BTS documentation <https://www.debian.org/Bugs/server-request#usercategory>`_

Uploading
---------

When uploading the package, it should be uploaded both to Debian and also to
PyPI. Please upload the source tarball (sdist) and also an egg (bdist_egg)
and a wheel (bdist_wheel), all built for Python 3. The python3-wheel
package needs to be installed to build the wheel.

The following developers have access to the PyPI project to be able to
upload it.

 *   pkern
 *   stuart
 *   jelmer

The upload procedure is::

    $ ./debian/rules dist
    $ twine upload --sign dist/python?debian-x.y.z.*


Test uploads to TestPyPI can be made and tested with::

    $ twine upload --sign --repository testpypi dist/python-debian-x.y.z.tar.gz
    $ virtualenv python-debian-test
    $ cd python-debian-test
    $ . bin/activate
    $ pip install --index-url https://test.pypi.org/simple/ \
              --extra-index-url https://pypi.org/simple python-debian

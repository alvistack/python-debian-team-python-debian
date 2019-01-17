Contributing
============

Contributions to `python-debian` are most welcome. Where possible, please
discuss your thoughts with the maintainers via the `mailing list`_
as soon as you can so that we can help ensure that the process of including
new code is as painless as possible.

.. _mailing list: mailto:pkg-python-debian-maint@lists.alioth.debian.org


General principles
------------------

`python3-debian` gets installed by the Debian Installer as part of the "standard"
task (reportbug depends on python3-reportbug depends on python3-debian). It is
also pulled in to many desktop installations through tools such as
`gdebi <http://packages.debian.org/sid/gdebi>`_.
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
 - `dpkg-dev man pages <https://manpages.debian.org/stretch/dpkg-dev/>`_ including:
    - `deb-control(5) <https://manpages.debian.org/stretch/dpkg-dev/deb-control.5.html>`_,
      the `control` file in the binary package (generated from
      `debian/control` in the source package)
    - `deb-version(5) <https://manpages.debian.org/stretch/dpkg-dev/deb-version.5.html>`_,
      Debian version strings.
    - `deb-changelog(5) <https://manpages.debian.org/stretch/dpkg-dev/deb-changelog.5.html>`_,
      changelogs for Debian packages.
    - `deb-changes(5) <https://manpages.debian.org/stretch/dpkg-dev/deb-changes.5.html>`_,
      `changes` files that developers upload to add new packages to the
      archive.
    - `dsc(5) <https://manpages.debian.org/stretch/dpkg-dev/dsc.5.html>`_,
      Debian Source Control file that defines the files that are part of a
      source package.
 - `Debian mirror format <http://wiki.debian.org/RepositoryFormat>`_,
   including documentation for Packages, Sources files etc.
 - `dak documentation <https://salsa.debian.org/ftp-team/dak/tree/master/docs>`_,
   the Debian Archive Kit that manages the contents of the Debian archive.


Style guide
-----------

 - Code should be whitespace clean, pep8 & pylint compatible;
   a `.pylintrc` configuration file is provided and will one day be
   added to the CI process. (Where pep8 and pylintrc disagree about
   whitespace, follow pylint's recommendations.)

 - Write type annotations to help mypy understand the types and
   ensure that mypy is happy with the code.

 - Write tests. For everything.

 - Write docstrings in rst format so that sphinx can generate API
   documentation.

The pylint and mypy tools can be run easily from debian/rules to track code
quality::

        $ ./debian/rules qa


Test suite
----------

Please make sure all tests in the test suite pass after any change is made.

Adding a test that exposes a given bug and then fixing the bug (and hence the
test suite) is the preferred method for bug fixing. Please reference the bug
number and describe the problem and solution in the comments for the bug so
that those who come after you can understand both 'what' and 'why'.

The tests use absolute imports and do not alter sys.path so that they can be
used to test either the installed package or the current working tree. Tests
can be run either from the top-level directory or from the lib/ directory:

Run all tests from the top most directory of the source package::

        $ python3 -m unittest discover lib

Or from within the lib directory::

        $ python3 -m unittest discover

        $ python3 -m unittest debian/tests/test_deb822.py

Or by using setup.py::

        $ python3 setup.py test

The tests are run as part of the package build and also as a CI job on
salsa.debian.org. Tests will be run against merge requests automatically.
Running the tests with different encodings specified in the environment
(using LC_ALL) is a good way of catching errors in handling the encoding
of files.


Uploading
---------

When uploading the package, it should be uploaded both to Debian and also to
PyPI. Please upload the source tarball (sdist) and also an egg (bdist_egg)
and a wheel (bdist_wheel) for both Python 2 and Python 3. The python-wheel and
python3-wheel packages need to be installed to build the wheels.

The following developers have access to the PyPI project to be able to
upload it.

 *   pkern
 *   stuart

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

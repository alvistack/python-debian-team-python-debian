Documentation for the `debian` module
======================================

The `debian` Python modules work with Debian-related data formats,
providing a means to read data from files involved in Debian packaging,
and the distribution of Debian packages. The ability to create or edit
the files is also available for some formats.

Currently handled are:
  * Debtags information (:mod:`debian.debtags` module)
  * debian/changelog (:mod:`debian.changelog` module)
  * Packages files, pdiffs (:mod:`debian.debian_support` module)
  * Control files of single or multiple RFC822-style paragraphs, e.g.
    debian/control, .changes, .dsc, Packages, Sources, Release, etc.
    (:mod:`debian.deb822` module)
  * Raw .deb and .ar files, with (read-only) access to contained
    files and meta-information (:mod:`debian.debfile` module)


Contents:

.. toctree::
   :maxdepth: 1

   api/debian
   api/debian.arfile
   api/debian.changelog
   api/debian.copyright
   api/debian.deb822
   api/debian.debfile
   api/debian.debian_support
   api/debian.debtags
   api/debian.deprecation


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`


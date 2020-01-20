#! /usr/bin/python
## vim: fileencoding=utf-8

# Copyright (C) 2006 Adeodato Simó <dato@net.com.org.es>
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

from __future__ import absolute_import

import email.utils
import io
import os
import os.path
import re
import sys
import tempfile
if sys.version_info[0] >= 3:
    import unittest
else:
    import unittest2 as unittest
import warnings

import six

if six.PY3:
    from io import BytesIO, StringIO
else:
    from StringIO import StringIO
    BytesIO = StringIO

import apt_pkg   #type: ignore

from debian import deb822
from debian.debian_support import Version


UNPARSED_PACKAGE = '''\
Package: mutt
Priority: standard
Section: mail
Installed-Size: 4471
Maintainer: Adeodato Simó <dato@net.com.org.es>
Architecture: i386
Version: 1.5.12-1
Replaces: mutt-utf8
Provides: mail-reader, imap-client
Depends: libc6 (>= 2.3.6-6), libdb4.4, libgnutls13 (>= 1.4.0-0), libidn11 (>= 0.5.18), libncursesw5 (>= 5.4-5), libsasl2 (>= 2.1.19.dfsg1), exim4 | mail-transport-agent
Recommends: locales, mime-support
Suggests: urlview, aspell | ispell, gnupg, mixmaster, openssl, ca-certificates
Conflicts: mutt-utf8
Filename: pool/main/m/mutt/mutt_1.5.12-1_i386.deb
Size: 1799444
MD5sum: d4a9e124beea99d8124c8e8543d22e9a
SHA1: 5e3c295a921c287cf7cb3944f3efdcf18dd6701a
SHA256: 02853602efe21d77cd88056a4e2a4350f298bcab3d895f5f9ae02aacad81442b
Description: text-based mailreader supporting MIME, GPG, PGP and threading
 Mutt is a sophisticated text-based Mail User Agent. Some highlights:
 .
  * MIME support (including RFC1522 encoding/decoding of 8-bit message
    headers and UTF-8 support).
  * PGP/MIME support (RFC 2015).
  * Advanced IMAP client supporting SSL encryption and SASL authentication.
  * POP3 support.
  * Mailbox threading (both strict and non-strict).
  * Default keybindings are much like ELM.
  * Keybindings are configurable; Mush and PINE-like ones are provided as
    examples.
  * Handles MMDF, MH and Maildir in addition to regular mbox format.
  * Messages may be (indefinitely) postponed.
  * Colour support.
  * Highly configurable through easy but powerful rc file.
Tag: interface::text-mode, made-of::lang:c, mail::imap, mail::pop, mail::user-agent, protocol::imap, protocol::ipv6, protocol::pop, protocol::ssl, role::sw:client, uitoolkit::ncurses, use::editing, works-with::mail
Task: mail-server
'''
        

PARSED_PACKAGE = deb822.Deb822Dict([
    ('Package', 'mutt'),
    ('Priority', 'standard'),
    ('Section', 'mail'),
    ('Installed-Size', '4471'),
    ('Maintainer', 'Adeodato Simó <dato@net.com.org.es>'),
    ('Architecture', 'i386'),
    ('Version', '1.5.12-1'),
    ('Replaces', 'mutt-utf8'),
    ('Provides', 'mail-reader, imap-client'),
    ('Depends', 'libc6 (>= 2.3.6-6), libdb4.4, libgnutls13 (>= 1.4.0-0), libidn11 (>= 0.5.18), libncursesw5 (>= 5.4-5), libsasl2 (>= 2.1.19.dfsg1), exim4 | mail-transport-agent'),
    ('Recommends', 'locales, mime-support'),
    ('Suggests', 'urlview, aspell | ispell, gnupg, mixmaster, openssl, ca-certificates'),
    ('Conflicts', 'mutt-utf8'),
    ('Filename', 'pool/main/m/mutt/mutt_1.5.12-1_i386.deb'),
    ('Size', '1799444'),
    ('MD5sum', 'd4a9e124beea99d8124c8e8543d22e9a'),
    ('SHA1', '5e3c295a921c287cf7cb3944f3efdcf18dd6701a'),
    ('SHA256', '02853602efe21d77cd88056a4e2a4350f298bcab3d895f5f9ae02aacad81442b'),
    ('Description', '''text-based mailreader supporting MIME, GPG, PGP and threading
 Mutt is a sophisticated text-based Mail User Agent. Some highlights:
 .
  * MIME support (including RFC1522 encoding/decoding of 8-bit message
    headers and UTF-8 support).
  * PGP/MIME support (RFC 2015).
  * Advanced IMAP client supporting SSL encryption and SASL authentication.
  * POP3 support.
  * Mailbox threading (both strict and non-strict).
  * Default keybindings are much like ELM.
  * Keybindings are configurable; Mush and PINE-like ones are provided as
    examples.
  * Handles MMDF, MH and Maildir in addition to regular mbox format.
  * Messages may be (indefinitely) postponed.
  * Colour support.
  * Highly configurable through easy but powerful rc file.'''),
    ('Tag', 'interface::text-mode, made-of::lang:c, mail::imap, mail::pop, mail::user-agent, protocol::imap, protocol::ipv6, protocol::pop, protocol::ssl, role::sw:client, uitoolkit::ncurses, use::editing, works-with::mail'),
    ('Task', 'mail-server'), ])


GPG_SIGNED = [ '''\
-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA1

%s

-----BEGIN PGP SIGNATURE-----
Version: GnuPG v1.4.3 (GNU/Linux)
Comment: Signed by Adeodato Simó <dato@net.com.org.es>

iEYEARECAAYFAkRqYxkACgkQgyNlRdHEGIKccQCgnnUgfwYjQ7xd3zGGS2y5cXKt
CcYAoOLYDF5G1h3oR1iDNyeCI6hRW03S
=Um8T
-----END PGP SIGNATURE-----
''', '''\
-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA1

%s

-----BEGIN PGP SIGNATURE-----

iEYEARECAAYFAkRqYxkACgkQgyNlRdHEGIKccQCgnnUgfwYjQ7xd3zGGS2y5cXKt
CcYAoOLYDF5G1h3oR1iDNyeCI6hRW03S
=Um8T
-----END PGP SIGNATURE-----
''',
    ]


CHANGES_FILE = six.u('''\
Format: 1.7
Date: Fri, 28 Dec 2007 17:08:48 +0100
Source: bzr-gtk
Binary: bzr-gtk
Architecture: source all
Version: 0.93.0-2
Distribution: unstable
Urgency: low
Maintainer: Debian Bazaar Maintainers <pkg-bazaar-maint@lists.alioth.debian.org>
Changed-By: Chris Lamb <chris@chris-lamb.co.uk>
Description:
 bzr-gtk    - provides graphical interfaces to Bazaar (bzr) version control
Closes: 440354 456438
Changes:
 bzr-gtk (0.93.0-2) unstable; urgency=low
 .
   [ Chris Lamb ]
   * Add patch for unclosed progress window. (Closes: #440354)
     Patch by Jean-François Fortin Tam <jeff@ecchi.ca>
   * Fix broken icons in .desktop files (Closes: #456438).
Files:
 0fd797f4138a9d4fdeb8c30597d46bc9 1003 python optional bzr-gtk_0.93.0-2.dsc
 d9523676ae75c4ced299689456f252f4 3860 python optional bzr-gtk_0.93.0-2.diff.gz
 8960459940314b21019dedd5519b47a5 168544 python optional bzr-gtk_0.93.0-2_all.deb
''')

CHECKSUM_CHANGES_FILE = '''\
Format: 1.8
Date: Wed, 30 Apr 2008 23:58:24 -0600
Source: python-debian
Binary: python-debian
Architecture: source all
Version: 0.1.10
Distribution: unstable
Urgency: low
Maintainer: Debian python-debian Maintainers <pkg-python-debian-maint@lists.alioth.debian.org>
Changed-By: John Wright <jsw@debian.org>
Description:
 python-debian - Python modules to work with Debian-related data formats
Closes: 473254 473259
Changes:
 python-debian (0.1.10) unstable; urgency=low
 .
   * debian_bundle/deb822.py, tests/test_deb822.py:
     - Do not cache _CaseInsensitiveString objects, since it causes case
       preservation issues under certain circumstances (Closes: #473254)
     - Add a test case
   * debian_bundle/deb822.py:
     - Add support for fixed-length subfields in multivalued fields.  I updated
       the Release and PdiffIndex classes to use this.  The default behavior for
       Release is that of apt-ftparchive, just because it's simpler.  Changing
       the behavior to resemble dak requires simply setting the
       size_field_behavior attribute to 'dak'.  (Ideally, deb822 would detect
       which behavior to use if given an actual Release file as input, but this
       is not implemented yet.)  (Closes: #473259)
     - Add support for Checksums-{Sha1,Sha256} multivalued fields in Dsc and
       Changes classes
   * debian/control:
     - "python" --> "Python" in the Description field
     - Change the section to "python"
Checksums-Sha1:
 d12d7c95563397ec37c0d877486367b409d849f5 1117 python-debian_0.1.10.dsc
 19efe23f688fb7f2b20f33d563146330064ab1fa 109573 python-debian_0.1.10.tar.gz
 22ff71048921a788ad9d90f9579c6667e6b3de3a 44260 python-debian_0.1.10_all.deb
Checksums-Sha256:
 aae63dfb18190558af8e71118813dd6a11157c6fd92fdc9b5c3ac370daefe5e1 1117 python-debian_0.1.10.dsc
 d297c07395ffa0c4a35932b58e9c2be541e8a91a83ce762d82a8474c4fc96139 109573 python-debian_0.1.10.tar.gz
 4c73727b6438d9ba60aeb5e314e2d8523f021da508405dc54317ad2b392834ee 44260 python-debian_0.1.10_all.deb
Files:
 469202dfd24d55a932af717c6377ee59 1117 python optional python-debian_0.1.10.dsc
 4857552b0156fdd4fa99d21ec131d3d2 109573 python optional python-debian_0.1.10.tar.gz
 81864d535c326c082de3763969c18be6 44260 python optional python-debian_0.1.10_all.deb
'''

SIGNED_CHECKSUM_CHANGES_FILE = '''\
-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA1

%s
-----BEGIN PGP SIGNATURE-----
Version: GnuPG v1.4.6 (GNU/Linux)

iD8DBQFIGWQO0UIZh3p4ZWERAug/AJ93DWD9o+1VMgPDjWn/dsmPSgTWGQCeOfZi
6LAP26zP25GAeTlKwJQ17hs=
=fwnP
-----END PGP SIGNATURE-----
'''

UNPARSED_PARAGRAPHS_WITH_COMMENTS = '''\
# Leading comments should be ignored.

Source: foo
Section: bar
# An inline comment in the middle of a paragraph should be ignored.
Priority: optional
Homepage: http://www.debian.org/
Build-Depends: debhelper,
# quux, (temporarily disabled by a comment character)
 python

# Comments in the middle shouldn't result in extra blank paragraphs either.

# Ditto.

# A comment at the top of a paragraph should be ignored.
Package: foo
Architecture: any
Description: An awesome package
  # This should still appear in the result.
  Blah, blah, blah. # So should this.
# A comment at the end of a paragraph should be ignored.

# Trailing comments shouldn't cause extra blank paragraphs.
'''

PARSED_PARAGRAPHS_WITH_COMMENTS = [
    deb822.Deb822Dict([
        ('Source', 'foo'),
        ('Section', 'bar'),
        ('Priority', 'optional'),
        ('Homepage', 'http://www.debian.org/'),
        ('Build-Depends', 'debhelper,\n python'),
    ]),
    deb822.Deb822Dict([
        ('Package', 'foo'),
        ('Architecture', 'any'),
        ('Description', 'An awesome package\n'
            '  # This should still appear in the result.\n'
            '  Blah, blah, blah. # So should this.'),
    ]),
]


def find_test_file(filename):
    """ find a test file that is located within the test suite """
    return os.path.join(os.path.dirname(__file__), filename)


KEYRING = os.path.abspath(find_test_file('test-keyring.gpg'))


def open_utf8(filename, mode='r'):
    """Open a UTF-8 text file in text mode."""
    if sys.version < '3':
        # TODO(jsw): This isn't actually doing what the docstring says.  The
        # correct code (for both 2 and 3) is
        #   io.open(filename, code=mode, encoding='utf-8')
        # but that makes a couple of other tests fail on 2.x (both related to
        # apt_pkg - not surprisingly, its behavior with unicode objects isn't
        # very consistent).
        return open(filename, mode=mode)
    else:
        return open(filename, mode=mode, encoding='UTF-8')


class TestDeb822Dict(unittest.TestCase):
    def make_dict(self):
        d = deb822.Deb822Dict()
        d['TestKey'] = 1
        d['another_key'] = 2

        return d

    def test_case_insensitive_lookup(self):
        d = self.make_dict()

        self.assertEqual(1, d['testkey'])
        self.assertEqual(2, d['Another_keY'])

    def test_case_insensitive_assignment(self):
        d = self.make_dict()
        d['testkey'] = 3

        self.assertEqual(3, d['TestKey'])
        self.assertEqual(3, d['testkey'])

        d.setdefault('foo', 4)
        self.assertEqual(4, d['Foo'])

    def test_case_preserved(self):
        d = self.make_dict()

        self.assertEqual(sorted(['another_key', 'TestKey']), sorted(d.keys()))

    def test_order_preserved(self):
        d = self.make_dict()
        d['Third_key'] = 3
        d['another_Key'] = 2.5

        keys = ['TestKey', 'another_key', 'Third_key']

        self.assertEqual(keys, list(d.keys()))
        self.assertEqual(keys, list(six.iterkeys(d)))
        self.assertEqual(list(zip(keys, d.values())), list(d.items()))

        keys2 = []
        for key in d:
            keys2.append(key)

        self.assertEqual(keys, keys2)

    def test_derived_dict_equality(self):
        d1 = self.make_dict()
        d2 = dict(d1)

        self.assertEqual(d1, d2)

    def test_unicode_key_access(self):
        d = self.make_dict()
        self.assertEqual(1, d[six.u('testkey')])


class TestDeb822(unittest.TestCase):
    def assertWellParsed(self, deb822_, dict_):
        """Check that the given Deb822 object has the very same keys and
           values as the given dict.
        """

        self.assertEqual(deb822_.keys(), dict_.keys())

        for k, v in dict_.items():
            self.assertEqual(v, deb822_[k])
        self.assertEqual(deb822_, dict_)

    @staticmethod
    def gen_random_string(length=20):
        from random import choice
        import string
        chars = string.ascii_letters + string.digits
        return ''.join([choice(chars) for i in range(length)])

    def deb822_from_format_string(self, string, dict_=PARSED_PACKAGE, cls=deb822.Deb822):
        """Construct a Deb822 object by formatting string with % dict.
        
        Returns the formatted string, and a dict object containing only the
        keys that were used for the formatting."""

        dict_subset = DictSubset(dict_)
        string = string % dict_subset
        parsed = cls(string.splitlines())
        return parsed, dict_subset

    def test_parser(self):
        deb822_ = deb822.Deb822(UNPARSED_PACKAGE.splitlines())
        self.assertWellParsed(deb822_, PARSED_PACKAGE)

    def test_parser_with_newlines(self):
        deb822_ = deb822.Deb822([ l+'\n' for l in UNPARSED_PACKAGE.splitlines()])
        self.assertWellParsed(deb822_, PARSED_PACKAGE)

    def test_strip_initial_blanklines(self):
        deb822_ = deb822.Deb822(['\n'] * 3 + UNPARSED_PACKAGE.splitlines())
        self.assertWellParsed(deb822_, PARSED_PACKAGE)

    def test_gpg_stripping(self):
        for string in GPG_SIGNED:
            unparsed_with_gpg = string % UNPARSED_PACKAGE
            deb822_ = deb822.Deb822(unparsed_with_gpg.splitlines())
            self.assertWellParsed(deb822_, PARSED_PACKAGE)

    @unittest.skipUnless(os.path.exists('/usr/bin/gpgv'), "gpgv not installed")
    def test_gpg_info(self):
        unparsed_with_gpg = SIGNED_CHECKSUM_CHANGES_FILE % CHECKSUM_CHANGES_FILE
        deb822_from_str = deb822.Dsc(unparsed_with_gpg)
        result_from_str = deb822_from_str.get_gpg_info(keyrings=[KEYRING])
        deb822_from_file = deb822.Dsc(StringIO(unparsed_with_gpg))
        result_from_file = deb822_from_file.get_gpg_info(keyrings=[KEYRING])
        deb822_from_lines = deb822.Dsc(unparsed_with_gpg.splitlines())
        result_from_lines = deb822_from_lines.get_gpg_info(keyrings=[KEYRING])

        valid = {
         'GOODSIG':  ['D14219877A786561', 'John Wright <john.wright@hp.com>'],
         'VALIDSIG': ['8FEFE900783CF175827C2F65D14219877A786561', '2008-05-01',
                      '1209623566', '0', '3', '0', '17', '2', '01',
                      '8FEFE900783CF175827C2F65D14219877A786561'],
         'SIG_ID':   ['j3UjSpdky92fcQISbm8W5PlwC/g', '2008-05-01',
                      '1209623566'],
        }

        for result in result_from_str, result_from_file, result_from_lines:
            # The second part of the GOODSIG field could change if the primary
            # uid changes, so avoid checking that.  Also, the first part of the
            # SIG_ID field has undergone at least one algorithm changein gpg,
            # so don't bother testing that either.
            self.assertEqual(set(result.keys()), set(valid.keys()))
            self.assertEqual(result['GOODSIG'][0], valid['GOODSIG'][0])
            self.assertEqual(result['VALIDSIG'], valid['VALIDSIG'])
            self.assertEqual(result['SIG_ID'][1:], valid['SIG_ID'][1:])

    @unittest.skipUnless(os.path.exists('/usr/bin/gpgv'), "gpgv not installed")
    def test_gpg_info2(self):
        with open(find_test_file('test_Dsc.badsig'), mode='rb') as f:
            dsc = deb822.Dsc(f)
            i = dsc.get_gpg_info(keyrings=[KEYRING])
            self.assertTrue(i.valid())
            self.assertEqual('at', dsc['Source'])

    def test_iter_paragraphs_array(self):
        text = (UNPARSED_PACKAGE + '\n\n\n' + UNPARSED_PACKAGE).splitlines()

        for d in deb822.Deb822.iter_paragraphs(text):
            self.assertWellParsed(d, PARSED_PACKAGE)

    def test_iter_paragraphs_file_io(self):
        text = StringIO(UNPARSED_PACKAGE + '\n\n\n' + UNPARSED_PACKAGE)

        for d in deb822.Deb822.iter_paragraphs(text, use_apt_pkg=False):
            self.assertWellParsed(d, PARSED_PACKAGE)

        with self.assertWarns(UserWarning):
            # The StringIO is not a real file so this will raise a warning
            for d in deb822.Deb822.iter_paragraphs(text, use_apt_pkg=True):
                self.assertWellParsed(d, PARSED_PACKAGE)

    def test_iter_paragraphs_file(self):
        text = StringIO()
        text.write(UNPARSED_PACKAGE)
        text.write('\n\n\n')
        text.write(UNPARSED_PACKAGE)

        with tempfile.NamedTemporaryFile() as fh:
            if sys.version_info[0] >= 3:
                txt = text.getvalue().encode('UTF-8')
            else:
                txt = text.getvalue()
            fh.write(txt)

            fh.seek(0)
            for d in deb822.Deb822.iter_paragraphs(fh, use_apt_pkg=False):
                self.assertWellParsed(d, PARSED_PACKAGE)

            fh.seek(0)
            for d in deb822.Deb822.iter_paragraphs(fh, use_apt_pkg=True):
                self.assertWellParsed(d, PARSED_PACKAGE)


    def test_iter_paragraphs_with_gpg(self):
        for string in GPG_SIGNED:
            string = string % UNPARSED_PACKAGE
            text = (string + '\n\n\n' + string).splitlines()

            count = len([self.assertWellParsed(d, PARSED_PACKAGE) \
                            for d in deb822.Deb822.iter_paragraphs(text)])
            self.assertEqual(2, count)

    def test_iter_paragraphs_bytes(self):
        text = (UNPARSED_PACKAGE + '\n\n\n' + UNPARSED_PACKAGE)
        if six.PY2:
            binary = text
        else:
            binary = text.encode('utf-8')

        for d in deb822.Deb822.iter_paragraphs(binary):
            self.assertWellParsed(d, PARSED_PACKAGE)

    def test_iter_paragraphs_with_extra_whitespace(self):
        """ Paragraphs splitting when stray whitespace is between

        From policy §5.1:

            The paragraphs are separated by empty lines. Parsers may accept
            lines consisting solely of spaces and tabs as paragraph separators,
            but control files should use empty lines.

        On the principle of "be strict in what you send; be generous in
        what you receive", deb822 should permit such extra whitespace between
        deb822 stanzas. See #715558 for further details.

        However, when dealing with Packages and Sources files, the behaviour
        of apt is to not split on whitespace-only lines, and so the internal
        parser must be able to avoid doing so when dealing with these data.
        See #913274 for further details.
        """
        for extra_space in (" ", "  ", "\t"):
            text = six.u(UNPARSED_PACKAGE) + '%s\n' % extra_space + \
                        six.u(UNPARSED_PACKAGE)

            fd, filename = tempfile.mkstemp()
            fp = os.fdopen(fd, 'wb')
            fp.write(text.encode('utf-8'))
            fp.close()

            def test_count(cmd, expected, *args, **kwargs):
                #print("\n", cmd.__class__, expected)
                with open_utf8(filename) as fh:
                    count = len(list(cmd(fh, *args, **kwargs)))
                    self.assertEqual(
                        expected,
                        count,
                        "Wrong number paragraphs were found: expected {expected}, got {count}".format(
                            count=count,
                            expected=expected,
                        )
                    )

            try:
                # apt_pkg not used, should split
                test_count(deb822.Deb822.iter_paragraphs, 2)
                test_count(deb822.Deb822.iter_paragraphs, 2, use_apt_pkg=False)

                # apt_pkg used, should not split
                test_count(deb822.Deb822.iter_paragraphs, 1, use_apt_pkg=True)

                # Specialised iter_paragraphs force use of apt_pkg and don't split
                test_count(deb822.Packages.iter_paragraphs, 1, use_apt_pkg=True)
                test_count(deb822.Sources.iter_paragraphs, 1, use_apt_pkg=True)
                test_count(deb822.Packages.iter_paragraphs, 1, use_apt_pkg=False)
                test_count(deb822.Sources.iter_paragraphs, 1, use_apt_pkg=False)

                # Explicitly set internal parser to not split
                strict = {'whitespace-separates-paragraphs': False}
                test_count(deb822.Packages.iter_paragraphs, 1, use_apt_pkg=False, strict=strict)
                test_count(deb822.Sources.iter_paragraphs, 1, use_apt_pkg=False, strict=strict)

                # Explicitly set internal parser to split
                strict = {'whitespace-separates-paragraphs': True}
                test_count(deb822.Packages.iter_paragraphs, 2, use_apt_pkg=False, strict=strict)
                test_count(deb822.Sources.iter_paragraphs, 2, use_apt_pkg=False, strict=strict)

            finally:
                os.remove(filename)

    def _test_iter_paragraphs(self, filename, cls, **kwargs):
        """Ensure iter_paragraphs consistency"""
        
        f = open(filename, 'rb')
        packages_content = f.read()
        f.close()
        # XXX: The way multivalued fields parsing works, we can't guarantee
        # that trailing whitespace is reproduced.
        packages_content = b"\n".join([line.rstrip() for line in
                                       packages_content.splitlines()] + [b''])

        s = BytesIO()
        l = []
        f = open_utf8(filename)
        for p in cls.iter_paragraphs(f, **kwargs):
            p.dump(s)
            s.write(b"\n")
            l.append(p)
        f.close()
        self.assertEqual(s.getvalue(), packages_content)
        if kwargs["shared_storage"] is False:
            # If shared_storage is False, data should be consistent across
            # iterations -- i.e. we can use "old" objects
            s = BytesIO()
            for p in l:
                p.dump(s)
                s.write(b"\n")
            self.assertEqual(s.getvalue(), packages_content)

    def test_iter_paragraphs_apt_shared_storage_packages(self):
        self._test_iter_paragraphs(find_test_file("test_Packages"),
                                   deb822.Packages,
                                   use_apt_pkg=True, shared_storage=True)
    def test_iter_paragraphs_apt_no_shared_storage_packages(self):
        self._test_iter_paragraphs(find_test_file("test_Packages"),
                                   deb822.Packages,
                                   use_apt_pkg=True, shared_storage=False)
    def test_iter_paragraphs_no_apt_no_shared_storage_packages(self):
        self._test_iter_paragraphs(find_test_file("test_Packages"),
                                   deb822.Packages,
                                   use_apt_pkg=False, shared_storage=False)

    def test_iter_paragraphs_apt_shared_storage_sources(self):
        self._test_iter_paragraphs(find_test_file("test_Sources"),
                                   deb822.Sources,
                                   use_apt_pkg=True, shared_storage=True)
    def test_iter_paragraphs_apt_no_shared_storage_sources(self):
        self._test_iter_paragraphs(find_test_file("test_Sources"),
                                   deb822.Sources,
                                   use_apt_pkg=True, shared_storage=False)
    def test_iter_paragraphs_no_apt_no_shared_storage_sources(self):
        self._test_iter_paragraphs(find_test_file("test_Sources"),
                                   deb822.Sources,
                                   use_apt_pkg=False, shared_storage=False)

    def test_parser_empty_input(self):
        self.assertEqual({}, deb822.Deb822([]))

    def test_iter_paragraphs_empty_input(self):
        generator = deb822.Deb822.iter_paragraphs([])
        self.assertRaises(StopIteration, next, generator)

    def test_parser_limit_fields(self):
        wanted_fields = [ 'Package', 'MD5sum', 'Filename', 'Description' ]
        deb822_ = deb822.Deb822(UNPARSED_PACKAGE.splitlines(), wanted_fields)

        self.assertEqual(sorted(wanted_fields), sorted(deb822_.keys()))

        for key in wanted_fields:
            self.assertEqual(PARSED_PACKAGE[key], deb822_[key])

    def test_iter_paragraphs_limit_fields(self):
        wanted_fields = [ 'Package', 'MD5sum', 'Filename', 'Tag' ]

        for deb822_ in deb822.Deb822.iter_paragraphs(
                UNPARSED_PACKAGE.splitlines(), wanted_fields):

            self.assertEqual(sorted(wanted_fields), sorted(deb822_.keys()))

            for key in wanted_fields:
                self.assertEqual(PARSED_PACKAGE[key], deb822_[key])

    def test_dont_assume_trailing_newline(self):
        deb822a = deb822.Deb822(['Package: foo'])
        deb822b = deb822.Deb822(['Package: foo\n'])

        self.assertEqual(deb822a['Package'], deb822b['Package'])

        deb822a = deb822.Deb822(['Description: foo\n', 'bar'])
        deb822b = deb822.Deb822(['Description: foo', 'bar\n'])

        self.assertEqual(deb822a['Description'], deb822b['Description'])

    def test__delitem__(self):
        parsed = deb822.Deb822(UNPARSED_PACKAGE.splitlines())
        deriv = deb822.Deb822(_parsed=parsed)
        dict_ = PARSED_PACKAGE.copy()

        for key in ('Package', 'MD5sum', 'Description'):
            del dict_[key]
            for d in (parsed, deriv):
                del d[key]
                d.keys() # ensure this does not raise error
                self.assertWellParsed(d, dict_)


    def test_policy_compliant_whitespace(self):
        string = (
            'Package: %(Package)s\n'
            'Version :%(Version)s \n'
            'Priority:%(Priority)s\t \n'
            'Section \t :%(Section)s \n'
            'Empty-Field:        \t\t\t\n'
            'Multiline-Field : a \n b\n c\n'
        ) % PARSED_PACKAGE

        deb822_ = deb822.Deb822(string.splitlines())
        dict_   = PARSED_PACKAGE.copy()

        dict_['Empty-Field'] = ''
        dict_['Multiline-Field'] = 'a\n b\n c' # XXX should be 'a\nb\nc'?

        for k, v in deb822_.items():
            self.assertEqual(dict_[k], v)
    
    def test_case_insensitive(self):
        # PARSED_PACKAGE is a deb822.Deb822Dict object, so we can test
        # it directly
        self.assertEqual(PARSED_PACKAGE['Architecture'],
                         PARSED_PACKAGE['architecture'])

        c_i_dict = deb822.Deb822Dict()

        test_string = self.gen_random_string()
        c_i_dict['Test-Key'] = test_string
        self.assertEqual(test_string, c_i_dict['test-key'])

        test_string_2 = self.gen_random_string()
        c_i_dict['TeSt-KeY'] = test_string_2
        self.assertEqual(test_string_2, c_i_dict['Test-Key'])

        deb822_ = deb822.Deb822(StringIO(UNPARSED_PACKAGE))
        # deb822_.keys() will return non-normalized keys
        for k in deb822_:
            self.assertEqual(deb822_[k], deb822_[k.lower()])

    def test_multiline_trailing_whitespace_after_colon(self):
        """Trailing whitespace after the field name on multiline fields

        If the field's value starts with a newline (e.g. on MD5Sum fields in
        Release files, or Files field in .dsc's, the dumped string should not
        have a trailing space after the colon.  If the value does not start
        with a newline (e.g. the control file Description field), then there
        should be a space after the colon, as with non-multiline fields.
        """
        
        # bad_re: match a line that starts with a "Field:", and ends in
        # whitespace
        bad_re = re.compile(r"^\S+:\s+$")
        for cls in deb822.Deb822, deb822.Changes:
            parsed = cls(CHANGES_FILE.splitlines())
            for line in parsed.dump().splitlines():
                self.assertTrue(bad_re.match(line) is None,
                                "There should not be trailing whitespace "
                                "after the colon in a multiline field "
                                "starting with a newline")

        
        control_paragraph = """Package: python-debian
Architecture: all
Depends: ${python:Depends}
Suggests: python-apt
Provides: python-deb822
Conflicts: python-deb822
Replaces: python-deb822
Description: python modules to work with Debian-related data formats
 This package provides python modules that abstract many formats of Debian
 related files. Currently handled are:
  * Debtags information (debian_bundle.debtags module)
  * debian/changelog (debian_bundle.changelog module)
  * Packages files, pdiffs (debian_bundle.debian_support module)
  * Control files of single or multple RFC822-style paragraphs, e.g
    debian/control, .changes, .dsc, Packages, Sources, Release, etc.
    (debian_bundle.deb822 module)
"""
        parsed_control = deb822.Deb822(control_paragraph.splitlines())
        field_re = re.compile(r"^\S+:")
        field_with_space_re = re.compile(r"^\S+: ")
        for line in parsed_control.dump().splitlines():
            if field_re.match(line):
                self.assertTrue(field_with_space_re.match(line),
                                "Multiline fields that do not start with "
                                "newline should have a space between the "
                                "colon and the beginning of the value")

    def test_blank_value(self):
        """Fields with blank values are parsable--so they should be dumpable"""

        d = deb822.Deb822()
        d['Foo'] = 'bar'
        d['Baz'] = ''
        d['Another-Key'] = 'another value'
        
        # Previous versions would raise an exception here -- this makes the
        # test fail and gives useful information, so I won't try to wrap around
        # it.
        dumped = d.dump()
        
        # May as well make sure the resulting string is what we want
        expected = "Foo: bar\nBaz:\nAnother-Key: another value\n"
        self.assertEqual(dumped, expected)

    def test_copy(self):
        """The copy method of Deb822 should return another Deb822 object"""
        d = deb822.Deb822()
        d['Foo'] = 'bar'
        d['Bar'] = 'baz'
        d_copy = d.copy()

        self.assertTrue(isinstance(d_copy, deb822.Deb822))
        expected_dump = "Foo: bar\nBar: baz\n"
        self.assertEqual(d_copy.dump(), expected_dump)

    def test_bug457929_multivalued_dump_works(self):
        """dump() was not working in multivalued classes, see #457929."""
        changesobj = deb822.Changes(CHANGES_FILE.splitlines())
        self.assertEqual(CHANGES_FILE, changesobj.dump())

    def test_bug487902_multivalued_checksums(self):
        """New multivalued field Checksums was not handled correctly, see #487902."""
        changesobj = deb822.Changes(CHECKSUM_CHANGES_FILE.splitlines())
        self.assertEqual(CHECKSUM_CHANGES_FILE, changesobj.dump())

    def test_case_preserved_in_input(self):
        """The field case in the output from dump() should be the same as the
        input, even if multiple Deb822 objects have been created using
        different case conventions.

        This is related to bug 473254 - the fix for this issue is probably the
        same as the fix for that bug.
        """
        input1 = "Foo: bar\nBaz: bang\n"
        input2 = "foo: baz\nQux: thud\n"
        d1 = deb822.Deb822(input1.splitlines())
        d2 = deb822.Deb822(input2.splitlines())
        self.assertEqual(input1, d1.dump())
        self.assertEqual(input2, d2.dump())

        d3 = deb822.Deb822()
        if 'some-test-key' not in d3:
            d3['Some-Test-Key'] = 'some value'
        self.assertEqual(d3.dump(), "Some-Test-Key: some value\n")

    def test_unicode_values(self):
        """Deb822 objects should contain only unicode values

        (Technically, they are allowed to contain any type of object, but when
        parsed from files, and when only string-type objects are added, the
        resulting object should have only unicode values.)
        """

        objects = []
        objects.append(deb822.Deb822(UNPARSED_PACKAGE))
        objects.append(deb822.Deb822(CHANGES_FILE))
        with open_utf8(find_test_file('test_Packages')) as f:
            objects.extend(deb822.Deb822.iter_paragraphs(f))
        with open_utf8(find_test_file('test_Packages')) as f:
            objects.extend(deb822.Packages.iter_paragraphs(f))
        with open_utf8(find_test_file('test_Sources')) as f:
            objects.extend(deb822.Deb822.iter_paragraphs(f))
        with open(find_test_file('test_Sources.iso8859-1'), 'rb') as f:
            objects.extend(deb822.Deb822.iter_paragraphs(
                f, encoding="iso8859-1"))
        for d in objects:
            for value in d.values():
                self.assertTrue(isinstance(value, six.text_type))

        # The same should be true for Sources and Changes except for their
        # _multivalued fields
        multi = []
        multi.append(deb822.Changes(CHANGES_FILE))
        multi.append(deb822.Changes(SIGNED_CHECKSUM_CHANGES_FILE
                                    % CHECKSUM_CHANGES_FILE))
        with open_utf8(find_test_file('test_Sources')) as f:
            multi.extend(deb822.Sources.iter_paragraphs(f))
        for d in multi:
            for key, value in d.items():
                if key.lower() not in d.__class__._multivalued_fields:
                    self.assertTrue(isinstance(value, six.text_type))

    def test_encoding_integrity(self):
        with open_utf8(find_test_file('test_Sources')) as f:
            utf8 = list(deb822.Deb822.iter_paragraphs(f))
        with open(find_test_file('test_Sources.iso8859-1'), 'rb') as f:
            latin1 = list(deb822.Deb822.iter_paragraphs(
                f, encoding='iso8859-1'))

        # dump() with no fd returns a unicode object - both should be identical
        self.assertEqual(len(utf8), len(latin1))
        for i in range(len(utf8)):
            self.assertEqual(utf8[i].dump(), latin1[i].dump())

        # XXX: The way multiline fields parsing works, we can't guarantee
        # that trailing whitespace is reproduced.
        with open(find_test_file('test_Sources'), 'rb') as f:
            utf8_contents = b"\n".join([line.rstrip() for line in f] + [b''])
        with open(find_test_file('test_Sources.iso8859-1'), 'rb') as f:
            latin1_contents = b"\n".join([line.rstrip() for line in f] + [b''])

        utf8_to_latin1 = BytesIO()
        for d in utf8:
            d.dump(fd=utf8_to_latin1, encoding='iso8859-1')
            utf8_to_latin1.write(b"\n")

        latin1_to_utf8 = BytesIO()
        for d in latin1:
            d.dump(fd=latin1_to_utf8, encoding='utf-8')
            latin1_to_utf8.write(b"\n")

        self.assertEqual(utf8_contents, latin1_to_utf8.getvalue())
        self.assertEqual(latin1_contents, utf8_to_latin1.getvalue())

    def test_mixed_encodings(self):
        """Test that we can handle a simple case of mixed encodings

        In general, this isn't guaranteed to work.  It uses the chardet
        package, which tries to determine heuristically the encoding of the
        text given to it.  But as far as I've seen, it's reliable for mixed
        latin1 and utf-8 in maintainer names in old Sources files...
        """

        # Avoid spitting out the encoding warning during testing.
        warnings.filterwarnings(action='ignore', category=UnicodeWarning)

        filename = find_test_file('test_Sources.mixed_encoding')
        with open(filename, 'rb') as f1, open(filename, 'rb') as f2:
            for paragraphs in [
                        deb822.Sources.iter_paragraphs(f1),
                        deb822.Sources.iter_paragraphs(f2, use_apt_pkg=False)
                    ]:
                p1 = next(paragraphs)
                self.assertEqual(p1['maintainer'],
                                six.u('Adeodato Sim\xf3 <dato@net.com.org.es>'))
                p2 = next(paragraphs)
                self.assertEqual(p2['uploaders'],
                                six.u('Frank K\xfcster <frank@debian.org>'))

    def test_dump_text_mode(self):
        d = deb822.Deb822(CHANGES_FILE.splitlines())
        buf = io.StringIO()
        d.dump(fd=buf, text_mode=True)
        self.assertEqual(CHANGES_FILE, buf.getvalue())


    def test_bug597249_colon_as_first_value_character(self):
        """Colon should be allowed as the first value character. See #597249.
        """

        data = 'Foo: : bar'
        parsed = {'Foo': ': bar'}
        self.assertWellParsed(deb822.Deb822(data), parsed)

    @staticmethod
    def _dictset(d, key, value):
        d[key] = value

    def test_field_value_ends_in_newline(self):
        """Field values are not allowed to end with newlines"""

        d = deb822.Deb822()
        self.assertRaises(ValueError, self._dictset, d, 'foo', 'bar\n')
        self.assertRaises(ValueError, self._dictset, d, 'foo', 'bar\nbaz\n')

    def test_field_value_contains_blank_line(self):
        """Field values are not allowed to contain blank lines"""

        d = deb822.Deb822()
        self.assertRaises(ValueError, self._dictset, d, 'foo', 'bar\n\nbaz')
        self.assertRaises(ValueError, self._dictset, d, 'foo', '\n\nbaz')

    def test_multivalued_field_contains_newline(self):
        """Multivalued field components are not allowed to contain newlines"""

        d = deb822.Dsc()
        # We don't check at set time, since one could easily modify the list
        # without deb822 knowing.  We instead check at get time.
        d['Files'] = [{'md5sum': 'deadbeef', 'size': '9605', 'name': 'bad\n'}]
        self.assertRaises(ValueError, d.get_as_string, 'files')

    def _test_iter_paragraphs_comments(self, paragraphs):
        self.assertEqual(len(paragraphs), len(PARSED_PARAGRAPHS_WITH_COMMENTS))
        for i in range(len(paragraphs)):
            self.assertWellParsed(paragraphs[i],
                                  PARSED_PARAGRAPHS_WITH_COMMENTS[i])

    def test_iter_paragraphs_comments_use_apt_pkg(self):
        """ apt_pkg does not support comments within multiline fields

        This test checks that a file with comments inside multiline fields
        generates an error from the apt_pkg parser.

        See also https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=750247#35
                 https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=807351
        """
        try:
            fd, filename = tempfile.mkstemp()
            fp = os.fdopen(fd, 'wb')
            fp.write(UNPARSED_PARAGRAPHS_WITH_COMMENTS.encode('utf-8'))
            fp.close()

            with open_utf8(filename) as fh:
                with self.assertRaises(apt_pkg.Error):
                    list(deb822.Deb822.iter_paragraphs(fh, use_apt_pkg=True))
        finally:
            os.remove(filename)

    def test_iter_paragraphs_comments_native(self):
        paragraphs = list(deb822.Deb822.iter_paragraphs(
            UNPARSED_PARAGRAPHS_WITH_COMMENTS.splitlines(), use_apt_pkg=False))
        self._test_iter_paragraphs_comments(paragraphs)

    def test_iter_paragraphs_string_comments_native(self):
        paragraphs = list(deb822.Deb822.iter_paragraphs(
            UNPARSED_PARAGRAPHS_WITH_COMMENTS, use_apt_pkg=False))
        self._test_iter_paragraphs_comments(paragraphs)

    def test_release(self):
        with open(find_test_file('test_Release')) as f:
            release = deb822.Release(f)
        self.assertEqual(release['Codename'], 'sid')
        self.assertEqual(len(release['SHA1']), 61)
        self.assertEqual(len(release['SHA256']), 61)
        self.assertEqual(len(release['SHA512']), 61)
        self.assertEqual(release['SHA512'][0]['size'], '113433')

    def test_changes_binary_mode(self):
        """Trivial parse test for a signed file in binary mode"""
        with io.open(find_test_file('test_Changes'), 'rb') as f:
            changes = deb822.Changes(f)
        self.assertEqual('python-debian', changes['Source'])

    def test_changes_text_mode(self):
        """Trivial parse test for a signed file in text mode"""
        with io.open(find_test_file('test_Changes'), 'r', encoding='utf-8') as f:
            changes = deb822.Changes(f)
        self.assertEqual('python-debian', changes['Source'])

    def test_removals(self):
        with open(find_test_file('test_removals.822')) as f:
            removals = deb822.Removals.iter_paragraphs(f)
            r = next(removals)
            self.assertEqual(r['suite'], 'unstable')
            self.assertEqual(r['date'], u'Wed, 01 Jan 2014 17:03:54 +0000')
            self.assertEqual(r.date.strftime('%s'), '1388595834')
            self.assertEqual(len(r.binaries), 1)
            self.assertEqual(r.binaries[0]['package'], 'libzoom-ruby')
            self.assertEqual(r.binaries[0]['version'], '0.4.1-5')
            self.assertEqual(r.binaries[0]['architectures'], set(['all']))
            r = next(removals)
            self.assertEqual(len(r.binaries), 3)
            r = next(removals)
            self.assertEqual(r['bug'], '753912')
            self.assertEqual(r.bug, [753912])
            self.assertEqual(r.also_wnpp, [123456])
            r = next(removals)
            self.assertEqual(r.binaries[0]['architectures'],
                             set(['amd64', 'armel', 'armhf', 'hurd-i386',
                                  'i386', 'kfreebsd-amd64', 'kfreebsd-i386',
                                  'mips', 'mipsel', 'powerpc', 's390x',
                                  'sparc']))


class TestPkgRelations(unittest.TestCase):
    # TODO(jsw): Stop overriding this for Python versions that actually include
    # assertWarns.  Unfortunately, that's not possible right now because for
    # some reason sys.modules changes size during case.py's iteration of it in
    # _AssertWarnsContext.__enter__ (python3.4).
    def assertWarns(self, warning, callable, *args, **kwds):
        with warnings.catch_warnings(record=True) as warning_list:
            warnings.simplefilter('always')

            result = callable(*args, **kwds)

            self.assertTrue(any(item.category == warning for item in warning_list))

    def assertPkgDictEqual(self, expected, actual):
        p1keys = sorted(expected.keys())
        p2keys = sorted(actual.keys())
        self.assertEqual(p1keys, p2keys, "Different fields present in packages")
        for k in p1keys:
            self.assertEqual(expected[k], actual[k],
                            "Different for field '%s'" % k)

    @staticmethod
    def rel(dict_):
        """Modify dict_ to ensure it contains all fields from parse_relations

        Accept a dict that partially describes a package relationship and add
        to it any missing keys.

        returns: modified dict_
        """
        if 'version' not in dict_:
            dict_['version'] = None
        if 'arch' not in dict_:
            dict_['arch'] = None
        if 'archqual' not in dict_:
            dict_['archqual'] = None
        if 'restrictions' not in dict_:
            dict_['restrictions'] = None
        return dict_

    def test_packages(self):
        # make the syntax a bit more compact
        rel = TestPkgRelations.rel

        f = open(find_test_file('test_Packages'))
        pkgs = deb822.Packages.iter_paragraphs(f)
        pkg1 = next(pkgs)
        rel1 = {'breaks': [],
                'built-using': [],
                'conflicts': [],
                'depends': [
                        [rel({'name': 'file', 'archqual': 'i386'})],
                        [rel({'name': 'libc6', 'version': ('>=', '2.7-1')})],
                        [rel({'name': 'libpaper1'})],
                        [rel({'name': 'psutils'})],
                    ],
                'enhances': [],
                'pre-depends': [],
                'provides': [],
                'recommends': [
                        [rel({'name': 'bzip2'})],
                        [rel({'name': 'lpr'}),
                            rel({'name': 'rlpr'}),
                            rel({'name': 'cupsys-client'})],
                        [rel({'name': 'wdiff'})],
                    ],
                'replaces': [],
                'suggests': [
                        [rel({'name': 'emacsen-common'})],
                        [rel({'name': 'ghostscript'})],
                        [rel({'name': 'graphicsmagick-imagemagick-compat'}),
                            rel({'name': 'imagemagick'})],
                        [rel({'name': 'groff'})],
                        [rel({'name': 'gv'})],
                        [rel({'name': 'html2ps'})],
                        [rel({'name': 't1-cyrillic'})],
                        [rel({'name': 'texlive-base-bin'})],
                    ]
                }
        self.assertPkgDictEqual(rel1, pkg1.relations)
        pkg2 = next(pkgs)
        rel2 = {'breaks': [],
                'built-using': [],
                'conflicts': [],
                'depends': [
                        [rel({'name': 'lrzsz'})],
                        [rel({'name': 'openssh-client'}),
                            rel({'name': 'telnet'}),
                            rel({'name': 'telnet-ssl'})],
                        [rel({'name': 'libc6', 'version': ('>=', '2.6.1-1')})],
                        [rel({'name': 'libncurses5', 'version': ('>=', '5.6')})],
                        [rel({'name': 'libreadline5', 'version': ('>=', '5.2')})],
                    ],
                'enhances': [],
                'pre-depends': [],
                'provides': [],
                'recommends': [],
                'replaces': [],
                'suggests': []
                }
        self.assertPkgDictEqual(rel2, pkg2.relations)
        pkg3 = next(pkgs)
        dep3 = [
                [rel({'name': 'dcoprss', 'version': ('>=', '4:3.5.9-2')})],
                [rel({'name': 'kdenetwork-kfile-plugins', 'version': ('>=', '4:3.5.9-2')})],
                [rel({'name': 'kdict', 'version': ('>=', '4:3.5.9-2')})],
                [rel({'name': 'kdnssd', 'version': ('>=', '4:3.5.9-2')})],
                [rel({'name': 'kget', 'version': ('>=', '4:3.5.9-2')})],
                [rel({'name': 'knewsticker', 'version': ('>=', '4:3.5.9-2')})],
                [rel({'name': 'kopete', 'version': ('>=', '4:3.5.9-2')})],
                [rel({'name': 'kpf', 'version': ('>=', '4:3.5.9-2')})],
                [rel({'name': 'kppp', 'version': ('>=', '4:3.5.9-2')})],
                [rel({'name': 'krdc', 'version': ('>=', '4:3.5.9-2')})],
                [rel({'name': 'krfb', 'version': ('>=', '4:3.5.9-2')})],
                [rel({'name': 'ksirc', 'version': ('>=', '4:3.5.9-2')})],
                [rel({'name': 'kwifimanager', 'version': ('>=', '4:3.5.9-2')})],
                [rel({'name': 'librss1', 'version': ('>=', '4:3.5.9-2')})],
            ]
        self.assertEqual(dep3, pkg3.relations['depends'])
        f.close()

    def test_pkgrelation_str(self):
        bin_rels = [
            'file, libc6 (>= 2.7-1), libpaper1, psutils, '
            'perl:any, python:native'
            ]
        src_rels = [
            'apache2-src (>= 2.2.9), libaprutil1-dev, '
            'libcap-dev [!kfreebsd-i386 !kfreebsd-amd64 !hurd-i386], '
            'autoconf <!cross>, '
            'debhelper (>> 5.0.0) <!stage1> <!cross !stage2>'
            ]
        for bin_rel in bin_rels:
            self.assertEqual(bin_rel,
                    deb822.PkgRelation.str(deb822.PkgRelation.parse_relations(
                            bin_rel)))
        for src_rel in src_rels:
            self.assertEqual(src_rel,
                    deb822.PkgRelation.str(deb822.PkgRelation.parse_relations( \
                            src_rel)))
        self.assertWarns(UserWarning, deb822.PkgRelation.parse_relations,
                    "foo bar")

    def test_sources(self):
        # make the syntax a bit more compact
        rel = TestPkgRelations.rel

        f = open_utf8(find_test_file('test_Sources'))
        pkgs = deb822.Sources.iter_paragraphs(f)
        pkg1 = next(pkgs)
        rel1 = {'build-conflicts': [],
                'build-conflicts-indep': [],
                'build-depends': [
                        [rel({'name': 'apache2-src', 'version': ('>=', '2.2.9')})],
                        [rel({'name': 'libaprutil1-dev'})],
                        [rel({'arch': [(False, 'kfreebsd-i386'), (False, 'kfreebsd-amd64'), (False, 'hurd-i386')],
                            'name': 'libcap-dev'})],
                        [rel({'name': 'autoconf'})],
                        [rel({'name': 'debhelper', 'version': ('>>', '5.0.0')})],
                    ],
                'build-depends-indep': [],
                'binary': [
                        [rel({'name': 'apache2-mpm-itk'})]
                    ]
                }
        self.assertPkgDictEqual(rel1, pkg1.relations)
        pkg2 = next(pkgs)
        rel2 = {'build-conflicts': [],
                'build-conflicts-indep': [],
                'build-depends': [
                        [rel({'name': 'dpkg-dev', 'version': ('>=', '1.13.9')})],
                        [rel({'name': 'autoconf', 'version': ('>=', '2.13')})],
                        [rel({'name': 'bash'})],
                        [rel({'name': 'bison', 'archqual': 'amd64'})],
                        [rel({'name': 'flex'})],
                        [rel({'name': 'gettext', 'archqual': 'any'})],
                        [rel({'name': 'texinfo',
                            'restrictions': [
                                [(False, 'stage1')],
                                [(False, 'stage2'),
                                 (False, 'cross')]
                            ]})],
                        [rel({'arch': [(True, 'hppa')], 'name': 'expect-tcl8.3',
                            'version': ('>=', '5.32.2'),
                            'restrictions': [[(False, 'stage1')]]})],
                        [rel({'name': 'dejagnu', 'version': ('>=', '1.4.2-1.1'), 'arch': None})],
                        [rel({'name': 'dpatch'})],
                        [rel({'name': 'file'})],
                        [rel({'name': 'bzip2', 'archqual': 'native'})],
                        [rel({'name': 'lsb-release'})],
                    ],
                'build-depends-indep': [],
                'binary': [
                        [rel({'name': 'binutils'})],
                        [rel({'name': 'binutils-dev'})],
                        [rel({'name': 'binutils-multiarch'})],
                        [rel({'name': 'binutils-hppa64'})],
                        [rel({'name': 'binutils-spu'})],
                        [rel({'name': 'binutils-doc'})],
                        [rel({'name': 'binutils-source'})],
                    ]
                }
        self.assertPkgDictEqual(rel2, pkg2.relations)
        f.close()

    def test_restrictions_parse(self):
        """ test parsing of restriction formulas """
        r = "foo <cross>"
        # relation 0, alternative 0, restrictions set 0, condition 0
        term = deb822.PkgRelation.parse_relations(r)[0][0]['restrictions'][0][0]
        self.assertEqual(term.enabled, True)
        self.assertEqual(term[0], True)
        self.assertEqual(term.profile, 'cross')
        self.assertEqual(term[1], 'cross')

        r = "foo <!stage1> <!stage2 !cross>"
        # relation 0, alternative 0, restrictions set 1, condition 0
        term = deb822.PkgRelation.parse_relations(r)[0][0]['restrictions'][1][0]
        self.assertEqual(term.enabled, False)
        self.assertEqual(term[0], False)
        self.assertEqual(term.profile, 'stage2')
        self.assertEqual(term[1], 'stage2')

        # relation 0, alternative 0, restrictions set 1, condition 1
        term = deb822.PkgRelation.parse_relations(r)[0][0]['restrictions'][1][1]
        self.assertEqual(term.enabled, False)
        self.assertEqual(term[0], False)
        self.assertEqual(term.profile, 'cross')
        self.assertEqual(term[1], 'cross')

    def test_multiarch_parse(self):
        """ test parsing of architecture qualifiers from multiarch

        Also ensure that the archqual part makes a round-trip, see
        https://bugs.debian.org/868249
        """
        r = "foo:native"
        # relation 0, alternative 0, arch qualifier
        rel = deb822.PkgRelation.parse_relations(r)
        term = rel[0][0]['archqual']
        self.assertEqual(term, "native")
        self.assertEqual(deb822.PkgRelation.str(rel), r)


class TestVersionAccessor(unittest.TestCase):

    def test_get_version(self):
        # should not be available in most basic Deb822
        p = deb822.Deb822(UNPARSED_PACKAGE.splitlines())
        with self.assertRaises(AttributeError):
            p.get_version()

        # should be available in Packages
        p = deb822.Packages(UNPARSED_PACKAGE.splitlines())
        v = p.get_version()
        self.assertEqual(str(v), '1.5.12-1')
        self.assertTrue(isinstance(v, Version))

    def test_set_version(self):
        # should not be available in most basic Deb822
        p = deb822.Deb822(UNPARSED_PACKAGE.splitlines())
        with self.assertRaises(AttributeError):
            p.set_version()

        # should be available in Packages
        p = deb822.Packages(UNPARSED_PACKAGE.splitlines())
        newver = '9.8.7-1'
        v = Version(newver)
        p.set_version(v)
        self.assertEqual(p['Version'], newver)
        self.assertTrue(isinstance(p['Version'], six.string_types))


@unittest.skipUnless(os.path.exists('/usr/bin/gpgv'), "gpgv not installed")
class TestGpgInfo(unittest.TestCase):

    def setUp(self):
        self.data = SIGNED_CHECKSUM_CHANGES_FILE % CHECKSUM_CHANGES_FILE
        self.data = self.data.encode()
        self.valid = {
            'GOODSIG':
                ['D14219877A786561', 'John Wright <john.wright@hp.com>'],
            'VALIDSIG':
                ['8FEFE900783CF175827C2F65D14219877A786561', '2008-05-01',
                 '1209623566', '0', '3', '0', '17', '2', '01',
                 '8FEFE900783CF175827C2F65D14219877A786561'],
            'SIG_ID':
                ['j3UjSpdky92fcQISbm8W5PlwC/g', '2008-05-01', '1209623566'],
        }

    def _validate_gpg_info(self, gpg_info):
        # The second part of the GOODSIG field could change if the primary
        # uid changes, so avoid checking that.  Also, the first part of the
        # SIG_ID field has undergone at least one algorithm changein gpg,
        # so don't bother testing that either.
        self.assertEqual(set(gpg_info.keys()), set(self.valid.keys()))
        self.assertEqual(gpg_info['GOODSIG'][0], self.valid['GOODSIG'][0])
        self.assertEqual(gpg_info['VALIDSIG'], self.valid['VALIDSIG'])
        self.assertEqual(gpg_info['SIG_ID'][1:], self.valid['SIG_ID'][1:])

    def test_from_sequence_string(self):
        gpg_info = deb822.GpgInfo.from_sequence(self.data, keyrings=[KEYRING])
        self._validate_gpg_info(gpg_info)

    def test_from_sequence_newline_terminated(self):
        sequence = BytesIO(self.data)
        gpg_info = deb822.GpgInfo.from_sequence(sequence, keyrings=[KEYRING])
        self._validate_gpg_info(gpg_info)

    def test_from_sequence_no_newlines(self):
        sequence = self.data.splitlines()
        gpg_info = deb822.GpgInfo.from_sequence(sequence, keyrings=[KEYRING])
        self._validate_gpg_info(gpg_info)

    def test_from_file(self):
        fd, filename = tempfile.mkstemp()
        fp = os.fdopen(fd, 'wb')
        fp.write(self.data)
        fp.close()

        try:
            gpg_info = deb822.GpgInfo.from_file(filename, keyrings=[KEYRING])
        finally:
            os.remove(filename)

        self._validate_gpg_info(gpg_info)


def _no_space(s):
    """Returns s.  Raises ValueError if s contains any whitespace."""
    if re.search(r'\s', s):
        raise ValueError('whitespace not allowed')
    return s


class RestrictedWrapperTest(unittest.TestCase):
    class Wrapper(deb822.RestrictedWrapper):
        restricted_field = deb822.RestrictedField('Restricted-Field')  # type: ignore
        required_field = deb822.RestrictedField('Required-Field', allow_none=False)   # type: ignore
        space_separated = deb822.RestrictedField(    # type: ignore
                'Space-Separated',
                from_str=lambda s: tuple((s or '').split()),
                to_str=lambda seq: ' '.join(_no_space(s) for s in seq) or None)

    def test_unrestricted_get_and_set(self):
        data = deb822.Deb822()
        data['Foo'] = 'bar'

        wrapper = self.Wrapper(data)
        self.assertEqual('bar', wrapper['Foo'])
        wrapper['foo'] = 'baz'
        self.assertEqual('baz', wrapper['Foo'])
        self.assertEqual('baz', wrapper['foo'])

        multiline = 'First line\n Another line'
        wrapper['X-Foo-Bar'] = multiline
        self.assertEqual(multiline, wrapper['X-Foo-Bar'])
        self.assertEqual(multiline, wrapper['x-foo-bar'])

        expected_data = deb822.Deb822()
        expected_data['Foo'] = 'baz'
        expected_data['X-Foo-Bar'] = multiline
        self.assertEqual(expected_data.keys(), data.keys())
        self.assertEqual(expected_data, data)

    def test_trivially_restricted_get_and_set(self):
        data = deb822.Deb822()
        data['Required-Field'] = 'some value'

        wrapper = self.Wrapper(data)
        self.assertEqual('some value', wrapper.required_field)
        self.assertEqual('some value', wrapper['Required-Field'])
        self.assertEqual('some value', wrapper['required-field'])
        self.assertIsNone(wrapper.restricted_field)

        with self.assertRaises(deb822.RestrictedFieldError):
            wrapper['Required-Field'] = 'foo'
        with self.assertRaises(deb822.RestrictedFieldError):
            wrapper['required-field'] = 'foo'
        with self.assertRaises(deb822.RestrictedFieldError):
            wrapper['Restricted-Field'] = 'foo'
        with self.assertRaises(deb822.RestrictedFieldError):
            wrapper['Restricted-field'] = 'foo'

        with self.assertRaises(deb822.RestrictedFieldError):
            del wrapper['Required-Field']
        with self.assertRaises(deb822.RestrictedFieldError):
            del wrapper['required-field']
        with self.assertRaises(deb822.RestrictedFieldError):
            del wrapper['Restricted-Field']
        with self.assertRaises(deb822.RestrictedFieldError):
            del wrapper['restricted-field']

        with self.assertRaises(TypeError):
            wrapper.required_field = None

        wrapper.restricted_field = 'special value'
        self.assertEqual('special value', data['Restricted-Field'])
        wrapper.restricted_field = None
        self.assertFalse('Restricted-Field' in data)
        self.assertIsNone(wrapper.restricted_field)

        wrapper.required_field = 'another value'
        self.assertEqual('another value', data['Required-Field'])

    def test_set_already_none_to_none(self):
        data = deb822.Deb822()
        wrapper = self.Wrapper(data)
        wrapper.restricted_field = 'Foo'
        wrapper.restricted_field = None
        self.assertFalse('restricted-field' in data)
        wrapper.restricted_field = None
        self.assertFalse('restricted-field' in data)

    def test_processed_get_and_set(self):
        data = deb822.Deb822()
        data['Space-Separated'] = 'foo bar baz'

        wrapper = self.Wrapper(data)
        self.assertEqual(('foo', 'bar', 'baz'), wrapper.space_separated)
        wrapper.space_separated = ['bar', 'baz', 'quux']
        self.assertEqual('bar baz quux', data['space-separated'])
        self.assertEqual('bar baz quux', wrapper['space-separated'])
        self.assertEqual(('bar', 'baz', 'quux'), wrapper.space_separated)

        with self.assertRaises(ValueError) as cm:
            wrapper.space_separated = ('foo', 'bar baz')
        self.assertEqual(('whitespace not allowed',), cm.exception.args)

        wrapper.space_separated = None
        self.assertEqual((), wrapper.space_separated)
        self.assertFalse('space-separated' in data)
        self.assertFalse('Space-Separated' in data)

        wrapper.space_separated = ()
        self.assertEqual((), wrapper.space_separated)
        self.assertFalse('space-separated' in data)
        self.assertFalse('Space-Separated' in data)

    def test_dump(self):
        data = deb822.Deb822()
        data['Foo'] = 'bar'
        data['Baz'] = 'baz'
        data['Space-Separated'] = 'baz quux'
        data['Required-Field'] = 'required value'
        data['Restricted-Field'] = 'restricted value'

        wrapper = self.Wrapper(data)
        self.assertEqual(data.dump(), wrapper.dump())

        wrapper.restricted_field = 'another value'
        wrapper.space_separated = ('bar', 'baz', 'quux')
        self.assertEqual(data.dump(), wrapper.dump())


if __name__ == '__main__':
    unittest.main()

%global debug_package %{nil}

Name: python-debian
Epoch: 100
Version: 0.1.43
Release: 1%{?dist}
BuildArch: noarch
Summary: Python 3 modules to work with Debian-related data formats
License: GPL-3.0-or-later
URL: https://salsa.debian.org/python-debian-team/python-debian/-/tags
Source0: %{name}_%{version}.orig.tar.gz
BuildRequires: fdupes
BuildRequires: python-rpm-macros
BuildRequires: python3-apt >= 1.1
BuildRequires: python3-chardet
BuildRequires: python3-devel
BuildRequires: python3-setuptools

%description
Click is a Python package for creating command line interfaces in a
composable way with as little code as necessary. It's the "Command Line
Interface Creation Kit". It is configurable, and comes with defaults out
of the box.

%prep
%autosetup -T -c -n %{name}_%{version}-%{release}
tar -zx -f %{S:0} --strip-components=1 -C .

%build
%py3_build

%install
%py3_install
find %{buildroot}%{python3_sitelib} -type f -name '*.pyc' -exec rm -rf {} \;
fdupes -qnrps %{buildroot}%{python3_sitelib}

%check

%if 0%{?suse_version} > 1500
%package -n python%{python3_version_nodots}-debian
Summary: Python 3 modules to work with Debian-related data formats
Requires: python3
Requires: python3-chardet
Provides: python3-debian = %{epoch}:%{version}-%{release}
Provides: python3dist(debian) = %{epoch}:%{version}-%{release}
Provides: python%{python3_version}-debian = %{epoch}:%{version}-%{release}
Provides: python%{python3_version}dist(debian) = %{epoch}:%{version}-%{release}
Provides: python%{python3_version_nodots}-debian = %{epoch}:%{version}-%{release}
Provides: python%{python3_version_nodots}dist(debian) = %{epoch}:%{version}-%{release}

%description -n python%{python3_version_nodots}-debian
This package provides Python 3 modules that abstract many formats of
Debian related files. Currently handled are:
  - Debtags information (debian.debtags module)
  - debian/changelog (debian.changelog module)
  - Packages files, pdiffs (debian.debian\_support module)
  - Control files of single or multiple RFC822-style paragraphs, e.g.
    debian/control, .changes, .dsc, Packages, Sources, Release, etc.
    (debian.deb822 module)
  - Raw .deb and .ar files, with (read-only) access to contained files
    and meta-information

%files -n python%{python3_version_nodots}-debian
%doc README.rst
%{python3_sitelib}/*
%endif

%if 0%{?sle_version} > 150000
%package -n python3-debian
Summary: Python 3 modules to work with Debian-related data formats
Requires: python3
Requires: python3-chardet
Provides: python3-debian = %{epoch}:%{version}-%{release}
Provides: python3dist(debian) = %{epoch}:%{version}-%{release}
Provides: python%{python3_version}-debian = %{epoch}:%{version}-%{release}
Provides: python%{python3_version}dist(debian) = %{epoch}:%{version}-%{release}
Provides: python%{python3_version_nodots}-debian = %{epoch}:%{version}-%{release}
Provides: python%{python3_version_nodots}dist(debian) = %{epoch}:%{version}-%{release}

%description -n python3-debian
This package provides Python 3 modules that abstract many formats of
Debian related files. Currently handled are:
  - Debtags information (debian.debtags module)
  - debian/changelog (debian.changelog module)
  - Packages files, pdiffs (debian.debian\_support module)
  - Control files of single or multiple RFC822-style paragraphs, e.g.
    debian/control, .changes, .dsc, Packages, Sources, Release, etc.
    (debian.deb822 module)
  - Raw .deb and .ar files, with (read-only) access to contained files
    and meta-information

%files -n python3-debian
%doc README.rst
%{python3_sitelib}/*
%endif

%if !(0%{?suse_version} > 1500) && !(0%{?sle_version} > 150000)
%package -n python3-debian
Summary: Python 3 modules to work with Debian-related data formats
Requires: python3
Requires: python3-chardet
Provides: python3-debian = %{epoch}:%{version}-%{release}
Provides: python3dist(debian) = %{epoch}:%{version}-%{release}
Provides: python%{python3_version}-debian = %{epoch}:%{version}-%{release}
Provides: python%{python3_version}dist(debian) = %{epoch}:%{version}-%{release}
Provides: python%{python3_version_nodots}-debian = %{epoch}:%{version}-%{release}
Provides: python%{python3_version_nodots}dist(debian) = %{epoch}:%{version}-%{release}

%description -n python3-debian
This package provides Python 3 modules that abstract many formats of
Debian related files. Currently handled are:
  - Debtags information (debian.debtags module)
  - debian/changelog (debian.changelog module)
  - Packages files, pdiffs (debian.debian\_support module)
  - Control files of single or multiple RFC822-style paragraphs, e.g.
    debian/control, .changes, .dsc, Packages, Sources, Release, etc.
    (debian.deb822 module)
  - Raw .deb and .ar files, with (read-only) access to contained files
    and meta-information
%files -n python3-debian
%doc README.rst
%{python3_sitelib}/*
%endif

%changelog

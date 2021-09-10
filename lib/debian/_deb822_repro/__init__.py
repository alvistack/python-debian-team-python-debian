# The "from X import Y as Y" looks weird but we are stuck in a fight
# between mypy and pylint in the CI.
#
#    mypy --strict insists on either of following for re-exporting
#       1) Do a "from debian._deb822_repro.X import *"
#       2) Do a "from .X import Y"
#       3) Do a "from debian._deb822_repro.X import Y as Z"
#
#    pylint on the CI fails on relative imports (it assumes "lib" is a
#    part of the python package name in relative imports).  This rules
#    out 2) from the mypy list.  The use of 1) would cause overlapping
#    imports (and also it felt prudent to import only what was exported).
#
# This left 3) as the only option for now, which pylint then complains
# about (not unreasonably in general).  Unfortunately, we can disable
# that warning in this work around.  But once 2) becomes an option
# without pylint tripping over itself on the CI, then it considerably
# better than this approach.
#

# pylint: disable=useless-import-alias
from debian._deb822_repro.parsing import (
    parse_deb822_file as parse_deb822_file,
    LIST_SPACE_SEPARATED_INTERPRETATION as LIST_SPACE_SEPARATED_INTERPRETATION,
    LIST_COMMA_SEPARATED_INTERPRETATION as LIST_COMMA_SEPARATED_INTERPRETATION,
    Interpretation as Interpretation,
    # Primarily for documentation purposes / help()
    Deb822FileElement as Deb822FileElement,
    Deb822ParagraphElement as Deb822ParagraphElement,
)
from debian._deb822_repro.types import (
    AmbiguousDeb822FieldKeyError as AmbiguousDeb822FieldKeyError
)

__all__ = [
    'parse_deb822_file',
    'AmbiguousDeb822FieldKeyError',
    'LIST_SPACE_SEPARATED_INTERPRETATION',
    'LIST_COMMA_SEPARATED_INTERPRETATION',
    'Interpretation',
    'Deb822FileElement',
    'Deb822ParagraphElement',
]

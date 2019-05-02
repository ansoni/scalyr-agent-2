# Copyright 2014 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ------------------------------------------------------------------------
#
#
# author: Steven Czerwinski <czerwin@scalyr.com>

__author__ = 'czerwin@scalyr.com'

import sys
import unittest


PYTHON_26_OR_OLDER = sys.version_info[:2] < (2, 7)


def _noop_skip(reason):
    def decorator(test_func_or_obj):
        if not isinstance(test_func_or_obj, type):
            def skip_wrapper(*args, **kwargs):
                print('Skipping test %s. Reason: "%s"' % (test_func_or_obj.__name__, reason))
            return skip_wrapper
        else:
            test_func_or_obj.__unittest_skip__ = True
            test_func_or_obj.__unittest_skip_why__ = reason
            return test_func_or_obj
    return decorator


def _id(obj):
    return obj


def _noop_skip_if(condition, reason):
    if condition:
        return _noop_skip(reason)
    return _id


def _noop_skip_unless(condition, reason):
    if not condition:
        return _noop_skip(reason)
    return _id


skip = _noop_skip
if hasattr(unittest, 'skip'):
    skip = unittest.skip


skipUnless = _noop_skip_unless
if hasattr(unittest, 'skipUnless'):
    skipUnless = unittest.skipUnless


skipIf = _noop_skip_if
if hasattr(unittest, 'skipIf'):
    skipIf = unittest.skipIf


if sys.version_info[:2] < (2, 7):
    class ScalyrTestCase(unittest.TestCase):
        """The base class for Scalyr tests.

        This is used mainly to hide differences between the test fixtures available in the various Python
        versions
        """
        def assertIs(self, obj1, obj2, msg=None):
            """Just like self.assertTrue(a is b), but with a nicer default message."""
            if obj1 is not obj2:
                if msg is None:
                    msg = '%s is not %s' % (obj1, obj2)
                self.fail(msg)

        def assertIsNone(self, obj, msg=None):
            """Same as self.assertTrue(obj is None), with a nicer default message."""
            if msg is not None:
                self.assertTrue(obj is None, msg)
            else:
                self.assertTrue(obj is None, '%s is not None' % (str(obj)))

        def assertIsNotNone(self, obj, msg=None):
            """Included for symmetry with assertIsNone."""
            if msg is not None:
                self.assertTrue(obj is not None, msg)
            else:
                self.assertTrue(obj is not None, '%s is None' % (str(obj)))

        def assertGreater(self, a, b, msg=None):
            """Included for symmetry with assertIsNone."""
            if msg is not None:
                self.assertTrue(a > b, msg)
            else:
                self.assertTrue(a > b, '%s is greater than %s' % (str(a), str(b)))
else:
    class ScalyrTestCase(unittest.TestCase):
        """The base class for Scalyr tests.

        This is used mainly to hide differences between the test fixtures available in the various Python
        versions
        """
        def assertIs(self, obj1, obj2, msg=None):
            unittest.TestCase.assertIs(self, obj1, obj2, msg=msg)

        def assertIsNone(self, obj, msg=None):
            unittest.TestCase.assertIsNone(self, obj, msg=msg)

        def assertIsNotNone(self, obj, msg=None):
            unittest.TestCase.assertIsNotNone(self, obj, msg=msg)

        def assertGreater(self, a, b, msg=None):
            unittest.TestCase.assertGreater(self, a, b, msg=msg)

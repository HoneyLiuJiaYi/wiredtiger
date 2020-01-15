#!/usr/bin/env python
#
# Public Domain 2014-2019 MongoDB, Inc.
# Public Domain 2008-2014 WiredTiger, Inc.
#
# This is free and unencumbered software released into the public domain.
#
# Anyone is free to copy, modify, publish, use, compile, sell, or
# distribute this software, either in source code form or as a compiled
# binary, for any purpose, commercial or non-commercial, and by any
# means.
#
# In jurisdictions that recognize copyright laws, the author or authors
# of this software dedicate any and all copyright interest in the
# software to the public domain. We make this dedication for the benefit
# of the public at large and to the detriment of our heirs and
# successors. We intend this dedication to be an overt act of
# relinquishment in perpetuity of all present and future rights to this
# software under copyright law.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR
# OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
# ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.

import unittest, wiredtiger, wttest
from wiredtiger import stat
from wtscenario import make_scenarios

def timestamp_str(t):
    return '%x' % t

# test_las08.py
# Verify that we write the newest committed version to data store and the
# second newest committed version to history store.
class test_las08(wttest.WiredTigerTestCase):
    # Force a small cache.
    conn_config = 'cache_size=50MB,statistics=(fast)'
    session_config = 'isolation=snapshot'
    uri = "table:test_las09"
    key_format_values = [
        ('column', dict(key_format='r')),
        ('integer', dict(key_format='i')),
        ('string', dict(key_format='S')),
    ]
    scenarios = make_scenarios(key_format_values)

    def create_key(self, i):
        if self.key_format == 'S':
            return str(i)
        return i

    def check_ckpt_las(self, expected_data_value, expected_las_value, expected_las_start_ts, expected_las_stop_ts):
        session = self.conn.open_session(self.session_config)
        session.checkpoint()
        # Check the data file value
        cursor = session.open_cursor(self.uri, None, 'checkpoint=WiredTigerCheckpoint')
        for _, value in cursor:
            self.assertEqual(value, expected_data_value)
        cursor.close()
        # Check the lookaside file value
        cursor = session.open_cursor("file:WiredTigerLAS.wt", None, 'checkpoint=WiredTigerCheckpoint')
        for _, _, las_start_ts, _, las_stop_ts, _, _, _, type, value in cursor:
            # No WT_UPDATE_TOMBSTONE in lookaside
            self.assertNotEqual(type, 5)
            # No WT_UPDATE_BIRTHMARK in lookaside
            self.assertNotEqual(type, 1)
            # WT_UPDATE_STANDARD
            if (type == 4):
                self.assertEqual(value.decode(), expected_las_value + '\x00')
                self.assertEqual(las_start_ts, expected_las_start_ts)
                self.assertEqual(las_stop_ts, expected_las_stop_ts)
        cursor.close()
        session.close()

    def test_uncommitted_updates_not_written_to_lookaside(self):
        # Create a small table.
        create_params = 'key_format={},value_format=S'.format(self.key_format)
        self.session.create(self.uri, create_params)

        value1 = 'a' * 500
        value2 = 'b' * 500
        value3 = 'c' * 500

        # Load 5Mb of data.
        self.conn.set_timestamp('oldest_timestamp=' + timestamp_str(1))
        cursor = self.session.open_cursor(self.uri)
        self.session.begin_transaction()
        for i in range(1, 10000):
            cursor[self.create_key(i)] = value1
        self.session.commit_transaction('commit_timestamp=' + timestamp_str(2))

        # Load another 5Mb of data with a later timestamp.
        self.session.begin_transaction()
        for i in range(1, 10000):
            cursor[self.create_key(i)] = value2
        self.session.commit_transaction('commit_timestamp=' + timestamp_str(3))

        # Uncommitted changes
        self.session.begin_transaction()
        for i in range(1, 11):
            cursor[self.create_key(i)] = value3

        self.check_ckpt_las(value2, value1, 2, 3)

    def test_prepared_updates_not_written_to_lookaside(self):
        # Create a small table.
        create_params = 'key_format={},value_format=S'.format(self.key_format)
        self.session.create(self.uri, create_params)

        value1 = 'a' * 500
        value2 = 'b' * 500
        value3 = 'c' * 500

        # Load 5Mb of data.
        self.conn.set_timestamp('oldest_timestamp=' + timestamp_str(1))
        cursor = self.session.open_cursor(self.uri)
        self.session.begin_transaction()
        for i in range(1, 10000):
            cursor[self.create_key(i)] = value1
        self.session.commit_transaction('commit_timestamp=' + timestamp_str(2))

        # Load another 5Mb of data with a later timestamp.
        self.session.begin_transaction()
        for i in range(1, 10000):
            cursor[self.create_key(i)] = value2
        self.session.commit_transaction('commit_timestamp=' + timestamp_str(3))

        # Prepare some updates
        self.session.begin_transaction()
        for i in range(1, 11):
            cursor[self.create_key(i)] = value3
        self.session.prepare_transaction('prepare_timestamp=' + timestamp_str(4))

        self.check_ckpt_las(value2, value1, 2, 3)

    def test_write_newest_version_to_data_store(self):
        # Create a small table.
        create_params = 'key_format={},value_format=S'.format(self.key_format)
        self.session.create(self.uri, create_params)

        value1 = 'a' * 500
        value2 = 'b' * 500

        # Load 5Mb of data.
        self.conn.set_timestamp('oldest_timestamp=' + timestamp_str(1))
        cursor = self.session.open_cursor(self.uri)
        self.session.begin_transaction()
        for i in range(1, 10000):
            cursor[self.create_key(i)] = value1
        self.session.commit_transaction('commit_timestamp=' + timestamp_str(2))

        # Load another 5Mb of data with a later timestamp.
        self.session.begin_transaction()
        for i in range(1, 10000):
            cursor[self.create_key(i)] = value2
        self.session.commit_transaction('commit_timestamp=' + timestamp_str(3))

        self.check_ckpt_las(value2, value1, 2, 3)

    def test_write_deleted_version_to_data_store(self):
        # Create a small table.
        create_params = 'key_format={},value_format=S'.format(self.key_format)
        self.session.create(self.uri, create_params)

        value1 = 'a' * 500
        value2 = 'b' * 500

        # Load 5Mb of data.
        self.conn.set_timestamp('oldest_timestamp=' + timestamp_str(1))
        cursor = self.session.open_cursor(self.uri)
        self.session.begin_transaction()
        for i in range(1, 10000):
            cursor[self.create_key(i)] = value1
        self.session.commit_transaction('commit_timestamp=' + timestamp_str(2))

        # Load another 5Mb of data with a later timestamp.
        self.session.begin_transaction()
        for i in range(1, 10000):
            cursor[self.create_key(i)] = value2
        self.session.commit_transaction('commit_timestamp=' + timestamp_str(3))

        # Delete records.
        self.session.begin_transaction()
        for i in range(1, 10000):
            cursor = self.session.open_cursor(self.uri)
            cursor.set_key(self.create_key(i))
            self.assertEqual(cursor.remove(), 0)
        self.session.commit_transaction('commit_timestamp=' + timestamp_str(4))

        self.check_ckpt_las(value2, value1, 2, 3)

if __name__ == '__main__':
    wttest.run()
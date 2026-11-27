"""Unit tests for PostgreSQL pool selection and lifecycle."""
import unittest
from unittest.mock import MagicMock, patch

from watchlistguard import db


class PostgresPoolTests(unittest.TestCase):
    def setUp(self):
        db.close_pools()

    def tearDown(self):
        db.close_pools()

    @patch("psycopg_pool.ConnectionPool")
    def test_pools_are_reused_per_url_and_isolated_between_urls(self, pool_factory):
        pool_a = MagicMock(closed=False)
        pool_b = MagicMock(closed=False)
        raw_a, raw_b = MagicMock(), MagicMock()
        pool_a.getconn.return_value = raw_a
        pool_b.getconn.return_value = raw_b
        pool_factory.side_effect = [pool_a, pool_b]

        a1 = db.connect("postgresql://user:secret@host/db-a")
        a2 = db.connect("postgresql://user:secret@host/db-a")
        b1 = db.connect("postgresql://user:secret@host/db-b")
        try:
            self.assertIs(a1.pool, pool_a)
            self.assertIs(a2.pool, pool_a)
            self.assertIs(b1.pool, pool_b)
            self.assertEqual(pool_factory.call_count, 2)
            self.assertEqual(pool_factory.call_args_list[0].args[0], "postgresql://user:secret@host/db-a")
            self.assertEqual(pool_factory.call_args_list[1].args[0], "postgresql://user:secret@host/db-b")
        finally:
            db.close(a1)
            db.close(a2)
            db.close(b1)
        pool_a.putconn.assert_has_calls([unittest.mock.call(raw_a), unittest.mock.call(raw_a)])
        pool_b.putconn.assert_called_once_with(raw_b)

    @patch("psycopg_pool.ConnectionPool")
    def test_close_pools_closes_and_forgets_each_pool(self, pool_factory):
        first, second = MagicMock(closed=False), MagicMock(closed=False)
        pool_factory.side_effect = [first, second]
        one = db.connect("postgresql://user:secret@host/one")
        two = db.connect("postgresql://user:secret@host/two")
        db.close(one)
        db.close(two)

        db.close_pools()

        first.close.assert_called_once()
        second.close.assert_called_once()
        self.assertEqual(db._pools, {})


if __name__ == "__main__":
    unittest.main()

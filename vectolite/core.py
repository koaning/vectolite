"""This is a single notebook that contains all the source code, yay!"""

# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/00_core.ipynb.

# %% auto 0
__all__ = ['serialize_f32', 'VectoLite']

# %% ../nbs/00_core.ipynb 2
from nbdev.showdoc import *
import json
from diskcache import Cache
import hashlib
import orjson
import sqlite_vec
import pysqlite3
from typing import Dict

from typing import List
import struct


def serialize_f32(vector: List[float]) -> bytes:
    """Serializes a list of floats into a compact "raw bytes" format."""
    return struct.pack("%sf" % len(vector), *vector)



# %% ../nbs/00_core.ipynb 3
class VectoLite:
    def __init__(self, path: str):
        """
        Initializes the VectoLite instance with a connection to the SQLite database.

        Parameters
        ----------
            path 
                The path to the SQLite database file.
        """
        self.path = path
        self.db = pysqlite3.connect(f'{path}.sqlite')
        self.db.enable_load_extension(True)
        sqlite_vec.load(self.db)
        self.db.enable_load_extension(False)
        self.cache = Cache(path)
        self.rownums = None
        self.table_name = 'myvecs'

    def print_version(self):
        """
        Prints the SQLite and SQLite-vec versions.
        """
        sqlite_version, vec_version = self.db.execute(
            "select sqlite_version(), vec_version()"
        ).fetchone()
        print(f"sqlite_version={sqlite_version}, vec_version={vec_version}")
    
    @property
    def table_exists(self):
        """
        Checks if a table exists in the SQLite database.

        Returns:
            bool: True if the table exists, False otherwise.
        """
        return self.db.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{self.table_name}'").fetchone() is not None

    @property
    def table_len(self):
        """
        Returns the number of rows in the specified table. Will also cache the number of rows internally when called.

        Returns:
            int: The number of rows in the table.
        """
        if not self.rownums:
            self.rownums = self.db.execute(f"SELECT COUNT(*) FROM {self.table_name}").fetchone()[0]
        return self.rownums
    
    def parse_item(self, item: Dict):
        """
        Parses an item and returns its MD5 hash, serialized contents, and serialized vector.

        Args:
            item (dict): The item to parse.

        Returns:
            tuple: A tuple containing the MD5 hash (str), serialized contents (str), and serialized vector (bytes).
        """
        contents = orjson.dumps({k: v for k, v in item.items() if k != 'vector'})
        md5_hash = hashlib.md5(contents).hexdigest()
        return md5_hash, contents, item['vector']

    def insert(self, stream):
        """
        Inserts a stream of items into the specified table.

        Args:
            stream (iterable): An iterable stream of items to insert.
        """
        with self.db:
            for item in stream:
                md5_hash, contents, vector = self.parse_item(item)
        
                # Edge case: if the table does not exist, create it
                if not self.table_exists:
                    self.db.execute(f"CREATE VIRTUAL TABLE {self.table_name} USING vec0(embedding float[{len(vector)}])")
                    self.rownums = 0

                # If we have already inserted this item, no need to add again
                if md5_hash in self.cache:
                    return

                # Insert the item into the table
                i = self.table_len + 1
                self.db.execute(
                    f"INSERT INTO {self.table_name}(rowid, embedding) VALUES (?, ?)",
                    [i, serialize_f32(vector)],
                )
                self.cache[i] = contents
                self.cache[md5_hash] = i
                self.rownums += 1
    
    def query_idx(self, query, k=5):
        """
        Queries the specified table for the nearest neighbors to the given query vector.

        Args:
            query (list): The query vector.

        Returns:
            tuple: A tuple containing the rowids and distances of the nearest neighbors.
        """
        results = self.db.execute(
            f"""
              SELECT
                rowid,
                distance
              FROM {self.table_name}
              WHERE embedding MATCH ?
              ORDER BY distance
              LIMIT {k}
            """,
            [serialize_f32(query)],
        ).fetchall()
        return list(zip(*results))

    def query(self, query, k=5):
        """
        Queries the specified table for the nearest neighbors to the given query vector.

        Args:
            query (list): The query vector.

        Returns:
            list: A list of the nearest neighbors.
        """
        idxs, dists = self.query_idx(query, k)
        return [json.loads(self.cache[i].decode()) for i in idxs], dists

"""Validate bounds/checksums and the real old/new partition migration constraints."""
import struct
import unittest

from migration import NEW, ROOT, bundle, table_entries

def sample_bundle(entries):
    table, content = bytearray(), bytearray()
    for name, data in entries:
        table.extend(struct.pack('<32sIIHH', name.encode(), len(data), len(content), 0, 0))
        content.extend(b'ZZ' + data)
    data = table + content
    return struct.pack('<III', len(entries), sum(data) & 0xffff, len(data)) + data

class MigrationTests(unittest.TestCase):
    def test_real_layout_reallocates_exactly_two_mib(self):
        current = table_entries((ROOT / 'build/partition_table/partition-table.bin').read_bytes())
        for name, expected in NEW.items():
            self.assertEqual(current[name], expected)
        self.assertEqual(current['assets'][1] - 0x4d0000, 2 * 1024 * 1024)
        self.assertEqual(current['spine'][0] + current['spine'][1], current['wallpaper'][0])
        self.assertEqual(current['wallpaper'][0] + current['wallpaper'][1], 16 * 1024 * 1024)
        self.assertEqual(current['nvs'], (0x9000, 0x10000))
        self.assertEqual(current['userdata'], (0x510000, 0x20000))

    def test_payload_preserved_without_flash_padding(self):
        raw = sample_bundle([('role.json', b'{"role_id":"existing"}'), ('texture.png', b'\x00\x80\xff')])
        payload, files = bundle(raw + b'\xff' * 8192)
        self.assertEqual(payload, raw)
        self.assertEqual(files['texture.png'], b'\x00\x80\xff')
        migrated = payload + b'\xff' * (NEW['spine'][1] - len(payload))
        self.assertEqual(bundle(migrated), (payload, files))

    def test_corrupted_or_truncated_package_rejected(self):
        raw = bytearray(sample_bundle([('role.json', b'{}')]))
        with self.assertRaises(ValueError):
            bundle(raw[:-1])
        raw[-1] ^= 1
        with self.assertRaises(ValueError):
            bundle(raw)

    def test_duplicate_name_rejected(self):
        with self.assertRaises(ValueError):
            bundle(sample_bundle([('role.json', b'{}'), ('role.json', b'{}')]))

    def test_blank_slot_is_distinguished_from_broken_slot(self):
        self.assertEqual(bundle(b'\xff' * 4096), (None, {}))
        with self.assertRaises(ValueError):
            bundle(b'\0' * 4096)

    def test_overlapping_or_out_of_flash_layout_rejected(self):
        def entry(name, start, size):
            return struct.pack('<HBBII16sI', 0x50aa, 1, 0x40, start, size, name.encode(), 0)
        with self.assertRaises(ValueError):
            table_entries(entry('a', 0x10000, 0x20000) + entry('b', 0x20000, 0x10000))
        with self.assertRaises(ValueError):
            table_entries(entry('a', 0xf00000, 0x200000))

if __name__ == '__main__':
    unittest.main(verbosity=2)

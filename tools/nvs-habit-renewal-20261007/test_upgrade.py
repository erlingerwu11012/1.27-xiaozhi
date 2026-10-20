import hashlib,struct,unittest
from upgrade_preserve import FLASH_SIZE,PROTECTED,partitions,migrated_nvs,verify_preserved
def table(new=False):
    entries=[('nvs',0x9000,0x10000 if new else 0x4000),('phy_init',0x19000 if new else 0xd000,0x1000),('factory',0x20000 if new else 0x10000,0x4f0000 if new else 0x500000),('userdata',0x510000,0x20000),('assets',0x530000,0x4d0000),('spine',0xa00000,0x400000),('wallpaper',0xe00000,0x200000)]
    raw=b''.join(struct.pack('<HBBII16sI',0x50aa,0,0,start,size,name.encode(),0) for name,start,size in entries)
    return (raw+b'\xeb\xeb'+b'\xff'*14+hashlib.md5(raw).digest()).ljust(0x1000,b'\xff')
def backup(new=False):
    data=bytearray(b'\xa5'*FLASH_SIZE);data[0x8000:0x9000]=table(new);return data
class UpgradeTests(unittest.TestCase):
    def test_old_nvs_preserved_and_extension_blank(self):
        old=backup();nvs,phy,expanded=migrated_nvs(old);self.assertTrue(expanded);self.assertEqual(nvs[:0x4000],old[0x9000:0xd000]);self.assertEqual(nvs[0x4000:],b'\xff'*0xc000);self.assertEqual(phy,old[0xd000:0xe000])
    def test_existing_64k_preserved(self):
        old=backup(True);nvs,phy,expanded=migrated_nvs(old);self.assertFalse(expanded);self.assertEqual(nvs,old[0x9000:0x19000])
    def test_short_backup_rejected(self):
        with self.assertRaises(ValueError):migrated_nvs(b'\xff'*0x1000)
    def test_corrupt_partition_rejected(self):
        old=backup();old[0x8020]^=1
        with self.assertRaises(ValueError):migrated_nvs(old)
    def test_unknown_layout_rejected(self):
        old=backup();t=bytearray(table());t[4:8]=struct.pack('<I',0xa000);prefix=bytes(t[:224]);t[240:256]=hashlib.md5(prefix).digest();old[0x8000:0x9000]=t
        with self.assertRaises(ValueError):migrated_nvs(old)
    def test_protected_partitions_verified(self):
        old=backup();nvs,phy,_=migrated_nvs(old);after=bytearray(old);after[0x9000:0x19000]=nvs;after[0x19000:0x1a000]=phy;verify_preserved(old,after,nvs,phy)
        for name,(start,size) in PROTECTED.items():
            bad=bytearray(after);bad[start]^=1
            with self.assertRaises(ValueError):verify_preserved(old,bad,nvs,phy)
    def test_nvs_corruption_detected(self):
        old=backup();nvs,phy,_=migrated_nvs(old);after=bytearray(old);after[0x9000:0x19000]=nvs;after[0x19000:0x1a000]=phy;after[0x9000]^=1
        with self.assertRaises(ValueError):verify_preserved(old,after,nvs,phy)
    def test_final_partition_boundaries(self):
        p=partitions(table(True));self.assertEqual(p['nvs'],(0x9000,0x10000));self.assertEqual(p['factory'],(0x20000,0x4f0000));self.assertEqual(p['wallpaper'][0]+p['wallpaper'][1],FLASH_SIZE)
if __name__=='__main__':unittest.main()

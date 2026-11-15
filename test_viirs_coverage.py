"""Synthetic native HDF5 fixtures, separate from the real NASA evidence."""
from pathlib import Path
import tempfile,json,unittest
import numpy as np,h5py
import viirs_coverage
from validate_evidence import digest

class NasaViirsDecoderTests(unittest.TestCase):
 def fixture(self,mismatch=False):
  t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);root=Path(t.name);fn='VJ114IMG.A2024228.0842.002.test.nc';gn='VJ103IMG.A2024228.0842.021.test.nc'
  with h5py.File(root/fn,'w') as f:
   f.attrs.update(ShortName='VJ114IMG',VersionID='002',InputPointer='/test/'+('other.nc' if mismatch else gn),PlatformShortName='JPSS-1',StartTime='2024-08-15 08:42:00',EndTime='2024-08-15 08:48:00',DayNightFlag='Night')
   m=f.create_dataset('fire mask',data=np.array([[5,4],[1,8]],dtype='uint8'));m.attrs['legend']=np.array([b'0 not-processed\n1 bowtie\n2 glint\n3 water\n4 clouds\n5 clear land\n6 unclassified\n7 low confidence\n8 nominal confidence\n9 high confidence'])
   f.create_dataset('algorithm QA',data=np.zeros((2,2),dtype='uint32'))
   for k in ['FP_line','FP_sample','FP_latitude','FP_longitude']:f.create_dataset(k,data=np.array([],dtype='float32'))
  with h5py.File(root/gn,'w') as g:
   g.attrs.update(ShortName='VJ103IMG',VersionId='021',platform='JPSS-1');g.create_dataset('geolocation_data/latitude',data=np.full((2,2),44,dtype='float32'));g.create_dataset('geolocation_data/longitude',data=np.full((2,2),-120,dtype='float32'))
  (root/'manifest.json').write_text(json.dumps([{'file':k,'sha256':digest(root/k)} for k in [fn,gn]]));(root/'nasa-viirs-download-plan.json').write_text(json.dumps({'date':'2024-08-15','bbox':[-124,42,-116,46],'pairs':[{'mask':fn,'geolocation':gn}]}))
  viirs_coverage.process(root,root);return json.loads((root/'nasa-viirs-coverage.json').read_text())
 def test_hdf5_cloud_land_deleted_and_fire_are_distinct(self):
  d=self.fixture();self.assertTrue(d['all_selected_decoded']);self.assertEqual(d['pixel_samples'],4)
  for name in ['cloud','clear_nonfire_land','bowtie_deleted','nominal_fire']:self.assertEqual(d['counts'][name],1)
 def test_unrelated_geolocation_cannot_be_used(self):
  d=self.fixture(True);self.assertFalse(d['all_selected_decoded']);self.assertEqual(d['pixel_samples'],0)

if __name__=='__main__':unittest.main(verbosity=2)

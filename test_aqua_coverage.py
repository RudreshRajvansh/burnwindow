"""Synthetic HDF4 fixtures only, never mixed with real evidence artifacts."""
import unittest,tempfile,json
from pathlib import Path
import numpy as np
from pyhdf.SD import SD,SDC
import aqua_coverage
from validate_evidence import digest

class AquaDecoderTests(unittest.TestCase):
 def run_fixture(self,bad_shape=False,empty_fire=False):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
  fn='MYD14.A2024228.0955.061.test.hdf';gn='MYD03.A2024228.0955.061.test.hdf'
  f=SD(str(root/fn),SDC.WRITE|SDC.CREATE);s=f.create('fire mask',SDC.UINT8,(2,2));s[:]=np.array([[2,4],[5,9]],dtype='uint8');s.endaccess();f.attr('MOD03 input file').set(SDC.CHAR8,gn)
  if empty_fire:
   for name in ['FP_line','FP_sample','FP_latitude','FP_longitude']:s=f.create(name,SDC.FLOAT32,(0,));s.endaccess()
  f.end()
  g=SD(str(root/gn),SDC.WRITE|SDC.CREATE);shape=(2,3) if bad_shape else (2,2)
  for name,value in [('Latitude',44),('Longitude',-120)]:s=g.create(name,SDC.FLOAT32,shape);s[:]=np.full(shape,value,dtype='float32');s.endaccess()
  g.end();(root/'manifest.json').write_text(json.dumps([{'file':x,'sha256':digest(root/x),'test_fixture':True} for x in [fn,gn]]))
  (root/'aqua-download-plan.json').write_text(json.dumps({'date':'2024-08-15','bbox':[-124,42,-116,46],'pairs':[{'mask':fn,'geolocation':gn}]}))
  aqua_coverage.process(root,root);return json.loads((root/'aqua-coverage.json').read_text())
 def test_native_hdf4_and_modis_class_two_are_preserved(self):
  d=self.run_fixture();self.assertTrue(d['all_selected_decoded']);self.assertEqual(d['counts']['other_unprocessed'],1);self.assertEqual(d['counts']['cloud'],1);self.assertEqual(d['counts']['nonfire_land'],1);self.assertEqual(d['counts']['high_fire'],1)
 def test_mismatched_full_geolocation_cannot_be_verified(self):
  d=self.run_fixture(True);self.assertFalse(d['all_selected_decoded']);self.assertEqual(d['pixel_samples'],0);self.assertEqual(d['granules'][0]['state'],'unverified')
 def test_zero_length_sparse_fire_array_keeps_cloud_and_land_mask(self):
  d=self.run_fixture(empty_fire=True);self.assertTrue(d['all_selected_decoded']);self.assertEqual(d['pixel_samples'],4);self.assertEqual(d['granules'][0]['alignment_checks'],0)

if __name__=='__main__':unittest.main(verbosity=2)

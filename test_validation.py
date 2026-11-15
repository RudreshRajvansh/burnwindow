import unittest,tempfile,csv,json,copy
from pathlib import Path
import validate_evidence as ve
import coverage as cov
import earthdata_access as ed
from unittest.mock import patch,Mock

class ValidationTests(unittest.TestCase):
 def test_wape_bias_and_mae_have_distinct_meanings(self):
  m=ve.error_metrics([(10,20),(30,20)]);self.assertEqual(m['wape'],50);self.assertEqual(m['bias'],0);self.assertEqual(m['mae'],10)
 def test_zero_comparator_denominator_is_undefined(self):
  self.assertIsNone(ve.error_metrics([(0,1)])['wape'])
 def test_prediction_cannot_fit_target_labels(self):
  f={'annual':.5,'monthly':{'1':.25}};before=copy.deepcopy(f);p=ve.predict(8,f,1);self.assertEqual(p,{'raw':8,'annual':4,'pooled':2});self.assertEqual(f,before)
 def test_peak_displacement_wraps_calendar(self):
  rows=[{'month':1,'aqua':5,'pooled':1},{'month':12,'aqua':1,'pooled':5}];self.assertEqual(ve.peak_displacement(rows,'pooled'),1)
 def test_bad_qa_cannot_be_clear_land(self):
  import numpy as np
  mask=np.array([5,5,5,5,4,3,1,6,8,255],dtype='uint8');qa=np.array([0,1<<3,1<<5,1<<22,0,0,0,0,1<<4,0],dtype='uint32')
  self.assertEqual(cov.classified(mask,qa).tolist(),[5,10,10,10,4,3,1,6,10,11])
 def test_unknown_mask_schema_fails_closed(self):
  with self.assertRaises(ValueError):cov.validate_legends('cloud is clear','missing QA')
 def test_mismatched_shape_is_rejected(self):
  import numpy as np
  with self.assertRaises(ValueError):cov.classified(np.zeros((2,3)),np.zeros((3,2),dtype=int))
 def test_exact_source_geolocation_is_required(self):
  fn='EFIRE_v1r3_n20_s202408150841028_e202408150842255_c202408150927397.nc';gn='GITCO_j01_d20240815_t0841028_e0842255.h5'
  cov.check_pair(fn,gn,gn+',other.h5','n20','J01',(1536,6400),(1536,6400))
  with self.assertRaises(ValueError):cov.check_pair(fn,gn,'other.h5','n20','J01',(1536,6400),(1536,6400))
 def test_cross_platform_pair_is_rejected(self):
  with self.assertRaises(ValueError):cov.check_pair('x','y','y','n20','NPP',(1,1),(1,1))
 def test_token_destination_is_nasa_https_only(self):
  self.assertTrue(ed.authorized_url('https://data.lpdaac.earthdatacloud.nasa.gov/a.hdf'))
  for url in ['http://data.lpdaac.earthdatacloud.nasa.gov/a.hdf','https://evil.test/a.hdf','https://data.lpdaac.earthdatacloud.nasa.gov.evil.test/a.hdf','https://user@data.lpdaac.earthdatacloud.nasa.gov/a.hdf','https://data.lpdaac.earthdatacloud.nasa.gov/a?token=test']:
   self.assertFalse(ed.authorized_url(url))
 def test_modified_protocol_is_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'protocol.json').write_text('{}');(p/'protocol.sha256').write_text('bad  protocol.json')
   with self.assertRaises(ValueError):ve.read_protocol(p)
 def test_bearer_is_not_forwarded_to_nasa_cdn(self):
  redirect=Mock(status_code=303,headers={'Location':'https://d1nklfio7vscoe.cloudfront.net/science-file.hdf'});data=Mock(status_code=200)
  with patch('requests.get',side_effect=[redirect,data]) as get:
   self.assertIs(ed.data_response('https://data.lpdaac.earthdatacloud.nasa.gov/a.hdf','synthetic-test-only'),data)
   self.assertEqual(get.call_args_list[0].kwargs['headers'],{'Authorization':'Bearer synthetic-test-only'});self.assertEqual(get.call_args_list[1].kwargs['headers'],{})
 def test_unknown_redirect_gets_no_request_or_credential(self):
  redirect=Mock(status_code=302,headers={'Location':'https://unrelated.example/file'})
  with patch('requests.get',return_value=redirect) as get:
   with self.assertRaises(RuntimeError):ed.data_response('https://data.lpdaac.earthdatacloud.nasa.gov/a.hdf','synthetic-test-only')
   self.assertEqual(get.call_count,1)
 def test_invalid_source_cannot_silently_create_zero(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'source.csv';p.write_text('latitude,longitude,acq_date,acq_time,confidence,daynight,type,frp\nnan,0,2024-01-01,1200,n,D,0,1\n')
   with self.assertRaises(ValueError):list(ve.native_rows(p,'noaa20',2024))

if __name__=='__main__':unittest.main(verbosity=2)

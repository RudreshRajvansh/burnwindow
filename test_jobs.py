"""Job-state tests do not contact NASA or change the bundled database."""
import unittest
from unittest.mock import patch
import server

class JobTests(unittest.TestCase):
 def setUp(self):self.jobs=server.JOBS;server.JOBS={}
 def tearDown(self):server.JOBS=self.jobs
 def job(self):
  server.JOBS['test']={'id':'test','state':'queued','total':2,'done':0,'results':[],'errors':[],'current':None};return server.JOBS['test']
 def test_error_in_one_source_does_not_drop_success(self):
  j=self.job()
  with patch.object(server,'fetch_source',side_effect=[{'rows':4},ValueError('Invalid CSV')]):server.run_job('test',[{'id':'one'},{'id':'two'}])
  self.assertEqual(j['state'],'partial');self.assertEqual(j['done'],2);self.assertEqual(len(j['results']),1);self.assertEqual(j['errors'][0]['source'],'two')
 def test_cancel_preserves_committed_sources(self):
  j=self.job()
  def success(_):j['cancel']=True;return {'rows':4}
  with patch.object(server,'fetch_source',side_effect=success) as fetch:server.run_job('test',[{'id':'one'},{'id':'two'}])
  self.assertEqual(fetch.call_count,1);self.assertEqual(j['state'],'cancelled');self.assertEqual(j['done'],1)
 def test_only_one_ingestion_job(self):
  with patch.object(server.POOL,'submit'):
   server.new_job([{'id':'one'}])
   with self.assertRaises(ValueError):server.new_job([{'id':'two'}])
 def test_no_download_for_cached_archives(self):
  p=server.archive_plan({'countries':['Portugal'],'from':2018,'to':2025,'products':['modis','snpp','noaa20']});self.assertEqual(p['items'],[]);self.assertEqual(p['already_loaded'],24)
 def test_unknown_country_cannot_create_download_url(self):
  with self.assertRaises(ValueError):server.archive_plan({'countries':['../../file'],'from':2020,'to':2025})
 def test_current_partial_year_is_refused(self):
  with self.assertRaises(ValueError):server.archive_plan({'countries':['Portugal'],'from':2026,'to':2026})

if __name__=='__main__':unittest.main(verbosity=2)

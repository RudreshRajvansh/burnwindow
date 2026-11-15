"""Independent numerical and behavioral fixtures, separate from real evaluation data."""
import unittest,copy,math
import science

def months():
 return [{'year':y,'month':m,'aqua':(y-2017)*10+m,'target':2*((y-2017)*10+m)} for y in range(2019,2026) for m in range(1,13)]
def point(sensor,stamp='2025-01-01T12:00:00+00:00',lat=0,lon=0,dn='D'):
 return {'sensor':sensor,'stamp':stamp,'lat':lat,'lon':lon,'daynight':dn}

class ScienceTests(unittest.TestCase):
 def test_known_half_ratio_and_degenerate_bootstrap(self):
  d=science.diagnostic(months(),list(range(2019,2024)),[2024,2025],draws=60)
  self.assertEqual(d['bootstrap']['valid'],60)
  for v in d['bootstrap']['monthly_factor_bands'].values():self.assertEqual(v,[.5,.5])
  self.assertEqual(d['fit_band_check']['fraction'],1)
 def test_forward_folds_use_strictly_earlier_years(self):
  d=science.diagnostic(months(),list(range(2019,2024)),[2024,2025],draws=10)
  self.assertEqual([r['year'] for r in d['rolling_folds']],[2022,2023,2024,2025])
  for r in d['rolling_folds']:self.assertTrue(all(y<r['year'] for y in r['train_years']))
 def test_future_labels_cannot_change_fit_uncertainty(self):
  a=months();b=copy.deepcopy(a)
  for r in b:
   if r['year']>=2024:r['aqua']*=1000
  x=science.diagnostic(a,list(range(2019,2024)),[2024,2025],draws=40);y=science.diagnostic(b,list(range(2019,2024)),[2024,2025],draws=40)
  self.assertEqual(x['bootstrap'],y['bootstrap']);self.assertEqual(x['rolling_folds'][0],y['rolling_folds'][0]);self.assertNotEqual(x['fit_band_check'],y['fit_band_check'])
 def test_bootstrap_deterministic(self):
  args=(months(),list(range(2019,2024)),[2024,2025]);self.assertEqual(science.diagnostic(*args,draws=40),science.diagnostic(*args,draws=40))
 def test_sparse_reference_cannot_resolve_upper_decile(self):
  d=science.diagnostic(months(),list(range(2019,2024)),[2024,2025],draws=10)
  self.assertFalse(d['reference_resolution']['upper_decile_resolvable']);self.assertEqual(d['review_months'],24);self.assertAlmostEqual(d['reference_resolution']['minimum_rank_fraction'],1/6)
 def test_historical_reference_separate_from_conversion_fit(self):
  a=months()+[{'year':y,'month':m,'aqua':4,'target':None} for y in range(2003,2019) for m in range(1,13)]
  d=science.diagnostic(a,list(range(2019,2024)),[2024,2025],draws=10,baseline_years=list(range(2003,2024)))
  self.assertEqual(d['bootstrap']['training_years'],5);self.assertEqual(d['reference_resolution']['years'],21);self.assertTrue(d['reference_resolution']['upper_decile_resolvable']);self.assertAlmostEqual(d['reference_resolution']['minimum_rank_fraction'],1/22)
 def test_rank_fraction_handles_ties_conservatively(self):
  self.assertEqual(science.empirical_tail([1,2,3],3),.5);self.assertEqual(science.empirical_tail([1,2,3],4),.25);self.assertEqual(science.empirical_tail([1,2,3],0),1)
 def test_comparator_disagreement_flagged_even_outside_fit_band(self):
  a=months()+[{'year':y,'month':m,'aqua':4,'target':None} for y in range(2003,2019) for m in range(1,13)]
  for r in a:
   if r['year'] in (2024,2025):r.update(aqua=100,target=2)
  d=science.diagnostic(a,list(range(2019,2024)),[2024,2025],draws=10,baseline_years=list(range(2003,2024)))
  self.assertEqual(d['review_months'],24)
  for r in d['evaluation']:
   self.assertTrue(r['comparator_disagreement']);self.assertFalse(r['band_crosses_p90']);self.assertIn('disagree',r['review_reason'])
 def test_temporal_gates_are_nested(self):
  rows=[point('aqua')]+[point('noaa20',stamp=f'2025-01-01T12:{m:02d}:00+00:00') for m in (4,10,29,31)]
  d=science.associations(rows,'noaa20');self.assertEqual([w['edges'] for w in d['windows']],[1,2,3])
 def test_longitude_seam_proximity(self):
  d=science.associations([point('aqua',lon=179.999),point('noaa20',lon=-179.999)],'noaa20');self.assertEqual(d['windows'][0]['edges'],1)
 def test_polar_proximity(self):
  d=science.associations([point('aqua',lat=89.999,lon=0),point('noaa20',lat=89.999,lon=180)],'noaa20');self.assertEqual(d['windows'][0]['edges'],1)
 def test_midnight_association(self):
  d=science.associations([point('aqua','2025-01-01T23:59:00+00:00'),point('noaa20','2025-01-02T00:01:00+00:00')],'noaa20');self.assertEqual(d['windows'][0]['edges'],1)
 def test_day_night_and_spatial_gates(self):
  d=science.associations([point('aqua'),point('noaa20',dn='N'),point('noaa20',lat=.1)],'noaa20');self.assertEqual(d['windows'][-1]['edges'],0)
 def test_many_to_many_does_not_inflate_matched_sensor_count(self):
  d=science.associations([point('aqua'),point('noaa20'),point('noaa20',lon=.001)],'noaa20');self.assertEqual(d['windows'][0]['edges'],2);self.assertEqual(d['windows'][0]['aqua_matched'],1);self.assertEqual(d['windows'][0]['target_matched'],2)
 def test_no_positive_records_has_null_fraction(self):
  d=science.associations([],'noaa20');self.assertIsNone(d['windows'][0]['aqua_fraction'])

if __name__=='__main__':unittest.main(verbosity=2)

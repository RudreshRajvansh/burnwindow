"""Behavioral regression tests. All fixtures are synthetic and never appear in the app."""
import unittest,tempfile,csv,sys
from pathlib import Path
import engine

FIELDS=['latitude','longitude','acq_date','acq_time','satellite','confidence','daynight','frp','type']
def row(lat=0,lon=0,day='2025-01-01',time='1200',sat='Aqua',confidence='80',kind='0',dn='D'):
 return dict(zip(FIELDS,[lat,lon,day,time,sat,confidence,dn,'10',kind]))

class EngineTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.db=self.root/'test.sqlite';engine.initialize(self.db)
 def tearDown(self):self.temp.cleanup()
 def ingest(self,name,rows,product='modis',year=2025,tier='standard',country='Test'):
  p=self.root/name
  with p.open('w',newline='') as f:
   w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
  return engine.ingest(self.db,p,dict(id=name,url='https://example.test/'+name,tier=tier,country=country,product=product,start=f'{year}-01-01' if tier=='standard' else None,end=f'{year}-12-31' if tier=='standard' else None))
 def scope(self,**kw):return engine.scope(dict(lat=0,lon=0,radius=100,grid=10,sensor='noaa20',tier='standard',countries='Test',start='2025-01-01',end='2025-01-03',**kw))
 def test_quality_and_platform_separation(self):
  self.ingest('m.csv',[row(),row(time='1210',sat='Terra'),row(lat=.1,confidence='10'),row(lat=.2,kind='2'),row(lat=.3,dn='N')])
  self.ingest('n.csv',[row(sat='N20',confidence='nominal'),row(lat=.2,confidence='low')],product='noaa20')
  d=engine.analyze(self.db,self.scope());self.assertEqual(d['stats']['aqua']['reports'],1);self.assertEqual(d['stats']['terra']['reports'],1);self.assertEqual(d['stats']['noaa20']['reports'],1);self.assertEqual(d['quality_excluded'],3);self.assertEqual(d['overlap']['both'],1)
 def test_cell_day_deduplicates_multiple_passes(self):
  self.ingest('m.csv',[row(),row(),row(time='1215')]);d=engine.analyze(self.db,self.scope());self.assertEqual(d['stats']['aqua']['reports'],2);self.assertEqual(d['stats']['aqua']['cell_days'],1)
 def test_reingest_idempotent(self):
  a=self.ingest('m.csv',[row()]);b=self.ingest('m.csv',[row()]);self.assertTrue(b['unchanged']);self.assertEqual(engine.analyze(self.db,self.scope())['stats']['aqua']['reports'],1)
 def test_invalid_source_rolls_back(self):
  self.ingest('m.csv',[row()]);
  with self.assertRaises(ValueError):self.ingest('m.csv',[row(lat='nan')])
  self.assertEqual(engine.analyze(self.db,self.scope())['stats']['aqua']['reports'],1)
 def test_missing_is_null_not_zero(self):
  self.ingest('m.csv',[row()]);d=engine.analyze(self.db,self.scope());self.assertIsNone(d['series'][0]['noaa20']);self.assertEqual(d['series'][1]['aqua'],0);self.assertEqual(d['coverage'],'unknown')
 def test_empty_nrt_is_unavailable(self):
  self.ingest('n.csv',[],product='snpp',tier='nrt',country='Global');s=self.scope();s.update(tier='nrt',sensor='snpp');d=engine.analyze(self.db,s);self.assertFalse(d['stats']['snpp']['file_complete']);self.assertTrue(all(x['snpp'] is None for x in d['series']))
 def test_antimeridian_circle(self):
  self.ingest('m.csv',[row(lon=179.9),row(lon=-179.9),row(lon=0)]);s=self.scope();s.update(lon=180);d=engine.analyze(self.db,s);self.assertEqual(d['stats']['aqua']['reports'],2)
 def test_polar_circle(self):
  self.ingest('m.csv',[row(lat=89.9,lon=170),row(lat=89.9,lon=-60),row(lat=80)]);s=self.scope();s.update(lat=90);d=engine.analyze(self.db,s);self.assertEqual(d['stats']['aqua']['reports'],2)
 def test_utc_midnight_is_two_cell_days(self):
  self.ingest('m.csv',[row(time='2359'),row(day='2025-01-02',time='0001')]);d=engine.analyze(self.db,self.scope());self.assertEqual(d['stats']['aqua']['cell_days'],2)
 def test_native_time_is_validated(self):
  with self.assertRaises(ValueError):self.ingest('m.csv',[row(time='2460')])
 def test_preoperation_is_missing(self):
  src=[dict(product='noaa20',country='Test',start='2018-01-01',end='2018-12-31')]
  self.assertFalse(engine.available(src,'noaa20','2018-01-01','2018-01-31',['Test']));self.assertTrue(engine.available(src,'noaa20','2018-04-01','2018-04-30',['Test']))
 def test_country_union_requires_each_source(self):
  src=[dict(product='modis',country='A',start='2025-01-01',end='2025-12-31')];self.assertFalse(engine.available(src,'aqua','2025-01-01','2025-02-01',['A','B']))
 def test_intervening_year_gap_not_filled(self):
  src=[dict(product='modis',country='Test',start=f'{y}-01-01',end=f'{y}-12-31') for y in [2021,2023]];self.assertFalse(engine.available(src,'aqua','2021-01-01','2023-12-31',['Test']))
 def test_nonfinite_coordinates_rejected(self):
  for v in ['nan','inf','-inf']:
   with self.assertRaises(ValueError):engine.scope({'lat':v})
 def test_invalid_scope_rejected(self):
  for change in [dict(lat=91),dict(lon=181),dict(grid=7),dict(sensor='fake'),dict(daynight='X'),dict(start='2025-02-01',end='2025-01-01')]:
   with self.assertRaises(ValueError):engine.scope(change)
 def test_small_support_refuses_fit(self):
  self.ingest('m.csv',[row()]);self.ingest('n.csv',[row(confidence='h')],product='noaa20');d=engine.historical(self.db,self.scope());self.assertEqual(d['model']['state'],'insufficient')
 def test_test_years_never_influence_factors(self):
  for y in range(2019,2026):
   rr=[row(day=f'{y}-{m:02d}-{day:02d}') for m in range(1,13) for day in range(1,5)]
   self.ingest(f'm{y}.csv',rr,year=y);self.ingest(f'n{y}.csv',[{**r,'confidence':'n'} for r in rr],product='noaa20',year=y)
  d=engine.historical(self.db,self.scope());self.assertEqual(d['model']['train_years'],list(range(2019,2024)));self.assertEqual(d['model']['test_years'],[2024,2025]);self.assertEqual(d['model']['regional_factor'],1)
  self.ingest('m2003.csv',[row(day=f'2003-01-{day:02d}') for day in range(1,21)],year=2003)
  older=engine.historical(self.db,self.scope());self.assertEqual(d['model']['monthly_factors'],older['model']['monthly_factors']);self.assertEqual(d['model']['science']['bootstrap'],older['model']['science']['bootstrap']);self.assertEqual(older['model']['baseline_years'],[2003]+list(range(2019,2024)))
  self.assertNotEqual(d['months'][0]['p90'],older['months'][0]['p90'])
  self.ingest('n2025.csv',[row(day='2025-01-01',confidence='h')],product='noaa20');e=engine.historical(self.db,self.scope());self.assertEqual(d['model']['monthly_factors'],e['model']['monthly_factors']);self.assertNotEqual(d['model']['metrics'],e['model']['metrics'])
 def test_standard_and_nrt_never_mix(self):
  self.ingest('m.csv',[row()]);self.ingest('live.csv',[row(lat=.1)],tier='nrt',country='Global');d=engine.analyze(self.db,self.scope());self.assertEqual(d['stats']['aqua']['reports'],1)
 def test_zero_denominator_has_no_percent_error(self):self.assertIsNone(engine.metrics([(0,4)])['wape'])
 def test_cell_wrap_consistency(self):self.assertEqual(engine.cell(0,-180,10),engine.cell(0,180,10))

if __name__=='__main__':unittest.main(verbosity=2)

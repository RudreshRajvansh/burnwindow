"""Verify sealed evidence and native pixel-vector integrity without raw downloads."""
from pathlib import Path
import hashlib, json

APP = Path(__file__).resolve().parents[1]
V = APP / 'data/validation'

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def read(name):
    return json.loads((V / name).read_text(encoding='utf-8'))

def verify():
    sealed = list(V.glob('*.sha256'))
    for path in sealed:
        expected, filename = path.read_text().split()
        assert digest(V / filename) == expected, filename
    protocol = read('protocol.json')
    for name, expected in protocol['code_sha256'].items():
        assert digest(V / 'frozen_code' / name) == expected, name
    for name in ['geographic.json', 'independent.json']:
        result = read(name)
        assert result['protocol_sha256'] == digest(V / 'protocol.json')
        assert result['evaluator_sha256'] == digest(APP / 'validate_evidence.py')
    geographic = read('geographic.json')
    assert len(geographic['cases']) == 16 and not geographic['source_failures']
    assert sum(len(case['months']) for case in geographic['cases']) == 384
    assert all(not case['missing_months'] for case in geographic['cases'])
    independent = read('independent.json')
    assert len(independent['events']) == 23
    assert digest(V / 'mtbs-reference.geojson') == independent['reference_manifest']['sha256']
    for name, processor in [('coverage.json', 'coverage.py'), ('nasa-viirs-coverage.json', 'viirs_coverage.py')]:
        assert read(name)['processor_sha256'] == digest(APP / processor)
    ledger = read('native-processing-ledger.json')
    assert digest(V / ledger['aqua_result']) == ledger['aqua_result_sha256']
    assert digest(V / ledger['nasa_viirs_result']) == ledger['nasa_viirs_result_sha256']
    assert digest(V / 'frozen_code/aqua_coverage_v3.py') == ledger['aqua_processor_sha256']
    assert digest(APP / 'aqua_coverage.py') == ledger['aqua_processor_sha256']
    pixel_files = 0
    for name, visits, pairs in [('coverage.json', 758933, 4), ('aqua-coverage-v3.json', 314673, 5), ('nasa-viirs-coverage.json', 5698900, 4)]:
        result = read(name)
        assert len(result['granules']) == pairs
        assert sum(result['counts'].values()) == result['pixel_samples'] == visits
        assert sum(g['pixel_samples'] for g in result['granules']) == visits
        for granule in result['granules']:
            assert granule.get('state', granule.get('status')) in ('decoded_native_samples', 'verified_product_samples')
            assert granule['max_alignment_error_degrees'] in (None, 0.0)
            if 'pixel_evidence' in granule:
                vector = granule['pixel_evidence']
                assert digest(V / vector['file']) == vector['sha256'], vector['file']
                pixel_files += 1
    print(f'PASS: {len(sealed)} sealed hashes; frozen models/evaluators; all 16 geographic and 23 event cases; 13 paired swaths; {pixel_files} native vector files.')

if __name__ == '__main__':
    verify()
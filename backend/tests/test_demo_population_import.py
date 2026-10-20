from copy import deepcopy
import zipfile
import json
import shutil
import sqlite3
from dataclasses import asdict

from backend.app.models import LayerRecord, ProjectRecord
from backend.app.state_writer import StateWriterLease, StateWriterAlreadyActive
from scripts import migrate_demo_population_lesson as migration
from scripts.import_shanghai_township_population import sha256

import pytest

from scripts.import_shanghai_township_population import DISTRICTS, parse_rows, join_boundaries
from scripts.migrate_demo_population_lesson import build_stages, decorate_population

HEADER = [None, '总人口（人）', '0-14岁人口（人）', '15-59岁人口（人）',
          '60岁及以上人口（人）', '65岁及以上人口（人）',
          '居住本乡、镇、街道，户口在本乡、镇、街道人口（人）']


def sample_rows():
    rows = [HEADER, ['上海市',1600,160,1120,320,160,800]]
    for district in DISTRICTS.values():
        rows += [[district,100,10,70,20,10,50], ['同名工业区',100,10,70,20,10,50]]
    return rows


def sample_boundaries():
    features=[]
    for i,(code,district) in enumerate(DISTRICTS.items()):
        x=121+i/100
        features.append({'type':'Feature','properties':{'name':'同名工业区','code':code+'001000'},
                         'geometry':{'type':'Polygon','coordinates':[[[x,31],[x+.005,31],[x+.005,31.005],[x,31.005],[x,31]]]}})
    return {'type':'FeatureCollection','features':features}


def test_preserves_special_units_and_scopes_same_names_by_district():
    table=parse_rows(sample_rows())
    assert len(table['records'])==16
    assert table['city_population']==1600
    assert all(r['name']=='同名工业区' for r in table['records'])
    geo,receipt=join_boundaries(table,sample_boundaries(),'test_hash')
    assert receipt['population']==1600
    assert len({f['properties']['boundary_code'] for f in geo['features']})==16
    assert all('density' not in f['properties'] for f in geo['features'])


@pytest.mark.parametrize('mutation', ['negative','decimal','string','bool','age_sum','older','local','district_sum','city_sum','duplicate','unknown_district','wrong_units'])
def test_rejects_bad_or_ambiguous_input(mutation):
    rows=sample_rows()
    if mutation=='negative': rows[3][1]=-1
    elif mutation=='decimal':rows[3][1]=100.5
    elif mutation=='string':rows[3][1]='100'
    elif mutation=='bool':rows[3][1]=True
    elif mutation=='age_sum':rows[3][2]=11
    elif mutation=='older':rows[3][5]=21
    elif mutation=='local':rows[3][6]=101
    elif mutation=='district_sum':rows[2][1:6]=[101,11,70,20,10]
    elif mutation=='city_sum':rows[1][1:6]=[1601,161,1120,320,160]
    elif mutation=='duplicate':rows.insert(4,deepcopy(rows[3]))
    elif mutation=='unknown_district':rows[2][0]='非上海区'
    elif mutation=='wrong_units':rows[0]=[None,'总人口（万人）',*HEADER[2:]]
    with pytest.raises(ValueError):parse_rows(rows)


def test_missing_local_registration_stays_null():
    rows=sample_rows();rows[3][6]=None
    table=parse_rows(rows)
    assert table['records'][0]['local_registered_residents'] is None
    assert table['records'][0]['population']==100


@pytest.mark.parametrize('mutation',['missing','duplicate_name','duplicate_code','wrong_district','point','outside','lossy_repair'])
def test_rejects_missing_duplicate_or_unusable_boundaries(mutation):
    table=parse_rows(sample_rows());geo=sample_boundaries()
    if mutation=='missing':geo['features'].pop()
    elif mutation=='duplicate_name':geo['features'].append(deepcopy(geo['features'][0]))
    elif mutation=='duplicate_code':geo['features'][1]['properties']['code']=geo['features'][0]['properties']['code']
    elif mutation=='wrong_district':geo['features'][0]['properties']['code']='110101001000'
    elif mutation=='point':geo['features'][0]['geometry']={'type':'Point','coordinates':[121,31]}
    elif mutation=='outside':geo['features'][0]['geometry']['coordinates']=[[[1,1],[2,1],[2,2],[1,1]]]
    elif mutation=='lossy_repair':geo['features'][0]['geometry']['coordinates']=[[[121,31],[121.1,31.1],[121,31.1],[121.1,31],[121,31]]]
    with pytest.raises(ValueError):join_boundaries(table,geo,'test')


def test_history_alias_is_labelled_and_cannot_be_used_twice():
    rows=sample_rows();i=list(DISTRICTS.values()).index('杨浦区')
    rows[3+i*2][0]='长海路街道';table=parse_rows(rows)
    geo=sample_boundaries();geo['features'][i]['properties']['name']='五角场镇'
    joined,receipt=join_boundaries(table,geo,'hash')
    p=joined['features'][i]['properties']
    assert p['name']=='长海路街道' and p['boundary_name']=='五角场镇'
    assert '2019' in p['boundary_status'] and '待核验' in p['boundary_status']
    assert len(receipt['aliases'])==1


def test_population_colors_use_counts_without_modifying_source():
    geo,_=join_boundaries(parse_rows(sample_rows()),sample_boundaries(),'test')
    geo['features'][0]['properties']['population']=500000
    styled,classes=decorate_population(geo)
    assert styled['features'][0]['properties']['__fillColor']!=styled['features'][1]['properties']['__fillColor']
    assert '__fillColor' not in geo['features'][0]['properties']
    assert len(classes)==6


def test_slide_order_full_frame_and_original_text_preserved(tmp_path):
    pptx=tmp_path/'fixture.pptx'
    with zipfile.ZipFile(pptx,'w') as z:
        write_presentation_order(z, list(range(1, 12)))
        for n in range(1,12):
            z.writestr(f'ppt/slides/slide{n}.xml',f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:t>第{n}页原文</a:t></p:sld>')
    stages=build_stages(pptx,{'slide_count':11,'slides':[{}]*11,'renderer':'fixture'},'/files/uploads/scoped', ['existing'])
    assert len(stages)==11
    assert stages[9]['content']=='第10页原文'
    assert stages[9]['presentation']['blocks'][0]['asset']['url'].endswith('slide_10.png')
    assert all(s['presentation']['blocks'][0]['w']==1 and s['presentation']['blocks'][0]['h']==1 for s in stages)
    assert stages[6]['actions'][0]['scene']['layer_visibility']['existing'] is False
    assert all(s['timing_mode']=='teacher' for s in stages)
    assert stages[6]['scene']['globe']=={'enabled': False}
    assert stages[7]['scene']['layer_visibility']['shanghai_township_population_2020'] is True
    assert stages[7]['scene']['view']['zoom']==9
    with pytest.raises(ValueError):build_stages(pptx,{'slide_count':10,'slides':[{}]*10,'renderer':'fixture'},'/files/uploads/scoped',[])


def write_presentation_order(archive, order):
    p_ns = 'http://schemas.openxmlformats.org/presentationml/2006/main'
    r_ns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    archive.writestr('ppt/presentation.xml',
        f'<p:presentation xmlns:p="{p_ns}" xmlns:r="{r_ns}"><p:sldIdLst>' +
        ''.join(f'<p:sldId id="{255+i}" r:id="rId{n}"/>' for i, n in enumerate(order)) +
        '</p:sldIdLst></p:presentation>')
    archive.writestr('ppt/_rels/presentation.xml.rels',
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        ''.join(f'<Relationship Id="rId{n}" Type="{r_ns}/slide" Target="slides/slide{n}.xml"/>'
                for n in set(order)) + '</Relationships>')


def test_reordered_presentation_text_matches_native_page_number(tmp_path):
    pptx = tmp_path/'reordered.pptx'
    with zipfile.ZipFile(pptx, 'w') as archive:
        write_presentation_order(archive, [3, 1, 2])
        for n in range(1, 4):
            archive.writestr(f'ppt/slides/slide{n}.xml',
                f'<sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:t>original {n}</a:t></sld>')
    stages = build_stages(pptx, {'slide_count': 3, 'slides': [{}]*3, 'renderer': 'native'}, '/owned', [])
    assert [s['content'] for s in stages] == ['original 3', 'original 1', 'original 2']
    assert [s['presentation']['blocks'][0]['asset']['url'] for s in stages] == [
        '/owned/slides/slide_01.png', '/owned/slides/slide_02.png', '/owned/slides/slide_03.png']


@pytest.fixture
def isolated_migration(tmp_path, monkeypatch):
    # A source instance and a separate clone; never open repository/production data.
    original = tmp_path/'original'
    (original/'state/layer_data').mkdir(parents=True)
    (original/'auth').mkdir()
    legacy = LayerRecord.create(layer_id='builtin_population_regions', name='old rectangles',
        kind='vector', source='builtin', geometry_type='Polygon', data={
            'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': {},
                'geometry': {'type': 'Polygon', 'coordinates': [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}}]})
    query = LayerRecord.create(layer_id='visual_query_existing', name='old query',
        kind='vector', source='query', geometry_type='Polygon')
    project = ProjectRecord.create(owner_user_id='owner')
    project.layers = [legacy, query]
    project.enabled_templates = ['population_distribution', 'other']
    project.active_layer_id = legacy.layer_id
    other = deepcopy(project)
    other.project_id = 'unrelated'
    other.owner_user_id = 'another_owner'
    other.layers[0].data = {'type': 'FeatureCollection', 'features_file': 'old.json'}
    (original/'state/layer_data/old.json').write_text(json.dumps(legacy.data), encoding='utf-8')
    snapshot = {key: {} for key in ('projects', 'jobs', 'artifacts', 'lessons', 'lesson_designs',
        'lesson_rehearsals', 'class_sessions', 'conversations', 'messages', 'confirmations', 'workflows')}
    snapshot['projects'] = {p.project_id: asdict(p) for p in (project, other)}
    (original/'state/runtime.json').write_text(json.dumps(snapshot), encoding='utf-8')
    with sqlite3.connect(original/'auth/auth.db') as db:
        db.executescript("""
            CREATE TABLE users(user_id TEXT PRIMARY KEY, email TEXT, status TEXT);
            INSERT INTO users VALUES ('owner', 'demo@example.invalid', 'active');
            CREATE TABLE user_files(path TEXT PRIMARY KEY, user_id TEXT REFERENCES users(user_id), created_at TEXT);
            INSERT INTO user_files VALUES ('original-private-file', 'owner', 'old-timestamp');
            CREATE TABLE auth_settings(key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO auth_settings VALUES ('keep', 'unchanged');
        """)
    root = tmp_path/'isolated-copy'
    shutil.copytree(original, root)
    package = tmp_path/'package'
    (package/'slides').mkdir(parents=True)
    (package/'prepared').mkdir()
    pptx = tmp_path/'source.pptx'
    with zipfile.ZipFile(pptx, 'w') as archive:
        write_presentation_order(archive, [2, 1])
        for n in (1, 2):
            archive.writestr(f'ppt/slides/slide{n}.xml',
                f'<sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:t>text {n}</a:t></sld>')
    slides = []
    for n in (1, 2):
        path = package/f'slides/slide_{n:02d}.png'
        path.write_bytes(b'native-image-' + bytes([n]))
        slides.append({'number': n, 'file': f'slides/slide_{n:02d}.png', 'sha256': sha256(path)})
    manifest = {'source_sha256': sha256(pptx), 'slide_count': 2, 'slides': slides, 'renderer': 'native'}
    (package/'render_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    (package/'boundary_source.json').write_text('{}', encoding='utf-8')
    geo, receipt = join_boundaries(parse_rows(sample_rows()), sample_boundaries(), 'xlsx-hash')
    receipt.update(source_sha256='xlsx-hash', source_file_name='private.xlsx')
    for name, value in [('population_receipt.json', receipt), ('shanghai_township_population_2020.geojson', geo)]:
        (package/'prepared'/name).write_text(json.dumps(value), encoding='utf-8')
    (package/'prepared/shanghai_township_population_2020.csv').write_text('private fixture', encoding='utf-8')
    # Production remains running; simulate closed ports ONLY inside this test.
    monkeypatch.setattr(migration.socket.socket, 'connect_ex', lambda *_: 111)
    return original, root, project.project_id, package, pptx


def tree_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def run_isolated(fixture, apply):
    _, root, project_id, package, pptx = fixture
    return migration.migrate(root, project_id, 'demo@example.invalid', package, pptx, apply)


def test_apply_backs_up_before_any_mutation_and_preserves_legacy_layers(isolated_migration, monkeypatch):
    original, root, project_id, _, _ = isolated_migration
    original_files = tree_bytes(original)
    before = json.loads((root/'state/runtime.json').read_text(encoding='utf-8'))
    old_backup = migration.backup_original
    calls = []

    def checked_backup(*args):
        assert sha256(root/'state/runtime.json') == sha256(original/'state/runtime.json')
        with pytest.raises(StateWriterAlreadyActive):
            StateWriterLease(root/'state/runtime.json')
        assert not (root/'uploads').exists()
        old_backup(*args)
        calls.append(args[2])

    monkeypatch.setattr(migration, 'backup_original', checked_backup)
    # Both read-only and writable RuntimeStore constructors clean old layers in
    # memory; the migration must never use either to build its saved snapshot.
    from backend.app.store import RuntimeStore
    monkeypatch.setattr(RuntimeStore, '__init__', lambda *_a, **_k: pytest.fail('mutating store loaded'))
    report = run_isolated(isolated_migration, True)
    assert len(calls) == 1
    backup = calls[0]
    manifest = json.loads((backup/'backup_manifest.json').read_text())
    assert manifest['complete']
    assert all(sha256(backup/name) == digest for name, digest in manifest['files'].items())
    assert (backup/'runtime.json').read_bytes() == original_files['state/runtime.json']
    assert (backup/'layer_data/old.json').read_bytes() == original_files['state/layer_data/old.json']
    after = json.loads((root/'state/runtime.json').read_text(encoding='utf-8'))
    added = after['projects'][project_id]['layers'].pop()
    assert added['metadata']['workflow_style']['legend']['title'] == '2020街镇人口总量'
    after['projects'][project_id]['updated_at'] = before['projects'][project_id]['updated_at']
    lesson = after['lessons'].pop(report['lesson_id'])
    assert [s['content'] for s in lesson['stages']] == ['text 2', 'text 1']
    assert after == before  # includes target AND unrelated legacy population/query layers
    with sqlite3.connect(root/'auth/auth.db') as db:
        assert db.execute('SELECT * FROM auth_settings').fetchall() == [('keep', 'unchanged')]
        grants = db.execute('SELECT * FROM user_files').fetchall()
        assert ('original-private-file', 'owner', 'old-timestamp') in grants
    assert tree_bytes(original) == original_files
    with pytest.raises(ValueError, match='Migration already exists'):
        run_isolated(isolated_migration, True)


@pytest.mark.parametrize('apply', [False, True])
@pytest.mark.parametrize('malformation', ['declared_count', 'preview_list', 'preview_order', 'missing_asset', 'missing_csv', 'missing_relationships'])
def test_invalid_package_fails_read_only_before_backup_files_or_grants(isolated_migration, apply, malformation):
    _, root, _, package, pptx = isolated_migration
    manifest_path = package/'render_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if malformation == 'declared_count': manifest['slide_count'] = 3
    elif malformation == 'preview_list': manifest['slides'].pop()
    elif malformation == 'preview_order': manifest['slides'][0]['number'] = 2
    elif malformation == 'missing_asset': (package/'slides/slide_01.png').unlink()
    elif malformation == 'missing_csv': (package/'prepared/shanghai_township_population_2020.csv').unlink()
    elif malformation == 'missing_relationships':
        with zipfile.ZipFile(pptx, 'w') as archive:
            archive.writestr('ppt/slides/slide1.xml', '<sld/>')
        manifest['source_sha256'] = sha256(pptx)
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    before = tree_bytes(root)
    with pytest.raises((ValueError, FileNotFoundError)):
        run_isolated(isolated_migration, apply)
    assert tree_bytes(root) == before
    assert not (root/'uploads').exists() and not (root/'_backup').exists()


def test_valid_dry_run_never_loads_or_writes_state(isolated_migration):
    _, root, *_ = isolated_migration
    before = tree_bytes(root)
    report = run_isolated(isolated_migration, False)
    assert report['slide_count'] == 2
    assert tree_bytes(root) == before


def test_failed_backup_blocks_all_teaching_data_changes(isolated_migration, monkeypatch):
    _, root, *_ = isolated_migration
    before = tree_bytes(root)
    def fail_backup(*args):
        raise OSError('simulated backup failure')
    monkeypatch.setattr(migration, 'backup_original', fail_backup)
    with pytest.raises(OSError, match='backup failure'):
        run_isolated(isolated_migration, True)
    after = tree_bytes(root)
    # POSIX retains its lease inode by contract; Windows uses a named mutex.
    # Only that empty coordination file is allowed, never teaching/auth data.
    assert after.pop('state/.runtime-writer.lock', None) in (None, b'')
    assert after == before


def test_existing_writer_prevents_backup_and_apply(isolated_migration):
    _, root, *_ = isolated_migration
    lease = StateWriterLease(root/'state/runtime.json')
    try:
        before = tree_bytes(root)
        with pytest.raises(StateWriterAlreadyActive):
            run_isolated(isolated_migration, True)
        assert tree_bytes(root) == before
    finally:
        lease.close()


def test_corrupt_backup_copy_cannot_cross_write_barrier(isolated_migration, monkeypatch):
    _, root, *_ = isolated_migration
    before = tree_bytes(root)
    copy = migration.shutil.copy2
    def corrupt_copy(source, destination):
        result = copy(source, destination)
        if str(destination).endswith('runtime.json'):
            destination.write_bytes(b'corrupt backup')
        return result
    monkeypatch.setattr(migration.shutil, 'copy2', corrupt_copy)
    with pytest.raises(RuntimeError, match='Backup hash verification failed'):
        run_isolated(isolated_migration, True)
    assert {name: (root/name).read_bytes() for name in before} == before
    assert not (root/'uploads').exists()
    assert not list((root/'_backup').rglob('backup_manifest.json'))


def test_preflight_state_change_is_rejected_before_backup(isolated_migration, monkeypatch):
    _, root, *_ = isolated_migration
    lease = migration.StateWriterLease
    state = root/'state/runtime.json'
    changed = state.read_bytes() + b' '
    def concurrent_change(path):
        state.write_bytes(changed)
        return lease(path)
    monkeypatch.setattr(migration, 'StateWriterLease', concurrent_change)
    with pytest.raises(RuntimeError, match='State changed during preflight'):
        run_isolated(isolated_migration, True)
    assert state.read_bytes() == changed
    assert not (root/'uploads').exists() and not (root/'_backup').exists()

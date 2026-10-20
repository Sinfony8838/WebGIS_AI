"""Migrate a prepared private population package into one existing demo project.

Run only with the server stopped. A StateWriterLease is mandatory.
The migration appends a new lesson/layer, backs up state and auth, and verifies
all pre-existing records. No password reset, built-in lesson update or service
startup is performed. --apply is required for writes.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
import posixpath
from pathlib import Path
import shutil
import socket
import sqlite3
import sys
import zipfile
from uuid import uuid4
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.models import LayerRecord, LessonRecord, utc_now
from backend.app.state_writer import StateWriterLease
from backend.app.services.lessons import LessonService
from scripts.import_shanghai_township_population import sha256

TITLE = '人口分布模拟课件（2026-10-20最新版）'
LAYER_ID = 'shanghai_township_population_2020'
LAYER_NAME = '上海街镇人口总量（2020，历史边界参照）'


def ordered_slide_parts(archive):
    """Resolve native presentation order; slide filenames are not page numbers."""
    p_ns = 'http://schemas.openxmlformats.org/presentationml/2006/main'
    r_ns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    rel_ns = 'http://schemas.openxmlformats.org/package/2006/relationships'
    try:
        presentation = ET.fromstring(archive.read('ppt/presentation.xml'))
        relationships = ET.fromstring(archive.read('ppt/_rels/presentation.xml.rels'))
        rels = {}
        for rel in relationships.findall(f'{{{rel_ns}}}Relationship'):
            if rel.attrib['Id'] in rels:
                raise ValueError('Duplicate presentation relationship')
            rels[rel.attrib['Id']] = rel.attrib
        names = []
        for slide in presentation.findall(f'{{{p_ns}}}sldIdLst/{{{p_ns}}}sldId'):
            rel = rels[slide.attrib[f'{{{r_ns}}}id']]
            if rel.get('TargetMode') == 'External' or rel.get('Type') != r_ns + '/slide':
                raise ValueError('Slide relationship must reference an internal slide')
            target = rel['Target']
            name = posixpath.normpath(target.lstrip('/') if target.startswith('/')
                                     else posixpath.join('ppt', target))
            if not name.startswith('ppt/slides/') or not name.endswith('.xml') or name not in archive.namelist():
                raise ValueError('Invalid or missing slide relationship target')
            if name in names:
                raise ValueError('Duplicate presentation slide reference')
            names.append(name)
        if not names:
            raise ValueError('Presentation has no ordered slides')
        return names
    except (KeyError, ET.ParseError) as exc:
        raise ValueError('Invalid PPTX presentation relationships') from exc


def build_stages(pptx: Path, manifest, url_prefix: str, existing_layer_ids):
    with zipfile.ZipFile(pptx) as z:
        names = ordered_slide_parts(z)
        if (type(manifest['slide_count']) is not int or len(names) != manifest['slide_count']
                or len(manifest['slides']) != len(names)):
            raise ValueError('PPTX and preview counts disagree')
        stages = []
        for i, name in enumerate(names, 1):
            text = ' '.join(t.text or '' for t in ET.fromstring(z.read(name)).iter(
                '{http://schemas.openxmlformats.org/drawingml/2006/main}t'))
            block = {'id': f'ppt_slide_{i:02d}', 'type': 'image', 'text': '',
                     'asset': {'url': f'{url_prefix}/slides/slide_{i:02d}.png',
                               'mime_type': 'image/png', 'name': f'原课件第{i}页'},
                     'x': 0.0, 'y': 0.0, 'w': 1.0, 'h': 1.0, 'z': 0, 'order': 1}
            scene = {'layer_visibility': {}}
            actions = []
            if i in (7, 8):
                actions = [{'action_id': f'shanghai_population_{i}',
                            'type': 'scene', 'label': '上海街镇人口总量图（2020）',
                            'note': LAYER_NAME + '；总量不等于密度，旧边界仅作参照。',
                            'scene': {'globe': {'enabled': False}, 'layer_visibility': {**{k: False for k in existing_layer_ids}, LAYER_ID: True},
                                      'view': {'center': [121.45, 31.15], 'zoom': 9,
                                               'extent': [120.85, 30.67, 122.0, 31.88]}}}]
            if actions:
                scene = deepcopy(actions[0]['scene'])
            stages.append({'stage_id': f'ppt_{i:02d}', 'title': f'第{i:02d}页 · {text[:38] or "人口分布"}',
                           'kind': 'presentation', 'timing_mode': 'teacher', 'minutes': 0,
                           'content': text, 'material': f'原课件第{i}页；{manifest["renderer"]}静态导出。',
                           'script': ['展示板保留原页排版；动画、切换和手写请使用原生PowerPoint。'],
                           'questions': [], 'scene': scene, 'presentation': {'blocks': [block]},
                           'actions': actions})
    # This uses only the pure normalizer; __init__ would upgrade built-in lessons.
    normalizer = LessonService.__new__(LessonService)
    return normalizer._normalize_stages(stages)


def decorate_population(geojson):
    payload = deepcopy(geojson)
    colors = ['#fff7bc', '#fec44f', '#fe9929', '#ec7014', '#cc4c02', '#8c2d04']
    limits = [10000, 50000, 100000, 200000, 400000]
    for f in payload['features']:
        p = f['properties']
        index = sum(p['population'] > threshold for threshold in limits)
        p.update({'__fillColor': colors[index], '__fillOpacity': 0.72,
                  '__strokeColor': '#334155', '__strokeWidth': 0.6})
    return payload, [{'max': value, 'color': colors[i]} for i, value in enumerate(limits)] + [
        {'min_exclusive': limits[-1], 'color': colors[-1]}]


def assert_sources(package: Path, pptx: Path):
    manifest = json.loads((package/'render_manifest.json').read_text(encoding='utf-8'))
    receipt = json.loads((package/'prepared/population_receipt.json').read_text(encoding='utf-8'))
    geojson = json.loads((package/'prepared/shanghai_township_population_2020.geojson').read_text(encoding='utf-8'))
    if sha256(pptx) != manifest['source_sha256']:
        raise ValueError('Original PPTX changed since export')
    if len(geojson['features']) != receipt['units'] or sum(
            f['properties']['population'] for f in geojson['features']) != receipt['population']:
        raise ValueError('Population receipt mismatch')
    for i, slide in enumerate(manifest['slides'], 1):
        expected = package/f'slides/slide_{i:02d}.png'
        if (slide['number'] != i or slide['file'].replace('\\', '/') != f'slides/slide_{i:02d}.png'
                or sha256(expected) != slide['sha256']):
            raise ValueError(f'Preview hash/order mismatch: {i}')
    return manifest, receipt, geojson


def package_files(package, pptx, manifest):
    files = [pptx, package/'render_manifest.json', package/'boundary_source.json']
    files += [package/'prepared'/name for name in (
        'shanghai_township_population_2020.csv', 'shanghai_township_population_2020.geojson',
        'population_receipt.json')]
    files += [package/f'slides/slide_{i:02d}.png' for i in range(1, manifest['slide_count'] + 1)]
    # Hash every required file now, before even a dry run can succeed.
    json.loads((package/'boundary_source.json').read_text(encoding='utf-8'))
    return {path: sha256(path) for path in files}


def referenced_layer_files(state, snapshot):
    directory = state.parent/'layer_data'
    paths = set()
    for project in snapshot['projects'].values():
        for layer in project['layers']:
            name = layer.get('data', {}).get('features_file')
            if name:
                if not isinstance(name, str) or '/' in name or '\\' in name or ':' in name or name in ('.', '..'):
                    raise ValueError('Unsafe existing layer-data reference')
                path = directory/name
                if path.resolve().parent != directory.resolve() or not path.is_file():
                    raise ValueError('Missing or unsafe existing layer-data file')
                paths.add(path)
    return {path: sha256(path) for path in paths}


def backup_original(state, auth_db, backup, layer_hashes):
    """No service/store constructors: complete and verify recovery files first."""
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(state, backup/'runtime.json')
    for path in layer_hashes:
        destination = backup/'layer_data'/path.name
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(path, destination)
    with sqlite3.connect(auth_db.as_uri()+'?mode=ro', uri=True) as source:
        with sqlite3.connect(backup/'auth.db') as dest:
            source.backup(dest)
            if dest.execute('PRAGMA quick_check').fetchone() != ('ok',):
                raise RuntimeError('Auth backup failed integrity check')
            if list(source.iterdump()) != list(dest.iterdump()):
                raise RuntimeError('Auth backup differs from the original')
    hashes = {'runtime.json': sha256(state), 'auth.db': sha256(backup/'auth.db')}
    hashes.update({'layer_data/'+path.name: digest for path, digest in layer_hashes.items()})
    if any(sha256(backup/name) != digest for name, digest in hashes.items()):
        raise RuntimeError('Backup hash verification failed')
    (backup/'backup_manifest.json').write_text(json.dumps(
        {'complete': True, 'files': hashes}, indent=2), encoding='utf-8')


def write_snapshot(state, serialized):
    temporary = state.with_name(state.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8', newline='') as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(state)
    finally:
        temporary.unlink(missing_ok=True)


def migrate(data_root: Path, project_id: str, owner_email: str, package: Path, pptx: Path, apply: bool):
    data_root = data_root.resolve()
    for port in (18999, 18080):
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError(f'Stop the production server before offline migration (port {port})')
    state = data_root/'state/runtime.json'
    auth_db = data_root/'auth/auth.db'
    if not state.is_file() or not auth_db.is_file():
        raise ValueError('Existing state and auth are required; never bootstrap an instance')
    manifest, receipt, geojson = assert_sources(package, pptx)
    with sqlite3.connect(auth_db.as_uri()+'?mode=ro', uri=True) as db:
        user = db.execute('SELECT user_id,status FROM users WHERE email=?', (owner_email,)).fetchone()
    if not user or user[1] != 'active':
        raise ValueError('Owner account is missing or inactive')
    uid = user[0]
    state_hash = sha256(state)
    before = json.loads(state.read_text(encoding='utf-8'))
    if sha256(state) != state_hash:
        raise RuntimeError('State changed during preflight')
    project = before['projects'].get(project_id)
    if not project or project['owner_user_id'] != uid:
        raise ValueError('Project must belong to the requested owner')
    migration_id = 'demo_population_20261020_' + manifest['source_sha256'][:12]
    if any(l.get('metadata',{}).get('migration_id') == migration_id for l in before['lessons'].values()):
        raise ValueError('Migration already exists; refusing duplicate or overwrite')
    if any(l['layer_id'] == LAYER_ID for l in project['layers']):
        raise ValueError('Population layer already exists; refusing overwrite')
    target = data_root/'uploads'/project_id/migration_id
    if target.exists():
        raise ValueError('Migration output directory already exists')
    prefix = '/files/uploads/'+target.relative_to(data_root/'uploads').as_posix()
    # All stage/asset/record construction belongs to read-only preflight.
    stages = build_stages(pptx, manifest, prefix, [l['layer_id'] for l in project['layers']])
    sources = package_files(package, pptx, manifest)
    layer_hashes = referenced_layer_files(state, before)
    styles, classes = decorate_population(geojson)
    layer = LayerRecord.create(layer_id=LAYER_ID, name=LAYER_NAME,kind='vector',source='upload',
        geometry_type='MultiPolygon',visible=True,opacity=1.0,
        z_index=max([l.get('z_index', 0) for l in project['layers']],default=0)+20,
        data=styles,style={'labelField':'name'},metadata={
            'migration_id':migration_id,'source_year':'2020','source_name':receipt['source_file_name'],
            'source_sha256':receipt['source_sha256'],'source_sheet':'上海市','unit':'人',
            'population_field':'population','style_field':'population','feature_count':receipt['units'],
            'classification':classes,'workflow_style':{'legend':{'title':'2020街镇人口总量','items':[{'label':label,'color':item['color']} for label,item in zip(['≤10,000','10,001–50,000','50,001–100,000','100,001–200,000','200,001–400,000','>400,000'],classes)]}},'source_url':prefix+'/shanghai_township_population_2020.csv',
            'limitation':receipt['limitation'],'description':LAYER_NAME+'；'+receipt['limitation'],
            'license':'Private user-supplied statistics; third-party boundaries for non-commercial teaching reference'})
    lesson = LessonRecord.create(title=TITLE,source='imported',owner_user_id=uid,
        subject='地理',grade='高中',objectives=['运用资料，描述人口分布的特点及影响因素。'],
        stages=stages,
        metadata={'project_id':project_id,'migration_id':migration_id,'source_file_name':pptx.name,
                  'source_sha256':manifest['source_sha256'],'source_url':prefix+'/'+pptx.name,
                  'preview_renderer':manifest['renderer'],'slide_count':manifest['slide_count'],
                  'population_layer_id':LAYER_ID,'preview_limit':'静态原生导出；动画和转场请打开原始PPTX'})
    after = deepcopy(before)
    after['projects'][project_id]['layers'].append(asdict(layer))
    after['projects'][project_id]['updated_at'] = utc_now()
    after['lessons'][lesson.lesson_id] = asdict(lesson)
    # Preserve raw serialized records, including legacy layers and external refs.
    # RuntimeStore.__init__ intentionally performs unrelated startup migrations.
    serialized = json.dumps(after, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    report = {'migration_id': migration_id, 'owner_user_id': uid, 'project_id': project_id,
              'lesson_title': TITLE, 'slide_count': manifest['slide_count'],
              'population_units': receipt['units'], 'population_total': receipt['population'],
              'source_pptx_sha256': manifest['source_sha256'], 'source_xlsx_sha256': receipt['source_sha256'],
              'limitation': receipt['limitation'], 'state_before_sha256': state_hash}
    if not apply:
        print(json.dumps({'dry_run': True, **report}, ensure_ascii=False, indent=2))
        return report
    lease = StateWriterLease(state)
    try:
        lease.assert_owned()
        if sha256(state) != state_hash:
            raise RuntimeError('State changed during preflight')
        if any(sha256(path) != digest for path, digest in {**sources, **layer_hashes}.items()):
            raise RuntimeError('Source files changed during preflight')
        # Backup completion is a hard barrier before assets, grants or state writes.
        backup = data_root/'_backup'/f'{migration_id}_{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}'
        backup_original(state, auth_db, backup, layer_hashes)
        if sha256(backup/'runtime.json') != state_hash:
            raise RuntimeError('State backup differs from preflight')
        with sqlite3.connect(auth_db.as_uri()+'?mode=ro', uri=True) as db:
            pre_grants = db.execute('SELECT path,user_id,created_at FROM user_files ORDER BY path').fetchall()
        target.mkdir(parents=True, exist_ok=False)
        (target/'slides').mkdir()
        for i in range(1, manifest['slide_count'] + 1):
            name = f'slide_{i:02d}.png'
            shutil.copy2(package/'slides'/name, target/'slides'/name)
        shutil.copy2(pptx, target/pptx.name)
        for name in ('shanghai_township_population_2020.csv','shanghai_township_population_2020.geojson','population_receipt.json'):
            shutil.copy2(package/'prepared'/name, target/name)
        for name in ('render_manifest.json','boundary_source.json'):
            shutil.copy2(package/name, target/name)
        # Use the existing schema without AuthService's initialization side effects.
        with sqlite3.connect(auth_db) as db:
            db.execute('PRAGMA foreign_keys = ON')
            for path in target.rglob('*'):
                if path.is_file():
                    db.execute('INSERT INTO user_files(path,user_id,created_at) VALUES (?,?,?)',
                               (str(path.resolve()), uid, utc_now()))
        lease.assert_owned()
        if sha256(state) != state_hash:
            raise RuntimeError('State changed after backup')
        write_snapshot(state, serialized)
        actual = json.loads(state.read_text(encoding='utf-8'))
        if actual != after:
            raise RuntimeError('Saved state differs from the append-only snapshot')
        with sqlite3.connect(auth_db.as_uri()+'?mode=ro', uri=True) as db:
            post_grants = db.execute('SELECT path,user_id,created_at FROM user_files ORDER BY path').fetchall()
        if not all(item in post_grants for item in pre_grants):
            raise RuntimeError('Existing file grants changed')
        report.update({'lesson_id':lesson.lesson_id,'layer_id':LAYER_ID,'backup_directory':str(backup),
                       'asset_directory':str(target),'preserved_existing_records':True,
                       'preserved_existing_file_grants':True,'state_after_sha256':sha256(state),
                       'new_files':len([p for p in target.rglob('*') if p.is_file()])})
        (target/'migration_receipt.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return report
    finally:
        lease.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root',required=True,type=Path)
    p.add_argument('--project-id',required=True)
    p.add_argument('--owner-email',required=True)
    p.add_argument('--package',required=True,type=Path)
    p.add_argument('--pptx',required=True,type=Path)
    p.add_argument('--apply',action='store_true')
    args=p.parse_args()
    migrate(args.data_root,args.project_id,args.owner_email,args.package,args.pptx,args.apply)


if __name__=='__main__':
    main()

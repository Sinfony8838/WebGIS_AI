"""Prepare Shanghai 2020 township counts without inventing density or geometry.

Private inputs and outputs belong outside Git. Boundary aliases remain explicit,
and history-dependent boundaries are labelled as reference geometry.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

DISTRICTS = {
    '310101': '黄浦区', '310104': '徐汇区', '310105': '长宁区',
    '310106': '静安区', '310107': '普陀区', '310109': '虹口区',
    '310110': '杨浦区', '310112': '闵行区', '310113': '宝山区',
    '310114': '嘉定区', '310115': '浦东新区', '310116': '金山区',
    '310117': '松江区', '310118': '青浦区', '310120': '奉贤区',
    '310151': '崇明区',
}
FIELDS = ['population', 'age_0_14', 'age_15_59', 'age_60_plus',
          'age_65_plus', 'local_registered_residents']
ALIASES = {
    ('杨浦区', '长海路街道'): '五角场镇',
    ('嘉定区', '菊园新区'): '菊园新区管委会',
    ('奉贤区', '金海街道'): '金海社区',
    ('奉贤区', '海湾旅游区'): '上海市奉贤区海湾旅游区',
}
BOUNDARY_NOTE = '第三方历史边界仅作教学空间参照；人口为2020年表内总量，非密度；不用于面积或精确边界分析。'
CHANGE_NOTE = '2019年长海路街道与五角场街道发生范围调整；此处沿用旧边界，2020年精确边界待核验。'
BOUNDARY_URL = 'https://map.ruiduobao.com/downloadCityBatch/city/310100?format=geojson&year=2020&village=none'


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def counts(values, row_number):
    result = []
    for value in values:
        if value is None:
            result.append(None)
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or int(value) != value:
            raise ValueError(f'Invalid integer count at row {row_number}: {value!r}')
        else:
            result.append(int(value))
    total, young, working, old, older, local = result
    if None in (total, young, working, old, older) or total != young + working + old or older > old:
        raise ValueError(f'Invalid age reconciliation at row {row_number}')
    if local is not None and local > total:
        raise ValueError(f'Local registered count exceeds population at row {row_number}')
    return result


def parse_rows(rows):
    rows = list(rows)
    expected = ['总人口（人）', '0-14岁人口（人）', '15-59岁人口（人）',
                '60岁及以上人口（人）', '65岁及以上人口（人）',
                '居住本乡、镇、街道，户口在本乡、镇、街道人口（人）']
    if not rows or list(rows[0][1:7]) != expected or rows[1][0] != '上海市':
        raise ValueError('Unexpected Shanghai worksheet layout or units')
    city = counts(rows[1][1:7], 2)
    totals, records, seen = {}, [], set()
    district = ''
    for number, row in enumerate(rows[2:], 3):
        name = str(row[0] or '').strip()
        if not name:
            if any(v is not None for v in row[1:7]):
                raise ValueError(f'Unnamed statistical unit at row {number}')
            continue
        values = counts(row[1:7], number)
        if name in DISTRICTS.values():
            if name in totals:
                raise ValueError(f'Duplicate district: {name}')
            district = name
            totals[name] = values
            continue
        if not district or (district, name) in seen:
            raise ValueError(f'Missing district or duplicate statistical unit: {name}')
        seen.add((district, name))
        records.append({'district': district, 'name': name, 'source_row': number,
                        **dict(zip(FIELDS, values))})
    if set(totals) != set(DISTRICTS.values()):
        raise ValueError('All 16 Shanghai district totals are required')
    reconciliation = []
    for district, total in totals.items():
        subset = [r for r in records if r['district'] == district]
        for i, field in enumerate(FIELDS[:5]):
            if sum(r[field] for r in subset) != total[i]:
                raise ValueError(f'District reconciliation failed: {district}/{field}')
        reconciliation.append({'district': district, 'units': len(subset),
                               'population': total[0], 'difference': 0})
    for i, field in enumerate(FIELDS[:5]):
        if sum(r[field] for r in records) != city[i]:
            raise ValueError(f'City reconciliation failed: {field}')
    return {'city_population': city[0], 'records': records,
            'district_reconciliation': reconciliation}


def join_boundaries(table, boundaries, source_hash):
    from shapely import make_valid
    from shapely.geometry import shape, mapping
    from shapely.validation import explain_validity
    index, boundary_codes = {}, set()
    for f in boundaries.get('features', []):
        p = f.get('properties') or {}
        code = str(p.get('code') or '')
        district = DISTRICTS.get(code[:6])
        name = p.get('name')
        key = (district, name)
        if not district or len(code) != 12 or not code.isdigit() or not code.endswith('000'):
            raise ValueError(f'Invalid Shanghai township boundary code: {code}')
        if key in index or code in boundary_codes:
            raise ValueError(f'Duplicate boundary: {key}/{code}')
        boundary_codes.add(code)
        index[key] = f
    features, used, repairs, aliases = [], set(), [], []
    for record in table['records']:
        key = (record['district'], record['name'])
        boundary_name = ALIASES.get(key, key[1])
        matched = (key[0], boundary_name)
        if matched not in index or matched in used:
            raise ValueError(f'Missing or reused boundary: {matched}')
        used.add(matched)
        original = index[matched]
        geom = shape(original['geometry'])
        repair = ''
        if not geom.is_valid:
            repair = explain_validity(geom)
            fixed = make_valid(geom)
            # Preserve polygon topology, reject lossy or non-polygon repair.
            if fixed.geom_type == 'GeometryCollection':
                from shapely.ops import unary_union
                fixed = unary_union([g for g in fixed.geoms if g.geom_type in ('Polygon', 'MultiPolygon')])
            if fixed.geom_type not in ('Polygon', 'MultiPolygon') or not fixed.is_valid or fixed.is_empty:
                raise ValueError(f'Unusable repaired boundary: {key}')
            if abs(fixed.area - geom.area) > max(1e-12, geom.area * 1e-5):
                raise ValueError(f'Boundary repair changes area: {key}')
            repairs.append({'district': key[0], 'name': key[1], 'reason': repair})
            geom = fixed
        if geom.geom_type not in ('Polygon', 'MultiPolygon') or geom.is_empty:
            raise ValueError(f'Not a township polygon: {key}')
        minx, miny, maxx, maxy = geom.bounds
        if not (120 <= minx <= maxx <= 123 and 30 <= miny <= maxy <= 33):
            raise ValueError(f'Boundary outside Shanghai: {key}')
        if geom.geom_type == 'Polygon':
            from shapely.geometry import MultiPolygon
            geom = MultiPolygon([geom])
        note = BOUNDARY_NOTE
        if key in ALIASES:
            aliases.append({'district': key[0], 'population_name': key[1], 'boundary_name': boundary_name})
            note += f' 人口表名称“{key[1]}”对应边界名称“{boundary_name}”，仅作历史参照。'
        if key in {('杨浦区', '长海路街道'), ('杨浦区', '五角场街道')}:
            note += ' ' + CHANGE_NOTE
        properties = {**record, 'population_2020': record['population'],
                      'source_year': '2020', 'unit': '人', 'source_sheet': '上海市',
                      'source_sha256': source_hash, 'boundary_code': original['properties']['code'],
                      'boundary_name': boundary_name, 'boundary_source_url': BOUNDARY_URL,
                      'boundary_status': note, 'geometry_repair': repair}
        features.append({'type': 'Feature', 'properties': properties, 'geometry': mapping(geom)})
    return {'type': 'FeatureCollection', 'features': features}, {
        'units': len(features), 'population': sum(f['properties']['population'] for f in features),
        'aliases': aliases, 'geometry_repairs': repairs,
        'unused_boundaries': [{'district': k[0], 'name': k[1]} for k in index if k not in used],
        'district_reconciliation': table['district_reconciliation'],
        'limitation': BOUNDARY_NOTE + ' ' + CHANGE_NOTE,
    }


def prepare(xlsx: Path, boundaries: Path, output: Path):
    import openpyxl
    with xlsx.open('rb') as stream:
        workbook = openpyxl.load_workbook(stream, read_only=True, data_only=True)
        try:
            table = parse_rows(workbook['上海市'].values)
        finally:
            workbook.close()
    source_hash = sha256(xlsx)
    geojson, receipt = join_boundaries(table, json.loads(boundaries.read_text(encoding='utf-8')), source_hash)
    receipt.update({'source_file_name': xlsx.name, 'source_sha256': source_hash,
                    'boundary_sha256': sha256(boundaries), 'boundary_source_url': BOUNDARY_URL})
    output.mkdir(parents=True, exist_ok=False)
    (output/'shanghai_township_population_2020.geojson').write_text(json.dumps(geojson, ensure_ascii=False, separators=(',', ':'))+'\n', encoding='utf-8')
    (output/'population_receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    with (output/'shanghai_township_population_2020.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['district','name',*FIELDS,'source_row'])
        writer.writeheader();writer.writerows(table['records'])
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xlsx',required=True,type=Path)
    parser.add_argument('--boundaries',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    receipt=prepare(args.xlsx,args.boundaries,args.output)
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()

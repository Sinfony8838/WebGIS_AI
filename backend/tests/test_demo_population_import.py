from copy import deepcopy
import zipfile

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

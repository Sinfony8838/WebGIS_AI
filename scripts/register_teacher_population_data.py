"""Register the prepared WorldPop resources; render native regional windows.

Run after build_teacher_population_resources.py. Private rasters remain local.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from build_teacher_population_resources import ROOT, coloured
import rasterio
from rasterio.windows import from_bounds


def main(source):
    maps = ROOT/'backend/app/data/builtin/teaching_maps'
    path = maps/'registry.json'
    registry = json.loads(path.read_text(encoding='utf-8'))
    with rasterio.open(source) as src:
        for id, name, bbox, center, zoom in [
            ('shanghai_worldpop_teacher', '上海人口网格（2015估计）', [120.85,30.65,122.2,31.9], [121.47,31.23],9),
            ('northeast_population', '东北人口网格（2015估计）', [115,36,136,55], [126,45],6),
        ]:
            w=from_bounds(*bbox,src.transform).round_offsets().round_lengths()
            a=src.read(1,window=w).astype('float64');valid=np.isfinite(a)&(a>=0)
            transform=src.window_transform(w);dx,dy=transform.a,-transform.e
            lat=transform.f-(np.arange(a.shape[0])+.5)*dy
            area=6371.0088**2*np.deg2rad(dx)*(np.sin(np.deg2rad(lat+dy/2))-np.sin(np.deg2rad(lat-dy/2)))
            filename=id+'_teacher.png';coloured(a/area[:,None],valid).save(maps/filename)
            bounds=list(rasterio.windows.bounds(w,src.transform))
            item={'id':id,'name':name,'filename':filename,'bounds':bounds,'view':{'center':center,'zoom':zoom},'opacity':.7,
                  'category':'人口','category_order':1,'image_crs':'EPSG:4326','registration':'georeferenced_raster',
                  'source':'WorldPop Global R2025A UA v1','source_year':'2015','note':'约1公里模型估计；不等于2019东北教材图或2020上海街镇统计。',
                  'legend':legend()}
            registry['items']=[m for m in registry['items'] if m['id']!=id]+[item]
        registry['items']=[m for m in registry['items'] if m['id']!='worldpop_global_teacher']+[
            {'id':'worldpop_global_teacher','name':'世界人口密度网格（2015估计）','filename':'worldpop_global_teacher.png',
             'bounds':list(src.bounds),'view':{'center':[15,20],'zoom':2},'opacity':.75,'category':'人口','category_order':1,
             'image_crs':'EPSG:4326','registration':'georeferenced_raster','source':'WorldPop Global R2025A UA v1','source_year':'2015',
             'legend':legend(),'note':'显示为0.1°聚合网格；圈定统计仍用原始约1公里人数网格。透明处为无数据。'}]
    path.write_text(json.dumps(registry,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    path=ROOT/'backend/app/data/builtin/one_map/catalog.json'
    catalog=json.loads(path.read_text(encoding='utf-8'))
    catalog['items']=[m for m in catalog['items'] if m['id']!='finland_population_density_2015']+[
        {'id':'finland_population_density_2015','name':'芬兰人口密度教学网格（2015）','category':'population',
         'source':'builtin:one_map/population/finland_density_2015.geojson','format':'geojson',
         'fields':['name','population','area','density','year'],'coverage':'Finland','source_year':'2015',
         'source_name':'WorldPop Global R2025A UA v1，0.1°聚合；Natural Earth国家范围',
         'source_url':'https://data.worldpop.org/repo/prj/Global_2015_2030/R2025A/doc/Global2_Release_Statement_R2025A_v1.pdf',
         'license':'CC BY 4.0; Natural Earth public domain','includes_taiwan':False,'status':'ready','geometry_type':'Polygon',
         'recommended_template':'population_choropleth','population_fields':['name','population','area','density'],
         'tags':['population','Finland','2015'],'description':'人口像元人数求和后除以球面单元面积；海岸按中心点裁剪，仅作教学，不用于国家人口总量。'}]
    path.write_text(json.dumps(catalog,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')


def legend():
    return [{'label':label+' 人/km²','color':color} for label,color in zip(
        ['<1','1–10','10–50','50–100','100–200','200–500','500–1000','1000–5000','≥5000'],
        ['#fffcda','#fceda1','#fad277','#f1ae4e','#e1802d','#c04f1e','#912919','#5c181c','#36101c'])]


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);main(parser.parse_args().source)

"""Warp textbook map pixels using their printed graticule, not guessed bboxes.

Control points are pixels in the retained 1080px textbook images. The Arctic
Circle is an independent check; coast alignment still requires browser QA.
"""
import json
import os
import importlib.util
from pathlib import Path
import numpy as np
from PIL import Image
_proj = Path(importlib.util.find_spec('rasterio').origin).parent / 'proj_data'
if (_proj/'proj.db').exists():
    os.environ['PROJ_DATA']=str(_proj);os.environ['PROJ_LIB']=str(_proj)
import rasterio
from rasterio.control import GroundControlPoint
from rasterio.transform import from_bounds, GCPTransformer
from rasterio.warp import reproject, Resampling

ROOT=Path(__file__).resolve().parents[1]
MAPS=ROOT/'backend/app/data/builtin/teaching_maps'
FINLAND={
    'finland_population': {'file':'芬兰人口分布图.jpg', 'points':[(400,545,24,68),(400,1138,24,64),(400,1724,24,60),(739,535,30,68),(785,1115,30,64),(837,1704,30,60)],'check':(400,764,24,66.5635),'crop':[9,4,1071,1830],'legend':[903,4,1071,398]},
    'finland_climate': {'file':'芬兰降水气温图.jpg','points':[(397,347,24,68),(396,971,24,64),(396,1546,24,60),(716,333,30,68),(760,950,30,64),(810,1527,30,60)],'check':(397,572,24,66.5635),'crop':[14,8,1068,1580],'legend':[783,8,1068,480]},
    'finland_topography': {'file':'芬兰地形图.jpg','points':[(460,324,24,68),(460,867,24,64),(460,1400,24,60),(757,312,30,68),(795,849,30,64),(850,1384,30,60)],'check':(460,522,24,66.5635),'crop':[13,9,1068,1452],'legend':[13,9,228,558]}
}
CHINA={
 'china_jan_temperature': {'file':'中国1月平均气温分布图.jpg','points':[(766,357,116.407,39.904),(869,538,121.47,31.23),(742,560,114.31,30.59),(526,677,102.72,25.038),(727,713,113.264,23.129),(666,781,110.35,20.04),(331,238,87.616,43.826),(319,547,91.137,29.652),(829,70,122.54,52.97),(853,222,126.65,45.75),(548,444,103.834,36.061)],'check':(826,526,118.8,32.06),'crop':[51,40,1047,827],'legend':[51,573,229,827]},
 'china_precipitation': {'file':'中国年降水量分布图.jpg','points':[(879,536,121.47,31.23),(747,560,114.31,30.59),(519,674,102.72,25.038),(303,544,91.137,29.652),(330,251,87.616,43.826),(551,438,103.834,36.061),(925,195,126.65,45.75),(731,719,113.264,23.129),(896,673,121.51,25.04)],'check':(769,345,116.407,39.904),'crop':[15,21,1060,841],'legend':[15,572,211,841]},
 'china_topography': {'file':'中国地形图.jpg','points':[(649,129,110,50),(649,347,110,40),(650,570,110,30),(650,769,110,20),(505,121,100,50),(480,333,100,40),(457,544,100,30),(430,754,100,20),(800,119,120,50),(822,336,120,40),(855,544,120,30),(883,754,120,20)],'check':(756,343,116.407,39.904),'crop':[38,23,1034,812],'legend':[38,602,191,812]}
}


def warp(name, item):
    im=Image.open(MAPS/item['file']).convert('RGBA');a=np.array(im)
    legend_output=name+'_legend_teacher.png'
    im.crop(item['legend']).save(MAPS/legend_output)
    x0,y0,x1,y1=item['crop'];a[:y0,:,3]=0;a[y1:,:,3]=0;a[:,:x0,3]=0;a[:,x1:,3]=0
    lx,ly,rx,ry=item['legend'];a[ly:ry,lx:rx,3]=0
    points=[GroundControlPoint(row=y,col=x,x=lon,y=lat) for x,y,lon,lat in item['points']]
    china=name in CHINA
    height,width=(900,1600) if china else (1200,1500)
    result=np.zeros((4,height,width),dtype='uint8');bounds=[72,18,136,54] if china else [18,59,33,71]
    transform=from_bounds(*bounds,width,height)
    for band in range(4):
        reproject(a[:,:,band],result[band],gcps=points,src_crs='EPSG:4326',dst_transform=transform,
                  dst_crs='EPSG:4326',resampling=Resampling.nearest,SRC_METHOD='GCP_TPS',src_nodata=0,dst_nodata=0)
    output=name+'_teacher.png';Image.fromarray(result.transpose(1,2,0)).save(MAPS/output)
    x,y,lon,lat=item['check']
    with GCPTransformer(points, tps=True) as transformer:
        gotx,goty=transformer.xy(y,x,offset='ul')
    error=111.2*((goty-lat)**2+((gotx-lon)*np.cos(np.deg2rad(lat)))**2)**.5
    if error>(40 if china else 15):raise ValueError(f'{name}独立检查偏差{error:.1f}km，不能作为已配准资源。')
    return {'id':name,'filename':output,'legend_filename':legend_output,'bounds':bounds,'image_crs':'EPSG:4326','registration':'graticule_gcp',
            'source':'人教版高中地理必修第二册 教材图 张玥修订稿','source_year':'2015' if 'population' in name else '教材气候平均值（时期见原图）' if 'climate' in name or 'temperature' in name or 'precipitation' in name else '教材地形材料',
            'note':'按原图经纬网配准；仅作定性叠置，不读取图片颜色计算数值。地理边界受教材制图概括影响。',
            'control_points':item['points'],'check_error_km':round(float(error),3)}


if __name__=='__main__':
    registry_path=MAPS/'registry.json';registry=json.loads(registry_path.read_text(encoding='utf-8'));checks=[]
    for name,item in {**FINLAND,**CHINA}.items():
        patch=warp(name,item);target=next(m for m in registry['items'] if m['id']==name);target.update(patch);checks.append(patch)
    registry_path.write_text(json.dumps(registry,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    out=ROOT/'backend/data/outputs/teacher_map_registration.json';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps([{k:m[k] for k in ('id','check_error_km')} for m in checks]))

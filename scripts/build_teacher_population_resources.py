"""Prepare private teacher figures and native WorldPop count tiles.

Requires the existing geodata build environment (rasterio, numpy, Pillow,
python-docx). Source documents, rasters and generated assets are not committed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import sqlite3
import zlib
import os
import importlib.util
from pathlib import Path
import numpy as np
# Do not inherit an incompatible PostgreSQL/PostGIS PROJ database.
_proj = Path(importlib.util.find_spec('rasterio').origin).parent / 'proj_data'
if (_proj / 'proj.db').exists():
    os.environ['PROJ_DATA'] = str(_proj)
    os.environ['PROJ_LIB'] = str(_proj)
import rasterio
from rasterio.windows import Window, from_bounds
from PIL import Image
from docx import Document

ROOT = Path(__file__).resolve().parents[1]
SHA = "d26a413034dfdb0fdd1a5d8c1674cb8b35f7f0b4e0796a49b6c29e452727731a"
BREAKS = [1, 10, 50, 100, 200, 500, 1000, 5000]
COLORS = [(255,252,218),(252,237,161),(250,210,119),(241,174,78),(225,128,45),(192,79,30),(145,41,25),(92,24,28),(54,16,28)]


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(4<<20), b''):h.update(b)
    return h.hexdigest()


def figures(source, target):
    if digest(source)!=SHA: raise ValueError('修订稿校验值不匹配，请核对教学来源版本。')
    d=Document(source);items=[]
    for row_index,row in enumerate(d.tables[0].rows):
        seen=set(); n=0
        for cell in row.cells:
            if cell._tc in seen: continue
            seen.add(cell._tc)
            for blip in cell._tc.xpath('.//a:blip'):
                rid=blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                if not rid: continue
                part=d.part.related_parts[rid];n+=1
                filename=f'source_row_{row_index}_{n}.png'
                from io import BytesIO
                with Image.open(BytesIO(part.blob)) as im: im.convert('RGB').save(target/filename)
                items.append({'row':row_index,'order':n,'filename':filename,'source':'张玥 人口分布稿本设计 修订稿','sha256':digest(target/filename)})
    (target/'manifest.json').write_text(json.dumps({'source_sha256':SHA,'items':items},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Teacher figures',len(items),flush=True)


def coloured(density, valid):
    indices=np.searchsorted(np.array(BREAKS),np.nan_to_num(density),side='right')
    rgba=np.zeros((*density.shape,4),dtype='uint8');rgba[:,:,:3]=np.array(COLORS,dtype='uint8')[indices];rgba[:,:,3]=valid.astype('uint8')*255
    return Image.fromarray(rgba)


def count_tiles(source, package, map_dir):
    package.mkdir(parents=True,exist_ok=True)
    dbpath=package/'counts.sqlite'
    if dbpath.exists(): raise ValueError('已有统计包，请使用新的输出目录，避免覆盖历史资料。')
    total=0.; valid_pixels=0;tile_size=512
    with rasterio.open(source) as src, sqlite3.connect(dbpath) as db:
        if src.crs.to_epsg()!=4326 or src.transform.a<=0 or src.transform.e>=0:raise ValueError('仅接受北向上的WGS84人数网格。')
        dx,dy=abs(src.transform.a),abs(src.transform.e)
        db.execute('CREATE TABLE tiles(row INTEGER,col INTEGER,height INTEGER,width INTEGER,data BLOB,PRIMARY KEY(row,col))')
        for row in range(0,src.height,tile_size):
            for col in range(0,src.width,tile_size):
                a=src.read(1,window=Window(col,row,min(tile_size,src.width-col),min(tile_size,src.height-row))).astype('<f4')
                good=np.isfinite(a)&(a>=0)
                total+=float(a[good].sum(dtype='float64'));valid_pixels+=int(good.sum());a[~good]=np.nan
                if good.any():db.execute('INSERT INTO tiles VALUES(?,?,?,?,?)',(row,col,*a.shape,zlib.compress(a.tobytes(),6)))
            db.commit()
            print(f'Population tiles {row+min(tile_size,src.height-row)}/{src.height}',flush=True)
        header={'format':'worldpop-count-tiles-v1','package_id':'worldpop_global_2015','year':2015,'units':'persons_per_pixel',
                'bbox':list(src.bounds),'resolution_degrees':[dx,dy],'tile_size':tile_size,'width':src.width,'height':src.height,
                'total_population':total,'valid_pixels':valid_pixels,'source_sha256':digest(source),
                'source':{'name':'WorldPop Global 2015–2030 R2025A UA v1','file':source.name,'year':2015,'license':'CC BY 4.0',
                          'url':'https://data.worldpop.org/repo/prj/Global_2015_2030/R2025A/doc/Global2_Release_Statement_R2025A_v1.pdf'},
                'caveats':['模型估计人数，非逐人实测；alpha版本已锁定源文件校验值。','范围84°N至60°S，海洋及主要水体为无数据。']}
        (package/'package.json').write_text(json.dumps(header,ensure_ascii=False,indent=2),encoding='utf-8')
        # Display grid is aggregated; quantitative zone statistics above retain
        # the original 30-arc-second cells. The two resolutions are explicit.
        factor=12;display=np.zeros((src.height//factor,src.width//factor),dtype='float64');coverage=np.zeros(display.shape,dtype='bool')
        for row in range(0,src.height,120):
            a=src.read(1,window=Window(0,row,src.width,min(120,src.height-row))).astype('float64')
            good=np.isfinite(a)&(a>=0);a[~good]=0
            rows=a.shape[0]//factor
            display[row//factor:row//factor+rows]=a.reshape(rows,factor,src.width//factor,factor).sum(axis=(1,3))
            coverage[row//factor:row//factor+rows]=good.reshape(rows,factor,src.width//factor,factor).any(axis=(1,3))
        lat=src.bounds.top-(np.arange(display.shape[0])+.5)*dy*factor
        area=(6371.0088**2)*np.deg2rad(dx*factor)*(np.sin(np.deg2rad(lat+dy*factor/2))-np.sin(np.deg2rad(lat-dy*factor/2)))
        coloured(display/area[:,None],coverage).save(map_dir/'worldpop_global_teacher.png')
        # Finland teaching grid: aggregate raw counts into 0.1-degree cells.
        minx,miny,maxx,maxy=18.,59.,33.,71.
        window=from_bounds(minx,miny,maxx,maxy,src.transform).round_offsets().round_lengths()
        a=src.read(1,window=window).astype('float64');good=np.isfinite(a)&(a>=0);a[~good]=0
        hh,ww=a.shape[0]//factor,a.shape[1]//factor
        sums=a[:hh*factor,:ww*factor].reshape(hh,factor,ww,factor).sum(axis=(1,3))
        mask=good[:hh*factor,:ww*factor].reshape(hh,factor,ww,factor).any(axis=(1,3))
        lats=maxy-(np.arange(hh)+.5)*.1
        areas=(6371.0088**2)*np.deg2rad(.1)*(np.sin(np.deg2rad(lats+.05))-np.sin(np.deg2rad(lats-.05)))
        density=sums/areas[:,None]
        # Clip to the existing Finland geometry; coastal raster cells are
        # approximate and this display grid is not used as a national total.
        from shapely.geometry import shape,Point
        countries=json.loads((ROOT/'backend/app/data/builtin/one_map/boundaries/world_countries.geojson').read_text(encoding='utf-8'))
        fin=next(shape(f['geometry']) for f in countries['features'] if f['properties'].get('name_en')=='Finland' or f['properties'].get('name') in {'芬兰','Finland'})
        features=[]
        for r,c in zip(*np.where(mask)):
            x=minx+c*.1;y=maxy-r*.1
            if not fin.covers(Point(x+.05,y-.05)):mask[r,c]=False;continue
            features.append({'type':'Feature','geometry':{'type':'Polygon','coordinates':[[[x,y],[x+.1,y],[x+.1,y-.1],[x,y-.1],[x,y]]]},
                             'properties':{'name':f'芬兰教学网格 {r}-{c}','population':round(float(sums[r,c]),3),'area':round(float(areas[r]),6),'density':round(float(density[r,c]),3),'year':2015}})
        coloured(density,mask).save(map_dir/'finland_worldpop_teacher.png')
        out=ROOT/'backend/app/data/builtin/one_map/population/finland_density_2015.geojson'
        out.write_text(json.dumps({'type':'FeatureCollection','features':features},ensure_ascii=False),encoding='utf-8')
        print('World count total',total,'Finland display cells',len(features),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--source-docx',type=Path,required=True);p.add_argument('--worldpop',type=Path);p.add_argument('--maps-dir',type=Path);args=p.parse_args()
    target=ROOT/'backend/data/uploads/teacher_population_revised';target.mkdir(parents=True,exist_ok=True)
    figures(args.source_docx,target)
    maps=ROOT/'backend/app/data/builtin/teaching_maps'
    if args.maps_dir:
        for path in args.maps_dir.glob('*.jpg'):shutil.copy2(path,maps/path.name)
    if args.worldpop:count_tiles(args.worldpop,ROOT/'backend/data/population/worldpop_global_2015',maps)


if __name__=='__main__':main()

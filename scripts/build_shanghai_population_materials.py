"""Build classroom charts from the archived Shanghai official statistical tables.

Run from any cwd: python scripts/build_shanghai_population_materials.py
No coordinates, density estimates, migration estimates, or invented precision.
"""
from __future__ import annotations
import csv
import io
import json
from decimal import Decimal
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'backend/app/data/builtin/population/shanghai_subdistrict_population.json'
TARGET = ROOT / 'frontend/public/teaching-resources'


def build() -> None:
    data = json.loads(SOURCE.read_text(encoding='utf-8'))
    qp, yp = data['qingpu'], data['yangpu']
    assert [sum(row[col] for row in qp['rows']) for col in (1, 2)] == qp['total']
    # Yangpu publishes rounded values; preserve the official total independently.
    rounded_sum = sum(Decimal(str(row[1])) for row in yp['rows'])
    assert abs(rounded_sum - Decimal(str(yp['total'][0]))) <= Decimal('0.06')
    TARGET.mkdir(parents=True, exist_ok=True)
    for key, d in data.items():
        rows = d['rows']  # keep the order of the official source table
        comparison = key == 'qingpu'
        year = '2010 → 2020' if comparison else '2020'
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="850" viewBox="0 0 1200 850" role="img" aria-labelledby="title desc">',
                 f'<title id="title">{escape(d["title"])} {year}</title>',
                 '<desc id="desc">人口总量统计图，非人口密度。'+escape('；'.join(d['notes']))+'</desc>',
                 '<rect width="1200" height="850" rx="20" fill="#fff"/>',
                 '<g font-family="Microsoft YaHei, PingFang SC, sans-serif" fill="#17384b">']
        def text(x, y, value, size=20, color='#17384b', anchor='start', weight='400'):
            parts.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" text-anchor="{anchor}" font-weight="{weight}">{escape(str(value))}</text>')
        def line(x1,y1,x2,y2,color,width=1):
            parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"/>')
        text(38,51,d['title'],30,weight='600')
        text(38,88,f'{year} 年 · 常住人口总量 · 保留官方街镇顺序',20,'#526979')
        text(38,126,'观察任务：找出变化方向不同的街镇，再提出需要哪些资料来解释。' if comparison else '观察任务：人口总量较大，能否说明人口密度也较高？还缺什么数据？',20)
        left, right = 214, 726
        max_value = 220000 if comparison else 20
        def px(value): return round(left + float(value)/max_value*(right-left),2)
        for tick in ([0,50000,100000,150000,200000] if comparison else [0,5,10,15,20]):
            x=px(tick)
            line(x,207,x,700,'#e3eaf0')
            text(x,191,f'{tick/10000:g}' if comparison else str(tick),18,'#526979','middle')
        text(right,164,'万人',18,'#526979','end')
        if comparison:
            text(848,191,'2010 年（人）',18,anchor='end')
            text(996,191,'2020 年（人）',18,anchor='end')
            text(1157,191,'增减（人）',18,anchor='end')
            parts.append('<circle cx="839" cy="160" r="6" fill="white" stroke="#667e95" stroke-width="2"/><circle cx="986" cy="160" r="7" fill="#087f8c"/>')
        else:
            text(970,191,'常住人口（万人）',18,anchor='end')
        for i,row in enumerate(rows):
            y=230+i*40
            if i%2==0: parts.append(f'<rect x="30" y="{y-25}" width="1140" height="38" fill="#f5f8fa"/>')
            text(38,y,row[0],20)
            if comparison:
                a,b=row[1:]
                line(px(a),y-7,px(b),y-7,'#b8c9d4',5)
                parts.append(f'<circle cx="{px(a)}" cy="{y-7}" r="7" fill="white" stroke="#667e95" stroke-width="2"/><circle cx="{px(b)}" cy="{y-7}" r="7" fill="#087f8c"/>')
                text(848,y,f'{a:,}',20,anchor='end')
                text(996,y,f'{b:,}',20,anchor='end',weight='600')
                text(1157,y,f'{b-a:+,}',20,'#087f8c' if b>=a else '#a45538','end')
            else:
                value=row[1]
                parts.append(f'<rect x="{left}" y="{y-21}" width="{px(value)-left:.2f}" height="22" rx="4" fill="#258c9b"/>')
                text(970,y,f'{value:.2f}',20,anchor='end',weight='600')
        line(38,720,1162,720,'#d8e2e8')
        text(38,752,'统计口径：人口总量；缺少同期面积和边界，不计算街镇密度。',18)
        text(38,780,'两期人口变化不等于净迁移；2010 年对照值采用同一公报。' if comparison else f'原表总计 124.25 万人；街道加总 {rounded_sum} 万人，保留原表精度与总计。',18)
        text(38,810,'来源：'+d['source_name']+'；'+d['published_at'],16,'#526979')
        parts.append('</g></svg>')
        base=TARGET/f'shanghai_{key}_population'
        base.with_suffix('.svg').write_text('\n'.join(parts)+'\n',encoding='utf-8')
        stream=io.StringIO(newline='')
        writer=csv.writer(stream)
        writer.writerow(['地区',*[f'{year}年常住人口（{d["unit"]}）' for year in d['years']], '单位','来源','发布日期','备注'])
        for row in [['全区',*d['total']],*rows]:
            values=row if comparison else [row[0],f'{row[1]:.2f}']
            writer.writerow([*values,d['unit'],d['source_url'],d['published_at'],'；'.join(d['notes'])])
        base.with_suffix('.csv').write_text(stream.getvalue(),encoding='utf-8-sig',newline='')


if __name__ == '__main__':
    build()

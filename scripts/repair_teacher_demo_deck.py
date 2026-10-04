"""Repair the supplied legacy demo's overflowing text in a separate copy.

This does not run during uploads: native rendering must preserve other decks.
"""
from pathlib import Path
import argparse
from copy import deepcopy
from hashlib import sha256
from zipfile import ZipFile
from lxml import etree

NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main', 'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
def tag(prefix, name): return '{'+NS[prefix]+'}'+name
def text(sp): return ''.join(t.text or '' for t in sp.iter(tag('a','t')))
def position(sp, x, y, w, h):
    xfrm=sp.find('p:spPr/a:xfrm',NS)
    xfrm.find('a:off',NS).attrib.update({'x':str(round(x*12700)),'y':str(round(y*12700))})
    xfrm.find('a:ext',NS).attrib.update({'cx':str(round(w*12700)),'cy':str(round(h*12700))})
def paragraphs(sp, values, size):
    body=sp.find('p:txBody',NS); original=body.find('a:p',NS)
    run=next(original.iter(tag('a','r')), None)
    prop=deepcopy(run.find('a:rPr',NS)) if run is not None else etree.Element(tag('a','rPr'))
    prop.set('sz',str(size*100))
    # Original template uses white body text over a photographic master.
    # The repaired copy uses a clean light slide instead.
    for fill in prop.findall('a:solidFill',NS): prop.remove(fill)
    fill=etree.SubElement(prop,tag('a','solidFill'))
    etree.SubElement(fill,tag('a','srgbClr')).set('val','24465C')
    for p in body.findall('a:p',NS):body.remove(p)
    settings=body.find('a:bodyPr',NS);settings.set('wrap','square')
    for fit in list(settings): settings.remove(fit)
    for value in values:
        p=etree.SubElement(body,tag('a','p'));r=etree.SubElement(p,tag('a','r'));r.append(deepcopy(prop));etree.SubElement(r,tag('a','t')).text=value
def light_background(root):
    root.set('showMasterSp','0')
    common=root.find('p:cSld',NS)
    old_bg=common.find('p:bg',NS)
    if old_bg is not None: common.remove(old_bg)
    bg=etree.Element(tag('p','bg')); common.insert(0,bg)
    bgpr=etree.SubElement(bg,tag('p','bgPr'))
    fill=etree.SubElement(bgpr,tag('a','solidFill'))
    etree.SubElement(fill,tag('a','srgbClr')).set('val','F7FAFC')
    etree.SubElement(bgpr,tag('a','effectLst'))
def repair(source, output):
    if source.resolve()==output.resolve():raise ValueError('Use a separate output file.')
    before=sha256(source.read_bytes()).hexdigest()
    with ZipFile(source) as z:
        changes={}
        first=etree.fromstring(z.read('ppt/slides/slide1.xml'))
        shape=next(s for s in first.findall('.//p:sp',NS) if text(s).startswith('GeoBot WebGIS-AI'))
        runs=[t.text or '' for t in shape.iter(tag('a','t'))]
        paragraphs(shape,[runs[0],runs[1]+runs[2],runs[3],runs[4]+'    '+runs[5]],22)
        position(shape,82,106,560,148)
        for empty in first.findall('.//p:sp',NS):
            if empty.find('p:nvSpPr/p:cNvPr',NS).get('id')=='12' and not text(empty):empty.getparent().remove(empty)
        changes['ppt/slides/slide1.xml']=etree.tostring(first,xml_declaration=True,encoding='UTF-8',standalone=True)
        # The supplied deck overwrote narrow master title placeholders with
        # long headings. Empty screenshot frames also obscure overflowing text.
        # Keep every text shape's content in a readable light-page layout.
        for number in (4,5,6,8,9,11,12,13,14):
            root=etree.fromstring(z.read(f'ppt/slides/slide{number}.xml'))
            light_background(root)
            shapes=root.findall('.//p:sp',NS)
            nonempty=[s for s in shapes if text(s).strip()]
            heading,body=nonempty[:2]
            values=[text(s) for s in nonempty[1:]]
            paragraphs(heading,[text(heading)],24);position(heading,38,22,640,62)
            paragraphs(body,values,18);position(body,38,104,640,273)
            for sp in shapes:
                if sp not in (heading,body):sp.getparent().remove(sp)
            for pic in root.findall('.//p:pic',NS):pic.getparent().remove(pic)
            changes[f'ppt/slides/slide{number}.xml']=etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
        for number in (16,17,18):
            root=etree.fromstring(z.read(f'ppt/slides/slide{number}.xml'))
            light_background(root)
            shapes=root.findall('.//p:sp',NS)
            if number==16:
                for pic in root.findall('.//p:pic',NS):pic.getparent().remove(pic)
                heading=next(s for s in shapes if text(s).startswith('04 '))
                body=next(s for s in shapes if text(s).startswith('5-6'))
                paragraphs(heading,[text(heading)],30);position(heading,55,95,610,70)
                paragraphs(body,[text(body)],22);position(body,55,190,610,90)
            else:
                heading=next(s for s in shapes if s.find('p:nvSpPr/p:cNvPr',NS).get('id')=='2')
                paragraphs(heading,[text(heading)],24);position(heading,38,23,640,46)
                intro=next(s for s in shapes if s.find('p:nvSpPr/p:cNvPr',NS).get('id')=='25')
                paragraphs(intro,[t.text for t in intro.iter(tag('a','t')) if t.text],20);position(intro,55,94,610,105)
                body=next(s for s in shapes if s.find('p:nvSpPr/p:cNvPr',NS).get('id')==('3' if number==17 else '5'))
                paragraphs(body,[t.text for t in body.iter(tag('a','t')) if t.text],20);position(body,55,205,610,160)
                for sp in shapes:
                    if sp not in (heading,intro,body):sp.getparent().remove(sp)
            changes[f'ppt/slides/slide{number}.xml']=etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
        output.parent.mkdir(parents=True,exist_ok=True)
        with ZipFile(output,'w') as target:
            for item in z.infolist():target.writestr(item,changes.get(item.filename,z.read(item)))
    assert sha256(source.read_bytes()).hexdigest()==before
    print(f'Preserved source {before}; repaired {len(changes)} slides in {output.name}')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('output',type=Path);a=p.parse_args();repair(a.source,a.output)

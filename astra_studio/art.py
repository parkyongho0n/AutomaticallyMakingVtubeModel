from __future__ import annotations
import hashlib,json
from pathlib import Path
from PIL import Image
import numpy as np
from psd_tools import PSDImage
from psd_tools.api.layers import PixelLayer
from .models import Project
from .storage import within, atomic_json

def placed(layer,root,canvas):
    out=Image.new('RGBA',canvas)
    if layer.image:
        im=Image.open(within(root,layer.image)).convert('RGBA')
        x,y,w,h=(round(v) for v in layer.rect)
        out.alpha_composite(im.resize((max(1,w),max(1,h)),Image.Resampling.LANCZOS),(x,y))
    return out

def composite(p:Project,root:Path):
    canvas=Image.new('RGBA',p.canvas);masks={}
    for layer in p.layers:
        im=placed(layer,root,p.canvas)
        if layer.clip_to and layer.clip_to in masks:
            a=np.array(im.getchannel('A'),dtype=np.uint16)*np.array(masks[layer.clip_to],dtype=np.uint16)//255
            im.putalpha(Image.fromarray(a.astype('uint8')))
        masks[layer.id]=im.getchannel('A')
        if layer.visible:canvas=Image.alpha_composite(canvas,im)
    return canvas

def assemble(p:Project,root:Path,dest:Path):
    dest.mkdir(parents=True,exist_ok=True)
    active=[l for l in p.layers if l.image]
    if not active:raise ValueError('이미지가 있는 파츠를 먼저 추가하세요.')
    neutral=composite(p,root);neutral.save(dest/'neutral.png')
    for alias,name in [(False,'layers.psd'),(True,'model.psd')]:
        psd=PSDImage.new('RGBA',p.canvas)
        for layer in p.layers:
            if not layer.image or (alias and not layer.rig_include):continue
            im=placed(layer,root,p.canvas)
            # Bake arbitrary clip relationships into pixels for portable PSDs.
            # The native runtime gets full iris surfaces for the exporter to rig.
            if layer.clip_to and not alias:
                mask=placed(next(l for l in p.layers if l.id==layer.clip_to),root,p.canvas).getchannel('A')
                a=np.array(im.getchannel('A'),dtype=np.uint16)*np.array(mask,dtype=np.uint16)//255
                im.putalpha(Image.fromarray(a.astype('uint8')))
            box=im.getbbox()
            if not box:continue
            pix=PixelLayer.frompil(im.crop(box),psd,name=layer.alias if alias else layer.name,top=box[1],left=box[0])
            pix.visible=True if alias else layer.visible
        psd.save(dest/name)
    restored=PSDImage.open(dest/'layers.psd').composite().convert('RGBA')
    a=np.asarray(neutral,dtype=float);b=np.asarray(restored,dtype=float)
    mae=float(np.abs(a[:,:,:3]*a[:,:,3:]/255-b[:,:,:3]*b[:,:,3:]/255).mean())
    if mae>3:raise ValueError(f'PSD 재조립 오차가 큽니다: {mae:.3f}')
    atomic_json(dest/'report.json',{'part_count':len(active),'empty_slots':[l.name for l in p.layers if not l.image],
                'psd_visible_mae':mae,'input_reference_sha256':hashlib.sha256(within(root,p.reference).read_bytes()).hexdigest() if p.reference else None,
                'note':'클리핑은 편집용 PSD 픽셀에 적용됩니다. 원본 전체 파츠는 프로젝트 assets에 보관합니다. 런타임용 PSD에는 전체 눈 표면을 전달합니다.'})
    return {'parts':len(active),'psd_mae':mae}

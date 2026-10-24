from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
import re

ID = r'^[a-zA-Z0-9_-]{1,80}$'

class Layer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=ID)
    name: str = Field(min_length=1, max_length=120)
    alias: str = Field(min_length=1, max_length=120)
    image: str | None = None
    rect: tuple[float, float, float, float]
    visible: bool = True
    rig_include: bool = True
    clip_to: str | None = None
    attachment: str = ''
    @model_validator(mode='after')
    def valid_rect(self):
        import math
        x,y,w,h=self.rect
        if not all(math.isfinite(v) for v in self.rect) or not (1<=w<=8192 and 1<=h<=8192 and w*h<=16777216 and abs(x)<=8192 and abs(y)<=8192):
            raise ValueError('파츠 위치 또는 크기가 허용 범위를 벗어났습니다.')
        if self.image and not re.fullmatch(r'assets/[a-zA-Z0-9_-]+\.png', self.image):
            raise ValueError('프로젝트 내부 PNG 자산만 사용할 수 있습니다.')
        return self

class Rig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    profile: Literal['standard','astra'] = 'standard'
    mesh_spacing: int = Field(default=16, ge=8, le=64)
    head_strength: float = Field(default=.45, ge=0, le=1)
    body_strength: float = Field(default=.25, ge=0, le=1)

class Project(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal[1] = 1
    id: str = Field(pattern=ID)
    name: str = Field(min_length=1, max_length=100)
    revision: int = Field(default=0, ge=0)
    canvas: tuple[int,int] = (1254,1254)
    reference: str | None = None
    layers: list[Layer] = Field(default_factory=list, max_length=200)
    rig: Rig = Field(default_factory=Rig)
    notes: str = Field(default='', max_length=5000)
    @model_validator(mode='after')
    def valid_project(self):
        if not all(256<=v<=4096 for v in self.canvas): raise ValueError('캔버스는 256~4096px 범위여야 합니다.')
        ids=[l.id for l in self.layers]
        if len(ids)!=len(set(ids)): raise ValueError('파츠 ID가 중복되었습니다.')
        if self.reference and not re.fullmatch(r'assets/[a-zA-Z0-9_-]+\.png',self.reference): raise ValueError('잘못된 기준 이미지 경로')
        for i,l in enumerate(self.layers):
            if l.clip_to and any(b.id==l.clip_to and b.clip_to for b in self.layers): raise ValueError('중첩 클리핑은 지원하지 않습니다.')
            if l.clip_to and l.clip_to not in ids[:i]: raise ValueError('클리핑 대상은 아래쪽에 있는 기존 파츠여야 합니다.')
        return self

# Normalized starting layout, explicitly editable; not claimed to be image analysis.
def template_layers(canvas: tuple[int,int]):
    specs=[
        ('HAIR_Back','hair back support',(.17,.18,.66,.82)),
        ('BODY_Upper','topwear blouse',(.32,.52,.36,.43)),
        ('NECK','neck',(.43,.45,.14,.15)),
        ('FACE_Base','face',(.38,.24,.24,.28)),
        ('EYE_R_White','eye white R',(.407,.39,.075,.035)),
        ('EYE_R_Iris','iris R',(.426,.39,.036,.036)),
        ('EYE_L_White','eye white L',(.518,.39,.075,.035)),
        ('EYE_L_Iris','iris L',(.537,.39,.036,.036)),
        ('MOUTH_Line','mouth close',(.483,.468,.034,.009)),
        ('MOUTH_Inside','mouth open',(.48,.465,.04,.028)),
        ('HAIR_Front','hair front center',(.35,.18,.30,.40)),
        ('BROW_R','brow R',(.407,.36,.075,.012)),
        ('BROW_L','brow L',(.518,.36,.075,.012)),
        ('EYE_R_UpperLid','eyelash upper R',(.402,.383,.085,.015)),
        ('EYE_L_UpperLid','eyelash upper L',(.513,.383,.085,.015)),
    ]
    result=[]
    for name,alias,(x,y,w,h) in specs:
        result.append(Layer(id=name,name=name,alias=alias,rect=(x*canvas[0],y*canvas[1],w*canvas[0],h*canvas[1]),
                            clip_to=name.replace('Iris','White') if name.endswith('Iris') else None,
                            visible=name!='MOUTH_Inside'))
    return result

from fastapi import HTTPException
from sqlalchemy import select
from src.models import Dataset
from src.services.business import metadata
from src.utils.serialization import checksum
import math, time
def validate_records(records):
    # 手工接入与远端同步共用的整份校验；抛出 ValueError 由调用方翻译为各自失败态
    if not (5<=len(records)<=5000): raise ValueError('记录条数须在 5–5,000 之间')
    for index,row in enumerate(records):
        for c in metadata()['columns']:
            value=row.get(c['key'])
            if value is None or value=='': raise ValueError(f'第 {index+1} 行缺少字段 {c["label"]}')
            if c['type']=='number':
                try:
                    if isinstance(value,bool) or not math.isfinite(float(value)): raise ValueError()
                    row[c['key']]=float(value)
                except (TypeError, ValueError, OverflowError): raise ValueError(f'第 {index+1} 行 {c["label"]} 必须为有限数值')
def create(db, data):
    name=data.name.strip()
    if len(name)<2: raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
    if db.scalar(select(Dataset).where(Dataset.name==name)):
        raise HTTPException(409, '该数据批次名已存在，请修改名称')
    try:
        validate_records(data.records)
    except ValueError as e:
        raise HTTPException(422, str(e))
    d=Dataset(name=name, source=data.source, records=data.records, checksum=checksum(data.records), created_at=time.time())
    db.add(d); db.flush()
    return d

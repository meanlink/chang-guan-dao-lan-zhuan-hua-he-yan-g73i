from pydantic import BaseModel, Field, field_validator
class SourceInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    base_url: str = Field(min_length=8, max_length=300)
    token: str = Field(default='', max_length=300)
    page_size: int = Field(default=100, ge=1, le=500)
    @field_validator('base_url')
    @classmethod
    def normalize(cls, v):
        v = v.strip().rstrip('/')
        if not v.startswith(('http://', 'https://')):
            raise ValueError('服务地址须以 http:// 或 https:// 开头')
        return v

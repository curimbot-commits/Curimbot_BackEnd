
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

# =========================================================
# Type Breakdown
# =========================================================
class TypeBreakdown(BaseModel):
    """Desglose por tipo de archivo"""
    file_type: str = Field(..., description="Tipo de archivo (pdf, txt, docx)")
    count: int = Field(..., description="Número de documentos de este tipo")
    size: int = Field(..., description="Tamaño total en bytes")
    
    class Config:
        from_attributes = True

# =========================================================
# Esquemas para Funcionalidades de Dashboard
# =========================================================
class DashboardStats(BaseModel):
    """Estadísticas completas del dashboard"""
    totalDocuments: int = Field(..., description="Total de documentos")
    totalSize: int = Field(..., description="Tamaño total en bytes")
    documentsToday: int = Field(..., description="Documentos subidos hoy")
    documentsThisWeek: int = Field(..., description="Documentos subidos esta semana")
    documentsThisMonth: int = Field(..., description="Documentos subidos este mes")
    averagePerDay: float = Field(..., description="Promedio de documentos por día")
    mostActiveUser: Optional[str] = Field(None, description="Usuario más activo")
    peakUploadTime: Optional[str] = Field(None, description="Período con más subidas")
    typeBreakdown: List[TypeBreakdown] = Field(
        default_factory=list,
        description="Desglose de documentos por tipo"
    )  
    
    class Config:
        from_attributes = True

class ChartDataPoint(BaseModel):
    """Punto de datos para gráficos"""
    period: str = Field(..., alias="label", description="Período (fecha o etiqueta)")
    pdf: int = Field(0, description="Cantidad de PDFs")
    docx: int = Field(0, description="Cantidad de DOCX")
    txt: int = Field(0, description="Cantidad de TXT")
    total: int = Field(..., alias="value", description="Total de documentos")
    
    class Config:
        from_attributes = True
        populate_by_name = True
        
    @property
    def label(self) -> str:
        """Alias para compatibilidad con frontend"""
        return self.period
    
    @property
    def value(self) -> int:
        """Alias para compatibilidad con frontend"""
        return self.total


class UserStorageStats(BaseModel):
    """Estadísticas de almacenamiento por usuario"""
    user_id: int
    total_documents: int = Field(..., description="Total de documentos del usuario")
    total_size: int = Field(..., description="Tamaño total en bytes")
    type_breakdown: List[Dict[str, Any]] = Field(..., description="Desglose por tipo de archivo")
    
    class Config:
        from_attributes = True

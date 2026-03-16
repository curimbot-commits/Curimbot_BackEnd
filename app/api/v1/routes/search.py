import datetime
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional, Annotated

from app.schemas.document_schemas import SearchResult
from app.schemas.log_schemas import LogCreate
from ....models import models
from ....db.database import SessionLocal
from ....schemas import schemas
from ....db import crud
from ....services import storage, nlp
from ....services.utils import extract_text
from ....services.auth_service import get_current_user

router = APIRouter(prefix="/search", tags=["search"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/search", response_model=List[SearchResult])
def search_documents(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    query: Annotated[Optional[str], Query(description="Texto a buscar.")] = None,
    category: Annotated[Optional[str], Query()] = None,
    file_type: Annotated[Optional[str], Query(description="Filtrar por tipo de archivo: pdf, docx, txt")] = None,
    date_from: Annotated[Optional[datetime.datetime], Query(description="Fecha desde (ISO)")] = None, 
    date_to: Annotated[Optional[datetime.datetime], Query(description="Fecha hasta (ISO)")] = None, 
    sort_by: Annotated[Optional[str], Query(enum=["relevance", "date", "size"])] = "relevance",
    semantic: Annotated[Optional[bool], Query(description="Usar búsqueda semántica")] = True,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(le=100)] = 20
):
    """
    Búsqueda avanzada en documentos con NLP, filtros y ordenamiento.
    """
    # Validación mínima
    if not query and not category:
        raise HTTPException(status_code=400, detail="Debes especificar una búsqueda o una categoría.")

    # Escoger tipo de búsqueda
    if semantic and query:
        documents = crud.search_documents_semantic(
            db=db,
            user_id=user.id,
            query=query,
            category=category,
            file_type=file_type,
            date_from=date_from,
            date_to=date_to,
            sort_by=sort_by,
            skip=skip,
            limit=limit
        )
    else:
        documents = crud.search_documents(
            db=db,
            user_id=user.id,
            query=query,
            category=category,
            file_type=file_type,
            date_from=date_from,
            date_to=date_to,
            sort_by=sort_by,
            skip=skip,
            limit=limit
        )

    # Resaltado de coincidencias en los snippets
    if query:
        for doc in documents:
            doc.match_snippet = nlp.highlight_text_snippet(doc.text, query)

    # Guardar en historial
    log_data = LogCreate(
        user_id=user.id,
        action="search",
        detail=f"Búsqueda: '{query}' | Resultados: {len(documents)}"
    )
    crud.create_log(db=db, log_data=log_data)
    db.commit()

    return documents



"""Cabeceras de descarga con nombres de archivo problemáticos."""

from urllib.parse import unquote

import pytest

from app.api.v1.routes.documents_endpoints.download import content_disposition
from tests.test_documents_access import _as, _make_doc


@pytest.mark.parametrize("name", [
    "Reporte Q4 2025.pdf",
    "año_niño.pdf",
    "报告.pdf",
    'evil"; filename="x.exe',
    "a\r\nSet-Cookie: x=1.pdf",
])
def test_content_disposition_is_safe(name):
    header = content_disposition(name)
    header.encode("latin-1")  # no debe fallar al enviarse
    assert "\r" not in header and "\n" not in header
    fallback = header.split('filename="', 1)[1].split('"', 1)[0]
    assert '"' not in fallback and ";" not in fallback
    assert unquote(header.split("filename*=UTF-8''", 1)[1]) == name


def test_download_unicode_filename(client, make_user, db):
    owner = make_user()
    doc = _make_doc(db, owner, is_public=0)
    doc.filename = "报告 año.txt"
    db.commit()
    r = _as(client, owner).get(f"/documents/download/{doc.id}")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "filename*=UTF-8''" in r.headers["content-disposition"]

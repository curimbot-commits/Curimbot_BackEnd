"""Tests de humo del control de acceso a documentos."""

from app.enums.enums import FileType
from app.models.document_models import Document
from app.services import storage_service
from tests.conftest import login


def _make_doc(db, owner, is_public: int) -> Document:
    content = b"contenido de prueba"
    doc = Document(
        filename="prueba.txt",
        mimetype="text/plain",
        size=len(content),
        file_type=FileType.txt,
        text=content.decode(),
        blob_enc=storage_service.encrypt_bytes(content),
        is_public=is_public,
        uploaded_by=owner.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def _as(client, user):
    client.cookies.clear()
    assert login(client, user.email).status_code == 200
    return client


def test_owner_can_download_own_doc(client, make_user, db):
    owner = make_user()
    doc = _make_doc(db, owner, is_public=0)
    r = _as(client, owner).get(f"/documents/download/{doc.id}")
    assert r.status_code == 200
    assert r.content == b"contenido de prueba"


def test_user_cannot_download_other_users_private_doc(client, make_user, db):
    owner, other = make_user(), make_user()
    doc = _make_doc(db, owner, is_public=0)
    r = _as(client, other).get(f"/documents/download/{doc.id}")
    assert r.status_code == 403


def test_user_can_download_admin_public_doc(client, make_user, db):
    admin, user = make_user("admin"), make_user()
    doc = _make_doc(db, admin, is_public=1)
    r = _as(client, user).get(f"/documents/download/{doc.id}")
    assert r.status_code == 200, r.text


def test_user_can_read_metadata_of_admin_public_doc(client, make_user, db):
    admin, user = make_user("admin"), make_user()
    doc = _make_doc(db, admin, is_public=1)
    r = _as(client, user).get(f"/documents/{doc.id}/metadata")
    assert r.status_code == 200, r.text


def test_user_cannot_delete_admin_public_doc(client, make_user, db):
    admin, user = make_user("admin"), make_user()
    doc = _make_doc(db, admin, is_public=1)
    r = _as(client, user).delete(f"/documents/{doc.id}")
    assert r.status_code == 403

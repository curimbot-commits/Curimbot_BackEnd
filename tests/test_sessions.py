"""Sesión 'actual' = la de la petición; rutas legacy peligrosas eliminadas."""


from tests.conftest import login


def _bearer(r):
    return {"Authorization": f"Bearer {r.cookies['access_token']}"}


def test_current_session_is_the_requesting_one(client, make_user):
    user = make_user()
    first = login(client, user.email)
    client.cookies.clear()
    second = login(client, user.email)  # la última creada (is_current en BD)
    client.cookies.clear()

    sessions = client.get("/auth/sessions/active", headers=_bearer(first)).json()
    current = [s for s in sessions if s["is_current"]]
    assert len(sessions) == 2 and len(current) == 1

    # "Cerrar las demás" desde el primer dispositivo conserva el primero
    r = client.post("/auth/sessions/revoke-others", json={"except_current": True}, headers=_bearer(first))
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 1
    assert client.get("/auth/me", headers=_bearer(first)).status_code == 200
    assert client.get("/auth/me", headers=_bearer(second)).status_code == 401


def test_legacy_delete_cannot_delete_users(client, make_user):
    admin = make_user("admin")
    victim = make_user()
    r = login(client, admin.email)
    client.cookies.clear()
    resp = client.delete(f"/auth/{victim.id}", headers=_bearer(r))
    assert resp.status_code in (404, 405)
    client.cookies.clear()
    assert login(client, victim.email).status_code == 200


def test_revoke_single_session(client, make_user):
    user = make_user()
    first = login(client, user.email)
    client.cookies.clear()
    second = login(client, user.email)
    client.cookies.clear()

    sessions = client.get("/auth/sessions/active", headers=_bearer(first)).json()
    other = next(s for s in sessions if not s["is_current"])
    r = client.delete(f"/auth/sessions/{other['id']}", headers=_bearer(first))
    assert r.status_code == 200, r.text
    assert client.get("/auth/me", headers=_bearer(second)).status_code == 401
    assert client.get("/auth/me", headers=_bearer(first)).status_code == 200

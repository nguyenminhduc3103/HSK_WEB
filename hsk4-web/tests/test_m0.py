def test_index(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Luyện đề của bạn" in r.text
    assert "HSK 4" in r.text


def test_admin_requires_password(client):
    r = client.get("/admin")
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers

    r = client.get("/admin", auth=("x", "wrong"))
    assert r.status_code == 401

    r = client.get("/admin", auth=("x", "secret"))
    assert r.status_code == 200

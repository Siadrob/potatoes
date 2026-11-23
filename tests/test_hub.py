import sqlite3

import pytest

import media
from app import create_app
from conftest import ME, login
from db import get_db

YT = {"items": [
    {"id": {"videoId": "abc123"}, "snippet": {"title": "Leroy combo guide &amp; tips", "channelTitle": "RyzingSol",
     "publishedAt": "2026-07-10T12:00:00Z", "thumbnails": {"medium": {"url": "https://i.ytimg.com/vi/abc123/mq.jpg"}}}},
    {"id": {"channelId": "pas une vidéo"}, "snippet": {}},
]}
STREAMS = {"data": [
    {"user_name": "BigEN", "user_login": "bigen", "title": "Ranked grind", "viewer_count": 5000, "language": "en",
     "thumbnail_url": "https://x/{width}x{height}.jpg"},
    {"user_name": "PetitFR", "user_login": "petitfr", "title": "On monte en GoD", "viewer_count": 40, "language": "fr",
     "thumbnail_url": "https://x/{width}x{height}.jpg"},
    {"user_name": "LeroyMain", "user_login": "leroymain", "title": "LEROY only !", "viewer_count": 12, "language": "es",
     "thumbnail_url": "https://x/{width}x{height}.jpg"},
]}


class FakeGet:
    def __init__(self):
        self.calls = []
        self.fail = False

    def __call__(self, url, headers=None, data=None, timeout=20):
        self.calls.append(url.split("?")[0])
        if self.fail:
            raise media.MediaError("erreur 403 : quota dépassé")
        if "googleapis" in url:
            assert "Leroy" in url
            return YT
        if "oauth2/token" in url:
            return {"access_token": "tok", "expires_in": 3600}
        assert headers["Authorization"] == "Bearer tok"
        if "helix/games" in url:
            return {"data": [{"id": "538054672", "name": "TEKKEN 8"}]}
        return STREAMS


@pytest.fixture
def fake():
    return FakeGet()


def make(tmp_path, fake, **cfg):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db"), "MEDIA_GET": fake, **cfg})
    with app.app_context():
        get_db().execute("INSERT INTO matches (player_id, played_at, my_char, opp_char, result) "
                         "VALUES (?, '2026-11-20 10:00', 'Leroy', 'King', 'W')", (ME,))
        get_db().commit()
    return app, login(app, app.test_client())


def test_youtube_parsing(fake):
    videos = media.youtube_videos("k", "Leroy", get=fake)
    assert videos == [{"id": "abc123", "title": "Leroy combo guide & tips", "channel": "RyzingSol",
                       "date": "2026-07-10", "thumb": "https://i.ytimg.com/vi/abc123/mq.jpg",
                       "url": "https://www.youtube.com/watch?v=abc123"}]


def test_stream_ranking(fake):
    tw = media.Twitch("id", "secret", get=fake)
    ranked = media.rank_streams(tw.streams(), "Leroy", "fr")
    # Le perso d'abord, puis la langue choisie, puis les plus regardés.
    assert [s["user"] for s in ranked] == ["LeroyMain", "PetitFR", "BigEN"]
    assert ranked[0]["mentions_char"] and ranked[0]["thumb"] == "https://x/320x180.jpg"
    tw.streams()
    assert fake.calls.count("https://id.twitch.tv/oauth2/token") == 1     # jeton réutilisé
    assert fake.calls.count("https://api.twitch.tv/helix/games") == 1     # id du jeu réutilisé


def test_cache_and_fallback(tmp_path, fake):
    from datetime import timedelta
    conn = sqlite3.connect(tmp_path / "c.db")
    calls = []
    fetch = lambda: calls.append(1) or ["v1"]
    assert media.cached(conn, "k", timedelta(hours=1), fetch) == ["v1"]
    assert media.cached(conn, "k", timedelta(hours=1), fetch) == ["v1"] and len(calls) == 1
    def failing():
        raise media.MediaError("quota")
    assert media.cached(conn, "k", timedelta(0), failing) == ["v1"]          # erreur : ancienne valeur
    with pytest.raises(media.MediaError):
        media.cached(conn, "autre", timedelta(0), failing)


def test_home_without_keys(tmp_path, fake):
    app, client = make(tmp_path, fake)
    html = client.get("/").get_data(as_text=True)
    assert "YOUTUBE_API_KEY" in html and "identifiants Twitch" in html
    assert fake.calls == []


def test_home_with_youtube_and_partial_twitch(tmp_path, fake):
    app, client = make(tmp_path, fake, YOUTUBE_API_KEY="k", TWITCH_CLIENT_ID="id")
    html = client.get("/").get_data(as_text=True)
    assert 'data-video="abc123"' in html and "RyzingSol" in html
    assert "TWITCH_CLIENT_SECRET" in html
    client.get("/")
    assert fake.calls.count("https://www.googleapis.com/youtube/v3/search") == 1   # cache 24 h


def test_home_with_twitch(tmp_path, fake):
    app, client = make(tmp_path, fake, TWITCH_CLIENT_ID="id", TWITCH_CLIENT_SECRET="s")
    html = client.get("/").get_data(as_text=True)
    assert html.index("LeroyMain") < html.index("PetitFR") < html.index("BigEN")
    assert 'class="char-tag">Leroy' in html


def test_hub_errors_do_not_break_home(tmp_path, fake):
    fake.fail = True
    app, client = make(tmp_path, fake, YOUTUBE_API_KEY="k", TWITCH_CLIENT_ID="id", TWITCH_CLIENT_SECRET="s")
    r = client.get("/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "quota dépassé" in html and "Lives indisponibles" in html

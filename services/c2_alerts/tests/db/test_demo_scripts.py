"""C2-12: demo scripts (scripts/demo/c2_*.py), the seed IDs and the C2 seed (app/seed.py).

The scripts run against the C2 app in-process (TestClient is an httpx client) with the usual
fakes for C1/C4/C3 readers, so the bodies they send are checked by C2's real API.
"""

from __future__ import annotations

import importlib.util
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from app import seed as c2_seed
from app.api.deps import (
    get_clock,
    get_detection_reader,
    get_house_reader,
    get_session,
    get_settings_reader,
)
from app.gateways.types import Detection
from app.main import create_app
from app.models.orm import AlertRule, AlertType
from app.schemas.evaluate import EvaluateRequest
from app.services.signed_link import ExpiredLink
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests import factories
from tests.factories import BATH, HOUSE_A1, KITCHEN, MAPLE, OAK, make_alert, make_rule
from tests.fakes import FakeDetectionReader, FakeHouseReader, FakeSettingsReader

SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
NOON_LA = datetime(2026, 10, 25, 19, 0, tzinfo=UTC)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


seed_ids = load("seed_ids", SCRIPTS / "seed_ids.py")
fake_detection = load("c2_fake_detection", SCRIPTS / "demo" / "c2_fake_detection.py")
expired_link = load("c2_expired_link", SCRIPTS / "demo" / "c2_expired_link.py")
quiet_hours = load("c2_quiet_hours", SCRIPTS / "demo" / "c2_quiet_hours.py")


# --- seed IDs -------------------------------------------------------------------------------


def test_seed_ids_match_c2_tests_and_seed():
    assert seed_ids.TENANTS["acme"] == factories.TENANT_A
    assert seed_ids.TENANTS["sunrise"] == factories.TENANT_B
    assert seed_ids.house_id("maple") == factories.HOUSE_A1
    assert seed_ids.house_id("OAK") == factories.HOUSE_A2
    assert seed_ids.house_id("pine") == factories.HOUSE_B1
    assert seed_ids.room_id("maple", "Bathroom") == factories.ROOM_A1_BATH
    assert seed_ids.room_id("maple", "Kitchen") == factories.ROOM_A1_KITCHEN
    assert seed_ids.USERS["ops@homeai.test"][0] == factories.STAFF_USER
    assert seed_ids.USERS["owner.maple@acme.test"][0] == factories.OWNER_USER
    assert tuple(seed_ids.TENANTS.values()) == c2_seed.SEED_TENANTS
    assert seed_ids.USERS["ops@homeai.test"][0] == c2_seed.SEED_OPS_USER


def test_seed_ids_are_unique_and_well_formed():
    import uuid

    ids = [
        *seed_ids.TENANTS.values(),
        *(h[0] for h in seed_ids.HOUSES.values()),
        *seed_ids.ROOMS.values(),
        *(u[0] for u in seed_ids.USERS.values()),
        *seed_ids.MAPLE_CONTACTS,
    ]
    assert len(ids) == len(set(ids)) == 2 + 3 + 15 + 5 + 3
    assert all(str(uuid.UUID(i)) == i for i in ids)
    assert seed_ids.house_id("22222222-0000-0000-0000-0000000000b1") == factories.HOUSE_B1
    assert seed_ids.tenant_of(factories.HOUSE_B1) == factories.TENANT_B
    with pytest.raises(KeyError):
        seed_ids.tenant_of("not-a-house")


# --- c2_fake_detection.py -------------------------------------------------------------------


class FakeCollection:
    """``insert_one`` / ``find_one`` of ai_detections, feeding C2's detection reader."""

    def __init__(self, reader: FakeDetectionReader):
        self.docs: dict[str, dict] = {}
        self.reader = reader

    def insert_one(self, doc):
        self.docs[doc["_id"]] = doc
        self.reader.add(Detection.model_validate(doc))

    def find_one(self, query):
        return self.docs.get(query["_id"])


@pytest.fixture
def stored():
    return FakeDetectionReader()


@pytest.fixture
def client(settings, session, stored):
    app = create_app(settings, checks={})
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_house_reader] = lambda: FakeHouseReader(
        [MAPLE, OAK], [BATH, KITCHEN]
    )
    app.dependency_overrides[get_settings_reader] = lambda: FakeSettingsReader()
    app.dependency_overrides[get_detection_reader] = lambda: stored
    app.dependency_overrides[get_clock] = lambda: lambda: NOON_LA
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def c3_token(client, auth_header):
    return auth_header(service_scopes=["alerts:evaluate"])["Authorization"].split()[1]


def test_detection_document_is_what_c2_reads():
    doc = fake_detection.build_detection(
        label="fall_indicator", confidence=0.8123, house="maple", room=None
    )
    detection = Detection.model_validate(doc)
    assert (detection.house_id, detection.room_id) == (HOUSE_A1, factories.ROOM_A1_BATH)
    assert (detection.tenant_id, detection.top_confidence) == (factories.TENANT_A, 0.812)
    assert detection.model.version == "1.0.0"
    EvaluateRequest.model_validate(fake_detection.evaluate_payload(doc))
    assert fake_detection.evaluate_payload(doc)["detected_at"].endswith("Z")


def test_media_id_of_a_real_clip_or_a_made_up_one():
    clip = "77777777-0000-4000-8000-000000000001"
    doc = fake_detection.build_detection(
        label="glass_break", confidence=0.8, house="maple", room=None, media_id=clip
    )
    assert doc["media_id"] == clip
    assert fake_detection.evaluate_payload(doc)["media_id"] == clip
    made_up = fake_detection.build_detection(
        label="glass_break", confidence=0.8, house="maple", room=None
    )
    assert made_up["media_id"] != clip


def test_media_id_option_reaches_c2(client, session, stored, c3_token, capsys):
    make_rule(session, "intrusion")
    clip = "77777777-0000-4000-8000-000000000002"
    detections = FakeCollection(stored)
    args = ["--label", "glass_break", "--media-id", clip.upper(), "--token", c3_token]
    assert fake_detection.main(args, http=client, detections=detections) == 0
    [detection_id] = detections.docs
    assert stored.get(detection_id).media_id == clip  # normalised to the lowercase UUID
    with pytest.raises(SystemExit):  # not a UUID: argparse-style failure before anything runs
        fake_detection.main(
            ["--label", "dog", "--media-id", "clip-1", "--token", "t"], detections=detections
        )


def test_room_uuid_or_unknown_house_passes_through():
    other_house = "22222222-0000-0000-0000-0000000000ff"
    room = "33333333-0000-0000-0000-0000000000ff"
    with pytest.raises(KeyError):  # tenant unknown for a house that is not seeded
        fake_detection.build_detection(label="dog", confidence=0.5, house=other_house, room=room)
    doc = fake_detection.build_detection(label="dog", confidence=0.5, house="oak", room=room)
    assert doc["room_id"] == room


def test_fake_detection_raises_an_alert_then_a_duplicate(client, session, stored, c3_token, capsys):
    make_rule(session, "intrusion")
    detections = FakeCollection(stored)
    args = ["--label", "glass_break", "--conf", "0.78", "--house", "maple", "--room", "Kitchen"]
    code = fake_detection.main([*args, "--token", c3_token], http=client, detections=detections)
    out = capsys.readouterr().out
    assert code == 0
    assert "C2 answered 201" in out and '"decision": "alert"' in out
    [detection_id] = detections.docs

    code = fake_detection.main(
        ["--resend", detection_id, "--token", c3_token], http=client, detections=detections
    )
    assert code == 0
    assert '"duplicate": true' in capsys.readouterr().out


def test_no_matching_rule_is_a_no_alert(client, stored, c3_token, capsys):
    code = fake_detection.main(
        ["--label", "dog", "--conf", "0.9", "--token", c3_token],
        http=client,
        detections=FakeCollection(stored),
    )
    assert code == 0
    assert '"decision": "no_alert"' in capsys.readouterr().out


def test_resend_of_an_unknown_detection(stored, capsys):
    code = fake_detection.main(
        ["--resend", "nope", "--token", "t"], detections=FakeCollection(stored)
    )
    assert code == 1


def test_rejected_by_c2_exits_non_zero(client, stored, capsys):
    code = fake_detection.main(
        ["--label", "dog", "--token", "not-a-jwt"], http=client, detections=FakeCollection(stored)
    )
    assert code == 1
    assert "C2 answered 401" in capsys.readouterr().out


def test_service_token_comes_from_c4():
    seen = {}

    def c4(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.read()
        if request.url.path == "/api/v1/auth/service-token":
            return httpx.Response(200, json={"data": {"token": "tok", "expires_in": 900}})
        return httpx.Response(403, json={"error": {"code": "forbidden"}})

    http = httpx.Client(base_url="http://gw", transport=httpx.MockTransport(c4))
    assert fake_detection.service_token(http, "dev-c3-secret") == "tok"
    assert b'"client_id":"c3-worker"' in seen["body"] and b"alerts:evaluate" in seen["body"]
    with pytest.raises(SystemExit, match="refused"):
        fake_detection.service_token(
            httpx.Client(
                base_url="http://gw",
                transport=httpx.MockTransport(lambda r: httpx.Response(401, json={})),
            ),
            "wrong",
        )


@pytest.mark.parametrize(
    "argv",
    [[], ["--label", "smoke_alarm", "--conf", "1.5"], ["--label", "scream"]],
)
def test_bad_arguments(argv):
    with pytest.raises(SystemExit):
        fake_detection.main(argv, detections=FakeCollection(FakeDetectionReader()))


def test_refuses_in_production_unless_demo_mode(monkeypatch, stored):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert fake_detection.main(["--label", "dog"], detections=object()) == 2
    monkeypatch.setenv("DEMO_MODE", "1")  # the EC2 demo: allowed
    with pytest.raises(SystemExit):  # gets past the guard, then needs a reachable C4
        fake_detection.main(
            ["--label", "dog"],
            detections=FakeCollection(stored),
            http=httpx.Client(
                base_url="http://gw",
                transport=httpx.MockTransport(lambda r: httpx.Response(502, text="<html>")),
            ),
        )


def test_room_names_ignore_case_and_unknown_rooms_are_refused(stored):
    doc = fake_detection.build_detection(
        label="dog", confidence=0.5, house="maple", room="bathROOM"
    )
    assert doc["room_id"] == factories.ROOM_A1_BATH
    with pytest.raises(SystemExit):
        fake_detection.main(
            ["--label", "dog", "--room", "Garage", "--token", "t"],
            detections=FakeCollection(stored),
        )


def test_gateway_html_error_is_printed_not_raised(stored, capsys):
    http = httpx.Client(
        base_url="http://gw",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(502, text="<html>Bad Gateway</html>")
        ),
    )
    code = fake_detection.main(
        ["--label", "dog", "--token", "t"], http=http, detections=FakeCollection(stored)
    )
    assert code == 1
    assert "C2 answered 502: <html>Bad Gateway</html>" in capsys.readouterr().out


def test_document_round_trips_through_mongo():
    """Stored with pymongo as the script does, read back by C2's real Mongo reader."""
    import os

    from app.gateways.detection_gateway import MongoDetectionGateway
    from pymongo import MongoClient

    url = os.environ.get("MONGO_URL_C2_READER")
    if not url:
        pytest.skip("MONGO_URL_C2_READER not set")
    collection = MongoClient(url, tz_aware=True).get_default_database()["demo_script_check"]
    try:
        doc = fake_detection.build_detection(
            label="smoke_alarm", confidence=0.91, house="maple", room=None
        )
        collection.insert_one(dict(doc))
        got = MongoDetectionGateway(collection).get(doc["_id"])
        assert (got.top_label, got.room_id, got.detected_at.tzinfo is not None) == (
            "smoke_alarm",
            seed_ids.room_id("maple", "Kitchen"),
            True,
        )
    finally:
        collection.drop()


# --- c2_expired_link.py ---------------------------------------------------------------------


def test_expired_link_is_rejected_by_the_alert_view(client, settings, session, capsys):
    alert = make_alert(session, make_rule(session, "intrusion"), house_id=HOUSE_A1)
    links = expired_link.links_from_settings(settings)  # same key as the app (C2_ALERT_VIEW_KEY)
    code = expired_link.main(
        ["--alert-id", alert.alert_id, "--contact-id", seed_ids.MAPLE_CONTACTS[0]],
        links=links,
        now=NOON_LA,  # the app's clock in this test
    )
    assert code == 0
    link = capsys.readouterr().out.strip().splitlines()[-1]
    token = link.rsplit("/", 1)[1]
    with pytest.raises(ExpiredLink):
        links.verify(token, now=NOON_LA)
    r = client.get(f"/api/v1/alert-view/{token}")
    assert (r.status_code, r.json()["error"]["code"]) == (401, "token_expired")


def test_newest_alert_and_its_first_contact(session):
    from app.models.orm import Notification

    rule = make_rule(session, "intrusion")
    make_alert(session, rule, triggered_at=NOON_LA - timedelta(hours=1))
    newest = make_alert(session, rule, triggered_at=NOON_LA)
    for contact, priority in ((seed_ids.MAPLE_CONTACTS[1], 2), (seed_ids.MAPLE_CONTACTS[0], 1)):
        session.add(
            Notification(
                alert_id=newest.alert_id,
                contact_id=contact,
                channel="email",
                priority=priority,
                status="sent",
            )
        )
    session.flush()
    assert expired_link.newest_alert_in(session) == (newest.alert_id, seed_ids.MAPLE_CONTACTS[0])


def test_no_alert_falls_back_to_a_made_up_id(settings, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL_C2", "postgresql+psycopg://x@nowhere/db")
    links = expired_link.links_from_settings(settings)
    assert expired_link.main([], links=links, lookup=lambda url: None) == 0
    assert "made-up alert id" in capsys.readouterr().out

    def unreachable(url):
        raise OSError("could not translate host name postgres")

    assert expired_link.main([], links=links, lookup=unreachable) == 0
    assert "cannot read c2.alerts (OSError)" in capsys.readouterr().out
    monkeypatch.delenv("DATABASE_URL_C2")
    assert expired_link.main([], links=links) == 0


def test_key_unavailable(settings, capsys):
    from app.gateways.types import DependencyUnavailableError
    from app.services.signed_link import SignedLinkService

    def no_key():
        raise DependencyUnavailableError("secrets")

    links = SignedLinkService(keys=no_key, public_base_url="x")
    assert expired_link.main(["--alert-id", "a"], links=links) == 1
    assert "cannot read the alert-view key" in capsys.readouterr().out


# --- app/seed.py ----------------------------------------------------------------------------


def defaults(session, tenant):
    return session.scalar(
        select(func.count())
        .select_from(AlertRule)
        .where(AlertRule.tenant_id == tenant, AlertRule.house_id.is_(None))
    )


def test_seed_creates_every_default_rule_once(session):
    types = session.scalar(select(func.count()).select_from(AlertType))
    assert c2_seed.seed_rules(session) == dict.fromkeys(c2_seed.SEED_TENANTS, types)
    assert c2_seed.seed_rules(session) == dict.fromkeys(c2_seed.SEED_TENANTS, 0)
    assert [defaults(session, t) for t in c2_seed.SEED_TENANTS] == [types, types]


def test_seed_main(session, monkeypatch, capsys):
    from homeai_common import db

    @contextmanager
    def scope():
        yield session

    monkeypatch.setattr(db, "configure_db", lambda url: None)
    monkeypatch.setattr(db, "session_scope", scope)
    monkeypatch.setattr(db, "dispose_db", lambda: None)
    assert c2_seed.main(["--tenant", factories.TENANT_B]) == 0
    assert (
        "tenant 11111111-0000-0000-0000-000000000002: 7 default rule(s)" in capsys.readouterr().out
    )
    assert defaults(session, factories.TENANT_A) == 0


def test_seed_never_needs_houses():
    with pytest.raises(RuntimeError, match="does not look up houses"):
        c2_seed._NoHouseLookups().house("x")


# --- demo reset (app/demo_reset.py) ---------------------------------------------------------


def _alert_with_activity(session, rule, house_id: str):
    from app.models.orm import AlertStatusHistory, Notification

    alert = make_alert(session, rule, house_id=house_id)
    session.add_all(
        [
            AlertStatusHistory(
                alert_id=alert.alert_id, to_status="open", actor_id="system", actor_role="system"
            ),
            Notification(alert_id=alert.alert_id, channel="in_app", status="sent"),
            Notification(
                alert_id=alert.alert_id,
                contact_id=seed_ids.MAPLE_CONTACTS[0],
                channel="email",
                priority=1,
                status="sent",
            ),
        ]
    )
    session.flush()
    return alert


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_demo_reset_clears_alerts_and_keeps_rules(session):
    from app.demo_reset import reset_alerts
    from app.models.orm import Alert, AlertStatusHistory, Notification

    rule = make_rule(session, "intrusion")
    _alert_with_activity(session, rule, MAPLE.house_id)
    _alert_with_activity(session, rule, OAK.house_id)
    rules = _count(session, AlertRule)
    assert reset_alerts(session) == {"notifications": 4, "history": 2, "alerts": 2}
    assert [_count(session, m) for m in (Alert, AlertStatusHistory, Notification)] == [0, 0, 0]
    assert _count(session, AlertRule) == rules


def test_demo_reset_one_house(session):
    from app.demo_reset import reset_alerts
    from app.models.orm import Alert, Notification

    rule = make_rule(session, "intrusion")
    _alert_with_activity(session, rule, MAPLE.house_id)
    oak = _alert_with_activity(session, rule, OAK.house_id)
    assert reset_alerts(session, MAPLE.house_id) == {"notifications": 2, "history": 1, "alerts": 1}
    assert session.scalars(select(Alert.alert_id)).all() == [oak.alert_id]
    assert _count(session, Notification) == 2


def test_demo_reset_main(session, settings, monkeypatch, capsys):
    from app import demo_reset
    from app.models.orm import Alert
    from homeai_common import db

    @contextmanager
    def scope():
        yield session

    monkeypatch.setattr(db, "configure_db", lambda url: None)
    monkeypatch.setattr(db, "session_scope", scope)
    monkeypatch.setattr(db, "dispose_db", lambda: None)
    _alert_with_activity(session, make_rule(session, "intrusion"), MAPLE.house_id)

    monkeypatch.setattr(
        demo_reset, "get_settings", lambda: settings.model_copy(update={"demo_mode": False})
    )
    assert demo_reset.main(["--yes"]) == 2
    assert "DEMO_MODE is off" in capsys.readouterr().out

    monkeypatch.setattr(
        demo_reset, "get_settings", lambda: settings.model_copy(update={"demo_mode": True})
    )
    assert demo_reset.main([]) == 0  # without --yes: only counts
    assert "1 alert(s); run again with --yes" in capsys.readouterr().out
    assert _count(session, Alert) == 1
    assert demo_reset.main(["--yes"]) == 0
    assert "deleted 1 alert(s), 1 history row(s), 2 notification(s); rules kept" in (
        capsys.readouterr().out
    )
    assert _count(session, Alert) == 0


# --- quiet hours (scripts/demo/c2_quiet_hours.py; the C4 write itself runs in C4's image) -----


def test_quiet_window_covers_now_in_house_time():
    # 19:07 UTC on 25 Oct is 12:07 in Los Angeles (PDT): quiet from 11:50 for 2 h.
    now = datetime(2026, 10, 25, 19, 7, tzinfo=UTC)
    assert quiet_hours.window_covering(now, "America/Los_Angeles", 2) == ("11:50", "13:50")
    assert quiet_hours.window_covering(now, "America/New_York", 1.5) == ("14:50", "16:20")
    late = datetime(2026, 10, 26, 6, 30, tzinfo=UTC)  # 23:30 in LA: the window wraps midnight
    assert quiet_hours.window_covering(late, "America/Los_Angeles", 2) == ("23:15", "01:15")
    with pytest.raises(ValueError, match="between 0 and 24"):
        quiet_hours.window_covering(now, "America/Los_Angeles", 24)


def test_quiet_window_parse_and_house_timezone():
    assert quiet_hours.parse_window("22:00-07:00") == ("22:00", "07:00")
    with pytest.raises(ValueError, match="HH:MM-HH:MM"):
        quiet_hours.parse_window("10pm-7am")
    assert quiet_hours.house_timezone(seed_ids.house_id("maple")) == "America/Los_Angeles"
    assert quiet_hours.house_timezone(seed_ids.house_id("pine")) == "America/New_York"


def test_quiet_hours_bad_arguments_stop_before_c4(capsys):
    for argv in (["--set", "late"], ["--cover-now", "--hours", "30"], ["--show", "--house", "elm"]):
        with pytest.raises(SystemExit) as exc:
            quiet_hours.main(argv)
        assert exc.value.code == 2
    assert "HH:MM-HH:MM" in capsys.readouterr().err

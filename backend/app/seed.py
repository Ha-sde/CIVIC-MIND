"""Demo data so the public feed, queue and map are populated on first run (SEED_DEMO=true)."""
from datetime import timedelta

from . import ai_engine, services
from .models import Cluster, User, utcnow

CENTER = (16.7050, 74.2433)

REPORTS = [
    # (text, dlat, dlon, address, days_ago, how many extra reporters)
    ("Huge pothole near the school gate, two bikes already fell. Very dangerous.", 0.0040, -0.0030, "Station Road", 6, 3),
    ("Garbage not collected for five days, bad smell in the whole colony.", -0.0060, 0.0050, "Market Lane", 4, 2),
    ("Open manhole next to the hospital entrance, children walk here.", 0.0010, 0.0080, "Hospital Chowk", 1, 1),
    ("Streetlight not working on this lane, very dark at night.", -0.0020, -0.0070, "Lane 4, Rajarampuri", 3, 0),
    ("Water pipe leakage, water flowing on the road since weeks.", 0.0070, 0.0040, "Shivaji Peth", 8, 2),
    ("Live wire hanging low near the bus stop, sparking when it rains.", -0.0035, 0.0020, "Bus Stand Road", 2, 1),
    ("Road caved in near the market, big cracks and uneven surface since months, buses slow down.", 0.0025, -0.0085, "Ring Road", 10, 1),
    ("Stray dogs attacking people in the evening, many residents scared.", -0.0075, -0.0040, "Shahupuri", 5, 0),
]


def seed_demo(db):
    if db.query(Cluster).count() > 0:
        return
    citizen = User(role="citizen", name="Demo Citizen", contact="9000000001")
    official = User(role="official", name="Demo Roads Officer", contact="9000000002",
                    department="Roads & Public Works", ward="Ward 7")
    helpers = [User(role="citizen", name=f"Resident {i}", contact=f"90000001{i:02d}") for i in range(1, 5)]
    db.add_all([citizen, official, *helpers])
    db.flush()

    for idx, (text, dlat, dlon, address, days, extra) in enumerate(REPORTS):
        lat, lon = CENTER[0] + dlat, CENTER[1] + dlon
        ai = ai_engine.analyze_local(text, address)
        _, cluster, _ = services.ingest(db, citizen, text, lat, lon, address, [], ai)
        for k in range(extra):
            services.ingest(db, helpers[k % len(helpers)], text, lat + 0.0003 * (k + 1), lon - 0.0002 * (k + 1), address, [], ai)
        born = utcnow() - timedelta(days=days)
        cluster.created_at = born
        for ev in cluster.events:
            ev.created_at = born
        for comp in cluster.complaints:
            comp.created_at = born
        # walk a few through the lifecycle so every stage is visible
        actor = official
        if idx == 0:
            services.transition(db, cluster, actor, "acknowledged", "Road gang assigned.", target_date=utcnow() + timedelta(days=4))
            services.transition(db, cluster, actor, "in_progress", "Material procured, filling started.", progress=60)
        elif idx == 6:
            services.transition(db, cluster, actor, "acknowledged", "Inspection scheduled.", target_date=utcnow() + timedelta(days=5))
        elif idx == 3:
            cluster.stage = "received"
        elif idx == 7:
            cluster.stage = "completed"
            cluster.progress = 100
            cluster.resolved_at = utcnow() - timedelta(days=1)
            cluster.acknowledged_at = born + timedelta(hours=20)
            services.add_event(db, cluster, "acknowledged", actor, "Animal control team informed.")
            services.add_event(db, cluster, "completed", actor, "Dogs relocated to shelter; area inspected.", 100)
    db.commit()

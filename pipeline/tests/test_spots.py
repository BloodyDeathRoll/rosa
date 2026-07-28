from pathlib import Path

from rosa_pipeline.spots import load_spots, load_spots_file

SPOTS_DIR = Path(__file__).resolve().parents[2] / "data" / "spots"


def test_loads_israel_seed():
    spots = load_spots_file(SPOTS_DIR / "israel.yaml")
    assert len(spots) == 42


def test_beit_yanai_fields():
    spots = load_spots(SPOTS_DIR)
    by = spots["beit-yanai"]
    assert by.name == "Beit Yanai"
    # offshore_direction derived from the local coast tangent (W-facing coast → ~90-120)
    assert 90 <= by.offshore_direction <= 120
    assert by.swell_window == (250, 340)
    assert by.height_coeff == 1.0
    # sampled at its own coord pushed ~0.06° west, not a shared regional point
    assert by.offshore_point == (32.3817, 34.8035)
    assert by.timezone == "Asia/Jerusalem"
    assert by.ideal_size_m == (0.6, 1.5)


def test_per_spot_override_survives_merge():
    spots = load_spots(SPOTS_DIR)
    assert spots["bat-galim"].swell_window == (270, 360)  # bay orientation override


def test_shore_normal_defaults_to_opposite_offshore_wind():
    spots = load_spots(SPOTS_DIR)
    by = spots["beit-yanai"]  # no explicit shore_normal → derived
    assert by.shore_normal == (by.offshore_direction + 180) % 360


def test_shore_normal_override_decouples_from_wind():
    # Arugam Bay: best wind is the SW monsoon (offshore_direction ~245) but the coast faces
    # E/SE - shore_normal is set explicitly and must NOT be offshore_direction + 180.
    spots = load_spots(SPOTS_DIR)
    ab = spots["arugam-bay"]
    assert ab.offshore_direction == 245
    assert ab.shore_normal == 115


def test_per_spot_points_are_distinct():
    # neighbours no longer collapse onto one shared sample point (the identical-forecast bug)
    spots = load_spots(SPOTS_DIR)
    assert spots["hilton"].offshore_point != spots["kontiki"].offshore_point


def test_derived_directions_vary():
    spots = load_spots(SPOTS_DIR)
    dirs = {round(s.offshore_direction) for s in spots.values()}
    assert len(dirs) > 5  # not all pinned to a single default angle


def test_committed_bathy_profiles_match_their_spots():
    """Every committed profile belongs to a live spot AND was cast from where that spot
    sits now. Catches the two ways bathymetry rots: a removed spot leaving an orphan
    file, and a moved pin leaving depths sampled somewhere else."""
    from rosa_pipeline.bathymetry import load_profile

    bathy_dir = SPOTS_DIR / "derived" / "bathy"
    spots = load_spots(SPOTS_DIR)
    # the captured elevations map shares the directory but is not a profile
    ids = sorted(p.stem for p in bathy_dir.glob("*.json") if p.stem != "bathy_elevations")

    orphans = [i for i in ids if i not in spots]
    assert orphans == [], f"profiles with no spot: {orphans}"

    stale = [i for i in ids if not load_profile(i, bathy_dir).matches_spot(spots[i])]
    assert stale == [], f"profiles cast from superseded coordinates - re-cut them: {stale}"


def test_seaward_directions_agree_with_each_other():
    """``shore_normal`` aims the seabed ray the wave physics marches along, while
    ``offshore_bearing`` aims the forecast sample point. Both mean "out to sea", so
    they cannot disagree by much - when they did, the ray ran up the beach and the
    spot forecast collapsed to nothing (Fishermen Bay was 102 deg out, six of nine
    depth samples on dry land, 69% of its hours reading 0.0-0.1 m; 2026-07-29)."""
    import yaml

    from rosa_pipeline.transform import angle_diff

    bad = []
    for path in sorted(SPOTS_DIR.glob("*.yaml")):
        for entry in (yaml.safe_load(path.read_text()) or {}).get("spots", []):
            bearing = entry.get("offshore_bearing")
            if bearing is None:
                continue  # no hand-set sample ray: the derived normal is all there is
            spot = load_spots(SPOTS_DIR)[entry["id"]]
            off = angle_diff(float(bearing), spot.shore_normal)
            if off > 45:
                bad.append(f"{entry['id']} ({off:.0f} deg)")
    assert bad == [], (
        "these spots aim their depth profile and their sample point at different "
        f"seas - set shore_normal and re-cut the profile: {bad}"
    )


def test_committed_profiles_reach_open_water():
    """A profile whose seaward end is dry land is pointing the wrong way: the physics
    would march the swell up a hillside and break it to nothing."""
    from rosa_pipeline.bathymetry import load_profile

    bathy_dir = SPOTS_DIR / "derived" / "bathy"
    spots = load_spots(SPOTS_DIR)
    dry = []
    for sid in sorted(spots):
        profile = load_profile(sid, bathy_dir)
        if profile is not None and profile.offshore_depth_m <= 0:
            dry.append(f"{sid} ({profile.offshore_depth_m:.0f} m)")
    assert dry == [], f"profiles whose deep end is above water: {dry}"


def test_offshore_wind_comes_from_the_land():
    """``offshore_direction`` is where an OFFSHORE wind blows from, so it has to sit on
    the landward side of the beach - within 90 deg of ``shore_normal`` + 180. Past that
    the spot calls an onshore wind offshore and rates blown-out days as clean (Fishermen
    Bay was 102 deg out, calling the SW monsoon offshore; 2026-07-29)."""
    from rosa_pipeline.transform import angle_diff

    spots = load_spots(SPOTS_DIR)
    backwards = [
        f"{sid} ({angle_diff(s.offshore_direction, (s.shore_normal + 180) % 360):.0f} deg)"
        for sid, s in sorted(spots.items())
        if angle_diff(s.offshore_direction, (s.shore_normal + 180) % 360) >= 90
    ]
    assert backwards == [], f"spots whose offshore wind blows in off the sea: {backwards}"

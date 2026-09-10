from conftest import ROOT, load_path_module


def known_families(audit, lines):
    return [event.family for event in audit.analyze_known_noise(lines, 0, len(lines)).events]


def test_advanced_animator_known_probe_requires_complete_loader_signature():
    audit = load_path_module(ROOT / "audit-server-log.py")
    root = "/steamapps/workshop/content/108600/1/mods/Foo/common/media/AnimSets"
    positive = [
        "ERROR: AdvancedAnimator$1.visitFileFailed > Exception thrown",
        f"java.nio.file.NoSuchFileException: {root}",
        " at zombie.core.skinnedmodel.advancedanimation.AdvancedAnimator.searchFolders(AdvancedAnimator.java:1)",
        " at zombie.core.skinnedmodel.advancedanimation.AdvancedAnimator.loadModMedia(AdvancedAnimator.java:2)",
        " at zombie.core.skinnedmodel.advancedanimation.AdvancedAnimator.collectModFiles(AdvancedAnimator.java:3)",
    ]
    analysis = audit.analyze_known_noise(positive, 0, len(positive))
    assert known_families(audit, positive) == ["AdvancedAnimator optional-directory probes"]
    assert audit.find_events(positive, 0, len(positive), analysis.suppressed_line_indexes) == []
    missing_xml = positive.copy()
    missing_xml[1] = f"java.nio.file.NoSuchFileException: {root}/player/actions/foo.xml"
    assert not known_families(audit, missing_xml)
    assert audit.find_events(missing_xml, 0, len(missing_xml))
    xml_error = ["ERROR: AdvancedAnimator > PZXmlParserException for aim_default.xml"]
    assert not known_families(audit, xml_error)
    assert audit.find_events(xml_error, 0, 1)[0].category == "ANIMATION / ASSET"


def test_exact_known_noise_signatures_do_not_hide_near_misses():
    audit = load_path_module(ROOT / "audit-server-log.py")
    positive = [
        'WARN: Script ModelScript.checkMesh > no such mesh "foo/bar|submesh" for X.Y',
        "ERROR: Sound BrokenFences.addBrokenTiles > Missing ThumpSound for breakable object fencing_01_1.",
        "WARN: Moveable Moveable.ReadFromWorldSprite > Warning: Moveable not valid for carpentry_02_1.",
        "WARN: XuiSkin$EntityUiStyle.Load > Could not find icon: Item_Dice",
        "WARN: XuiSkin$EntityUiStyle.LoadComponentInfo > Could not find icon: Item_Note2",
        "ERROR: invalid room metaID #231 in cell 25,33 while reading map_meta.bin.",
        "ERROR: duplicate RoomDef.metaID for room at 10707,9484,0.",
        "WARN: Mannequin zone missing properties in media/maps/Muldraugh, KY/objects.lua",
        "coords: 13583,1299,0",
    ]
    families = known_families(audit, positive)
    assert families == [
        "ModelScript file|submesh validation", "BrokenFences ThumpSound", "Moveable validation",
        "XUI missing-icon resolution", "XUI missing-icon resolution", "Known map/metagrid issues",
        "Known map/metagrid issues", "Known map/metagrid issues",
    ]
    analysis = audit.analyze_known_noise(positive, 0, len(positive))
    assert not audit.find_events(positive, 0, len(positive), analysis.suppressed_line_indexes)

    negatives = [
        'WARN: Script ModelScript.checkMesh > no such mesh "foo/bar" for X.Y',
        'WARN: Script ModelScript.check > no such model "HBVCEF.Primer_Rifle" for HBAC.Primer_Rifle.',
        "ERROR: Sound OtherSystem.add > Missing ThumpSound for breakable object fencing_01_1.",
        "WARN: Moveable exception while loading sprite",
        "WARN: XuiSkin$EntityUiStyle.Load > Could not find LuaWindowClass: Foo",
        "ERROR: invalid room metaID #999 in cell 25,33 while reading map_meta.bin.",
    ]
    assert not known_families(audit, negatives)
    assert len(audit.find_events(negatives, 0, len(negatives))) == len(negatives)


def test_tile_alias_noise_requires_property_and_complete_generation_stack():
    audit = load_path_module(ROOT / "audit-server-log.py")
    positive = [
        "ERROR: IsoPropertyType.lookup > unknown property ladderW",
        " at IsoPropertyType.lookupOrDefaultStr(IsoPropertyType.java:1)",
        " at TilePropertyAliasMap.register(TilePropertyAliasMap.java:2)",
        " at TilePropertyAliasMap.Generate(TilePropertyAliasMap.java:3)",
        " at IsoWorld.GenerateTilePropertyLookupTables(IsoWorld.java:4)",
    ]
    assert known_families(audit, positive) == ["Tile-property alias generation"]
    unrelated = ["ERROR: IsoPropertyType.lookup > unknown property ladderW"]
    assert not known_families(audit, unrelated)
    assert audit.find_events(unrelated, 0, 1)


def test_known_noise_preserves_raw_counts_and_runtime_phase_split(tmp_path):
    audit = load_path_module(ROOT / "audit-server-log.py")
    source = tmp_path / "DebugLog-server.txt"
    source.write_text("fixture\n", encoding="utf-8")
    lines = [
        'WARN: Script ModelScript.checkMesh > no such mesh "foo|bar" for X.Y',
        'WARN: Script ModelScript.check > no such model "HBVCEF.Primer_Rifle" for HBAC.Primer_Rifle.',
        audit.STARTED_MARKER,
        'WARN: Script ModelScript.checkMesh > no such mesh "foo|bar" for X.Y',
    ]
    startup = audit.format_report(source, lines, "startup", 0, 3, 2)
    runtime = audit.format_report(source, lines, "runtime", 2, 4, 2)
    assert "Raw startup counts: ERROR=0, WARN=2, Exception=0" in startup
    assert "Actionable classified events: 1" in startup
    assert "ModelScript file|submesh validation: 1" in startup
    assert "Raw runtime counts: ERROR=0, WARN=1, Exception=0" in runtime
    assert "Actionable classified events: 0" in runtime
    assert "ModelScript file|submesh validation: 1" in runtime

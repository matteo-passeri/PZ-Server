from conftest import FIX_SCRIPTS, fix_context, load_path_module


FIX_NAME = "45-realistic-recipes-b42-skill-names.py"


def recipe(name, lines):
    return "craftRecipe " + name + "\n{\n" + "\n".join(
        "    " + line for line in lines
    ) + "\n}\n"


def bad_recipes():
    return (
        recipe("MakeKitchenTongs", (
            "SkillRequired = MetalWelding:1,",
            "xpAward = Metalworking:5,",
            "category = Metalworking,",
        ))
        + recipe("MakeToolbox", (
            "SkillRequired = Carpentry:1,",
            "category = Carpentry,",
        ))
    )


def target_path(workshop, module, mod_directory=None):
    root = workshop / module.WORKSHOP_ID / "mods" / (mod_directory or module.MOD_ID)
    path = root / module.SCRIPT_RELATIVE
    path.parent.mkdir(parents=True)
    return path


def active_context(workshop, module, log=None):
    ctx = fix_context(workshop, log)
    ctx.update({
        "active_workshop_ids": (module.WORKSHOP_ID,),
        "active_mod_ids": (module.MOD_ID,),
    })
    return ctx


def test_both_known_bad_recipe_lines_are_patched_and_unrelated_content_is_unchanged(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    path = target_path(tmp_path / "workshop", module)
    unrelated = (
        "category = Metalworking,\ncategory = Carpentry,\n"
        "Base.MetalworkingPliers\n"
        "tags[base:metalworkingpliers]\ntags[base:metalworkingpunch]\n"
        "tags[base:metalworkingchisel]\n"
    )
    source = (unrelated + bad_recipes()).replace("\n", "\r\n")
    path.write_bytes(source.encode("utf-8"))
    before_unrelated = unrelated.replace("\n", "\r\n").encode("utf-8")
    messages = []

    assert module.FIX["run"](active_context(tmp_path / "workshop", module, messages.append))
    data = path.read_bytes()
    assert b"xpAward = MetalWelding:5," in data
    assert b"SkillRequired = Woodwork:1," in data
    assert data.startswith(before_unrelated)
    assert messages[-2:] == [
        "Realistic Recipes MakeKitchenTongs: CHANGED.",
        "Realistic Recipes MakeToolbox: CHANGED.",
    ]


def test_already_patched_file_is_untouched_and_reported_per_recipe(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    path = target_path(tmp_path / "workshop", module)
    path.write_text(
        bad_recipes().replace("Metalworking:5", "MetalWelding:5").replace(
            "SkillRequired = Carpentry:1", "SkillRequired = Woodwork:1"
        ),
        encoding="utf-8",
    )
    before = path.read_bytes()
    messages = []

    assert not module.FIX["run"](active_context(tmp_path / "workshop", module, messages.append))
    assert path.read_bytes() == before
    assert messages[-2:] == [
        "Realistic Recipes MakeKitchenTongs: ALREADY PATCHED.",
        "Realistic Recipes MakeToolbox: ALREADY PATCHED.",
    ]


def test_only_kitchen_tongs_bad_is_patched(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    path = target_path(tmp_path / "workshop", module)
    text = bad_recipes().replace("SkillRequired = Carpentry:1", "SkillRequired = Woodwork:1")
    path.write_text(text, encoding="utf-8")

    assert module.FIX["run"](active_context(tmp_path / "workshop", module))
    assert path.read_text(encoding="utf-8") == text.replace("Metalworking:5", "MetalWelding:5")


def test_only_toolbox_bad_is_patched(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    path = target_path(tmp_path / "workshop", module)
    text = bad_recipes().replace("Metalworking:5", "MetalWelding:5")
    path.write_text(text, encoding="utf-8")

    assert module.FIX["run"](active_context(tmp_path / "workshop", module))
    assert path.read_text(encoding="utf-8") == text.replace(
        "SkillRequired = Carpentry:1", "SkillRequired = Woodwork:1"
    )


def test_unexpected_recipe_block_is_untouched_while_other_recipe_can_change(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    path = target_path(tmp_path / "workshop", module)
    text = recipe("MakeKitchenTongs", (
        "SkillRequired = MetalWelding:1,",
        "xpAward = ChangedUpstream:5,",
    )) + recipe("MakeToolbox", (
        "SkillRequired = Carpentry:1,",
        "category = Carpentry,",
    ))
    path.write_text(text, encoding="utf-8")
    messages = []

    assert module.FIX["run"](active_context(tmp_path / "workshop", module, messages.append))
    updated = path.read_text(encoding="utf-8")
    assert "xpAward = ChangedUpstream:5," in updated
    assert "SkillRequired = Woodwork:1," in updated
    assert any("MakeKitchenTongs: SKIPPED / UPSTREAM CHANGED" in message for message in messages)


def test_missing_workshop_mod_or_file_is_a_successful_skip(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    workshop = tmp_path / "workshop"
    messages = []
    ctx = active_context(workshop, module, messages.append)

    assert not module.FIX["run"](ctx)
    (workshop / module.WORKSHOP_ID / "mods" / module.MOD_ID).mkdir(parents=True)
    assert not module.FIX["run"](ctx)
    assert messages == [
        "Realistic Recipes: SKIPPED / TARGET NOT INSTALLED.",
        "Realistic Recipes: SKIPPED / TARGET NOT INSTALLED.",
    ]


def test_second_run_is_idempotent(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    workshop = tmp_path / "workshop"
    path = target_path(workshop, module)
    path.write_text(bad_recipes(), encoding="utf-8")
    ctx = active_context(workshop, module)

    assert module.FIX["run"](ctx)
    before = path.read_bytes()
    assert not module.FIX["run"](ctx)
    assert path.read_bytes() == before


def test_lowercase_mod_root_alias_is_resolved(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    workshop = tmp_path / "workshop"
    path = target_path(workshop, module, "realisticrecipes")
    path.write_text(bad_recipes(), encoding="utf-8")

    assert module.FIX["run"](active_context(workshop, module))
    assert "MetalWelding:5" in path.read_text(encoding="utf-8")


def test_only_target_workshop_and_42_script_can_change(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    workshop = tmp_path / "workshop"
    target = target_path(workshop, module)
    target.write_text(bad_recipes(), encoding="utf-8")
    wrong_workshop = workshop / "9999999999" / "mods" / module.MOD_ID / module.SCRIPT_RELATIVE
    wrong_version = target.parents[4] / "41" / module.SCRIPT_RELATIVE.relative_to("42")
    for path in (wrong_workshop, wrong_version):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(bad_recipes(), encoding="utf-8")
    before = {path: path.read_bytes() for path in (wrong_workshop, wrong_version)}

    assert module.FIX["run"](active_context(workshop, module))
    assert {path: path.read_bytes() for path in before} == before

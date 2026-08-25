import importlib.util
import unittest
from pathlib import Path


GENERATOR = Path(__file__).with_name("generate-mod-list.py")


def load_generator():
    spec = importlib.util.spec_from_file_location("generate_mod_list", GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERATOR_MODULE = load_generator()


class ModLoadOrderTests(unittest.TestCase):
    def test_water_trailer_fix_dependencies_are_ordered(self) -> None:
        original = [
            "rWaterTrailerSemiB42",
            "rWaterTrailerB42",
            "rSemiTruck",
            "82oshkoshM911",
            "tsarslib",
            "damnlib",
        ]

        ordered = GENERATOR_MODULE.reorder_mod_ids(original)
        positions = {mod_id: index for index, mod_id in enumerate(ordered)}

        for dependency in (
            "damnlib",
            "tsarslib",
            "82oshkoshM911",
            "rSemiTruck",
        ):
            self.assertLess(positions[dependency], positions["rWaterTrailerB42"])
        self.assertLess(
            positions["rWaterTrailerB42"],
            positions["rWaterTrailerSemiB42"],
        )

    def test_final_collection_keeps_diagnostics_last_with_error_last(self) -> None:
        collection_order = [
            "ordinary_mod",
            "Linux_Animsets_Marz_Mods",
            "errorMagnifier",
            "AMMS_Standalone",
        ]

        ordered = GENERATOR_MODULE.reorder_mod_ids(collection_order)

        self.assertEqual(
            ordered[-2:],
            ["AMMS_Standalone", "errorMagnifier"],
        )


if __name__ == "__main__":
    unittest.main()

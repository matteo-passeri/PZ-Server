import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("generate-mod-list.py")
SPEC = importlib.util.spec_from_file_location("generate_mod_list", SCRIPT_PATH)
assert SPEC and SPEC.loader
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


class MapCollectionTests(unittest.TestCase):
    def test_map_collection_item_uses_workshop_title_without_map_field(self) -> None:
        self.assertEqual(
            GENERATOR.extract_map_names(
                "Nellis Air Force Base",
                "Thank you for downloading my map!",
                True,
            ),
            ["Nellis Air Force Base"],
        )

    def test_tag_or_description_cannot_classify_a_non_map_collection_item(self) -> None:
        self.assertEqual(
            GENERATOR.extract_map_names(
                "Unrelated Mod",
                "This mod has the Map Steam tag and says map repeatedly.",
                False,
            ),
            [],
        )


class CollectionSelectionTests(unittest.TestCase):
    def test_collection_ids_accept_commas_and_repeated_arguments(self) -> None:
        self.assertEqual(
            GENERATOR.normalize_collection_ids(["100, 200", "300", "200"]),
            ["100", "200", "300"],
        )

    def test_collection_ids_reject_invalid_values(self) -> None:
        with self.assertRaises(ValueError):
            GENERATOR.normalize_collection_ids(["100,not-an-id"])


if __name__ == "__main__":
    unittest.main()

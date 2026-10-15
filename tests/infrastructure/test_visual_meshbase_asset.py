"""Lightweight structure checks for the reviewed, repository-only visual snapshot."""
from __future__ import annotations

import json
from pathlib import Path
import struct
import unittest


ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "assets/xbox_one_s/visual_meshbase"
ABXY = {
    "00_A_Button_VISUAL_UNCALIBRATED", "01_B_Button_VISUAL_UNCALIBRATED",
    "13_X_Button_VISUAL_UNCALIBRATED", "15_Y_Button_VISUAL_UNCALIBRATED",
}


class VisualMeshbaseAssetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = (ASSET / "visual_meshbase.glb").read_bytes()
        magic, version, size = struct.unpack_from("<III", raw)
        if (magic, version, size) != (0x46546C67, 2, len(raw)):
            raise ValueError("invalid snapshot GLB header")
        length, kind = struct.unpack_from("<II", raw, 12)
        if kind != 0x4E4F534A:
            raise ValueError("missing GLB JSON chunk")
        cls.document = json.loads(raw[20:20 + length])
        cls.materials = json.loads((ASSET / "materials.json").read_text())
        cls.manifest = json.loads((ASSET / "manifest.json").read_text())

    def test_two_materials_and_face_groups(self):
        document = self.document
        self.assertEqual([m["alphaMode"] for m in document["materials"]], ["OPAQUE", "BLEND"])
        self.assertEqual(self.materials["materials"], document["materials"])
        counts = [0, 0]
        for mesh in document["meshes"]:
            for primitive in mesh["primitives"]:
                self.assertEqual(primitive.get("mode", 4), 4)
                count = document["accessors"][primitive["indices"]]["count"]
                self.assertEqual(count % 3, 0)
                counts[primitive["material"]] += count // 3
        self.assertEqual(counts, [6590, 256])

    def test_translucent_faces_only_in_abxy(self):
        document = self.document
        translucent = {}
        for node in document["nodes"]:
            for primitive in document["meshes"][node["mesh"]]["primitives"]:
                if document["materials"][primitive["material"]]["alphaMode"] == "BLEND":
                    translucent[node["name"]] = document["accessors"][primitive["indices"]]["count"] // 3
        self.assertEqual(translucent, dict.fromkeys(ABXY, 64))

    def test_constant_opacity_and_source(self):
        opacity = self.materials["constant_opacity"]
        self.assertEqual(opacity["material"], "BLEND")
        self.assertEqual(opacity["value"], 64 / 255)
        self.assertEqual((opacity["numerator"], opacity["denominator"]), (64, 255))
        self.assertTrue(opacity["source"]["description"])
        self.assertTrue(opacity["source"]["evidence"])
        coverage = opacity["source"]["statistics"]
        self.assertEqual((coverage["faces"], coverage["exact_alpha_min"], coverage["exact_alpha_max"]), (256, 64, 64))
        for key in ("usage", "sapien", "sapien_source", "shader_evidence", "mujoco", "gltf"):
            self.assertTrue(opacity[key])
        self.assertIn("specularColorTexture", self.materials["specular_note"])
        self.assertIn("specularTexture", self.materials["specular_note"])

    def test_manifest_required_fields_and_checks(self):
        manifest = self.manifest
        self.assertTrue({"asset_id", "stage", "frozen", "status", "author", "license", "source_url",
                         "derived_from", "alpha_rule", "statistics", "parts", "seam_gate", "checks",
                         "approval", "evidence", "files", "adoption"} <= manifest.keys())
        self.assertTrue(manifest["frozen"])
        self.assertEqual(manifest["status"], "frozen_owner_reviewed")
        self.assertEqual(manifest["license"], "CC-BY-4.0")
        self.assertEqual(manifest["derived_from"]["source"],
                         "assets/xbox_one_s/visual/Xbox_One_S_BatonyRobson_STATIC_VISUAL_UNCALIBRATED.glb")
        self.assertEqual(manifest["derived_from"]["inventory"], "assets/xbox_one_s/visual/inventory.json")
        self.assertEqual((manifest["alpha_rule"]["exact_below"], manifest["alpha_rule"]["halo_below"],
                          manifest["alpha_rule"]["halo_texels"]), (255, 250, 1))
        self.assertEqual((manifest["statistics"]["opaque"], manifest["statistics"]["blend"]), (6590, 256))
        self.assertTrue(manifest["seam_gate"]["passed"])
        self.assertTrue(manifest["seam_gate"]["required_for_every_future_split"])
        self.assertEqual(manifest["seam_gate"]["unsafe_edges"], [])
        self.assertEqual(manifest["seam_gate"]["shared_vertices_cut"], [])
        for name in ("seam_gate", "k1", "k1b", "k2_cycles", "sapien_raster", "mujoco_classic"):
            self.assertTrue(manifest["checks"][name]["passed"], name)
            self.assertTrue(manifest["checks"][name]["evidence"], name)
        for name in manifest["files"]:
            self.assertTrue((ASSET / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()

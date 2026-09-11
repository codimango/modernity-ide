import importlib.util
import unittest

from PIL import Image, ImageDraw


HAS_NUMPY = importlib.util.find_spec("numpy") is not None


@unittest.skipUnless(HAS_NUMPY, "install img2blockbench[semantic-evidence] to render")
class SemanticEvidenceTests(unittest.TestCase):
    def test_front_back_render_is_deterministic_and_respects_face_material(self):
        from semantic_evidence import foreground_mask, render_view

        material = lambda base: {
            "base": base,
            "shade": base,
            "highlight": base,
            "pattern": "solid",
            "pattern_scale": 1,
        }
        spec = {
            "texture": {"density": 2, "palette_size": 4, "gutter": 1, "atlas_size": 64},
            "materials": {
                "red": material("#dd331f"),
                "blue": material("#2255dd"),
            },
            "cubes": [
                {
                    "name": "box",
                    "bone": "root",
                    "center": [0, 0, 0],
                    "size": [4, 5, 3],
                    "rotation": [0, 0, 0],
                    "origin": [0, 0, 0],
                    "role": "test box",
                    "material": "red",
                    "faces": {"south": {"material": "blue"}},
                }
            ],
            "landmarks": [],
        }
        first = render_view(spec, (0, 0, 1), size=(96, 96))
        second = render_view(spec, (0, 0, 1), size=(96, 96))
        back = render_view(spec, (0, 0, -1), size=(96, 96))
        self.assertEqual(first.tobytes(), second.tobytes())
        self.assertIsNotNone(foreground_mask(first).getbbox())
        front_pixel = first.convert("RGB").getpixel((48, 48))
        back_pixel = back.convert("RGB").getpixel((48, 48))
        self.assertGreater(front_pixel[2], front_pixel[0])
        self.assertGreater(back_pixel[0], back_pixel[2])

    def test_alpha_silhouette_preserves_aspect_and_scores_keypoints(self):
        from semantic_evidence import alpha_silhouette_metrics

        reference = Image.new("RGBA", (80, 120), (0, 0, 0, 0))
        ImageDraw.Draw(reference).rectangle((20, 10, 59, 109), fill="#ffffff")
        rendered = Image.new("RGBA", (160, 160), (13, 20, 28, 255))
        ImageDraw.Draw(rendered).rectangle((60, 20, 99, 119), fill="#aa3322")
        metrics = alpha_silhouette_metrics(
            reference,
            rendered,
            reference_keypoints={"eye": (40, 35), "hem": (40, 105)},
            rendered_keypoints={"eye": (80, 45), "hem": (80, 115)},
            target_height=100,
        )
        self.assertEqual(1.0, metrics["iou"])
        self.assertEqual(0.4, metrics["reference_aspect_ratio"])
        self.assertEqual(0.4, metrics["rendered_aspect_ratio"])
        self.assertEqual(2, metrics["keypoints"]["count"])
        self.assertEqual(0.0, metrics["keypoints"]["maximum_error_subject_heights"])

    def test_alpha_silhouette_rejects_opaque_or_mismatched_inputs(self):
        from semantic_evidence import alpha_mask, alpha_silhouette_metrics

        with self.assertRaisesRegex(ValueError, "within 1..255"):
            alpha_mask(Image.new("RGBA", (8, 8), (0, 0, 0, 0)), threshold=0)
        with self.assertRaisesRegex(ValueError, "no transparent pixels"):
            alpha_mask(Image.new("RGB", (8, 8), "white"))
        reference = Image.new("RGBA", (12, 12), (0, 0, 0, 0))
        ImageDraw.Draw(reference).rectangle((2, 2, 9, 9), fill="white")
        rendered = Image.new("RGB", (12, 12), (13, 20, 28))
        ImageDraw.Draw(rendered).rectangle((2, 2, 9, 9), fill="red")
        with self.assertRaisesRegex(ValueError, "names must match"):
            alpha_silhouette_metrics(
                reference,
                rendered,
                reference_keypoints={"a": (3, 3)},
                rendered_keypoints={"b": (3, 3)},
            )


if __name__ == "__main__":
    unittest.main()

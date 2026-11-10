"""Process-only diagnostic overrides; approved defaults are never edited."""
from contextlib import contextmanager
import copy
from dataclasses import replace
from unittest.mock import patch


@contextmanager
def policy(iterations=None, sleep_threshold=None, batch_size=None, batch_library=None):
    import xbox_gamepad_physics.robotwin.loader as loader
    from xbox_gamepad_physics.robotwin import mappings
    original_description = loader._validated_description
    original_preload = mappings.apply_preload
    batch_records = []

    def description(*args, **kwargs):
        result = original_description(*args, **kwargs)
        if iterations is None:
            return result
        options = copy.deepcopy(result.backend_options)
        raw = options["solver_iterations"]
        for point in raw.get("validated_points", [raw]):
            for key, count in zip(("position", "velocity"), iterations):
                point[key]["value"] = count
        return replace(result, backend_options=options)

    def preload(articulation, scene, values):
        original_preload(articulation, scene, values)
        if sleep_threshold is not None:
            articulation.set_sleep_threshold(sleep_threshold)
        if batch_size is not None:
            from experiments.robotwin.station_rtf.batch_api import scene_batch
            before = scene_batch(articulation, batch_library)
            after = scene_batch(articulation, batch_library, batch_size)
            batch_records.append(dict(before=before, after=after))

    with patch.object(loader, "_validated_description", side_effect=description), \
         patch.object(mappings, "apply_preload", side_effect=preload):
        yield batch_records

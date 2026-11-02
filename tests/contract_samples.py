"""Shared valid-record builders for contract tests (KL-1.1+).

All numeric values here are synthetic test constants, not measurements.
"""

SAMPLE_SHA256 = "192ae2b5f280e3957952882c73bb9b03d4db7df2229747d86c88f779149647be"


def valid_provenance():
    return {
        "software_name": "kineticlab-test",
        "software_version": "0.1.0",
        "input_sha256": SAMPLE_SHA256,
        "model_name": None,
        "model_version": None,
        "raw_refs": [],
    }


def valid_artifact_hashes():
    # Synthetic digests (clearly patterned hex, never real bytes).
    return {
        "raw_bob_sha256": "b0" * 32,
        "raw_card_sha256": "c0" * 32,
        "calibration_sha256": "d0" * 32,
        "geometry_report_sha256": "e0" * 32,
    }


def valid_media():
    return {
        "schema_version": "media.v1",
        "source_path": "Smoke/test_3.mp4",
        "source_sha256": "a98a532410a4af2d70921d5adaf1298f151dab8f0e92348f6920cce0be5875ce",
        "container": "mp4",
        "video_stream_count": 1,
        "audio_stream_count": 1,
        "codec": "h264",
        "width": 1024,
        "height": 576,
        "pixel_format": "yuv420p",
        "duration_seconds": 7.872,
        "frame_count": 234,
        "nominal_frame_rate": None,
        "time_base": "1/90000",
        "processing_copy_path": None,
        "processing_copy_sha256": None,
        "valid": True,
        "warnings": [],
        "provenance": valid_provenance(),
    }


def valid_frame(index=0):
    return {
        "schema_version": "frame.v1",
        "frame_index": index,
        "source_frame_index": index,
        "pts_seconds": index * 0.033,
        "duration_seconds": None,
        "decoded_reference": f"decode:{index}",
        "valid": True,
        "warnings": [],
        "provenance": None,
    }


def valid_observation():
    return {
        "schema_version": "observation.v1",
        "frame_index": 0,
        "pts_seconds": 0.0,
        "object_role": "bob",
        "object_id": "bob-1",
        "confidence": 0.9,
        "bbox": [100.0, 200.0, 140.0, 260.0],
        "centroid_x_px": 120.0,
        "centroid_y_px": 230.0,
        "mask_area_px": 1256.0,
        "mask_reference": "masks/bob-1_frame0.bin",
        "valid": True,
        "source": "sam_fixture",
        "warnings": [],
        "provenance": None,
    }


def valid_calibration():
    return {
        "schema_version": "calibration.v1",
        "reference_type": "unknown",
        "reference_dimensions_mm": {"width_mm": 100.0, "height_mm": 50.0},
        "dimension_source": "user_confirmed",
        "observed_corners_px": [[10.0, 10.0], [110.0, 10.0], [110.0, 60.0], [10.0, 60.0]],
        "observed_oriented_dimensions_px": {"long_side_px": 100.0, "short_side_px": 50.0},
        "scale_mm_per_px": 1.0,
        "plane_transform": None,
        "scale_uncertainty_mm_per_px": None,
        "same_plane_assumption": True,
        "camera_fixed_assumption": True,
        "valid": True,
        "warnings": [],
        "provenance": None,
    }


def valid_fit():
    return {
        "schema_version": "fit.v1",
        "model_id": "M1",
        "parameter_names": ["g_over_l"],
        "parameters": {"g_over_l": 15.0},
        "parameter_units": {"g_over_l": "1/s^2"},
        "initial_conditions": {"theta0_rad": 0.3, "omega0_rad_s": 0.0},
        "solver": "RK45",
        "optimizer": "least_squares",
        "converged": True,
        "residual_summary": {"rmse": 0.01, "max_abs": 0.03, "dof": 200},
        "observation_count": 234,
        "rejected_count": 0,
        "fit_uncertainty_method": "none",
        "pivot_length_mm": None,
        "pivot_length_source": "not_provided",
        "g_over_l_per_s2": 15.0,
        "gravity_m_s2": None,
        "warnings": [],
        "provenance": None,
    }


def valid_result(status="success"):
    return {
        "schema_version": "result.v1",
        "status": status,
        "measurement_name": "pendulum_g_over_l",
        "value": 15.0,
        "unit": "1/s^2",
        "interval": None,
        "interval_method": None,
        "identifiable_quantity": {"name": "g/L_eff", "value": 15.0, "unit": "1/s^2"},
        "calibration": valid_calibration(),
        "fit": valid_fit(),
        "quality_metrics": {
            "frames_total": 234,
            "frames_usable": 230,
            "observations_total": 468,
            "observations_valid": 460,
            "calibrated_frames": 230,
        },
        "assumptions": ["camera fixed for the clip"],
        "warnings": [],
        "reject_reasons": [],
        "provenance": {**valid_provenance(),
                       "artifact_hashes": valid_artifact_hashes()},
        "exports": [],
    }
